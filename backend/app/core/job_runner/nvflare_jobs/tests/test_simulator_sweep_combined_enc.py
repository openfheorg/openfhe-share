"""End-to-end combined encrypted simulator sweep (KM + LCS, one job, shared score cache).

This is the Stage-6 payoff: when survival (Kaplan-Meier) AND LCS run for the same model,
the expensive ``ct x ct`` risk-score dot product runs ONCE and is shared by both analyses,
instead of once per analysis. A single ``workflow_model_upload`` (for_scoring) and a single
``workflow_enc_biomarker_score_cache`` producer feed BOTH from-cache consumers:

    KeyGen
    -> workflow_model_upload                          (Encrypted, for_scoring; depth-5 model)
    -> workflow_enc_biomarker_score_cache             (dot product + neutral pack, CACHE, no decrypt)
    # --- KM branch (reads the cache) ---
    -> workflow_enc_biomarker_risk_group_postprocess  (-cutoff + x rm from cache -> risk-group margins)
    -> workflow_stat_analytics                        (kaplan-meier, HE)                     <-- compared
    -> workflow_reference_stat_analytics              (kaplan-meier, clear oracle)           <-- compared
    # --- LCS branch (reads the SAME cache, non-destructively) ---
    -> workflow_enc_biomarker_score_postprocess       (x 1/rsf descale from cache -> raw scores)
    -> workflow_stat_analytics_scores_mean_stdev      (HE)
    -> workflow_stat_analytics_meta_analysis          (HE, fused fit)                        <-- compared
    -> workflow_biomarker_score_computation           (clear oracle scoring)
    -> workflow_reference_stat_analytics_scores_mean_stdev (clear oracle)
    -> workflow_biomarker_lr_fit_2                    (clear oracle fit)
    -> workflow_reference_stat_analytics_meta_analysis (clear oracle)                        <-- compared

The two consumers read the one cached ciphertext NON-DESTRUCTIVELY (the KM postprocess runs
first and does NOT pop the cache), so the fact that BOTH the KM and the LCS branches produce
correct results in one job is itself the proof that the shared-cache payoff holds: if the KM
read had consumed the cache, the LCS postprocess would abort with "no cached score ciphertext
available". See ``docs/UnifiedBiomarkerScorePlan.md`` (Stage 5/6).

Usage::

    DUALITY_SIM_BIOMARKER_MODELS_ROOT=<repo>/standalone/client_utils/model_files/project_2 \
    DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 \
    pytest -v -k "Non-Small_Cell_Lung_Cancer-cox_lasso" \
        backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_combined_enc.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nvflare.private.fed.app.simulator.simulator_runner import SimulatorRunner

from .conftest import (
    LOG_CONFIG_REL,
    SIM_CLIENTS,
    SWEEP_DETAIL_ATTR,
    StageJob,
    diff_km_results,
    km_binning_report,
    km_max_delta,
)

# KM (survival) oracle: kaplan-meier HE vs clear reference. Reuse the open KM sweep's
# parameters + result-path helper verbatim.
from .test_simulator_sweep_km_open import (
    CANCERS,
    MODEL_KEYS,
    N_THREADS,
    KM_STAGE_DIR,
    HE_WORKFLOW as KM_HE_WORKFLOW,
    REF_WORKFLOW as KM_REF_WORKFLOW,
    CHI2_TOLERANCE as KM_CHI2_TOLERANCE,
    TOLERANCE as KM_TOLERANCE,
    _case_id,
    _result_path,
)

# LCS oracle: meta-analysis HE vs clear reference (plus the mean-stdev WARN / degenerate
# lr-fit skips the LCS sweep uses).
from .test_simulator_sweep_lcs_open import (
    META_STAGE_DIR,
    MEAN_STDEV_STAGE_DIR,
    HE_WORKFLOW as LCS_HE_WORKFLOW,
    REF_WORKFLOW as LCS_REF_WORKFLOW,
    REF_MEAN_STDEV_WORKFLOW,
    TOLERANCE as LCS_TOLERANCE,
    _collect_lr_fit_failures,
    _diff_results,
    _is_numeric,
)


def _fmt(value: object, spec: str) -> str:
    return "None" if not isinstance(value, (int, float)) else format(value, spec)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("cancer", "model_key"),
    [(c, m) for c in CANCERS for m in MODEL_KEYS],
    ids=_case_id,
)
def test_combined_encrypted_km_and_lcs_match_references(
    cancer: str,
    model_key: str,
    tmp_path: Path,
    stage_job_combined_enc: StageJob,
    request: pytest.FixtureRequest,
) -> None:
    job_dir = stage_job_combined_enc(cancer, model_key)
    workspace = tmp_path / "ws"

    runner = SimulatorRunner(
        job_folder=str(job_dir),
        workspace=str(workspace),
        clients=",".join(SIM_CLIENTS),
        n_clients=None,
        threads=N_THREADS,
        log_config=str(job_dir / LOG_CONFIG_REL),
    )
    status = runner.run()
    assert status == 0, f"Simulator returned non-zero status: {status}"

    # Both branches are ALWAYS evaluated (no fail-fast): the KM branch inherits the
    # documented run-to-run group-flip flake, and letting a KM flip short-circuit the test
    # would hide a simultaneous (real) LCS divergence. We collect a per-branch verdict, put
    # both on the detail line, and only then decide skip/fail/pass. failures[] holds hard
    # divergences (a KM flip is real-but-expected; an LCS divergence is a genuine bug --
    # both are reported, both fail the case, exactly as the standalone sweeps do).
    failures: list[str] = []

    # ------------------------------------------------------------------ KM branch
    km_he_path = _result_path(workspace, KM_STAGE_DIR, KM_HE_WORKFLOW)
    km_ref_path = _result_path(workspace, KM_STAGE_DIR, KM_REF_WORKFLOW)
    assert km_he_path.is_file(), f"HE Kaplan-Meier result missing: {km_he_path}"
    assert km_ref_path.is_file(), f"Reference Kaplan-Meier result missing: {km_ref_path}"
    km_he = json.loads(km_he_path.read_text())
    km_ref = json.loads(km_ref_path.read_text())

    km_skipped = km_ref.get("status") == "FAIL" and km_he.get("status") == "FAIL"
    km_max = float("nan")
    km_detail = "KM degenerate (both FAIL)"
    binning = km_binning_report(tmp_path)
    if not km_skipped:
        km_mismatches = diff_km_results(km_he, km_ref, KM_TOLERANCE, KM_CHI2_TOLERANCE)
        km_max = km_max_delta(km_he, km_ref)
        if km_mismatches:
            km_detail = (
                f"KM chi2={_fmt(km_ref.get('chi2'), '.3f')} DIVERGE ({len(km_mismatches)} field(s)): "
                f"{km_mismatches[0].strip()}"
            )
            failures.append(
                f"Kaplan-Meier disagrees beyond {KM_TOLERANCE:g} (curves) / {KM_CHI2_TOLERANCE:g} (chi2) "
                f"(chi2 he={_fmt(km_he.get('chi2'), '.3f')} ref={_fmt(km_ref.get('chi2'), '.3f')}):\n  "
                + "\n  ".join(km_mismatches)
            )
        else:
            km_detail = f"KM chi2={_fmt(km_ref.get('chi2'), '.3f')} max_delta={km_max:.1e}"
    if binning:
        km_detail = f"{km_detail} [{binning}]"

    # ----------------------------------------------------------------- LCS branch
    lcs_skipped = False
    lcs_skip_reason = ""
    lcs_max = float("nan")
    lcs_detail = ""

    ref_mean_stdev_path = _result_path(
        workspace, MEAN_STDEV_STAGE_DIR, REF_MEAN_STDEV_WORKFLOW
    )
    assert ref_mean_stdev_path.is_file(), (
        f"Reference mean-stdev result missing: {ref_mean_stdev_path}"
    )
    ref_mean_stdev = json.loads(ref_mean_stdev_path.read_text())
    lr_fit_failures = _collect_lr_fit_failures(workspace)
    if ref_mean_stdev.get("status") == "WARN":
        lcs_skipped = True
        lcs_skip_reason = f"LCS reference mean-stdev WARN: {ref_mean_stdev.get('msg', '<no msg>')}"
        lcs_detail = "LCS skip (mean-stdev WARN, low SNR)"
    elif lr_fit_failures:
        lcs_skipped = True
        lcs_skip_reason = (
            f"biomarker_lr_fit degenerate on {len(lr_fit_failures)} client/path pair(s): "
            + "; ".join(lr_fit_failures)
        )
        lcs_detail = f"LCS skip ({len(lr_fit_failures)} degenerate LR fit(s))"
    else:
        lcs_he_path = _result_path(workspace, META_STAGE_DIR, LCS_HE_WORKFLOW)
        lcs_ref_path = _result_path(workspace, META_STAGE_DIR, LCS_REF_WORKFLOW)
        assert lcs_he_path.is_file(), f"HE meta-analysis result missing: {lcs_he_path}"
        assert lcs_ref_path.is_file(), f"Reference meta-analysis result missing: {lcs_ref_path}"
        lcs_he = json.loads(lcs_he_path.read_text())
        lcs_ref = json.loads(lcs_ref_path.read_text())

        if lcs_ref.get("status") == "FAIL" and lcs_he.get("status") == "FAIL":
            lcs_skipped = True
            lcs_skip_reason = "LCS meta-analysis degenerate (both FAIL)"
            lcs_detail = "LCS degenerate (both FAIL)"
        else:
            lcs_mismatches = _diff_results(lcs_he, lcs_ref, LCS_TOLERANCE)
            lcs_max = max(
                (
                    abs(lcs_he[k] - lcs_ref[k])
                    for k in lcs_he
                    if _is_numeric(lcs_he.get(k)) and _is_numeric(lcs_ref.get(k))
                    and lcs_he[k] is not None and lcs_ref[k] is not None
                ),
                default=0.0,
            )
            if lcs_mismatches:
                lcs_detail = f"LCS beta={_fmt(lcs_ref.get('meta_beta1'), '.3f')} DIVERGE ({len(lcs_mismatches)} field(s)): {lcs_mismatches[0].strip()}"
                failures.append(
                    f"meta-analysis disagrees beyond {LCS_TOLERANCE:g}:\n  "
                    + "\n  ".join(lcs_mismatches)
                )
            else:
                lcs_detail = (
                    f"LCS beta={_fmt(lcs_ref.get('meta_beta1'), '.3f')} "
                    f"p={_fmt(lcs_ref.get('p_value'), '.3g')} max_delta={lcs_max:.1e}"
                )

    setattr(request.node, SWEEP_DETAIL_ATTR, f"{km_detail} | {lcs_detail}")

    if failures:
        pytest.fail(f"{cancer} / {model_key}: combined encrypted divergence:\n" + "\n".join(failures))

    if km_skipped and lcs_skipped:
        pytest.skip(
            f"{cancer} / {model_key}: nothing to validate "
            f"(KM degenerate; {lcs_skip_reason})"
        )
