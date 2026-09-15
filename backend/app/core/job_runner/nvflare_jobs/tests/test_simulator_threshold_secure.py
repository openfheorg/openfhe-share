"""End-to-end secure threshold-samples (protected sample-count check) simulator tests.

These run the REAL multiparty pipeline the unit tests and the single-party CKKS probe
cannot cover: threshold keygen, the +1-spare-level encryption reaching every executor
through the job meta, the towers=2 compressed masked margin surviving the partial
multiparty decrypt (with its noise flooding), and the pass/stop verdict + error.json
wiring. The chain is the smallest one available (open KM: KeyGen -> threshold ->
kaplan-meier + clear reference), with the secure threshold workflow injected after
KeyGen the same way NVFlareJobStager does for deployed jobs.

Determinism instead of repetition: the historical failure (masked margin wrapping the
CKKS decode bound, ~1-2% of runs per workflow slot) was a mask-tail event, so instead
of running the job hundreds of times, ``DUALITY_SIM_THRESHOLD_MASK_Z`` pins the total
mask exponent at the clip bound -- one run covers the exact draw that used to wrap.

Lean-mode caveat: the sweep runner's lean mode pins an INSECURE reduced CKKS ring
dimension (DUALITY_SIM_CKKS_RING_DIM). The threshold verdict rides on decrypt headroom
and noise behavior, so a lean pass does not certify the production parameterization --
every test here emits ``ThresholdLeanModeWarning`` when lean/reduced-ring is active.
Run at least once with ``DUALITY_SWEEP_MODE=full`` (or the ring unset) before relying
on it for a release.

Usage (on a full checkout DUALITY_SIM_BIOMARKER_MODELS_ROOT self-defaults to the
in-repo model tree; make sure the venv carries the current duality_nvflare_lib
wheel -- ``pip install --force-reinstall --no-deps wheels/duality_nvflare_lib-*.whl``)::

    DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 \
    pytest -v backend/app/core/job_runner/nvflare_jobs/tests/test_simulator_threshold_secure.py
"""

from __future__ import annotations

import copy
import json
import os
import warnings
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import pytest
from nvflare.private.fed.app.simulator.simulator_runner import SimulatorRunner

from .conftest import (
    LOG_CONFIG_REL,
    SERVER_CONFIG_REL,
    SIM_CLIENTS,
    StageJob,
    _lean_active,
)
from .test_simulator_sweep_km_open import (
    KM_STAGE_DIR,
    N_THREADS,
    _result_path,
)

CANCER = "Pancreatic Cancer"
MODEL_KEY = "cox_lasso"
HE_WORKFLOW = "workflow_stat_analytics"
THRESHOLD_WORKFLOW_ID = "workflow_threshold_samples_secure"
MASK_Z_ENV = "DUALITY_SIM_THRESHOLD_MASK_Z"
FORCE_COUNT_ENV = "DUALITY_SIM_THRESHOLD_FORCE_COUNT"

# Original log-DP mask clip for the (<=5 owners, T<=10) branch; forcing the total mask
# exponent here reproduces, deterministically, the draw that wrapped the decrypted sign
# before the 2-tower fix (margin 20.5 * e^27.14 ~ 1.25e13 >> the old ~1e6 decode bound).
FULL_POSITIVE_CLIP = "27.14"
# Deep negative exponent that stays ABOVE the multiparty decryption noise floor
# (20.5 * e^-13.5 ~ 2.8e-5 > ~1e-6): the verdict must still be a deterministic pass.
# The full negative clip is intentionally NOT asserted as a pass: 20.5 * e^-27.14 sinks
# below the noise floor, where the sign is unreliable by design (the aggregator warns).
DEEP_NEGATIVE_Z = "-13.5"


class ThresholdLeanModeWarning(UserWarning):
    """Threshold e2e ran with lean/reduced-ring CKKS parameters (not production)."""


# The threshold pre-pass validates the KM workflow's biomarker model paths, which
# resolve through DUALITY_SIM_BIOMARKER_MODELS_ROOT. Without it the pre-pass errors
# out before any verdict (and the simulator still exits 0), so on a full checkout
# default it to the in-repo models tree instead of failing five tests cryptically.
# Applied at import (the conftest ring-dim pattern), not in a fixture: simulator
# parties can snapshot the environment before a test-time monkeypatch runs.
# The containerised sweep mounts nvflare_jobs near the filesystem root (e.g.
# /work/nvflare_jobs), where the repo ancestor does not exist and the runner-provided
# env root is authoritative -- same depth guard as conftest.sweep_cancers.
_parents = Path(__file__).resolve().parents
_REPO_MODELS_ROOT = (
    _parents[6] / "standalone" / "client_utils" / "model_files" / "project_2"
    if len(_parents) > 6
    else None
)
if (
    not os.getenv("DUALITY_SIM_BIOMARKER_MODELS_ROOT", "").strip()
    and _REPO_MODELS_ROOT is not None
    and _REPO_MODELS_ROOT.is_dir()
):
    os.environ["DUALITY_SIM_BIOMARKER_MODELS_ROOT"] = str(_REPO_MODELS_ROOT)


@pytest.fixture(autouse=True)
def _models_root_default() -> None:
    if not os.getenv("DUALITY_SIM_BIOMARKER_MODELS_ROOT", "").strip():
        pytest.skip(
            "DUALITY_SIM_BIOMARKER_MODELS_ROOT is not set and no in-repo model tree "
            f"was found ({_REPO_MODELS_ROOT}); the threshold pre-pass cannot validate "
            "the KM workflow without it."
        )


@pytest.fixture(autouse=True)
def _warn_when_lean() -> None:
    ring = os.getenv("DUALITY_SIM_CKKS_RING_DIM", "").strip()
    if _lean_active() or ring:
        warnings.warn(
            "Secure-threshold e2e tests are running with lean/reduced CKKS parameters "
            f"(DUALITY_SIM_CKKS_RING_DIM={ring or 'lean default'}). The threshold "
            "verdict depends on decrypt headroom and noise behavior, so this run does "
            "NOT certify the production parameterization; run once with "
            "DUALITY_SWEEP_MODE=full before a release.",
            ThresholdLeanModeWarning,
        )


def _threshold_workflow(min_global_samples: int, workflows: Dict[str, dict]) -> dict:
    """The secure threshold workflow entry, shaped like NVFlareJobStager's template."""
    return {
        "id": THRESHOLD_WORKFLOW_ID,
        "path": "workflow_runtime.customSAG",
        "args": {
            "min_clients": 0,
            "num_rounds": 2,
            "start_round": 0,
            "aggregator_id": "aggregator",
            "persistor_id": "persistor",
            "persist_every_n_rounds": 2,
            "shareable_generator_id": "shareable_generator",
            "train_task_name": "task_threshold_samples_secure",
            "allow_empty_global_weights": True,
            "train_timeout": 0,
            "wait_time_after_min_received": 0,
            "workload_args": {
                "min_global_samples": min_global_samples,
                "workflows": workflows,
            },
        },
    }


StageThreshold = Callable[..., Path]


@pytest.fixture
def stage_threshold_job(stage_job_km_open: StageJob) -> StageThreshold:
    """Stage the open-KM job with a secure threshold workflow injected after KeyGen.

    The threshold's per-workflow args mirror the config's own stat workflows (the same
    duplication the deployment stager performs), optionally extended with
    ``extra_workflows`` entries that only exist for the pre-count.
    """

    def _stage(
        min_global_samples: int,
        extra_workflows: Optional[Dict[str, dict]] = None,
    ) -> Path:
        job_dir = stage_job_km_open(CANCER, MODEL_KEY)
        cfg_path = job_dir / SERVER_CONFIG_REL
        cfg = json.loads(cfg_path.read_text())

        counted = {
            wf["id"]: copy.deepcopy(wf["args"]["workload_args"])
            for wf in cfg["workflows"]
            if wf["id"].startswith("workflow_stat_analytics")
        }
        assert counted, "km_open sim config lost its stat workflow; test scaffold stale"
        if extra_workflows:
            counted.update(copy.deepcopy(extra_workflows))

        keygen_idx = next(
            i for i, wf in enumerate(cfg["workflows"]) if wf["id"] == "workflow_KeyGen"
        )
        cfg["workflows"].insert(
            keygen_idx + 1, _threshold_workflow(min_global_samples, counted)
        )
        cfg_path.write_text(json.dumps(cfg, indent=2))
        return job_dir

    return _stage


def _run_simulator(job_dir: Path, tmp_path: Path) -> Tuple[int, Path]:
    workspace = tmp_path / "ws"
    runner = SimulatorRunner(
        job_folder=str(job_dir),
        workspace=str(workspace),
        clients=",".join(SIM_CLIENTS),
        n_clients=None,
        threads=N_THREADS,
        log_config=str(job_dir / LOG_CONFIG_REL),
    )
    return runner.run(), workspace


def _threshold_error_payloads(workspace: Path) -> Dict[str, dict]:
    """{workflow_name: payload} for every threshold-stage error.json in the workspace."""
    found: Dict[str, dict] = {}
    for path in workspace.rglob("error.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("stage") == "threshold_samples":
            found[payload.get("workflow", str(path))] = payload
    return found


def _all_errors_digest(workspace: Path) -> str:
    """One line per error.json anywhere in the workspace, for assertion messages.

    The simulator exits 0 even when a workflow errors out (the failure lands in an
    error.json instead), so a bare 'result missing' assertion hides the real cause --
    e.g. an unset DUALITY_SIM_BIOMARKER_MODELS_ROOT failing prepass validation."""
    lines = []
    for path in sorted(workspace.rglob("error.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            payload = {}
        lines.append(
            f"  {path.relative_to(workspace)}: stage={payload.get('stage')!r} "
            f"message={str(payload.get('message'))[:160]!r}"
        )
    return "\n".join(lines) if lines else "  (no error.json files in the workspace)"


def _workspace_log_text(workspace: Path) -> str:
    chunks = []
    for pattern in ("*.log", "*.txt"):
        for path in workspace.rglob(pattern):
            try:
                chunks.append(path.read_text(errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def _assert_job_computed(workspace: Path) -> None:
    km_path = _result_path(workspace, KM_STAGE_DIR, HE_WORKFLOW)
    assert km_path.is_file(), (
        f"Downstream Kaplan-Meier result missing ({km_path}); the threshold pre-pass "
        "stopped or broke a run that should have proceeded. Errors found in the "
        f"workspace:\n{_all_errors_digest(workspace)}"
    )
    threshold_errors = _threshold_error_payloads(workspace)
    assert not threshold_errors, (
        f"Threshold pre-pass wrote stop errors on a passing run: {threshold_errors}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("min_global_samples", [10, 20], ids=["T10", "T20"])
def test_secure_threshold_passes_with_ample_data(
    min_global_samples: int,
    tmp_path: Path,
    stage_threshold_job: StageThreshold,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both (sigma, B) branches: counts clip at T per site, margin is maximal, the job
    must proceed and the server must log one masked margin per counted workflow with
    no reliability warnings."""
    monkeypatch.delenv(MASK_Z_ENV, raising=False)
    monkeypatch.delenv(FORCE_COUNT_ENV, raising=False)
    job_dir = stage_threshold_job(min_global_samples)

    status, workspace = _run_simulator(job_dir, tmp_path)

    assert status == 0, f"Simulator returned non-zero status: {status}"
    _assert_job_computed(workspace)

    log_text = _workspace_log_text(workspace)
    assert "Secure threshold masked margin for" in log_text, (
        "The aggregator's masked-margin debug line is missing from the workspace logs; "
        "either logging broke or an old wheel (< 1.2.7.14.19) handled the aggregation."
    )
    assert "threshold verdict is unreliable" not in log_text, (
        "Wrap/noise reliability warning fired on an ample-data run."
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "forced_total_z",
    [FULL_POSITIVE_CLIP, DEEP_NEGATIVE_Z],
    ids=["mask_at_positive_clip", "mask_deep_negative"],
)
def test_secure_threshold_survives_extreme_masks(
    forced_total_z: str,
    tmp_path: Path,
    stage_threshold_job: StageThreshold,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deterministic tail: at the full positive clip the masked margin is ~1.25e13,
    which wrapped to a random sign (false 'threshold not met') before the 2-tower fix.
    Simulator clients inherit this process's environment, so the env var reaches every
    site's executor."""
    monkeypatch.setenv(MASK_Z_ENV, forced_total_z)
    monkeypatch.delenv(FORCE_COUNT_ENV, raising=False)
    job_dir = stage_threshold_job(10)

    status, workspace = _run_simulator(job_dir, tmp_path)

    assert status == 0, (
        f"Simulator returned non-zero status {status} with forced mask exponent "
        f"{forced_total_z}: the masked-margin decrypt likely wrapped or drowned."
    )
    _assert_job_computed(workspace)


@pytest.mark.slow
def test_secure_threshold_stops_run_below_threshold(
    tmp_path: Path,
    stage_threshold_job: StageThreshold,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The below-threshold verdict, end to end: the encrypted sign check must come out
    negative, stop the whole run, write BELOW_SAMPLE_THRESHOLD error.json files, and
    produce no downstream result.

    This dataset cannot yield a genuinely small cohort (only the general-statistics
    pipeline can: the biomarker chains count whole per-cancer cohorts, and columns like
    the schema's ``income`` are absent from the project-2 bundles entirely, which stops
    the run earlier, in extraction). ``DUALITY_SIM_THRESHOLD_FORCE_COUNT`` therefore
    pins every site's local pre-count below T, exercising the same encrypted negative
    margin a real sub-threshold general-statistics cohort produces."""
    monkeypatch.delenv(MASK_Z_ENV, raising=False)
    monkeypatch.setenv(FORCE_COUNT_ENV, "3")  # 3 sites x 3 = 9 < T=10
    job_dir = stage_threshold_job(10)

    status, workspace = _run_simulator(job_dir, tmp_path)

    errors = _threshold_error_payloads(workspace)
    assert errors, (
        "Threshold pre-pass wrote no stop errors although every count was forced below "
        f"T. Errors found in the workspace:\n{_all_errors_digest(workspace)}"
    )
    below = {w for w, p in errors.items() if p.get("code") == "BELOW_SAMPLE_THRESHOLD"}
    assert below, f"No workflow carries BELOW_SAMPLE_THRESHOLD; got: {errors}"
    assert all(
        p.get("code") in ("BELOW_SAMPLE_THRESHOLD", "RUN_STOPPED_BY_SAMPLE_THRESHOLD")
        for p in errors.values()
    ), f"Unexpected threshold error codes: {errors}"

    km_path = _result_path(workspace, KM_STAGE_DIR, HE_WORKFLOW)
    assert not km_path.is_file(), (
        "Downstream KM result exists although the threshold pre-pass stopped the run."
    )
