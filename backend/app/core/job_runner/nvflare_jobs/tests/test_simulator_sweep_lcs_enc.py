"""End-to-end encrypted LCS simulator sweep (score-cache / reuse architecture).

The HE meta-analysis must agree with the clear-text reference within CKKS noise.
The encrypted LCS chain computes the risk-score dot product once in a score-cache
producer, then applies the LCS descale in a postprocess consumer:

    KeyGen
    -> workflow_model_upload                       (Encrypted, for_scoring; depth-5 model)
    -> workflow_enc_biomarker_score_cache          (dot product + neutral pack, CACHE, no decrypt)
    -> workflow_enc_biomarker_score_postprocess    (x 1/rsf descale from cache -> raw scores)
    -> workflow_stat_analytics_scores_mean_stdev   (HE)
    -> workflow_stat_analytics_meta_analysis       (HE, fused fit)              <-- compared
    -> workflow_biomarker_score_computation        (clear oracle scoring)
    -> workflow_reference_stat_analytics_scores_mean_stdev (clear oracle)
    -> workflow_biomarker_lr_fit_2                 (clear oracle fit)
    -> workflow_reference_stat_analytics_meta_analysis (clear oracle)           <-- compared

The expensive ``ct x ct`` risk-score dot product runs ONCE (in the producer);
the consumer only applies the cheap per-slot descale to the cached ciphertext.
This validates that relocating the descale tail after a server-side cache leaves
the raw scores (and hence the whole downstream LCS pipeline) unchanged within
CKKS noise. See ``docs/UnifiedBiomarkerScorePlan.md`` (Stage 4/5).

Usage::

    # Single case (both noise regimes are covered by cox_lasso + logistic_reg):
    DUALITY_SIM_BIOMARKER_MODELS_ROOT=<repo>/standalone/client_utils/model_files/project_2 \
    DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 \
    pytest -v -k "Colorectal_Cancer" \
        backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_lcs_enc.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nvflare.private.fed.app.simulator.simulator_runner import SimulatorRunner

from .conftest import LOG_CONFIG_REL, SIM_CLIENTS, SWEEP_DETAIL_ATTR, StageJob

# Import the shared LCS oracle (constants + diff helpers) from the open LCS sweep;
# the comparison target (meta-analysis vs clear reference) is identical.
from .test_simulator_sweep_lcs_open import (
    CANCERS,
    MODEL_KEYS,
    META_STAGE_DIR,
    HE_WORKFLOW,
    REF_WORKFLOW,
    MEAN_STDEV_STAGE_DIR,
    REF_MEAN_STDEV_WORKFLOW,
    N_THREADS,
    TOLERANCE,
    _case_id,
    _collect_lr_fit_failures,
    _diff_results,
    _is_numeric,
    _result_path,
)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("cancer", "model_key"),
    [(c, m) for c in CANCERS for m in MODEL_KEYS],
    ids=_case_id,
)
def test_lcs_enc_meta_analysis_matches_reference(
    cancer: str,
    model_key: str,
    tmp_path: Path,
    stage_job_lcs_enc: StageJob,
    request: pytest.FixtureRequest,
) -> None:
    job_dir = stage_job_lcs_enc(cancer, model_key)
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

    ref_mean_stdev_path = _result_path(
        workspace, MEAN_STDEV_STAGE_DIR, REF_MEAN_STDEV_WORKFLOW
    )
    assert ref_mean_stdev_path.is_file(), (
        f"Reference mean-stdev result missing: {ref_mean_stdev_path}"
    )
    ref_mean_stdev = json.loads(ref_mean_stdev_path.read_text())
    if ref_mean_stdev.get("status") == "WARN":
        mean_val = ref_mean_stdev.get("mean_scores") or ref_mean_stdev.get("mean") or 0.0
        stdev_val = ref_mean_stdev.get("stdev_scores") or ref_mean_stdev.get("stdev") or 0.0
        setattr(
            request.node,
            SWEEP_DETAIL_ATTR,
            f"low SNR: |mean|={abs(mean_val):.2e} stdev={stdev_val:.2e}",
        )
        pytest.skip(
            f"{cancer} / {model_key}: reference mean-stdev reports WARN: "
            f"{ref_mean_stdev.get('msg', '<no msg>')}"
        )

    lr_fit_failures = _collect_lr_fit_failures(workspace)
    if lr_fit_failures:
        setattr(
            request.node,
            SWEEP_DETAIL_ATTR,
            f"{len(lr_fit_failures)} degenerate LR fit(s) "
            f"({lr_fit_failures[0].split(':')[0]}, ...)",
        )
        pytest.skip(
            f"{cancer} / {model_key}: biomarker_lr_fit degenerate on "
            f"{len(lr_fit_failures)} client/path pair(s):\n  "
            + "\n  ".join(lr_fit_failures)
        )

    he_path = _result_path(workspace, META_STAGE_DIR, HE_WORKFLOW)
    ref_path = _result_path(workspace, META_STAGE_DIR, REF_WORKFLOW)
    assert he_path.is_file(), f"HE meta-analysis result missing: {he_path}"
    assert ref_path.is_file(), f"Reference meta-analysis result missing: {ref_path}"

    he = json.loads(he_path.read_text())
    ref = json.loads(ref_path.read_text())

    if ref.get("status") == "FAIL" and he.get("status") == "FAIL":
        setattr(
            request.node,
            SWEEP_DETAIL_ATTR,
            f"degenerate fit (ref+he both FAIL): {ref.get('msg', '<no msg>')[:120]}",
        )
        pytest.skip(
            f"{cancer} / {model_key}: meta-analysis FAILed on both paths "
            f"(no signal to validate): {ref.get('msg', '<no msg>')}"
        )

    def _fmt(value: object, spec: str) -> str:
        return "None" if value is None else format(value, spec)

    mismatches = _diff_results(he, ref, TOLERANCE)
    if mismatches:
        setattr(
            request.node,
            SWEEP_DETAIL_ATTR,
            f"beta={_fmt(ref.get('meta_beta1'), '.3f')} | "
            + f"{len(mismatches)} field(s) disagree, first: {mismatches[0].strip()}",
        )
        pytest.fail(
            f"{cancer} / {model_key}: encrypted LCS meta-analysis disagrees beyond {TOLERANCE:g}:\n"
            + "\n".join(mismatches)
        )

    max_delta = max(
        (
            abs(he[k] - ref[k])
            for k in he
            if _is_numeric(he.get(k)) and _is_numeric(ref.get(k))
            and he[k] is not None and ref[k] is not None
        ),
        default=0.0,
    )


    setattr(
        request.node,
        SWEEP_DETAIL_ATTR,
        f"beta={_fmt(ref.get('meta_beta1'), '.3f')} "
        f"p={_fmt(ref.get('p_value'), '.3g')} "
        f"max_delta={max_delta:.1e}",
    )
