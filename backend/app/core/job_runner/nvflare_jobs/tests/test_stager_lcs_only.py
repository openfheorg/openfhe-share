"""Unit tests for the LCS-only encrypted optimization wiring in ``NVFlareJobStager``.

When an ENCRYPTED job runs LCS (meta-analysis) with NO KM biomarker-discovery consumer, the rsf
baking (which exists only for KM's sign resolution) is unnecessary. Such a job uploads the model
unbaked (rsf=1), skips the LCS descale, and drops depth 5 -> 4. Two pieces implement it:

  * ``_is_lcs_only_encrypted_biomarker()`` -- detects the case from ``functions_map``.
  * ``_mark_lcs_only_encrypted_workflows()`` -- sets ``lcs_only=True`` on the model_upload +
    score_cache + LCS score_postprocess workflows.

This module tests both as pure functions. The stager imports the backend app package (fastapi
etc.), present in the backend container / CI but not the bare sweep venv, so the module skips when
it cannot import.
"""

from __future__ import annotations

import pytest

NVFlareJobStager = pytest.importorskip(
    "NVFlareJobStager",
    reason="NVFlareJobStager needs the backend app package (fastapi, app.core.*); "
    "run in the backend container / CI.",
).NVFlareJobStager


def _stager(functions_map: dict) -> "NVFlareJobStager":
    inst = NVFlareJobStager.__new__(NVFlareJobStager)  # bypass __init__ (needs DB/config)
    inst.functions_map = functions_map
    return inst


# functions_map cfgs carry an explicit computation_type so the test does not depend on the
# FUNCTION_TO_COMPUTATION_TYPE table.
_LCS = {"model_type": "Encrypted", "computation_type": "meta-analysis"}
_KM = {"model_type": "Encrypted", "computation_type": "kaplan-meier", "is_biomarker_discovery": "true"}
_LCS_OPEN = {"model_type": "Open-access", "computation_type": "meta-analysis"}


def test_detects_encrypted_lcs_only() -> None:
    assert _stager({"lcs": [_LCS]})._is_lcs_only_encrypted_biomarker() is True


def test_combined_is_not_lcs_only() -> None:
    # KM discovery shares the cache -> must stay baked.
    assert _stager({"lcs": [_LCS], "km": [_KM]})._is_lcs_only_encrypted_biomarker() is False


def test_km_only_is_not_lcs_only() -> None:
    assert _stager({"km": [_KM]})._is_lcs_only_encrypted_biomarker() is False


def test_open_access_lcs_is_not_lcs_only_encrypted() -> None:
    # The flag is an ENCRYPTED-path concept; open-access LCS has no rsf baking to skip.
    assert _stager({"lcs": [_LCS_OPEN]})._is_lcs_only_encrypted_biomarker() is False


def _wf(wf_id: str) -> dict:
    return {"id": wf_id, "args": {"workload_args": {}}}


def _lcs_only(workflows: list[dict], wf_id: str) -> bool:
    for w in workflows:
        if w["id"] == wf_id:
            return bool(w["args"]["workload_args"].get("lcs_only", False))
    raise AssertionError(f"no workflow {wf_id}")


def test_marks_the_three_workflows_for_lcs_only() -> None:
    workflows = [
        _wf("workflow_model_upload"),
        _wf("workflow_enc_biomarker_score_cache"),
        _wf("workflow_enc_biomarker_score_postprocess"),
        _wf("workflow_stat_analytics_meta_analysis"),  # not a target
    ]
    changed = _stager({"lcs": [_LCS]})._mark_lcs_only_encrypted_workflows(workflows)
    assert changed is True
    for wid in (
        "workflow_model_upload",
        "workflow_enc_biomarker_score_cache",
        "workflow_enc_biomarker_score_postprocess",
    ):
        assert _lcs_only(workflows, wid) is True, wid
    # unrelated workflow untouched
    assert _lcs_only(workflows, "workflow_stat_analytics_meta_analysis") is False


def test_marks_suffixed_workflow_ids() -> None:
    # ids may be suffixed with __<model_key>.
    workflows = [_wf("workflow_model_upload"), _wf("workflow_enc_biomarker_score_postprocess__cox_lasso")]
    assert _stager({"lcs": [_LCS]})._mark_lcs_only_encrypted_workflows(workflows) is True
    assert _lcs_only(workflows, "workflow_enc_biomarker_score_postprocess__cox_lasso") is True


def test_combined_marks_nothing() -> None:
    workflows = [
        _wf("workflow_model_upload"),
        _wf("workflow_enc_biomarker_score_cache"),
        _wf("workflow_enc_biomarker_score_postprocess"),
        _wf("workflow_enc_biomarker_risk_group_postprocess"),
    ]
    changed = _stager({"lcs": [_LCS], "km": [_KM]})._mark_lcs_only_encrypted_workflows(workflows)
    assert changed is False
    assert _lcs_only(workflows, "workflow_model_upload") is False
