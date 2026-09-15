"""Shared fixtures for the NVFlare simulator sweeps.

The sweeps stage an isolated copy of ``nvflare_job_template`` per test case,
overwrite its ``config_fed_server.json`` with one of the ``tests/sim_config_fed_server_*.json``
chains ({km,lcs,combined} x {open,enc}), patch the ``cancer_type`` / ``model_key``
workload args, and run NVFlare's ``SimulatorRunner`` in-process. Everything is
written under pytest's ``tmp_path`` — the deployment template
(``nvflare_job_template/.../config_fed_server.json``) is never modified, so no
manual swap/restore is needed.

Requires: the test deps (``pip install -r tests/requirements-test.txt``) and the
``duality_nvflare_lib`` wheel installed into the active environment (see
``_require_duality_wheel``).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Callable

import pytest

# ``nvflare_jobs/tests/conftest.py`` -> ``nvflare_jobs/``.
NVFLARE_JOBS_DIR = Path(__file__).resolve().parent.parent
JOB_TEMPLATE_DIR = NVFLARE_JOBS_DIR / "jobs" / "nvflare_job_template"


def _find_share_root() -> Path | None:
    """Locate the full share checkout that owns this nvflare_jobs tree.

    Returns ``None`` when ``nvflare_jobs`` is mounted on its own (the Docker sweep
    runner mounts it at ``/work/nvflare_jobs``); there the runner supplies
    ``DUALITY_SIM_BIOMARKER_MODELS_ROOT`` and installs the wheel itself.
    """
    for base in (NVFLARE_JOBS_DIR, *NVFLARE_JOBS_DIR.parents):
        if (base / "standalone" / "client_utils" / "model_files" / "project_2").is_dir():
            return base
    return None


SHARE_ROOT = _find_share_root()
BIOMARKER_MODELS_DIR = (
    SHARE_ROOT / "standalone" / "client_utils" / "model_files" / "project_2" if SHARE_ROOT else None
)
STANDALONE_WHEELS_DIR = SHARE_ROOT / "standalone" / "wheels" if SHARE_ROOT else None
SERVER_CONFIG_REL = Path("app_server") / "config" / "config_fed_server.json"
CLIENT_CONFIG_REL = Path("app_client") / "config" / "config_fed_client.json"
LOG_CONFIG_REL = Path("app_server") / "config" / "log_config.json"
SERVER_SCHEMA_REL = Path("app_server") / "custom" / "global_schema.json"
RUN_SIMULATOR_PATH = NVFLARE_JOBS_DIR / "scripts" / "run_simulator.py"

# lean CKKS ring dimension. The biomarker packing needs batch (ring/2) >= cov_length,
# so this cannot go below 2 * cov_length.
LEAN_CKKS_RING_DIM = 4096


def _sweep_mode() -> str:
    """Sweep mode: 'lean' (default) or 'full'. See run_simulator_sweep.py --mode."""
    return (os.getenv("DUALITY_SWEEP_MODE", "lean").strip().lower() or "lean")


def _lean_active() -> bool:
    """True only when DUALITY_SWEEP_MODE is explicitly set to lean.

    The sweep runner always exports DUALITY_SWEEP_MODE; a bare-host ``pytest`` does
    not. Gating the destructive lean-only side effects (stripping observability from
    the staged configs and pruning the workspace) on an explicit opt-in keeps a
    plain ``pytest`` run from silently mutating configs or deleting its workspaces,
    which ``_sweep_mode()``'s ``lean`` default would otherwise trigger.
    """
    value = os.getenv("DUALITY_SWEEP_MODE")
    return value is not None and value.strip().lower() == "lean"


def _apply_lean_ring_dim() -> str:
    """lean trades HE security for speed: pin an INSECURE CKKS ring dimension so keygen
    and every ciphertext are cheaper. full mode leaves it unset, so the parties build a
    real HEStd_128_classic context and the sweep measures production parameters.

    Applied here rather than per entry point so the containerised sweep and a bare-host
    ``DUALITY_SWEEP_MODE=lean pytest`` agree. Simulator parties inherit the environment.
    Returns the effective setting, for logging.
    """
    existing = os.getenv("DUALITY_SIM_CKKS_RING_DIM", "").strip()
    if existing:
        return existing
    if _lean_active():
        os.environ["DUALITY_SIM_CKKS_RING_DIM"] = str(LEAN_CKKS_RING_DIM)
        return str(LEAN_CKKS_RING_DIM)
    return "full security"


_LEAN_RING_DIM_EFFECTIVE = _apply_lean_ring_dim()


def _strip_profiler_component(cfg: dict) -> bool:
    """Drop the observability hooks (profiler component + trace filter) from a config.

    lean mode records only pass/fail + test detail, so it disables per-party
    observability entirely (no profile_summary.json / trace.jsonl written during the
    run, and no profiler / trace-filter event overhead). Removes both:
      * the ``profiler`` component from ``components``; and
      * any ``TraceCorrelationFilter`` entry from ``task_data_filters`` (dropping a
        filter block once its ``filters`` list is emptied).
    Returns True if the config dict was modified.
    """
    changed = False

    comps = cfg.get("components")
    if isinstance(comps, list):
        kept = [c for c in comps if not (isinstance(c, dict) and c.get("id") == "profiler")]
        if len(kept) != len(comps):
            cfg["components"] = kept
            changed = True

    filter_blocks = cfg.get("task_data_filters")
    if isinstance(filter_blocks, list):
        kept_blocks: list = []
        blocks_changed = False
        for block in filter_blocks:
            if isinstance(block, dict) and isinstance(block.get("filters"), list):
                filters = block["filters"]
                kept_filters = [
                    f
                    for f in filters
                    if not (
                        isinstance(f, dict)
                        and "TraceCorrelationFilter" in str(f.get("path", ""))
                    )
                ]
                if len(kept_filters) != len(filters):
                    blocks_changed = True
                    if not kept_filters:
                        # The trace filter was this block's only filter; drop the
                        # now-empty block entirely.
                        continue
                    block["filters"] = kept_filters
            kept_blocks.append(block)
        if blocks_changed:
            cfg["task_data_filters"] = kept_blocks
            changed = True

    return changed

# Simulator server configs, staged over the template's config_fed_server.json under
# pytest's tmp_path (the deployment default is never touched). Named
# {km,lcs,combined} x {open,enc}:
#   - km       = survival Kaplan-Meier biomarker discovery
#   - lcs      = exceptional response discrimination (mean-stdev -> meta-analysis)
#   - combined = KM AND LCS for one model in a SINGLE job, sharing ONE per-patient
#                score computation (the reuse payoff)
#   - open     = clear-text scoring; enc = encrypted (score-cache producer + per-
#                consumer postprocess; the dot product runs once and is shared)
# Each config also stages the clear-text reference oracle it is compared against.
# See docs/UnifiedBiomarkerScorePlan.md.
_HERE = Path(__file__).resolve().parent
LCS_OPEN_SIM_CONFIG_PATH = _HERE / "sim_config_fed_server_lcs_open.json"
KM_OPEN_SIM_CONFIG_PATH = _HERE / "sim_config_fed_server_km_open.json"
COMBINED_OPEN_SIM_CONFIG_PATH = _HERE / "sim_config_fed_server_combined_open.json"
LCS_ENC_SIM_CONFIG_PATH = _HERE / "sim_config_fed_server_lcs_enc.json"
KM_ENC_SIM_CONFIG_PATH = _HERE / "sim_config_fed_server_km_enc.json"
COMBINED_ENC_SIM_CONFIG_PATH = _HERE / "sim_config_fed_server_combined_enc.json"

# Matches the ``--datasource-version`` used for manual simulator runs.
DEFAULT_DATASOURCE_VERSION = "2_1"


def _datasource_version() -> str:
    """Selected datasource version key (``<project>_<group>``, e.g. ``2_1``).

    Resolution order: the ``--datasource-version`` pytest option (written into
    the environment by ``pytest_configure`` so client subprocesses inherit it),
    then ``DUALITY_SIM_DATASOURCE_VERSION``, then the default.
    """
    return os.environ.get("DUALITY_SIM_DATASOURCE_VERSION", DEFAULT_DATASOURCE_VERSION)


def _datasource_schema_path(version: str) -> Path:
    project, group = version.split("_", 1)
    return (
        NVFLARE_JOBS_DIR
        / "global_schema"
        / f"project_{project}"
        / f"datasource_group_{group}"
        / "global_schema.json"
    )

# Canonical non-hyphenated client names. NVFlare's SimulatorRunner hardcodes
# ``-n N`` to ``site-1 .. site-N`` (hyphenated), which would not match the
# non-hyphenated ``site3`` leader / non-contributing client in the config.
# Passing explicit ``siteN`` names (they appear in meta.json's deploy_map)
# makes NVFlare skip its hyphen branch — mirroring scripts/run_simulator.py.
SIM_CLIENTS = ["site1", "site2", "site3"]

# Last-resort sweep parametrization when no model directory can be discovered
# at collection time. Normal runs derive
# the list from the selected group's model files via ``sweep_cancers()``.
FALLBACK_MSKCHORD_CANCERS = [
    "Breast Carcinoma",
    "Colorectal Cancer",
    "Non-Small Cell Lung Cancer",
    "Pancreatic Cancer",
    "Prostate Cancer",
]


def sweep_cancers() -> list[str]:
    """Cancer types with both cox_lasso and logistic_reg weight files for the
    selected datasource version — the sweep parametrization.

    Discovered at collection time from the model-files directory so the case
    list tracks data updates for the retained five-cancer MSKChord catalog.
    Resolution mirrors the
    runtime lookup: ``DUALITY_SIM_BIOMARKER_MODELS_ROOT`` first, else the
    in-repo ``standalone/client_utils/model_files/project_2`` tree. Falls back
    to ``FALLBACK_MSKCHORD_CANCERS`` when nothing can be discovered, keeping
    collection alive so the fixture-level error paths report the real problem.
    """
    version = os.environ.get("DUALITY_SIM_DATASOURCE_VERSION", DEFAULT_DATASOURCE_VERSION)
    group_dir_name = f"datasource_group_{version.split('_')[-1]}"
    candidates = []
    env_root = os.environ.get("DUALITY_SIM_BIOMARKER_MODELS_ROOT")
    if env_root:
        candidates.append(Path(env_root) / group_dir_name)
    # In-repo fallback: only reachable from a full share checkout. Container
    # runs mount nvflare_jobs near the filesystem root (e.g. /work/nvflare_jobs),
    # where this ancestor does not exist and the env root above is authoritative.
    if len(_HERE.parents) > 5:
        candidates.append(
            _HERE.parents[5] / "standalone" / "client_utils" / "model_files" / "project_2" / group_dir_name
        )
    for group_dir in candidates:
        if not group_dir.is_dir():
            continue
        per_model = {}
        for model_key in ("cox_lasso", "logistic_reg"):
            prefix = f"{model_key}_"
            per_model[model_key] = {
                p.name[len(prefix):-len("_weights.csv")]
                for p in group_dir.glob(f"{model_key}_*_weights.csv")
            }
        cancers = sorted(per_model["cox_lasso"] & per_model["logistic_reg"])
        if cancers:
            return cancers
    return list(FALLBACK_MSKCHORD_CANCERS)


StageJob = Callable[..., Path]


def _exec_run_simulator_module() -> None:
    """Execute ``scripts/run_simulator.py`` for its environment side effects.

    The script's module-level code sets ``FL_IS_SIMULATOR``,
    ``DUALITY_BACKEND_URL``, and (via ``_try_load_dotenv_local``) the
    ``DUALITY_*_DATASOURCE_*`` paths from ``standalone/.env.local``. Reusing it
    keeps the test environment identical to a manual
    ``python3 scripts/run_simulator.py`` invocation.
    """
    spec = importlib.util.spec_from_file_location(
        "_nvflare_sim_env_loader", str(RUN_SIMULATOR_PATH)
    )
    if spec is None or spec.loader is None:
        raise pytest.UsageError(f"Cannot load env loader from {RUN_SIMULATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--datasource-version",
        default=None,
        metavar="P_G",
        help="Project-2 datasource version key (for example, 2_1). Optional "
        "alternative to exporting DUALITY_SIM_DATASOURCE_VERSION — either "
        "works; when both are set the option wins for this run. Default "
        f"{DEFAULT_DATASOURCE_VERSION}. Drives sweep parametrization, the "
        "staged job's global schema, and the per-site FHIR bundle paths.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: full open-access simulator sweep; ~minutes per case",
    )
    # Resolve --datasource-version into the environment BEFORE collection so
    # sweep_cancers(), the staged schema, and the simulator client processes
    # (which inherit the environment) all agree on one version. Without the
    # option, DUALITY_SIM_DATASOURCE_VERSION (or the default) applies as before.
    version = config.getoption("--datasource-version")
    if version:
        if not re.fullmatch(r"\d+_\d+", version):
            raise pytest.UsageError(
                f"--datasource-version must look like 2_1, got {version!r}"
            )
        if not _datasource_schema_path(version).is_file():
            raise pytest.UsageError(
                f"--datasource-version {version}: no global schema at "
                f"{_datasource_schema_path(version)}"
            )
        os.environ["DUALITY_SIM_DATASOURCE_VERSION"] = version


def pytest_report_header() -> str:
    """Report the HE parameters, so a run's security level is never inferred from timings.

    Shows the raw DUALITY_SWEEP_MODE: only an explicit ``lean`` reduces the ring, while
    ``_sweep_mode()`` treats unset as lean, so naming the mode would read as a contradiction.
    """
    mode = os.getenv("DUALITY_SWEEP_MODE") or "unset"
    return (
        f"CKKS ring dimension: {_LEAN_RING_DIM_EFFECTIVE} (DUALITY_SWEEP_MODE={mode}) | "
        f"datasource version: {_datasource_version()}"
    )


# Attribute name used by the sweep to attach a short human-readable detail
# (e.g. ``"low SNR: |mean|=1.15e-07 stdev=0.00e+00"``) to its test node.
SWEEP_DETAIL_ATTR = "_sweep_detail"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    """Propagate ``_sweep_detail`` onto the call report and stash the call outcome.

    The stashed ``_sweep_failed`` flag lets ``_lean_prune_workspace`` keep a failed
    case's simulator workspace for debugging instead of pruning it. It defaults to
    ``True`` (keep) when the call phase never ran, e.g. a setup error.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        detail = getattr(item, SWEEP_DETAIL_ATTR, None)
        if detail:
            report.sweep_detail = detail
        setattr(item, "_sweep_failed", report.failed)


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    """Append the sweep detail to the verbose per-test status line (``-v``)."""
    detail = getattr(report, "sweep_detail", None)
    if not detail or report.when != "call":
        return None
    if report.passed:
        return "passed", ".", f"PASSED [{detail}]"
    if report.failed:
        return "failed", "F", f"FAILED [{detail}]"
    if report.skipped:
        return "skipped", "s", f"SKIPPED [{detail}]"
    return None


def _bundled_duality_wheel() -> Path | None:
    if STANDALONE_WHEELS_DIR is None:
        return None
    wheels = sorted(STANDALONE_WHEELS_DIR.glob("duality_nvflare_lib-*.whl"))
    return wheels[-1] if wheels else None


def _wheel_metadata_version(wheel: Path) -> str | None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            (name for name in archive.namelist() if name.endswith(".dist-info/METADATA")),
            None,
        )
        if metadata_name is None:
            return None
        text = archive.read(metadata_name).decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("Version:"):
            return line.partition(":")[2].strip()
    return None


@pytest.fixture(scope="session", autouse=True)
def _require_duality_wheel() -> None:
    """Require the local public snapshot wheel; never suggest the package registry."""
    bundled = _bundled_duality_wheel()
    installed = None
    try:
        installed = importlib.metadata.version("duality_nvflare_lib")
    except importlib.metadata.PackageNotFoundError:
        pass

    if importlib.util.find_spec("duality_nvflare_apis") is not None:
        if bundled is None:
            # Docker sweep mounts only nvflare_jobs and installs a locally-built wheel.
            return
        expected = _wheel_metadata_version(bundled)
        if expected is None or installed == expected:
            return
        raise pytest.UsageError(
            f"Wrong duality_nvflare_lib is installed ({installed!r}); this checkout bundles "
            f"{expected!r}. Install the local snapshot before running the sweep:\n"
            f"    python -m pip install --force-reinstall --no-index --no-deps {bundled}"
        )

    wheel_hint = bundled or (
        STANDALONE_WHEELS_DIR / "duality_nvflare_lib-*.whl"
        if STANDALONE_WHEELS_DIR
        else "standalone/wheels/duality_nvflare_lib-*.whl"
    )
    raise pytest.UsageError(
        "duality_nvflare_apis is not importable. Install the wheel bundled with this "
        "checkout before running the sweep:\n"
        f"    python -m pip install --force-reinstall --no-index --no-deps {wheel_hint}"
    )


_DATASOURCE_ENV_PATTERN = r"DUALITY_(?:SERVER|CLIENT_[A-Z0-9]+)_DATASOURCE_{suffix}"


def _resolve_env_datasource_path(raw: str) -> Path | None:
    """Host path behind a ``DUALITY_*_DATASOURCE_*`` value, as the FHIR resolver reads it.

    Repo-relative values resolve against ``DUALITY_SIM_DATASOURCE_BASE`` first, then the
    cwd chain, mirroring ``FHIRBaseConfigResolver._expand_relative_datasource_path``. A
    sibling ZIP also counts as a hit, so a deleted extract still resolves and is restored.
    """
    value = raw.strip()
    if not value or value.lower().startswith(("http://", "https://")):
        return None
    if Path(value).is_absolute():
        return Path(value).expanduser()

    hint = os.getenv("DUALITY_SIM_DATASOURCE_BASE")
    cwd = Path.cwd().resolve()
    bases = ([Path(hint)] if hint else []) + [cwd, *list(cwd.parents)[:64]]
    for base in bases:
        candidate = (base.expanduser().resolve() / value).resolve()
        if candidate.is_file() or candidate.with_suffix(".zip").is_file():
            return candidate
    return None


def _extract_bundle_json(zip_path: Path, json_path: Path, *, env_key: str) -> None:
    # Unique temp name: under xdist several workers may refresh the same bundle at once,
    # and each needs its own staging file before the atomic replace.
    staged = json_path.with_name(f"{json_path.name}.from-zip.{os.getpid()}")
    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        member = next((name for name in members if Path(name).name == json_path.name), None)
        if member is None:
            candidates = [name for name in members if Path(name).suffix.lower() == ".json"]
            if len(candidates) != 1:
                preview = ", ".join(candidates[:12]) or "<none>"
                raise pytest.UsageError(
                    f"{env_key}: cannot refresh {json_path.name} from {zip_path.name}. "
                    f"Archive JSON members: {preview}"
                )
            member = candidates[0]
        try:
            with archive.open(member) as source, staged.open("wb") as target:
                shutil.copyfileobj(source, target)
            staged.replace(json_path)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

    # Stamp the extraction time, not the archive member's date, or the JSON stays older
    # than the ZIP and every later run re-extracts the same bytes.
    os.utime(json_path, None)


def _refresh_datasource_bundles() -> list[str]:
    """Re-extract each selected FHIR bundle whose sibling ZIP is newer. Returns log lines.

    Only the ZIPs are tracked, so a pull updates the archive and leaves the extracted JSON
    stale — a bare-host run would then validate against data the repository no longer
    carries. Same rule as the docker sweep runner and ``client_utils/create_client.py``;
    a no-op in the container, whose mounted inputs have no sibling archive.
    """
    pattern = re.compile(_DATASOURCE_ENV_PATTERN.format(suffix=re.escape(_datasource_version())))
    messages: list[str] = []
    for env_key, raw in sorted(os.environ.items()):
        if not pattern.fullmatch(env_key):
            continue
        json_path = _resolve_env_datasource_path(raw)
        if json_path is None or json_path.suffix.lower() != ".json":
            continue
        zip_path = json_path.with_suffix(".zip")
        if not zip_path.is_file():
            continue
        if json_path.is_file() and json_path.stat().st_mtime >= zip_path.stat().st_mtime:
            continue
        _extract_bundle_json(zip_path, json_path, env_key=env_key)
        messages.append(f"{env_key}: refreshed {json_path.name} from {zip_path.name} (archive was newer).")
    return messages


@pytest.fixture(scope="session", autouse=True)
def _simulator_env(request: pytest.FixtureRequest) -> None:
    """Configure environment variables required by the workflow custom code.

    Delegates to ``scripts/run_simulator.py`` so the test environment matches a
    manual simulator invocation. Pins the datasource version and anchors the
    biomarker model lookup so it does not depend on cwd.
    """
    os.environ.setdefault("DUALITY_SIM_DATASOURCE_VERSION", DEFAULT_DATASOURCE_VERSION)
    if BIOMARKER_MODELS_DIR is not None:
        os.environ.setdefault("DUALITY_SIM_BIOMARKER_MODELS_ROOT", str(BIOMARKER_MODELS_DIR))
    # Public simulator runs are local-wheel-only. Set this before the staged
    # client/server duality_wheel_runtime modules are imported.
    os.environ["DUALITY_NVFLARE_LIB_UPDATE_DISABLED"] = "1"
    _exec_run_simulator_module()

    # The datasource paths only exist once run_simulator has loaded .env.local, so the
    # staleness check belongs here rather than in pytest_configure.
    reporter = request.config.pluginmanager.getplugin("terminalreporter")
    for message in _refresh_datasource_bundles():
        if reporter is not None:
            reporter.write_line(message)
        else:
            print(message)


# Test-only binning probe (see ``binning_probe.py``). The module is copied into each
# staged job's client app, so the capability lives only in jobs the sweep staged --
# never in the wheel or the production template.
_PROBE_MODULE = "binning_probe"
BINNING_PROBE_ENV = "SIM_BINNING_PROBE"


def binning_probe_path(tmp_path: Path) -> Path:
    """Where this case's probe records land."""
    return tmp_path / "binning-probe.jsonl"


def _install_binning_probe(job_dir: Path, client_cfg: dict) -> bool:
    """Copy the probe into ``job_dir`` and register it. True when ``client_cfg`` changed."""
    source = _HERE / f"{_PROBE_MODULE}.py"
    custom_dir = job_dir / CLIENT_CONFIG_REL.parent.parent / "custom"
    if not source.is_file() or not custom_dir.is_dir():
        return False
    shutil.copy2(source, custom_dir / source.name)

    components = client_cfg.setdefault("components", [])
    if any(
        isinstance(entry, dict) and entry.get("id") == _PROBE_MODULE for entry in components
    ):
        return False
    components.append({"id": _PROBE_MODULE, "path": f"{_PROBE_MODULE}.BinningProbe"})
    # Also an event handler: that is what makes NVFlare actually build the component,
    # and building it is the entire point -- its constructor installs the wrapper.
    handlers = client_cfg.setdefault("event_handlers", [])
    if f"@{_PROBE_MODULE}" not in handlers:
        handlers.append(f"@{_PROBE_MODULE}")
    return True


def _stage_job(
    tmp_path: Path, sim_config_path: Path, cancer_type: str, model_key: str
) -> Path:
    """Stage an isolated job folder with ``sim_config_path`` as its server config.

    Copies the job template to ``tmp_path/job``, overwrites its
    ``config_fed_server.json`` with ``sim_config_path``, and patches every
    workflow whose ``workload_args`` declares ``cancer_type`` / ``model_key`` /
    ``model_keys``. Patching by presence (not by workflow id) keeps the fixture
    stable if workflows are renamed or reordered. ``model_keys`` (the list form
    the encrypted chain's model_upload / scoring steps use) is set to
    ``[model_key]`` so it stays consistent with the singular ``model_key``.
    """
    job_dir = tmp_path / "job"
    shutil.copytree(JOB_TEMPLATE_DIR, job_dir)

    # Stage the selected datasource group's global schema over the template's
    # static copy. The template file is a placeholder (deployment overwrites it
    # via stage_global_schema); running with a mismatched schema silently drops
    # every model gene outside the staged panel from the risk score.
    version = _datasource_version()
    schema_src = _datasource_schema_path(version)
    if not schema_src.is_file():
        raise RuntimeError(
            f"No global schema for datasource version {version!r} at {schema_src}; "
            "the staged job would run with the template's stale schema."
        )
    shutil.copy2(schema_src, job_dir / SERVER_SCHEMA_REL)

    cfg_path = job_dir / SERVER_CONFIG_REL
    cfg = json.loads(sim_config_path.read_text())

    patched = 0
    for wf in cfg.get("workflows", []):
        wa = wf.get("args", {}).get("workload_args")
        if not isinstance(wa, dict):
            continue
        if "cancer_type" in wa:
            wa["cancer_type"] = cancer_type
        if "model_key" in wa:
            wa["model_key"] = model_key
            patched += 1
        if "model_keys" in wa:
            wa["model_keys"] = [model_key]
            patched += 1

    if patched == 0:
        raise RuntimeError(
            "No workflow with 'model_key'/'model_keys' found in sim config; the "
            "test scaffold is out of sync with the workflow definitions."
        )

    if _lean_active():
        # lean: no observability -> strip the profiler component and the trace
        # correlation filter from both the server and client apps. The server cfg
        # is written unconditionally below (its workload args were just patched);
        # the client's is a separate file, rewritten just below when anything changed.
        _strip_profiler_component(cfg)

    client_cfg_path = job_dir / CLIENT_CONFIG_REL
    try:
        client_cfg = json.loads(client_cfg_path.read_text())
        client_changed = _install_binning_probe(job_dir, client_cfg)
        if _lean_active():
            client_changed = _strip_profiler_component(client_cfg) or client_changed
        if client_changed:
            client_cfg_path.write_text(json.dumps(client_cfg, indent=2))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"WARNING: could not patch client config {client_cfg_path}: {exc}",
            file=sys.stderr,
            flush=True,
        )

    # Point the probe at this case's own file; the simulator's client processes
    # inherit the environment, so nothing else has to be threaded through.
    os.environ[BINNING_PROBE_ENV] = str(binning_probe_path(tmp_path))

    cfg_path.write_text(json.dumps(cfg, indent=2))
    return job_dir


@pytest.fixture(autouse=True)
def _lean_prune_workspace(request: pytest.FixtureRequest, tmp_path: Path):
    """lean mode: delete a PASSED case's heavy simulator workspace after the test.

    NVFlare writes the run workspace (HE ciphertexts, per-party job dirs) under the
    test's ``tmp_path``; in lean mode nothing reads it afterward (no perf manifest),
    so pruning here keeps peak disk near a single case instead of the whole sweep.
    A FAILED case keeps its workspace so it can be debugged. Runs in teardown, after
    the pass/fail report is recorded. No-op unless lean is explicitly active.
    """
    yield
    if not _lean_active():
        return
    # Defaults to True (keep) when no call report was stashed, e.g. a setup error.
    if getattr(request.node, "_sweep_failed", True):
        return
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def stage_job_lcs_open(tmp_path: Path) -> StageJob:
    """Isolated staged OPEN-ACCESS LCS (logistic calibration / meta-analysis) job."""

    def _stage(cancer_type: str, model_key: str) -> Path:
        return _stage_job(tmp_path, LCS_OPEN_SIM_CONFIG_PATH, cancer_type, model_key)

    return _stage


@pytest.fixture
def stage_job_km_open(tmp_path: Path) -> StageJob:
    """Isolated staged OPEN-ACCESS KM (survival biomarker-discovery) job."""

    def _stage(cancer_type: str, model_key: str) -> Path:
        return _stage_job(tmp_path, KM_OPEN_SIM_CONFIG_PATH, cancer_type, model_key)

    return _stage


@pytest.fixture
def stage_job_combined_open(tmp_path: Path) -> StageJob:
    """Isolated staged COMBINED OPEN-ACCESS job (one clear biomarker_score_computation
    feeding BOTH the reused-score KM grouping and the LCS mean-stdev/meta chain)."""

    def _stage(cancer_type: str, model_key: str) -> Path:
        return _stage_job(tmp_path, COMBINED_OPEN_SIM_CONFIG_PATH, cancer_type, model_key)

    return _stage


@pytest.fixture
def stage_job_lcs_enc(tmp_path: Path) -> StageJob:
    """Isolated staged ENCRYPTED LCS job (score-cache producer + LCS descale postprocess)."""

    def _stage(cancer_type: str, model_key: str) -> Path:
        return _stage_job(tmp_path, LCS_ENC_SIM_CONFIG_PATH, cancer_type, model_key)

    return _stage


@pytest.fixture
def stage_job_km_enc(tmp_path: Path) -> StageJob:
    """Isolated staged ENCRYPTED KM job (score-cache producer + KM risk-group postprocess)."""

    def _stage(cancer_type: str, model_key: str) -> Path:
        return _stage_job(tmp_path, KM_ENC_SIM_CONFIG_PATH, cancer_type, model_key)

    return _stage


@pytest.fixture
def stage_job_combined_enc(tmp_path: Path) -> StageJob:
    """Isolated staged COMBINED ENCRYPTED job (one model_upload + one score-cache producer
    feeding BOTH the KM risk-group postprocess and the LCS descale postprocess consumers)."""

    def _stage(cancer_type: str, model_key: str) -> Path:
        return _stage_job(tmp_path, COMBINED_ENC_SIM_CONFIG_PATH, cancer_type, model_key)

    return _stage


# ---------------------------------------------------------------------------
# Kaplan-Meier result comparison (shared by both survival sweeps)
#
# Unlike the LCS sweeps, whose meta-analysis result is a flat set of scalar
# fields, the KM workflow emits per-group survival *curves* over a shared time
# grid plus a scalar log-rank statistic::
#
#     {
#       "S_output": {"high_score": [S0, S1, ...], "low_score": [...]},
#       "times":    [t0, t1, ...],
#       "chi2":     <float>,
#       "p_value":  <float>,
#       "CI":       {...}       # optional, only when CI_type is set
#     }
#
# so the diff walks the arrays element-wise and the scalars pointwise, all
# within one tolerance. ``CI`` is informational and not compared.
# ---------------------------------------------------------------------------

# Per-group survival-curve fields (dict of group -> list of probabilities).
_KM_CURVE_FIELDS = ("S_output",)
# Scalar log-rank fields compared within tolerance. ``p_value`` is deliberately
# NOT compared: it can be smaller than the CKKS noise itself (a p of ~1e-5 with
# a comparison tolerance of the same order is meaningless), and it is the
# quantity the KM-nondeterminism notes track as run-to-run variable. It is still
# surfaced in each test's PASSED detail line for information, just not asserted.
_KM_SCALAR_FIELDS = ("chi2",)
# Shared time grid; compared so a grid mismatch surfaces as a clear error
# rather than a silent element-wise misalignment of the curves.
_KM_GRID_FIELD = "times"


def _km_is_number(value: object) -> bool:
    """True for ``int`` / ``float`` (not ``bool``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _km_diff_sequence(label: str, he: object, ref: object, tol: float) -> list[str]:
    """Element-wise diff of two numeric sequences within ``tol``.

    Reports only the single worst-offending index (with the total length) so a
    curve that disagrees at many grid points yields one readable line rather
    than hundreds.
    """
    if not isinstance(he, list) or not isinstance(ref, list):
        return [f"  {label}: non-list value he={type(he).__name__} ref={type(ref).__name__}"]
    if len(he) != len(ref):
        return [f"  {label}: length differs he={len(he)} ref={len(ref)}"]
    mismatches: list[str] = []
    worst_idx = -1
    worst_delta = 0.0
    for i, (a, b) in enumerate(zip(he, ref)):
        if a is None and b is None:
            continue
        if not _km_is_number(a) or not _km_is_number(b):
            mismatches.append(f"  {label}[{i}]: he={a!r} ref={b!r}")
            continue
        delta = abs(a - b)
        if delta > tol and delta > worst_delta:
            worst_delta = delta
            worst_idx = i
    if worst_idx >= 0:
        mismatches.append(
            f"  {label}[{worst_idx}]: he={he[worst_idx]:.10g} "
            f"ref={ref[worst_idx]:.10g} delta={worst_delta:.2e} (worst of {len(he)})"
        )
    return mismatches


def diff_km_results(
    he: dict, ref: dict, tol: float, scalar_tol: float | None = None
) -> list[str]:
    """Return human-readable mismatch lines, or an empty list on agreement.

    Compares the time grid, the per-group survival curves (element-wise), and
    the scalar log-rank statistics. Curves/scalars present on one side but not
    the other are reported as mismatches; ``CI`` is skipped.

    ``tol`` bounds the time grid and the survival curves, which are probabilities in
    [0, 1]. ``scalar_tol`` (defaulting to ``tol``) bounds the log-rank scalars, which
    are not on that scale -- see ``CHI2_TOLERANCE`` for why chi2 needs its own bound.
    """
    mismatches: list[str] = []

    # Time grid first: a mismatch here makes the curve diffs meaningless.
    if _KM_GRID_FIELD in he or _KM_GRID_FIELD in ref:
        mismatches += _km_diff_sequence(
            _KM_GRID_FIELD, he.get(_KM_GRID_FIELD), ref.get(_KM_GRID_FIELD), tol
        )

    for field in _KM_CURVE_FIELDS:
        he_curves = he.get(field)
        ref_curves = ref.get(field)
        if he_curves is None and ref_curves is None:
            continue
        if not isinstance(he_curves, dict) or not isinstance(ref_curves, dict):
            mismatches.append(
                f"  {field}: missing or non-dict (he={type(he_curves).__name__} "
                f"ref={type(ref_curves).__name__})"
            )
            continue
        for group in sorted(set(he_curves) | set(ref_curves)):
            if group not in he_curves:
                mismatches.append(f"  {field}.{group}: missing in HE result")
                continue
            if group not in ref_curves:
                mismatches.append(f"  {field}.{group}: missing in reference result")
                continue
            mismatches += _km_diff_sequence(
                f"{field}.{group}", he_curves[group], ref_curves[group], tol
            )

    for field in _KM_SCALAR_FIELDS:
        he_v = he.get(field)
        ref_v = ref.get(field)
        if he_v is None and ref_v is None:
            continue
        if not _km_is_number(he_v) or not _km_is_number(ref_v):
            mismatches.append(f"  {field}: he={he_v!r} ref={ref_v!r}")
            continue
        delta = abs(he_v - ref_v)
        if delta > (tol if scalar_tol is None else scalar_tol):
            mismatches.append(
                f"  {field}: he={he_v:.10g} ref={ref_v:.10g} delta={delta:.2e}"
            )

    return mismatches


def km_max_delta(he: dict, ref: dict) -> float:
    """Largest absolute HE-vs-reference difference across curves and scalars.

    For the human-readable ``PASSED [...]`` detail line only; ``diff_km_results``
    owns the pass/fail decision.
    """
    deltas = [0.0]
    for field in _KM_CURVE_FIELDS:
        he_curves = he.get(field) or {}
        ref_curves = ref.get(field) or {}
        if not isinstance(he_curves, dict) or not isinstance(ref_curves, dict):
            continue
        for group in set(he_curves) & set(ref_curves):
            hc, rc = he_curves[group], ref_curves[group]
            if not isinstance(hc, list) or not isinstance(rc, list):
                continue
            deltas += [
                abs(a - b) for a, b in zip(hc, rc) if _km_is_number(a) and _km_is_number(b)
            ]
    for field in _KM_SCALAR_FIELDS:
        he_v, ref_v = he.get(field), ref.get(field)
        if _km_is_number(he_v) and _km_is_number(ref_v):
            deltas.append(abs(he_v - ref_v))
    return max(deltas)


def _bucket_counts(arms: dict) -> dict:
    """``{(arm, cell, is_event): count}`` for one path's cohort, plus arm sizes."""
    buckets: dict[tuple, int] = {}
    sizes: dict[str, int] = {}
    for arm, payload in (arms or {}).items():
        sizes[str(arm)] = int(payload.get("n", 0))
        for cell in payload.get("cells", []):
            index, events, censored = int(cell[0]), int(cell[1]), int(cell[2])
            if events:
                buckets[(str(arm), index, True)] = events
            if censored:
                buckets[(str(arm), index, False)] = censored
    return {"buckets": buckets, "sizes": sizes}


def _patients_moved(primary: dict, reference: dict) -> int | None:
    """Exact count of patients whose arm differs between the two paths, or None.

    Every patient occupies exactly one ``(arm, time cell, event?)`` bucket, so moving
    one decrements its old bucket and increments its new one: the summed absolute
    difference over all buckets is twice the number that moved. Order-independent --
    it compares multisets, never positions -- so it needs no assumption that the two
    paths enumerate the cohort in the same order.

    None when the two sides are not comparable (different cohort size or grid), since
    a count would then be meaningless rather than merely imprecise.
    """
    left, right = _bucket_counts(primary), _bucket_counts(reference)
    if sum(left["sizes"].values()) != sum(right["sizes"].values()):
        return None  # different cohorts; nothing to say about re-binning
    delta = 0
    for key in set(left["buckets"]) | set(right["buckets"]):
        delta += abs(left["buckets"].get(key, 0) - right["buckets"].get(key, 0))
    return delta // 2


def km_binning_report(tmp_path: Path) -> str | None:
    """Short label for what the binning probe saw this case, or None if nothing.

    ``REBINNED n=<k>``: k patients landed in a different arm than the clear reference
    put them in. Exact, not a lower bound -- ``net 0`` marks the case where the arms
    came out the same size because patients crossed in both directions, which an
    arm-size comparison cannot see at all.

    ``BINNING OK``: both paths produced identical arms. Their Kaplan-Meier output is
    then identical by construction, so a case that still fails diverged in the
    aggregation, not in the binning.

    Either is followed by ``(<k> closer than <margin> to cutoff, <s> sites)``: k patients
    whose score sits within ``filter_engine_config.NEAR_CUTOFF_MARGIN`` of the cutoff, so
    their arm cannot be guaranteed and a disagreement about them is expected rather than a
    defect. The count comes from the clear path, which knows the exact ``score - cutoff``
    and so gives the same answer every run; counting it on the encrypted side would measure
    that run's ``rm`` draw instead. ``<s>`` is how many sites it covers -- see
    ``_near_cutoff_phrase`` for why that differs between the open and encrypted suites and
    must be stated. It stands alone as ``NEAR_CUTOFF (...)`` only when there was no
    reference to compare against.

    Read together with the verdict: ``REBINNED`` with a non-zero count is the expected
    consequence of an ambiguous cohort, ``REBINNED`` with a zero count is a defect, and
    ``BINNING OK`` on a failing case puts the error in the CKKS aggregation of N and d
    rather than in the binning.
    """
    path = binning_probe_path(tmp_path)
    try:
        records = [
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return None
    return _binning_label(records)


def _near_cutoff_phrase(count: int, sites: int) -> str:
    """``<n> closer than <margin> to cutoff, <k> sites`` -- threshold AND scope.

    The threshold is read from the code that applies it rather than restated here, so
    the label cannot drift from the constant the clear path actually counts against.

    The scope has to be stated because it differs by suite: a non-contributing site bins
    in the clear on both workflows, so it is excluded when an encrypted path is under
    test and included when a clear one is. Two suites can therefore report different
    counts for the same cohort, and without the site count that reads as a contradiction
    rather than as two measurements over two different scopes.
    """
    try:
        from duality_nvflare_apis.fhir.filter_engine_config import NEAR_CUTOFF_MARGIN

        threshold = f"closer than {float(NEAR_CUTOFF_MARGIN):g} to cutoff"
    except Exception:
        threshold = "near cutoff"
    return f"{count} {threshold}, {sites} site{'' if sites == 1 else 's'}"


def _binning_label(records: list) -> str | None:
    primary: dict[str, dict] = {}
    reference: dict[str, dict] = {}
    near_by_site: dict[str, int] = {}
    repeated = False
    for record in records:
        arms = record.get("arms") or {}
        if not arms:
            continue
        site = str(record.get("site", "?"))
        target = reference if record.get("kind") == "clear_recompute" else primary
        if site in target and target[site] != arms:
            # The same site and path reported twice with different arms: we cannot
            # tell which pair belongs together, so refuse to report a number.
            repeated = True
        target[site] = arms
        if record.get("near_cutoff") is not None:
            # Only the clear path reports this, and a site reporting twice reports the
            # same cohort both times, so assign rather than accumulate.
            near_by_site[site] = int(record["near_cutoff"])

    # Count the exposure only where the path under test actually bins: a site that runs
    # the clear path for both workflows cannot re-bin anyone.
    scope = near_by_site if not primary else {s: n for s, n in near_by_site.items() if s in primary}
    near_total = sum(scope.values())
    near_phrase = _near_cutoff_phrase(near_total, len(scope))
    # Shown whenever the clear path measured it, zero included: an absent parenthetical
    # has to mean "not measured", not "measured as none".
    suffix = f" ({near_phrase})" if scope else ""

    if not primary and not reference:
        errors = [r.get("error") for r in records if r.get("error")]
        return f"PROBE FAILED ({str(errors[0])[:60]})" if errors else None
    if repeated:
        return f"BINNING INCONCLUSIVE (duplicate probe records){suffix}"

    if not primary:
        # Nothing encrypted or reused to compare against the recompute reference --
        # the open KM sweep runs the same clear path twice, so this is expected there.
        return f"NEAR_CUTOFF ({near_phrase})" if near_total else None
    if not set(primary) <= set(reference):
        # Every site under test needs a clear counterpart, or the count silently
        # covers fewer sites while still reading as exact. The reverse asymmetry is
        # normal and must not trip this: a non-contributing site runs the clear path
        # for both workflows, so it appears only under ``clear_recompute``.
        return f"BINNING INCONCLUSIVE (no reference for {sorted(set(primary) - set(reference))}){suffix}"
    compared = [(primary[site], reference[site]) for site in primary]

    moved = 0
    for own, ref in compared:
        site_moved = _patients_moved(own, ref)
        if site_moved is None:
            return f"BINNING INCONCLUSIVE (cohorts differ){suffix}"
        moved += site_moved

    if not moved:
        return f"BINNING OK{suffix}"
    sizes_match = all(_bucket_counts(o)["sizes"] == _bucket_counts(r)["sizes"] for o, r in compared)
    return f"REBINNED n={moved}{' net 0' if sizes_match else ''}{suffix}"
