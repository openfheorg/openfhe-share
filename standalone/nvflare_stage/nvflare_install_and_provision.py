# purpose: provision an NVFLARE workspace and pack the admin startup kit
# reads configuration from .env.local 
# can run locally on non windows or via wsl on windows
# rewrites project.yml with host and ports for the local machine before provisioning
# tars the admin kit folder and writes DUALITY_ADMIN_TAR back into .env.local

import os
import sys
import subprocess
import re
import shutil
import tarfile
import shlex

# compute repo root and ensure it is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(1, REPO_ROOT)

# timeouts for provisioning commands
WSL_TIMEOUT_SECS = int(os.environ.get("DUALITY_NVF_WSL_TIMEOUT_SECS", "900"))
LOCAL_TIMEOUT_SECS = int(os.environ.get("DUALITY_NVF_LOCAL_TIMEOUT_SECS", "600"))

def info(m): print("[INFO] " + str(m), flush=True)
def warn(m): print("[WARN] " + str(m), flush=True)
def err(m):  print("[ERROR] " + str(m), flush=True)

# load environment variables from .env.local
# if a relative path is given it is resolved from repo root
def load_env(path=None):
    if path:
        p = path
        if not os.path.isabs(p):
            p = os.path.join(REPO_ROOT, p)
    else:
        p = os.path.join(REPO_ROOT, ".env.local")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        info("Loaded env from " + p)
        return os.path.abspath(p)
    err(".env.local not found at " + p)
    sys.exit(1)

# update or append a key in an env file
def update_env_file(env_path, key, value):
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    found = False
    new_lines = []
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            new_lines.append(key + "=" + value)
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(key + "=" + value)
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines).rstrip() + "\n")
    info("Updated " + key + " in " + env_path)

# quick check for nvflare python package
def nvflare_installed():
    try:
        import nvflare  # noqa: F401
        return True
    except Exception:
        return False

# install nvflare into the current python
def pip_install_nvflare():
    info("Installing NVFLARE via pip...")
    cmd = [sys.executable, "-m", "pip", "install", "nvflare==2.7.2"]
    subprocess.run(cmd, check=True)

# rewrite project.yml server block and sp_end_point for local host and ports
def rewrite_project_for_local(src_path, dst_path, host, fed_port, admin_port):
    with open(src_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = 0
    updated_server = False
    while i < len(lines) and not updated_server:
        if re.match(r"^\s*-\s+name:\s+\S+", lines[i]):
            block_start = i
            block_end = i + 1
            while block_end < len(lines) and not re.match(r"^\s*-\s+name:\s+\S+", lines[block_end]):
                block_end += 1
            is_server = False
            for j in range(block_start + 1, block_end):
                if re.match(r"^\s*type:\s*server\s*$", lines[j]):
                    is_server = True
                    break
            if is_server:
                for j in range(block_start, block_end):
                    if re.match(r"^\s*-\s+name:\s+\S+", lines[j]):
                        lines[j] = re.sub(r"^(\s*-\s+name:\s+).+$", r"\g<1>" + host, lines[j])
                    elif re.match(r"^\s*fed_learn_port:\s*\d+\s*$", lines[j]):
                        lines[j] = re.sub(r"^(\s*fed_learn_port:\s*)\d+\s*$", r"\g<1>" + str(fed_port), lines[j])
                    elif re.match(r"^\s*admin_port:\s*\d+\s*$", lines[j]):
                        lines[j] = re.sub(r"^(\s*admin_port:\s*)\d+\s*$", r"\g<1>" + str(admin_port), lines[j])
                updated_server = True
            i = block_end
            continue
        i += 1
    text = "\n".join(lines)
    text = re.sub(
        r"sp_end_point:\s*[^:\s]+:\d+:\d+",
        "sp_end_point: " + host + ":" + str(fed_port) + ":" + str(admin_port),
        text,
    )
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(text)

# detect if wsl is available on windows
def _wsl_available():
    try:
        subprocess.run(["wsl", "--status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        info("WSL detected.")
        return True
    except Exception as e:
        warn("WSL not available: " + str(e))
        return False

# run a command and stream stdout live
def _run_logged(cmd, timeout=None):
    info("RUN: " + " ".join(shlex.quote(c) for c in cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        while True:
            chunk = p.stdout.readline()
            if not chunk:
                break
            try:
                s = chunk.decode("utf-8", errors="replace")
            except Exception:
                s = chunk.decode(errors="replace")
            print(s, end="")
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        raise
    return p.returncode

# provision using wsl by creating a small venv and installing nvflare inside it
def _provision_with_wsl(project_file, workspace_dir):
    host_abs = os.path.abspath(os.getcwd())
    if len(host_abs) >= 3 and host_abs[1] == ":":
        drive = host_abs[0].lower()
        path_part = host_abs[2:].replace("\\", "/")
        wsl_work = f"/mnt/{drive}/{path_part}"
    else:
        wsl_work = host_abs.replace("\\", "/")
    info("WSL provision working directory: " + wsl_work)
    venv_dir = "/root/.nvf_venv"
    pip_bin = venv_dir + "/bin/pip"
    nvflare_bin = venv_dir + "/bin/nvflare"
    bash_cmd = (
        "export LANG=C.UTF-8; export LC_ALL=C.UTF-8; "
        f"cd {shlex.quote(wsl_work)} && "
        "apt-get update && "
        "apt-get install -y python3-venv python3-pip && "
        f"python3 -m venv {shlex.quote(venv_dir)} && "
        f"{shlex.quote(pip_bin)} install --upgrade pip && "
        f"{shlex.quote(pip_bin)} install nvflare==2.7.2 && "
        f"{shlex.quote(nvflare_bin)} provision -p {shlex.quote(project_file)} -w {shlex.quote(workspace_dir)}"
    )
    cmd = ["wsl", "-u", "root", "-e", "bash", "-lc", bash_cmd]
    rc = _run_logged(cmd, timeout=WSL_TIMEOUT_SECS)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)

# try local provisioning commands on non windows
def _provision_local_attempts(project_file, workspace_dir, is_windows):
    if is_windows:
        warn("Windows detected: skipping local Python attempts and using WSL only.")
        return False
    attempts = []
    nvflare_path = shutil.which("nvflare")
    if nvflare_path:
        attempts.append([nvflare_path, "provision", "-p", project_file, "-w", workspace_dir])
    prov_path = shutil.which("provision")
    if prov_path:
        attempts.append([prov_path, "-p", project_file, "-w", workspace_dir])
    attempts.append([sys.executable, "-m", "nvflare.cli", "provision", "-p", project_file, "-w", workspace_dir])
    for cmd in attempts:
        try:
            rc = _run_logged(cmd, timeout=LOCAL_TIMEOUT_SECS)
            if rc == 0:
                return True
        except Exception as e:
            warn("Local attempt failed: " + str(e))
    return False

# orchestrates provisioning based on the platform
def provision_workspace(project_file, workspace_dir):
    # Clean-provision when we have decided to provision
    if os.path.isdir(workspace_dir):
        shutil.rmtree(workspace_dir, ignore_errors=True)
    os.makedirs(workspace_dir, exist_ok=True)
    info("Provisioning NVFLARE workspace -> " + workspace_dir)
    is_windows = os.name == "nt"
    if not is_windows:
        if _provision_local_attempts(project_file, workspace_dir, is_windows=False):
            return
        warn("Local provision failed on non Windows; no WSL fallback on this platform.")
        raise RuntimeError("Local provision failed. See logs above for details.")
    if not _wsl_available():
        raise RuntimeError("WSL is not available. Enable WSL and install a Linux distro from the Store.")
    _provision_with_wsl(project_file, workspace_dir)

# search the provisioned tree for the admin folder
def _find_admin_dir(workspace_dir, admin_name):
    workspace_dir = os.path.abspath(workspace_dir)
    for root, dirs, _files in os.walk(workspace_dir):
        if admin_name in dirs:
            return os.path.join(root, admin_name)
    return None

# add a directory entry into a tar with reasonable defaults
def _add_dir_with_empty(tar: tarfile.TarFile, dir_path: str, arc_prefix: str):
    ti = tarfile.TarInfo(name=arc_prefix)
    ti.type = tarfile.DIRTYPE
    try:
        st = os.stat(dir_path)
        ti.mode = st.st_mode
        ti.mtime = int(st.st_mtime)
    except Exception:
        ti.mode = 0o755
    tar.addfile(ti)

# write a tar that contains the admin startup kit including startup and local subfolders
def tar_admin_kit(workspace_dir, admin_name, out_tar_path):
    admin_dir = _find_admin_dir(workspace_dir, admin_name)
    if not admin_dir or not os.path.isdir(admin_dir):
        err("Admin kit folder not found under " + os.path.abspath(workspace_dir) + " for name: " + admin_name)
        return 2
    startup = os.path.join(admin_dir, "startup")
    local_dir = os.path.join(admin_dir, "local")
    os.makedirs(local_dir, exist_ok=True)
    fl = os.path.join(startup, "fl_admin.sh")
    if os.path.exists(fl):
        try:
            os.chmod(fl, os.stat(fl).st_mode | 0o111)
        except Exception:
            pass
        try:
            b = open(fl, "rb").read()
            if b"\r\n" in b:
                open(fl, "wb").write(b.replace(b"\r\n", b"\n"))
        except Exception:
            pass
    out_dir = os.path.dirname(out_tar_path)
    os.makedirs(out_dir, exist_ok=True)
    with tarfile.open(out_tar_path, "w") as tar:
        _add_dir_with_empty(tar, admin_dir, admin_name)
        for root, dirs, files in os.walk(admin_dir):
            rel_root = os.path.relpath(root, admin_dir)
            arc_root = os.path.join(admin_name, "." if rel_root == "." else rel_root).replace("\\", "/")
            for d in dirs:
                d_full = os.path.join(root, d)
                d_arc = os.path.join(arc_root, d).replace("\\", "/")
                _add_dir_with_empty(tar, d_full, d_arc)
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.join(arc_root, name).replace("\\", "/")
                tar.add(full, arcname=arc)
    info("Wrote admin startup kit tar with startup and local folders: " + out_tar_path)
    return 0

def _expected_workspace_root(workspace_dir):
    # Expected structure: <workspace_dir>/duality_nvflare/prod_00
    return os.path.join(os.path.abspath(workspace_dir), "duality_nvflare", "prod_00")

def _workspace_is_provisioned(workspace_dir):
    expected = _expected_workspace_root(workspace_dir)
    # Treat as provisioned only when prod_00 actually contains the provisioned participant kits.
    # Docker bind-mounts auto-create an EMPTY prod_00 (root-owned) when the nvflare container starts,
    # so an isdir() check alone would wrongly report "already provisioned", skip provisioning, and
    # leave no client startup-kit folders (breaking client creation, option 6).
    return os.path.isdir(expected) and any(os.scandir(expected))

# main entry for the nvflare stage
def run():
    env_path = load_env()

    # Always refresh dist so the admin tar we write is current
    dist_dir = os.path.join(REPO_ROOT, "dist")
    if os.path.isdir(dist_dir):
        shutil.rmtree(dist_dir, ignore_errors=True)
    os.makedirs(dist_dir, exist_ok=True)

    host = (os.environ.get("DUALITY_NVFLARE_HOST", "") or "").strip()
    fed_port = int(os.environ.get("DUALITY_NVFLARE_FED_PORT", "8002"))
    admin_port = int(os.environ.get("DUALITY_NVFLARE_ADMIN_PORT", "8003"))

    src_project = os.environ.get("DUALITY_NVFLARE_PROJECT_FILE", "project.yml")
    if not os.path.exists(src_project):
        err("project file not found: " + str(src_project))
        return 2

    workspace_dir = os.environ.get("DUALITY_NVFLARE_WORKSPACE", "nvflare_workspace")

    # NEW BEHAVIOR: if workspace already looks provisioned, skip provisioning
    if _workspace_is_provisioned(workspace_dir):
        info("Existing workspace found, skipping provisioning step.")
    else:
        # Only try to install/use NVFLARE and provision when needed
        if os.name != "nt" and not nvflare_installed():
            try:
                pip_install_nvflare()
            except subprocess.CalledProcessError:
                warn("Local NVFLARE install failed; will still attempt local provision.")

        local_project = os.path.splitext(src_project)[0] + ".local.yml"
        rewrite_project_for_local(src_project, local_project, host, fed_port, admin_port)
        info("Wrote local project file: " + local_project)

        try:
            provision_workspace(local_project, workspace_dir)
        except Exception as e:
            err("Provisioning failed: " + str(e))
            return 4

    # Pack admin startup kit and update env with the tar path either way
    admin_name = os.environ.get("DUALITY_NVFLARE_ADMIN_NAME", "admin@share.local")
    out_tar = os.path.join(REPO_ROOT, "dist", "admin_startup_kit.tar")
    rc = tar_admin_kit(workspace_dir, admin_name, out_tar)
    if rc != 0:
        return rc

    update_env_file(env_path, "DUALITY_ADMIN_TAR", out_tar)

    info("NVFLARE workspace ready.")
    info("Server host: " + host + "  fed_port: " + str(fed_port) + "  admin_port: " + str(admin_port))
    info("Workspace:   " + workspace_dir)
    info("Admin tar:   " + out_tar)
    return 0

if __name__ == "__main__":
    print("This script is meant to be run via the orchestrator.")
    print("Use:  python main.py nvflare")
    sys.exit(1)
