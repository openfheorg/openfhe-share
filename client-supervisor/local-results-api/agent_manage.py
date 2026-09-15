import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_IMAGE = "duality-client-agent:local"
DEFAULT_CONTAINER = "duality-client-agent"
DEFAULT_PORT = 8088
TOKEN_FILENAME = ".duality_client_agent_token"


def _run_capture(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)


def _run(cmd):
    subprocess.check_call(cmd)


def _is_ubuntu():
    try:
        data = Path("/etc/os-release").read_text(encoding="utf-8").lower()
        return "ubuntu" in data
    except Exception:
        return False


def _docker_cli_present() -> bool:
    return shutil.which("docker") is not None


def _is_interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _try_start_docker_service():
    if not _is_ubuntu():
        return
    try:
        _run(["sudo", "systemctl", "start", "docker"])
        return
    except Exception:
        pass
    try:
        _run(["sudo", "service", "docker", "start"])
    except Exception:
        pass


def _docker_base_cmd():
    candidates = [
        ["docker"],
        ["sudo", "-n", "docker"],
    ]
    if _is_interactive():
        candidates.append(["sudo", "docker"])

    for base in candidates:
        try:
            _run_capture(base + ["version"])
            return base
        except subprocess.CalledProcessError as e:
            out = (getattr(e, "output", "") or "").lower()

            if "permission denied" in out and "docker.sock" in out:
                continue

            if "a password is required" in out or "sudo:" in out and "password" in out:
                continue

            if "cannot connect to the docker daemon" in out or "is the docker daemon running" in out:
                _try_start_docker_service()
                try:
                    _run_capture(base + ["version"])
                    return base
                except subprocess.CalledProcessError:
                    continue
                except Exception:
                    continue

            continue
        except FileNotFoundError:
            continue
        except Exception:
            continue

    return None


def ensure_docker(installdocker: bool):
    base = _docker_base_cmd()
    if base:
        return base

    if _docker_cli_present():
        raise RuntimeError(
            "Docker CLI found but cannot access the Docker daemon. "
            "Fix docker.sock permissions (add user to docker group and re-login) "
            "or allow sudo access to docker."
        )

    if not installdocker:
        raise RuntimeError("Docker is not available")

    if not _is_ubuntu():
        raise RuntimeError("Docker auto-install is only supported on Ubuntu")

    _run(["sudo", "apt-get", "update"])
    _run(["sudo", "apt-get", "install", "-y", "curl"])
    _run(["curl", "-fsSL", "https://get.docker.com", "-o", "install-docker.sh"])
    _run(["sudo", "sh", "install-docker.sh"])

    base = _docker_base_cmd()
    if not base:
        raise RuntimeError("Docker install completed but docker is still not available")
    return base


def docker_image_exists(docker_cmd, image: str) -> bool:
    out = _run_capture(docker_cmd + ["images", "-q", image]).strip()
    return bool(out)


def docker_container_exists(docker_cmd, name: str) -> bool:
    try:
        _run_capture(docker_cmd + ["inspect", name])
        return True
    except Exception:
        return False


def docker_container_running(docker_cmd, name: str) -> bool:
    try:
        out = _run_capture(docker_cmd + ["inspect", "-f", "{{.State.Running}}", name]).strip().lower()
        return out == "true"
    except Exception:
        return False


def docker_rm_force(docker_cmd, name: str):
    try:
        _run(docker_cmd + ["rm", "-f", name])
    except Exception:
        pass


def docker_build(docker_cmd, image: str, context_dir: str):
    # Always rebuild from the current local source during the desktop demo.
    # This prevents stale duality-client-agent:local layers from hiding source changes.
    _run(docker_cmd + ["build", "--no-cache", "-t", image, context_dir])


def _token_path(workspace_root: str) -> str:
    return str(Path(workspace_root).expanduser().resolve() / TOKEN_FILENAME)


def read_or_create_token(workspace_root: str, token: str = "") -> str:
    token = (token or "").strip()
    tp = _token_path(workspace_root)
    if token:
        Path(tp).write_text(token, encoding="utf-8")
        return token
    if os.path.exists(tp):
        existing = Path(tp).read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    Path(tp).write_text(token, encoding="utf-8")
    return token


def docker_run_agent(docker_cmd, image: str, container: str, workspace_root: str, port: int, token: str, ui_origins: str, job_save_location: str = ""):
    workspace_root = str(Path(workspace_root).expanduser().resolve())
    if not os.path.isdir(workspace_root):
        raise RuntimeError(f"Workspace root is not a directory: {workspace_root}")

    container_job_save_location = (job_save_location or "/nvflare/job-results").strip()
    # The host workspace is mounted into the container at /nvflare, so this is
    # the corresponding host path the local NVFlare client should write into.
    host_job_results = Path(workspace_root) / container_job_save_location.replace("/nvflare/", "", 1).lstrip("/")
    host_job_results.mkdir(parents=True, exist_ok=True)

    sys.stdout.write(f"[Results Agent] workspace host path: {workspace_root}\n")
    sys.stdout.write(f"[Results Agent] job results host path: {host_job_results}\n")
    sys.stdout.write(f"[Results Agent] container mount: {workspace_root} -> /nvflare:ro\n")
    sys.stdout.write(f"[Results Agent] DUALITY_NVFLARE_JOB_SAVE_LOCATION={container_job_save_location}\n")
    sys.stdout.flush()

    cmd = docker_cmd + [
        "run",
        "-d",
        "--name",
        container,
        "--restart",
        "unless-stopped",
        "-p",
        f"127.0.0.1:{port}:8088",
        "-e",
        "DUALITY_NVFLARE_WORKSPACE=/nvflare",
        "-e",
        f"DUALITY_CLIENT_AGENT_TOKEN={token}",
        "-e",
        f"DUALITY_NVFLARE_JOB_SAVE_LOCATION={container_job_save_location}",
        "-v",
        f"{workspace_root}:/nvflare:ro",
    ]

    ui_origins = (ui_origins or "").strip()
    if ui_origins:
        cmd += ["-e", f"DUALITY_UI_ORIGINS={ui_origins}"]

    cmd += [image]
    _run(cmd)


def docker_restart_or_run(docker_cmd, image: str, container: str, workspace_root: str, port: int, token: str, ui_origins: str, job_save_location: str = ""):
    if not docker_image_exists(docker_cmd, image):
        raise RuntimeError(f"Docker image not found: {image}")

    if docker_container_exists(docker_cmd, container):
        if job_save_location:
            # Docker cannot change environment variables or mounts on an existing
            # container. Recreate it so DUALITY_NVFLARE_JOB_SAVE_LOCATION follows
            # the currently selected startup-kit workspace/run location.
            docker_rm_force(docker_cmd, container)
        elif docker_container_running(docker_cmd, container):
            _run(docker_cmd + ["restart", container])
            return
        else:
            _run(docker_cmd + ["start", container])
            return

    docker_run_agent(docker_cmd, image, container, workspace_root, port, token, ui_origins, job_save_location=job_save_location)


def docker_stop_agent(docker_cmd, container: str):
    if not docker_container_exists(docker_cmd, container):
        return
    try:
        _run(docker_cmd + ["stop", container])
    except Exception:
        pass


def docker_status(docker_cmd, container: str) -> dict:
    if not docker_container_exists(docker_cmd, container):
        return {"exists": False, "running": False}
    running = docker_container_running(docker_cmd, container)
    return {"exists": True, "running": running}


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    build = sp.add_parser("build_deploy")
    build.add_argument("--workspace", required=True)
    build.add_argument("--image", default=DEFAULT_IMAGE)
    build.add_argument("--container", default=DEFAULT_CONTAINER)
    build.add_argument("--port", type=int, default=DEFAULT_PORT)
    build.add_argument("--token", default="")
    build.add_argument("--ui_origins", default="")
    build.add_argument("--job_save_location", default="")
    build.add_argument("--installdocker", action="store_true")

    start = sp.add_parser("start")
    start.add_argument("--workspace", required=True)
    start.add_argument("--image", default=DEFAULT_IMAGE)
    start.add_argument("--container", default=DEFAULT_CONTAINER)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--token", default="")
    start.add_argument("--ui_origins", default="")
    start.add_argument("--job_save_location", default="")
    start.add_argument("--installdocker", action="store_true")

    stop = sp.add_parser("stop")
    stop.add_argument("--container", default=DEFAULT_CONTAINER)
    stop.add_argument("--installdocker", action="store_true")

    status = sp.add_parser("status")
    status.add_argument("--container", default=DEFAULT_CONTAINER)
    status.add_argument("--installdocker", action="store_true")

    args = p.parse_args()

    docker_cmd = ensure_docker(installdocker=bool(getattr(args, "installdocker", False)))

    if args.cmd == "stop":
        docker_stop_agent(docker_cmd, args.container)
        return

    if args.cmd == "status":
        st = docker_status(docker_cmd, args.container)
        sys.stdout.write(json.dumps(st) + "\n")
        sys.stdout.flush()
        return

    workspace = str(Path(args.workspace).expanduser().resolve())
    image = args.image
    container = args.container
    port = int(args.port)
    token = read_or_create_token(workspace, token=getattr(args, "token", ""))
    ui_origins = (getattr(args, "ui_origins", "") or "").strip()
    job_save_location = (getattr(args, "job_save_location", "") or "").strip()

    if args.cmd == "build_deploy":
        context_dir = os.path.dirname(os.path.abspath(__file__))
        sys.stdout.write(f"[Results Agent] rebuilding Docker image from: {context_dir}\n")
        sys.stdout.flush()
        docker_build(docker_cmd, image, context_dir)
        docker_rm_force(docker_cmd, container)
        docker_run_agent(docker_cmd, image, container, workspace, port, token, ui_origins, job_save_location=job_save_location)
    else:
        docker_restart_or_run(docker_cmd, image, container, workspace, port, token, ui_origins, job_save_location=job_save_location)

    sys.stdout.write(f"DUALITY_CLIENT_AGENT_TOKEN={token}\n")
    sys.stdout.write(f"http://127.0.0.1:{port}/health\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
