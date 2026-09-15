import argparse
import glob
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


APP_HOME = Path.home() / ".duality-client"
STATE_PATH = APP_HOME / "tool-ui-state.json"
ENV_SH_PATH = APP_HOME / "tool-ui-env.sh"
ENV_CMD_PATH = APP_HOME / "tool-ui-env.cmd"

DEFAULT_CONTAINER = "duality-client-agent"
TOKEN_FILENAME = ".duality_client_agent_token"
OQS_INSTALL_PATH = "/usr/local"
OQS_LIB_PATH = "/usr/local/lib"

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
LOCAL_RESULTS_API_DIR = PROJECT_ROOT / "local-results-api"
AGENT_MANAGE_SCRIPT = LOCAL_RESULTS_API_DIR / "agent_manage.py"


def detect_os_type() -> str:
    if sys.platform.startswith("linux"):
        return "ubuntu"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return sys.platform


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_state() -> dict:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    state = _read_json(STATE_PATH)
    if not isinstance(state, dict):
        return {}
    state.setdefault("workspaces", {})
    state.setdefault("startup_ran", {})
    return state


def _write_env_files(state: dict) -> None:
    last_site = (state.get("last_site") or "").strip()
    last_env = (state.get("last_env") or "").strip()
    workspaces = state.get("workspaces") or {}
    ws = ""
    if last_site and isinstance(workspaces, dict):
        ws = (workspaces.get(last_site) or "").strip()

    sh_lines = [
        'export DUALITY_CLIENT_SITE="{0}"'.format(last_site.replace('"', '\\"')),
        'export DUALITY_CLIENT_ENV="{0}"'.format(last_env.replace('"', '\\"')),
        'export DUALITY_CLIENT_WORKSPACE="{0}"'.format(ws.replace('"', '\\"')),
        "",
    ]
    ENV_SH_PATH.write_text("\n".join(sh_lines), encoding="utf-8")

    cmd_lines = [
        "@echo off",
        'set "DUALITY_CLIENT_SITE={0}"'.format(last_site.replace('"', "")),
        'set "DUALITY_CLIENT_ENV={0}"'.format(last_env.replace('"', "")),
        'set "DUALITY_CLIENT_WORKSPACE={0}"'.format(ws.replace('"', "")),
        "",
    ]
    ENV_CMD_PATH.write_text("\r\n".join(cmd_lines), encoding="utf-8")


def save_state(state: dict) -> None:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    _write_env_files(state)


def prompt(msg: str, default: str = "") -> str:
    v = input(msg).strip()
    return v if v else default


def _run_capture(cmd: list[str], env: dict | None = None) -> str:
    return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, env=env)


def run_cmd(cmd: list[str], env: dict | None = None, cwd: str | None = None) -> None:
    subprocess.check_call(cmd, env=env, cwd=cwd)


def _launch_detached_terminal(cmd: list[str], env: dict | None = None, cwd: str | None = None) -> bool:
    os_type = detect_os_type()

    if os_type == "windows":
        cmdline = subprocess.list2cmdline(cmd)
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "", "cmd.exe", "/k", cmdline],
                env=env,
                cwd=cwd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return True
        except Exception:
            return False

    if os_type == "mac":
        cmdline = " ".join(shlex.quote(x) for x in cmd)
        apple = f'''
tell application "Terminal"
  activate
  do script "cd {shlex.quote(cwd) if cwd else shlex.quote(os.getcwd())} && {cmdline}"
end tell
'''
        try:
            subprocess.Popen(["osascript", "-e", apple], env=env)
            return True
        except Exception:
            return False

    if os_type == "ubuntu":
        cmdline = " ".join(shlex.quote(x) for x in cmd)
        workdir = cwd or os.getcwd()
        bash_cmd = f'cd "{workdir}" && {cmdline}; exec bash'
        for tcmd in [
            ["gnome-terminal", "--", "bash", "-ic", bash_cmd],
            ["x-terminal-emulator", "-e", "bash", "-ic", bash_cmd],
            ["xterm", "-e", "bash", "-ic", bash_cmd],
        ]:
            try:
                subprocess.Popen(tcmd, env=env)
                return True
            except FileNotFoundError:
                continue
            except OSError:
                continue

    return False


def run_cmd_detached(cmd: list[str], env: dict | None = None, cwd: str | None = None, log_path: str | None = None) -> None:
    if _launch_detached_terminal(cmd, env=env, cwd=cwd):
        return

    stdout = None
    stderr = None
    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            f = open(log_path, "a", encoding="utf-8")
            stdout = f
            stderr = f
        except Exception:
            stdout = None
            stderr = None

    subprocess.Popen(cmd, env=env, cwd=cwd, stdout=stdout, stderr=stderr)


def pick_site(state: dict) -> str:
    last = (state.get("last_site") or "").strip()
    site = prompt(f"Site [{last}]: ", default=last).strip()
    if not site:
        raise RuntimeError("Site is required")
    state["last_site"] = site
    return site


def pick_env(state: dict) -> str:
    last = (state.get("last_env") or "aws").strip()
    envv = prompt(f"Env [{last}]: ", default=last).strip()
    if not envv:
        raise RuntimeError("Env is required")
    state["last_env"] = envv
    return envv


def _managed_workspace_for_site(site: str) -> Path:
    normalized = (site or "").strip()
    if not normalized:
        raise RuntimeError("Site is required")
    return (APP_HOME / normalized).expanduser().resolve()


def _discover_workspace_for_site(site: str) -> str:
    candidate = _managed_workspace_for_site(site)
    if (candidate / "startup" / "start.sh").exists():
        return str(candidate)
    return ""


def _get_default_workspace(state: dict, site: str) -> str:
    # The terminal supervisor uses the same persistent per-user workspace as
    # the desktop supervisor. Source-checkout and legacy saved paths are not
    # considered.
    _ = state
    return str(_managed_workspace_for_site(site))


def get_workspace(state: dict, site: str, prompt_if_missing: bool = True) -> str:
    # ``prompt_if_missing`` is retained for caller compatibility. Workspace
    # selection is no longer interactive: each site is fixed to
    # ~/.duality-client/<site>.
    _ = prompt_if_missing
    ws = _get_default_workspace(state, site)
    workspaces = state.get("workspaces") or {}
    if not isinstance(workspaces, dict):
        workspaces = {}
    workspaces[site] = ws
    state["workspaces"] = workspaces
    return ws


def _docker_base_cmd() -> list[str] | None:
    try:
        _run_capture(["docker", "version"])
        return ["docker"]
    except Exception:
        pass

    try:
        _run_capture(["sudo", "-n", "docker", "version"])
        return ["sudo", "-n", "docker"]
    except Exception:
        return None


def docker_available() -> bool:
    return _docker_base_cmd() is not None


def container_running(container_name: str) -> bool | None:
    base = _docker_base_cmd()
    if not base:
        return None
    try:
        out = _run_capture(
            base
            + [
                "ps",
                "--filter",
                f"name=^{container_name}$",
                "--filter",
                "status=running",
                "--format",
                "{{.Names}}",
            ]
        )
        return container_name in out.splitlines()
    except Exception:
        return None


def startup_ran(state: dict, site: str) -> bool:
    m = state.get("startup_ran") or {}
    if not isinstance(m, dict):
        return False
    return bool(m.get(site))


def mark_startup_ran(state: dict, site: str) -> None:
    m = state.get("startup_ran") or {}
    if not isinstance(m, dict):
        m = {}
    m[site] = True
    state["startup_ran"] = m


def liboqs_installed() -> bool:
    for pattern in [
        "/usr/local/lib/liboqs.so",
        "/usr/local/lib/liboqs.so.*",
        "/usr/lib/liboqs.so",
        "/usr/lib/liboqs.so.*",
    ]:
        if glob.glob(pattern):
            return True
    return False


def build_subprocess_env(state: dict, site: str) -> dict:
    env = dict(os.environ)
    ws = get_workspace(state, site, prompt_if_missing=False)
    if ws:
        env["DUALITY_CLIENT_WORKSPACE"] = ws
        env["DUALITY_NVFLARE_WORKSPACE"] = ws
        job_results = str((Path(ws) / "job-results").resolve())
        Path(job_results).mkdir(parents=True, exist_ok=True)
        env["DUALITY_NVFLARE_JOB_SAVE_LOCATION"] = job_results
    last_env = (state.get("last_env") or "").strip()
    if last_env:
        env["DUALITY_CLIENT_ENV"] = last_env
    if site:
        env["DUALITY_CLIENT_SITE"] = site
    if detect_os_type() == "ubuntu":
        env["OQS_INSTALL_PATH"] = OQS_INSTALL_PATH
        current_ld = (env.get("LD_LIBRARY_PATH") or "").strip()
        ld_parts = [p for p in current_ld.split(":") if p]
        if OQS_LIB_PATH not in ld_parts:
            ld_parts.insert(0, OQS_LIB_PATH)
        env["LD_LIBRARY_PATH"] = ":".join(ld_parts) if ld_parts else OQS_LIB_PATH
    return env


def print_overview(state: dict, os_type: str, break_system_packages: bool) -> None:
    site = (state.get("last_site") or "").strip()
    envv = (state.get("last_env") or "").strip()
    ws = ""
    if site:
        ws = get_workspace(state, site, prompt_if_missing=False)

    d_avail = docker_available()
    c_run = container_running(DEFAULT_CONTAINER) if d_avail else None

    print("Overview")
    print(f"OS: {os_type}")
    print(f"Last site: {site or '-'}")
    print(f"Last env: {envv or '-'}")
    print(f"Workspace: {ws or '-'}")
    print(f"Break system packages: {'yes' if break_system_packages else 'no'}")
    if os_type == "ubuntu":
        print(f"liboqs installed: {'yes' if liboqs_installed() else 'no'}")
    else:
        print("liboqs installed: -")
    if site:
        print(f"Startup kit ran: {'yes' if startup_ran(state, site) else 'no'}")
    else:
        print("Startup kit ran: -")
    print(f"Docker available: {'yes' if d_avail else 'no'}")
    if c_run is None:
        print("Container running: -")
    else:
        print(f"Container running: {'yes' if c_run else 'no'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bsp", action="store_true")
    args = parser.parse_args()

    state = load_state()
    os_type = detect_os_type()
    break_system_packages = bool(args.bsp)

    while True:
        print()
        print_overview(state, os_type, break_system_packages)
        print()
        print("SHARE Client Terminal Supervisor")
        print("1) Download/install startup kit + start NVFlare + build Results API")
        print("2) Start NVFlare client kit (start.sh)")
        print("3) Stop NVFlare client kit (stop_fl.sh)")
        print("4) Rebuild Results API (build + redeploy container)")
        print("5) Start/restart Results API")
        print("6) Stop Results API")
        print("7) Show Results API token for a workspace")
        print("8) Install liboqs")
        print("9) Sync configured datasource files for site")
        print("10) Exit")
        choice = prompt("> ").strip()

        if choice == "10":
            save_state(state)
            return

        try:
            if choice == "1":
                site = pick_site(state)
                envv = pick_env(state)
                installdeps = prompt("Install OS deps? [y/N]: ", default="n").lower().startswith("y")

                cmd = [
                    sys.executable,
                    str(MAIN_SCRIPT),
                    "client",
                    "--site",
                    site,
                    "--env",
                    envv,
                    "--os",
                    os_type,
                    "--install-base",
                    str(APP_HOME),
                ]
                if installdeps:
                    cmd += ["--installdeps"]
                if break_system_packages:
                    cmd += ["--breaksystempackages"]

                run_cmd(cmd, env=build_subprocess_env(state, site), cwd=str(PROJECT_ROOT))
                mark_startup_ran(state, site)
                ws = get_workspace(state, site, prompt_if_missing=False)
                if ws:
                    workspaces = state.get("workspaces") or {}
                    if not isinstance(workspaces, dict):
                        workspaces = {}
                    workspaces[site] = ws
                    state["workspaces"] = workspaces
                save_state(state)
                continue

            if choice == "2":
                site = pick_site(state)
                ws = get_workspace(state, site, prompt_if_missing=True)
                start_sh = str(Path(ws) / "startup" / "start.sh")
                if not os.path.exists(start_sh):
                    raise RuntimeError(f"start.sh not found: {start_sh}")
                run_cmd_detached(
                    ["bash", start_sh],
                    env=build_subprocess_env(state, site),
                    cwd=str(Path(ws) / "startup"),
                    log_path=str(Path(ws) / "startup" / "start_sh.log"),
                )
                save_state(state)
                continue

            if choice == "3":
                site = pick_site(state)
                ws = get_workspace(state, site, prompt_if_missing=True)
                stop_script = Path(ws) / "startup" / "stop_fl.sh"
                if not stop_script.exists():
                    raise RuntimeError(f"stop_fl.sh not found: {stop_script}")
                run_cmd(
                    ["bash", "./stop_fl.sh"],
                    env=build_subprocess_env(state, site),
                    cwd=str(stop_script.parent),
                )
                save_state(state)
                continue

            if choice == "4":
                site = pick_site(state)
                ws = get_workspace(state, site, prompt_if_missing=True)
                cmd = [sys.executable, str(AGENT_MANAGE_SCRIPT), "build_deploy", "--workspace", ws, "--job_save_location", "/nvflare/job-results"]
                if os_type == "ubuntu" and not docker_available():
                    cmd += ["--installdocker"]
                run_cmd_detached(
                    cmd,
                    env=build_subprocess_env(state, site),
                    cwd=str(PROJECT_ROOT),
                    log_path=str(Path(ws) / "startup" / "agent_build_deploy.log"),
                )
                save_state(state)
                continue

            if choice == "5":
                site = pick_site(state)
                ws = get_workspace(state, site, prompt_if_missing=True)
                cmd = [sys.executable, str(AGENT_MANAGE_SCRIPT), "start", "--workspace", ws, "--job_save_location", "/nvflare/job-results"]
                if os_type == "ubuntu" and not docker_available():
                    cmd += ["--installdocker"]
                run_cmd_detached(
                    cmd,
                    env=build_subprocess_env(state, site),
                    cwd=str(PROJECT_ROOT),
                    log_path=str(Path(ws) / "startup" / "agent_start.log"),
                )
                save_state(state)
                continue

            if choice == "6":
                cmd = [sys.executable, str(AGENT_MANAGE_SCRIPT), "stop"]
                if os_type == "ubuntu" and not docker_available():
                    cmd += ["--installdocker"]
                run_cmd(cmd, env=os.environ.copy(), cwd=str(PROJECT_ROOT))
                save_state(state)
                continue

            if choice == "7":
                site = pick_site(state)
                ws = get_workspace(state, site, prompt_if_missing=True)
                token_path = Path(ws) / TOKEN_FILENAME
                if not token_path.exists():
                    print("Token file not found")
                else:
                    print(token_path.read_text(encoding="utf-8").strip())
                save_state(state)
                continue

            if choice == "8":
                if os_type != "ubuntu":
                    raise RuntimeError("liboqs installation is only supported on ubuntu")
                force_reinstall = prompt("Force reinstall liboqs? [y/N]: ", default="n").lower().startswith("y")
                cmd = [sys.executable, str(MAIN_SCRIPT), "install_liboqs", "--os", os_type]
                if force_reinstall:
                    cmd += ["--force_reinstall"]
                run_cmd(cmd, env=os.environ.copy(), cwd=str(PROJECT_ROOT))
                save_state(state)
                continue

            if choice == "9":
                site = pick_site(state)
                cmd_update = [sys.executable, str(MAIN_SCRIPT), "update_data", "--site", site, "--overwrite"]
                run_cmd(cmd_update, env=build_subprocess_env(state, site), cwd=str(PROJECT_ROOT))
                save_state(state)
                continue

            print("Unknown choice")

        except Exception as e:
            print(f"Error: {e}")
            save_state(state)


if __name__ == "__main__":
    main()