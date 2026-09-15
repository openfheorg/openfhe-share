from nvflare.private.fed.app.simulator.simulator_runner import SimulatorRunner
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Server config used when the job folder's stat-analytics workflow carries no
# ``computation_type`` (the shipped template deliberately leaves it empty: the
# backend stager fills it per submitted function, and any default placed there
# would leak into every deployed job). Same file the pytest sweep uses.
DEFAULT_SIM_SERVER_CONFIG = Path(__file__).resolve().parent.parent / "tests" / "sim_config_fed_server_km_open.json"
SERVER_CONFIG_REL = Path("app_server") / "config" / "config_fed_server.json"


def _load_env_file(path: str) -> None:
    """Minimal KEY=VALUE loader; does not override variables already in os.environ."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


def _maybe_set_sim_datasource_base_from_env_path(env_path: str) -> None:
    """If the env file lives under a directory named standalone, use that as the base for repo-relative paths."""
    p = Path(env_path).resolve()
    if p.name not in (".env.local", "default.env.local"):
        return
    if p.parent.name != "standalone":
        return
    os.environ.setdefault("DUALITY_SIM_DATASOURCE_BASE", str(p.parent))


def _find_checkout_biomarker_models_root() -> Path | None:
    """Return standalone/client_utils/model_files/project_2 from a full checkout."""
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "standalone" / "client_utils" / "model_files" / "project_2"
        if candidate.is_dir():
            return candidate
    return None


def _try_load_dotenv_local() -> None:
    """Load datasource and other vars from .env.local for simulator runs (see DUALITY_SIM_ENV_FILE)."""
    hinted = os.getenv("DUALITY_SIM_ENV_FILE")
    if hinted and os.path.isfile(hinted):
        _load_env_file(hinted)
        _maybe_set_sim_datasource_base_from_env_path(hinted)
        return
    cwd_file = Path.cwd() / ".env.local"
    if cwd_file.is_file():
        _load_env_file(str(cwd_file))
        _maybe_set_sim_datasource_base_from_env_path(str(cwd_file))
        return
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents):
        for candidate in (parent / ".env.local", parent / "standalone" / ".env.local"):
            if candidate.is_file():
                _load_env_file(str(candidate))
                _maybe_set_sim_datasource_base_from_env_path(str(candidate))
                return
    # No .env.local anywhere: fall back to the tracked standalone defaults so a
    # fresh checkout can run the simulator without seeding one first.
    for parent in [here] + list(here.parents):
        candidate = parent / "standalone" / "default.env.local"
        if candidate.is_file():
            _load_env_file(str(candidate))
            _maybe_set_sim_datasource_base_from_env_path(str(candidate))
            return


def _find_checkout_biomarker_models_root() -> Path | None:
    """Return standalone/client_utils/model_files/project_2 from a full checkout."""
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "standalone" / "client_utils" / "model_files" / "project_2"
        if candidate.is_dir():
            return candidate
    return None


_try_load_dotenv_local()

# Public simulator runs are local-wheel-only. The caller must install the
# bundled/local wheel before starting the simulator.
os.environ["DUALITY_NVFLARE_LIB_UPDATE_DISABLED"] = "1"

_models_root = _find_checkout_biomarker_models_root()
if _models_root is not None:
    os.environ.setdefault("DUALITY_SIM_BIOMARKER_MODELS_ROOT", str(_models_root))

os.environ["FL_IS_SIMULATOR"] = "true"
# Progress webhooks skip HTTP unless DUALITY_SIM_ENABLE_BACKEND_HTTP=1 (see analytics_aggregator / webhooks / persistor).
# Job custom code treats missing DUALITY_BACKEND_URL as "cloud" mode (AWS Secrets Manager + prod API).
# Default to a localhost base so local simulator stays in LOCAL_BUILD without AWS credentials.
# Override with your real backend URL when testing against a live API.
os.environ.setdefault("DUALITY_BACKEND_URL", "http://127.0.0.1:1")

# Suffix for simulator datasource env vars: DUALITY_SERVER_DATASOURCE_<N>, DUALITY_CLIENT_SITE1_DATASOURCE_<N>, ...
# Also selects MODEL_DIR_<N> for biomarker weights/cutoffs (see apis/utils.resolve_biomarker_model_paths).
# Edit here or set DUALITY_SIM_DATASOURCE_VERSION in the shell / .env.local, or pass --datasource-version.
DEFAULT_SIM_DATASOURCE_VERSION = "2_1"
os.environ.setdefault("DUALITY_SIM_DATASOURCE_VERSION", DEFAULT_SIM_DATASOURCE_VERSION)


def define_simulator_parser(simulator_parser):
    simulator_parser.add_argument("job_folder")
    simulator_parser.add_argument("-w", "--workspace", type=str, help="WORKSPACE folder")
    simulator_parser.add_argument("-n", "--n_clients", type=int, help="number of clients")
    simulator_parser.add_argument("-c", "--clients", type=str, help="client names list")
    simulator_parser.add_argument("-t", "--threads", type=int, help="number of parallel running clients")
    simulator_parser.add_argument("-gpu", "--gpu", type=str, help="list of GPU Device Ids, comma separated")
    simulator_parser.add_argument("-m", "--max_clients", type=int, default=100, help="max number of clients")
    simulator_parser.add_argument(
        "--datasource-version",
        type=str,
        default=None,
        metavar="N",
        help="override DUALITY_SIM_DATASOURCE_VERSION (DUALITY_*_DATASOURCE_<N> and MODEL_DIR_<N>, e.g. 1, 2_1)",
    )
    simulator_parser.add_argument(
        "--server-config",
        type=str,
        default=None,
        metavar="JSON",
        help=(
            "server config to run instead of the job folder's config_fed_server.json "
            "(e.g. tests/sim_config_fed_server_km_enc.json). The job folder is copied "
            "next to the workspace and the copy is patched; the template is never modified. "
            f"Defaults to {DEFAULT_SIM_SERVER_CONFIG.name} when the job folder's stat-analytics "
            "workflow has no computation_type."
        ),
    )


def _stat_workflow_lacks_computation_type(job_folder: str) -> bool:
    """True when the job's ``task_stat_analytics`` workflow has no ``computation_type``."""
    try:
        cfg = json.loads((Path(job_folder) / SERVER_CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for wf in cfg.get("workflows", []):
        args = wf.get("args") if isinstance(wf, dict) else None
        if not isinstance(args, dict) or args.get("train_task_name") != "task_stat_analytics":
            continue
        workload = args.get("workload_args")
        if not isinstance(workload, dict) or not workload.get("computation_type"):
            return True
    return False


def _stage_job_with_server_config(job_folder: str, server_config: str, workspace: str | None) -> str:
    """Copy ``job_folder`` next to the workspace and overwrite its server config."""
    src = Path(job_folder).resolve()
    cfg = Path(server_config).resolve()
    if not cfg.is_file():
        raise FileNotFoundError(f"--server-config not found: {cfg}")
    # Stage next to the workspace, not inside it: SimulatorRunner clears the
    # workspace directory during setup and would delete the staged copy.
    if workspace:
        ws = Path(workspace).resolve()
        staged = ws.parent / f"{ws.name}_staged_job"
    else:
        staged = Path(tempfile.mkdtemp(prefix="nvflare_sim_")) / "staged_job"
    if staged.exists():
        shutil.rmtree(staged)
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, staged)
    shutil.copy2(cfg, staged / SERVER_CONFIG_REL)
    print(f"[run_simulator] staged {src.name} -> {staged} with server config {cfg}", flush=True)
    return str(staged)


def _server_log_has_fatal_error(workspace: str | None) -> bool:
    if not workspace:
        return False
    log = Path(workspace) / "server" / "log.txt"
    try:
        return "FATAL_SYSTEM_ERROR" in log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def run_simulator(simulator_args, job_folder):
    simulator_args.job_folder = job_folder
    log_config = os.path.join(job_folder, "app_server/config/log_config.json")
    simulator = SimulatorRunner(
        job_folder=simulator_args.job_folder,
        workspace=simulator_args.workspace,
        clients=simulator_args.clients,
        n_clients=simulator_args.n_clients,
        threads=simulator_args.threads,
        gpu=simulator_args.gpu,
        max_clients=simulator_args.max_clients,
        log_config=log_config,
    )

    run_status = simulator.run()

    return run_status


def _resolve_client_names(args):
    """Canonical non-hyphenated client names for this run.

    NVFlare's SimulatorRunner hardcodes ``-n N`` to ``site-1 .. site-N`` (hyphenated,
    see simulator_runner.py), which won't match the non-hyphenated leader_client_name
    used in standalone (e.g. ``site3``). We translate ``-n`` into an explicit list of
    ``siteN`` names so NVFlare's hyphen branch is never reached. Returns the list, or
    None when neither ``-c`` nor ``-n`` was passed (let NVFlare derive from meta as before).
    """
    if args.clients:
        return [c.strip() for c in args.clients.split(",") if c.strip()]
    if args.n_clients:
        return [f"site{i + 1}" for i in range(args.n_clients)]
    return None


if __name__ == "__main__":
    """
    This is the main program when running the NVFlare Simulator. Use the Flare simulator API,
    create the SimulatorRunner object, do a setup(), then calls the run().
    """

    parser = argparse.ArgumentParser()
    define_simulator_parser(parser)
    args = parser.parse_args()
    if args.datasource_version is not None:
        os.environ["DUALITY_SIM_DATASOURCE_VERSION"] = args.datasource_version

    # Force canonical non-hyphenated client names (matches standalone + the site3 leader).
    # Passing them via clients= makes NVFlare skip its hardcoded "site-"+i branch. The names
    # must appear in meta.json's deploy_map.app_client (a static, simulator-only list -- the
    # stager regenerates deploy_map for deployment, so the template list only affects the sim).
    client_names = _resolve_client_names(args)
    if client_names:
        args.clients = ",".join(client_names)
        args.n_clients = None

    job_folder = args.job_folder
    server_config = args.server_config
    if server_config is None and _stat_workflow_lacks_computation_type(job_folder):
        server_config = str(DEFAULT_SIM_SERVER_CONFIG)
        print(
            f"[run_simulator] {SERVER_CONFIG_REL} in {job_folder} has no computation_type "
            f"(the stager fills it for deployed jobs); using --server-config {server_config}",
            flush=True,
        )
    if server_config is not None:
        job_folder = _stage_job_with_server_config(job_folder, server_config, args.workspace)

    try:
        status = run_simulator(args, job_folder)
    except Exception as exc:
        raise Exception('Computation Failed!') from exc
    fatal = _server_log_has_fatal_error(args.workspace)
    print(f'status: {status}' + (' (FATAL_SYSTEM_ERROR in server log)' if fatal else ''))
    if status != 0 or fatal:
        sys.exit(1)
