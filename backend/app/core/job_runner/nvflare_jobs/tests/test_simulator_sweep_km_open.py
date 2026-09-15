"""End-to-end OPEN-ACCESS survival (Kaplan-Meier) sweep over (cancer_type, model_key).

Each case runs the open-access survival biomarker-discovery pipeline in the
NVFlare simulator and asserts the HE Kaplan-Meier result agrees with the
clear-text reference KM result (within CKKS noise). 'Open-access' = the biomarker
model is public: each client computes its own per-patient risk *groups* in
clear-text from the on-disk model files, and only the Kaplan-Meier aggregation
runs under HE. The reference path aggregates the same clear-text groups in the
clear, giving ground truth for the HE aggregation.

The chain (see tests/sim_config_fed_server_survival.json):

    KeyGen
    -> workflow_stat_analytics            (kaplan-meier, HE; clear local scoring)  <-- compared
    -> workflow_reference_stat_analytics  (kaplan-meier, clear oracle)             <-- compared

site3 is the non-contributing leader (participates in decryption, contributes no
covariate share), so the federated estimate is over site1 + site2 on both paths.

The sweep stages an isolated job under tmp_path (no manual config swap needed).

Usage::

    # Full open-access survival sweep (slow, ~minutes per case):
    pytest backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_km_open.py -v

    # Single case:
    pytest -v -k "Glioma and cox_lasso" \
        backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_km_open.py
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
    sweep_cancers,
)

# Cancer types with both cox_lasso and logistic_reg coefficient files available,
# discovered per DUALITY_SIM_DATASOURCE_VERSION at collection time.
CANCERS = sweep_cancers()
MODEL_KEYS = ["cox_lasso", "logistic_reg"]

# The Kaplan-Meier workflow writes its result under a stage dir named for the
# computation_type (see analytics_aggregator_impl._write_json:
# job-results/<job_id>/<computation_type>/<workflow_id>/...).
KM_STAGE_DIR = "kaplan-meier"
HE_WORKFLOW = "workflow_stat_analytics"
REF_WORKFLOW = "workflow_reference_stat_analytics"

# site3 is the non-contributing leader; site1 / site2 contribute. The final KM
# result is identical across contributing sites (same multiparty decryption), so
# reading site1 is sufficient.
SITE = "site1"

RESULT_REL = Path("aggregated") / "processed_results.json"

N_THREADS = 3

# Applied to the survival curves (p_value is not compared; see conftest._KM_SCALAR_FIELDS).
# Single source for the KM tolerance: km_enc and the combined sweeps import this value,
# so changing it here changes them too.
#
# The curves are probabilities in [0, 1] and are produced by a single ciphertext
# multiply, so they stay within ~2e-4 of the reference even in runs where the log-rank
# statistic diverges by two orders more. Matches the LCS tolerance.
TOLERANCE = 1e-4

# chi2 is bounded separately because it is not on the curves' scale: it is an unbounded
# statistic assembled from a far deeper, mask-heavy chain -- the log-rank branch runs
# ~7 sequential ciphertext multiplications against 1 for the curves, over degree-3 and
# degree-4 polynomials in the at-risk counts, and its per-bin additive masks cancel only
# on summation. The same absolute bound is therefore a much stricter demand on chi2 than
# on a survival probability, and the masking calibration table in apis/utils.py documents
# only ~3 decimal digits for this path.
CHI2_TOLERANCE = 1e-3


def _per_site_result_path(
    workspace: Path, site: str, stage_dir: str, workflow_id: str
) -> Path:
    return (
        workspace
        / site
        / "job-results"
        / "simulate_job"
        / stage_dir
        / workflow_id
        / RESULT_REL
    )


def _result_path(workspace: Path, stage_dir: str, workflow_id: str) -> Path:
    return _per_site_result_path(workspace, SITE, stage_dir, workflow_id)


def _case_id(value: object) -> str:
    return str(value).replace(" ", "_").replace(",", "").replace("/", "_")


@pytest.mark.slow
@pytest.mark.parametrize(
    ("cancer", "model_key"),
    [(c, m) for c in CANCERS for m in MODEL_KEYS],
    ids=_case_id,
)
def test_open_survival_matches_reference(
    cancer: str,
    model_key: str,
    tmp_path: Path,
    stage_job_km_open: StageJob,
    request: pytest.FixtureRequest,
) -> None:
    job_dir = stage_job_km_open(cancer, model_key)
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

    # A KM workflow can degenerate (a single risk group, or all-censored input),
    # in which case the analytics manager returns a status/msg instead of curves.
    # If both paths degenerate identically there is no signal to validate, so
    # skip with the reason rather than reporting a hollow PASS.
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
            f"{cancer} / {model_key}: Kaplan-Meier disagrees beyond "
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
