from datetime import datetime
import os
import sys
import json
import subprocess
import threading
import traceback
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Iterable
from urllib.parse import urlparse

from nvflare.apis.event_type import EventType
from nvflare.apis.shareable import Shareable, make_reply
from nvflare.apis.signal import Signal
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey, ReturnCode
from nvflare.apis.dxo import DXO, DataKind, from_shareable
from nvflare.apis.fl_constant import FLContextKey
from nvflare.app_common.app_constant import AppConstants

from duality_nvflare_apis.stat_analytics import StatAnalyticsManager
from duality_nvflare_apis.HEExecutor import HEExecutor
from duality_nvflare_apis.HEAggregator import KEY_PQC_KEY_PACKAGE
from duality_nvflare_apis.utils import (
    ENC_BIOMARKER_RISK_GROUP_COMPUTATION,
    ENC_BIOMARKER_SCORE_CACHE,
    ENC_BIOMARKER_POSTPROCESS_TYPES,
    ENC_BIOMARKER_ROUND2_ACK_TYPES,
)
from duality_nvflare_apis.stat_analytics_event_type import (
    PROFILE_SNAPSHOT_EVENT,
    StatAnalyticsEventType,
)
from duality_nvflare_apis.FHIRBaseConfigResolver import FHIRBaseConfigResolver
from duality_nvflare_apis.utils import resolve_biomarker_model_paths, load_weights_dataframe

import pickle

import faulthandler

faulthandler.enable(all_threads=True)
# dump_traceback_later(120, repeat=True) spams "Timeout (0:02:00)!" (faulthandler, not app timeout).

# Mirror of app.core.mysql.SupportedFunction.MODEL_TYPE_ENCRYPTED (the backend stamps this
# string into workflow workload_args; the NVFlare runtime cannot import app.core).
MODEL_TYPE_ENCRYPTED = "Encrypted"

def _dbg(msg: str):
    """Central debug printer with a consistent prefix."""
    print(f"[DEBUG][AnalyticsExecutor] {msg}", flush=True)


def _bump_suffix(value: str) -> str:
    s = str(value)
    m = re.match(r"^(.*)_(\d+)$", s)
    if m:
        return f"{m.group(1)}_{int(m.group(2)) + 1}"
    return f"{s}_2"


def _extract_workflow_id(fl_ctx: FLContext) -> Optional[str]:
    try:
        task_data = fl_ctx.get_prop(ReservedKey.TASK_DATA, None) or {}
        headers = task_data.get("__headers__", {}) or {}
        cookie_jar = headers.get("__cookie_jar__", {}) or {}
        workflow_id = cookie_jar.get("__workflow__")
        if isinstance(workflow_id, str) and workflow_id.strip():
            return workflow_id.strip()
    except Exception:
        return None
    return None


def _is_url(value: Optional[str]) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)



def _normal_csv_column_name(value: Any) -> str:
    return str(value).replace("\ufeff", "").strip().lower()


def _model_type_aliases(model_type: Any) -> set[str]:
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


def _select_model_cutoff_row(cutoff_df, model_type: Any = None):
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
    candidate_columns: Iterable[str],
    *,
    model_type: Any = None,
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


# --------------------
# Progress code mapping (all numeric; friendly strings live only on the backend)
# Reduced to single, consolidated emits. No ROUND_BEGIN/ROUND_END, no *_BEGIN/_DONE pairs.
# --------------------
PROGRESS_CODE = {
    "JOB_RECEIVED": 100,

    "KEYGEN": 101,

    # sample-count pre-pass (workflow_threshold_samples_*)
    "THRESHOLD_SAMPLES": 102,

    # params parsed from DXO
    "PARAMS_LOADED": 300,

    # reference (clear-text) path (single)
    "REF_PREPROCESS": 410,

    # encrypted path (HE) local prep (single)
    "HE_PREPROCESS": 420,

    # HE encrypt / decrypt (single)
    "ENCRYPT": 400,
    "DECRYPT": 500,

    # postprocess (single)
    "POSTPROCESS": 600,

    # artifacts
    "WRITE_RESULTS_JSON": 702,

    "EXCEPTION_ENCOUNTERED": 900
}


DATASOURCE_LOOKUP_TOPIC = "duality.datasource.lookup"
DATASOURCE_LOOKUP_TIMEOUT = 30.0


class AnalyticsExecutor(HEExecutor):
    # ------------------------------------------------------------------
    # Progress emission helper: craft ANALYTIC DXO and fire 'analytix_log_stats'
    # ------------------------------------------------------------------
    # We keep using ConvertToFedEvent (client config) to republish local
    # "analytix_log_stats" as "fed.analytix_log_stats".
    #
    # directly craft the ANALYTIC DXO payload so the server sees exactly: {tag, global_step, scalars:{...}}.
    def _emit_progress(self, fl_ctx: FLContext, tag: str, scalars: Dict[str, Any], step: int = -1) -> None:
        """Emit progress by crafting an ANALYTIC DXO and firing 'analytix_log_stats'.

        - Only numeric items are kept in `scalars`. Non-numeric values are dropped.
        - Puts the DXO Shareable into FLContextKey.EVENT_DATA (private, non-sticky).
        - Fires the non-fed event; AnalyticsSender + ConvertToFedEvent do the rest.
        """
        try:
            numeric_scalars: Dict[str, float] = {}
            for k, v in (scalars or {}).items():
                if isinstance(v, bool):
                    numeric_scalars[k] = 1.0 if v else 0.0
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric_scalars[k] = float(v)

            if not numeric_scalars:
                numeric_scalars = {"heartbeat": 1.0}

            function_name = None

            if self.analytics_manager.computation_type is not None:
                function_name = self.analytics_manager.computation_type

            payload: Dict[str, Any] = {
                "tag": tag,
                "global_step": int(step) if step is not None else -1,
                "scalars": numeric_scalars,
            }
            if function_name:
                payload["function"] = function_name

            dxo = DXO(data_kind=DataKind.ANALYTIC, data=payload)
            shareable = dxo.to_shareable()

            fl_ctx.set_prop(FLContextKey.EVENT_DATA, shareable, private=True, sticky=False)
            engine = fl_ctx.get_engine()
            engine.fire_event("analytix_log_stats", fl_ctx)

            _dbg(f"emit_progress: fired analytix_log_stats payload={payload}")
        except Exception:
            _dbg("_emit_progress failure:\n" + traceback.format_exc())


    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(
        self,
        # OpenFHE parameters
        leader_client_name: str = "site1",
        mult_depth = 0,
        cc_batch_size = None,
        scale_mod_size = 53,
        scaling_technique = "FLEXIBLEAUTO",
        key_switch_technique = "BV",
        ckks_data_type = "REAL",
        generate_mult_keys: bool = False,
        generate_sum_keys: bool = False,
        generate_index_keys: bool = False,
        indices: list = [],
        # For Statistic Analytics toolset
        stat_data_path: str = None,
        filters_path: str = None
    ):
        """Initializes the AnalyticsExecutor.

        This executor handles client-side tasks for statistical analytics workflows,
        supporting both clear-text and homomorphically encrypted computations.

        Args:
            leader_client_name: Name of the client designated as leader for HE operations.
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
            stat_data_path: Base path to the statistical data file for analytics.
        """
        super().__init__(
            leader_client_name=leader_client_name,
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

        self.analytics_manager = StatAnalyticsManager(
            stat_data_path=stat_data_path
        )
        self.filters_path = filters_path

        self.init_emitted = False
        self.flag_calc_local_result = True  # Flag used to calculate local data only result.
        self.filters_data: Dict[str, Any] = {}
        self.project_id: Optional[int] = None
        self.datasource_group_id: Optional[int] = None
        self.datasource_resolved = False
        self._bg_threads: list = []

    def _warm_records_cache_async(self, stat_data_path, cancer_type, biomarker_covariates, filters, label, site=None, profiler=None):
        """Warm the process-level biomarker-records cache off the FL critical path.

        A non-contributing initiator's covariate load is dead for the *federated* result
        but is reused by its later local KM scoring (Initiator view). Running it on a
        daemon thread overlaps the cohort load with the server's aggregation of the
        contributing clients + the downstream workflows, so the later stat_analytics
        scoring hits a warm cache instead of paying the cold load on the critical path.
        Best-effort: local_pre_get_biomarker_records single-flights on the cache key, so a
        later reader coordinates with this warm rather than double-loading. Args are
        captured by value here because self.analytics_manager is reset per workflow.
        """
        def _run():
            import time as _time
            t0w, t0m = _time.time(), _time.monotonic()
            try:
                from duality_nvflare_apis.utils import local_pre_get_biomarker_records
                local_pre_get_biomarker_records(
                    stat_data_path, cancer_type=cancer_type,
                    biomarker_covariates=biomarker_covariates, filters=filters)
                _dbg(f"[bg] {label}: records cache warmed")
            except Exception:
                _dbg(f"[bg] {label}: cache warm failed:\n{traceback.format_exc()}")
            finally:
                # Record the background span so the timeline shows this load overlapping
                # the server's work rather than disappearing off the critical path.
                if profiler is not None and site:
                    try:
                        profiler.record_async_span(
                            site, "__background__", f"bg:{label}",
                            t0w, _time.time(), t0m, _time.monotonic())
                    except Exception:
                        _dbg("[bg] record_async_span failed:\n" + traceback.format_exc())
        t = threading.Thread(target=_run, name=f"warm-{label}", daemon=True)
        t.start()
        self._bg_threads.append(t)

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        """Handles events triggered by the NVFlare framework.

        Specifically, this method listens for the `START_RUN` event to dynamically
        configure the path to the client's specific data file based on its name
        (e.g., 'site1' uses 'data_filtered_1.csv').

        Args:
            event_type: The type of event being handled.
            fl_ctx: The FLContext providing runtime information.
        """
        if event_type == EventType.ABOUT_TO_END_RUN:
            # Join background records-cache warms here -- the Profiler also flushes its
            # trace on ABOUT_TO_END_RUN, so joining now gives a straggler warm's span a
            # chance to land in the trace instead of an already-dumped one.
            for t in getattr(self, "_bg_threads", []) or []:
                try:
                    t.join(timeout=30)
                except Exception:
                    pass

        if event_type == EventType.START_RUN:

            client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
            _dbg(f"START_RUN for client={client_name}")

            package_status_result = self.check_and_install()
            _dbg(f"Dependency check result: {package_status_result}")
            if package_status_result["status"] != "ok":
                raise Exception(f"[{client_name}] Fail: Dependencies missing and could not be installed. {package_status_result['message']}")

            if self.filters_path is not None:
                resolved, searched = self._resolve_filters_path(fl_ctx)
                _dbg(f"Filters path requested: {self.filters_path} | resolved={resolved} | searched={searched}")
                self.filters_data: Dict[str, Any] = {}
                if resolved and resolved.exists():
                    try:
                        self.filters_data = json.loads(Path(resolved).read_text())
                    except Exception:
                        raise Exception(f"[{client_name}] Fail: Filter not found or invalid filter file at {resolved}")
                self.analytics_manager.filters = self.filters_data.get("conditions", [])
                _dbg(f"Filters extracted: {self.analytics_manager.filters}")

                project_entry = self.filters_data.get("project") or {}
                project_id = project_entry.get("id")

                selected_datasource_group = project_entry.get("selected_datasource_group") or {}
                datasource_group_id = selected_datasource_group.get("id")

                try:
                    self.project_id = int(project_id) if project_id is not None else None
                except (TypeError, ValueError):
                    self.project_id = None

                try:
                    self.datasource_group_id = int(datasource_group_id) if datasource_group_id is not None else None
                except (TypeError, ValueError):
                    self.datasource_group_id = None

                self.analytics_manager.stat_data_path = None
                self.datasource_resolved = False
                _dbg(
                    "analytics_executor: datasource will be requested from NVFlare server "
                    f"for project_id={self.project_id}, datasource_group_id={self.datasource_group_id}"
                )


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
            _dbg(f"Pip installing missing packages: {missing}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            return {"status": "ok", "message": f"Installed missing packages: {missing}"}
        except Exception as e:
            return {"status": "fail", "message": f"Could not install: {missing} | {e}"}

    def _resolve_filters_path(self, fl_ctx: FLContext) -> Tuple[Optional[Path], Iterable[Path]]:
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

    def _get_aux_reply(self, replies):
        if isinstance(replies, Shareable):
            return replies
        if isinstance(replies, dict) and replies:
            for reply in replies.values():
                if isinstance(reply, Shareable):
                    return reply
        return None

    def _request_datasource_from_server(self, client_name: str, fl_ctx: FLContext) -> str:
        if self.project_id is None:
            raise Exception(f"[{client_name}] Fail: project_id is required before datasource lookup.")

        engine = fl_ctx.get_engine()
        if engine is None:
            raise Exception(f"[{client_name}] Fail: NVFlare engine is not available for datasource lookup.")

        request = Shareable({
            "client_name": client_name,
            "project_id": self.project_id,
            "datasource_group_id": self.datasource_group_id,
        })

        _dbg(
            "requesting datasource from NVFlare server "
            f"topic={DATASOURCE_LOOKUP_TOPIC} client={client_name} "
            f"project_id={self.project_id} datasource_group_id={self.datasource_group_id}"
        )

        try:
            replies = engine.send_aux_request(
                targets=None,
                topic=DATASOURCE_LOOKUP_TOPIC,
                request=request,
                timeout=DATASOURCE_LOOKUP_TIMEOUT,
                fl_ctx=fl_ctx,
                optional=False,
                secure=False,
            )
        except TypeError:
            replies = engine.send_aux_request(
                topic=DATASOURCE_LOOKUP_TOPIC,
                request=request,
                timeout=DATASOURCE_LOOKUP_TIMEOUT,
                fl_ctx=fl_ctx,
                optional=False,
                secure=False,
            )

        reply = self._get_aux_reply(replies)
        if reply is None:
            raise Exception(f"[{client_name}] Fail: datasource lookup did not receive a server reply.")

        rc = reply.get_return_code(ReturnCode.ERROR)
        status = reply.get("status")
        if rc != ReturnCode.OK or status != "SUCCESS":
            error_message = reply.get("error") or f"status={status}, rc={rc}"
            raise Exception(f"[{client_name}] Fail: datasource lookup failed: {error_message}")

        source = reply.get("source")
        if not isinstance(source, str) or not source.strip():
            raise Exception(f"[{client_name}] Fail: datasource lookup reply did not include source.")

        return source.strip()

    def _ensure_datasource_ready(self, client_name: str, fl_ctx: FLContext) -> None:
        stat_data_source = self.analytics_manager.stat_data_path
        if isinstance(stat_data_source, str) and stat_data_source.strip():
            return

        # Simulator: resolve locally from DUALITY_CLIENT_SITE*_DATASOURCE_<suffix> (.env.local),
        # bypassing the backend lookup that de59318b introduced. Deployment (FL_IS_SIMULATOR unset)
        # is unchanged -- it still uses the runtime server lookup. The sim resolver keys off
        # client_name + DUALITY_SIM_DATASOURCE_VERSION, so no project_id / filters.json is needed.
        if os.getenv("FL_IS_SIMULATOR", "").strip().lower() in ("1", "true", "yes", "on"):
            sim_source = FHIRBaseConfigResolver._resolve_simulator_datasource_path(client_name)
            if not sim_source:
                suffix = os.getenv("DUALITY_SIM_DATASOURCE_VERSION", "2_1")
                frag = FHIRBaseConfigResolver._site_key_fragment(client_name)
                raise Exception(
                    f"[{client_name}] Fail: simulator datasource not set. "
                    f"Define DUALITY_CLIENT_{frag}_DATASOURCE_{suffix} in .env.local."
                )
            stat_data_source = FHIRBaseConfigResolver._expand_relative_datasource_path(sim_source)
        else:
            stat_data_source = self._request_datasource_from_server(client_name, fl_ctx)

        self.analytics_manager.stat_data_path = stat_data_source
        self.datasource_resolved = True

        if self.project_id is not None:
            try:
                FHIRBaseConfigResolver.register_project_base(
                    project_id=self.project_id,
                    datasource_value=stat_data_source,
                    datasource_group_id=self.datasource_group_id,
                )
            except Exception:
                _dbg("register_project_base failed:\n" + traceback.format_exc())

        _dbg(f"analytics_executor: analytics_manager.stat_data_path = {self.analytics_manager.stat_data_path}")

        if _is_url(stat_data_source):
            _dbg(f"analytics_executor: using FHIR endpoint data source: {stat_data_source}")
        elif os.path.exists(stat_data_source):
            _dbg(f"analytics_executor: using local file data source: {stat_data_source}")
        else:
            raise Exception(f"[{client_name}] Fail: analytics_executor: analytics_manager.stat_data_path invalid: {stat_data_source}")

    def _write_json(self, fl_ctx: FLContext, rel_path: str, payload: Dict[str, Any]) -> None:
        job_id = fl_ctx.get_job_id()

        workflow_name = fl_ctx.get_prop("duality_workflow_ts")
        if not workflow_name:
            workflow_name = _extract_workflow_id(fl_ctx) or "workflow_1"

        root = Path("job-results") / str(job_id) / str(self.analytics_manager.computation_type) / str(workflow_name)
        out_file = (root / rel_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to write JSON to {out_file}: {e}") from e

    def _write_exception_json(
        self,
        fl_ctx: FLContext,
        *,
        stage: str,
        task_name: Optional[str],
        dxo: Optional[DXO],
        e: Exception
    ) -> None:
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        round_idx = None
        try:
            if dxo is not None:
                round_idx = dxo.get_meta_prop("round")
        except Exception:
            round_idx = None

        payload: Dict[str, Any] = {
            "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "job_id": fl_ctx.get_job_id() if hasattr(fl_ctx, "get_job_id") else None,
            "client": client_name,
            "task": task_name,
            "round": round_idx,
            "stage": stage,
            "exception_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }

        try:
            self._write_json(fl_ctx, f"client/{client_name}/error.json", payload)
        except Exception:
            pass

        try:
            self._emit_progress(
                fl_ctx,
                tag="job_progress",
                scalars={"round": round_idx if round_idx is not None else -1, "code": PROGRESS_CODE["EXCEPTION_ENCOUNTERED"]},
                step=round_idx if round_idx is not None else -1,
            )
        except Exception:
            pass

    def _compute_local_meta_analysis_view(self) -> Optional[Dict[str, Any]]:
        """Compute a fully-local meta-analysis view from this client's own data.

        Returns the dict to write to ``local/local_results.json``, or ``None`` to
        signal "do not write" (e.g. this client has no local patient data) so a
        contributing client's earlier write isn't clobbered.

        The local view uses *this client's* (μ, σ) over its ``cached_risk_scores``
        — not the federated aggregate the upstream mean-stdev workflow stored on
        the manager — so the per-user "Initiator" panel is each client's
        standalone read on its own data, independent of who is contributing.
        Single-client meta-analysis collapses to (β₁, SE) of the local fit.
        """
        import math as _math
        import numpy as np
        from duality_nvflare_apis.utils import local_pre_logistic_regression_with_global_zscore
        from scipy import stats as _scipy_stats

        am = self.analytics_manager
        scores = am.cached_risk_scores
        if scores is None or len(scores) == 0:
            return None

        arr = np.asarray(scores, dtype=float)
        local_mu = float(arr.mean())
        ddof = 1 if getattr(am, "std_type", "sample") == "sample" else 0
        local_sigma = float(arr.std(ddof=ddof))
        if not _math.isfinite(local_sigma) or local_sigma <= 0.0:
            return None

        try:
            fit = local_pre_logistic_regression_with_global_zscore(
                stat_data_path=am.stat_data_path,
                filters=am.filters,
                time_col=am.time_column_id,
                censoring_col=am.censoring_column_id,
                horizon_threshold=am.horizon_threshold,
                risk_scores=scores,
                score_mean=local_mu,
                score_std=local_sigma,
                model_key=am.model_key,  # match the aggregated path's cox_lasso β₁ flip
            )
        except Exception:
            return None

        beta1 = None if fit is None else fit.get("beta1")
        se_beta1 = None if fit is None else fit.get("se_beta1")
        # NaN comparisons are all False, so an isfinite check is required ahead of
        # the ``< 1e-10`` degeneracy test: statsmodels.Logit can converge to NaN
        # coefficients on a near-singular Hessian, which would otherwise reach the
        # output JSON as the literal token ``NaN`` and break the frontend's parse.
        try:
            beta1_f = float(beta1) if beta1 is not None else None
            se_beta1_f = float(se_beta1) if se_beta1 is not None else None
        except (TypeError, ValueError):
            beta1_f = None
            se_beta1_f = None
        if (
            beta1_f is None
            or se_beta1_f is None
            or not _math.isfinite(beta1_f)
            or not _math.isfinite(se_beta1_f)
            or se_beta1_f < 1e-10
        ):
            return None

        z = beta1_f / se_beta1_f
        p_value = float(2.0 * _scipy_stats.norm.sf(abs(z)))
        # Same keys the aggregated path emits, so the frontend card renders the
        # local view with no per-source remapping.
        return {
            "status": "OK",
            "meta_beta1": beta1_f,
            "meta_se_beta1": se_beta1_f,
            "z": float(z),
            "p_value": p_value,
            "ci_lower": beta1_f - 1.96 * se_beta1_f,
            "ci_upper": beta1_f + 1.96 * se_beta1_f,
            "total_inv_var": 1.0 / (se_beta1_f * se_beta1_f),
            "local_mu": local_mu,
            "local_sigma": local_sigma,
            "n_scores": int(len(scores)),
        }

    # ------------------------------------------------------------------
    # Executor API
    # ------------------------------------------------------------------
    def execute(self, task_name: str, shareable: Shareable, fl_ctx: FLContext, abort_signal: Signal) -> Shareable:
        """Main entry point for task execution on the client.

        This method acts as a dispatcher, routing incoming tasks to their respective
        handler methods based on the `task_name`. It first attempts to handle
        common HE tasks (like key exchange) via the parent `HEExecutor`. If not
        handled, it then routes to a specific analytics task handler.

        Args:
            task_name: The name of the task to be executed.
            shareable: The Shareable object received from the server.
            fl_ctx: The FLContext for the current execution.
            abort_signal: A signal to indicate if the task should be aborted.

        Returns:
            A Shareable object containing the results of the task execution.
        """

        dxo = None

        try:
            if self.init_emitted == False:
                self.init_emitted = True
                try:
                    self._emit_progress(
                        fl_ctx,
                        tag="job_progress",
                        scalars={"code": PROGRESS_CODE["JOB_RECEIVED"]},
                        step=-1,
                    )
                except Exception:
                    _dbg("init_emitted emit failed:\n" + traceback.format_exc())

            client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
            _dbg(f"execute: task={task_name} client={client_name}")

            if abort_signal.triggered:
                _dbg("execute: abort_signal triggered, returning empty Shareable")
                return Shareable()

            try:
                dxo = from_shareable(shareable)
            except Exception as e:
                _dbg("execute: from_shareable failed:\n" + traceback.format_exc())
                self._write_exception_json(fl_ctx, stage="from_shareable", task_name=task_name, dxo=None, e=e)
                return make_reply(ReturnCode.OK)

            if dxo is None:
                _dbg("execute: dxo is None (unexpected)")
                self._write_exception_json(fl_ctx, stage="from_shareable:dxo_none", task_name=task_name, dxo=None, e=Exception("dxo is None"))
                return make_reply(ReturnCode.OK)

            if task_name in (
                "task_reference_stat_analytics",
                "task_stat_analytics",
                "task_threshold_samples_unsecure",
                "task_threshold_samples_secure",
                "task_enc_biomarker_disc",
                "task_enc_biomarker_score_cache",
                "task_enc_biomarker_score_postprocess",
                "task_enc_biomarker_risk_group_postprocess",
            ):
                self._ensure_datasource_ready(client_name, fl_ctx)

            # PQC routing: on first task after KeyGen, receive and store AES session key if this client gets its key package.
            if (
                task_name != "task_KeyGen"
                and dxo.data
                and KEY_PQC_KEY_PACKAGE in dxo.data
                and self.hide_result_from_server
                and client_name != self.leader_client_name
            ):
                pqc = self._get_pqc_manager(client_name)
                if pqc is not None and not pqc.is_coordinator:
                    pkg = dxo.data[KEY_PQC_KEY_PACKAGE]
                    if isinstance(pkg, (list, tuple)) and len(pkg) == 3:
                        try:
                            pqc.receive_key_package(pkg[0], pkg[1], pkg[2])
                        except Exception as e:
                            self.custom_logger.warning(f"[{client_name}] PQC receive_key_package failed: {e}")

            round_idx = None
            try:
                round_idx = dxo.get_meta_prop("round")
            except Exception:
                round_idx = None

            if round_idx == 0 and task_name in ("task_reference_stat_analytics", "task_stat_analytics"):
                workflow_name = _extract_workflow_id(fl_ctx) or "workflow_1"
                fl_ctx.set_prop("duality_workflow_ts", workflow_name, private=True, sticky=True)

            try:
                if task_name == "task_KeyGen":
                    round_idx = dxo.get_meta_prop("round")
                    self._emit_progress(
                        fl_ctx,
                        tag="job_progress",
                        scalars={"round": round_idx, "code": PROGRESS_CODE["KEYGEN"]},
                        step=-1,
                    )
                elif task_name.startswith("task_threshold_samples"):
                    # Emitted here rather than in _task_threshold_samples so a client excluded
                    # from contributing (which returns before doing any work) still reports the
                    # round it took part in.
                    self._emit_progress(
                        fl_ctx,
                        tag="job_progress",
                        scalars={"round": round_idx, "code": PROGRESS_CODE["THRESHOLD_SAMPLES"]},
                        step=-1,
                    )

                result = super().execute(task_name, shareable, fl_ctx, abort_signal)
                if result is not None:
                    _dbg("execute: handled by HEExecutor, returning upstream result")
                    return result
                else:
                    _dbg("execute: not handled by HEExecutor; dispatching to analytics tasks")
            except Exception as e:
                _dbg("execute: super().execute raised:\n" + traceback.format_exc())
                self._write_exception_json(fl_ctx, stage="super().execute", task_name=task_name, dxo=dxo, e=e)
                return make_reply(ReturnCode.OK)

            try:
                if task_name.startswith("task_threshold_samples"):
                    return self._task_threshold_samples(dxo, fl_ctx, task_name)
                elif task_name == "task_reference_stat_analytics":
                    return self._task_reference_stat_analytics(dxo, fl_ctx, abort_signal)
                elif task_name == "task_stat_analytics":
                    return self._task_stat_analytics(dxo, fl_ctx, abort_signal)
                elif task_name == "task_profile_consolidate":
                    return self._task_profile_consolidate(dxo, shareable, fl_ctx, abort_signal)
                elif task_name == "task_model_upload":
                    return self._task_model_upload(dxo, fl_ctx, abort_signal)
                elif task_name in ("task_enc_biomarker_disc", "task_enc_biomarker_score_cache", "task_enc_biomarker_score_postprocess", "task_enc_biomarker_risk_group_postprocess"):
                    # The split score-cache producer's client side is identical to discovery
                    # round 0 (encrypt covariates); it just never runs a decrypt round
                    # (num_rounds=1). The split postprocess consumers (LCS score + KM risk-group)
                    # instead upload NO covariates (the producer already cached the packed score)
                    # and join only the decrypt round(s). _task_enc_biomarker_disc recognizes all
                    # split computation_types and routes each accordingly.
                    return self._task_enc_biomarker_disc(dxo, fl_ctx, abort_signal)
                else:
                    self.log_error(fl_ctx, f"Unknown task: {task_name}")
                    _dbg(f"execute: unknown task={task_name}")
                    return make_reply(ReturnCode.TASK_UNKNOWN)
            except Exception as e:
                _dbg("execute: task dispatch raised:\n" + traceback.format_exc())
                self._write_exception_json(fl_ctx, stage="dispatch", task_name=task_name, dxo=dxo, e=e)
                return make_reply(ReturnCode.OK)

        except Exception as e:
            _dbg("execute: OUTER EXCEPTION\n" + traceback.format_exc())
            self._write_exception_json(fl_ctx, stage="execute", task_name=task_name, dxo=dxo, e=e)
            return make_reply(ReturnCode.OK)

    # ------------------------------------------------------------------
    # Task: Threshold Samples
    # ------------------------------------------------------------------
    def _task_threshold_samples(self, dxo, fl_ctx, task_name):
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        round_idx = dxo.get_meta_prop("round")
        if round_idx == 0:
            non_contributing = dxo.get_meta_prop("non_contributing_clients") or []
            if client_name in non_contributing: # TODO: Exclude non-contributing clients from the num_client mask calculation; counting them wastes noise budget.
                return self.get_shareable_data({}, fl_ctx)

            self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
            depth_required = dxo.get_meta_prop("depth_required", None)
            threshold = dxo.get_meta_prop("workload_args")["min_global_samples"]
            workload_args=dxo.get_meta_prop("workload_args")["workflows"]
            generated_args=dxo.get_meta_prop("generated_args")
            merged_args = {}
            # Important: Order of keys in this dict really matters even though dicts are not ordered.
            # We want the handle_pre_count to return a list of count of workflows in the order that's mentioned in config file's workload_args.
            # This makes sure that we are adding up the same index of counts across all data owners.
            for k in list(workload_args.keys()):
                merged_args[k] = {**workload_args.get(k, {}), **generated_args.get(k, {})}
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)
            self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
            try:
                weights = self.analytics_manager.handle_pre_count(merged_args, threshold)
            finally:
                self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
            forced_count = os.environ.get("DUALITY_SIM_THRESHOLD_FORCE_COUNT", "").strip()
            if forced_count:
                # TEST/DEVELOPMENT ONLY: pretend every workflow counted this many local
                # rows so the below-threshold verdict path can be exercised end-to-end on
                # datasets whose real cohorts never fall under the threshold (only the
                # general-statistics pipeline yields genuinely small counts). Clipped the
                # same way pre_count clips. Absent in production deployments.
                weights["count"] = [min(int(forced_count), threshold)] * len(workload_args)
            if task_name == "task_threshold_samples_secure":
                self.analytics_manager.computation_type = "_PRE_COUNT_SECURE_"
                def multiplicative_mask(num_clients, sigma_val, B_val):
                    import numpy as np
                    import math
                    # TEST/DEVELOPMENT ONLY: force the total mask exponent (sum of the
                    # per-site z) to a fixed value so one simulator run exercises an
                    # extreme mask product deterministically instead of sampling a
                    # ~1% tail. The normal clip still applies, so the forced draw can
                    # never exceed what production could produce. Absent in production.
                    forced_total_z = os.environ.get("DUALITY_SIM_THRESHOLD_MASK_Z", "").strip()
                    if forced_total_z:
                        z_val = float(forced_total_z) / num_clients
                    else:
                        scale_val = sigma_val / math.sqrt(num_clients)
                        z_val = np.random.normal(loc=0.0, scale=scale_val)
                    z_clip_val = max(-1 * B_val / num_clients, min(B_val / num_clients, z_val))
                    rm = np.exp(z_clip_val)
                    return rm
                rm_share = [multiplicative_mask(num_clients=len(fl_ctx.get_engine().get_clients()), sigma_val=generated_args["sigma_val"], B_val=generated_args["B_val"]) for _ in range(len(workload_args))]
                weights["rm_share"] = rm_share
                self.fire_event(StatAnalyticsEventType.ENCRYPT_START, fl_ctx)
                try:
                    enc_weights = self.openfhe_manager.exec_encrypt_stat_analytics(round_idx, "_PRE_COUNT_SECURE_", weights, depth_required)
                finally:
                    self.fire_event(StatAnalyticsEventType.ENCRYPT_END, fl_ctx)
            else:
                self.analytics_manager.computation_type = "_PRE_COUNT_UNSECURE_"
                self.fire_event(StatAnalyticsEventType.ENCRYPT_START, fl_ctx)
                try:
                    enc_weights = self.openfhe_manager.exec_encrypt_stat_analytics(round_idx, "_PRE_COUNT_UNSECURE_", weights, depth_required)
                finally:
                    self.fire_event(StatAnalyticsEventType.ENCRYPT_END, fl_ctx)
        elif round_idx == 1:
            self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
            try:
                enc_weights = self.openfhe_manager._decrypt_stat_analytics_single_shares("_PRE_COUNT_UNSECURE_",   # Both secure and unsecure use same decryption logic
                                                                    dxo.data["enc_result"],
                                                                    self.arch,
                                                                    client_name,
                                                                    fl_ctx.get_prop(ReservedKey.CLIENT_NAME) == self.leader_client_name)
            finally:
                self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)
            self.analytics_manager.computation_type = None  # Reset computation type after workflow completion.
        else:
            raise Exception(f"[{client_name}] Invalid round {round_idx}.")
        return self.get_shareable_data(enc_weights, fl_ctx)

    # ------------------------------------------------------------------
    # Task: Reference (clear-text) Analytics
    # ------------------------------------------------------------------
    def _task_reference_stat_analytics(self, dxo, fl_ctx, abort_signal: Signal):
        """Handles the client-side logic for the clear-text statistical analytics task.

        Two-round workflow:
        - Round 0: Load params, preprocess local data (clear), return stats.
        - Round 1: Receive aggregated global statistics, post-process, write artifact.
        """
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        round_idx = None
        try:
            round_idx = dxo.get_meta_prop("round")
        except Exception:
            _dbg("_task_reference_stat_analytics: failed to read round:\n" + traceback.format_exc())
        _dbg(f"_task_reference_stat_analytics: client={client_name} round={round_idx}")

        weights = {}
        try:
            if round_idx == 0:
                self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
                # Extract relevant properties from the DXO
                self.analytics_manager.reset_computation_props()
                self.analytics_manager.set_props_from_init_load(workload_args=dxo.get_meta_prop("workload_args"), generated_args=dxo.get_meta_prop("generated_args"))
                if self.analytics_manager.computation_type == "biomarker_score_computation":
                    # Start of a new model_key chain — the open-access chain always
                    # begins with clear-text scoring. reset_computation_props
                    # deliberately PRESERVES the chain-shared cache so it can flow
                    # score-comp -> mean-stdev -> meta-analysis within one chain, but
                    # a job that emits two chains (e.g. cox_lasso + logistic_reg both
                    # selected on the workflow-groups page) would otherwise let the
                    # second chain inherit the first chain's cached state, collapsing
                    # both models' Initiator/local views (and the fused fit) onto the
                    # first chain's data. Drop everything chain-local here — mirrors
                    # the reset in _task_enc_biomarker_disc round 0 for the encrypted
                    # chain.
                    self.analytics_manager.cached_risk_scores = None
                    self.analytics_manager.cached_scores_model_key = None
                    self.analytics_manager.cached_scores_mean = None
                    self.analytics_manager.cached_scores_std = None
                    self.analytics_manager.cached_lr_fit = None
                    self.analytics_manager._fused_lr_fit_status = None
                    # Open-access chain: every client scores from the broadcast model, so
                    # the encrypted-chain result suppression must not apply.
                    self._enc_chain_active = False
                self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["PARAMS_LOADED"]},
                    step=round_idx if round_idx is not None else -1,
                )

                _dbg(f"_task_reference_stat_analytics r0: params set; preprocessing reference")
                self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
                try:
                    weights = self.analytics_manager.preprocess_reference()
                finally:
                    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["REF_PREPROCESS"]},
                    step=round_idx if round_idx is not None else -1,
                )

                # Non-contributing clients still run preprocess_reference above
                # (so their own scores/fit are cached for their local view) but
                # must NOT contribute a share to the clear-text reference
                # aggregation — mirroring the encrypted path's round-0 skip in
                # _task_stat_analytics. The aggregator's accept() drops empty
                # shares (HEAggregator: ``if dxo.data and dxo.data != {}``), so
                # returning {} excludes this client from aggregate_reference.
                non_contributing = dxo.get_meta_prop("non_contributing_clients") or []
                if client_name in non_contributing:
                    weights = {}

            elif round_idx == 1:
                _dbg(f"_task_reference_stat_analytics r1: postprocess_reference")
                self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                try:
                    result = self.analytics_manager.postprocess_reference(dxo.data)
                finally:
                    self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)
                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["POSTPROCESS"]},
                    step=round_idx if round_idx is not None else -1,
                )
                _dbg(f"_task_reference_stat_analytics r1: final result keys={list(result.keys()) if isinstance(result, dict) else type(result)}")
                if isinstance(result, dict):
                    self._write_json(fl_ctx, "aggregated/processed_results.json", result)
                    self._emit_progress(
                        fl_ctx, "job_progress",
                        {"round": round_idx, "code": PROGRESS_CODE["WRITE_RESULTS_JSON"]},
                        step=round_idx if round_idx is not None else -1,
                    )
                _dbg(f"[{client_name}] Final reference result: {result}")
                self.analytics_manager.computation_type = None

            else:
                raise Exception(f"[{client_name}] Invalid round {round_idx} for reference analytics task.")
        except Exception:
            _dbg("_task_reference_stat_analytics: EXCEPTION\n" + traceback.format_exc())
            raise

        return self.get_shareable_data(weights, fl_ctx)

    # ------------------------------------------------------------------
    # Task: Encrypted (HE) Analytics
    # ------------------------------------------------------------------
    def _task_stat_analytics(self, dxo, fl_ctx, abort_signal: Signal):
        """Handles the client-side logic for the encrypted statistical analytics task.

        Three-round workflow using homomorphic encryption:
        - Round 0: Load params, preprocess local data, encrypt local stats.
        - Round 1: Participate in distributed decryption (submit decrypt share).
        - Round 2: Receive final decrypted global stats, post-process, write artifact.
        """
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        round_idx = None
        try:
            round_idx = dxo.get_meta_prop("round")
        except Exception:
            _dbg("_task_stat_analytics: failed to read round:\n" + traceback.format_exc())
        _dbg(f"_task_stat_analytics: client={client_name} round={round_idx}")

        enc_weights = {}
        try:
            if round_idx == 0:
                self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
                # Extract relevant properties from the DXO
                generated_args=dxo.get_meta_prop("generated_args")
                self._enc_biomarker_no_results = False
                if 'w_biomarker_risk_scores' in generated_args: # Code to select this client's scores and re-order serially.
                    wargs = dxo.get_meta_prop("workload_args") or {}
                    mk = str(wargs.get("model_key", "")).strip()
                    if not mk:
                        raise ValueError("workload_args.model_key is required when using persisted biomarker risk scores.")
                    risk_scores_map = generated_args['w_biomarker_risk_scores']
                    non_contributing = dxo.get_meta_prop("non_contributing_clients") or []
                    if client_name in non_contributing and (not isinstance(risk_scores_map, dict) or client_name not in risk_scores_map):
                        if client_name == self.leader_client_name:
                            # Non-contributing leader in survival biomarker discovery: it uploaded no
                            # covariates to disc_1, so the federated risk scores exclude it. It still owns
                            # the plaintext model, so score its OWN cohort locally to populate the
                            # Initiator (local) view -- the scores never leave the client and it stays out
                            # of the federated KM. Drop the (foreign) risk-scores map and inject the local
                            # model so set_props takes the risk_scores=None path and the KM preprocess
                            # scores from coeffs+cutoff (utils.local_pre_kaplan_meier). Mirrors the
                            # score-path leader (_task_enc_biomarker_disc r2 local scoring).
                            import pandas as pd
                            model_dir = os.path.dirname(os.path.abspath(__file__))
                            wcopy = {"model_key": mk, "cancer_type": wargs.get("cancer_type")}
                            resolve_biomarker_model_paths(wcopy, model_dir)
                            coeffs_df = load_weights_dataframe(wcopy["scale_coeff_file_path"])
                            cutoff_df = pd.read_csv(wcopy["cutoff_file_path"])
                            del generated_args['w_biomarker_risk_scores']
                            generated_args['coeffs'] = coeffs_df
                            generated_args['cutoff_value'] = cutoff_df.iloc[0, 0]
                            _dbg(f"[{client_name}] {wargs.get('computation_type')}: non-contributing leader in biomarker discovery; scoring locally from the plaintext model for the Initiator view (excluded from federated KM).")
                        else:
                            # Non-contributing NON-leader: the plaintext model only exists at the
                            # leader/initiator (Encrypted model_type), so this site can neither score
                            # its cohort nor display any result. Give set_props an EMPTY score list
                            # (None would trigger the plaintext-model load) and mark the workflow
                            # result-less for this client: it skips preprocess/local view/postprocess
                            # and joins only the decrypt rounds -- its partial-decrypt key share is
                            # still required by the n-of-n multiparty decryption.
                            generated_args['w_biomarker_risk_scores'] = []
                            self._enc_biomarker_no_results = True
                            _dbg(f"[{client_name}] {wargs.get('computation_type')}: non-contributing non-leader in encrypted biomarker discovery; no plaintext model on this site -- producing no results, joining decrypt rounds only.")
                    else:
                        generated_args['w_biomarker_risk_scores'] = self.openfhe_manager._remove_biomarker_mask_and_extract_scores(
                            generated_args['w_biomarker_risk_scores'][client_name], mk
                        )
                        generated_args['w_biomarker_risk_scores'] = self.analytics_manager._re_map_batched_patients_biomarker(generated_args['w_biomarker_risk_scores'], self.openfhe_manager.cc_batch_size, len(generated_args['biomarker_covariates']))
                self.analytics_manager.reset_computation_props()
                self.analytics_manager.set_props_from_init_load(workload_args=dxo.get_meta_prop("workload_args"), generated_args=generated_args)
                self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)

                exc_meta = dxo.get_meta_prop("exclude_analyzing_clients")
                self.exclude_analyzing_clients = [str(x) for x in exc_meta] if isinstance(exc_meta, (list, tuple)) else []

                depth_required = dxo.get_meta_prop("depth_required", None)

                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["PARAMS_LOADED"]},
                    step=round_idx if round_idx is not None else -1,
                )

                # The rest of the encrypted-model chain (mean-stdev over the cached scores,
                # meta-analysis over the cached fit) is equally result-less for a
                # non-contributing non-leader: it has no scores to view locally and
                # contributed no data to the federated result.
                am = self.analytics_manager
                in_score_chain = (
                    (am.computation_type == "mean-stdev" and am.over_cached_scores)
                    or (am.computation_type == "meta-analysis" and am.horizon_threshold is not None)
                )
                if (
                    not self._enc_biomarker_no_results
                    and in_score_chain
                    and getattr(self, "_enc_chain_active", False)
                    and client_name != self.leader_client_name
                    and client_name in (dxo.get_meta_prop("non_contributing_clients") or [])
                ):
                    self._enc_biomarker_no_results = True

                if self._enc_biomarker_no_results:
                    # Result-less non-contributing non-leader (see the risk-scores branch
                    # above): no preprocess, no local view, no share. set_props already ran,
                    # so computation_type is in place for the round-1 partial decryption.
                    _dbg(f"[{client_name}] {am.computation_type}: non-contributing non-leader in the encrypted-model chain; producing no results, joining decrypt rounds only.")
                    return self.get_shareable_data({}, fl_ctx)

                _dbg("_task_stat_analytics r0: preprocess()")
                self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
                try:
                    weights = self.analytics_manager.preprocess()
                finally:
                    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["HE_PREPROCESS"]},
                    step=round_idx if round_idx is not None else -1,
                )

                if self.flag_calc_local_result:
                    if self.analytics_manager.computation_type == "meta-analysis":
                        # Purely-local Initiator view: z-score this client's own
                        # cached scores against its LOCAL (μ, σ) and fit locally.
                        # The generic path below would reuse cached_lr_fit / the
                        # cached_scores_mean/std that mean-stdev set to the FEDERATED
                        # global, mixing federated state into what must be a
                        # standalone per-client read. Single-client meta-analysis
                        # collapses to (β₁, SE) of the local fit. Returns None (skip
                        # the write) when this client has no usable local view, so a
                        # contributing client's earlier write isn't clobbered.
                        local_only_result = self._compute_local_meta_analysis_view()
                        if local_only_result is not None:
                            self._write_json(fl_ctx, "local/local_results.json", local_only_result)
                    else:
                        self.fire_event(StatAnalyticsEventType.AGGREGATE_REFERENCE_START, fl_ctx)
                        try:
                            local_only_intermed_result = self.analytics_manager.aggregate_reference({}, weights)
                        finally:
                            self.fire_event(StatAnalyticsEventType.AGGREGATE_REFERENCE_END, fl_ctx)
                        self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                        try:
                            if self.analytics_manager.computation_type in ['mean', 'stdev']:
                                local_only_result = self.analytics_manager.postprocess(local_only_intermed_result)
                            else:
                                local_only_result = self.analytics_manager.postprocess_reference(local_only_intermed_result)
                            self._write_json(fl_ctx, "local/local_results.json", local_only_result)
                        finally:
                            self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)

                non_contributing = dxo.get_meta_prop("non_contributing_clients") or []
                if client_name in non_contributing:
                    _dbg(f"[{client_name}] Skipping contribution to aggregation.")
                    return self.get_shareable_data({}, fl_ctx)

                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["ENCRYPT"]},
                    step=round_idx if round_idx is not None else -1,
                )

                _dbg("_task_stat_analytics r0: encrypt")
                self.fire_event(StatAnalyticsEventType.ENCRYPT_START, fl_ctx)
                try:
                    enc_weights = self.openfhe_manager.exec_encrypt_stat_analytics(round_idx, self.analytics_manager.computation_type, weights, depth_required)
                finally:
                    self.fire_event(StatAnalyticsEventType.ENCRYPT_END, fl_ctx)

            elif round_idx == 1:
                _dbg("_task_stat_analytics r1: decrypt step")
                self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
                try:
                    enc_weights = self.openfhe_manager._decrypt_stat_analytics_single_shares(
                        self.analytics_manager.computation_type,
                        dxo.data["enc_result"],
                        self.arch,
                        client_name,
                        fl_ctx.get_prop(ReservedKey.CLIENT_NAME) == self.leader_client_name
                    )  # TODO: Support 'cc' architecture decryption; only 'star' is handled here.
                finally:
                    self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)

                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["DECRYPT"]},
                    step=round_idx if round_idx is not None else -1,
                )

                if self.hide_result_from_server and fl_ctx.get_prop(ReservedKey.CLIENT_NAME) == self.leader_client_name:
                    self.local_partial_decrypt_share = enc_weights
                    enc_weights = {}  # Leader does not send its share to server; it will inject it locally when fusing

            elif round_idx == 2:
                # postprocess aggregated - consolidated single emit; emit AFTER success
                _dbg("_task_stat_analytics r2: postprocess")
                if (
                    not self.hide_result_from_server
                    and client_name in getattr(self, "exclude_analyzing_clients", ())
                ):
                    self.analytics_manager.computation_type = None
                    return self.get_shareable_data({}, fl_ctx)
                if getattr(self, "_enc_biomarker_no_results", False):
                    # Result-less non-contributing non-leader: nothing to postprocess or
                    # display on this site. (In hide_result_from_server mode a non-leader
                    # returns {} below anyway; this covers the no-hide round-2 write.)
                    self.analytics_manager.computation_type = None
                    return self.get_shareable_data({}, fl_ctx)
                if self.hide_result_from_server:
                    if fl_ctx.get_prop(ReservedKey.CLIENT_NAME) == self.leader_client_name:
                        recv_result = dxo.data.get('result', {})
                        recv_result[client_name] = self.local_partial_decrypt_share

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
                            if time_grid and time_grid[-1] < self.analytics_manager.time_grid_max:
                                time_grid.append(self.analytics_manager.time_grid_max)
                            metadata = {"len_time_grid": len(time_grid)}

                        self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
                        try:
                            unprocessed_result = self.openfhe_manager._decrypt_stat_analytics_all_shares(self.analytics_manager.computation_type, recv_result, arch=self.arch, metadata=metadata)
                        finally:
                            self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)
                        self.local_partial_decrypt_share = None
                    else:
                        return self.get_shareable_data({}, fl_ctx)
                else:
                    unprocessed_result = dxo.data.get('result', {})

                self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                try:
                    result = self.analytics_manager.postprocess(unprocessed_result)
                finally:
                    self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)
                self._emit_progress(
                    fl_ctx, "job_progress",
                    {"round": round_idx, "code": PROGRESS_CODE["POSTPROCESS"]},
                    step=round_idx if round_idx is not None else -1,
                )
                _dbg(f"_task_stat_analytics r2: final result keys={list(result.keys()) if isinstance(result, dict) else type(result)}")
                if isinstance(result, dict):
                    self._write_json(fl_ctx, "aggregated/processed_results.json", result)
                    self._emit_progress(
                        fl_ctx, "job_progress",
                        {"round": round_idx, "code": PROGRESS_CODE["WRITE_RESULTS_JSON"]},
                        step=round_idx if round_idx is not None else -1,
                    )
                _dbg(f"[{client_name}] Final result: {result}")
                self.analytics_manager.computation_type = None

                if self.hide_result_from_server and fl_ctx.get_prop(ReservedKey.CLIENT_NAME) == self.leader_client_name:
                    self.fire_event(StatAnalyticsEventType.ENCRYPT_PQC_START, fl_ctx)
                    try:
                        # Broadcast the UNPROCESSED aggregate (not the postprocessed
                        # result) so each round-3 non-leader runs postprocess itself.
                        # That makes postprocess side effects — e.g. caching the global
                        # (mean, std) on the manager for the next chain workflow — land on
                        # every contributing client, not just the leader. Required for the
                        # meta-analysis chain under hide_result_from_server.
                        raw_vec = self._get_pqc_manager(client_name).build_payload_vector(unprocessed_result)
                        excl = set(getattr(self, "exclude_analyzing_clients", ()) or ())
                        enc_weights = {k: v for k, v in raw_vec.items() if k not in excl}
                        # Diagnostic: record exactly which non-leaders the leader produced round-3
                        # payloads for, per workflow, so any drop can be localized (leader build vs
                        # server round-2 spec vs dispatch).
                        self.custom_logger.info(
                            f"[{client_name}] PQC round 2 build ({fl_ctx.get_prop(ReservedKey.WORKFLOW)}): "
                            f"enc_weights keys={sorted(enc_weights.keys())} "
                            f"(raw_vec={sorted(raw_vec.keys())}, excl={sorted(excl)})"
                        )
                    finally:
                        self.fire_event(StatAnalyticsEventType.ENCRYPT_PQC_END, fl_ctx)

            elif round_idx == 3:
                if not self.hide_result_from_server:
                    raise Exception(f"[{client_name}] Invalid round {round_idx} for encrypted analytics task.")
                if client_name == self.leader_client_name:
                    return self.get_shareable_data({}, fl_ctx)
                if client_name in getattr(self, "exclude_analyzing_clients", ()):
                    self.analytics_manager.computation_type = None
                    return self.get_shareable_data({}, fl_ctx)
                if getattr(self, "_enc_biomarker_no_results", False):
                    # Result-less non-contributing non-leader: drop the round-3 payload
                    # unread -- this site displays nothing for the encrypted-model workflow.
                    self.analytics_manager.computation_type = None
                    return self.get_shareable_data({}, fl_ctx)

                payload = dxo.data.get("result")
                if isinstance(payload, (list, tuple)) and len(payload) == 2:
                    self.fire_event(StatAnalyticsEventType.DECRYPT_PQC_START, fl_ctx)
                    try:
                        unprocessed_result = self._get_pqc_manager(client_name).decrypt_payload(payload[0], payload[1])
                    finally:
                        self.fire_event(StatAnalyticsEventType.DECRYPT_PQC_END, fl_ctx)
                else:
                    # PQC round-3 per-client payload missing (None): the leader's per-client (nonce,
                    # ciphertext) did not reach this client. The root cause (a round-2 wait race where the
                    # server aggregated before the leader's payload submission arrived) is fixed upstream
                    # by the customSAG round-2 wait barrier; this branch remains as a defense-in-depth
                    # backstop. Fail gracefully instead of crashing the contribution (which would surface
                    # as a "not a valid DXO" REJECT and cascade): log loudly, skip postprocess, and return
                    # an empty (valid) shareable so the round completes and the rest of the job proceeds.
                    self.custom_logger.error(
                        f"[{client_name}] PQC round 3: missing per-client payload (got "
                        f"{type(payload).__name__}) for workflow "
                        f"{fl_ctx.get_prop(ReservedKey.WORKFLOW)}; skipping this combo's result for this "
                        f"run."
                    )
                    self.analytics_manager.computation_type = None
                    return self.get_shareable_data({}, fl_ctx)
                # The leader broadcast the UNPROCESSED aggregate (see round 2); postprocess
                # it locally so the side effects (e.g. cached global mean/std for the next
                # chain workflow) land on this contributing client too, and write the same
                # processed_results.json the leader produced in round 2.
                if isinstance(unprocessed_result, dict):
                    self._write_json(fl_ctx, "aggregated/unprocessed_results.json", unprocessed_result)
                self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
                try:
                    result = self.analytics_manager.postprocess(unprocessed_result)
                finally:
                    self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)
                _dbg(f"[{client_name}] Final result: {result}")
                if isinstance(result, dict):
                    self._write_json(fl_ctx, "aggregated/processed_results.json", result)
                self.analytics_manager.computation_type = None

            else:
                raise Exception(f"[{client_name}] Invalid round {round_idx} for encrypted analytics task.")
        except Exception:
            _dbg("_task_stat_analytics: EXCEPTION\n" + traceback.format_exc())
            raise

        return self.get_shareable_data(enc_weights, fl_ctx)

    def _task_model_upload(self, dxo, fl_ctx, abort_signal):
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)

        if client_name != self.leader_client_name:
            return self.get_shareable_data({}, fl_ctx)

        model_keys  = dxo.get_meta_prop("model_keys", []) or []
        cancer_type = dxo.get_meta_prop("cancer_type", "") or ""
        model_type  = dxo.get_meta_prop("model_type", "") or ""

        # At runtime the executor's cwd is the job sandbox root.
        # Stager copies CSVs into {job_id}/app_client/custom/ via _copy_biomarker_model_files_if_needed.
        # Passing this dir lets resolve_biomarker_model_paths use its fallback discovery
        # (DUALITY_SIM_BIOMARKER_MODELS_ROOT / MODEL_DIR_* / cwd walk),
        # which is the same path other call sites in this file rely on.
        model_dir = os.path.dirname(os.path.abspath(__file__))

        if model_type.strip().lower() == MODEL_TYPE_ENCRYPTED.lower():
            return self._task_model_upload_encrypted(dxo, fl_ctx, model_keys, cancer_type, model_dir)

        # Open-access: ship the raw model CSV bytes; the server writes them to disk for the
        # clear-text biomarker (kaplan-meier) consumer to read.
        model_data = {}
        for mk in model_keys:
            wcopy = {"model_key": mk, "cancer_type": cancer_type}
            resolve_biomarker_model_paths(wcopy, model_dir)
            with open(wcopy["scale_coeff_file_path"], "rb") as f:
                weights_bytes = f.read()
            with open(wcopy["cutoff_file_path"], "rb") as f:
                cutoff_bytes = f.read()
            model_data[mk] = {
                "weights_csv": weights_bytes,
                "cutoff_csv":  cutoff_bytes,
            }

        return self.get_shareable_data(
            {"model_data": model_data, "cancer_type": cancer_type},
            fl_ctx,
        )

    def _task_model_upload_encrypted(self, dxo, fl_ctx, model_keys, cancer_type, model_dir):
        """Leader-only: encrypt each biomarker model under the multiparty public key and upload
        the ciphertexts, so the *plaintext* coefficients/cutoff never reach the server.

        KeyGen has already run (model_upload is staged after workflow_KeyGen), so
        self.openfhe_manager holds the crypto context (cc, cc_batch_size) and the aggregated
        multiparty public key (mp_public_key) -- the same state used to encrypt patient
        covariates in the discovery round. We encrypt at the same CKKS level the discovery
        round uses (level_val = mult_depth - depth_required) so the downstream homomorphic
        risk-score computation is unchanged.
        """
        covs = dxo.get_meta_prop("biomarker_covariates", None)
        if not covs:
            raise RuntimeError("model_upload (Encrypted): 'biomarker_covariates' missing from metadata.")

        depth_required = dxo.get_meta_prop("depth_required", None)
        level_val = 0
        if depth_required:
            level_val = self.openfhe_manager.mult_depth - depth_required

        # for_scoring (LCS): selects the _score artifact variant + ER_threshold sidecar + the
        # encrypted 1/rsf descale ciphertext. Set by the persistor from workload_args.
        for_scoring = bool(dxo.get_meta_prop("for_scoring", False))
        # lcs_only: LCS is the sole consumer (no KM). Upload unbaked (rsf=1) and emit NO 1/rsf, so
        # the LCS postprocess skips the descale (avoids the near-zero-cutoff round-trip). Default
        # False -> baked, KM-only / combined unchanged.
        lcs_only = bool(dxo.get_meta_prop("lcs_only", False))

        enc_model_data = {}
        rsf_by_model = {}
        horizon_threshold_by_model = {}
        for mk in model_keys:
            wcopy = {"model_key": mk, "cancer_type": cancer_type}
            resolve_biomarker_model_paths(wcopy, model_dir)
            coeffs_df = load_weights_dataframe(wcopy["scale_coeff_file_path"])
            cutoff_value = _load_named_numeric_cutoff_column(
                wcopy["cutoff_file_path"],
                ("cutoff", "cutoff_value", "threshold"),
                model_type=mk,
                value_label="model_upload (Encrypted): biomarker cutoff",
            )
            if for_scoring:
                horizon_threshold_by_model[mk] = _load_named_numeric_cutoff_column(
                    wcopy["cutoff_file_path"],
                    ("ER_threshold", "horizon_threshold"),
                    model_type=mk,
                    value_label="model_upload (Encrypted): ER_threshold",
                )
            ser_coeff, ser_cutoff, ser_inv_rsf, rsf = self.openfhe_manager.encrypt_biomarker_model(
                coeffs_df, cutoff_value, covs, level_val, for_scoring=for_scoring, lcs_only=lcs_only
            )
            enc_model_data[mk] = {
                "coeff_ct": ser_coeff,
                "cutoff_ct": ser_cutoff,
                "inv_rsf_ct": ser_inv_rsf,
            }
            rsf_by_model[mk] = rsf

        payload = {
            "enc_model_data": enc_model_data,
            # Discovery still needs plaintext rsf server-side (KM dead-band); the LCS
            # scoring path descales via the encrypted 1/rsf and must NOT leak rsf, so it
            # is omitted entirely for for_scoring uploads (encrypted-model contract).
            "risk_scores_scale_factor_by_model": {} if for_scoring else rsf_by_model,
            "cancer_type": cancer_type,
            # Selects the on-disk .ct variant: scoring writes "_score" files so it does
            # not overwrite the discovery model for the same key.
            "for_scoring": for_scoring,
        }
        if horizon_threshold_by_model:
            payload["horizon_threshold_by_model"] = horizon_threshold_by_model

        return self.get_shareable_data(payload, fl_ctx)

    # ------------------------------------------------------------------
    # Task: Encrypted Biomarker Discovery
    # ------------------------------------------------------------------
    def _task_enc_biomarker_disc(self, dxo, fl_ctx, abort_signal: Signal):
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        round_idx = dxo.get_meta_prop("round")
        if round_idx == 0:
            self.fire_event(StatAnalyticsEventType.SETUP_START, fl_ctx)
            depth_required = dxo.get_meta_prop("depth_required", None)
            self.openfhe_manager.biomarker_decrypt_masks.clear()
            self.analytics_manager.reset_computation_props()
            self.analytics_manager.set_props_from_init_load(workload_args=dxo.get_meta_prop("workload_args"), generated_args=dxo.get_meta_prop("generated_args"))
            is_risk_group = (self.analytics_manager.computation_type == ENC_BIOMARKER_RISK_GROUP_COMPUTATION)
            # Split-architecture producer: same round-0 covariate encryption as the fused
            # scoring path, but the workflow ends after round 0 (num_rounds=1) -- the server
            # caches the packed ciphertext and the KM/LCS postprocess consumers decrypt later.
            is_score_cache = (self.analytics_manager.computation_type == ENC_BIOMARKER_SCORE_CACHE)
            # Split-architecture postprocess consumers (LCS descale = biomarker_enc_score_postprocess,
            # KM = biomarker_enc_risk_group_postprocess): both read the server-cached packed score, so
            # they upload NO covariates. They still run setup + preprocess and join the decrypt round(s),
            # but skip the round-0 encrypt. LCS is num_rounds=3 (r2 fuses/caches scores); KM is
            # num_rounds=2 (server combines -> persistor -> downstream kaplan-meier, no client r2).
            is_postprocess = (self.analytics_manager.computation_type in ENC_BIOMARKER_POSTPROCESS_TYPES)
            # Both biomarker-discovery paths -- survival (risk_group) and LCS (score) -- honor
            # non_contributing_clients: a non-contributing client (e.g. site3) skips its covariate
            # upload to the HE dot-product but still joins round 1 to supply partial-decrypt shares.
            # For survival, the non-contributing client then scores its own cohort locally from the
            # plaintext model for its Initiator KM view (see _task_stat_analytics r0). Persist on self:
            # the round-2 aggregator broadcast does not carry the persistor's non_contributing meta_prop.
            nc_meta = dxo.get_meta_prop("non_contributing_clients")
            self.non_contributing_clients = [str(x) for x in nc_meta] if isinstance(nc_meta, (list, tuple)) else []
            # Chain marker for the encrypted-model (score-cache) chain: downstream
            # _task_stat_analytics workflows use it to keep a non-contributing
            # non-leader result-less (no plaintext model on this site). Cleared when
            # an open-access chain starts (_task_reference_stat_analytics r0).
            self._enc_chain_active = True
            if is_score_cache or is_postprocess:
                # First workflow of an LCS chain (the split score-cache producer, OR the split
                # postprocess consumer that owns the score->mean-stdev handoff).
                # reset_computation_props preserves the chain-shared cache
                # (score -> mean-stdev -> meta-analysis), so clear it here to stop a second
                # chain (e.g. cox_lasso then logistic_reg) inheriting the first's state.
                # Mirrors r0 of _task_reference_stat_analytics.
                self.analytics_manager.cached_risk_scores = None
                self.analytics_manager.cached_scores_mean = None
                self.analytics_manager.cached_scores_std = None
                self.analytics_manager.cached_lr_fit = None
                self.analytics_manager._fused_lr_fit_status = None
            self.fire_event(StatAnalyticsEventType.SETUP_END, fl_ctx)
            if (is_risk_group or is_score_cache) and client_name in (getattr(self, "non_contributing_clients", []) or []):
                # Non-contributing client on the score-producing round. reuse-scores unified the old
                # risk_group disc + LCS score into the single-round score_cache (num_rounds=1; the
                # round-2 fusion moved to the separate postprocess workflow, which runs its own
                # preprocess). This client uploads no covariate share, so its preprocess output is
                # dead for the federated score AND the server never uses its message -- yet the round
                # runs under min_clients=0 (aggregate only after ALL clients respond). So return {}
                # BEFORE preprocess: the server's wait-for-all then clears as soon as the contributing
                # clients finish instead of blocking on this client's cohort load. Warm the records
                # cache on a BACKGROUND thread for this client's later local Initiator scoring
                # (stat_analytics r0); the cache single-flights, so if stat_analytics arrives first it
                # waits for this warm rather than double-loading. (Mirrors performance_trace's disc
                # non-contributing path, ported onto the reuse-scores score_cache.)
                am = self.analytics_manager
                prof = None
                try:
                    prof = fl_ctx.get_engine().get_component("profiler")
                except Exception:
                    prof = None
                self._warm_records_cache_async(
                    am.stat_data_path, am.cancer_type, am.biomarker_covariates, am.filters,
                    "score_cache", site=client_name, profiler=prof)
                _dbg(f"[{client_name}] {self.analytics_manager.computation_type}: non-contributing; returning empty before preprocess, warming records cache in background.")
                return self.get_shareable_data({}, fl_ctx)
            self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
            try:
                weights = self.analytics_manager.preprocess()
            finally:
                self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
            if is_postprocess:
                # Split postprocess consumer: the producer already cached the packed score, so
                # NO client uploads covariates this round (for any client, contributing or not).
                # preprocess above established _enc_score_n_patients + biomarker_covariates for the
                # round-2 fusion; return {} and join rounds 1-2 (partial-decrypt + fuse).
                _dbg(f"[{client_name}] {self.analytics_manager.computation_type}: postprocess consumer; no covariate upload (reading server-cached score).")
                return self.get_shareable_data({}, fl_ctx)
            # (Non-contributing score_cache clients already returned above, before preprocess.)
            self.fire_event(StatAnalyticsEventType.ENCRYPT_START, fl_ctx)
            try:
                enc_weights = self.openfhe_manager.exec_encrypt_stat_analytics(round_idx, self.analytics_manager.computation_type, weights, depth_required)
            finally:
                self.fire_event(StatAnalyticsEventType.ENCRYPT_END, fl_ctx)
        elif round_idx == 1:
            self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
            try:
                enc_weights = self.openfhe_manager._decrypt_stat_analytics_single_shares(self.analytics_manager.computation_type,
                                                                    dxo.data["enc_result"],
                                                                    self.arch,
                                                                    client_name,
                                                                    fl_ctx.get_prop(ReservedKey.CLIENT_NAME) == self.leader_client_name)  # TODO: Support 'cc' architecture decryption; only 'star' is handled here.
            finally:
                self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)
        elif round_idx == 2 and self.analytics_manager.computation_type in ENC_BIOMARKER_ROUND2_ACK_TYPES:
            # LCS scoring, final round: fuse this client's combined-partials cipher
            # (strip the round-1 privacy mask), re-map the batched slots to
            # per-patient order, trim to the cohort size, and cache for the
            # downstream mean-stdev. The split postprocess consumer descaled the cached
            # rsf-scaled score by 1/rsf server-side, so its slots are the raw scores too --
            # the fusion/extraction is identical to the fused rsf=1 path.
            self.fire_event(StatAnalyticsEventType.POSTPROCESS_START, fl_ctx)
            try:
                w_data = dxo.data.get("w_biomarker_risk_scores", {}) if isinstance(dxo.data, dict) else {}
                # workload_args is only on the round-0 dxo; model_key persists on the
                # manager from set_props_from_init_load.
                mk = str(self.analytics_manager.model_key or "").strip()
                if not mk:
                    raise RuntimeError(
                        f"[{client_name}] biomarker score fusion: missing model_key in "
                        "round-2 client state. The encrypted score payload cannot be selected."
                    )

                raw_expected_count = getattr(self.analytics_manager, "_enc_score_n_patients", None)
                if raw_expected_count is None:
                    raise RuntimeError(
                        f"[{client_name}] biomarker score fusion: missing round-0 "
                        f"expected patient count for model_key={mk!r}. Client state was lost before "
                        "the encrypted score-fusion round."
                    )
                try:
                    expected_count = int(raw_expected_count)
                except (TypeError, ValueError) as e:
                    raise RuntimeError(
                        f"[{client_name}] biomarker score fusion: invalid round-0 "
                        f"expected patient count {raw_expected_count!r} for model_key={mk!r}."
                    ) from e
                if expected_count < 0:
                    raise RuntimeError(
                        f"[{client_name}] biomarker score fusion: negative round-0 "
                        f"expected patient count {expected_count} for model_key={mk!r}."
                    )

                received_model_keys = sorted(str(key) for key in w_data.keys()) if isinstance(w_data, dict) else []
                per_model = w_data.get(mk) if isinstance(w_data, dict) else None
                received_client_keys = (
                    sorted(str(key) for key in per_model.keys())
                    if isinstance(per_model, dict)
                    else []
                )
                ser_ct = per_model.get(client_name) if isinstance(per_model, dict) else None
                _dbg(
                    f"[{client_name}] biomarker score fusion: round-2 payload "
                    f"model_key={mk!r}, expected_patients={expected_count}, "
                    f"received_model_keys={received_model_keys}, "
                    f"received_client_keys={received_client_keys}, "
                    f"ciphertext_present={ser_ct is not None}."
                )

                # Persisted at round 0 (the round-2 broadcast lacks this meta_prop).
                non_contributing = getattr(self, "non_contributing_clients", []) or []
                if ser_ct is None:
                    if client_name in non_contributing and client_name != self.leader_client_name:
                        # Non-contributing NON-leader: the plaintext model only exists at the
                        # leader/initiator (Encrypted model_type), so this site cannot score
                        # its cohort. Leave cached_risk_scores=None -- no Initiator view, and
                        # the downstream mean-stdev/meta workflows contribute zero shares.
                        self.analytics_manager.cached_risk_scores = None
                        _dbg(
                            f"[{client_name}] biomarker score fusion: non-contributing "
                            f"non-leader; no plaintext model on this site, Initiator view "
                            f"unavailable (excluded from the federated aggregate)."
                        )
                    elif client_name in non_contributing:
                        # Leader/initiator: holds the plaintext model locally, so score
                        # its own cohort to populate the Initiator (local) view. These
                        # scores never leave the client and it is already excluded from
                        # the federated aggregate (no round-0 upload). On failure, leave
                        # cached_risk_scores=None (Initiator view unavailable).
                        am = self.analytics_manager
                        try:
                            model_dir = os.path.dirname(os.path.abspath(__file__))
                            wcopy = {"model_key": mk, "cancer_type": am.cancer_type}
                            resolve_biomarker_model_paths(wcopy, model_dir)
                            coeffs_df = load_weights_dataframe(wcopy["scale_coeff_file_path"]).assign(penalized=True)
                            am.coeffs = coeffs_df[["covariate", "penalized", "coef"]]
                            am._run_fused_biomarker_score_computation()
                            _dbg(
                                f"[{client_name}] biomarker score fusion: non-contributing "
                                f"leader scored {len(am.cached_risk_scores or [])} patients locally "
                                f"for its Initiator view."
                            )
                        except Exception:
                            am.cached_risk_scores = None
                            _dbg(
                                f"[{client_name}] biomarker score fusion: local leader "
                                f"scoring failed; Initiator view unavailable:\n{traceback.format_exc()}"
                            )
                    elif expected_count > 0:
                        # This used to be treated as an "empty cohort" and silently
                        # converted to cached_risk_scores=[]. That masks the actual
                        # failure: a non-empty local covariate matrix reached round 0,
                        # but this client did not receive its encrypted score slice.
                        raise RuntimeError(
                            f"[{client_name}] biomarker score fusion: encrypted score "
                            f"payload missing for a non-empty local cohort (expected_patients="
                            f"{expected_count}, model_key={mk!r}, received_model_keys="
                            f"{received_model_keys}, received_client_keys={received_client_keys})."
                        )
                    else:
                        # A genuinely empty local cohort is valid. Keep the [] sentinel
                        # so the downstream mean/stdev workflow does not re-run local
                        # plaintext scoring for a client that intentionally contributed
                        # no covariate records.
                        self.analytics_manager.cached_risk_scores = []
                        _dbg(
                            f"[{client_name}] biomarker score fusion: no local "
                            f"patients were produced in round 0 for model_key={mk!r}; "
                            "caching an empty score list."
                        )
                else:
                    plaintext = self.openfhe_manager._remove_biomarker_mask_and_extract_scores(ser_ct, mk)
                    cov_len = len(self.analytics_manager.biomarker_covariates or [])
                    remapped = self.analytics_manager._re_map_batched_patients_biomarker(
                        plaintext, self.openfhe_manager.cc_batch_size, cov_len,
                    )
                    plaintext_slots = len(plaintext)
                    remapped_count = len(remapped)
                    if remapped_count < expected_count:
                        raise RuntimeError(
                            f"[{client_name}] biomarker score fusion: decrypted score "
                            f"payload is shorter than the non-empty round-0 cohort "
                            f"(expected_patients={expected_count}, remapped_scores="
                            f"{remapped_count}, plaintext_slots={plaintext_slots}, "
                            f"model_key={mk!r})."
                        )
                    self.analytics_manager.cached_risk_scores = list(remapped[:expected_count])
                    _dbg(
                        f"[{client_name}] biomarker score fusion: fused score payload "
                        f"plaintext_slots={plaintext_slots}, remapped_scores={remapped_count}, "
                        f"cached_scores={len(self.analytics_manager.cached_risk_scores)}, "
                        f"expected_patients={expected_count}, model_key={mk!r}."
                    )
                _dbg(
                    f"[{client_name}] biomarker score fusion: cached "
                    f"{len(self.analytics_manager.cached_risk_scores or [])} scores."
                )
            finally:
                self.fire_event(StatAnalyticsEventType.POSTPROCESS_END, fl_ctx)
            enc_weights = {"status": "OK", "n_scores": len(self.analytics_manager.cached_risk_scores or [])}
        else:
            raise Exception(f"[{client_name}] Invalid round {round_idx} for encrypted analytics task.")
        return self.get_shareable_data(enc_weights, fl_ctx)

    # ------------------------------------------------------------------
    # Task: Profile Consolidate
    # ------------------------------------------------------------------
    def _task_profile_consolidate(self, dxo, shareable: Shareable, fl_ctx: FLContext, abort_signal: Signal) -> Shareable:
        """Round 0: upload local profile_summary.json. Round 1 (leader only): write merged bundle."""
        job_id = fl_ctx.get_job_id()
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        round_idx = shareable.get_header(AppConstants.CURRENT_ROUND)
        if round_idx is None:
            round_idx = dxo.get_meta_prop("round")
        try:
            r_int = int(round_idx) if round_idx is not None else 0
        except (TypeError, ValueError):
            r_int = 0

        if r_int == 0:
            # Clients never receive EventType.START_WORKFLOW; flush profiler to disk before read.
            try:
                fl_ctx.get_engine().fire_event(PROFILE_SNAPSHOT_EVENT, fl_ctx)
            except Exception:
                _dbg("_task_profile_consolidate: PROFILE_SNAPSHOT_EVENT failed:\n" + traceback.format_exc())
            path = Path("job-results") / str(job_id) / "profile_summary.json"
            try:
                if path.is_file():
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                else:
                    data = {
                        "error": "missing_profile_summary",
                        "job_id": str(job_id),
                        "site": client_name,
                    }
            except Exception as e:
                data = {
                    "error": "read_failed",
                    "message": str(e),
                    "job_id": str(job_id),
                    "site": client_name,
                }
            return self.get_shareable_data(data, fl_ctx, metadata={"round": 1})

        if client_name == self.leader_client_name and isinstance(dxo.data, dict) and dxo.data:
            out_path = Path("job-results") / str(job_id) / "profile_summaries_all_sites.json"
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(dxo.data, f, indent=2)
                _dbg(f"_task_profile_consolidate: wrote {out_path}")
            except Exception:
                _dbg("_task_profile_consolidate write failed:\n" + traceback.format_exc())
        # Aggregator.accept() requires a DXO (WEIGHTS); make_reply is not a valid DXO shareable.
        return self.get_shareable_data({}, fl_ctx, metadata={"round": r_int + 1})
