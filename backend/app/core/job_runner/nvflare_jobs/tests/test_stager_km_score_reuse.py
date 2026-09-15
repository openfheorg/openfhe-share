"""Unit tests for the open-access KM<->LCS score-reuse wiring in ``NVFlareJobStager``.

``_wire_open_access_km_score_reuse`` makes an open-access Kaplan-Meier biomarker-discovery
workflow consume the per-patient scores an LCS (meta-analysis) chain already computes for the
same model, instead of re-scoring the cohort. This module tests the pure graph transform:

  * a combined KM+LCS job (same model) marks the KM ``from_cached_score`` and orders it after the
    ``biomarker_score_computation`` that fills the cache,
  * a KM-only job (no LCS chain) is left untouched (keeps recomputing),
  * an encrypted job is never touched (it has its own precomputed-score handoff).

The stager imports the backend app package (fastapi etc.), which is present in the backend
container / CI but not in the bare sweep venv, so the whole module skips when it cannot import.
"""

from __future__ import annotations

import pytest

# The stager lives at nvflare_jobs/NVFlareJobStager.py and imports ``app.core...`` + fastapi.
NVFlareJobStager = pytest.importorskip(
    "NVFlareJobStager",
    reason="NVFlareJobStager needs the backend app package (fastapi, app.core.*); "
    "run in the backend container / CI.",
).NVFlareJobStager


def _wf(computation_type: str, model_key: str | None = None, discovery: bool = False) -> dict:
    wl: dict = {"computation_type": computation_type}
    if model_key:
        wl["model_key"] = model_key
    if discovery:
        wl["is_biomarker_discovery"] = True
    return {"id": f"wf_{computation_type}_{model_key}", "args": {"workload_args": wl}}


def _stager(functions_map: dict) -> "NVFlareJobStager":
    inst = NVFlareJobStager.__new__(NVFlareJobStager)  # bypass __init__ (needs DB/config)
    inst.functions_map = functions_map
    return inst


def _km_flag(workflows: list[dict], model_key: str) -> bool:
    for w in workflows:
        wl = w["args"]["workload_args"]
        if wl.get("computation_type") == "kaplan-meier" and wl.get("model_key") == model_key:
            return bool(wl.get("from_cached_score", False))
    raise AssertionError(f"no kaplan-meier workflow for {model_key}")


def _order(workflows: list[dict]) -> list[str]:
    return [w["id"] for w in workflows]


def test_combined_single_model_wires_and_orders_reuse() -> None:
    # KM appears BEFORE the LCS chain (worst case for ordering).
    wfs = [
        _wf("kaplan-meier", "cox_lasso", discovery=True),
        _wf("biomarker_score_computation", "cox_lasso"),
        _wf("mean-stdev"),
        _wf("meta-analysis", "cox_lasso"),
    ]
    out = _stager({})._wire_open_access_km_score_reuse(wfs)

    assert _km_flag(out, "cox_lasso") is True
    order = _order(out)
    assert order.index("wf_biomarker_score_computation_cox_lasso") < order.index(
        "wf_kaplan-meier_cox_lasso"
    ), "reusing KM must run after the score-comp that fills its cache"


def test_km_only_job_is_untouched() -> None:
    wfs = [_wf("kaplan-meier", "cox_lasso", discovery=True)]
    out = _stager({})._wire_open_access_km_score_reuse(wfs)
    assert _km_flag(out, "cox_lasso") is False, "no LCS cache -> KM must keep recomputing"
    assert _order(out) == ["wf_kaplan-meier_cox_lasso"]


def test_two_models_each_km_ordered_within_its_own_cache_window() -> None:
    wfs = [
        _wf("kaplan-meier", "cox_lasso", discovery=True),
        _wf("kaplan-meier", "logistic_reg", discovery=True),
        _wf("biomarker_score_computation", "cox_lasso"),
        _wf("meta-analysis", "cox_lasso"),
        _wf("biomarker_score_computation", "logistic_reg"),
        _wf("meta-analysis", "logistic_reg"),
    ]
    out = _stager({})._wire_open_access_km_score_reuse(wfs)
    order = _order(out)

    for mk in ("cox_lasso", "logistic_reg"):
        assert _km_flag(out, mk) is True
        assert order.index(f"wf_biomarker_score_computation_{mk}") < order.index(
            f"wf_kaplan-meier_{mk}"
        )
    # cox KM must fall inside cox's cache window: after cox score-comp, before logistic score-comp
    # (each score-comp clears the previous model's cache), else the model-key guard would raise.
    assert order.index("wf_kaplan-meier_cox_lasso") < order.index(
        "wf_biomarker_score_computation_logistic_reg"
    )


def test_encrypted_job_is_never_touched() -> None:
    wfs = [
        _wf("kaplan-meier", "cox_lasso", discovery=True),
        _wf("biomarker_score_computation", "cox_lasso"),
        _wf("meta-analysis", "cox_lasso"),
    ]
    out = _stager({"f": [{"model_type": "Encrypted"}]})._wire_open_access_km_score_reuse(wfs)
    assert _km_flag(out, "cox_lasso") is False, "encrypted path uses w_biomarker_risk_scores handoff"
