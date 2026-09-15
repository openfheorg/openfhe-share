import argparse
import configparser
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from startup_kit_delivery import (
    APP_HOME,
    download_startup_kit,
    install_startup_kit,
    validate_site_name,
)


PROJECT_ROOT = Path(__file__).resolve().parent
MONOREPO_ROOT = PROJECT_ROOT.parent
LOCAL_RESULTS_API_DIR = PROJECT_ROOT / "local-results-api"
STANDALONE_ROOT = MONOREPO_ROOT / "standalone"
STANDALONE_DATA_DIR = STANDALONE_ROOT / "nvflare_stage" / "data"
STANDALONE_ENV_PATH = STANDALONE_ROOT / ".env.local"

UBUNTU_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
OQS_INSTALL_PATH = "/usr/local"
OQS_LIB_PATH = "/usr/local/lib"


def _with_dist_packages_pythonpath(env=None):
    env_map = dict(env or os.environ)
    current_pythonpath = (env_map.get("PYTHONPATH") or "").strip()
    pythonpath_parts = [p for p in current_pythonpath.split(":") if p]
    if UBUNTU_DIST_PACKAGES not in pythonpath_parts:
        pythonpath_parts.insert(0, UBUNTU_DIST_PACKAGES)
    env_map["PYTHONPATH"] = ":".join(pythonpath_parts) if pythonpath_parts else UBUNTU_DIST_PACKAGES
    return env_map


def _expand_abs_path(path_value):
    return os.path.abspath(os.path.expanduser(path_value))


def _normalize_real_path(path_value):
    return os.path.realpath(_expand_abs_path(path_value))


def _resolve_venv_root(venv_value):
    if not venv_value:
        return None

    candidate = _expand_abs_path(venv_value)

    if os.path.isfile(candidate):
        basename = os.path.basename(candidate).lower()
        if basename in {"python", "python3", "python.exe"}:
            return os.path.dirname(os.path.dirname(candidate))
        raise RuntimeError(f"--venv must point to a virtual environment directory or python executable: {venv_value}")

    return candidate


def _get_venv_bin_dir(venv_root):
    if os.name == "nt":
        return os.path.join(venv_root, "Scripts")
    return os.path.join(venv_root, "bin")


def _get_venv_python(venv_root):
    bin_dir = _get_venv_bin_dir(venv_root)

    if os.name == "nt":
        candidates = [
            os.path.join(bin_dir, "python.exe"),
            os.path.join(bin_dir, "python"),
        ]
    else:
        candidates = [
            os.path.join(bin_dir, "python3"),
            os.path.join(bin_dir, "python"),
        ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return _normalize_real_path(candidate)

    raise RuntimeError(f"Could not find a python executable in virtual environment: {venv_root}")


def _apply_venv_to_env(env_map, venv_root):
    resolved_root = _resolve_venv_root(venv_root)
    if not resolved_root:
        return env_map

    bin_dir = _get_venv_bin_dir(resolved_root)
    current_path = (env_map.get("PATH") or "").strip()
    path_parts = [p for p in current_path.split(os.pathsep) if p]

    if bin_dir not in path_parts:
        path_parts.insert(0, bin_dir)

    env_map["VIRTUAL_ENV"] = resolved_root
    env_map["PATH"] = os.pathsep.join(path_parts) if path_parts else bin_dir
    return env_map


def _ensure_expected_venv(venv_value):
    resolved_root = _resolve_venv_root(venv_value)
    if not resolved_root:
        return None

    if not os.path.isdir(resolved_root):
        raise RuntimeError(f"Virtual environment directory not found: {resolved_root}")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RuntimeError(
            "Do not run the full script with sudo when using --venv. "
            "Run it as your normal user and let the script sudo apt-get steps as needed."
        )

    expected_python = _get_venv_python(resolved_root)
    current_python = _normalize_real_path(sys.executable)

    if current_python != expected_python:
        script_path = _expand_abs_path(sys.argv[0])
        new_env = _apply_venv_to_env(dict(os.environ), resolved_root)
        os.execve(expected_python, [expected_python, script_path, *sys.argv[1:]], new_env)

    _apply_venv_to_env(os.environ, resolved_root)
    return resolved_root


def run(cmd, sudo=False, env=None):
    exec_env = _with_dist_packages_pythonpath(env)
    if sudo and hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "env", f'PYTHONPATH={exec_env["PYTHONPATH"]}'] + cmd
    subprocess.check_call(cmd, env=exec_env)


def run_capture(cmd, env=None):
    exec_env = _with_dist_packages_pythonpath(env)
    return subprocess.check_output(cmd, text=True, env=exec_env)


def install_ubuntu_dependencies():
    run(["apt-get", "update"], sudo=True)
    run(["apt-get", "install", "-y", "python3", "python3-pip", "python3-venv"], sudo=True)


def _has_liboqs_shared_library():
    for pattern in [
        "/usr/local/lib/liboqs.so",
        "/usr/local/lib/liboqs.so.*",
        "/usr/lib/liboqs.so",
        "/usr/lib/liboqs.so.*",
    ]:
        if glob.glob(pattern):
            return True
    return False


def install_liboqs_ubuntu(force_reinstall=False):
    if _has_liboqs_shared_library() and not force_reinstall:
        return

    run(["apt-get", "update"], sudo=True)
    run(
        [
            "apt-get",
            "install",
            "-y",
            "git",
            "cmake",
            "ninja-build",
            "build-essential",
            "libssl-dev",
            "ca-certificates",
            "libgomp1",
        ],
        sudo=True,
    )

    build_root = f"/tmp/liboqs-build-{int(time.time())}"
    src_dir = os.path.join(build_root, "liboqs")
    build_dir = os.path.join(src_dir, "build")

    if os.path.exists(build_root):
        shutil.rmtree(build_root, ignore_errors=True)
    os.makedirs(build_root, exist_ok=True)

    try:
        run(["git", "clone", "--depth=1", "https://github.com/open-quantum-safe/liboqs", src_dir])
        run(
            [
                "cmake",
                "-S",
                src_dir,
                "-B",
                build_dir,
                "-GNinja",
                "-DBUILD_SHARED_LIBS=ON",
                f"-DCMAKE_INSTALL_PREFIX={OQS_INSTALL_PATH}",
            ]
        )
        run(["cmake", "--build", build_dir, "--parallel", "8"])
        run(["cmake", "--install", build_dir], sudo=True)
        run(["ldconfig"], sudo=True)
    finally:
        shutil.rmtree(build_root, ignore_errors=True)


def configure_oqs_environment(env_map=None, persist=False):
    if env_map is None:
        env_map = os.environ

    current_ld = (env_map.get("LD_LIBRARY_PATH") or "").strip()
    ld_parts = [p for p in current_ld.split(":") if p]
    if OQS_LIB_PATH not in ld_parts:
        ld_parts.insert(0, OQS_LIB_PATH)
    ld_library_path = ":".join(ld_parts) if ld_parts else OQS_LIB_PATH

    env_map["OQS_INSTALL_PATH"] = OQS_INSTALL_PATH
    env_map["LD_LIBRARY_PATH"] = ld_library_path

    os.environ["OQS_INSTALL_PATH"] = OQS_INSTALL_PATH
    os.environ["LD_LIBRARY_PATH"] = ld_library_path

    if persist:
        persist_env_variable("OQS_INSTALL_PATH", OQS_INSTALL_PATH)
        persist_env_variable("LD_LIBRARY_PATH", ld_library_path)


def pip_install(
    package,
    os_type,
    force_reinstall=False,
    upgrade=False,
    eager=False,
    no_cache_dir=True,
    break_system_packages=False,
):
    cmd = [sys.executable, "-m", "pip", "install"]

    if os_type == "ubuntu" and break_system_packages:
        cmd.append("--break-system-packages")

    if no_cache_dir:
        cmd.append("--no-cache-dir")
    if upgrade:
        cmd.append("--upgrade")
    if force_reinstall:
        cmd.append("--force-reinstall")
    if eager:
        cmd.extend(["--upgrade-strategy", "eager"])

    cmd.append(package)
    run(cmd)


def load_env_file(path: Path, *, overwrite: bool = False) -> bool:
    """Load a simple KEY=VALUE env file without requiring python-dotenv."""
    path = path.expanduser().resolve()
    if not path.exists():
        return False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        value = os.path.expandvars(os.path.expanduser(value))
        if key and (overwrite or key not in os.environ):
            os.environ[key] = value
    return True


def load_standalone_env() -> None:
    if load_env_file(STANDALONE_ENV_PATH, overwrite=False):
        print(f"Loaded standalone datasource configuration from {STANDALONE_ENV_PATH}")


def load_install_ini():
    cfg = configparser.ConfigParser()
    install_path = PROJECT_ROOT / "install.ini"
    read_files = cfg.read(install_path)
    if not read_files:
        raise RuntimeError(f"install.ini not found: {install_path}")
    if "Setup" not in cfg:
        raise RuntimeError("install.ini missing [Setup] section")
    if "Data" not in cfg:
        raise RuntimeError("install.ini missing [Data] section")
    return cfg


def persist_env_variable(key, value):
    bashrc = os.path.expanduser("~/.bashrc")
    lines = []
    if os.path.exists(bashrc):
        with open(bashrc, "r", encoding="utf-8") as f:
            lines = f.readlines()
    new_line = f'export {key}="{value}"\n'
    updated = False
    result_lines = []
    for line in lines:
        if line.strip().startswith(f"export {key}="):
            if not updated:
                result_lines.append(new_line)
                updated = True
        else:
            result_lines.append(line)
    if not updated:
        if result_lines and not result_lines[-1].endswith("\n"):
            result_lines[-1] = result_lines[-1] + "\n"
        result_lines.append(new_line)
    with open(bashrc, "w", encoding="utf-8") as f:
        f.writelines(result_lines)


def get_fhir_config_path(cfg, site):
    data_section = cfg["Data"]
    if site not in data_section:
        raise RuntimeError(f"Site {site} not found in [Data] section of install.ini")
    relative_path = data_section[site].strip()
    if not relative_path:
        raise RuntimeError(f"[Data] entry for site {site} is empty")

    configured = Path(relative_path).expanduser()
    candidates = []
    if configured.is_absolute():
        candidates.append(configured)
    else:
        candidates.extend([
            PROJECT_ROOT / configured,
            PROJECT_ROOT / "test_data" / configured,
        ])

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return str(resolved)

    tried = "\n".join(f"  {candidate.resolve()}" for candidate in candidates)
    raise RuntimeError(
        f"FHIR base config file for site {site} not found. Tried:\n{tried}"
    )


def _ensure_json_from_zip(expected_json_path: Path, overwrite=True) -> Path | None:
    if expected_json_path.suffix.lower() != ".json":
        return None

    zip_path = expected_json_path.with_suffix(".zip")
    if not zip_path.exists():
        return expected_json_path if expected_json_path.exists() else None

    if expected_json_path.exists() and not overwrite:
        return expected_json_path

    expected_json_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = [n for n in zf.namelist() if n and not n.endswith("/")]

            exact = None
            for n in names:
                if Path(n).name == expected_json_path.name:
                    exact = n
                    break

            member = exact
            if member is None:
                json_members = [n for n in names if n.lower().endswith(".json")]
                if len(json_members) == 1:
                    member = json_members[0]

            if member is None:
                json_count = len([n for n in names if n.lower().endswith(".json")])
                raise RuntimeError(
                    f"Could not determine which JSON file to extract from {zip_path}. "
                    f"Expected {expected_json_path.name}, but found {json_count} JSON files."
                )

            with zf.open(member, "r") as src, open(expected_json_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            return expected_json_path if expected_json_path.exists() else None

    except Exception as e:
        raise RuntimeError(f"Failed to unzip {zip_path} to produce {expected_json_path}: {e}") from e

def _iter_project_data_targets(project_id, value, source_key=None):
    current_source_key = project_id if source_key is None else source_key

    if isinstance(value, str):
        yield project_id, str(current_source_key), value
        return

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            next_source_key = str(child_key) if source_key is None else f"{source_key}.{child_key}"
            yield from _iter_project_data_targets(project_id, child_value, next_source_key)
        return

    if isinstance(value, list):
        for index, child_value in enumerate(value, start=1):
            next_source_key = f"{current_source_key}[{index}]"
            yield from _iter_project_data_targets(project_id, child_value, next_source_key)


def _is_http_source(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _resolve_standalone_source_value(value: str) -> Path | None:
    raw = (value or "").strip()
    if not raw or _is_http_source(raw):
        return None

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = STANDALONE_ROOT / candidate
    candidate = candidate.resolve()

    if candidate.suffix.lower() == ".json":
        produced = _ensure_json_from_zip(candidate, overwrite=True)
        if produced and produced.exists():
            return produced.resolve()
    if candidate.suffix.lower() == ".zip" and candidate.exists():
        expected_json = candidate.with_suffix(".json")
        produced = _ensure_json_from_zip(expected_json, overwrite=True)
        if produced and produced.exists():
            return produced.resolve()
    if candidate.exists():
        return candidate
    return None


def _datasource_env_keys(site: str, project_id: str, source_key: str) -> list[str]:
    prefix = f"DUALITY_CLIENT_{site.upper()}_DATASOURCE"
    project = str(project_id).strip()
    group = str(source_key).strip()
    keys: list[str] = []

    # Grouped datasource configs use keys such as
    # DUALITY_CLIENT_SITE1_DATASOURCE_2_1.
    if group and group != project and group.isdigit():
        keys.append(f"{prefix}_{project}_{group}")
    keys.append(f"{prefix}_{project}")
    keys.append(prefix)
    return keys


def _resolve_datasource_source_path(site, project_id, source_key, dest_path, overwrite=True):
    filename = os.path.basename(dest_path)

    # Prefer the exact source configured by standalone/.env.local. This mirrors
    # standalone/client_utils/create_client.py and keeps one datasource mapping
    # authoritative across the monorepo.
    for env_key in _datasource_env_keys(site, str(project_id), str(source_key)):
        env_value = os.environ.get(env_key)
        if not env_value:
            continue
        resolved = _resolve_standalone_source_value(env_value)
        if resolved is not None:
            return str(resolved)

    # The test_data directory now contains only FHIR base configuration files.
    # Actual datasource JSON/ZIP files live in share/standalone/nvflare_stage/data.
    direct = (STANDALONE_DATA_DIR / filename).resolve()
    if direct.suffix.lower() == ".json":
        produced = _ensure_json_from_zip(direct, overwrite=overwrite)
        if produced and produced.exists():
            return str(produced.resolve())
    if direct.exists():
        return str(direct)

    if STANDALONE_DATA_DIR.exists():
        for candidate in STANDALONE_DATA_DIR.rglob(filename):
            if candidate.is_file():
                return str(candidate.resolve())
        zip_name = Path(filename).with_suffix(".zip").name
        for zip_candidate in STANDALONE_DATA_DIR.rglob(zip_name):
            expected = zip_candidate.with_suffix(".json")
            produced = _ensure_json_from_zip(expected, overwrite=overwrite)
            if produced and produced.exists():
                return str(produced.resolve())

    return None

def sync_fhir_data_from_config(config_path, site, overwrite=True):
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    projects = config_data.get("projects", {})
    if not isinstance(projects, dict) or not projects:
        return

    for project_id, project_destinations in projects.items():
        for _, source_key, dest in _iter_project_data_targets(project_id, project_destinations):
            if not isinstance(dest, str):
                continue

            dest = dest.strip()
            if not dest:
                continue
            if not dest.lower().endswith(".json"):
                print(f"Skipping datasource sync for project {project_id} datasource {source_key}: {dest}")
                continue

            dest_path = os.path.abspath(dest)
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)

            src_path = _resolve_datasource_source_path(site, project_id, source_key, dest_path, overwrite=overwrite)

            if src_path is None:
                if os.path.exists(dest_path) and not overwrite:
                    continue
                raise RuntimeError(
                    f"FHIR data file for site {site}, project {project_id}, datasource {source_key} was not found. "
                    f"Expected it under {STANDALONE_DATA_DIR} or in {STANDALONE_ENV_PATH}. "
                    f"Destination: {dest_path}"
                )

            if os.path.abspath(src_path) == os.path.abspath(dest_path):
                continue

            if os.path.exists(dest_path) and not overwrite:
                continue

            shutil.copy2(src_path, dest_path)
            print(f"Updated data for project {project_id} datasource {source_key}: {dest_path}")


def set_fhir_base_config_env(config_path, env_map):
    persist_env_variable("DUALITY_NVFLARE_FHIR_BASE_CONFIG", config_path)
    env_map["DUALITY_NVFLARE_FHIR_BASE_CONFIG"] = config_path


def get_nvflare_server_name(cfg):
    if "Server" in cfg and "name" in cfg["Server"]:
        name = cfg["Server"]["name"].strip()
        if name:
            return name
    raise RuntimeError("Could not determine NVFLare server name from install.ini")


def provision_site_workspace(site, install_base=None, api_base_url=None, timeout_seconds=300):
    destination_base = Path(install_base or APP_HOME).expanduser().resolve()
    print(f"Downloading startup kit for {site} from the SHARE content-delivery service...")
    archive_path = download_startup_kit(
        site,
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
    )
    print(f"Downloaded startup kit: {archive_path}")

    install = install_startup_kit(
        archive_path,
        destination_base,
        expected_site=site,
        replace_existing=True,
    )
    if install.backup_workspace:
        print(f"Previous workspace backed up to: {install.backup_workspace}")
    print(f"Installed startup kit at: {install.workspace}")
    return str(install.workspace)


def _copy_client_agent_manage(startup_dir):
    src = str((LOCAL_RESULTS_API_DIR / "agent_manage.py").resolve())
    if not os.path.exists(src):
        return None
    dst = os.path.join(startup_dir, "duality_agent_manage.py")
    try:
        shutil.copy2(src, dst)
        run(["chmod", "+x", dst], sudo=False)
        return dst
    except Exception:
        return None


def _patch_start_script_for_agent(start_script_path):
    try:
        with open(start_script_path, "r", encoding="utf-8") as f:
            text = f.read()
        if "duality_agent_manage.py" in text:
            return
        lines = text.splitlines(True)
        out = []
        inserted = False
        for line in lines:
            out.append(line)
            if not inserted and line.startswith('DIR="') and "BASH_SOURCE" in line:
                block = (
                    'if command -v python3 >/dev/null 2>&1; then\n'
                    '  python3 "$DIR/duality_agent_manage.py" start --workspace "$DIR/.." >> "$DIR/duality_agent_manage_start.log" 2>&1 &\n'
                    "fi\n"
                )
                out.append(block)
                inserted = True
        if not inserted:
            out.insert(
                1,
                'python3 "$DIR/duality_agent_manage.py" start --workspace "$DIR/.." >> "$DIR/duality_agent_manage_start.log" 2>&1 &\n',
            )
        with open(start_script_path, "w", encoding="utf-8") as f:
            f.write("".join(out) + ("\n" if out and not out[-1].endswith("\n") else ""))
    except Exception:
        return


def _build_deploy_client_agent(workspace_root, os_type, env_map=None):
    agent_script = str((LOCAL_RESULTS_API_DIR / "agent_manage.py").resolve())
    if not os.path.exists(agent_script):
        return

    cmd = [sys.executable, agent_script, "build_deploy", "--workspace", os.path.abspath(workspace_root)]
    if os_type == "ubuntu":
        cmd.append("--installdocker")

    if os_type == "ubuntu":
        cmdline = " ".join(shlex_quote(x) for x in cmd)
        workdir = os.getcwd()
        bash_cmd = f'cd "{workdir}" && {cmdline}; exec bash'
        for tcmd in [
            ["gnome-terminal", "--", "bash", "-ic", bash_cmd],
            ["x-terminal-emulator", "-e", "bash", "-ic", bash_cmd],
            ["xterm", "-e", "bash", "-ic", bash_cmd],
        ]:
            try:
                subprocess.Popen(tcmd, env=env_map)
                return
            except FileNotFoundError:
                continue
            except OSError:
                continue

    log_path = os.path.join(os.path.abspath(workspace_root), "startup", "agent_build_deploy.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        f = open(log_path, "a", encoding="utf-8")
        subprocess.Popen(cmd, env=env_map, stdout=f, stderr=f)
    except Exception:
        subprocess.Popen(cmd, env=env_map)


def shlex_quote(s: str) -> str:
    if not s:
        return "''"
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@%+=:,./-")
    if all(c in safe for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def launch_startup(startup_dir, env_map):
    start_script = os.path.join(startup_dir, "start.sh")
    if not os.path.exists(start_script):
        raise RuntimeError(f"start.sh not found at {startup_dir}")
    stop_script = os.path.join(startup_dir, "stop_fl.sh")
    if os.path.exists(stop_script):
        try:
            subprocess.run(
                ["bash", "./stop_fl.sh"],
                cwd=startup_dir,
                env=env_map,
                check=True,
                input="y",
                text=True,
            )
        except subprocess.CalledProcessError:
            pass
        time.sleep(15)

    tried_any = False
    for cmd in [
        ["gnome-terminal", "--", "bash", "-ic", f'cd "{startup_dir}" && ./start.sh; exec bash'],
        ["x-terminal-emulator", "-e", "bash", "-ic", f'cd "{startup_dir}" && ./start.sh; exec bash'],
        ["xterm", "-e", "bash", "-ic", f'cd "{startup_dir}" && ./start.sh; exec bash'],
    ]:
        try:
            subprocess.Popen(cmd, env=env_map)
            tried_any = True
            return
        except FileNotFoundError:
            continue
        except OSError:
            continue

    if not tried_any:
        subprocess.Popen(["bash", "./start.sh"], cwd=startup_dir, env=env_map)


def print_security_group_hint():
    try:
        ip = run_capture(["curl", "-s", "http://checkip.amazonaws.com"]).strip()
        if ip:
            print(f"Be sure to add IP: {ip} to security group access rules")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    client_parser = subparsers.add_parser("client")
    client_parser.add_argument("--site", required=False, help="NVFlare client site. Prompts when omitted.")
    client_parser.add_argument("--env", required=True)
    client_parser.add_argument("--installdeps", action="store_true")
    client_parser.add_argument("--os", required=True)
    client_parser.add_argument("--venv", required=False)
    client_parser.add_argument("--breaksystempackages", action="store_true")
    client_parser.add_argument(
        "--install-base",
        default=str(APP_HOME),
        help="Parent directory where the downloaded <site> workspace is installed (default: ~/.duality-client)",
    )
    client_parser.add_argument(
        "--content-api-base",
        default="",
        help="Optional startup-kit API base URL override. Defaults to DUALITY_CONTENT_API_BASE_URL/DUALITY_BACKEND_URL.",
    )
    client_parser.add_argument(
        "--download-timeout",
        type=int,
        default=300,
        help="Startup-kit download timeout in seconds (default: 300)",
    )

    server_parser = subparsers.add_parser("server")
    server_parser.add_argument("--env", required=True)
    server_parser.add_argument("--installdeps", action="store_true")
    server_parser.add_argument("--os", required=True)
    server_parser.add_argument("--venv", required=False)
    server_parser.add_argument("--breaksystempackages", action="store_true")
    server_parser.add_argument(
        "--workspace",
        default="",
        help="Existing NVFlare server workspace. Server tar provisioning is no longer handled by client-supervisor.",
    )

    update_parser = subparsers.add_parser("update_data")
    update_parser.add_argument("--site", required=False)
    update_parser.add_argument("--no-overwrite", action="store_true")
    update_parser.add_argument("--overwrite", action="store_true")

    install_liboqs_parser = subparsers.add_parser("install_liboqs")
    install_liboqs_parser.add_argument("--os", required=True)
    install_liboqs_parser.add_argument("--force_reinstall", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.error("You must specify a command")

    if args.command == "client":
        if not (getattr(args, "site", None) or "").strip():
            if not sys.stdin.isatty():
                parser.error("client requires --site in non-interactive mode")
            args.site = input("Client site (for example site1): ").strip()
        args.site = validate_site_name(args.site)

    venv_root = None
    if args.command in {"client", "server"}:
        venv_root = _ensure_expected_venv(getattr(args, "venv", None))

    if args.command == "install_liboqs":
        os_type = args.os.lower()
        if os_type != "ubuntu":
            raise RuntimeError("install_liboqs is only supported for --os ubuntu")
        install_liboqs_ubuntu(force_reinstall=bool(getattr(args, "force_reinstall", False)))
        configure_oqs_environment(persist=True)
        return

    load_standalone_env()
    cfg = load_install_ini()

    if args.command == "update_data":
        overwrite = True if bool(getattr(args, "overwrite", False)) else not bool(getattr(args, "no_overwrite", False))

        site = getattr(args, "site", None)
        if site:
            site_key = site.strip()
            if site_key.lower() == "server":
                site_key = get_nvflare_server_name(cfg)

            config_path = get_fhir_config_path(cfg, site_key)
            sync_fhir_data_from_config(config_path, site_key, overwrite=overwrite)
            return

        seen = set()
        for data_key in cfg["Data"].keys():
            config_path = get_fhir_config_path(cfg, data_key)
            if config_path in seen:
                continue
            seen.add(config_path)
            sync_fhir_data_from_config(config_path, data_key, overwrite=overwrite)
        return

    os_type = args.os.lower()
    break_system_packages = bool(getattr(args, "breaksystempackages", False))

    if os_type == "ubuntu" and args.installdeps:
        install_ubuntu_dependencies()

    if os_type == "ubuntu":
        configure_oqs_environment(persist=False)

    pip_install(
        "nvflare==2.7.2",
        os_type,
        force_reinstall=True,
        upgrade=True,
        eager=True,
        break_system_packages=break_system_packages,
    )

    if args.command == "client":
        config_path = get_fhir_config_path(cfg, args.site)
        sync_fhir_data_from_config(config_path, args.site, overwrite=True)

        install_base = Path(args.install_base).expanduser().resolve()
        extracted_root = provision_site_workspace(
            args.site,
            install_base=install_base,
            api_base_url=(args.content_api_base or None),
            timeout_seconds=args.download_timeout,
        )

        child_env = os.environ.copy()
        if venv_root:
            _apply_venv_to_env(child_env, venv_root)
        set_fhir_base_config_env(config_path, child_env)
        if os_type == "ubuntu":
            configure_oqs_environment(child_env, persist=False)

        toolkit_root = str(PROJECT_ROOT)
        ws = os.path.abspath(extracted_root)
        job_results_path = os.path.join(ws, "job-results")
        os.makedirs(job_results_path, exist_ok=True)

        child_env["DUALITY_TOOLKIT_ROOT"] = toolkit_root
        child_env["DUALITY_CLIENT_SITE"] = args.site
        child_env["DUALITY_CLIENT_ENV"] = args.env
        child_env["DUALITY_CLIENT_WORKSPACE"] = ws
        child_env["DUALITY_NVFLARE_WORKSPACE"] = ws
        child_env["DUALITY_NVFLARE_JOB_SAVE_LOCATION"] = job_results_path
        if venv_root:
            child_env["DUALITY_SELECTED_VENV"] = venv_root

        persist_env_variable("DUALITY_TOOLKIT_ROOT", toolkit_root)
        persist_env_variable("DUALITY_CLIENT_SITE", args.site)
        persist_env_variable("DUALITY_CLIENT_ENV", args.env)
        persist_env_variable("DUALITY_CLIENT_WORKSPACE", ws)
        persist_env_variable("DUALITY_NVFLARE_JOB_SAVE_LOCATION", job_results_path)

        startup_dir = os.path.abspath(os.path.join(extracted_root, "startup"))
        _copy_client_agent_manage(startup_dir)
        _patch_start_script_for_agent(os.path.join(startup_dir, "start.sh"))

        _build_deploy_client_agent(extracted_root, os_type, env_map=child_env)
        launch_startup(startup_dir, child_env)

        print_security_group_hint()

    elif args.command == "server":
        workspace_value = (args.workspace or os.environ.get("DUALITY_SERVER_WORKSPACE") or "").strip()
        if not workspace_value:
            raise RuntimeError(
                "Server archive staging is no longer managed by client-supervisor. Pass --workspace or set DUALITY_SERVER_WORKSPACE."
            )
        workspace = Path(workspace_value).expanduser().resolve()
        startup_dir = workspace / "startup"
        if not (startup_dir / "start.sh").exists():
            raise RuntimeError(f"Server start.sh not found under: {startup_dir}")
        env_map = os.environ.copy()
        if venv_root:
            _apply_venv_to_env(env_map, venv_root)
            env_map["DUALITY_SELECTED_VENV"] = venv_root
        if os_type == "ubuntu":
            configure_oqs_environment(env_map, persist=False)
        launch_startup(str(startup_dir), env_map)

    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
