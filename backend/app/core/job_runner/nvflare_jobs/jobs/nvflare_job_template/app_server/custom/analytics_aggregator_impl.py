from datetime import datetime
import os
import sys
import json
import subprocess
from pathlib import Path
import traceback
from typing import Any, Dict, Optional, Tuple, Iterable

from nvflare.apis.event_type import EventType
from nvflare.app_common.app_event_type import AppEventType
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey
from nvflare.apis.shareable import Shareable
from nvflare.apis.dxo import DXO, DataKind
from nvflare.app_common.app_constant import AppConstants
from nvflare.fuel.sec.audit import AuditService

from duality_nvflare_apis.HEAggregator import HEAggregator
from duality_nvflare_apis.stat_analytics import StatAnalyticsManager
from duality_nvflare_apis.utils import (
    resolve_biomarker_model_paths,
    resolve_encrypted_biomarker_model_paths,
    load_weights_dataframe,
    biomarker_server_risk_key,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
)
from duality_nvflare_apis.stat_analytics_event_type import StatAnalyticsEventType
from duality_nvflare_apis.FHIRBaseConfigResolver import FHIRBaseConfigResolver

import pickle

# --- added: stdlib HTTP client for direct server -> backend emits ---
import urllib.request
import urllib.error

# Optional secret manager (only used in CLOUD mode)
try:
    from sm import ParticipationSecretsManager
except Exception:
    ParticipationSecretsManager = None  # keep import optional

import faulthandler

faulthandler.enable(all_threads=True)
# dump_traceback_later(120, repeat=True) spams "Timeout (0:02:00)!" (faulthandler, not app timeout).

FUNCTION_SUBMIT_JOBSTATUS = "/nvflare/client/emit_progress"

API_BASE = os.getenv("DUALITY_BACKEND_URL")
LOCAL_BUILD = True
if not API_BASE:
    LOCAL_BUILD = False
    API_BASE = "https://api.example.org"
    SECRET_NAME = "example-database-secret"

_EMIT_URL = f"{API_BASE}{FUNCTION_SUBMIT_JOBSTATUS}"

LOG_PATH = os.getenv("DUALITY_NVFLARE_LOG_PATH", "./logs/duality_nvflare.log")

def _should_skip_backend_progress_http() -> bool:
    """NVFlare simulator uses a dummy DUALITY_BACKEND_URL; skip POSTs unless explicitly enabled."""
    sim = os.getenv("FL_IS_SIMULATOR", "").strip().lower() in ("1", "true", "yes", "on")
    if not sim:
        return False
    if os.getenv("DUALITY_SIM_ENABLE_BACKEND_HTTP", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return True

_PRINT_BROKEN = False

def _log_line(msg: str):
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"[{ts}] [Analytics Aggregator] {msg}"

    global _PRINT_BROKEN

    # 1) Try printing first; EC2/NVFLARE setups can have a broken stdout.
    if not _PRINT_BROKEN:
        try:
            print(line, flush=True)
            return
        except Exception:
            # stdout is broken; switch to file-only mode for the rest of the run
            _PRINT_BROKEN = True

    # 2) Fallback to file (single attempt; swallow any errors)
    try:
        path = LOG_PATH or "/tmp/nvflare_analytics_aggregator.log"
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # last resort: give up quietly
        pass

# --------------------
# Progress code mapping (keep aligned with client emitter)
# Consolidated to single-shot emits for preprocess, decrypt, postprocess.
# --------------------
PROGRESS_CODE = {
    "JOB_RECEIVED": 100,

    "KEYGEN": 101,

    # sample-count pre-pass (workflow_threshold_samples_*)
    "THRESHOLD_SAMPLES": 102,

    # params parsed from model/DXO
    "PARAMS_LOADED": 300,

    # reference (clear-text) path (not used here, but kept for completeness)
    "REF_PREPROCESS": 410,

    # encrypted path (HE) local prep (server-as-data-owner) – consolidated
    "HE_PREPROCESS": 420,

    # HE encrypt / decrypt (mostly client side; server uses decrypt/postprocess)
    # We keep single code for decrypt to mirror the consolidated scheme.
    "DECRYPT": 500,

    # postprocess (consolidated)
    "POSTPROCESS": 600,

    # artifacts
    "WRITE_RESULTS_JSON": 702,

    # --- explicit aggregation phase messages from initiator/server ---
    "AGGREGATE_BEGIN": 710,          # "Aggregating results from all sources"
    "AGGREGATE_DONE": 711,           # "Aggregation complete; running analysis"
    "WRITE_AGGREGATED_JSON": 712,    # "Writing aggregated results to JSON"

    "THRESHOLD_FAILED": 720,

    # --------------------
    # Encrypted biomarker discovery (workflow_enc_biomarker_disc)
    # Use a dedicated 4-digit namespace (1000-1999) to avoid collisions.
    # --------------------
    "BIO_WORKFLOW_STARTED": 1100,
    "BIO_RECV_CIPHERTEXTS": 1110,
    "BIO_LOAD_FILTERS": 1120,
    "BIO_PREPROCESS": 1130,
    "BIO_VALIDATE_ARTIFACTS": 1140,
    "BIO_AGGREGATE_BEGIN": 1150,
    "BIO_AGGREGATE_DONE": 1160,
    "BIO_RECV_PARTIAL_DECRYPTS": 1170,
    "BIO_DECRYPT": 1180,
    "BIO_SEND_RISK_SCORES": 1190,

    "EXCEPTION_ENCOUNTERED": 900
}


def _server_emit_progress(
    *,
    fl_ctx: FLContext,
    code: int,
    round_idx: Optional[int] = None,
    origin: str = "initiator",
    function_name: Optional[str] = None,
    tag: str = "job_progress",
    timeout: float = 5.0,
) -> None:
    """Lightweight direct POST from server to backend for job progress."""

    if _should_skip_backend_progress_http():
        return

    if not _EMIT_URL:
        return

    job_id = fl_ctx.get_job_id() if hasattr(fl_ctx, "get_job_id") else None
    if not job_id:
        return

    scalars: Dict[str, float] = {"code": float(code)}
    if round_idx is not None:
        try:
            scalars["round"] = float(int(round_idx))
        except Exception:
            pass

    body: Dict[str, object] = {
        "job_id": job_id,
        "origin": origin,
        "scalars": scalars,
    }
    if function_name:
        body["function"] = function_name


    if not LOCAL_BUILD:
        if ParticipationSecretsManager is None:
            _log_line("worker: ParticipationSecretsManager not available in CLOUD mode")
        else:
            try:
                pw = ParticipationSecretsManager.get_mysql_password(SECRET_NAME)  # type: ignore[arg-type]
                body["$pw"] = pw
            except Exception:
                _log_line("worker: failed to fetch secret:\n" + traceback.format_exc())

    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Source": "nvflare-server",
    }

    req = urllib.request.Request(_EMIT_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # drain for connection reuse; keep logs quiet in production
            resp.read()
            _log_line(f"[DEBUG][AnalyticsAggregator] server_emit ok {resp.getcode()} -> {body}")
    except urllib.error.HTTPError as e:
        _log_line(
            f"[DEBUG][AnalyticsAggregator] server_emit HTTPError {e.code}: "
            f"{e.read().decode('utf-8', 'ignore')}"
        )
        pass
    except Exception as e:
        _log_line(f"[DEBUG][AnalyticsAggregator] server_emit failed: {e}")
        pass

class AnalyticsAggregator(HEAggregator):

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(self, filters_path: str = None, stat_data_path: str = None):
        """Initializes the AnalyticsAggregator.

        This aggregator is responsible for handling statistical analytics workflows,
        both in clear text and with homomorphic encryption.
        """
        super().__init__()
        self.analytics_manager = StatAnalyticsManager()
        self.is_server_data_owner = False
        self.is_server_contributing_to_aggregation = False
        self.local_analysed_data = None
        self.filters_path = filters_path
        self.stat_data_path = stat_data_path

        self.min_global_samples = None
        self.flag_failed_threshold_count = None

        self._last_round_recv_size = 0
        self._last_round_send_size = 0

        self.flag_calc_local_result = True  # Flag used to calculate local data only result.
        self.leader_client_name = "site1"  # Set from global model in stat_analytics round 0 when hide_result_from_server.
        self.exclude_analyzing_clients = []  # From global model meta for workflow_stat_analytics

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        """Handles events during the federated learning process.

        This method extends the parent `HEAggregator`'s event handling to include
        dependency checks and installations before training starts.

        Args:
            event_type: The type of event being handled.
            fl_ctx: The FLContext provided by the platform.
        """
        if event_type == EventType.START_RUN:
            # Server acknowledges job receipt (round unknown at START_RUN)
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["JOB_RECEIVED"], round_idx=None, function_name=self.analytics_manager.computation_type)

            # Ensure required packages are installed
            package_status_result = self.check_and_install()
            _log_line(f"[DEBUG] [AnalyticsAggregator] Dependency check result: {package_status_result}")
            if package_status_result["status"] != "ok":
                raise Exception(f"[AnalyticsAggregator] Fail: Dependencies missing and could not be installed. {package_status_result['message']}")
        elif event_type == EventType.START_WORKFLOW:
            self.custom_logger.info(f"-------------------------------------- Workflow: {fl_ctx.get_prop(ReservedKey.WORKFLOW)} Started --------------------------------------")
            self.hide_result_from_server = None
            self.leader_client_name = "site1"
            self.exclude_analyzing_clients = []
            self.local_analysed_data = None
            self.local_list_enc_result = None
            self._last_round_recv_size = 0
            self._last_round_send_size = 0
        elif event_type == EventType.END_WORKFLOW:
            self.custom_logger.info(f"-------------------------------------- Workflow: {fl_ctx.get_prop(ReservedKey.WORKFLOW)} Ended --------------------------------------")
        elif event_type == AppEventType.BEFORE_AGGREGATION:
            self.custom_logger.info(f"----------------- Round: {fl_ctx.get_prop(AppConstants.CURRENT_ROUND)} -----------------")
            self.custom_logger.info(f"RECV: size = {(fl_ctx.get_prop('__prof_payload_in_acc', 0) - self._last_round_recv_size)} Bytes.")
            self._last_round_recv_size = fl_ctx.get_prop('__prof_payload_in_acc', 0)
        elif event_type == AppEventType.AFTER_AGGREGATION:
            self.custom_logger.info(f"SEND: size = {(fl_ctx.get_prop('__prof_payload_out_acc', 0) - self._last_round_send_size)} Bytes.")
            self._last_round_send_size = fl_ctx.get_prop('__prof_payload_out_acc', 0)

    def check_and_install(self):
        REQUIRED_PACKAGES = [
            "matplotlib",
            "numpy",
            "openfhe",
            "pandas",
            "scipy"
        ]

        missing = []
        for pkg in REQUIRED_PACKAGES:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)

        if not missing:
            return {"status": "ok", "message": "All dependencies installed"}

        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            return {"status": "ok", "message": f"Installed missing packages: {missing}"}
        except Exception as e:
            return {"status": "fail", "message": f"Could not install: {missing} | {e}"}

    def _resolve_filters_path(self, fl_ctx: FLContext) -> Tuple[Optional[Path], Iterable[Path]]:
        # Try to resolve the filters.json file location based on context and defaults
        rel = Path(self.filters_path)
        if rel.is_absolute() and rel.exists():
            return rel, []
        app_root_ctx = fl_ctx.get_prop("app_root", None)
        job_id = fl_ctx.get_prop("job_id", None)
        site_name = fl_ctx.get_prop("site_name", None)
        bases: list[Path] = []
        if app_root_ctx:
            bases.append(Path(app_root_ctx))
        if job_id and site_name:
            bases.append(Path.cwd() / str(job_id) / f"app_{site_name}")
        bases.append(Path.cwd())
        module_dir = Path(__file__).resolve().parent
        bases.append(module_dir)
        bases.append(module_dir.parent)
        for b in bases:
            candidate = (b / rel).resolve()
            if candidate.exists():
                return candidate, bases
        return None, bases

    def _write_json(self, fl_ctx: FLContext, rel_path: str, payload: Dict[str, Any]) -> None:
        job_id = fl_ctx.get_job_id()
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)

        root = Path("job-results") / str(job_id) / str(self.analytics_manager.computation_type) / workflow_name
        out_file = (root / rel_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to write JSON to {out_file}: {e}") from e

    def _write_workflow_error_json(
        self, fl_ctx: FLContext, workflow_name: str, computation_type: Any, payload: Dict[str, Any]
    ) -> None:
        """Write error.json into another workflow's results directory.

        ``_write_json`` always targets the *current* workflow; the sample-count pre-pass has to
        leave its explanation in the directories of the workflows it stopped, which is where the
        results retriever (and therefore the UI) looks for a per-computation error.
        """
        root = Path("job-results") / str(fl_ctx.get_job_id()) / str(computation_type) / str(workflow_name)
        try:
            root.mkdir(parents=True, exist_ok=True)
            with open(root / "error.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            self.custom_logger.warning(f"Failed to write error.json for workflow {workflow_name}: {e}")

    def _write_exception_json(self, fl_ctx: FLContext, stage: str, e: Exception) -> None:
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)

        payload: Dict[str, Any] = {
            "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "job_id": fl_ctx.get_job_id() if hasattr(fl_ctx, "get_job_id") else None,
            "workflow": workflow_name,
            "round": round_idx,
            "stage": stage,
            "exception_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }

        try:
            self._write_json(fl_ctx, "error.json", payload)
        except Exception:
            pass

        try:
            _server_emit_progress(
                fl_ctx=fl_ctx,
                code=PROGRESS_CODE["EXCEPTION_ENCOUNTERED"],
                round_idx=round_idx,
                function_name=getattr(self.analytics_manager, "computation_type", None),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Aggregator workflow
    # ------------------------------------------------------------------
    def aggregate(self, fl_ctx: FLContext) -> Shareable:
        """Performs one round of aggregation for a statistical analytics workflow.

        This is the main entry point for the aggregator, called by the NVFlare platform
        once per round.

        The method first delegates to the parent `HEAggregator` to handle any
        common homomorphic encryption tasks (e.g., key exchange). If the parent
        does not return a result, this method dispatches to a specific workflow
        handler based on the `workflow_name` from the FLContext.

        After the workflow-specific logic is complete, it calls `self.reset()`
        to clear any round-specific state before returning the results.

        Args:
            fl_ctx: The FLContext provided by the platform, containing round-specific
                    information and context.

        Returns:
            A Shareable object containing the aggregated data to be sent back to clients.

        Raises:
            Exception: If the `workflow_name` is not supported.
        """
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
        try:
            if workflow_name == "workflow_KeyGen":
                round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["KEYGEN"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
            elif workflow_name.startswith("workflow_threshold_samples"):
                # No function name: the pre-pass runs under the internal _PRE_COUNT_* computation
                # type, which means nothing to a reader of the job log.
                round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["THRESHOLD_SAMPLES"], round_idx=round_idx)

            result = super().aggregate(fl_ctx)

            if result is not None:
                return result


            if workflow_name.startswith("workflow_threshold_samples"):
                round_result = self._workflow_threshold_samples(fl_ctx)
            elif workflow_name.startswith("workflow_reference_stat_analytics"):
                round_result = self._workflow_reference_stat_analytics(fl_ctx)
            elif workflow_name.startswith("workflow_biomarker_score_computation"):
                round_result = self._workflow_reference_stat_analytics(fl_ctx)
            elif workflow_name.startswith("workflow_biomarker_lr_fit"):
                round_result = self._workflow_reference_stat_analytics(fl_ctx)
            elif workflow_name.startswith("workflow_stat_analytics"):
                round_result = self._workflow_stat_analytics(fl_ctx)
            elif workflow_name.startswith("workflow_model_upload"):
                round_result = self._workflow_model_upload(fl_ctx)
            elif workflow_name.startswith("workflow_enc_biomarker_score_cache"):
                round_result = self._workflow_enc_biomarker_score_cache(fl_ctx)
            elif workflow_name.startswith("workflow_enc_biomarker_score_postprocess") or workflow_name.startswith("workflow_enc_biomarker_risk_group_postprocess"):
                round_result = self._workflow_enc_biomarker_postprocess(fl_ctx)
            elif workflow_name.startswith("workflow_enc_biomarker_disc"):
                round_result = self._workflow_enc_biomarker_disc(fl_ctx)
            else:
                raise Exception(f"Unsupported AnalyticsAggregator workflow {workflow_name}")

            self.reset()
            return round_result
        except SystemExit as e:
            self._write_exception_json(fl_ctx, "aggregate:SystemExit", e)
            try:
                self.reset()
            except Exception:
                pass
            round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
            try:
                next_round = int(round_idx) + 1 if round_idx is not None else 1
            except Exception:
                next_round = 1
            return self.get_shareable_data({}, fl_ctx, metadata={"round": next_round, "error": True})

        except Exception as e:
            self._write_exception_json(fl_ctx, "aggregate", e)
            try:
                self.reset()
            except Exception:
                pass
            round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
            try:
                next_round = int(round_idx) + 1 if round_idx is not None else 1
            except Exception:
                next_round = 1
            return self.get_shareable_data({}, fl_ctx, metadata={"round": next_round, "error": True})

    # ------------------------------------------------------------------
    # Statistical Analytics
    # ------------------------------------------------------------------

    def _load_data_filters(self, fl_ctx: FLContext) -> None:
        # TODO: Apply filters once per job rather than once per workflow.
        # Load the filters
        if self.filters_path is not None:
            resolved, _ = self._resolve_filters_path(fl_ctx)
            self.filters_data: Dict[str, Any] = {}
            if resolved and resolved.exists():
                try:
                    self.filters_data = json.loads(Path(resolved).read_text())
                except Exception:
                    self.filters_data = {}
                    raise Exception(f"[AnalyticsAggregator] Fail: Filter not found or invalid filter file at {resolved}")
            self.analytics_manager.filters = self.filters_data.get("conditions", [])

        project_entry = self.filters_data.get("project") or {}
        project_id = project_entry.get("id")

        selected_datasource_group = project_entry.get("selected_datasource_group")
        if not isinstance(selected_datasource_group, dict):
            selected_datasource_group = {}
        datasource_group_id = selected_datasource_group.get("id")

        fhir_base = FHIRBaseConfigResolver.get_base_for_project(
            project_id,
            site_name=None,
            datasource_group_id=datasource_group_id,
        )
        self.analytics_manager.stat_data_path = fhir_base
        self.stat_data_path = fhir_base

        if not self.analytics_manager.stat_data_path:
            raise Exception(f"[AnalyticsAggregator] Fail: analytics_aggregator: stat_data_path not set or invalid..")

    def _workflow_threshold_samples(self, fl_ctx: FLContext):
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        workload_args = fl_ctx.get_prop("workload_args")["workflows"]
        if round_idx == 0:
            depth_required = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']["depth_required"]
            for site, value in self.accepted_data.items():
                if value.get("ciphertext", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients encrypted count ciphertexts.")

            self.min_global_samples = fl_ctx.get_prop("workload_args")["min_global_samples"]
            global_model_meta = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']
            self.mask_wrap_guard = global_model_meta.get("mask_wrap_guard")
            self.is_server_data_owner = global_model_meta['is_server_data_owner']
            self.is_server_contributing_to_aggregation = global_model_meta['is_server_contributing_to_aggregation']
            self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
            if self.is_server_data_owner:
                self._load_data_filters(fl_ctx)

            # Process local data if the server is a contributing data owner
            if self.is_server_data_owner and self.is_server_contributing_to_aggregation:
                generated_args = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']["generated_args"]
                merged_args = {}
                # Important: Order of keys in this dict really matters even though dicts are not ordered.
                # We want the handle_pre_count to return a list of count of workflows in the order that's mentioned in config file's workload_args.
                # This makes sure that we are adding up the same index of counts across all data owners.
                for k in list(workload_args.keys()):
                    merged_args[k] = {**workload_args.get(k, {}), **generated_args.get(k, {})}
                self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
                try:
                    count = self.analytics_manager.handle_pre_count(merged_args, self.min_global_samples)
                finally:
                    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
                self.local_analysed_data = count
            else:
                self.local_analysed_data = None
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

            # Aggregate the counts from clients
            self.fire_event(StatAnalyticsEventType.AGGREGATE_START, fl_ctx)
            try:
                if fl_ctx.get_prop(ReservedKey.WORKFLOW) == "workflow_threshold_samples_secure":
                    self.analytics_manager.computation_type = "_PRE_COUNT_SECURE_"
                    try:
                        result, self.local_list_enc_result = self.openfhe_manager.aggregate_stat_analytics("_PRE_COUNT_SECURE_", self.accepted_data, self.local_analysed_data, {"threshold": self.min_global_samples, "num_workflows": len(workload_args)}, depth_required)
                    except SystemExit as e:
                        self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics:SystemExit", e)
                        raise
                    except Exception as e:
                        self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics", e)
                        raise
                else:
                    self.analytics_manager.computation_type = "_PRE_COUNT_UNSECURE_"
                    try:
                        result, self.local_list_enc_result = self.openfhe_manager.aggregate_stat_analytics("_PRE_COUNT_UNSECURE_", self.accepted_data, self.local_analysed_data, {}, depth_required)
                    except SystemExit as e:
                        self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics:SystemExit", e)
                        raise
                    except Exception as e:
                        self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics", e)
                        raise
            finally:
                self.fire_event(StatAnalyticsEventType.AGGREGATE_END, fl_ctx)


            self.custom_logger.info(f"SEND: to all clients: aggregated count ciphertext.")
            return self.get_shareable_data(result, fl_ctx, metadata={"round": fl_ctx.get_prop(AppConstants.CURRENT_ROUND)+1})

        elif round_idx == 1:
            for site, value in self.accepted_data.items():
                if value.get("partialresult", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients partial decryptions.")

            self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
            try:
                ser_weights = self.openfhe_manager.server_decrypt_stat_analytics_r0("_PRE_COUNT_UNSECURE_", self.accepted_data, self.local_list_enc_result, self.arch, metadata={}) # Both secure and unsecure use same decryption logic
            finally:
                self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)
            ser_weights = ser_weights[:len(workload_args)]

            if fl_ctx.get_prop(ReservedKey.WORKFLOW) == "workflow_threshold_samples_secure":
                # The masked margins are exactly what this server just decrypted, so logging
                # them adds no exposure; the magnitude is the forensic the sign alone cannot
                # give (wrap vs noise vs genuinely below threshold).
                wrap_guard = getattr(self, "mask_wrap_guard", None)
                for w_name, masked in zip(workload_args, ser_weights):
                    self.custom_logger.info(
                        f"Secure threshold masked margin for {w_name}: {masked:.6e}"
                    )
                    if wrap_guard is not None and abs(masked) > wrap_guard:
                        self.custom_logger.warning(
                            f"Masked margin for {w_name} exceeds the CKKS wrap guard "
                            f"({wrap_guard:.2e}); the decrypted sign may have wrapped and "
                            "this threshold verdict is unreliable."
                        )
                    elif abs(masked) < 1e-5:
                        self.custom_logger.warning(
                            f"Masked margin for {w_name} is below the decryption noise "
                            "guard (1e-05); the sign may be noise and this threshold "
                            "verdict is unreliable."
                        )

            self.flag_failed_threshold_count = {}
            ctr = 0
            for workflow_name in workload_args:
                self.flag_failed_threshold_count[workflow_name] = False
                if fl_ctx.get_prop(ReservedKey.WORKFLOW) == "workflow_threshold_samples_secure" and ser_weights[ctr] < 0:
                    self.flag_failed_threshold_count[workflow_name] = True
                elif fl_ctx.get_prop(ReservedKey.WORKFLOW) == "workflow_threshold_samples_unsecure" and round(ser_weights[ctr]) < self.min_global_samples:
                    self.flag_failed_threshold_count[workflow_name] = True
                ctr += 1

            failed_workflows = [w for w, failed in self.flag_failed_threshold_count.items() if failed]
            if failed_workflows:
                # A computation below the minimum sample count cannot be delivered, so the run
                # cannot deliver what was requested. Stop here instead of skipping only the
                # affected workflows and returning a result set that silently omits them: every
                # remaining workflow is marked to be skipped and the job is failed with a reason.
                for workflow_name in self.flag_failed_threshold_count:
                    self.flag_failed_threshold_count[workflow_name] = True
                reason = (
                    f"Sample-count threshold not met: {len(failed_workflows)} of "
                    f"{len(self.flag_failed_threshold_count)} computation(s) have fewer than "
                    f"{self.min_global_samples} records ({', '.join(failed_workflows)}). "
                    "The run was stopped; no partial results were produced."
                )
                self._write_threshold_stop_errors(fl_ctx, workload_args, failed_workflows, reason)

            # Setting fl_ctx property that is used at the custom SAG workflow.
            fl_ctx.set_prop("FLAG_SKIP_WORKFLOW", self.flag_failed_threshold_count, private=False, sticky=True)

            if failed_workflows:
                _server_emit_progress(fl_ctx=fl_ctx,  code=PROGRESS_CODE["THRESHOLD_FAILED"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
                self.log_error(fl_ctx, reason)
                self.system_panic(reason, fl_ctx)
                return self.get_shareable_data({}, fl_ctx, metadata={})

            self.log_info(fl_ctx, "Flags for skipping workflows set based on total samples.")
            return self.get_shareable_data({}, fl_ctx, metadata={})
        else:
            raise Exception(f"Invalid round {round_idx}")

    def _write_threshold_stop_errors(
        self,
        fl_ctx: FLContext,
        workload_args: Dict[str, Any],
        failed_workflows: Iterable[str],
        reason: str,
    ) -> None:
        """Leave an error.json in every workflow the threshold pre-pass stopped.

        Written for the workflows that are below the threshold *and* the ones cancelled with
        them, so no requested computation ends up with an empty results directory and no
        explanation -- which is what makes a stopped run look like a partial success.
        """
        failed = set(failed_workflows)
        stamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        for workflow_name, w_args in workload_args.items():
            below_threshold = workflow_name in failed
            payload: Dict[str, Any] = {
                "timestamp_utc": stamp,
                "job_id": fl_ctx.get_job_id() if hasattr(fl_ctx, "get_job_id") else None,
                "workflow": workflow_name,
                "stage": "threshold_samples",
                "code": "BELOW_SAMPLE_THRESHOLD" if below_threshold else "RUN_STOPPED_BY_SAMPLE_THRESHOLD",
                "message": (
                    f"Fewer than {self.min_global_samples} records available for this computation; "
                    "it was not run."
                    if below_threshold
                    else "Not run: the run was stopped because another computation was below the "
                         f"minimum of {self.min_global_samples} records."
                ),
                "details": {"reason": reason, "min_global_samples": self.min_global_samples},
            }
            self._write_workflow_error_json(
                fl_ctx, workflow_name, (w_args or {}).get("computation_type"), payload
            )

    def _workflow_reference_stat_analytics(self, fl_ctx: FLContext):
        """Handles the server-side logic for the clear-text statistical analytics workflow.

        This is a two-round workflow:
        - Round 0: Collects statistical data from clients, determines the
          computation type from the global model, and aggregates the data in clear text.
        - Round 1: Finalizes the workflow.

        Args:
            fl_ctx: The current federated learning context.

        Returns:
            A Shareable object containing the aggregated statistics for the current round.

        Raises:
            Exception: If the current round number is invalid for this workflow.
        """

        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        aggregated_result = {}
        if round_idx == 0:
            global_model_meta = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']
            self.is_server_data_owner = global_model_meta['is_server_data_owner']
            self.is_server_contributing_to_aggregation = global_model_meta['is_server_contributing_to_aggregation']
            self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
            if self.is_server_data_owner:
                self._load_data_filters(fl_ctx)

            # Extract relevant properties from the global model metadata and setting the metadata for aggregation
            self.analytics_manager.reset_computation_props()
            metadata = self.analytics_manager.set_props_from_init_load(workload_args=fl_ctx.get_prop("workload_args"), generated_args=fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']["generated_args"])
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["PARAMS_LOADED"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)

            # Process local data if the server is a contributing data owner
            if self.is_server_data_owner and self.is_server_contributing_to_aggregation:
                self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
                try:
                    self.local_analysed_data = self.analytics_manager.preprocess_reference()
                finally:
                    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["HE_PREPROCESS"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
                self._write_json(fl_ctx, "initiator/raw_results.json", self.local_analysed_data)  # TODO: Remove; this raw dump is for debugging only.
            else:
                self.local_analysed_data = None

            # Aggregate the statistical data from clients
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["AGGREGATE_BEGIN"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
            self.fire_event(StatAnalyticsEventType.AGGREGATE_REFERENCE_START, fl_ctx)
            try:
                aggregated_result = self.analytics_manager.aggregate_reference(self.accepted_data, self.local_analysed_data)
            finally:
                self.fire_event(StatAnalyticsEventType.AGGREGATE_REFERENCE_END, fl_ctx)
            self._write_json(fl_ctx, "aggregated/raw_results.json", aggregated_result)  # TODO: Remove; this raw dump is for debugging only.
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["AGGREGATE_DONE"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)

            # Post-process the aggregated result if the server is the data owner 
            if self.is_server_data_owner:
                self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                try:
                    result = self.analytics_manager.postprocess_reference(aggregated_result)
                finally:
                    self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["POSTPROCESS"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
                self.log_info(fl_ctx, f"Final reference result: {result}")
                self._write_json(fl_ctx, "aggregated/processed_results.json", result)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["WRITE_AGGREGATED_JSON"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
        elif round_idx == 1:
            aggregated_result = {}
        else:
            raise Exception(f"Invalid round {round_idx}")

        return self.get_shareable_data(aggregated_result, fl_ctx, metadata={"round": fl_ctx.get_prop(AppConstants.CURRENT_ROUND)+1})

    def _workflow_stat_analytics(self, fl_ctx: FLContext):
        """Handles the server-side logic for the encrypted statistical analytics workflow.

        This is a three-round workflow using homomorphic encryption:
        - Round 0: Collects encrypted statistical data from clients and performs
          encrypted aggregation.
        - Round 1: Handles the decryption phase of the aggregated results.
        - Round 2: Finalizes the workflow.

        Args:
            fl_ctx: The current federated learning context.

        Returns:
            A Shareable object containing the data for the current round (e.g.,
            encrypted results, decrypted results, or finalization signals).

        Raises:
            Exception: If the current round number is invalid for this workflow.
        """

        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        metadata={}
        result = {}
        if round_idx == 0:
            for site, value in self.accepted_data.items():
                if value.get("ciphertext", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients encrypted ciphertexts.")

            self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
            global_model_meta = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']
            self.hide_result_from_server = bool(global_model_meta.get("hide_result_from_server", False))
            self.exclude_analyzing_clients = list(global_model_meta.get("exclude_analyzing_clients") or [])
            if self.hide_result_from_server:
                self.leader_client_name = global_model_meta.get("leader_client_name", "site1")
            depth_required = global_model_meta["depth_required"]
            self.is_server_data_owner = global_model_meta['is_server_data_owner']
            self.is_server_contributing_to_aggregation = global_model_meta['is_server_contributing_to_aggregation']
            if self.is_server_data_owner:
                self._load_data_filters(fl_ctx)

            # Extract relevant properties And set the metadata for aggregation
            generated_args=fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']["generated_args"]
            workload_args=fl_ctx.get_prop("workload_args")
            if 'w_biomarker_risk_scores' in generated_args:
                # Encrypted biomarker flow: risk scores were computed homomorphically in
                # workflow_enc_biomarker_disc; the server holds NO plaintext model. When the server
                # is a data owner it scores its OWN patients from its precomputed score slice
                # (biomarker_server_risk_key) -- finalizing the multiparty decryption with no
                # hide-from-lead mask (remove_mask=False) -- exactly as each client does for its own
                # slice (see executor _task_stat_analytics). No plaintext coeffs/cutoff are loaded.
                if self.is_server_data_owner:
                    mk = str(workload_args.get("model_key", "")).strip()
                    if not mk:
                        raise ValueError("workload_args.model_key is required for encrypted biomarker risk scores.")
                    server_share = generated_args['w_biomarker_risk_scores'].get(biomarker_server_risk_key)
                    if server_share is None:
                        raise Exception(
                            "Encrypted biomarker: the server's own risk-score slice is missing. The server "
                            "must be a data owner during workflow_enc_biomarker_disc to score its own patients."
                        )
                    scores = self.openfhe_manager._remove_biomarker_mask_and_extract_scores(
                        server_share, mk, remove_mask=False
                    )
                    scores = self.analytics_manager._re_map_batched_patients_biomarker(
                        scores, self.openfhe_manager.cc_batch_size, len(generated_args['biomarker_covariates'])
                    )
                    generated_args['w_biomarker_risk_scores'] = scores
                else:
                    # Server is a pure computing party: it owns no patients to score. Use an empty
                    # score list (NOT None) so set_props_from_init_load does not fall back to loading
                    # a plaintext model, which does not exist in the encrypted flow.
                    generated_args['w_biomarker_risk_scores'] = []
            self.analytics_manager.reset_computation_props()
            metadata = self.analytics_manager.set_props_from_init_load(workload_args=workload_args, generated_args=generated_args)
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["PARAMS_LOADED"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

            # Process local data if the server is a data owner
            if self.is_server_data_owner:
                # consolidated single emit: AFTER preprocess success
                self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
                try:
                    self.local_analysed_data = self.analytics_manager.preprocess()
                finally:
                    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["HE_PREPROCESS"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)

                # Conduct statistical analysis exclusively on the local data.
                if self.flag_calc_local_result:
                    self.fire_event(StatAnalyticsEventType.AGGREGATE_REFERENCE_START, fl_ctx)
                    try:
                        local_only_intermed_result = self.analytics_manager.aggregate_reference({}, self.local_analysed_data)
                    finally:
                        self.fire_event(StatAnalyticsEventType.AGGREGATE_REFERENCE_END, fl_ctx)
                    self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                    try:
                        if self.analytics_manager.computation_type in ['mean', 'stdev']:
                            local_only_result = self.analytics_manager.postprocess(local_only_intermed_result)
                        else:
                            local_only_result = self.analytics_manager.postprocess_reference(local_only_intermed_result)
                        self._write_json(fl_ctx, "initiator/raw_results.json", local_only_result)
                    finally:
                        self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)

                # If the server is not contributing to aggregation, discard local data
                if not self.is_server_contributing_to_aggregation:
                    self.local_analysed_data = None
            else:
                self.local_analysed_data = None

            # Aggregate encrypted statistics from all sources (ciphertext domain)
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["AGGREGATE_BEGIN"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
            self.fire_event(StatAnalyticsEventType.AGGREGATE_START, fl_ctx)
            try:
                result, self.local_list_enc_result = self.openfhe_manager.aggregate_stat_analytics(
                    self.analytics_manager.computation_type,
                    self.accepted_data,
                    self.local_analysed_data,
                    metadata,
                    depth_required
                )
            except SystemExit as e:
                self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics:SystemExit", e)
                raise
            except Exception as e:
                self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics", e)
                raise
            finally:
                self.fire_event(StatAnalyticsEventType.AGGREGATE_END, fl_ctx)

            self.custom_logger.info(f"SEND: to all clients: aggregated result ciphertext.")
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["AGGREGATE_DONE"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)

        elif round_idx == 1:
            for site, value in self.accepted_data.items():
                if value.get("partialresult", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients partial decryptions.")

            # Setting Metadata
            self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
            metadata = {}
            if self.analytics_manager.computation_type == "chi2":
                metadata = {
                    "len_category1": len(self.analytics_manager.column_1_categories),
                    "len_category2": len(self.analytics_manager.column_2_categories)
                    }
            elif self.analytics_manager.computation_type == "kaplan-meier":
                import math
                M_steps = math.ceil((self.analytics_manager.time_grid_max - self.analytics_manager.time_grid_min) / self.analytics_manager.time_grid_step)
                time_grid = [self.analytics_manager.time_grid_min + ind * self.analytics_manager.time_grid_step for ind in range(int(M_steps))]
                if time_grid and time_grid[-1] < self.analytics_manager.time_grid_max: # Ensure max_time is covered if not perfectly aligned
                    time_grid.append(self.analytics_manager.time_grid_max)
                metadata = {"len_time_grid": len(time_grid)}
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

            # Decrypt the aggregated results from clients (server-side)
            self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
            try:
                ser_weights = self.openfhe_manager.server_decrypt_stat_analytics_r0(
                    self.analytics_manager.computation_type,
                    self.accepted_data,
                    self.local_list_enc_result,
                    self.arch,
                    metadata,
                    self.hide_result_from_server
                )
            finally:
                self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)


            # If the server is the data owner, post-process the decrypted results
            if self.is_server_data_owner and not self.hide_result_from_server:
                # Save raw aggregated (now in clear)
                self._write_json(fl_ctx, "aggregated/raw_results.json", ser_weights)  # TODO: Remove; this raw dump is for debugging only.
                # consolidated single emit: AFTER postprocess success
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["POSTPROCESS"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
                self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                try:
                    result = self.analytics_manager.postprocess(ser_weights)
                finally:
                    self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)
                self._write_json(fl_ctx, "aggregated/processed_results.json", result)
                _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE["WRITE_AGGREGATED_JSON"], round_idx=round_idx, function_name=self.analytics_manager.computation_type)

            self.custom_logger.info(f"SEND: to all clients: decrypted results or all partial decryption shares.")
            if self.hide_result_from_server:
                # Only the leader can fuse the partial decryptions in round 2.
                # Mark the asymmetric shareable with explicit targets so customSAG
                # does not also send the empty base payload to every other client.
                per_client_specs = {self.leader_client_name: {"_extra_data_": {"result": ser_weights}}}
                next_meta = {"round": round_idx + 1, "_TARGET_CLIENTS_": [self.leader_client_name]}
                return self.get_shareable_data_asymmetric({}, next_meta, per_client_specs, fl_ctx)
            next_meta = {"round": round_idx + 1}
            excl = set(self.exclude_analyzing_clients or [])
            if excl:
                try:
                    client_names = [
                        c.name if hasattr(c, "name") else str(c)
                        for c in fl_ctx.get_engine().get_clients()
                    ]
                except Exception:
                    client_names = []
                per_client_specs = {}
                for name in client_names:
                    if name in excl:
                        per_client_specs[name] = {"_override_": True, "data": {}, "meta": dict(next_meta)}
                    else:
                        per_client_specs[name] = {"_extra_data_": {"result": ser_weights}}
                return self.get_shareable_data_asymmetric({}, next_meta, per_client_specs, fl_ctx)
            return self.get_shareable_data({"result": ser_weights}, fl_ctx, metadata=next_meta)

        elif round_idx == 2:
            result = {}
            if self.hide_result_from_server:
                per_client_specs = {}
                leader_payload = self.accepted_data.get(self.leader_client_name)
                if not isinstance(leader_payload, dict) or not leader_payload:
                    self.custom_logger.error(
                        f"PQC round-3 ({fl_ctx.get_prop(ReservedKey.WORKFLOW)}): leader "
                        f"'{self.leader_client_name}' round-2 submission is ABSENT/empty at aggregation "
                        f"(accepted_data={sorted(self.accepted_data.keys())}). The round advanced before "
                        f"the leader submitted its per-non-leader payloads -- non-leaders would receive a "
                        f"result-less round-3 payload. This is the round-2 wait race (fixed upstream by "
                        f"the customSAG wait barrier; this guard is the server-side backstop). Failing "
                        f"this combo to avoid a silent bad result."
                    )
                    raise Exception(
                        f"PQC round-3 leader submission missing for "
                        f"{fl_ctx.get_prop(ReservedKey.WORKFLOW)}: leader='{self.leader_client_name}' "
                        f"accepted_data={sorted(self.accepted_data.keys())}"
                    )
                if len(self.accepted_data) != 1:
                    raise Exception(f"Invalid number of clients {len(self.accepted_data)} for encrypted analytics task.")
                leader_map = leader_payload
                excl = set(self.exclude_analyzing_clients or [])
                for cname, value in leader_map.items():
                    if cname in excl:
                        continue
                    per_client_specs[cname] = {"_extra_data_": {"result": value}}
                try:
                    all_names = [
                        c.name if hasattr(c, "name") else str(c)
                        for c in fl_ctx.get_engine().get_clients()
                    ]
                except Exception:
                    all_names = []
                next_meta = {"round": round_idx + 1}
                for name in all_names:
                    if name == self.leader_client_name:
                        continue
                    if name in excl and name not in per_client_specs:
                        per_client_specs[name] = {"_override_": True, "data": {}, "meta": dict(next_meta)}
                # Diagnostic + loud guard: non-leaders enter per_client_specs ONLY via leader_map above,
                # so if the leader's round-2 submission is missing one, that client silently falls
                # through to a result-less base at round 3. Log the keys, and surface any missing
                # analyzing non-leader as an ERROR (instead of a silent None) so any drop is localizable.
                expected_non_leaders = {
                    n for n in all_names if n != self.leader_client_name and n not in excl
                }
                missing = expected_non_leaders - set(per_client_specs.keys())
                self.custom_logger.info(
                    f"PQC round-2 per-client specs ({fl_ctx.get_prop(ReservedKey.WORKFLOW)}): "
                    f"accepted_data={sorted(self.accepted_data.keys())} "
                    f"leader_map={sorted(leader_map.keys())} specs={sorted(per_client_specs.keys())}"
                )
                if missing:
                    self.custom_logger.error(
                        f"PQC round-2 ({fl_ctx.get_prop(ReservedKey.WORKFLOW)}): analyzing non-leaders "
                        f"{sorted(missing)} are MISSING from per_client_specs (leader_map="
                        f"{sorted(leader_map.keys())}) -> they would get an empty round-3 payload."
                    )

                # Only clients with a real per-client PQC payload (plus explicit no-op
                # overrides for excluded clients) should receive round 3. Unlisted clients
                # would otherwise receive the empty base payload and fail with result=None.
                next_meta["_TARGET_CLIENTS_"] = list(per_client_specs.keys())
                return self.get_shareable_data_asymmetric({}, next_meta, per_client_specs, fl_ctx)

        elif round_idx == 3:
            result = {}
        else:
            raise Exception(f"Invalid round {round_idx}")

        return self.get_shareable_data(result, fl_ctx, metadata={"round": fl_ctx.get_prop(AppConstants.CURRENT_ROUND)+1})

    def _workflow_model_upload(self, fl_ctx):
        job_id   = fl_ctx.get_job_id()
        dest_dir = os.path.abspath(os.path.join(str(job_id), "app_server", "custom"))
        os.makedirs(dest_dir, exist_ok=True)

        # accepted_data is keyed by site name; the leader's entry carries the model payload
        # (other clients returned {} -- see _task_model_upload non-leader branch).
        # Open-access leaders send "model_data" (raw CSV bytes); Encrypted leaders send
        # "enc_model_data" (OpenFHE ciphertext bytes) + "risk_scores_scale_factor_by_model".
        leader_value = None
        for site, value in self.accepted_data.items():
            if isinstance(value, dict) and (value.get("enc_model_data") or value.get("model_data")):
                leader_value = value
                break

        if not leader_value:
            raise ValueError("workflow_model_upload: no model data received from any client")

        cancer_type = leader_value.get("cancer_type") or ""
        if not cancer_type:
            raise ValueError("workflow_model_upload: cancer_type missing from leader payload")

        # IMPORTANT: filenames preserve spaces in cancer_type. Both resolve_biomarker_model_paths
        # (CSV) and resolve_encrypted_biomarker_model_paths (.ct) use the raw cancer_type string;
        # do NOT translate spaces to underscores here or the downstream consumer won't find them.
        enc_model_data = leader_value.get("enc_model_data")
        if enc_model_data:
            # Encrypted model: persist the per-model ciphertext blobs + scale-factor sidecar.
            # plaintext coefficients never reached the server -- they were encrypted on leader_client
            rsf_by_model = leader_value.get("risk_scores_scale_factor_by_model") or {}
            horizon_threshold_by_model = leader_value.get("horizon_threshold_by_model") or {}
            # LCS scoring uploads (rsf=1.0) write the "_score" .ct variant so they don't
            # overwrite the discovery model (rsf=1/|cutoff|) for the same model_key.
            for_scoring = bool(leader_value.get("for_scoring", False))
            for mk, blobs in enc_model_data.items():
                paths = {"model_key": mk, "cancer_type": cancer_type}
                resolve_encrypted_biomarker_model_paths(paths, dest_dir, for_scoring=for_scoring)
                with open(paths["coeff_ct_file_path"], "wb") as f:
                    f.write(blobs["coeff_ct"])
                with open(paths["cutoff_ct_file_path"], "wb") as f:
                    f.write(blobs["cutoff_ct"])
                # Encrypted 1/rsf: additive artifact, consumed by the LCS descale so
                # the server never needs plaintext rsf/|cutoff|. Tolerate older leaders
                # that did not upload it (falls back to the plaintext-rsf path).
                if blobs.get("inv_rsf_ct") is not None:
                    with open(paths["inv_rsf_ct_file_path"], "wb") as f:
                        f.write(blobs["inv_rsf_ct"])
                # Discovery persists the plaintext rsf sidecar (the KM dead-band still
                # needs it). The LCS scoring path descales via the encrypted 1/rsf, so it
                # must NOT write plaintext rsf to disk -- enforce the encrypted contract.
                if not for_scoring:
                    with open(paths["scale_factor_file_path"], "w") as f:
                        json.dump({"rsf": float(rsf_by_model.get(mk, 1.0))}, f)
                if for_scoring and mk in horizon_threshold_by_model:
                    # Encrypted LCS keeps weights/cutoff encrypted, but the later
                    # meta-analysis resolver still needs the non-secret ER_threshold
                    # from the cutoff CSV. Preserve that downstream contract without
                    # copying plaintext model coefficients or cutoff values to server.
                    threshold_path = os.path.join(dest_dir, f"{mk}_{cancer_type}_cutoff.csv")
                    with open(threshold_path, "w") as f:
                        f.write("ER_threshold\n")
                        f.write(f"{float(horizon_threshold_by_model[mk])}\n")
            written_keys = list(enc_model_data)
            audit_msg = f"encrypted model_keys={written_keys} cancer_type={cancer_type!r}"
        else:
            # Open-access model: persist the raw CSVs for the clear-text biomarker consumer.
            model_data = leader_value["model_data"]
            for mk, files in model_data.items():
                weights_path = os.path.join(dest_dir, f"{mk}_{cancer_type}_weights.csv")
                cutoff_path  = os.path.join(dest_dir, f"{mk}_{cancer_type}_cutoff.csv")
                with open(weights_path, "wb") as f:
                    f.write(files["weights_csv"])
                with open(cutoff_path, "wb") as f:
                    f.write(files["cutoff_csv"])
            written_keys = list(model_data)
            audit_msg = f"open-access model_keys={written_keys} cancer_type={cancer_type!r}"

        self.custom_logger.info(
            f"workflow_model_upload: wrote model files for keys {written_keys} "
            f"(cancer_type={cancer_type!r}) to {dest_dir}"
        )

        try:
            auditor = AuditService.get_auditor()
            if auditor is not None:
                auditor.add_job_event(
                    job_id=fl_ctx.get_job_id(),
                    scope_name="workflow_model_upload",
                    msg=audit_msg,
                )
        except Exception:
            pass

        return self.get_shareable_data({}, fl_ctx)

    def _bio_progress_emitter(self, fl_ctx: FLContext, round_idx):
        """Return ``emit(code)`` bound to this workflow's ``fl_ctx`` / ``round_idx``, filling
        in the standard ``function_name=self.analytics_manager.computation_type`` for the
        biomarker progress events. ``computation_type`` is read lazily (at each ``emit`` call)
        so a set_props_from_init_load that runs mid-method is reflected."""
        def emit(code):
            _server_emit_progress(fl_ctx=fl_ctx, code=PROGRESS_CODE[code], round_idx=round_idx, function_name=self.analytics_manager.computation_type)
        return emit

    def _biomarker_round0_setup(self, fl_ctx: FLContext, *, is_postprocess: bool):
        """Shared round-0 prologue for the encrypted-biomarker workflows.

        Fires SETUP_START, reads the uploaded global-model meta (depth + server-owner
        flags, stashed on ``self``), resets + reloads the analytics computation props,
        and stamps the per-model metadata (model_keys / biomarker_models_by_key / covs)
        from workload_args. Returns ``(depth_required, metadata)``; the caller fires
        SETUP_END (the postprocess consumers read the server-cached score first).

        Two variants:
          * producer / discovery (``is_postprocess=False``): the server owns data
            slices, so load the data filters, seed ``metadata`` from
            ``set_props_from_init_load`` (it carries the openfhe aggregation params the
            dot product needs), and validate that the uploaded coeff/cutoff .ct blobs
            exist. Emits PARAMS_LOADED + BIO_VALIDATE_ARTIFACTS.
          * from-cache postprocess consumer (``is_postprocess=True``): reads the cached
            score and uploads nothing, so no filters / no .ct validation; ``metadata``
            starts empty (only the three biomarker keys are needed for the tail).
        ``set_props_from_init_load`` is called in BOTH variants for its side effects
        (it populates ``biomarker_covariates``); only whether its return seeds
        ``metadata`` differs.
        """
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        emit = self._bio_progress_emitter(fl_ctx, round_idx)
        self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
        global_model_meta = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']
        depth_required = global_model_meta["depth_required"]
        self.is_server_data_owner = global_model_meta['is_server_data_owner']
        self.is_server_contributing_to_aggregation = global_model_meta['is_server_contributing_to_aggregation']
        if not is_postprocess and self.is_server_data_owner:
            emit("BIO_LOAD_FILTERS")
            self._load_data_filters(fl_ctx)

        self.analytics_manager.reset_computation_props()
        init_meta = self.analytics_manager.set_props_from_init_load(
            workload_args=fl_ctx.get_prop("workload_args"),
            generated_args=global_model_meta["generated_args"],
        )
        metadata = {} if is_postprocess else init_meta
        if not is_postprocess:
            emit("PARAMS_LOADED")
            emit("BIO_VALIDATE_ARTIFACTS")

        wargs = fl_ctx.get_prop("workload_args")
        metadata["model_keys"] = list(wargs["model_keys"])
        metadata["biomarker_models_by_key"] = wargs["biomarker_models_by_key"]
        metadata["covs"] = self.analytics_manager.biomarker_covariates
        if not is_postprocess:
            # Encrypted-only path: artifacts are the uploaded ciphertext blobs (.ct), not CSVs.
            for mk, paths in metadata["biomarker_models_by_key"].items():
                cc_path = paths["coeff_ct_file_path"]
                co_path = paths["cutoff_ct_file_path"]
                if not os.path.exists(cc_path) or not os.path.exists(co_path):
                    raise FileNotFoundError(
                        f"Error: Encrypted model {mk}: '{cc_path}' or '{co_path}' was not found."
                    )
        return depth_required, metadata

    def _workflow_enc_biomarker_score_cache(self, fl_ctx: FLContext):
        """Split-architecture score producer (num_rounds=1, no decrypt).

        Round 0 is byte-for-byte the discovery/scoring compute (dot product + slot-mask +
        NEUTRAL pack, computation_type=biomarker_enc_score_cache -> SKIP_CUTOFF + no descale +
        no rm), but instead of broadcasting the aggregated ciphertext for a partial-decrypt
        round, the server CACHES the packed rsf-scaled score ciphertexts (one per model x
        client, incl. its own biomarker_server_risk_key slice) for the downstream KM / LCS
        postprocess consumers. The cache is threaded to the persistor via the round-0 weights
        (see save_model -> w_biomarker_score_ct_cache). See UnifiedBiomarkerScorePlan.md sec 2-3.
        """
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        if round_idx != 0:
            raise Exception(f"workflow_enc_biomarker_score_cache is a single-round producer; got round {round_idx}")
        emit = self._bio_progress_emitter(fl_ctx, round_idx)

        emit("BIO_WORKFLOW_STARTED")

        for site, value in self.accepted_data.items():
            if value.get("ciphertext", None) == None:
                self.custom_logger.warning(f"Missing input from {site}.")
        self.custom_logger.info(f"RECV: All clients encrypted ciphertexts.")
        emit("BIO_RECV_CIPHERTEXTS")

        depth_required, metadata = self._biomarker_round0_setup(fl_ctx, is_postprocess=False)
        self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

        # Score the server's own patients too when it is a data owner (identical to discovery).
        if self.is_server_data_owner:
            self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
            try:
                self.local_analysed_data = self.analytics_manager.preprocess()
            finally:
                self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
            emit("BIO_PREPROCESS")
        else:
            self.local_analysed_data = None

        # Homomorphic dot product + neutral pack over all clients (and the server slice).
        emit("BIO_AGGREGATE_BEGIN")
        self.fire_event(StatAnalyticsEventType.AGGREGATE_START, fl_ctx)
        try:
            result, self.local_list_enc_result = self.openfhe_manager.aggregate_stat_analytics(self.analytics_manager.computation_type, self.accepted_data, self.local_analysed_data, metadata, depth_required)
            try:
                fl_ctx.set_prop("__duality_parallel_stats",
                                getattr(self.openfhe_manager, "last_parallel_stats", None),
                                private=True, sticky=False)
            except Exception:
                pass
        except SystemExit as e:
            self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_score_cache:aggregate_stat_analytics:SystemExit", e)
            raise
        except Exception as e:
            self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_score_cache:aggregate_stat_analytics", e)
            raise
        finally:
            self.fire_event(StatAnalyticsEventType.AGGREGATE_END, fl_ctx)
        emit("BIO_AGGREGATE_DONE")

        # Cache the packed neutral score ciphertexts {model_key: {client_name: ser_ct}} for the
        # postprocess consumers. No decrypt round: the workflow ends after round 0 (num_rounds=1),
        # and save_model stashes this onto the persistor's w_biomarker_score_ct_cache.
        cache_payload = result.get("enc_result", {}) if isinstance(result, dict) else {}
        self.custom_logger.info(
            f"SCORE CACHE: caching packed score ciphertexts for models "
            f"{sorted(cache_payload.keys())} "
            f"(clients per model: { {mk: sorted(v.keys()) for mk, v in cache_payload.items()} })."
        )
        return self.get_shareable_data({"w_biomarker_score_ct_cache": cache_payload}, fl_ctx, metadata={"round": round_idx+1})

    def _workflow_enc_biomarker_postprocess(self, fl_ctx: FLContext):
        """Split-architecture from-cache postprocess consumer -- LCS descale OR KM risk group.

        The producer (workflow_enc_biomarker_score_cache) already ran the expensive dot product
        and cached the packed rsf-scaled score; this workflow reuses it, so NO client encrypts and
        NO dot product runs. Both consumers share the same round structure; only the per-slot tail
        (in openfhe apply_biomarker_score_postprocess_tail) and the terminal round differ, keyed on
        computation_type:

          * LCS (biomarker_enc_score_postprocess, num_rounds=3): tail = x 1/rsf; round 2 is a
            terminal ack (clients fuse + cache their own score slice locally, as in the fused path).
          * KM  (biomarker_enc_risk_group_postprocess, num_rounds=2): tail = -cutoff then x rm;
            ends at round 1 (server combines -> persistor -> downstream kaplan-meier, no client r2).
            It produces the SAME ``w_biomarker_risk_scores`` the fused ``workflow_enc_biomarker_disc``
            KM branch handed to the persistor, so downstream kaplan-meier is unchanged.

        Rounds (SAG): round 0 reads the server-cached score (private+sticky fl_ctx prop set by the
        persistor), applies the tail to a FRESH deserialized ciphertext, and broadcasts enc_result
        for the partial-decrypt round -- clients upload nothing. Round 1 combines the clients'
        partial decryptions and hands the recovered score ciphertexts to the clients + persistor.

        NOTE (KM): no ``risk_scores_scale_factor`` is emitted -- the score-cache reads the ``_score``
        upload variant (no plaintext rsf) and the downstream KM dead-band is rsf-free (utils.py).
        See UnifiedBiomarkerScorePlan.md sections 2-3 (and section 9 for the known sign(cutoff) leak).
        """
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        emit = self._bio_progress_emitter(fl_ctx, round_idx)
        result = {}
        if round_idx == 0:
            emit("BIO_WORKFLOW_STARTED")

            depth_required, metadata = self._biomarker_round0_setup(fl_ctx, is_postprocess=True)
            # computation_type is only resolved by set_props_from_init_load (inside the setup
            # call above), so read it FRESH here -- a stale value from a prior workflow in the
            # same job (e.g. the KM postprocess before this LCS one in a combined job) would
            # otherwise route the wrong per-slot tail in apply_biomarker_score_postprocess_tail.
            computation_type = self.analytics_manager.computation_type
            is_km = (computation_type == ENC_BIOMARKER_RISK_GROUP_POSTPROCESS)

            # Server-only handoff from the producer: the packed score ciphertexts cached on the
            # persistor and bridged here via a private+sticky fl_ctx prop (never broadcast to clients).
            cached_cts = fl_ctx.get_prop("w_biomarker_score_ct_cache")
            if not cached_cts:
                raise Exception(
                    f"{computation_type}: no cached score ciphertext available (expected the "
                    "private+sticky 'w_biomarker_score_ct_cache' set by the persistor after "
                    "workflow_enc_biomarker_score_cache)."
                )
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

            emit("BIO_AGGREGATE_BEGIN")
            self.fire_event(StatAnalyticsEventType.AGGREGATE_START, fl_ctx)
            try:
                result, self.local_list_enc_result = self.openfhe_manager.apply_biomarker_score_postprocess_tail(
                    computation_type, cached_cts, metadata, depth_required
                )
            except SystemExit as e:
                self._write_exception_json(fl_ctx, f"_workflow_enc_biomarker_postprocess[{computation_type}]:apply_tail:SystemExit", e)
                raise
            except Exception as e:
                self._write_exception_json(fl_ctx, f"_workflow_enc_biomarker_postprocess[{computation_type}]:apply_tail", e)
                raise
            finally:
                self.fire_event(StatAnalyticsEventType.AGGREGATE_END, fl_ctx)
            emit("BIO_AGGREGATE_DONE")
            tail_desc = "rm-masked (score - cutoff)" if is_km else "descaled score"
            self.custom_logger.info(f"SEND: to all clients: {tail_desc} ciphertext for partial decryption.")

        elif round_idx == 1:
            # computation_type persists on self.analytics_manager from the round-0 set_props.
            computation_type = self.analytics_manager.computation_type
            is_km = (computation_type == ENC_BIOMARKER_RISK_GROUP_POSTPROCESS)
            for site, value in self.accepted_data.items():
                if value.get("partialresult", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients partial decryptions.")
            emit("BIO_RECV_PARTIAL_DECRYPTS")

            metadata = {}
            emit("BIO_DECRYPT")
            self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
            try:
                ser_weights = self.openfhe_manager.server_decrypt_stat_analytics_r0(computation_type, self.accepted_data, self.local_list_enc_result, self.arch, metadata)
            finally:
                self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)

            # KM hands the recovered scores to the persistor (-> downstream KM) and emits NO
            # risk_scores_scale_factor (dead-band is rsf-free, utils.py); LCS returns them for the
            # clients to fuse in round 2. Same shareable payload either way.
            self.custom_logger.info(
                "SEND: to persistor + clients: recovered risk-score ciphertexts."
                if is_km else
                "SEND: to all clients: combined partial decryptions (scores)."
            )
            emit("BIO_SEND_RISK_SCORES")
            return self.get_shareable_data({"w_biomarker_risk_scores": ser_weights}, fl_ctx, metadata={"round": round_idx+1})

        elif round_idx == 2:
            # LCS terminal round (num_rounds=3): clients fuse + cache their own score slice locally
            # in their round-2 task (mirrors the fused scoring path). Nothing to aggregate -- ack so
            # the workflow ends. KM is num_rounds=2 and never reaches this round.
            result = {}
            return self.get_shareable_data(result, fl_ctx, metadata={"round": round_idx+1})

        else:
            raise Exception(f"Invalid round {round_idx}")

        return self.get_shareable_data(result, fl_ctx, metadata={"round": fl_ctx.get_prop(AppConstants.CURRENT_ROUND)+1})

    def _workflow_enc_biomarker_disc(self, fl_ctx: FLContext):
        round_idx = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        emit = self._bio_progress_emitter(fl_ctx, round_idx)
        result = {}
        if round_idx == 0:
            emit("BIO_WORKFLOW_STARTED")

            for site, value in self.accepted_data.items():
                if value.get("ciphertext", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients encrypted ciphertexts.")
            emit("BIO_RECV_CIPHERTEXTS")

            depth_required, metadata = self._biomarker_round0_setup(fl_ctx, is_postprocess=False)
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

            # Process local data if the server is a data owner
            if self.is_server_data_owner:
                self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
                try:
                    self.local_analysed_data = self.analytics_manager.preprocess()
                finally:
                    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
                emit("BIO_PREPROCESS")

                # Keep local_analysed_data even when is_server_contributing_to_aggregation is False:
                # the server's own patients are scored HOMOMORPHICALLY in aggregate_stat_analytics
                # (encrypted under the multiparty key, model never seen in plaintext). Per-site
                # biomarker scoring is independent of cross-site aggregation, so this flag -- which
                # only governs combining the server's stats into the downstream aggregate -- must not
                # suppress the server's own risk-score computation.
            else:
                self.local_analysed_data = None

            # Aggregate the statistical data from clients
            emit("BIO_AGGREGATE_BEGIN")
            self.fire_event(StatAnalyticsEventType.AGGREGATE_START, fl_ctx)
            try:
                result, self.local_list_enc_result = self.openfhe_manager.aggregate_stat_analytics(self.analytics_manager.computation_type, self.accepted_data, self.local_analysed_data, metadata, depth_required)
                try:
                    fl_ctx.set_prop("__duality_parallel_stats",
                                    getattr(self.openfhe_manager, "last_parallel_stats", None),
                                    private=True, sticky=False)
                except Exception:
                    pass
            except SystemExit as e:
                self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics:SystemExit", e)
                raise
            except Exception as e:
                self._write_exception_json(fl_ctx, "_workflow_enc_biomarker_disc:aggregate_stat_analytics", e)
                raise
            finally:
                self.fire_event(StatAnalyticsEventType.AGGREGATE_END, fl_ctx)
            self._bio_risk_scores_scale_factor = metadata.get("risk_scores_scale_factor_by_model")
            self.custom_logger.info(f"SEND: to all clients: aggregated result ciphertext.")
            emit("BIO_AGGREGATE_DONE")

        elif round_idx == 1:
            for site, value in self.accepted_data.items():
                if value.get("partialresult", None) == None:
                    self.custom_logger.warning(f"Missing input from {site}.")
            self.custom_logger.info(f"RECV: All clients partial decryptions.")
            emit("BIO_RECV_PARTIAL_DECRYPTS")

            # Setting Metadata
            metadata = {}
            emit("BIO_DECRYPT")
            # Decrypt the aggregated results from clients
            self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
            try:
                ser_weights = self.openfhe_manager.server_decrypt_stat_analytics_r0(self.analytics_manager.computation_type, self.accepted_data, self.local_list_enc_result, self.arch, metadata)
            finally:
                self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)

            self.custom_logger.info(f"SEND: to all clients: decrypted results.")
            emit("BIO_SEND_RISK_SCORES")
            bio_weights = {"w_biomarker_risk_scores": ser_weights}
            rsf = getattr(self, "_bio_risk_scores_scale_factor", None)
            if rsf is not None:
                bio_weights["risk_scores_scale_factor"] = rsf
            return self.get_shareable_data(bio_weights, fl_ctx, metadata={"round": round_idx+1})   # Sending risk_scores to persistor to save

        elif round_idx == 2:
            # LCS scoring only (num_rounds=3): round 1 broadcast the combined-partials
            # ciphers, which clients fuse + cache locally. Nothing to aggregate -- ack
            # so the workflow terminates. (Discovery is num_rounds=2 and never gets here.)
            result = {}
            return self.get_shareable_data(result, fl_ctx, metadata={"round": round_idx+1})

        else:
            raise Exception(f"Invalid round {round_idx}")

        return self.get_shareable_data(result, fl_ctx, metadata={"round": fl_ctx.get_prop(AppConstants.CURRENT_ROUND)+1})
