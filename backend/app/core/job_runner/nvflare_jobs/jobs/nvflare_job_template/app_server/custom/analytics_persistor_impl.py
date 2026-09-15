import os
import json
import math
from datetime import datetime
import traceback

from nvflare.apis.event_type import EventType
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey
from nvflare.app_common.abstract.model import ModelLearnable, make_model_learnable
from nvflare.app_common.app_constant import AppConstants

from duality_nvflare_apis.HEPersistor import HEPersistor
from duality_nvflare_apis.HEAggregator import META_PER_CLIENT_PAYLOADS, KEY_PQC_KEY_PACKAGE
from duality_nvflare_apis.utils import (
    resolve_biomarker_model_paths,
    resolve_encrypted_biomarker_model_paths,
    load_weights_dataframe,
    ENC_BIOMARKER_ALL,
    ENC_BIOMARKER_SCORE_VARIANT,
)
import urllib.request
import urllib.error

import pickle

# Optional secret manager (only used in CLOUD mode)
try:
    from sm import ParticipationSecretsManager
except Exception:
    ParticipationSecretsManager = None  # keep import optional

import faulthandler

faulthandler.enable(all_threads=True)
# dump_traceback_later(120, repeat=True) spams "Timeout (0:02:00)!" (faulthandler, not app timeout).

AUDIT_RECORD_SUBMIT = "/nvflare/jobs/audit/submit"
EMIT_PROGRESS_SUBMIT = "/nvflare/client/emit_progress"

API_BASE = os.getenv("DUALITY_BACKEND_URL")
LOCAL_BUILD = True
if not API_BASE:
    LOCAL_BUILD = False
    API_BASE = "https://api.example.org"
    SECRET_NAME = "example-database-secret"

_AUDIT_RECORD_URL = f"{API_BASE}{AUDIT_RECORD_SUBMIT}"
_EMIT_PROGRESS_URL = f"{API_BASE}{EMIT_PROGRESS_SUBMIT}"

LOG_PATH = os.getenv("DUALITY_NVFLARE_LOG_PATH", "./logs/duality_nvflare.log")

_PRINT_BROKEN = False

def _should_skip_backend_progress_http() -> bool:
    sim = os.getenv("FL_IS_SIMULATOR", "").strip().lower() in ("1", "true", "yes", "on")
    if not sim:
        return False
    if os.getenv("DUALITY_SIM_ENABLE_BACKEND_HTTP", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return True

# --------------------
# Progress code mapping (keep aligned with backend NVFlareClientEmitManager)
# These are persistor/bootstrap steps that can occur before aggregation starts.
# --------------------
PROGRESS_CODE = {
    "VALIDATE_WORKFLOW_ARGS": 1210,
    "LOAD_SCHEMA_METADATA": 1220,
    "VALIDATE_OPENFHE_PARAMS": 1230,
    "SAVED_INTERMEDIATE_ARTIFACT": 1240,
}

BIOMARKER_MODEL_KEYS = frozenset({"cox_lasso", "logistic_reg"})

# Mirror of app.core.mysql.SupportedFunction.MODEL_TYPE_ENCRYPTED (the backend stamps this
# string into workflow workload_args; the NVFlare runtime cannot import app.core).
MODEL_TYPE_ENCRYPTED = "Encrypted"


def _log_line(msg: str):
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"[{ts}] [Analytics Persistor] {msg}"

    global _PRINT_BROKEN

    if not _PRINT_BROKEN:
        try:
            print(line, flush=True)
            return
        except Exception:
            _PRINT_BROKEN = True

    try:
        path = LOG_PATH or "/tmp/nvflare_analytics_persistor.log"
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass



def _is_threshold_samples_workflow(fl_ctx: FLContext) -> bool:
    """True while the sample-count pre-pass (workflow_threshold_samples_*) is running.

    That pass validates every downstream workflow's args just to count rows, so it must
    never require artifacts that only the real computation needs (weights/cutoff CSVs,
    encrypted model ciphertexts). Those are not staged for the pre-pass, and demanding
    them there fails a job whose actual computations are perfectly runnable.
    """
    if fl_ctx is None:
        return False
    return str(fl_ctx.get_prop(ReservedKey.WORKFLOW) or "").startswith("workflow_threshold_samples")


def _normal_csv_column_name(value) -> str:
    return str(value).replace("\ufeff", "").strip().lower()


def _model_type_aliases(model_type) -> set[str]:
    raw = str(model_type or "").strip().lower()
    aliases = {raw} if raw else set()
    if raw == "logistic_reg":
        aliases.update({"logistic", "logisticreg"})
    elif raw == "cox_lasso":
        aliases.update({"cox", "coxlasso", "cox-lasso"})
    if raw:
        aliases.add(raw.replace("_", ""))
        aliases.add(raw.replace("-", "_"))
    return {a for a in aliases if a}


def _select_model_cutoff_row(cutoff_df, model_type=None):
    """Select the relevant row from a cutoff CSV, honoring model_type when present."""
    if cutoff_df.empty:
        raise ValueError("cutoff CSV is empty")

    normalized_columns = {_normal_csv_column_name(col): col for col in cutoff_df.columns}
    model_type_col = normalized_columns.get("model_type")
    aliases = _model_type_aliases(model_type)
    if model_type_col is not None and aliases:
        match_mask = cutoff_df[model_type_col].astype(str).str.strip().str.lower().isin(aliases)
        matching_rows = cutoff_df.loc[match_mask]
        if not matching_rows.empty:
            return matching_rows.iloc[0]

    return cutoff_df.iloc[0]


def _load_named_numeric_cutoff_column(
    cutoff_file_path: str,
    candidate_columns,
    *,
    model_type=None,
    value_label: str = "cutoff value",
) -> float:
    """Load a numeric value from a cutoff CSV by column name rather than position."""
    import pandas as pd

    cutoff_df = pd.read_csv(cutoff_file_path)
    normalized_columns = {_normal_csv_column_name(col): col for col in cutoff_df.columns}
    column = None
    for candidate in candidate_columns:
        column = normalized_columns.get(_normal_csv_column_name(candidate))
        if column is not None:
            break
    if column is None:
        raise ValueError(
            f"{value_label} CSV {cutoff_file_path!r} must contain one of "
            f"{list(candidate_columns)!r}; parsed columns={list(cutoff_df.columns)!r}"
        )

    row = _select_model_cutoff_row(cutoff_df, model_type=model_type)
    raw_value = row[column]
    try:
        return float(raw_value)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"{value_label} in column {column!r} of {cutoff_file_path!r} "
            f"must be numeric, got {raw_value!r}"
        ) from e


def _emit_progress(
    *,
    fl_ctx: FLContext,
    code: int,
    function_name: str | None,
    origin: str = "initiator",
    round_idx: int | None = None,
    timeout: float = 5.0,
) -> None:
    if _should_skip_backend_progress_http():
        return

    if not _EMIT_PROGRESS_URL:
        return

    job_id = fl_ctx.get_job_id() if hasattr(fl_ctx, "get_job_id") else None
    if not job_id:
        return

    scalars: dict[str, float] = {"code": float(code)}
    if round_idx is not None:
        try:
            scalars["round"] = float(int(round_idx))
        except Exception:
            pass

    body: dict[str, object] = {
        "job_id": job_id,
        "origin": origin or "initiator",
        "scalars": scalars,
    }
    if function_name:
        body["function"] = function_name

    if not LOCAL_BUILD:
        if ParticipationSecretsManager is None:
            _log_line("worker: ParticipationSecretsManager not available in CLOUD mode")
        else:
            try:
                sm = ParticipationSecretsManager()
                pw = sm.get_mysql_password(SECRET_NAME)
                body["$pw"] = pw
            except Exception:
                _log_line("worker: failed to fetch secret:\n" + traceback.format_exc())

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        _EMIT_PROGRESS_URL,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Source": "nvflare-client"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        _log_line(f"emit_progress HTTPError {e.code} {getattr(e, 'reason', '')}")
    except urllib.error.URLError as e:
        _log_line(f"emit_progress URLError {getattr(e, 'reason', '')}")
    except Exception:
        _log_line("emit_progress unexpected error:\n" + traceback.format_exc())


def _try_emit_progress(
    *,
    fl_ctx: FLContext,
    code: int,
    function_name: str | None,
    round_idx: int | None,
) -> None:
    try:
        _emit_progress(fl_ctx=fl_ctx, code=code, function_name=function_name, round_idx=round_idx)
    except Exception:
        pass


def log_audit(audit_record: dict, nvflare_job_id: str) -> None:
    if _should_skip_backend_progress_http():
        return
    if not audit_record:
        return

    payload = {
        "nvflare_job_id": nvflare_job_id,
        "security_level": audit_record.get("security_level"),
        "ring_dimension": audit_record.get("ring_dimension"),
        "batch_size": audit_record.get("batch_size"),
        "scale_mod_size": audit_record.get("scale_mod_size"),
        "multiplicative_depth": audit_record.get("multiplicative_depth"),
        "scaling_technique": audit_record.get("scaling_technique"),
        "keyswitch_technique": audit_record.get("keyswitch_technique"),
        "ckks_data_type": audit_record.get("ckks_data_type"),
        "ind_cpa_noise_bits": audit_record.get("ind_cpa_noise_bits"),
    }

    if not LOCAL_BUILD and ParticipationSecretsManager is not None:
        try:
            sm = ParticipationSecretsManager()
            pw = sm.get_mysql_password(SECRET_NAME)
            payload["$pw"] = pw
        except Exception as e:
            _log_line("failed to fetch password for audit submit:\n" + traceback.format_exc())

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _AUDIT_RECORD_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        _log_line(f"audit submit HTTPError {e.code} {getattr(e, 'reason', '')}")
    except urllib.error.URLError as e:
        _log_line(f"audit submit URLError {getattr(e, 'reason', '')}")
    except Exception as e:
        _log_line("audit submit unexpected error:\n" + traceback.format_exc())


# Secure threshold-samples mask parameters, per supported config. The (sigma, B) pairs
# implement the log-DP masking of the margin and MUST NOT change without redoing that
# privacy analysis. The server decrypts sign((sum of clipped counts - (T - 0.5)) * e^(sum z));
# the masked value spans up to margin_max * e^B (~1e14), so the aggregation keeps 2 RNS
# towers (see the +1 spare level in _validate_openfhe_parameters and the towers=2 compress
# in openfhe_manager): a single tower decodes correctly only up to ~2^(73 - scale_mod)
# (~1e6 at scale 53) and silently wraps the sign at random beyond that.
_THRESHOLD_MASK_CONFIGS = (
    # (max_owners, max_threshold, sigma_val, B_val)
    (5, 10, 5.154, 27.14),
    (5, 20, 5.706, 27.70),
    (10, 20, 5.388, 26.91),
)
# Measured decrypt bound of the 2-tower pipeline at scale_mod 53: exact through 1e16,
# decode raises (loudly) from ~1e17. Guarded at 1e15 for a 10x margin; re-measure with
# tests/threshold_mask_probe.py if the CKKS parameterization changes.
_THRESHOLD_SAFE_DECRYPT_BOUND = 1.0e15


def secure_threshold_mask_wrap_guard(scale_mod_size):
    """Decrypt-magnitude bound for the secure threshold pipeline (2-tower compress)."""
    # Scale-aware: the measured 1e15 guard holds at scale_mod 53; each extra scale bit
    # costs one bit of headroom.
    return _THRESHOLD_SAFE_DECRYPT_BOUND * 2.0 ** (53 - scale_mod_size)


def secure_threshold_mask_params(num_owners, min_global_samples, scale_mod_size):
    """(sigma_val, B_val) for the secure threshold mask, validated against CKKS headroom.

    Raises at staging time (never mid-run) if the config is unsupported or if
    margin_max * e^B no longer fits the decrypt bound -- so a parameter or CKKS change
    fails loudly instead of silently wrapping decrypted signs at random. The opposite
    tail (a knife-edge margin of +-0.5 times a near-full negative clip) can sink below
    the decryption noise floor; that is inherent to the mask design and is surfaced at
    runtime by the aggregator's noise-guard warning instead of being blocked here.
    """
    for max_owners, max_threshold, sigma_val, b_val in _THRESHOLD_MASK_CONFIGS:
        if num_owners <= max_owners and min_global_samples <= max_threshold:
            break
    else:
        raise Exception(
            "Secure threshold samples workflow supports only 2 configs: "
            "(num_contributing_data_owners <=5, T<=10) and (num_contributing_data_owners <=10, T<=20)."
        )

    margin_max = num_owners * min_global_samples - (min_global_samples - 0.5)
    wrap_guard = secure_threshold_mask_wrap_guard(scale_mod_size)
    if margin_max * math.exp(b_val) > wrap_guard:
        raise Exception(
            f"Secure threshold mask bound margin_max*e^B = {margin_max * math.exp(b_val):.3e} "
            f"exceeds the CKKS decrypt bound {wrap_guard:.3e} for scale_mod_size={scale_mod_size}; "
            "the decrypted sign could wrap. Reduce B_val or scale_mod_size, or add headroom "
            "(more towers kept at compression)."
        )
    return sigma_val, b_val


class AnalyticsPersistor(HEPersistor):

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(
        self,
        arch = "star",
        is_server_data_owner = False,
        is_server_contributing_to_aggregation = False,
        hide_result_from_server = False,
        leader_client_name: str = "site1",
        exclude_analyzing_clients=None,
        non_contributing_clients=None,
        # OpenFHE parameters
        mult_depth = 0,
        cc_batch_size = None,
        scale_mod_size = 53,
        scaling_technique = "FLEXIBLEAUTO",
        key_switch_technique = "BV",
        ckks_data_type = "REAL",
        generate_mult_keys: bool = False,
        generate_sum_keys: bool = False,
        generate_index_keys: bool = False,
        indices: list = []
    ):
        """Initializes the AnalyticsPersistor.

        This persistor is responsible for loading the initial model and saving the
        final model for statistical analytics workflows. It extends HEPersistor to
        handle homomorphic encryption setup and teardown.

        Args:
            arch: The HE architecture ("star" or "ring").
            is_server_data_owner: Flag indicating if the server is a data owner.
            is_server_contributing_to_aggregation: Flag indicating if the server contributes to aggregation.
            hide_result_from_server: Flag indicating if the server should hide its results from the other parties.
            exclude_analyzing_clients: Client names that must not receive the final stat-analytics result; leader cannot be listed.
            mult_depth: Multiplicative depth for the CKKS HE scheme.
            cc_batch_size: Cryptocontext batch size for the CKKS HE scheme.
            scale_mod_size: Scaling factor bit-length for the CKKS HE scheme.
            scaling_technique: The CKKS scaling technique to use.
            key_switch_technique: The CKKS key switching technique to use.
            ckks_data_type: The data type (e.g., REAL) for CKKS operations.
            generate_mult_keys: Flag to generate multiplication evaluation keys.
            generate_sum_keys: Flag to generate summation evaluation keys.
            generate_index_keys: Flag to generate rotation/index evaluation keys.
            indices: List of indices required for rotation evaluation keys.
        """
        super().__init__(
            arch=arch,
            hide_result_from_server=hide_result_from_server,
            leader_client_name=leader_client_name,
            exclude_analyzing_clients=exclude_analyzing_clients,
            mult_depth=mult_depth,
            cc_batch_size=cc_batch_size,
            scale_mod_size=scale_mod_size,
            scaling_technique=scaling_technique,
            key_switch_technique=key_switch_technique,
            ckks_data_type=ckks_data_type,
            generate_mult_keys=generate_mult_keys,
            generate_sum_keys=generate_sum_keys,
            generate_index_keys=generate_index_keys,
            indices=indices,
        )

        self.is_server_data_owner = is_server_data_owner
        self.is_server_contributing_to_aggregation = is_server_contributing_to_aggregation
        self.hide_result_from_server = hide_result_from_server
        self.non_contributing_clients = list(non_contributing_clients) if non_contributing_clients else []
        self.w_biomarker_risk_scores = None
        self.w_risk_scores_scale_factor = None
        # Split-architecture cross-workflow cache: the score-cache producer computes the
        # neutral (unmasked) rsf-scaled PACKED score ciphertext once and stashes it here,
        # keyed {model_key: {client_name: serialized_ct}} (client_name includes the server's
        # own biomarker_server_risk_key slice). The KM / LCS postprocess consumers pop it and
        # apply their per-slot tail (see UnifiedBiomarkerScorePlan.md). Same persistor-state
        # handoff mechanism as w_biomarker_risk_scores, but carries the ciphertext (no decrypt).
        self.w_biomarker_score_ct_cache = None
        self._horizon_threshold_cache: dict[str, float] = {}
        self._global_schema_cache: dict[str, dict] = {}
        self._pickled_coeffs_cache: dict[str, bytes] = {}

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        if event_type == EventType.START_RUN:
            self.custom_logger.info(f"Job starting. Components: Server (Data Owner = {self.is_server_data_owner}, Contributing to Aggregation = {self.is_server_contributing_to_aggregation}, Hide Result from Server = {self.hide_result_from_server}), and num_clients = {len(fl_ctx.get_engine().get_clients())}.")

    def _inject_pqc_key_packages(self, meta: dict, fl_ctx: FLContext) -> dict:
        """If PQC key packages are stored (after KeyGen with hide_result_from_server), add per-client
        payloads so the first task sends each client only its key package.

        - Only one workflow gets the injection: we clear self.pqc_key_packages after use, so the
          next workflow's load_model sees None and does not inject again.
        - Per-client delivery: we set meta[META_PER_CLIENT_PAYLOADS] = {client_name: {"_extra_data_": {pkg}}},
          i.e. the same structure the aggregator uses with get_shareable_data_asymmetric. The
          workflow (customSAG) resolves this when sending: _effective_shareable_for_client() merges
          base data with that client's _extra_data_, so each client receives only its own key package.
        """
        packages = getattr(self, "pqc_key_packages", None)
        if not self.hide_result_from_server or not packages:
            return meta
        try:
            clients = fl_ctx.get_engine().get_clients()
            client_names = [c.name if hasattr(c, "name") else str(c) for c in clients]
        except Exception:
            return meta
        excl = set(getattr(self, "exclude_analyzing_clients", ()) or ())
        per_client = {
            name: {"_extra_data_": {KEY_PQC_KEY_PACKAGE: pkg}}
            for name, pkg in packages.items()
            if name in client_names and name not in excl
        }
        if not per_client:
            return meta
        self.pqc_key_packages = None  # inject only into this workflow; later workflows get no packages
        meta = dict(meta)
        meta[META_PER_CLIENT_PAYLOADS] = per_client
        return meta

    def _get_broadcast_model_dir(self, fl_ctx: FLContext) -> str:
        return os.path.join(fl_ctx.get_job_id(), "app_server", "custom")

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_model(self, fl_ctx: FLContext) -> ModelLearnable:
        """Loads the initial model at the beginning of a run.

        This method is called by the NVFlare platform to get the starting model.
        It first delegates to the parent `HEPersistor` to handle any HE-specific
        loading (like key generation workflows).

        If not handled by the parent, it prepares a `ModelLearnable` object for
        the analytics workflows. This object contains metadata required by the
        clients, such as the computation type, data column, and scale factor,
        which are passed to the clients to configure their local execution.

        Args:
            fl_ctx: The FLContext provided by the platform.

        Returns:
            A ModelLearnable object containing the initial parameters for the workflow.

        Raises:
            Exception: If the workflow name is not supported.
        """
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
        self.custom_logger.info(f"SEND: to all clients + server: Initial model/parameters.")

        result = super().load_model(fl_ctx)

        if workflow_name == "workflow_KeyGen":
            log_audit(self.openfhe_manager.get_audit_record(), fl_ctx.get_job_id())

        if result is not None:
            return result

        workload_args = fl_ctx.get_prop("workload_args", {})
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)

        computation_type = None
        try:
            if isinstance(workload_args, dict):
                computation_type = workload_args.get("computation_type")
        except Exception:
            computation_type = None

        meta = {"round": 0,
                "is_server_data_owner": self.is_server_data_owner,
                "is_server_contributing_to_aggregation": self.is_server_contributing_to_aggregation,
                 "hide_result_from_server": self.hide_result_from_server,
                 "leader_client_name": self.leader_client_name,
                 "exclude_analyzing_clients": list(self.exclude_analyzing_clients),
                 "non_contributing_clients": self.non_contributing_clients
            }
        if workflow_name == "workflow_threshold_samples_unsecure":
            if workload_args["min_global_samples"] is None or workload_args["min_global_samples"] <= 0:
                raise Exception("min_global_samples must be specified and greater than 0.")
            meta["generated_args"] = self._threshold_generated_args(workload_args["workflows"], fl_ctx)
            depth_required = self._validate_openfhe_parameters(workflow_name, len(fl_ctx.get_engine().get_clients()), workload_args)
            meta["depth_required"] = depth_required
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name == "workflow_threshold_samples_secure":
            if workload_args["min_global_samples"] is None or workload_args["min_global_samples"] <= 0:
                raise Exception("min_global_samples must be specified and greater than 0.")
            meta["generated_args"] = self._threshold_generated_args(workload_args["workflows"], fl_ctx)
            depth_required = self._validate_openfhe_parameters(workflow_name, len(fl_ctx.get_engine().get_clients()), workload_args)
            meta["depth_required"] = depth_required
            num_contributing_data_owners = len(fl_ctx.get_engine().get_clients()) + 1 if (self.is_server_data_owner and self.is_server_contributing_to_aggregation) else len(fl_ctx.get_engine().get_clients())
            sigma_val, B_val = secure_threshold_mask_params(
                num_contributing_data_owners,
                workload_args["min_global_samples"],
                self.openfhe_manager.scale_mod_size,
            )
            meta["generated_args"]["sigma_val"] = sigma_val
            meta["generated_args"]["B_val"] = B_val
            # Carried to the aggregator so its round-1 sign check can flag masked margins
            # that are implausibly large (wrap) or small (noise) for this parameterization.
            meta["mask_wrap_guard"] = secure_threshold_mask_wrap_guard(self.openfhe_manager.scale_mod_size)
            self.custom_logger.info(f"Using sigma_val = {sigma_val} and B_val = {B_val} for generating mask for secure threshold samples workflow.")
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_reference_stat_analytics"):
            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_WORKFLOW_ARGS"], function_name=computation_type, round_idx=round_idx)
            self._validate_workload_args(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["LOAD_SCHEMA_METADATA"], function_name=computation_type, round_idx=round_idx)
            meta["generated_args"] = self.get_meta_from_schema(workload_args, fl_ctx)
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_stat_analytics"):
            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_WORKFLOW_ARGS"], function_name=computation_type, round_idx=round_idx)
            self._validate_workload_args(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["LOAD_SCHEMA_METADATA"], function_name=computation_type, round_idx=round_idx)
            meta["generated_args"] = self.get_meta_from_schema(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_OPENFHE_PARAMS"], function_name=computation_type, round_idx=round_idx)
            depth_required = self._validate_openfhe_parameters(workflow_name, len(fl_ctx.get_engine().get_clients()), workload_args, meta["generated_args"])
            meta["depth_required"] = depth_required
            if workload_args["computation_type"] == "kaplan-meier" and self.w_biomarker_risk_scores is not None:    # Loading risk scores if pre-calculated.
                mk = workload_args.get("model_key")
                if mk is None or str(mk).strip() == "":
                    raise Exception("model_key must be specified for workflow_stat_analytics when using precomputed biomarker risk scores.")
                mk = str(mk).strip()
                if mk not in BIOMARKER_MODEL_KEYS:
                    raise Exception(
                        f"model_key must be one of {sorted(BIOMARKER_MODEL_KEYS)}, got {mk!r}"
                    )
                if not isinstance(self.w_biomarker_risk_scores, dict):
                    raise Exception("Persisted w_biomarker_risk_scores has unexpected shape; expected dict keyed by model_key.")
                scores_for_model = self.w_biomarker_risk_scores.pop(mk, None)
                if scores_for_model is None:
                    raise Exception(
                        f"No encrypted biomarker risk scores persisted for model_key={mk!r}. "
                        "Run workflow_enc_biomarker_disc with this model in model_keys first."
                    )
                ga_update = {"w_biomarker_risk_scores": scores_for_model}
                if isinstance(self.w_risk_scores_scale_factor, dict):
                    sf = self.w_risk_scores_scale_factor.pop(mk, None)
                    if sf is not None:
                        ga_update["risk_scores_scale_factor"] = sf
                if not self.w_biomarker_risk_scores:
                    self.w_biomarker_risk_scores = None
                if isinstance(self.w_risk_scores_scale_factor, dict) and not self.w_risk_scores_scale_factor:
                    self.w_risk_scores_scale_factor = None
                meta["generated_args"].update(ga_update)
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_enc_biomarker_disc") or workflow_name.startswith("workflow_enc_biomarker_score_cache"):
            # Fused discovery/scoring (workflow_enc_biomarker_disc*) AND the split score-cache
            # producer (workflow_enc_biomarker_score_cache) share this setup: validate args,
            # resolve the encrypted model .ct artifacts (biomarker_models_by_key), and resolve
            # the HE depth. The producer computes the dot product + neutral pack exactly like
            # discovery r0; only the depth (5, via the resolver keying on workflow_name) and the
            # server-side caching differ. The postprocess consumer has its own branch (it reads
            # the cached ciphertext instead of running the dot product).
            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_WORKFLOW_ARGS"], function_name=computation_type, round_idx=round_idx)
            self._validate_workload_args(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["LOAD_SCHEMA_METADATA"], function_name=computation_type, round_idx=round_idx)
            meta["generated_args"] = self.get_meta_from_schema(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_OPENFHE_PARAMS"], function_name=computation_type, round_idx=round_idx)
            depth_required = self._validate_openfhe_parameters(workflow_name, len(fl_ctx.get_engine().get_clients()), workload_args, meta["generated_args"])
            meta["depth_required"] = depth_required
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_enc_biomarker_score_postprocess") or workflow_name.startswith("workflow_enc_biomarker_risk_group_postprocess"):
            # Split-architecture postprocess CONSUMER (LCS descale = ..._score_postprocess;
            # KM = ..._risk_group_postprocess). Unlike the producer, it does NOT run the dot
            # product: it reads the packed score the workflow_enc_biomarker_score_cache producer
            # cached on this persistor and applies only its per-slot tail (LCS x inv_rsf ct;
            # KM -cutoff + x rm). Validate args, resolve the encrypted model artifacts (LCS needs
            # the inv_rsf .ct, KM needs the cutoff .ct -- both in the _score upload variant), and
            # resolve depth (5, via the shared resolver). Both are rsf-free (no scale.json).
            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_WORKFLOW_ARGS"], function_name=computation_type, round_idx=round_idx)
            self._validate_workload_args(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["LOAD_SCHEMA_METADATA"], function_name=computation_type, round_idx=round_idx)
            meta["generated_args"] = self.get_meta_from_schema(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_OPENFHE_PARAMS"], function_name=computation_type, round_idx=round_idx)
            depth_required = self._validate_openfhe_parameters(workflow_name, len(fl_ctx.get_engine().get_clients()), workload_args, meta["generated_args"])
            meta["depth_required"] = depth_required

            # Hand the producer's cached score ciphertext to the (server-side) aggregator without
            # broadcasting it to clients. A PRIVATE + STICKY fl_ctx prop lives in the server's
            # shared context manager (same channel as workload_args), so the aggregator reads it in
            # round 0 while it never enters any client shareable -- unlike meta/generated_args, which
            # FullModelShareableGenerator copies to every client. The read is non-destructive here
            # and in the aggregator, so a combined KM+LCS job's two consumers can share one cache.
            if not self.w_biomarker_score_ct_cache:
                raise Exception(
                    "No cached biomarker score ciphertext is available. "
                    "workflow_enc_biomarker_score_cache must run before "
                    "workflow_enc_biomarker_score_postprocess."
                )
            fl_ctx.set_prop(
                "w_biomarker_score_ct_cache", self.w_biomarker_score_ct_cache, private=True, sticky=True
            )
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_biomarker_score_computation"):
            # Open-access clear-text scoring step: each client applies the biomarker model to its covariates and caches the per-patient
            # scores. 
            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_WORKFLOW_ARGS"], function_name=computation_type, round_idx=round_idx)
            self._validate_workload_args(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["LOAD_SCHEMA_METADATA"], function_name=computation_type, round_idx=round_idx)
            meta["generated_args"] = self.get_meta_from_schema(workload_args, fl_ctx)
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_biomarker_lr_fit"):
            # Open-access clear-text fit step (workflow_biomarker_lr_fit_2 also matches this prefix): each client z-normalizes the cached scores
            # with the global (mu, sigma) recovered by the preceding mean-stdev workflow and fits the local 2-parameter logit.
            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["VALIDATE_WORKFLOW_ARGS"], function_name=computation_type, round_idx=round_idx)
            self._validate_workload_args(workload_args, fl_ctx)

            _try_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["LOAD_SCHEMA_METADATA"], function_name=computation_type, round_idx=round_idx)
            meta["generated_args"] = self.get_meta_from_schema(workload_args, fl_ctx)
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        elif workflow_name.startswith("workflow_model_upload"):
            # Pass-through metadata for the executor's _task_model_upload:
            #   - model_keys: which biomarker models to read (e.g. ["cox_lasso", "logistic_reg"])
            #   - cancer_type: filename component for resolve_biomarker_model_paths
            #   - model_type: "Encrypted" vs "Open-access" (selects the executor branch)
            meta["model_keys"]  = list(workload_args.get("model_keys") or [])
            meta["cancer_type"] = str(workload_args.get("cancer_type") or "")
            meta["model_type"]  = str(workload_args.get("model_type") or "")
            if meta["model_type"].strip().lower() == MODEL_TYPE_ENCRYPTED.lower():
                # Encrypted upload: the leader client encrypts the model under the multiparty
                # public key, so it needs the same packing inputs the downstream
                # enc_biomarker_disc consumer uses:
                #   - depth_required: level_val = mult_depth - depth_required must match the
                #     level patient covariates are encrypted at (biomarker depth_required = 4).
                #     This call also asserts KeyGen produced the required mult/index eval keys.
                #   - biomarker_covariates: the global covariate ordering used to align coeffs.
                num_clients = len(fl_ctx.get_engine().get_clients())
                # The uploaded weights/cutoff must be encoded at the SAME level_val
                # (= mult_depth - depth_required) as the covariates the downstream consumer
                # encrypts, so the model-upload depth is resolved via the consumer's resolver.
                # Defaults to the fused discovery workflow (depth 4); the split score-cache
                # chain sets biomarker_depth_workflow="workflow_enc_biomarker_score_cache"
                # to level-match at depth 5. Kept as a workload_arg so this is inert on the
                # existing configs.
                depth_workflow = workload_args.get("biomarker_depth_workflow") or "workflow_enc_biomarker_disc"
                meta["depth_required"] = self._validate_openfhe_parameters(
                    depth_workflow, num_clients, workload_args
                )
                schema_name = workload_args.get("global_schema") or "global_schema.json"
                schema_path = os.path.join(fl_ctx.get_job_id(), "app_server/custom", schema_name)
                if not os.path.exists(schema_path):
                    raise FileNotFoundError(f"Error: The file '{schema_path}' was not found.")
                with open(schema_path, "r") as f:
                    global_schema = json.load(f)
                covs = global_schema.get("metadata", {}).get("biomarker_covariates")
                if covs is None:
                    raise Exception(
                        "Global schema is missing 'biomarker_covariates', needed for encrypted model upload."
                    )
                meta["biomarker_covariates"] = covs
                # for_scoring (LCS): leader encrypts the _score variant (+ ER_threshold sidecar +
                # the encrypted 1/rsf descale). Defaults False, leaving the discovery chain unchanged.
                meta["for_scoring"] = bool(workload_args.get("for_scoring", False))
                # lcs_only: LCS is the sole consumer (no KM). The leader then uploads unbaked
                # (rsf=1) and emits NO 1/rsf, so the LCS postprocess skips the descale. Defaults
                # False (baked), leaving KM-only / combined uploads unchanged.
                meta["lcs_only"] = str(workload_args.get("lcs_only", "")).strip().lower() in ("true", "1")
            # No OpenFHE validation for the open-access path — that is a file-transport round only.
            meta = self._inject_pqc_key_packages(meta, fl_ctx)
            return make_model_learnable(weights={}, meta_props=meta)

        else:
            raise Exception(f"Unsupported workflow {workflow_name}")

    def _validate_openfhe_parameters(self, workflow_name: str, num_clients: int, workload_args: dict, generated_args: dict = None):
        '''Validate openfhe_parameters'''
        self.custom_logger.info("Validating OpenFHE parameters.")
        num_contributing_data_owners = num_clients + 1 if (self.is_server_data_owner and self.is_server_contributing_to_aggregation) else num_clients

        if (workflow_name.startswith("workflow_threshold_samples") or workflow_name.startswith("workflow_stat_analytics")) and self.openfhe_manager.cc is None:
            raise Exception(f"OpenFHE CryptoContext is not initialized for workflow {workflow_name}. Must call workflow_KeyGen first.")

        if workflow_name == "workflow_threshold_samples_unsecure":
            depth_required = 1
            # batch_size_required = len(workload_args["workflows"])

        elif workflow_name == "workflow_threshold_samples_secure":
            # +1 spare level so the masked margin decrypts with 2 RNS towers. At 1 tower the
            # decode bound is ~2^(73 - scale_mod) (~1e6 at scale 53) and margin_max * e^B
            # exceeds it, silently wrapping the decrypted sign at random. With the spare
            # level the bound is ~1e16 (measured), far above the e^B mask range.
            depth_required = math.ceil(math.log2(num_contributing_data_owners+1)) + 1
            # batch_size_required = len(workload_args["workflows"])
            if self.openfhe_manager.generate_mult_keys is False:
                raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")

        elif workflow_name.startswith("workflow_stat_analytics"):
            computation_type = workload_args["computation_type"]
            if computation_type == "mean":
                depth_required = 2
                # batch_size_required = 2
            elif computation_type == "meta-analysis":
                # Inverse-variance meta-analysis is a pure tree-sum + multi-party decrypt. The fused lr_fit (if present) runs on clear-text locally and adds no HE
                # cost. depth_required = 1 carries the additive ciphertext through compression and decryption.
                depth_required = 1
            elif computation_type == "stdev":
                depth_required = 3
                # batch_size_required = 5
                if self.openfhe_manager.generate_mult_keys is False:
                    raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
                if self.openfhe_manager.generate_index_keys is False:
                    raise Exception(f"OpenFHE rotation/index evaluation keys are required but not generated for workflow {workflow_name}.")
                if not set([1, 2]).issubset(set(self.openfhe_manager.indices)):
                    raise Exception(f"OpenFHE rotation/index evaluation keys must include indices [1, 2] for workflow {workflow_name}.")
            elif computation_type == "mean-stdev":
                # Combined mean+stdev: tree-sum (0) -> ctx*ctx' (1) -> rotate+subtract (0) -> mask multiply (1) = depth 3. 
                depth_required = 3
                # batch_size_required = 9
                if self.openfhe_manager.generate_mult_keys is False:
                    raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
                if self.openfhe_manager.generate_index_keys is False:
                    raise Exception(f"OpenFHE rotation/index evaluation keys are required but not generated for workflow {workflow_name}.")
                if not set([1, 2]).issubset(set(self.openfhe_manager.indices)):
                    raise Exception(f"OpenFHE rotation/index evaluation keys must include indices [1, 2] for workflow {workflow_name}.")
            elif computation_type == "chi2":
                depth_required = 4 + math.ceil(math.log2(num_contributing_data_owners)) +1 # +1: Additive mask is way too big; so, had to increase mult_depth by 1.
                # batch_size_required = N_sum # haven't implemented batch_size check since it is complicated to calculate here.
                if self.openfhe_manager.generate_mult_keys is False:
                    raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
                if self.openfhe_manager.generate_sum_keys is False:
                    raise Exception(f"OpenFHE sum evaluation keys are required but not generated for workflow {workflow_name}.")
            elif computation_type == "kaplan-meier":
                ci_type = workload_args.get("CI_type", None)
                if ci_type is not None and str(ci_type).lower() != "none":
                    depth_required = 1
                else:
                    depth_required = 6 + math.ceil(math.log2(num_contributing_data_owners)) + len(generated_args["group_categories"])-1 # TODO: Different requirement if log-rank not computed.
                    # batch_size_required = N_time_bins
                    if self.openfhe_manager.generate_mult_keys is False:
                        raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
            elif computation_type == "t-test":
                depth_required = 5
                # batch_size_required = 24
                if self.openfhe_manager.generate_mult_keys is False:
                    raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
                if self.openfhe_manager.generate_index_keys is False:
                    raise Exception(f"OpenFHE rotation/index evaluation keys are required but not generated for workflow {workflow_name}.")
                if not set([1, 2, 8]).issubset(set(self.openfhe_manager.indices)):
                    raise Exception(f"OpenFHE rotation/index evaluation keys must include indices [1, 2, 8] for workflow {workflow_name}.")

        elif workflow_name.startswith("workflow_enc_biomarker_score_cache") or workflow_name.startswith("workflow_enc_biomarker_score_postprocess") or workflow_name.startswith("workflow_enc_biomarker_risk_group_postprocess"):
            # Split encrypted-score architecture (baked score-cache producer + consumers). The
            # producer caches the packed rsf-scaled score (3 pack multiplies spent); each consumer
            # tail is one more multiply (LCS x 1/rsf descale; KM -cutoff then x rm) -> depth_required
            # 4 -> 5 (3 pack + 1 tail + 1 decrypt margin). See UnifiedBiomarkerScorePlan.md sec 2.
            # Free in KM/combined jobs (mult_depth already ~10, same ring). An LCS-only job
            # (lcs_only) has NO consumer tail multiply -- the model is uploaded unbaked at rsf=1
            # so the LCS descale is skipped -- leaving 3 pack + 1 decrypt margin = 4. That saves
            # one RNS limb (~20%/op on the biomarker steps; same ring 16384). The guard below
            # enforces mult_depth >= depth_required. The lcs_only flag is carried on the
            # model_upload / score_cache / score_postprocess workload_args (set by the stager or
            # the sim config) so both this validation and the model-upload level-match agree.
            depth_required = 5
            if str(workload_args.get("lcs_only", "")).strip().lower() in ("true", "1"):
                depth_required = 4
            if self.openfhe_manager.generate_mult_keys is False:
                raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
            if self.openfhe_manager.generate_index_keys is False:
                raise Exception(f"OpenFHE rotation/index evaluation keys are required but not generated for workflow {workflow_name}.")

        elif workflow_name.startswith("workflow_enc_biomarker_disc"):
            depth_required = 4
            if self.openfhe_manager.generate_mult_keys is False:
                raise Exception(f"OpenFHE multiplication evaluation keys are required but not generated for workflow {workflow_name}.")
            if self.openfhe_manager.generate_index_keys is False:
                raise Exception(f"OpenFHE rotation/index evaluation keys are required but not generated for workflow {workflow_name}.")
            # # Indices check post-poned to stat analysis since we need cov_length for determining needed covs. # TODO: Now that we are getting cov_length from global schema, we can move this check here.
            # required_indices = [2**i for i in range(int(math.log2(cov_length)))] + [-(cov_length-1)]
            # if not set(required_indices).issubset(set(self.openfhe_manager.indices)):
            #     raise Exception(f"OpenFHE rotation/index evaluation keys must include indices {required_indices} for workflow {workflow_name}.")


        if self.openfhe_manager.mult_depth < depth_required:
            raise Exception(f"OpenFHE multiplicative depth {self.openfhe_manager.mult_depth} is less than required depth {depth_required} for workflow {workflow_name}.")
        # if self.openfhe_manager.cc_batch_size is None or self.openfhe_manager.cc_batch_size < batch_size_required:
        #     raise Exception(f"OpenFHE batch size {self.openfhe_manager.cc_batch_size} is less than required batch size {batch_size_required} for workflow {workflow_name}.")
        return depth_required


    # Set of cancer types recognized by the open-access biomarker LCS workflows
    # (biomarker_lr_fit, biomarker_score_computation). Centralized so the
    # standalone and fused validation paths stay in lockstep.
    _BIOMARKER_CANCER_TYPES = frozenset({
        'Glioma', 'Colorectal Cancer', 'Other', 'Breast Carcinoma',
        'Non-Hodgkin Lymphoma', 'Leukemia', 'Bladder Cancer',
        'Esophagogastric Carcinoma', 'Ovarian Cancer', 'Melanoma',
        'Cancer of Unknown Primary', 'Head and Neck Carcinoma',
        'Small Cell Lung Cancer', 'Endometrial Cancer',
        'Non-Small Cell Lung Cancer', 'Soft Tissue Sarcoma',
        'Biliary Cancer', 'Pancreatic Cancer', 'Prostate Cancer',
        'Renal Cell Carcinoma', 'Mesothelioma', 'Thyroid Cancer',
        'Meningothelial Tumor', 'Gastrointestinal Stromal Tumor',
        'Gastrointestinal Neuroendocrine Tumor', 'Skin Cancer, Non-Melanoma',
    })

    def _resolve_horizon_threshold(self, cutoff_file_path: str, computation_label: str, model_type: str | None = None) -> float:
        """Read ER_threshold from the cutoff CSV by column name, caching the parsed value.

        load_model runs every round; the cutoff CSV is invariant for a given
        (model_key, cancer_type) pair across the whole job, so reading it once
        and reusing the cached float avoids a per-round pandas read.
        ``computation_label`` only flows into error messages so the caller
        (standalone biomarker_lr_fit vs fused meta-analysis) is identifiable.
        """
        cache_key = (cutoff_file_path, str(model_type or ""))
        cached = self._horizon_threshold_cache.get(cache_key)
        if cached is not None:
            return cached
        if not os.path.exists(cutoff_file_path):
            raise FileNotFoundError(
                f"Error: The file '{cutoff_file_path}' was not found."
            )
        try:
            horizon = _load_named_numeric_cutoff_column(
                cutoff_file_path,
                ("ER_threshold", "horizon_threshold"),
                model_type=model_type,
                value_label="horizon_threshold (ER_threshold column of cutoff CSV)",
            )
        except (IndexError, KeyError, TypeError, ValueError) as e:
            raise Exception(
                f"horizon_threshold (ER_threshold column of cutoff CSV at "
                f"{cutoff_file_path!r}) must be a numeric value "
                f"for computation_type = '{computation_label}': {e}"
            )
        if horizon <= 0:
            raise Exception(
                f"horizon_threshold (ER_threshold column of cutoff CSV) must be > 0 "
                f"for computation_type = '{computation_label}'"
            )
        self._horizon_threshold_cache[cache_key] = horizon
        return horizon

    def _load_pickled_coeffs(self, scale_coeff_file_path: str) -> bytes:
        """Read the scale_coeff CSV, normalize to the three columns clients
        expect ([covariate, penalized, coef]), and pickle the result. The
        pickled bytes are cached by path so every workflow round can ship the
        same coefficients without re-reading the CSV, rebuilding the DataFrame,
        or re-pickling.
        """
        cached = self._pickled_coeffs_cache.get(scale_coeff_file_path)
        if cached is not None:
            return cached
        coeffs = load_weights_dataframe(scale_coeff_file_path)
        coeffs = coeffs.assign(penalized=True)
        coeffs = coeffs[["covariate", "penalized", "coef"]]
        pickled = pickle.dumps(coeffs)
        self._pickled_coeffs_cache[scale_coeff_file_path] = pickled
        return pickled

    def _schema_km_time_grid_max(self, workload_args: dict, fl_ctx: FLContext):
        """Per-datasource KM grid ceiling from the staged global schema, or None.

        Reads ``metadata.biomarker_km_time_grid_max`` from the job's
        ``global_schema.json``. Absent key/file (e.g. non-biomarker KM jobs or
        legacy schemas) means "keep the configured grid".
        """
        schema_name = workload_args.get("global_schema")
        if not schema_name or fl_ctx is None:
            return None
        schema_path = os.path.join(fl_ctx.get_job_id(), "app_server/custom", schema_name)
        schema = self._global_schema_cache.get(schema_path)
        if schema is None:
            if not os.path.exists(schema_path):
                return None
            with open(schema_path, "r") as f:
                schema = json.load(f)
            self._global_schema_cache[schema_path] = schema
        value = (schema.get("metadata") or {}).get("biomarker_km_time_grid_max")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise Exception(
                f"biomarker_km_time_grid_max in {schema_name} must be numeric; got {value!r}"
            )

    def _validate_and_resolve_lr_fit_args(
        self, workload_args: dict, fl_ctx: FLContext, computation_label: str
    ) -> None:
        """Validate the biomarker_lr_fit args and inject ``horizon_threshold``.

        Shared by the standalone ``biomarker_lr_fit`` validation and the fused
        ``meta-analysis`` validation so both paths apply the same rules.
        ``computation_label`` only flows into error messages so the caller is
        identifiable.
        """
        if workload_args.get("time_column_id") in (None, ""):
            raise Exception(f"time_column_id must be specified for computation_type = '{computation_label}'")
        if workload_args.get("censoring_column_id") in (None, ""):
            raise Exception(f"censoring_column_id must be specified for computation_type = '{computation_label}'")
        if workload_args["time_column_id"] == workload_args["censoring_column_id"]:
            raise Exception(
                "time_column_id and censoring_column_id must refer to distinct columns "
                "(the FHIR extractor returns a duplicate-column DataFrame otherwise)."
            )
        if (
            "cancer_type" not in workload_args
            or workload_args["cancer_type"] not in self._BIOMARKER_CANCER_TYPES
        ):
            raise Exception(f"cancer_type must be specified and valid for computation_type = '{computation_label}'")
        mk = workload_args.get("model_key")
        if mk is None or str(mk).strip() == "":
            raise Exception(f"model_key must be specified for computation_type = '{computation_label}'")
        mk = str(mk).strip()
        if mk not in BIOMARKER_MODEL_KEYS:
            raise Exception(f"model_key must be one of {sorted(BIOMARKER_MODEL_KEYS)}, got {mk!r}")
        # ``horizon_threshold`` is the ``ER_threshold`` column of the cutoff CSV. If the
        # stager already injected it (encrypted chain, where the plaintext CSV is never
        # on the server), honor that value instead of reading the CSV. ER_threshold is a
        # non-secret horizon, so passing it in does not leak model weights.
        existing_horizon = workload_args.get("horizon_threshold")
        if (
            isinstance(existing_horizon, (int, float))
            and not isinstance(existing_horizon, bool)
            and float(existing_horizon) > 0
        ):
            workload_args["horizon_threshold"] = float(existing_horizon)
            return
        # Threshold sample-count never uses horizon_threshold and the cutoff CSV is not
        # staged into the threshold job, so skip the file resolution there.
        if _is_threshold_samples_workflow(fl_ctx):
            return
        # Open-access: resolve the file and inject the parsed value so the client
        # picks it up via set_props_from_init_load.
        resolve_biomarker_model_paths(workload_args, self._get_broadcast_model_dir(fl_ctx))
        workload_args["horizon_threshold"] = self._resolve_horizon_threshold(
            workload_args["cutoff_file_path"], computation_label, model_type=mk
        )

    def _validate_and_resolve_score_computation_args(
        self, workload_args: dict, fl_ctx: FLContext, computation_label: str
    ) -> None:
        """Validate the biomarker_score_computation args and resolve scale_coeff_file_path.

        Shared by the standalone ``biomarker_score_computation`` validation and
        the fused ``mean-stdev`` (over_cached_scores) validation so both paths
        apply the same rules. ``computation_label`` only flows into error
        messages so the caller is identifiable.
        """
        if (
            "cancer_type" not in workload_args
            or workload_args["cancer_type"] not in self._BIOMARKER_CANCER_TYPES
        ):
            raise Exception(f"cancer_type must be specified and valid for computation_type = '{computation_label}'")
        mk = workload_args.get("model_key")
        if mk is None or str(mk).strip() == "":
            raise Exception(f"model_key must be specified for computation_type = '{computation_label}'")
        mk = str(mk).strip()
        if mk not in BIOMARKER_MODEL_KEYS:
            raise Exception(f"model_key must be one of {sorted(BIOMARKER_MODEL_KEYS)}, got {mk!r}")
        # Threshold sample-count doesn't need the scale-coeff file, which isn't staged
        # into the threshold job, so skip the file resolution there.
        if _is_threshold_samples_workflow(fl_ctx):
            return
        # Encrypted chain: the model artifacts are the pre-encrypted ciphertexts from
        # workflow_model_upload and the clients consume the AES-dispersed clear scores
        # cached by the enc score postprocess -- no plaintext weights CSV exists on the
        # server, so skip the file resolution (same gate as kaplan-meier).
        _mt = str(workload_args.get("model_type") or "").strip().lower()
        if _mt == MODEL_TYPE_ENCRYPTED.lower():
            return
        resolve_biomarker_model_paths(workload_args, self._get_broadcast_model_dir(fl_ctx))
        if not os.path.exists(workload_args["scale_coeff_file_path"]):
            raise FileNotFoundError(
                f"Error: The file '{workload_args['scale_coeff_file_path']}' was not found."
            )

    def _validate_workload_args(self, workload_args: dict, fl_ctx: FLContext = None):
        '''Validate statistical analytics arguments'''
        self.custom_logger.info("Validating workflow arguments.")

        _log_line(f"CWD: {os.getcwd()}")
        _log_line(f"__file__: {__file__}")
        try:
            _log_line(f"workload_args.model_key: {workload_args.get('model_key')}")
            _log_line(f"workload_args.model_keys: {workload_args.get('model_keys')}")
            _log_line(f"workload_args.cancer_type: {workload_args.get('cancer_type')}")
        except Exception:
            pass

        if self.is_server_data_owner not in [True, False] or self.is_server_contributing_to_aggregation not in [True, False] or self.hide_result_from_server not in [True, False]:
            raise Exception("is_server_data_owner, is_server_contributing_to_aggregation, and hide_result_from_server must be True or False")
        if not isinstance(getattr(self, "exclude_analyzing_clients", []), (list, tuple)):
            raise Exception("exclude_analyzing_clients must be a list of client name strings")
        if self.leader_client_name in self.exclude_analyzing_clients:
            raise Exception("leader_client_name cannot appear in exclude_analyzing_clients")
        if fl_ctx is not None:
            num_rounds = fl_ctx.get_prop(AppConstants.NUM_ROUNDS)
            workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
            if workflow_name.startswith("workflow_stat_analytics"):
                if self.hide_result_from_server and num_rounds != 4:
                    raise Exception(f"num_rounds must be 4 in workflow_stat_analytics for dispersing AES decrypted payload to clients but got num_rounds={num_rounds}.")
                elif not self.hide_result_from_server and num_rounds != 3:
                    raise Exception(f"num_rounds must be 3 in workflow_stat_analytics but got num_rounds={num_rounds}.")
        if self.is_server_contributing_to_aggregation == True and self.is_server_data_owner == False:
            raise Exception("Server cannot contribute to aggregation if it is not a data owner.")
        if "computation_type" not in workload_args:
            raise Exception("computation_type must be specified")
        _VALID_COMPUTATION_TYPES = [
            "mean", "stdev", "mean-stdev", "meta-analysis", "chi2", "kaplan-meier", "t-test",
            "biomarker_score_computation", "biomarker_lr_fit",
            *ENC_BIOMARKER_ALL,
        ]
        if workload_args["computation_type"] not in _VALID_COMPUTATION_TYPES:
            raise Exception(f"computation_type must be one of {_VALID_COMPUTATION_TYPES}")
        if workload_args["computation_type"] == "mean" and workload_args["data_column_id"] is None:
            raise Exception("data_column_id must be specified for computation_type = 'mean'")
        if workload_args["computation_type"] == "stdev" and (workload_args["data_column_id"] is None or workload_args["std_type"] not in ["population", "sample"]):
            raise Exception("data_column_id must be specified for computation_type = 'stdev' and std_type must be one of ['population', 'sample']")
        if workload_args["computation_type"] == "mean-stdev":
            std_type = workload_args.get("std_type", "sample")
            if std_type not in ["population", "sample"]:
                raise Exception("std_type must be one of ['population', 'sample'] for computation_type = 'mean-stdev'")
            over_cached = bool(workload_args.get("over_cached_scores", False))
            data_col = workload_args.get("data_column_id")
            if over_cached and data_col is not None:
                raise Exception("data_column_id and over_cached_scores are mutually exclusive for computation_type = 'mean-stdev'")
            if not over_cached and data_col is None:
                raise Exception("computation_type = 'mean-stdev' requires either data_column_id or over_cached_scores=True")
        if workload_args["computation_type"] == "chi2" and (workload_args["category_column_1_id"] is None or workload_args["category_column_2_id"] is None):
            raise Exception("category_column_1_id and category_column_2_id must be specified for computation_type = 'chi2'")
        if workload_args["computation_type"] == "kaplan-meier":
            if any(v is None for v in [workload_args["group_column_id"], workload_args["time_column_id"], workload_args["censoring_column_id"], workload_args["time_grid_min"], workload_args["time_grid_step"], workload_args["time_grid_max"]]):
                raise Exception("group_column_id, time_column_id, censoring_column_id, time_grid_min, time_grid_step, and time_grid_max must be specified for computation_type = 'kaplan-meier'")
            # Per-datasource grid CEILING from the staged global_schema: each
            # datasource group declares its own follow-up range, and the
            # effective grid is min(submitted, ceiling). A submitted value below
            # the ceiling is respected (a deliberately coarser/shorter grid is a
            # legitimate choice); a value above it is clipped — grid cells past
            # the data range would be thinly occupied (disclosure risk) and only
            # add masked-aggregation noise. Clipping is never silent: the
            # original is kept in ``time_grid_max_requested`` so the KM
            # postprocess attaches a visible warning to the results.
            _schema_grid_max = self._schema_km_time_grid_max(workload_args, fl_ctx)
            if _schema_grid_max is not None:
                try:
                    _requested_grid_max = float(workload_args["time_grid_max"])
                except (TypeError, ValueError):
                    _requested_grid_max = None
                if _requested_grid_max is None:
                    workload_args["time_grid_max"] = _schema_grid_max
                elif _requested_grid_max > _schema_grid_max:
                    workload_args["time_grid_max_requested"] = _requested_grid_max
                    workload_args["time_grid_max"] = _schema_grid_max
                    self.custom_logger.info(
                        f"kaplan-meier: configured time_grid_max={_requested_grid_max:g} "
                        f"clipped to the datasource ceiling {_schema_grid_max:g} "
                        f"(biomarker_km_time_grid_max)."
                    )
            # Coerce numeric grid fields once, here, and write back. The submission layer (see
            # FUNCTION_DEFAULT_PROPERTIES in SupportedFunction.py) stores these as strings even
            # though FUNCTION_PROPERTY_TYPES declares them float; downstream math (math.ceil, range,
            # comparisons against ints) breaks without coercion. Keep this defensive so any
            # submission path that stringifies them still works.
            for _k in ("time_grid_min", "time_grid_step", "time_grid_max"):
                try:
                    workload_args[_k] = float(workload_args[_k])
                except (TypeError, ValueError):
                    raise Exception(f"{_k} must be numeric; got {workload_args[_k]!r}")
            ci_type = workload_args.get("CI_type", None)
            if ci_type is not None and str(ci_type).lower() != "none" and ci_type not in ["log-log", "linear"]:
                raise Exception("CI_type for computation_type = 'kaplan-meier' must be one of [None, 'None', 'log-log', 'linear'].")
            if ((workload_args["time_grid_min"] >= workload_args["time_grid_max"] or workload_args["time_grid_step"] <= 0) or (workload_args["time_grid_min"] < 0) or (workload_args["time_grid_step"] > (workload_args["time_grid_max"] - workload_args["time_grid_min"]))):
                raise Exception("Invalid values for time_grid_min, time_grid_step, and time_grid_max.")
            if "is_biomarker_discovery" in workload_args and workload_args["is_biomarker_discovery"] == True:
                if "cancer_type" not in workload_args or workload_args["cancer_type"] not in ['Glioma', 'Colorectal Cancer', 'Other', 'Breast Carcinoma', 'Non-Hodgkin Lymphoma', 'Leukemia', 'Bladder Cancer', 'Esophagogastric Carcinoma', 'Ovarian Cancer', 'Melanoma', 'Cancer of Unknown Primary', 'Head and Neck Carcinoma', 'Small Cell Lung Cancer', 'Endometrial Cancer', 'Non-Small Cell Lung Cancer', 'Soft Tissue Sarcoma', 'Biliary Cancer', 'Pancreatic Cancer', 'Prostate Cancer', 'Renal Cell Carcinoma', 'Mesothelioma', 'Thyroid Cancer', 'Meningothelial Tumor', 'Gastrointestinal Stromal Tumor', 'Gastrointestinal Neuroendocrine Tumor', 'Skin Cancer, Non-Melanoma']:
                    raise Exception("cancer_type must be specified and valid for biomarker discovery in computation_type = 'kaplan-meier'")
                # The plaintext-CSV check below is only meaningful for the open-access path.
                _km_model_type = str(workload_args.get("model_type") or "").strip().lower()
                _km_is_encrypted = _km_model_type == MODEL_TYPE_ENCRYPTED.lower()
                if self.w_biomarker_risk_scores is not None or _km_is_encrypted:
                    pass
                else:
                    mk = workload_args.get("model_key")
                    if mk is None or str(mk).strip() == "":
                        raise Exception(
                            "model_key must be specified (with cancer_type), or risk scores must be provided "
                            "from 'workflow_enc_biomarker_disc', for biomarker discovery in computation_type = 'kaplan-meier'"
                        )
                    mk = str(mk).strip()
                    if mk not in BIOMARKER_MODEL_KEYS:
                        raise Exception(
                            f"model_key must be one of {sorted(BIOMARKER_MODEL_KEYS)}, got {mk!r}"
                        )
                    resolve_biomarker_model_paths(workload_args, self._get_broadcast_model_dir(fl_ctx))
                    if not os.path.exists(workload_args["scale_coeff_file_path"]) or not os.path.exists(
                        workload_args["cutoff_file_path"]
                    ):
                        raise FileNotFoundError(
                            f"Error: The file '{workload_args['scale_coeff_file_path']}' or '{workload_args['cutoff_file_path']}' was not found."
                        )
        if workload_args["computation_type"] == "t-test" and (workload_args["data_column_id"] is None or workload_args["category_column_1_id"] is None):
            raise Exception("data_column_id and category_column_1_id must be specified for computation_type = 't-test'")
        if workload_args["computation_type"] in ENC_BIOMARKER_ALL:
            # All encrypted biomarker computations share the same leader-uploaded ciphertext
            # artifacts and .ct path resolution; they differ only in the openfhe tail applied
            # (cutoff subtraction / rm / 1/rsf descale). The split score-cache producer and its
            # postprocess consumers resolve the same "_score" .ct variant as fused LCS scoring.
            if "cancer_type" not in workload_args or workload_args["cancer_type"] not in self._BIOMARKER_CANCER_TYPES:
                raise Exception(f"cancer_type must be specified and valid for computation_type = '{workload_args['computation_type']}'")
            raw_keys = workload_args.get("model_keys")
            if raw_keys is None or not isinstance(raw_keys, (list, tuple)) or len(raw_keys) == 0:
                raise Exception(
                    f"model_keys must be a non-empty list for {workload_args['computation_type']}"
                )
            seen = set()
            model_keys = []
            for x in raw_keys:
                mk = str(x).strip()
                if not mk:
                    raise Exception("model_keys entries must be non-empty strings")
                if mk not in BIOMARKER_MODEL_KEYS:
                    raise Exception(
                        f"Each model_keys entry must be one of {sorted(BIOMARKER_MODEL_KEYS)}, got {mk!r}"
                    )
                if mk not in seen:
                    seen.add(mk)
                    model_keys.append(mk)
            workload_args["model_keys"] = model_keys
            # workflow_enc_biomarker_disc is only ever staged for *encrypted* models, so the
            # model artifacts are the pre-encrypted ciphertexts uploaded during
            # workflow_model_upload (not plaintext CSVs). Resolve those .ct paths and the
            # per-model scale-factor sidecar from the job's app_server/custom dir.
            # Scoring reads the "_score" variant (rsf=1.0), discovery the default
            # (rsf=1/|cutoff|), so the same model_key resolves to non-colliding artifacts.
            _for_scoring = workload_args["computation_type"] in ENC_BIOMARKER_SCORE_VARIANT
            model_dir = self._get_broadcast_model_dir(fl_ctx)
            by_key = {}
            for mk in model_keys:
                wcopy = dict(workload_args)
                wcopy["model_key"] = mk
                resolve_encrypted_biomarker_model_paths(wcopy, model_dir, for_scoring=_for_scoring)
                coeff_ct = wcopy["coeff_ct_file_path"]
                cutoff_ct = wcopy["cutoff_ct_file_path"]
                scale_path = wcopy["scale_factor_file_path"]
                # Scoring does not persist a plaintext rsf sidecar (it descales via the
                # encrypted 1/rsf), so scale.json is only required for discovery.
                required = [coeff_ct, cutoff_ct] if _for_scoring else [coeff_ct, cutoff_ct, scale_path]
                for p in required:
                    if not os.path.exists(p):
                        raise FileNotFoundError(
                            f"Error: Encrypted model artifact '{p}' was not found. "
                            "workflow_model_upload (Encrypted) must run before workflow_enc_biomarker_disc."
                        )
                by_key[mk] = {
                    "coeff_ct_file_path": coeff_ct,
                    "cutoff_ct_file_path": cutoff_ct,
                }
                if not _for_scoring:
                    # Discovery consumes the plaintext rsf (KM dead-band). Scoring must
                    # not read it -- the encrypted-model contract keeps |cutoff| private.
                    with open(scale_path, "r") as f:
                        by_key[mk]["rsf"] = float(json.load(f)["rsf"])
                # Encrypted 1/rsf: consumed by the LCS descale (required for the score path;
                # the openfhe aggregator raises if it is missing there).
                inv_rsf_ct = wcopy.get("inv_rsf_ct_file_path")
                if inv_rsf_ct and os.path.exists(inv_rsf_ct):
                    by_key[mk]["inv_rsf_ct_file_path"] = inv_rsf_ct
            workload_args["biomarker_models_by_key"] = by_key
        if workload_args["computation_type"] == "biomarker_score_computation":
            self._validate_and_resolve_score_computation_args(
                workload_args, fl_ctx, "biomarker_score_computation"
            )
        if workload_args["computation_type"] == "biomarker_lr_fit":
            self._validate_and_resolve_lr_fit_args(workload_args, fl_ctx, "biomarker_lr_fit")
        if (
            workload_args["computation_type"] == "meta-analysis"
            and workload_args.get("time_column_id") is not None
        ):
            self._validate_and_resolve_lr_fit_args(
                workload_args, fl_ctx, "meta-analysis (fused lr_fit)"
            )
        if (
            workload_args["computation_type"] == "mean-stdev"
            and workload_args.get("over_cached_scores") is True
            and workload_args.get("model_key") is not None
        ):
            self._validate_and_resolve_score_computation_args(
                workload_args, fl_ctx, "mean-stdev (fused score_computation)"
            )
        if (
            workload_args["computation_type"] == "mean-stdev"
            and workload_args.get("over_cached_scores") is True
            and workload_args.get("time_column_id") is not None
        ):
            # The shared standardization runs over the ER-labeled rows only, so this
            # workflow consumes the training ER horizon exactly like meta-analysis /
            # biomarker_lr_fit: resolved here from the model_upload cutoff artifact
            # (or honored if the stager pre-injected it on the encrypted chain).
            self._validate_and_resolve_lr_fit_args(
                workload_args, fl_ctx, "mean-stdev (ER-labeled moments)"
            )
        return


    def _threshold_generated_args(self, workflows: dict, fl_ctx: FLContext) -> dict:
        """Validate + build generated_args for every workflow the sample-count pre-pass counts.

        A failure here is a setup error in one downstream workflow, and it aborts the whole job
        before any computation runs. Name the offending workflow in the raised error and leave an
        error.json in its results directory, so the run reports which computation broke instead of
        failing with an unattributed traceback and empty result directories.
        """
        generated_args = {}
        for w_name, w_args in workflows.items():
            try:
                self._validate_workload_args(w_args, fl_ctx)
                generated_args[w_name] = self.get_meta_from_schema(w_args, fl_ctx)
            except Exception as e:
                self._write_workflow_setup_error(fl_ctx, w_name, w_args, e)
                raise Exception(
                    f"Sample-count threshold pre-pass failed while preparing workflow "
                    f"'{w_name}' (computation_type="
                    f"{(w_args or {}).get('computation_type')!r}): {type(e).__name__}: {e}"
                ) from e
        return generated_args

    def _write_workflow_setup_error(
        self, fl_ctx: FLContext, workflow_name: str, workload_args: dict, e: Exception
    ) -> None:
        """Write error.json into ``workflow_name``'s results directory (best effort).

        Mirrors the aggregator's error.json contract so the results retriever can surface a
        setup failure for the affected computation.
        """
        payload = {
            "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "job_id": fl_ctx.get_job_id() if hasattr(fl_ctx, "get_job_id") else None,
            "workflow": workflow_name,
            "stage": f"{fl_ctx.get_prop(ReservedKey.WORKFLOW)}:validate_workload_args",
            "exception_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
        try:
            root = os.path.join(
                "job-results",
                str(fl_ctx.get_job_id()),
                str((workload_args or {}).get("computation_type")),
                str(workflow_name),
            )
            os.makedirs(root, exist_ok=True)
            with open(os.path.join(root, "error.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as write_err:
            _log_line(f"Failed to write error.json for workflow {workflow_name}: {write_err}")

    def get_meta_from_schema(self, workload_args: dict, fl_ctx: FLContext):
        '''Load metadata from the global schema, validate them, and pass them to executor using metadata.'''
        self.custom_logger.info("Loading global schema, validating arguments, and generating workload metadata.")
        # Load the global schema
        schema_path = os.path.join(fl_ctx.get_job_id(), "app_server/custom", workload_args["global_schema"])
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Error: The file '{schema_path}' was not found.")
        with open(schema_path, 'r') as f:
            global_schema = json.load(f)
        # Per-job cache for the parsed schema (invariant across rounds). Populated
        # here so callers/future rounds can reuse it without re-parsing the JSON.
        self._global_schema_cache.setdefault(schema_path, global_schema)

        # Load metadata from the global schema, validate them, and pass them to executor using metadata.
        metadata = {}
        if (
            workload_args["computation_type"] == "mean-stdev"
            and workload_args.get("over_cached_scores") is True
        ):
            metadata.update({"global_min": None, "global_max": None, "global_count": None})
            metadata["std_type"] = workload_args.get("std_type", "sample")
            # Fused score computation is open-access only: on the encrypted chain the
            # clients already hold the AES-dispersed clear scores from the enc score
            # postprocess, and no plaintext weights CSV exists on the server to load
            # coeffs from (validation skipped the path resolution accordingly).
            _mt = str(workload_args.get("model_type") or "").strip().lower()
            if workload_args.get("model_key") is not None and _mt != MODEL_TYPE_ENCRYPTED.lower():
                if global_schema["metadata"].get("biomarker_covariates") is None:
                    raise Exception(
                        "Global schema is missing 'biomarker_covariates', needed for fused "
                        "biomarker_score_computation in computation_type = 'mean-stdev'"
                    )
                metadata.update({"biomarker_covariates": global_schema["metadata"]["biomarker_covariates"]})
                # The sample-count pre-pass only counts the rows this workflow would use, so it
                # needs no coefficients -- and its validation deliberately skipped resolving the
                # weights CSV, so scale_coeff_file_path is not set. Reading it here used to raise
                # KeyError and kill the whole job for any open-access LCS run with a threshold.
                if not _is_threshold_samples_workflow(fl_ctx):
                    if "scale_coeff_file_path" not in workload_args:
                        resolve_biomarker_model_paths(workload_args, self._get_broadcast_model_dir(fl_ctx))
                    metadata.update({"coeffs": self._load_pickled_coeffs(workload_args["scale_coeff_file_path"])})
        elif workload_args["computation_type"] == "meta-analysis":
            metadata.update({"global_min": None, "global_max": None, "global_count": None})
            if workload_args.get("time_column_id") is not None:
                if (
                    workload_args["time_column_id"] not in global_schema["columns"]
                    or global_schema["columns"][workload_args["time_column_id"]]["type"] != "numeric"
                ):
                    raise Exception(
                        f"time_column_id '{workload_args['time_column_id']}' not found in "
                        f"global schema columns or is not of type 'numeric'."
                    )
        elif workload_args["computation_type"] == "mean-stdev":
            if workload_args["data_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["data_column_id"]]["type"] != "numeric":
                raise Exception(f"data_column_id '{workload_args['data_column_id']}' not found in global schema columns or is not of type 'numeric'.")

            global_min = global_schema["columns"][workload_args["data_column_id"]]["global_min"]
            global_max = global_schema["columns"][workload_args["data_column_id"]]["global_max"]
            global_count = global_schema["columns"][workload_args["data_column_id"]]["global_count"]
            if global_min is None or global_max is None or global_count is None:
                raise Exception(f"global_min, global_max, and global_count must be specified in the global schema for data_column_id '{workload_args['data_column_id']}'.")
            if global_min >= global_max or global_count < 0:
                raise Exception(f"Invalid values for global_min, global_max, and global_count in the global schema for data_column_id '{workload_args['data_column_id']}'.")

            metadata.update({"global_min": global_min, "global_max": global_max, "global_count": global_count})
            metadata["std_type"] = workload_args.get("std_type", "sample")
        elif workload_args["computation_type"] == "biomarker_score_computation":
            if global_schema["metadata"].get("biomarker_covariates") is None:
                raise Exception("Global schema is missing 'biomarker_covariates', needed for computation_type = 'biomarker_score_computation'")
            metadata.update({"biomarker_covariates": global_schema["metadata"]["biomarker_covariates"]})
            resolve_biomarker_model_paths(workload_args, self._get_broadcast_model_dir(fl_ctx))
            metadata.update({"coeffs": self._load_pickled_coeffs(workload_args["scale_coeff_file_path"])})
        elif workload_args["computation_type"] == "biomarker_lr_fit":
            if workload_args["time_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["time_column_id"]]["type"] != "numeric":
                raise Exception(f"time_column_id '{workload_args['time_column_id']}' not found in global schema columns or is not of type 'numeric'.")
        if workload_args["computation_type"] in (
            "mean-stdev", "meta-analysis", "biomarker_score_computation", "biomarker_lr_fit"
        ):
            return metadata
        if workload_args["computation_type"] == "mean" or workload_args["computation_type"] == "stdev":
            if workload_args["data_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["data_column_id"]]["type"] != "numeric":
                raise Exception(f"data_column_id '{workload_args['data_column_id']}' not found in global schema columns or is not of type 'numeric'.")

            global_min = global_schema["columns"][workload_args["data_column_id"]]["global_min"]
            global_max = global_schema["columns"][workload_args["data_column_id"]]["global_max"]
            global_count = global_schema["columns"][workload_args["data_column_id"]]["global_count"]
            if global_min is None or global_max is None or global_count is None:
                raise Exception(f"global_min, global_max, and global_count must be specified in the global schema for data_column_id '{workload_args['data_column_id']}'.")
            if global_min >= global_max or global_count < 0:
                raise Exception(f"Invalid values for global_min, global_max, and global_count in the global schema for data_column_id '{workload_args['data_column_id']}'.")

            metadata.update({"global_min": global_min, "global_max": global_max, "global_count": global_count})
        elif workload_args["computation_type"] == "chi2":
            if workload_args["category_column_1_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["category_column_1_id"]]["type"] != "categorical":
                raise Exception(f"category_column_1_id '{workload_args['category_column_1_id']}' not found in global schema columns or is not of type 'categorical'.")
            if workload_args["category_column_2_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["category_column_2_id"]]["type"] != "categorical":
                raise Exception(f"category_column_2_id '{workload_args['category_column_2_id']}' not found in global schema columns or is not of type 'categorical'.")

            column_1_categories = global_schema["columns"][workload_args["category_column_1_id"]]["categories"]
            column_2_categories = global_schema["columns"][workload_args["category_column_2_id"]]["categories"]
            if column_1_categories is None or column_2_categories is None:
                raise Exception(f"categories must be specified in the global schema for category_column_1_id '{workload_args['category_column_1_id']}' and category_column_2_id '{workload_args['category_column_2_id']}'.")

            # if global_schema["metadata"]["global_count_contingency_table"] is None or global_schema["metadata"]["global_count_contingency_table"]["column_id_1"] != workload_args["category_column_1_id"] or global_schema["metadata"]["global_count_contingency_table"]["column_id_2"] != workload_args["category_column_2_id"]:
            #     raise Exception(f"global_count_contingency_table must be specified in the global schema metadata for category_column_1_id '{workload_args['category_column_1_id']}' and category_column_2_id '{workload_args['category_column_2_id']}'.")

            scale_factor = global_schema["metadata"]["global_count_contingency_table"]["value"]
            if scale_factor is None or scale_factor < 0:
                raise Exception(f"Invalid value for scale_factor in the global schema metadata for category_column_1_id '{workload_args['category_column_1_id']}' and category_column_2_id '{workload_args['category_column_2_id']}'.")

            metadata.update({"column_1_categories": column_1_categories, "column_2_categories": column_2_categories, "scale_factor": scale_factor})
        elif workload_args["computation_type"] == "kaplan-meier":
            if workload_args["group_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["group_column_id"]]["type"] != "categorical":
                raise Exception(f"group_column_id '{workload_args['group_column_id']}' not found in global schema columns or is not of type 'categorical'.")
            if workload_args["time_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["time_column_id"]]["type"] != "numeric":
                raise Exception(f"time_column_id '{workload_args['time_column_id']}' not found in global schema columns or is not of type 'numeric'.")
            if workload_args["censoring_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["censoring_column_id"]]["type"] != "boolean":
                raise Exception(f"censoring_column_id '{workload_args['censoring_column_id']}' not found in global schema columns or is not of type 'boolean'.")

            group_categories = global_schema["columns"][workload_args["group_column_id"]]["categories"]
            if group_categories is None:
                raise Exception(f"categories must be specified in the global schema for group_column_id '{workload_args['group_column_id']}'.")

            if global_schema["metadata"]["max_samples_per_time_step"] is None or global_schema["metadata"]["max_samples_per_time_step"]["value"] is None:
                raise Exception(f"max_samples_per_time_step must be specified in the global schema metadata for computation_type = 'kaplan-meier'.")
            if workload_args["time_grid_min"] < global_schema["metadata"]["max_samples_per_time_step"]["time_grid_start"] or (workload_args["time_grid_min"] + workload_args["time_grid_step"]) < (global_schema["metadata"]["max_samples_per_time_step"]["time_grid_start"] + global_schema["metadata"]["max_samples_per_time_step"]["time_grid_step"]):
                raise Exception(f"time_grid_min + time_grid_step must be >= global time_grid_start + time_grid_step in max_samples_per_time_step in the global schema metadata for computation_type = 'kaplan-meier'.")
            max_samples_per_time_step = global_schema["metadata"]["max_samples_per_time_step"]["value"]
            num_contributing_data_owners = len(fl_ctx.get_engine().get_clients()) + 1 if (self.is_server_data_owner and self.is_server_contributing_to_aggregation) else len(fl_ctx.get_engine().get_clients())
            scale_factor = num_contributing_data_owners * len(group_categories) * max_samples_per_time_step

            metadata.update({"group_categories": group_categories, "scale_factor": scale_factor})

            if "is_biomarker_discovery" in workload_args and workload_args["is_biomarker_discovery"] == True:
                import pandas as pd
                # Clear-text Kaplan (e.g. workflow_reference_stat_analytics) always needs coeffs/cutoff from disk.
                # workflow_stat_analytics may use persisted encrypted risk scores for this model_key instead;
                # only then omit coeffs here (injected in load_model).
                # Also skip CSV read when job staged for encrypted biomarker discovery
                # (model_type=Encrypted). workflow_threshold_samples_secure's pre-validation runs
                # this for each downstream KM workflow before workflow_enc_biomarker_disc has had
                # a chance to populate self.w_biomarker_risk_scores; in encrypted mode the eventual
                # risk scores come from the disc workflow and no plaintext CSV exists on disk.
                workflow_name = (fl_ctx.get_prop(ReservedKey.WORKFLOW) or "") if fl_ctx is not None else ""
                use_encrypted_biomarker_scores = False
                if workflow_name.startswith("workflow_stat_analytics") and self.w_biomarker_risk_scores is not None:
                    mk = str(workload_args.get("model_key", "")).strip()
                    if (
                        mk
                        and isinstance(self.w_biomarker_risk_scores, dict)
                        and self.w_biomarker_risk_scores.get(mk) is not None
                    ):
                        use_encrypted_biomarker_scores = True
                if not use_encrypted_biomarker_scores:
                    _mt = str(workload_args.get("model_type") or "").strip().lower()
                    if _mt == MODEL_TYPE_ENCRYPTED.lower():
                        use_encrypted_biomarker_scores = True

                if use_encrypted_biomarker_scores:
                    pass
                else:
                    resolve_biomarker_model_paths(workload_args, self._get_broadcast_model_dir(fl_ctx))
                    coeff_path = workload_args["scale_coeff_file_path"]
                    coeffs = load_weights_dataframe(coeff_path)
                    coeffs = coeffs.assign(penalized=True)
                    coeffs = coeffs[["covariate", "penalized", "coef"]]
                    cutoff_value = _load_named_numeric_cutoff_column(
                        workload_args["cutoff_file_path"],
                        ("cutoff", "cutoff_value", "threshold"),
                        model_type=workload_args.get("model_key"),
                        value_label="biomarker cutoff",
                    )
                    metadata.update({"coeffs": pickle.dumps(coeffs), "cutoff_value": cutoff_value})
                if global_schema["metadata"]["biomarker_covariates"] is None:
                    raise Exception("Global schema is missing 'biomarker_covariates', needed for computation_type = 'kaplan-meier'")
                metadata.update({'biomarker_covariates': global_schema["metadata"]["biomarker_covariates"]})

        elif workload_args["computation_type"] == "t-test":
            if workload_args["data_column_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["data_column_id"]]["type"] != "numeric":
                raise Exception(f"data_column_id '{workload_args['data_column_id']}' not found in global schema columns or is not of type 'numeric'.")
            if workload_args["category_column_1_id"] not in global_schema["columns"] or global_schema["columns"][workload_args["category_column_1_id"]]["type"] != "categorical":
                raise Exception(f"category_column_1_id '{workload_args['category_column_1_id']}' not found in global schema columns or is not of type 'categorical'.")
            if len(global_schema["columns"][workload_args["category_column_1_id"]]["categories"]) != 2:
                raise Exception("t-test only supports 2 categories.")

            global_min = global_schema["columns"][workload_args["data_column_id"]]["global_min"]
            global_max = global_schema["columns"][workload_args["data_column_id"]]["global_max"]
            global_count = global_schema["columns"][workload_args["data_column_id"]]["global_count"]
            if global_min is None or global_max is None or global_count is None:
                raise Exception(f"global_min, global_max, and global_count must be specified in the global schema for data_column_id '{workload_args['data_column_id']}'.")
            if global_min >= global_max or global_count < 0:
                raise Exception(f"Invalid values for global_min, global_max, and global_count in the global schema for data_column_id '{workload_args['data_column_id']}'.")
            column_1_categories = global_schema["columns"][workload_args["category_column_1_id"]]["categories"]
            if column_1_categories is None:
                raise Exception(f"categories must be specified in the global schema for category_column_1_id '{workload_args['category_column_1_id']}'.")

            metadata.update({"global_min": global_min, "global_max": global_max, "global_count": global_count, "column_1_categories": column_1_categories})
        elif workload_args["computation_type"] in ENC_BIOMARKER_ALL:
            # The split-architecture producer (biomarker_enc_score_cache) and its LCS consumer
            # (biomarker_enc_score_postprocess) take the same covariate ordering + model artifacts
            # as the fused discovery/scoring paths; only the server-side tail differs.
            if global_schema["metadata"]["biomarker_covariates"] is None:
                raise Exception(f"Global schema is missing 'biomarker_covariates', needed for computation_type = '{workload_args['computation_type']}'")
            metadata.update({'biomarker_covariates': global_schema["metadata"]["biomarker_covariates"]})
            metadata["model_keys"] = list(workload_args["model_keys"])
            metadata["biomarker_models_by_key"] = workload_args["biomarker_models_by_key"]
            # group_categories = ["low_score", "high_score"]
            # metadata.update({"group_categories": group_categories})
        else:
            raise Exception(f"Unsupported computation_type '{workload_args['computation_type']}'")
        return metadata


    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save_model(self, model: ModelLearnable, fl_ctx: FLContext):
        """Saves data at the end of a workflow.

        This method is called by the NVFlare platform when a run completes.
        It delegates the saving logic to the parent `HEPersistor`, which is
        responsible for persisting any necessary artifacts, such as the final
        homomorphic encryption CryptoContext.

        Args:
            model: The final ModelLearnable object from the run.
            fl_ctx: The FLContext provided by the platform.
        """

        super().save_model(model, fl_ctx)
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
        if workflow_name.startswith("workflow_enc_biomarker_score_cache") and 'w_biomarker_score_ct_cache' in (model.get('weights') or {}):
            # Split-architecture producer: the score-cache workflow (num_rounds=1, no decrypt)
            # emits the neutral packed score ciphertexts in its round-0 weights. Stash them on
            # the persistor so the downstream KM / LCS postprocess workflow can pop and decrypt
            # them (cross-workflow handoff; mirrors w_biomarker_risk_scores below).
            self.w_biomarker_score_ct_cache = model['weights']['w_biomarker_score_ct_cache']
            round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
            try:
                _emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["SAVED_INTERMEDIATE_ARTIFACT"], function_name="biomarker_enc_score_cache", round_idx=round_idx)
            except Exception:
                pass
        if (workflow_name.startswith("workflow_enc_biomarker_disc")
                or workflow_name.startswith("workflow_enc_biomarker_risk_group_postprocess")) \
                and 'w_biomarker_risk_scores' in (model.get('weights') or {}):
            # Fused discovery (workflow_enc_biomarker_disc) AND the split KM postprocess
            # (workflow_enc_biomarker_risk_group_postprocess) persist the server-recovered
            # risk scores for the downstream KM consumer (load_model injects them into the
            # kaplan-meier generated_args). The split KM is terminal at its round 1
            # (num_rounds=2, no client round-2 fuse), so this persistor handoff is its ONLY
            # path to the downstream KM. The LCS score postprocess instead ends on a round-2
            # pass-through with empty weights (clients cache scores locally), so the weights
            # guard skips it here.
            self.w_biomarker_risk_scores = model['weights']['w_biomarker_risk_scores']
            self.w_risk_scores_scale_factor = model['weights'].get('risk_scores_scale_factor')
            round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
            try:
                _emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["SAVED_INTERMEDIATE_ARTIFACT"], function_name="biomarker_enc_risk_group_computation", round_idx=round_idx)
            except Exception:
                pass

    # def delete_model(self):
        # self.w_biomarker_risk_scores = None
