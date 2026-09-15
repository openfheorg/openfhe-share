"""End-to-end encrypted survival (Kaplan-Meier) simulator sweep (score-cache / reuse architecture).

The HE KM must agree with the clear-text reference KM within CKKS noise. The encrypted
KM chain computes the risk-score dot product once in a score-cache producer, then applies
the (-cutoff, x rm) tail in a risk-group postprocess consumer:

    KeyGen
    -> workflow_model_upload                        (Encrypted, for_scoring; depth-5 model)
    -> workflow_enc_biomarker_score_cache           (dot product + neutral pack, CACHE, no decrypt)
    -> workflow_enc_biomarker_risk_group_postprocess (-cutoff + x rm from cache -> risk-group margins)
    -> workflow_stat_analytics                       (kaplan-meier, HE; consumes cached scores)  <-- compared
    -> workflow_reference_stat_analytics             (kaplan-meier, clear oracle)                 <-- compared

The expensive ``ct x ct`` risk-score dot product runs ONCE (in the producer); the KM
consumer only applies the cheap ``-cutoff`` + ``x rm`` tail to the cached ciphertext, then
the same multiparty decrypt hands ``rm*rsf*(score-cutoff)`` to the downstream KM. This
validates that relocating the KM tail after a server-side cache leaves the risk groups
(hence the KM curves + log-rank) unchanged within CKKS noise.

The KM dead-band (``eff_epsilon``) runs rsf-free: the score-cache reads the ``_score``
upload variant, which carries no plaintext ``rsf`` / ``scale.json``, so the downstream KM
falls back to the model-keyed epsilon with no ``rsf`` factor. Known ``sign(cutoff)`` leak in
the padding slots is accepted for now (see ``docs/UnifiedBiomarkerScorePlan.md`` §9).

Usage::

    DUALITY_SIM_BIOMARKER_MODELS_ROOT=<repo>/standalone/client_utils/model_files/project_2 \
    DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 \
    pytest -v -k "Colorectal_Cancer" \
        backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_km_enc.py
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

# Import the shared KM oracle (constants + result-path helpers) from the open KM sweep;
# the comparison target (kaplan-meier vs clear reference) is identical.
from .test_simulator_sweep_km_open import (
    CANCERS,
    MODEL_KEYS,
    KM_STAGE_DIR,
    HE_WORKFLOW,
    REF_WORKFLOW,
    N_THREADS,
    CHI2_TOLERANCE,
    TOLERANCE,
    _case_id,
    _result_path,
)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("cancer", "model_key"),
    [(c, m) for c in CANCERS for m in MODEL_KEYS],
    ids=_case_id,
)
def test_km_enc_survival_matches_reference(
    cancer: str,
    model_key: str,
    tmp_path: Path,
    stage_job_km_enc: StageJob,
    request: pytest.FixtureRequest,
) -> None:
    job_dir = stage_job_km_enc(cancer, model_key)
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

    he_path = _result_path(workspace, KM_STAGE_DIR, HE_WORKFLOW)
    ref_path = _result_path(workspace, KM_STAGE_DIR, REF_WORKFLOW)
    assert he_path.is_file(), f"HE Kaplan-Meier result missing: {he_path}"
    assert ref_path.is_file(), f"Reference Kaplan-Meier result missing: {ref_path}"

    he = json.loads(he_path.read_text())
    ref = json.loads(ref_path.read_text())

    if ref.get("status") == "FAIL" and he.get("status") == "FAIL":
        setattr(
            request.node,
            SWEEP_DETAIL_ATTR,
            f"degenerate KM (ref+he both FAIL): {str(ref.get('msg', '<no msg>'))[:120]}",
        )
        pytest.skip(
            f"{cancer} / {model_key}: Kaplan-Meier FAILed on both paths "
            f"(no signal to validate): {ref.get('msg', '<no msg>')}"
        )

    def _fmt(value: object, spec: str) -> str:
        return "None" if not isinstance(value, (int, float)) else format(value, spec)

    binning = km_binning_report(tmp_path)
    mismatches = diff_km_results(he, ref, TOLERANCE, CHI2_TOLERANCE)
    if mismatches:
        setattr(
            request.node,
            SWEEP_DETAIL_ATTR,
            f"chi2={_fmt(ref.get('chi2'), '.3f')} | "
            + (f"{binning} | " if binning else "")
            + f"{len(mismatches)} field(s) disagree, first: {mismatches[0].strip()}",
        )
        pytest.fail(
            f"{cancer} / {model_key}: encrypted Kaplan-Meier disagrees beyond "
            f"{TOLERANCE:g} (curves) / {CHI2_TOLERANCE:g} (chi2):\n"
            + "\n".join(mismatches)
        )

    max_delta = km_max_delta(he, ref)

    setattr(
        request.node,
        SWEEP_DETAIL_ATTR,
        f"chi2={_fmt(ref.get('chi2'), '.3f')} "
        f"p={_fmt(ref.get('p_value'), '.3g')} "
        f"max_delta={max_delta:.1e}" + (f" | {binning}" if binning else ""),
    )
