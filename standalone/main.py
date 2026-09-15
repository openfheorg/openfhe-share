# purpose: top level orchestrator for local Duality setup
# runs staged tasks: mysql check, local source verification, nvflare provision, docker compose
# uses .env.local for configuration and can accept an explicit --env-file
# subcommands:
#   codebase  -> verify local backend and frontend source directories
#   mysql     -> verify or install local mysql  (skipped when DUALITY_DB_MODE=container)
#   nvflare   -> install nvflare and provision workspace
#   docker    -> build, up, down, logs, ps, pull, run (reset+build+up)
#   rebuild   -> rebuild and restart selected services from local source
#   update    -> git pull selected services, rebuild, restart
#   wheel     -> Build Wheel & Redeploy NVFlare Server/Client
#   clientdb  -> persist a NVFLARE client entry in MySQL so a site can receive broadcasted jobs
#   ui        -> interactive status dashboard and rebuild menu
# if no subcommand is given, runs mysql -> codebase and then either rebuilds existing containers or performs docker run
#
# Note:
# - To use the new Compose-managed MySQL service, set DUALITY_DB_MODE=container (default).
#   In that mode, the "mysql" step is a no-op and docker-compose brings up the DB.
# - To use a host-installed MySQL, set DUALITY_DB_MODE=host and the previous installer/check runs.

import argparse
import os
import sys
import subprocess
import time
from pathlib import Path
from shutil import copyfile

from utils.environment_utils import load_env_file
from utils.ip_utils import get_ip
from utils.mysql_driver_utils import ensure_mysql_driver
from mysql_stage.mysql_check_or_install import run as mysql_run
from nvflare_stage.nvflare_install_and_provision import run as nvflare_run
from codebase_stage.establish_code_base import run as codebase_run

try:
    from docker_stage.container_builder import ContainerBuilder
except Exception:
    ContainerBuilder = None

try:
    from client_utils.create_client import ensure_client_registered  # type: ignore
except Exception:
    ensure_client_registered = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent

SPLITTER = "============================================================"


def cmd_codebase(args) -> int:
    return codebase_run(getattr(args, "only", "all")) or 0


def cmd_mysql(_args) -> int:
    mode = (os.getenv("DUALITY_DB_MODE") or "container").strip().lower()
    if mode == "container":
        print(
            "[INFO] DUALITY_DB_MODE=container -> skipping host mysql check/install. Compose 'mysql' service will be used.",
            flush=True,
        )
        return 0
    return mysql_run() or 0


def cmd_nvflare(_args) -> int:
    return nvflare_run() or 0


def _resolve_env_file(cli_env_file: str | None) -> str | None:
    if cli_env_file:
        return cli_env_file
    p = REPO_ROOT / ".env.local"
    if p.exists():
        return str(p)
    return None


def _builder_from_args(args) -> "ContainerBuilder | None":
    if ContainerBuilder is None:
        print("[ERROR] Docker support not available (docker_stage/container_builder.py import failed).", flush=True)
        return None

    project_dir = REPO_ROOT / "docker_stage"
    if not project_dir.exists():
        print(f"[ERROR] docker_stage folder not found at {project_dir}", flush=True)
        return None

    env_file = _resolve_env_file(args.env_file)
    return ContainerBuilder(project_dir=project_dir, env_file=env_file)


def _read_env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return None


def _replace_or_append_env(path: Path, key: str, value: str):
    if not path.exists():
        path.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = []
    found = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith(f"{key}="):
            lines.append(f"{key}={value}")
            found = True
        else:
            lines.append(raw)
    if not found:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_docker(args) -> int:
    action = args.action or "run"

    needs_provision = action in ("run", "build", "up")
    if needs_provision:
        rc = nvflare_run()
        if rc:
            return rc

    env_file_path = _resolve_env_file(args.env_file)
    if env_file_path:
        load_env_file(env_file_path)

    builder = _builder_from_args(args)
    if builder is None:
        return 2

    if action == "build":
        return builder.build(services=args.services, no_cache=args.no_cache)
    elif action == "up":
        return builder.up(services=args.services, detach=not args.attach, build=not args.no_build)
    elif action == "down":
        return builder.down(remove_volumes=args.volumes)
    elif action == "logs":
        return builder.logs(services=args.services, follow=args.follow)
    elif action == "ps":
        return builder.ps()
    elif action == "pull":
        return builder.pull(services=args.services)
    elif action == "run":
        return builder.run_all(no_cache=args.no_cache)
    else:
        print(f"[ERROR] Unknown docker action: {action}", flush=True)
        return 2


def cmd_rebuild(args) -> int:
    builder = _builder_from_args(args)
    if builder is None:
        return 2

    rc = builder.rebuild(services=args.services, no_cache=args.no_cache)
    return rc


def cmd_update(args) -> int:
    builder = _builder_from_args(args)
    if builder is None:
        return 2

    return builder.update(services=args.services, no_cache=args.no_cache)


def cmd_clientdb(args) -> int:
    if ensure_client_registered is None:
        print("[ERROR] client_utils.create_client.ensure_client_registered not available.", flush=True)
        return 2

    site = args.site.strip()
    if not site:
        print("[ERROR] --site must be a non-empty string.", flush=True)
        return 2

    try:
        env_file = _resolve_env_file(args.env_file)
        if env_file:
            load_env_file(env_file)

        from client_utils.create_client import ping_backend_login  # type: ignore

        ping_backend_login()

        client_id, user_id = ensure_client_registered(site)
        print(f"[INFO] Client entry ensured for '{site}': client_id={client_id}, user_id={user_id}", flush=True)
        return 0
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    except Exception as e:
        print(f"[ERROR] Failed to create client entry: {e}", flush=True)
        return 2


def cmd_client(args) -> int:
    try:
        from client_utils import create_client  # type: ignore
    except Exception:
        print("[ERROR] client_utils.create_client not available.", flush=True)
        return 2

    cli_args: list[str] = []
    if args.site:
        cli_args += ["--site", args.site]
    if args.tar_file:
        cli_args += ["--tar-file", args.tar_file]
    if args.env_file:
        cli_args += ["--env-file", args.env_file]
    if args.tar_kit:
        cli_args.append("--tar-kit")
    if args.compose_file:
        cli_args += ["--compose-file", args.compose_file]
    if args.project:
        cli_args += ["--project", args.project]
    if getattr(args, "no_cache", False):
        cli_args.append("--no-cache")

    old_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0]] + cli_args
        create_client.main()
        return 0
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    finally:
        sys.argv = old_argv


def _ensure_env_local_seed():
    src = REPO_ROOT / "default.env.local"
    dst = REPO_ROOT / ".env.local"

    if not src.exists():
        print("[ERROR] Missing default.env.local. Please pull down from repository.", flush=True)
        sys.exit(1)

    try:
        copyfile(src, dst)

        db_mode = _read_env_value(dst, "DUALITY_DB_MODE")
        db_mode_value = (db_mode or "").strip().lower()

        current = _read_env_value(dst, "DUALITY_NVFLARE_HOST")
        if current is None or current.strip() == "" or current.strip().lower() == "auto":
            host = "nvflare" if db_mode_value == "container" else get_ip()
            _replace_or_append_env(dst, "DUALITY_NVFLARE_HOST", host)
            print(f"[INFO] Seeded .env.local and set DUALITY_NVFLARE_HOST={host}", flush=True)
        else:
            print(f"[INFO] Seeded .env.local; preserving DUALITY_NVFLARE_HOST={current}", flush=True)

        if db_mode is None or db_mode.strip() == "":
            _replace_or_append_env(dst, "DUALITY_DB_MODE", "container")
            print("[INFO] Seeded .env.local and set DUALITY_DB_MODE=container", flush=True)
    except Exception as e:
        print(f"[WARN] Could not seed .env.local: {e}", flush=True)


def _project_containers_exist() -> bool:
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return False
    for line in out.splitlines():
        if line.strip().startswith("duality-"):
            return True
    return False


def _list_running_client_sites() -> list[str]:
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return []
    sites: list[str] = []
    for name in out.splitlines():
        n = name.strip()
        if not n.startswith("duality-client-"):
            continue
        suffix = n[len("duality-client-") :]
        if suffix.startswith("results-"):
            continue
        if "-" in suffix:
            site = suffix.rsplit("-", 1)[0]
        else:
            site = suffix
        if site and site not in sites:
            sites.append(site)
    return sites


def _run_client_command(site: str, env_file_path: str | None) -> int:
    exe = sys.executable or "python"
    cmd = [exe, str(REPO_ROOT / "main.py")]
    if env_file_path:
        cmd += ["--env-file", env_file_path]
    cmd += ["client", "--site", site]
    try:
        subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))
        return 0
    except subprocess.CalledProcessError as e:
        return int(e.returncode) if isinstance(e.returncode, int) else 2
    except Exception:
        return 2


def _run_clientdb_command(site: str, env_file_path: str | None) -> int:
    exe = sys.executable or "python"
    cmd = [exe, str(REPO_ROOT / "main.py")]
    if env_file_path:
        cmd += ["--env-file", env_file_path]
    cmd += ["clientdb", "--site", site]
    try:
        subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))
        return 0
    except subprocess.CalledProcessError as e:
        return int(e.returncode) if isinstance(e.returncode, int) else 2
    except Exception:
        return 2


def _redeploy_running_clients(env_file_path: str | None) -> None:
    sites = _list_running_client_sites()
    if not sites:
        return
    time.sleep(2)
    for site in sites:
        print(f"[INFO] Rebuilding client container for '{site}'...", flush=True)
        _run_client_command(site, env_file_path)


def _seed_default_clients_via_backend(attempts: int = 10, delay: float = 1.5) -> bool:
    """Trigger the backend's lazy DB-init so it seeds the default clients (LOCAL/DEV).

    The backend seeds site1/site2/site3 into nvflare_clients on its first DB-touching
    request; the launcher's status panel reads MySQL directly and never triggers it, so
    a fresh build shows no registered clients. Poking /user/role does trigger it.
    """
    try:
        from client_utils.create_client import ping_backend_login  # type: ignore
    except Exception:
        return False
    waited = False
    for i in range(1, max(1, attempts) + 1):
        try:
            ping_backend_login(quiet=True)  # quiet: this poller reports its own outcome
        except Exception:
            pass
        if _probe_mysql().get("clients"):
            return True
        if i < attempts:
            if not waited:
                print("[INFO] waiting for backend to come up...", flush=True)
                waited = True
            time.sleep(delay)
    return bool(_probe_mysql().get("clients"))


def _container_statuses(project_name: str) -> dict[str, str]:
    try:
        out = subprocess.check_output(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
                "--format",
                "{{.Label \"com.docker.compose.service\"}}|{{.Status}}",
            ],
            text=True,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return {}
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            service, status = line.split("|", 1)
        else:
            parts = line.split(None, 1)
            service = parts[0]
            status = parts[1] if len(parts) > 1 else ""
        service = service.strip()
        if not service:
            continue
        mapping[service] = status.strip()
    return mapping


def _docker_status_error() -> str:
    try:
        subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.PIPE,
        )
        return ""
    except subprocess.CalledProcessError as e:
        msg = ((e.stderr or "") + "\n" + (e.output or "")).strip()
    except Exception as e:
        msg = str(e)

    lowered = msg.lower()
    if "permission denied while trying to connect to the docker daemon socket" in lowered:
        return "Permission denied accessing Docker daemon socket (/var/run/docker.sock)"
    if "cannot connect to the docker daemon" in lowered:
        return "Cannot connect to Docker daemon"
    return msg.splitlines()[0] if msg else ""


def _require_docker_access(operation: str = "this action") -> bool:
    docker_error = _docker_status_error()
    if not docker_error:
        return True
    print(f"[ERROR] Cannot run {operation}: {docker_error}", flush=True)
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("[INFO] Rerun the Linux launcher with sudo on this machine if Docker requires elevated access.", flush=True)
    return False


def _probe_mysql() -> dict:
    host = os.environ.get("DUALITY_MYSQL_HOST", "localhost") or "localhost"
    port_str = os.environ.get("DUALITY_MYSQL_PORT", "3306")
    user = os.environ.get("DUALITY_MYSQL_USER", "")
    db = os.environ.get("DUALITY_MYSQL_DB", "")
    pwd = os.environ.get("DUALITY_MYSQL_PASSWORD", "")
    info: dict[str, object] = {
        "host": host,
        "port": port_str,
        "user": user,
        "db": db,
        "ok": False,
        "driver": "",
        "error": "",
        "clients": [],
    }
    try:
        port = int(port_str)
    except Exception:
        port = 3306
    conn = None
    driver = ""
    try:
        mysql_mod, driver = ensure_mysql_driver()
        if mysql_mod is None or driver is None:
            raise RuntimeError("No MySQL driver available")
        if driver == "mysql.connector":
            conn = mysql_mod.connect(
                host=host,
                port=port,
                user=user,
                password=pwd,
                database=db or None,
                connection_timeout=3,
            )
        else:
            conn = mysql_mod.connect(
                host=host,
                port=port,
                user=user,
                password=pwd,
                database=db or None,
                connect_timeout=3,
            )
        info["driver"] = driver
        info["ok"] = True
        clients: list[str] = []
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT client_name FROM nvflare_clients ORDER BY client_name")
                rows = cur.fetchall()
                for row in rows:
                    if isinstance(row, (list, tuple)) and row and row[0]:
                        clients.append(str(row[0]))
            except Exception:
                clients = []
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
        except Exception:
            clients = []
        info["clients"] = clients
    except Exception as e:
        info["error"] = str(e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return info


def _nvflare_status() -> dict:
    workspace = os.environ.get("DUALITY_NVFLARE_WORKSPACE", "nvflare_workspace")
    workspace_abs = os.path.abspath(workspace)
    root = os.path.join(workspace_abs, "duality_nvflare", "prod_00")
    # Non-empty, not just present: a Docker bind-mount auto-creates an empty root-owned prod_00 when
    # the nvflare container starts, which would otherwise read as PROVISIONED and skip provisioning.
    provisioned = os.path.isdir(root) and any(os.scandir(root))
    return {
        "workspace": workspace_abs,
        "root": root,
        "provisioned": provisioned,
    }


def _format_client_list(values: list[str]) -> str:
    if not values:
        return "NO RUNNING CLIENT CONTAINERS"
    return ", ".join(sorted(values))


def _gather_status(builder: ContainerBuilder) -> dict:
    project_name = getattr(builder, "project_name", "duality")
    containers = _container_statuses(project_name)
    container_status = {
        "mysql": containers.get("mysql", ""),
        "backend": containers.get("backend", ""),
        "frontend": containers.get("frontend", ""),
        "nvflare": containers.get("nvflare", ""),
    }
    client_containers = _list_running_client_sites()
    mode = (os.getenv("DUALITY_DB_MODE") or "container").strip().lower()
    if mode == "container" and not container_status["mysql"]:
        mysql_info = {
            "host": os.environ.get("DUALITY_MYSQL_HOST", "localhost") or "localhost",
            "port": os.environ.get("DUALITY_MYSQL_PORT", "3306"),
            "user": os.environ.get("DUALITY_MYSQL_USER", ""),
            "db": os.environ.get("DUALITY_MYSQL_DB", ""),
            "ok": False,
            "driver": "",
            "error": "MySQL container not running (DUALITY_DB_MODE=container)",
            "clients": [],
        }
    else:
        mysql_info = _probe_mysql()
    nvf_info = _nvflare_status()
    return {
        "project_name": project_name,
        "docker_error": _docker_status_error(),
        "containers": container_status,
        "client_containers": client_containers,
        "mysql": mysql_info,
        "nvflare": nvf_info,
    }


def _render_banner(status: dict) -> None:
    containers = status["containers"]
    mysql_info = status["mysql"]
    nvf_info = status["nvflare"]
    client_containers = status["client_containers"]
    print(SPLITTER)
    print(" Duality Standalone Status")
    print(SPLITTER)
    print(f"Project: {status['project_name']}")
    docker_error = status.get("docker_error") or ""
    if docker_error:
        print(f"Docker : FAILED ({docker_error})")
    print()
    print("Containers")
    print(f"  mysql    : {containers.get('mysql') or '-'}")
    print(f"  backend  : {containers.get('backend') or '-'}")
    print(f"  frontend : {containers.get('frontend') or '-'}")
    print(f"  nvflare  : {containers.get('nvflare') or '-'}")
    print(f"  clients  : {_format_client_list(client_containers)}")
    print()
    print("MySQL")
    print(f"  host     : {mysql_info.get('host')}")
    print(f"  port     : {mysql_info.get('port')}")
    print(f"  user     : {mysql_info.get('user')}")
    print(f"  db       : {mysql_info.get('db')}")
    ok_flag = mysql_info.get("ok")
    if ok_flag:
        print(f"  status   : OK ({mysql_info.get('driver')})")
    else:
        err = mysql_info.get("error") or ""
        if err:
            print(f"  status   : FAILED ({err})")
        else:
            print("  status   : FAILED")
    clients_db = mysql_info.get("clients") or []
    if not clients_db:
        clients_db_display = "NO CLIENTS REGISTERED IN MYSQL TABLE"
    else:
        clients_db_display = ", ".join(sorted([str(x) for x in clients_db]))
    print(f"  clients  : {clients_db_display}")
    print()
    print("NVFLARE")
    print(f"  workspace: {nvf_info.get('workspace')}")
    print(f"  root     : {nvf_info.get('root')}")
    print(f"  status   : {'PROVISIONED' if nvf_info.get('provisioned') else 'NOT PROVISIONED'}")
    print(SPLITTER)


def _compute_main_action_label(status: dict) -> str:
    nvf_info = status["nvflare"]
    provisioned = bool(nvf_info.get("provisioned"))
    if not provisioned:
        return "Provision workspace & build all"
    if _project_containers_exist():
        return "Reset & rebuild all"
    return "Build all"


def _render_menu(status: dict) -> None:
    main_label = _compute_main_action_label(status)
    print(f"[1] {main_label}")
    print("[2] Rebuild backend")
    print("[3] Rebuild frontend")
    print("[4] Rebuild nvflare")
    print("[5] Rebuild mysql")
    print("[6] Create/Rebuild USER SPECIFIED client container (includes persist to MySQL)")
    print("[7] Persist USER SPECIFIED client to MySQL")
    print("[8] Rebuild ALREADY RUNNING client containers")
    print("[9] Build Wheel & Redeploy ALREADY RUNNING NVFlare Server/Client")
    print("[r] Refresh")
    print("[q] Quit")
    print(SPLITTER)


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _run_full_pipeline(args, env_file_path: str | None, wipe_mysql: bool = False) -> int:
    if not _require_docker_access("full pipeline"):
        return 2
    existing = _project_containers_exist()
    rc = cmd_mysql(args)
    if rc != 0:
        return rc
    rc = cmd_codebase(args)
    if rc != 0:
        return rc
    if existing:
        builder = _builder_from_args(args)
        if builder is None:
            return 2
        services = ["mysql", "backend", "frontend", "nvflare"]
        rc = builder.rebuild(services=services, no_cache=False, wipe_mysql=wipe_mysql)
        if rc != 0:
            return rc
        _redeploy_running_clients(env_file_path)
        return 0
    docker_args = argparse.Namespace(
        action="run",
        services=None,
        no_cache=False,
        no_build=False,
        attach=False,
        volumes=False,
        follow=False,
        env_file=env_file_path,
    )
    rc = cmd_docker(docker_args)
    return rc


def _run_local_wheel_builder(backend_repo_dir: Path, version: str | None = None) -> Path | None:
    nvflare_jobs_dir = backend_repo_dir / "app" / "core" / "job_runner" / "nvflare_jobs"
    wheels_dir = nvflare_jobs_dir / "wheels"
    script_path = wheels_dir / "APIWheelBuilderCI.py"

    if not wheels_dir.exists():
        print(f"[ERROR] Wheels directory not found at: {wheels_dir}", flush=True)
        return None
    if not script_path.exists():
        print(f"[ERROR] APIWheelBuilderCI.py not found at: {script_path}", flush=True)
        return None

    exe = sys.executable or "python"
    cmd = [
        exe,
        str(script_path),
        "--root",
        str(nvflare_jobs_dir),
        "--out-dir",
        str(wheels_dir),
    ]

    explicit_version = (version or os.getenv("DUALITY_LOCAL_WHEEL_VERSION") or "").strip()
    if explicit_version:
        cmd += ["--version", explicit_version]
        print(f"[INFO] Building local duality_nvflare_lib wheel version {explicit_version}", flush=True)
    else:
        print("[INFO] Building local duality_nvflare_lib wheel", flush=True)
    print("$ " + " ".join(cmd), flush=True)

    try:
        subprocess.run(cmd, check=True, cwd=str(wheels_dir))
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Local wheel build failed with status {e.returncode}", flush=True)
        return None
    except Exception as e:
        print(f"[ERROR] Failed running APIWheelBuilderCI.py: {e}", flush=True)
        return None

    wheels = sorted(
        wheels_dir.glob("duality_nvflare_lib-*.whl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not wheels:
        print(f"[ERROR] No local wheel produced in {wheels_dir}", flush=True)
        return None

    wheel_path = wheels[-1].resolve()
    print(f"[INFO] Local wheel ready: {wheel_path}", flush=True)
    return wheel_path


def cmd_wheel(args) -> int:
    builder = _builder_from_args(args)
    if builder is None:
        return 2

    env_file_path = _resolve_env_file(args.env_file)
    if env_file_path:
        load_env_file(env_file_path)

    project_name = getattr(builder, "project_name", "duality")
    statuses = _container_statuses(project_name)

    if not statuses.get("nvflare"):
        print("[ERROR] NVFLARE container is not running. Start NVFLARE and at least one client container, then retry.", flush=True)
        return 2

    sites = _list_running_client_sites()
    if not sites:
        print("[ERROR] No running client containers found. Start at least one client container, then retry.", flush=True)
        return 2

    backend_repo_dir = REPO_ROOT.parent / "backend"
    if not backend_repo_dir.exists():
        print(f"[WARN] Backend source not found at: {backend_repo_dir}. Running codebase check...", flush=True)
        rc = codebase_run("backend") or 0
        if rc != 0:
            return rc
        if not backend_repo_dir.exists():
            print(f"[ERROR] Backend source not found at: {backend_repo_dir}", flush=True)
            return 2

    wheel_path = _run_local_wheel_builder(backend_repo_dir, getattr(args, "wheel_version", None))
    if wheel_path is None:
        return 2

    previous_wheel_path = os.environ.get("DUALITY_LOCAL_WHEEL_PATH")
    os.environ["DUALITY_LOCAL_WHEEL_PATH"] = str(wheel_path)
    # Pin the nvflare server + redeployed clients to the freshly built local wheel.
    # The public job runtime (duality_wheel_runtime.py) never installs from a package
    # index, so this only makes the intent explicit; it is inherited by the docker
    # compose subprocesses (and create_client) for ${DUALITY_NVFLARE_LIB_UPDATE_DISABLED}.
    previous_update_disabled = os.environ.get("DUALITY_NVFLARE_LIB_UPDATE_DISABLED")
    os.environ["DUALITY_NVFLARE_LIB_UPDATE_DISABLED"] = "1"
    try:
        rc = builder.rebuild(
            services=["nvflare"],
            no_cache=getattr(args, "no_cache", False),
            local_wheel_path=str(wheel_path),
        )
        if rc != 0:
            return rc

        _redeploy_running_clients(env_file_path)
        return 0
    finally:
        if previous_wheel_path is None:
            os.environ.pop("DUALITY_LOCAL_WHEEL_PATH", None)
        else:
            os.environ["DUALITY_LOCAL_WHEEL_PATH"] = previous_wheel_path
        if previous_update_disabled is None:
            os.environ.pop("DUALITY_NVFLARE_LIB_UPDATE_DISABLED", None)
        else:
            os.environ["DUALITY_NVFLARE_LIB_UPDATE_DISABLED"] = previous_update_disabled


def cmd_ui(args) -> int:
    builder = _builder_from_args(args)
    if builder is None:
        input("Press Enter to exit...")
        return 2
    env_file_path = _resolve_env_file(getattr(args, "env_file", None))
    while True:
        _clear_screen()
        status = _gather_status(builder)
        _render_banner(status)
        _render_menu(status)
        choice = input("> ").strip().lower()
        if choice in ("q", "quit", "x"):
            return 0
        if choice in ("r", ""):
            continue
        if choice == "1":
            existing = _project_containers_exist()
            wipe = False
            if existing:
                print()
                print(SPLITTER)
                print("ATTENTION")
                print()
                print("If backend is running during mysql reset, please rebuild backend next to re-establish proper connection.")
                print(SPLITTER)
                print("", flush=True)
                ans = input(
                    "NOTE: data wipe requires re-adding clients\n\rWipe MySQL data volume before reset & rebuild all? [y/N] "
                ).strip().lower()
                wipe = ans in ("y", "yes")
            rc = _run_full_pipeline(args, env_file_path, wipe_mysql=wipe)
            if rc == 0:
                print("[INFO] Seeding default clients in MySQL (poking backend)...", flush=True)
                if _seed_default_clients_via_backend():
                    reg = _probe_mysql().get("clients") or []
                    print(f"[INFO] Registered clients: {', '.join(reg) if reg else '(none)'}", flush=True)
                else:
                    print(
                        "[WARN] Backend not reachable yet; default clients not seeded. "
                        "They will register once the backend serves its first request (e.g. option 6).",
                        flush=True,
                    )
            input(f"Full pipeline completed with status {rc}. Press Enter to continue...")
        elif choice == "2":
            if _require_docker_access("backend rebuild"):
                builder.rebuild(["backend"])
            input("Backend rebuild complete. Press Enter to continue...")
        elif choice == "3":
            if _require_docker_access("frontend rebuild"):
                builder.rebuild(["frontend"])
            input("Frontend rebuild complete. Press Enter to continue...")
        elif choice == "4":
            if _require_docker_access("nvflare rebuild"):
                builder.rebuild(["nvflare"])
            input("NVFLARE rebuild complete. Press Enter to continue...")
        elif choice == "5":
            print()
            print(SPLITTER)
            print("ATTENTION")
            print()
            print("If backend is running during mysql reset, please rebuild backend next to re-establish proper connection.")
            print(SPLITTER)
            print("", flush=True)
            ans = input(
                "NOTE: data wipe requires re-adding clients\n\rWipe MySQL data volume before rebuild? [y/N] "
            ).strip().lower()
            wipe = ans in ("y", "yes")
            if _require_docker_access("mysql rebuild"):
                builder.rebuild(["mysql"], wipe_mysql=wipe)
            input("MySQL rebuild complete. Press Enter to continue...")
        elif choice == "6":
            site = input("Enter site name (e.g., site1), or press Enter to launch all registered clients: ").strip()
            if site:
                rc = 2
                if _require_docker_access("client rebuild"):
                    rc = _run_client_command(site, env_file_path)
                input(f"Client create/rebuild completed with status {rc}. Press Enter to continue...")
            else:
                # Empty input -> launch every client registered in MySQL.
                _seed_default_clients_via_backend()
                registered = _probe_mysql().get("clients") or []
                if not registered:
                    input("No clients registered in MySQL (is the backend up? run option 1 first). Press Enter to continue...")
                elif _require_docker_access("client rebuild"):
                    for s in registered:
                        print(f"[INFO] Launching client container for '{s}'...", flush=True)
                        _run_client_command(s, env_file_path)
                    input(
                        f"Launched {len(registered)} registered client(s): "
                        f"{', '.join(registered)}. Press Enter to continue..."
                    )
                else:
                    input("Press Enter to continue...")
        elif choice == "7":
            site = input("Enter site name (e.g., site1): ").strip()
            if site:
                rc = _run_clientdb_command(site, env_file_path)
                input(f"Client persist completed with status {rc}. Press Enter to continue...")
        elif choice == "8":
            sites = _list_running_client_sites()
            if not sites:
                input("No running client containers found. Press Enter to continue...")
            else:
                if _require_docker_access("client rebuild"):
                    for s in sites:
                        _run_client_command(s, env_file_path)
                input("Running client containers rebuilt. Press Enter to continue...")
        elif choice == "9":
            rc = 2
            if _require_docker_access("wheel build and nvflare redeploy"):
                rc = cmd_wheel(argparse.Namespace(env_file=env_file_path, no_cache=False, wheel_version=None))
            input(f"Wheel + NVFLARE server/client redeploy completed with status {rc}. Press Enter to continue...")
        else:
            input("Unknown option. Press Enter to continue...")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "client":
        _ensure_env_local_seed()
        try:
            from client_utils import create_client
        except Exception:
            print("[ERROR] client_utils.create_client not available.", flush=True)
            sys.exit(2)

        old_argv = sys.argv[:]
        try:
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            create_client.main()
        finally:
            sys.argv = old_argv
        return

    parser = argparse.ArgumentParser(
        prog="standalone",
        description="Duality local standalone setup and orchestrator",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_code = sub.add_parser(
        "codebase",
        help="Verify local backend and frontend source directories",
    )
    p_code.add_argument(
        "only",
        nargs="?",
        choices=["backend", "frontend", "all"],
        default="all",
    )
    p_code.set_defaults(func=cmd_codebase)

    p_mysql = sub.add_parser(
        "mysql",
        help="Check and optionally install local MySQL (skipped if DUALITY_DB_MODE=container)",
    )
    p_mysql.set_defaults(func=cmd_mysql)

    p_nv = sub.add_parser(
        "nvflare",
        help="Install NVFLARE if needed and provision a local workspace",
    )
    p_nv.set_defaults(func=cmd_nvflare)

    p_rebuild = sub.add_parser(
        "rebuild",
        help="Rebuild and restart selected services from local source",
    )
    p_rebuild.add_argument(
        "services",
        nargs="+",
        choices=["frontend", "backend", "nvflare", "mysql"],
        help="Services to rebuild. Typically frontend or backend. nvflare/mysql are supported too.",
    )
    p_rebuild.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable build cache",
    )
    p_rebuild.set_defaults(func=cmd_rebuild)

    p_update = sub.add_parser(
        "update",
        help="git pull local service repos, rebuild, and restart targeted services",
    )
    p_update.add_argument(
        "services",
        nargs="+",
        choices=["frontend", "backend"],
        help="Services to update. Choose from frontend or backend",
    )
    p_update.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable build cache",
    )
    p_update.set_defaults(func=cmd_update)

    p_wheel = sub.add_parser(
        "wheel",
        help="Build Wheel & Redeploy NVFlare Server/Client",
    )
    p_wheel.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable build cache for NVFLARE redeploy",
    )
    p_wheel.add_argument(
        "--wheel-version",
        default=None,
        help="Optional local duality_nvflare_lib version to build",
    )
    p_wheel.set_defaults(func=cmd_wheel)

    p_cdb = sub.add_parser(
        "clientdb",
        help="Persist a NVFLARE client entry in MySQL for broadcasted jobs",
    )
    p_cdb.add_argument(
        "--site",
        required=True,
        type=str,
        help="Site name to register (e.g., site1, site2, or a custom site identifier)",
    )
    p_cdb.set_defaults(func=cmd_clientdb)

    p_client = sub.add_parser(
        "client",
        help="Create or rebuild a NVFLARE client container",
    )
    client_group = p_client.add_mutually_exclusive_group(required=True)
    client_group.add_argument(
        "--site",
        help="Site name (e.g., site1, site2) when building/running or --tar-kit.",
        type=str,
    )
    client_group.add_argument(
        "--tar-file",
        type=str,
        help="Path to an existing client_<site>_startup_kit.tar",
    )
    p_client.add_argument(
        "--tar-kit",
        action="store_true",
        help="Only create the client startup kit tar and exit",
    )
    p_client.add_argument(
        "--compose-file",
        default=str(REPO_ROOT / "client_utils" / "docker-compose.client-template.yml"),
        help="Compose template path",
    )
    p_client.add_argument(
        "--project",
        default="duality-client",
        help="Compose project name to group client build/run resources",
    )
    p_client.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable build cache so the client image is rebuilt from scratch",
    )
    p_client.set_defaults(func=cmd_client)

    p_ui = sub.add_parser(
        "ui",
        help="Interactive Duality status dashboard and rebuild menu",
    )
    p_ui.set_defaults(func=cmd_ui)

    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to env file. Defaults to .env.local in the repo root when not provided",
    )

    args = parser.parse_args()

    _ensure_env_local_seed()

    env_file_path = _resolve_env_file(args.env_file)
    if env_file_path:
        load_env_file(env_file_path)

    if hasattr(os, "getuid"):
        os.environ.setdefault("DUALITY_HOST_UID", str(os.getuid()))
        os.environ.setdefault("DUALITY_HOST_GID", str(os.getgid()))

    if not args.command:
        rc = _run_full_pipeline(args, env_file_path)
        sys.exit(rc)
    else:
        rc = args.func(args)
        sys.exit(rc)


if __name__ == "__main__":
    main()
