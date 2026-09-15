# docker_stage/container_builder.py
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

PUBLIC_SNAPSHOT_WHEEL_NAME = "duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl"

class ContainerBuilder:
    # project_dir is the folder that has docker-compose.yml
    # env_file is an optional .env style file to pass to compose
    # project_name is the compose project name used for container names
    def __init__(self, project_dir: Optional[Path] = None, env_file: Optional[str] = None, project_name: str = "duality"):
        self.project_dir = Path(project_dir or Path.cwd()).resolve()
        self.project_name = project_name
        self.env_file = str(Path(env_file).resolve()) if env_file else None
        self.compose_file = self.project_dir / "docker-compose.yml"
        # services known to the compose file; only backend/frontend need source on disk
        self._known_services = {"frontend", "backend", "nvflare", "mysql"}

    # check that docker is installed and the daemon is running
    def _ensure_docker_running(self):
        docker_bin = shutil.which("docker")
        docker_compose_bin = shutil.which("docker-compose")
        if not docker_bin and not docker_compose_bin:
            raise RuntimeError("Docker not found on PATH. Install Docker Desktop or docker-compose.")
        try:
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except Exception as e:
            detail = ""
            if isinstance(e, subprocess.CalledProcessError):
                detail = (e.stderr or "").strip().lower()
            if "permission denied while trying to connect to the docker daemon socket" in detail:
                raise RuntimeError(
                    "Docker daemon permission denied. Access to /var/run/docker.sock was denied."
                ) from e
            raise RuntimeError("Docker daemon does not appear to be running. Start Docker and retry.") from e

    # build the base compose command
    # prefers "docker compose", falls back to "docker-compose"
    # adds the project name and optional env file flag
    def _compose_base(self) -> List[str]:
        if shutil.which("docker"):
            base = ["docker", "compose"]
        elif shutil.which("docker-compose"):
            base = ["docker-compose"]
        else:
            raise RuntimeError("docker compose not found. Install Docker Desktop or docker-compose.")
        base += ["-p", self.project_name]
        if self.env_file:
            base += ["--env-file", self.env_file]
        return base

    # run a command in the project directory and return the exit code
    def _run(self, args: List[str], ignore_stderr_substrings: Optional[List[str]] = None) -> int:
        print(f"[cwd] {self.project_dir}")
        print("$ " + " ".join(args))
        p = subprocess.run(args, cwd=str(self.project_dir), text=True, capture_output=True)
        if p.stdout:
            print(p.stdout, end="")
        if p.stderr:
            stderr_lines = p.stderr.splitlines()
            if ignore_stderr_substrings:
                stderr_lines = [
                    line for line in stderr_lines
                    if not any(needle in line for needle in ignore_stderr_substrings)
                ]
            if stderr_lines:
                print("\n".join(stderr_lines), file=sys.stderr)
        return p.returncode

    # helper to get the current python exe (so "python main.py codebase" works on any platform/venv)
    def _python_exe(self) -> str:
        return sys.executable or "python"

    # paths: repo root is standalone/ and source trees live one level above it
    def _repo_root(self) -> Path:
        return self.project_dir.parent

    def _workspace_root(self) -> Path:
        return self._repo_root().parent

    def _service_source_dir(self, service: str) -> Path:
        mapping = {
            "frontend": self._workspace_root() / "frontend",
            "backend": self._workspace_root() / "backend",
        }
        return mapping[service]

    def _local_wheels_dir(self) -> Path:
        return self.project_dir / "local_wheels"

    # Ensure ./local_wheels exists and is writable by the current (host) user.
    #
    # docker-compose.yml bind-mounts ./local_wheels into the nvflare container.
    # If this host directory does not exist when `docker compose up` runs, the
    # Docker daemon (root) auto-creates it as root:root, after which non-root
    # tooling (this process) can no longer stage wheels into it. Creating it
    # here, before any compose command, keeps ownership with the invoking user.
    def _ensure_local_wheels_dir(self) -> Path:
        wheels_dir = self._local_wheels_dir()
        if wheels_dir.exists() and not os.access(wheels_dir, os.W_OK):
            try:
                wheels_dir.rmdir()
            except OSError:
                print(
                    f"[WARN] {wheels_dir} is not writable and not empty. "
                    f"Run: sudo chown -R $(id -un):$(id -gn) {wheels_dir}",
                    flush=True,
                )
        wheels_dir.mkdir(parents=True, exist_ok=True)
        return wheels_dir

    def _job_results_dir(self) -> Path:
        return self.project_dir.parent / "job-results"

    # Same ownership concern as ./local_wheels: docker-compose.yml bind-mounts
    # ../job-results into the backend and nvflare containers, and create_client.py
    # later needs to create standalone/job-results/<site> for site1/site2. If the
    # daemon creates the directory it is root-owned and that mkdir fails.
    def _ensure_job_results_dir(self) -> Path:
        results_dir = self._job_results_dir()
        if results_dir.exists() and not os.access(results_dir, os.W_OK):
            print(
                f"[WARN] {results_dir} is not writable by the current user. "
                f"Run: sudo chown -R $(id -un):$(id -gn) {results_dir}",
                flush=True,
            )
        results_dir.mkdir(parents=True, exist_ok=True)
        return results_dir

    def _prepare_local_wheel_context(self, services: List[str], local_wheel_path: Optional[str] = None) -> None:
        if "nvflare" not in [s.strip().lower() for s in services]:
            return

        wheels_dir = self._ensure_local_wheels_dir()
        source_value = local_wheel_path or os.getenv("DUALITY_LOCAL_WHEEL_PATH")

        if source_value:
            selected = Path(source_value).expanduser().resolve()
            if not selected.exists():
                print(f"[ERROR] Local wheel not found: {selected}", flush=True)
                raise FileNotFoundError(f"Local wheel not found: {selected}")
            if not selected.name.startswith("duality_nvflare_lib-") or selected.suffix != ".whl":
                raise ValueError(f"Local wheel must be a duality_nvflare_lib .whl file: {selected}")
            source_label = "explicit local"
        else:
            selected = self._repo_root() / "wheels" / PUBLIC_SNAPSHOT_WHEEL_NAME
            if not selected.is_file():
                raise FileNotFoundError(f"Bundled public runtime wheel is missing: {selected}")
            source_label = "bundled snapshot"

        for existing in wheels_dir.glob("duality_nvflare_lib-*.whl"):
            try:
                existing.unlink()
            except OSError as e:
                print(f"[WARN] Could not remove old local wheel {existing}: {e}", flush=True)

        dest = wheels_dir / selected.name
        if selected.resolve() != dest.resolve():
            shutil.copy2(selected, dest)
        print(f"[INFO] Prepared {source_label} runtime wheel for NVFlare build.", flush=True)

    # run the "codebase" step via your main.py so refs/branches in .env.local are respected
    # allow an optional selector ("backend" or "frontend") to avoid cloning both
    def _run_codebase(self, only: Optional[str] = None) -> None:
        repo_root = self._repo_root()
        main_py = repo_root / "main.py"
        if not main_py.exists():
            raise FileNotFoundError(f"Cannot locate main.py at {main_py}")
        cmd = [self._python_exe(), str(main_py), "codebase"]
        if only in ("backend", "frontend", "all"):
            cmd.append(only)
        print(f"[INFO] Checking local source via: {' '.join(cmd)} (cwd={repo_root})", flush=True)
        subprocess.run(cmd, cwd=str(repo_root), check=True)

    # basic checks before any compose action
    # makes sure docker is running, compose file exists
    # and local backend/frontend source trees are available
    def _check_files(self):
        self._ensure_docker_running()
        if not self.compose_file.exists():
            raise FileNotFoundError(f"docker-compose.yml not found at {self.compose_file}")
        self._ensure_local_wheels_dir()

    # decide if we should update the frontend env file
    # returns true when no services were specified or when frontend is in the list
    def _should_touch_frontend(self, services: Optional[List[str]]) -> bool:
        if services is None or len(services) == 0:
            return True
        return any(s.strip().lower() == "frontend" for s in services)

    # read key value pairs from the provided env file
    # returns a dict for quick lookups
    def _env_from_file(self) -> dict:
        data = {}
        if not self.env_file:
            return data
        p = Path(self.env_file)
        if not p.exists():
            return data
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
        return data

    # write a frontend env file with API base and build flavor
    # this helps the frontend know how to reach the backend
    def _write_frontend_env(self):
        fe_dir = self._service_source_dir("frontend")
        if not fe_dir.exists():
            print("[INFO] Frontend repo not present; skipping .env.production.local write.", flush=True)
            return
        env_kv = self._env_from_file()
        api_base = (
            env_kv.get("REACT_APP_API_BASE")
            or env_kv.get("NEXT_PUBLIC_BACKEND_URL")
            or os.getenv("REACT_APP_API_BASE")
            or os.getenv("NEXT_PUBLIC_BACKEND_URL")
            or "http://localhost:8000"
        )
        build_flavor = env_kv.get("REACT_APP_BUILD_FLAVOR") or os.getenv("REACT_APP_BUILD_FLAVOR") or "local"
        env_path = fe_dir / ".env.production.local"
        content = f"REACT_APP_API_BASE={api_base}\nREACT_APP_BUILD_FLAVOR={build_flavor}\n"
        env_path.write_text(content, encoding="utf-8")
        print(f"[INFO] Wrote {env_path} with API_BASE={api_base} BUILD_FLAVOR={build_flavor}", flush=True)

    # compute which requested services are missing on disk
    # only backend/frontend have local source to check
    def _missing_services(self, services: List[str]) -> List[str]:
        missing = []
        for s in services:
            t = s.strip().lower()
            if t in ("frontend", "backend"):
                if not self._service_source_dir(t).exists():
                    missing.append(t)
        return missing

    # ensure requested services have their source present
    # if missing, run codebase step for each missing service and re-check
    def _ensure_source_for_services(self, services: List[str]) -> None:
        missing = self._missing_services(services)
        if not missing:
            return
        print(f"[WARN] Missing source for: {', '.join(missing)}. Running codebase check...", flush=True)
        for svc in missing:
            try:
                self._run_codebase(svc)
            except subprocess.CalledProcessError as e:
                raise FileNotFoundError(f"Failed to verify source via codebase step for {svc}: {e}") from e
        missing_after = self._missing_services(services)
        if missing_after:
            raise FileNotFoundError(
                f"Source code required for: {', '.join(missing_after)}. Expected under {self._workspace_root()}. "
                f"Codebase check completed but source directories are still missing."
            )

    # derive the MySQL named volume for this compose project
    def _mysql_volume_name(self) -> str:
        return f"{self.project_name}_mysql_data"

    # wipe the MySQL data volume (stops and removes mysql container first)
    def wipe_mysql_storage(self) -> int:
        self._check_files()
        vol = self._mysql_volume_name()
        print(f"[INFO] Wiping MySQL storage volume: {vol}", flush=True)
        stop_cmd = self._compose_base() + ["stop", "mysql"]
        self._run(stop_cmd)
        rm_cmd = self._compose_base() + ["rm", "-f", "-s", "mysql"]
        self._run(rm_cmd)
        rc = self._run(["docker", "volume", "rm", "-f", vol])
        if rc != 0:
            print(f"[WARN] Volume '{vol}' could not be removed (it may not exist yet).", flush=True)
        else:
            print(f"[INFO] Removed volume '{vol}'.", flush=True)
        return rc

    # Wait until <container>'s entrypoint has finished creating /opt/nvflare/.venv and
    # installing the base nvflare wheel. The nvflare and client containers run a heavy
    # `python3 -m venv` + `pip install nvflare scipy openfhe ...` chain in CMD, and
    # `docker compose up -d` returns long before that finishes. Probing `pip show nvflare`
    # is the cheapest signal that the venv is usable and the base install is done.
    # Returns True when ready, False on timeout. Best-effort: never raises.
    def _wait_for_container_venv(self, container: str, timeout_s: int = 600, interval_s: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            probe = subprocess.run(
                ["docker", "exec", container, "/opt/nvflare/.venv/bin/pip", "show", "nvflare"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if probe.returncode == 0:
                return True
            time.sleep(interval_s)
        return False

    # stop and remove the compose project
    # remove_volumes true will also delete named volumes
    def reset(self, remove_volumes: bool = False) -> int:
        self._check_files()
        cmd = self._compose_base() + ["down", "--remove-orphans"]
        if remove_volumes:
            cmd += ["-v"]
        return self._run(cmd, ignore_stderr_substrings=['No resource found to remove for project'])

    # build images for all or selected services
    # can disable cache for a clean rebuild
    def build(self, services: Optional[List[str]] = None, no_cache: bool = False) -> int:
        self._check_files()
        source_services = ["backend", "frontend"] if services is None else services

        if services:
            bad = [s for s in services if s not in self._known_services]
            if bad:
                print(f"[ERROR] Unknown services: {', '.join(bad)}. Valid: {', '.join(sorted(self._known_services))}", flush=True)
                return 2
        self._ensure_source_for_services(source_services)
        if self._should_touch_frontend(services):
            self._write_frontend_env()
        cmd = self._compose_base() + ["build"]
        if no_cache:
            cmd += ["--no-cache"]
        if services:
            cmd += services
        return self._run(cmd)

    # start the stack
    # detach true returns to the shell, build true forces a build before up
    def up(self, services: Optional[List[str]] = None, detach: bool = True, build: bool = True) -> int:
        self._check_files()
        source_services = ["backend", "frontend"] if services is None else services
        if services:
            bad = [s for s in services if s not in self._known_services]
            if bad:
                print(f"[ERROR] Unknown services: {', '.join(bad)}. Valid: {', '.join(sorted(self._known_services))}", flush=True)
                return 2
        self._ensure_source_for_services(source_services)
        self._ensure_job_results_dir()
        if build and self._should_touch_frontend(services):
            self._write_frontend_env()
        cmd = self._compose_base() + ["up"]
        if detach:
            cmd += ["-d"]
        if build:
            cmd += ["--build"]
        if services:
            cmd += services
        return self._run(cmd)

    # stop the stack
    # remove_volumes true will also delete named volumes
    def down(self, remove_volumes: bool = False) -> int:
        self._check_files()
        cmd = self._compose_base() + ["down"]
        if remove_volumes:
            cmd += ["-v"]
        return self._run(cmd)

    # show logs for all or selected services
    # follow true streams the logs
    def logs(self, services: Optional[List[str]] = None, follow: bool = False) -> int:
        self._check_files()
        if services:
            bad = [s for s in services if s not in self._known_services]
            if bad:
                print(f"[ERROR] Unknown services: {', '.join(bad)}. Valid: {', '.join(sorted(self._known_services))}", flush=True)
                return 2
        cmd = self._compose_base() + ["logs"]
        if follow:
            cmd += ["-f"]
        if services:
            cmd += services
        return self._run(cmd)

    # show running containers for the project
    def ps(self) -> int:
        self._check_files()
        cmd = self._compose_base() + ["ps"]
        return self._run(cmd)

    # pull images from the registry for all or selected services
    def pull(self, services: Optional[List[str]] = None) -> int:
        self._check_files()
        source_services = ["backend", "frontend"] if services is None else services
        if services:
            bad = [s for s in services if s not in self._known_services]
            if bad:
                print(f"[ERROR] Unknown services: {', '.join(bad)}. Valid: {', '.join(sorted(self._known_services))}", flush=True)
                return 2
        self._ensure_source_for_services(source_services)
        cmd = self._compose_base() + ["pull"]
        if services:
            cmd += services
        return self._run(cmd)

    # convenience method to reset, optionally clear volumes, build, and start
    def run_all(self, no_cache: bool = False, clean_volumes: bool = False) -> int:
        self._prepare_local_wheel_context(["nvflare"])
        rc = self.reset(remove_volumes=False)
        if rc not in (0,):
            return rc
        if clean_volumes:
            rc = self.reset(remove_volumes=True)
            if rc != 0:
                return rc
        self._write_frontend_env()
        rc = self.build(no_cache=no_cache)
        if rc != 0:
            return rc
        return self.up()

    # rebuild only the given services from source and restart them
    # note: we do NOT use --no-deps so that backend can honor depends_on/healthchecks
    def rebuild(self, services: List[str], no_cache: bool = False, wipe_mysql: Optional[bool] = None, local_wheel_path: Optional[str] = None) -> int:
        if not services:
            print("[ERROR] rebuild requires one or more services (frontend, backend, nvflare, mysql)", flush=True)
            return 2
        self._check_files()
        bad = [s for s in services if s not in self._known_services]
        if bad:
            print(f"[ERROR] Unknown services: {', '.join(bad)}. Valid: {', '.join(sorted(self._known_services))}", flush=True)
            return 2
        self._ensure_source_for_services(services)
        self._prepare_local_wheel_context(services, local_wheel_path=local_wheel_path)

        if self._should_touch_frontend(services):
            self._write_frontend_env()

        env_kv = self._env_from_file()
        env_val = (env_kv.get("DUALITY_DB_WIPE_ON_REBUILD") or os.getenv("DUALITY_DB_WIPE_ON_REBUILD") or "").strip().lower()
        env_wipe = env_val in ("1", "true", "yes")
        do_wipe = env_wipe if wipe_mysql is None else bool(wipe_mysql)

        if do_wipe and "mysql" in services:
            self.wipe_mysql_storage()

        build_cmd = self._compose_base() + ["build"]
        if no_cache:
            build_cmd += ["--no-cache"]
        build_cmd += services
        rc = self._run(build_cmd)
        if rc != 0:
            return rc

        rm_cmd = self._compose_base() + ["rm", "-f", "-s"] + services
        rc = self._run(rm_cmd)
        if rc != 0:
            return rc

        self._ensure_job_results_dir()
        up_cmd = self._compose_base() + ["up", "-d", "--no-deps"] + services
        rc = self._run(up_cmd)
        return rc

    # update pulls latest source for the given services then rebuilds and restarts them
    def update(self, services: List[str], no_cache: bool = False) -> int:
        if not services:
            print("[ERROR] update requires one or more services (frontend, backend, nvflare, mysql)", flush=True)
            return 2
        self._check_files()
        bad = [s for s in services if s not in self._known_services]
        if bad:
            print(f"[ERROR] Unknown services: {', '.join(bad)}. Valid: {', '.join(sorted(self._known_services))}", flush=True)
            return 2
        svc_to_dir = {
            "frontend": self._service_source_dir("frontend"),
            "backend": self._service_source_dir("backend"),
        }
        for s in services:
            if s not in svc_to_dir:
                continue
            repo_dir = svc_to_dir[s]
            print(f"[INFO] Pulling latest for {s} at {repo_dir}", flush=True)
            try:
                subprocess.run(["git", "pull"], cwd=str(repo_dir), check=True)
            except subprocess.CalledProcessError as e:
                print(f"[ERROR] git pull failed in {repo_dir}: {e}", flush=True)
                return 2

        if self._should_touch_frontend(services):
            self._write_frontend_env()

        build_cmd = self._compose_base() + ["build"]
        if no_cache:
            build_cmd += ["--no-cache"]
        build_cmd += services
        rc = self._run(build_cmd)
        if rc != 0:
            return rc

        rm_cmd = self._compose_base() + ["rm", "-f", "-s"] + services
        rc = self._run(rm_cmd)
        if rc != 0:
            return rc

        self._ensure_job_results_dir()
        up_cmd = self._compose_base() + ["up", "-d", "--no-deps"] + services
        rc = self._run(up_cmd)
        return rc
