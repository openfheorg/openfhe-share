"""Unit tests for the threshold-samples pre-pass (``workflow_threshold_samples_*``).

Two areas, one module under test (the server persistor), one loader:

1. **Pre-pass argument building.** The pre-pass validates and builds ``generated_args``
   for *every* downstream stat workflow just to count rows, so it must never require
   artifacts only the real computation needs. Regression: an open-access LCS chain
   contains a fused ``mean-stdev`` (over_cached_scores) workflow whose validation
   deliberately skips resolving the weights CSV in the pre-pass, while
   ``get_meta_from_schema`` then read ``workload_args["scale_coeff_file_path"]``
   unconditionally -- a KeyError that killed the whole job (LCS *and* KM) before any
   computation ran, for every open-access run with a user threshold. The encrypted
   chain was unaffected because its ``model_type: Encrypted`` skips the same load.

2. **Secure-threshold mask parameters.** The masked margin the server decrypts is
   ``(sum of clipped counts - (T - 0.5)) * e^(sum z)``, with the log-DP ``(sigma, B)``
   mask parameters. Its magnitude spans up to ``margin_max * e^B`` (~1e14), so the
   pipeline keeps 2 RNS towers (a +1 spare level at encryption and a towers=2
   compress): a single tower decodes correctly only up to ``~2^(73 - scale_mod)``
   (~1e6 at scale_mod 53) and silently wraps the decrypted sign at random beyond
   that -- which showed up as sporadic false "threshold not met" verdicts (~1-2% per
   workflow slot per run) on data far above the threshold.

Related: ``threshold_mask_probe.py`` (standalone CKKS measurement of the decrypt
bound, run after any CKKS parameter change) and ``test_simulator_threshold_secure.py``
(end-to-end multiparty simulator cases, ``--suite threshold`` in the docker runner).

The persistor is instantiated with ``__new__`` (its ``__init__`` builds an OpenFHE
context) and only the attributes these code paths touch are set.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path

import pytest

_PERSISTOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "jobs"
    / "nvflare_job_template"
    / "app_server"
    / "custom"
    / "analytics_persistor_impl.py"
)


def _load_persistor_module():
    spec = importlib.util.spec_from_file_location("analytics_persistor_impl", _PERSISTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # duality_nvflare_apis / nvflare missing in a bare venv
        pytest.skip(f"analytics_persistor_impl not importable here: {type(e).__name__}: {e}")
    return module


_mod = _load_persistor_module()


# ---------------------------------------------------------------------------
# Pre-pass argument building
# ---------------------------------------------------------------------------

class _FakeEngine:
    def get_clients(self):
        return ["site1", "site2", "site3"]


class _FakeFLContext:
    """Only the accessors the validation / schema-metadata paths use."""

    def __init__(self, workflow: str, job_id: str):
        self._props = {"__workflow__": workflow}
        self._job_id = job_id

    def get_prop(self, key, default=None):
        if key == "__workflow__":
            return self._props[key]
        return self._props.get(key, default)

    def get_job_id(self):
        return self._job_id

    def get_engine(self):
        return _FakeEngine()


def _fl_ctx(workflow: str, job_id: str = "job-1") -> "_FakeFLContext":
    ctx = _FakeFLContext(workflow, job_id)
    # ReservedKey.WORKFLOW is what the code reads; map it onto the stored value.
    from nvflare.apis.fl_constant import ReservedKey

    ctx._props[ReservedKey.WORKFLOW] = workflow
    return ctx


class _NullLogger:
    def info(self, *_a, **_k):
        pass

    warning = error = debug = info


def _persistor():
    p = _mod.AnalyticsPersistor.__new__(_mod.AnalyticsPersistor)
    p.custom_logger = _NullLogger()
    p.is_server_data_owner = False
    p.is_server_contributing_to_aggregation = False
    p.hide_result_from_server = False
    p.leader_client_name = "site1"
    p.exclude_analyzing_clients = []
    p.non_contributing_clients = []
    p.w_biomarker_risk_scores = None
    p._global_schema_cache = {}
    p._pickled_coeffs_cache = {}
    return p


def _write_global_schema(tmp_path: Path, job_id: str) -> None:
    """Schema at the location get_meta_from_schema resolves: <job_id>/app_server/custom/."""
    schema_dir = tmp_path / job_id / "app_server" / "custom"
    schema_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "columns": {
            "time": {"type": "numeric", "global_min": 0, "global_max": 120, "global_count": 500},
            "event": {"type": "boolean"},
        },
        "metadata": {"biomarker_covariates": ["AGE", "SEX"]},
    }
    (schema_dir / "global_schema.json").write_text(json.dumps(schema))


def _open_access_fused_mean_stdev_args() -> dict:
    """The LCS-chain workflow from config_meta_analysis_open.json (no model_type => open)."""
    return {
        "computation_type": "mean-stdev",
        "global_schema": "global_schema.json",
        "over_cached_scores": True,
        "std_type": "sample",
        "cancer_type": "Non-Small Cell Lung Cancer",
        "model_key": "cox_lasso",
        "time_column_id": "time",
        "censoring_column_id": "event",
    }


def test_open_access_fused_mean_stdev_needs_no_model_files_in_prepass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_global_schema(tmp_path, "job-1")
    p = _persistor()
    ctx = _fl_ctx("workflow_threshold_samples_secure")
    w_args = _open_access_fused_mean_stdev_args()

    generated = p._threshold_generated_args({"workflow_stat_analytics_scores_mean_stdev": w_args}, ctx)

    meta = generated["workflow_stat_analytics_scores_mean_stdev"]
    # Counting rows needs the covariate list but never the coefficients.
    assert meta["biomarker_covariates"] == ["AGE", "SEX"]
    assert "coeffs" not in meta
    assert "scale_coeff_file_path" not in w_args


def test_encrypted_fused_mean_stdev_still_skips_coeffs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_global_schema(tmp_path, "job-1")
    p = _persistor()
    w_args = _open_access_fused_mean_stdev_args()
    w_args["model_type"] = _mod.MODEL_TYPE_ENCRYPTED

    meta = p.get_meta_from_schema(w_args, _fl_ctx("workflow_threshold_samples_secure"))

    assert "coeffs" not in meta


def test_prepass_failure_names_the_workflow_and_writes_error_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_global_schema(tmp_path, "job-1")
    p = _persistor()
    # mean-stdev with neither data_column_id nor over_cached_scores is rejected by validation.
    bad = {"computation_type": "mean-stdev", "global_schema": "global_schema.json"}

    with pytest.raises(Exception) as excinfo:
        p._threshold_generated_args({"workflow_stat_analytics_2": bad}, _fl_ctx("workflow_threshold_samples_unsecure"))

    message = str(excinfo.value)
    assert "workflow_stat_analytics_2" in message
    assert "mean-stdev" in message

    error_path = tmp_path / "job-results" / "job-1" / "mean-stdev" / "workflow_stat_analytics_2" / "error.json"
    assert error_path.exists()
    payload = json.loads(error_path.read_text())
    assert payload["workflow"] == "workflow_stat_analytics_2"
    assert payload["stage"].startswith("workflow_threshold_samples_unsecure")
    assert payload["message"]


def test_prepass_builds_args_for_every_workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_global_schema(tmp_path, "job-1")
    p = _persistor()
    workflows = {
        "workflow_stat_analytics_scores_mean_stdev": _open_access_fused_mean_stdev_args(),
        "workflow_stat_analytics_meta_analysis": {
            "computation_type": "meta-analysis",
            "global_schema": "global_schema.json",
            "time_column_id": "time",
            "censoring_column_id": "event",
            "cancer_type": "Non-Small Cell Lung Cancer",
            "model_key": "cox_lasso",
        },
    }

    generated = p._threshold_generated_args(workflows, _fl_ctx("workflow_threshold_samples_secure"))

    assert set(generated) == set(workflows)


# ---------------------------------------------------------------------------
# Secure-threshold mask parameters
# ---------------------------------------------------------------------------

SCALE = 53  # deployed scale_mod_size


def test_original_log_dp_parameters_are_preserved():
    # The (sigma, B) pairs carry the log-DP guarantee and must not drift as a side
    # effect of correctness work.
    assert _mod.secure_threshold_mask_params(3, 10, SCALE) == (5.154, 27.14)
    assert _mod.secure_threshold_mask_params(5, 10, SCALE) == (5.154, 27.14)
    assert _mod.secure_threshold_mask_params(3, 20, SCALE) == (5.706, 27.70)
    assert _mod.secure_threshold_mask_params(8, 20, SCALE) == (5.388, 26.91)


def test_all_supported_configs_fit_the_two_tower_decrypt_bound():
    for max_owners, max_t, _sigma, b_val in _mod._THRESHOLD_MASK_CONFIGS:
        margin_max = max_owners * max_t - (max_t - 0.5)
        assert margin_max * math.exp(b_val) <= _mod.secure_threshold_mask_wrap_guard(SCALE)


def test_one_tower_would_wrap_every_branch():
    # Regression documenting why the spare level + towers=2 compress exist: against the
    # measured single-tower decode bound (~2^(73 - scale_mod)) every branch's worst case
    # overflows, so reverting either half of the pipeline change must fail this check.
    one_tower_bound = 2.0 ** (73 - SCALE)
    for max_owners, max_t, _sigma, b_val in _mod._THRESHOLD_MASK_CONFIGS:
        margin_max = max_owners * max_t - (max_t - 0.5)
        assert margin_max * math.exp(b_val) > one_tower_bound


def test_unsupported_config_raises():
    with pytest.raises(Exception, match="supports only"):
        _mod.secure_threshold_mask_params(11, 20, SCALE)
    with pytest.raises(Exception, match="supports only"):
        _mod.secure_threshold_mask_params(6, 21, SCALE)


def test_insufficient_headroom_raises_at_staging():
    # A drastically larger scale_mod erodes the decrypt bound until the mask no longer
    # fits; staging must fail loudly rather than let signs wrap at random mid-run.
    with pytest.raises(Exception, match="decrypt bound"):
        _mod.secure_threshold_mask_params(3, 10, 100)


def test_wrap_guard_is_scale_aware():
    assert _mod.secure_threshold_mask_wrap_guard(53) == pytest.approx(1.0e15)
    assert _mod.secure_threshold_mask_wrap_guard(50) == pytest.approx(8.0e15)
