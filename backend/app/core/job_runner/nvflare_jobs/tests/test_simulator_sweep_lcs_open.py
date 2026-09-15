"""End-to-end open-access simulator sweep over (cancer_type, model_key) pairs.

Each case runs the open-access Exceptional Response Discrimination pipeline in the
NVFlare simulator and asserts the HE meta-analysis agrees with the clear-text
reference meta-analysis (within CKKS noise). 'Open-access' = the biomarker model
weights are clear-text and each client scores locally; the mean-stdev and
meta-analysis aggregations still run under CKKS.

The chain (see jobs/configs/config_meta_analysis_open.json + the reference oracle
phase in tests/sim_config_fed_server.json):

    KeyGen
    -> workflow_biomarker_score_computation              (clear, local)
    -> workflow_stat_analytics_scores_mean_stdev          (HE)
    -> workflow_biomarker_lr_fit                          (clear, local)
    -> workflow_stat_analytics_meta_analysis              (HE)              <-- compared
    -> workflow_reference_stat_analytics_scores_mean_stdev (clear oracle)
    -> workflow_biomarker_lr_fit_2                        (clear oracle)
    -> workflow_reference_stat_analytics_meta_analysis    (clear oracle)    <-- compared

site3 is the non-contributing leader, so the federated estimate is over
site1 + site2 on both the HE and reference paths.

The sweep stages an isolated job under tmp_path (no manual config swap needed).

Usage::

    # Full open-access sweep (slow):
    pytest backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_lcs_open.py -v

    # Single case:
    pytest -v -k "Glioma and cox_lasso" \
        backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_lcs_open.py

    # Exclude the slow sweep from a broader run:
    pytest -m "not slow"
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nvflare.private.fed.app.simulator.simulator_runner import SimulatorRunner

from .conftest import LOG_CONFIG_REL, SIM_CLIENTS, SWEEP_DETAIL_ATTR, StageJob, sweep_cancers

# Cancer types with both cox_lasso and logistic_reg coefficient files available,
# discovered per DUALITY_SIM_DATASOURCE_VERSION at collection time.
CANCERS = sweep_cancers()
MODEL_KEYS = ["cox_lasso", "logistic_reg"]

META_STAGE_DIR = "meta-analysis"
HE_WORKFLOW = "workflow_stat_analytics_meta_analysis"
REF_WORKFLOW = "workflow_reference_stat_analytics_meta_analysis"

# Reference mean-stdev is consulted first; a WARN means the score distribution is
# below the CKKS noise floor, so the HE-vs-reference comparison is meaningless.
MEAN_STDEV_STAGE_DIR = "mean-stdev"
REF_MEAN_STDEV_WORKFLOW = "workflow_reference_stat_analytics_scores_mean_stdev"

# Per-client biomarker_lr_fit outputs; a WARN on any site means that client's
# local logit fit degenerated (it contributes a zero share to meta-analysis).
# The production fit is FUSED into the meta-analysis workflow (no standalone
# production lr_fit workflow); the reference-oracle fit stays standalone as
# workflow_biomarker_lr_fit_2, which is what this skip-check consults. A fully
# degenerate production fit is still caught downstream by the meta-analysis FAIL.
LR_FIT_STAGE_DIR = "biomarker_lr_fit"
LR_FIT_WORKFLOWS = ("workflow_biomarker_lr_fit_2",)

# site3 is the non-contributing leader; the contributing sites are site1 / site2.
SITES_TO_CHECK = ("site1", "site2")
SITE = "site1"

RESULT_REL = Path("aggregated") / "processed_results.json"

# Non-hyphenated client names so NVFlare matches the config's site3 leader /
# non-contributing entries (see conftest.SIM_CLIENTS).
N_THREADS = 3

# Well above the ~1e-10 agreement seen in dev runs, tight enough to catch a real
# numerical regression. Single source for the LCS tolerance: lcs_enc and the combined
# sweeps import this value. Uniform 1e-4 with KM (see test_simulator_sweep_km_open).
TOLERANCE = 1e-4


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


def _collect_lr_fit_failures(workspace: Path) -> list[str]:
    """Return ``[<site>/<workflow>: <msg>, ...]`` for every degenerate LR fit."""
    failures: list[str] = []
    for site in SITES_TO_CHECK:
        for wf in LR_FIT_WORKFLOWS:
            path = _per_site_result_path(workspace, site, LR_FIT_STAGE_DIR, wf)
            if not path.is_file():
                continue
            payload = json.loads(path.read_text())
            if payload.get("status") == "WARN":
                failures.append(f"{site}/{wf}: {payload.get('msg', '<no msg>')}")
    return failures


def _is_numeric(value: object) -> bool:
    """True for ``int`` / ``float`` (not ``bool``) or ``None``."""
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _diff_results(he: dict, ref: dict, tol: float) -> list[str]:
    """Return human-readable mismatch lines, or an empty list on agreement.

    Only numeric fields participate. ``None`` vs ``None`` agrees; ``None`` vs a
    number is a mismatch.
    """
    mismatches: list[str] = []
    keys = {k for k, v in he.items() if _is_numeric(v)} | {
        k for k, v in ref.items() if _is_numeric(v)
    }
    for key in sorted(keys):
        if key not in he:
            mismatches.append(f"  {key}: missing in HE result")
            continue
        if key not in ref:
            mismatches.append(f"  {key}: missing in reference result")
            continue
        he_v, ref_v = he[key], ref[key]
        if he_v is None and ref_v is None:
            continue
        if he_v is None or ref_v is None:
            mismatches.append(f"  {key}: he={he_v!r} ref={ref_v!r}")
            continue
        delta = abs(he_v - ref_v)
        if delta > tol:
            mismatches.append(
                f"  {key}: he={he_v:.10g} ref={ref_v:.10g} delta={delta:.2e}"
            )
    return mismatches


def _case_id(value: object) -> str:
    return str(value).replace(" ", "_").replace(",", "").replace("/", "_")


@pytest.mark.slow
@pytest.mark.parametrize(
    ("cancer", "model_key"),
    [(c, m) for c in CANCERS for m in MODEL_KEYS],
    ids=_case_id,
)
def test_open_access_meta_analysis_matches_reference(
    cancer: str,
    model_key: str,
    tmp_path: Path,
    stage_job_lcs_open: StageJob,
    request: pytest.FixtureRequest,
) -> None:
    job_dir = stage_job_lcs_open(cancer, model_key)
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
            f"{cancer} / {model_key}: meta-analysis disagrees beyond {TOLERANCE:g}:\n"
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
