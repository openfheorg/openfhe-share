import argparse, os, sys, tarfile, subprocess, re, json, time, urllib.request, urllib.parse, zipfile, shutil
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.mysql_driver_utils import ensure_mysql_driver

# Force linux/amd64 build unless the caller overrides; enable BuildKit
DEF_ENV = {**os.environ, "DOCKER_DEFAULT_PLATFORM": "linux/amd64", "DOCKER_BUILDKIT": "1"}
PUBLIC_SNAPSHOT_WHEEL_NAME = "duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl"
# So the (root) client containers can hand trace files on the bind-mounted
# job-results tree back to this host user (no sudo to delete them later).
if hasattr(os, "getuid"):
    DEF_ENV.setdefault("DUALITY_HOST_UID", str(os.getuid()))
    DEF_ENV.setdefault("DUALITY_HOST_GID", str(os.getgid()))

def info(m): print(f"[INFO] {m}", flush=True)
def err(m):  print(f"[ERROR] {m}", flush=True)
def warn(m): print("[WARN] " + str(m), flush=True)

def run(cmd, **kw):
    # Wrapper so we always pass the default env unless overridden
    return subprocess.run(cmd, env=DEF_ENV, **kw)

def load_env(path: Path | None = None):
    # Minimal .env loader (.env.local by default). Does not overwrite already-set env vars.
    candidates = [path] if path else [REPO_ROOT / ".env.local"]
    for p in candidates:
        if p and p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
            info(f"Loaded env from {p}")
            return

def check_docker():
    # Ensure Docker Engine is reachable before proceeding
    try:
        run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        err("Docker daemon not running or not installed.")
        sys.exit(2)

def find_participant_dir(workspace: Path, name: str) -> Path | None:
    # Look for a participant directory named exactly `name` under the workspace tree
    for p in workspace.rglob(name):
        if p.is_dir() and p.name == name:
            return p
    return None

def _wait_for_container_venv(container: str, timeout_s: int = 600, interval_s: float = 3.0) -> bool:
    # The client container's CMD does `python3 -m venv` + `pip install nvflare scipy openfhe ...`
    # at startup. `docker compose up -d` returns before that finishes, so we poll
    # `pip show nvflare` until it returns 0 -- that's the signal that the venv exists
    # and the base install is complete. Returns True when ready, False on timeout.
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

def tar_client_kit(src_dir: Path, out_tar: Path):
    # Create a deterministic tarball of the client startup kit and ensure *.sh are executable
    out_tar.parent.mkdir(parents=True, exist_ok=True)
    info(f"Tarring client kit from {src_dir} -> {out_tar}")
    with tarfile.open(out_tar, "w") as tar:
        base = src_dir
        for root, _, files in os.walk(base):
            root_p = Path(root)
            for f in files:
                full = root_p / f
                arc = str(base.name / full.relative_to(base))
                ti = tar.gettarinfo(str(full), arcname=arc)
                if full.suffix == ".sh":
                    ti.mode = (ti.mode or 0o644) | 0o111
                with open(full, "rb") as fh:
                    tar.addfile(ti, fh)

def infer_site_from_tar(tar_path: Path) -> str | None:
    # Expect filenames like client_site2_startup_kit.tar
    m = re.search(r"client_(site[0-9A-Za-z._-]+)_startup_kit\.tar$", tar_path.name)
    return m.group(1) if m else None

def _ensure_json_from_zip(json_path: Path) -> Path:
    if json_path.suffix.lower() != ".json":
        return json_path

    zip_path = json_path.with_suffix(".zip")
    if not zip_path.exists():
        return json_path

    # Re-extract when the zip is newer than the previously extracted JSON, so a
    # data update to the .zip cannot leave clients running on stale data.
    if json_path.exists() and json_path.stat().st_mtime >= zip_path.stat().st_mtime:
        return json_path

    json_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            exact = None
            for n in names:
                if Path(n).name == json_path.name:
                    exact = n
                    break

            if exact:
                zf.extract(exact, path=str(json_path.parent))
                extracted = json_path.parent / exact
                if extracted != json_path:
                    extracted.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        extracted.replace(json_path)
                    except Exception:
                        shutil.move(str(extracted), str(json_path))
                return json_path

            json_members = [n for n in names if n.lower().endswith(".json")]
            if len(json_members) == 1:
                member = json_members[0]
                zf.extract(member, path=str(json_path.parent))
                extracted = json_path.parent / member
                if extracted != json_path:
                    extracted.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        extracted.replace(json_path)
                    except Exception:
                        shutil.move(str(extracted), str(json_path))
                return json_path

            zf.extractall(path=str(json_path.parent))

    except Exception as e:
        raise RuntimeError(f"Failed to unzip {zip_path} to produce {json_path}: {e}") from e

    if json_path.exists():
        return json_path

    for p in json_path.parent.rglob("*.json"):
        if p.name == json_path.name:
            try:
                p.replace(json_path)
            except Exception:
                shutil.move(str(p), str(json_path))
            return json_path

    return json_path

def _normalize_datasource_path(p: Path) -> Path:
    p = p.expanduser()
    if not p.is_absolute():
        p = REPO_ROOT / p
    p = p.resolve()
    if p.suffix.lower() == ".json":
        p = _ensure_json_from_zip(p)
    return p

def _is_remote_datasource(value: str) -> bool:
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    path = (parsed.path or "").lower()
    return not path.endswith(".json")

def _normalize_datasource_value(value: str) -> Path | str:
    value = value.strip()
    if _is_remote_datasource(value):
        return value
    return _normalize_datasource_path(Path(value))

def _get_datasource_env_matches(site: str) -> list[tuple[str, str]]:
    prefix = f"DUALITY_CLIENT_{site.upper()}_DATASOURCE_"
    matches = [(k, v) for k, v in os.environ.items() if k.startswith(prefix)]

    def suffix_sort(key: str) -> tuple[int, int, str]:
        s = key[len(prefix):].strip()
        parts = s.split("_")
        try:
            project_id = int(parts[0])
        except ValueError:
            project_id = 0
        try:
            group_id = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            group_id = 0
        return (project_id, group_id, s)

    matches.sort(key=lambda kv: suffix_sort(kv[0]))
    return matches

def _parse_datasource_env_key(site: str, key: str) -> tuple[str, str | None] | None:
    prefix = f"DUALITY_CLIENT_{site.upper()}_DATASOURCE_"
    if not key.startswith(prefix):
        return None

    suffix = key[len(prefix):].strip()
    if not suffix:
        return None

    parts = suffix.split("_")
    if len(parts) == 1:
        project_id = parts[0].strip()
        if not project_id:
            return None
        return (project_id, None)

    if len(parts) == 2:
        project_id = parts[0].strip()
        datasource_group_id = parts[1].strip()
        if not project_id or not datasource_group_id:
            return None
        return (project_id, datasource_group_id)

    return None

def collect_datasources_for_site(site: str) -> dict[str, Path | str | dict[str, Path | str]]:
    # Returns ordered mapping of project_id -> datasource or project_id -> { datasource_group_id -> datasource }.
    matches = _get_datasource_env_matches(site)
    if matches:
        collected: dict[str, Path | str | dict[str, Path | str]] = {}
        for key, raw_value in matches:
            parsed = _parse_datasource_env_key(site, key)
            if not parsed:
                continue

            project_id, datasource_group_id = parsed
            normalized_value = _normalize_datasource_value(raw_value)

            if datasource_group_id is None:
                existing = collected.get(project_id)
                if isinstance(existing, dict):
                    err(
                        f"Mixed grouped and ungrouped datasource configuration for site '{site}', project '{project_id}'."
                    )
                    sys.exit(18)
                collected[project_id] = normalized_value
            else:
                existing = collected.get(project_id)
                if existing is None:
                    existing = {}
                    collected[project_id] = existing

                if not isinstance(existing, dict):
                    err(
                        f"Mixed grouped and ungrouped datasource configuration for site '{site}', project '{project_id}'."
                    )
                    sys.exit(18)

                existing[datasource_group_id] = normalized_value

        if collected:
            return collected

    env_key = f"DUALITY_CLIENT_{site.upper()}_DATASOURCE"
    override = os.environ.get(env_key)
    if override:
        return {"1": _normalize_datasource_value(override)}

    warn(f"No local datasource JSON staging entries found for site '{site}'.")
    return {}

def stage_local_datasources_for_build(site: str, project_sources: dict[str, Path | str | dict[str, Path | str]]) -> Path:
    # Stage all local datasource JSON files into the Docker build context so they are copied into the image.
    inject_dir = THIS_DIR / "injected_datasources"
    inject_dir.mkdir(parents=True, exist_ok=True)

    for existing in inject_dir.iterdir():
        if existing.is_file() or existing.is_symlink():
            existing.unlink()
        elif existing.is_dir():
            shutil.rmtree(existing)

    local_files: list[Path] = []
    for value in project_sources.values():
        if isinstance(value, dict):
            for grouped_value in value.values():
                if isinstance(grouped_value, Path):
                    local_files.append(grouped_value)
        elif isinstance(value, Path):
            local_files.append(value)

    if not local_files:
        info(f"No local datasource JSON files configured for site '{site}'.")
        return inject_dir

    seen_names: set[str] = set()
    for src in local_files:
        if not src.exists():
            err(f"Datasource JSON not found for {site}: {src}")
            sys.exit(7)

        if src.name in seen_names:
            err(f"Duplicate datasource filename for site '{site}': {src.name}")
            sys.exit(17)

        seen_names.add(src.name)
        dest = inject_dir / src.name
        shutil.copy2(str(src), str(dest))
        info(f"Prepared datasource for image build: {src} -> {dest}")

    return inject_dir

def stage_local_wheel_for_build() -> Path:
    local_wheels_dir = THIS_DIR / "local_wheels"
    # Self-heal a root-owned dir auto-created by a prior `docker compose up` (the
    # client compose bind-mounts ./local_wheels; if it doesn't exist on the host,
    # the Docker daemon creates it as root, blocking later staging). rmdir is
    # governed by the parent dir's perms (user-owned), so this works without sudo
    # as long as the directory is empty.
    if local_wheels_dir.exists() and not os.access(local_wheels_dir, os.W_OK):
        try:
            local_wheels_dir.rmdir()
        except OSError:
            warn(
                f"{local_wheels_dir} is not writable and not empty. "
                f"Run: sudo chown -R $(id -un):$(id -gn) {local_wheels_dir}"
            )
    local_wheels_dir.mkdir(parents=True, exist_ok=True)

    source_value = os.environ.get("DUALITY_LOCAL_WHEEL_PATH")
    if source_value:
        selected = Path(source_value).expanduser().resolve()
        if not selected.exists():
            err(f"Local wheel not found: {selected}")
            sys.exit(20)
        if not selected.name.startswith("duality_nvflare_lib-") or selected.suffix != ".whl":
            err(f"Local wheel must be a duality_nvflare_lib .whl file: {selected}")
            sys.exit(20)
        source_label = "explicit local"
    else:
        repo_root = THIS_DIR.parent.parent
        selected = repo_root / "standalone" / "wheels" / PUBLIC_SNAPSHOT_WHEEL_NAME
        if not selected.is_file():
            err(f"Bundled public runtime wheel is missing: {selected}")
            sys.exit(20)
        source_label = "bundled snapshot"

    for existing in local_wheels_dir.glob("duality_nvflare_lib-*.whl"):
        try:
            existing.unlink()
        except OSError as e:
            warn(f"Could not remove old local wheel {existing}: {e}")

    dest = local_wheels_dir / selected.name
    if selected.resolve() != dest.resolve():
        shutil.copy2(selected, dest)
    info(f"Prepared {source_label} runtime wheel for client build.")
    return local_wheels_dir

def cleanup_runtime_artifacts(temp_compose: Path | None = None):
    errors = []

    try:
        inject_dir = THIS_DIR / "injected_datasources"
        if inject_dir.exists():
            shutil.rmtree(inject_dir)
            info(f"Deleted injected datasource dir: {inject_dir}")
    except Exception as e:
        errors.append(f"injected datasource cleanup failed: {e}")

    try:
        if temp_compose and temp_compose.exists():
            temp_compose.unlink()
            info(f"Deleted TEMP compose: {temp_compose.name}")
    except Exception as e:
        errors.append(f"temp compose cleanup failed: {e}")

    if errors:
        for e in errors:
            warn(e)

def _site_container_names(site: str) -> list[str]:
    return [
        f"duality-client-{site}",
        f"duality-client-results-{site}",
    ]


def remove_existing_site_containers(site: str):
    for container_name in _site_container_names(site):
        try:
            probe = subprocess.run(
                ["docker", "container", "inspect", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            warn(f"Could not inspect existing container '{container_name}': {e}")
            continue

        if probe.returncode != 0:
            continue

        info(f"Removing existing container '{container_name}' so it can be rebuilt cleanly.")
        subprocess.run(["docker", "rm", "-f", container_name], check=True)


def stop_site_containers(site: str):
    for container_name in _site_container_names(site):
        try:
            probe = subprocess.run(
                ["docker", "container", "inspect", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if probe.returncode != 0:
                continue
            info(f"Stopping container '{container_name}'.")
            subprocess.run(["docker", "stop", container_name], check=True)
        except Exception as e:
            warn(f"Could not stop container '{container_name}': {e}")


def get_site_results_port(site: str) -> int:
    site_text = (site or "").strip().lower()
    match = re.fullmatch(r"site(\d+)", site_text)
    if not match:
        raise RuntimeError(
            f"Cannot derive a local results port from site name '{site}'. "
            "Expected a name like site1, site2, or site3."
        )

    site_number = int(match.group(1))
    base_port = int(os.environ.get("DUALITY_CLIENT_RESULTS_BASE_PORT", "8088"))
    port = base_port + site_number
    if not (1 <= port <= 65535):
        raise RuntimeError(f"Derived invalid local results port {port} for site '{site}'.")
    return port


def copy_site3_model_files(site: str):
    if site.strip().lower() != "site3":
        return

    model_files_dir = THIS_DIR / "model_files"
    if not model_files_dir.exists():
        warn(f"No model_files directory found for site3 at {model_files_dir}; skipping model file copy.")
        return

    container_name = f"duality-client-{site}"
    target_dir = "/data/model_files"

    info(f"Copying model files for site3 into {container_name}:{target_dir}")
    subprocess.run(["docker", "exec", container_name, "mkdir", "-p", target_dir], check=True)

    source_arg = str(model_files_dir) + os.sep + "."
    subprocess.run(["docker", "cp", source_arg, f"{container_name}:{target_dir}/"], check=True)
    info(f"Copied model files from {model_files_dir} to {container_name}:{target_dir}")

# Simple interactive prompt
def ask_yes_no(prompt: str, default: bool = False) -> bool:
    """
    Ask a y/n question on stdin. Returns default if input is not a TTY.
    Accepts: y/yes/n/no (case-insensitive). Empty answer -> default.
    """
    if not sys.stdin.isatty():
        info(f"{prompt} {'Y/n' if default else 'y/N'} [non-interactive -> default={'y' if default else 'n'}]")
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    for _ in range(3):
        ans = input(prompt + suffix).strip().lower()
        if ans == "":
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'.")
    return default

# Compose rendering (per-site service names)
# We keep a shared compose project (e.g., "duality-client") and create uniquely
# named client and results-agent services so multiple simulated sites can run together.
# Site3 is the initiator and starts only its NVFLARE client service; its results are
# already exposed through the backend's existing job-results mount.
# Compose does not support env-var substitution in service keys, so we render a
# temporary compose file with both service keys rewritten for the selected site.
SERVICE_KEY_PATTERN = re.compile(r'(^|\r?\n)services:\s*(\r?\n)(\s*)client:', re.M)
RESULTS_SERVICE_KEY_PATTERN = re.compile(r'(^|\r?\n)(\s*)results-agent:', re.M)

def render_compose_for_site_temp(orig_compose: Path, site: str) -> Path:
    """
    Create a TEMPORARY per-site compose file next to the template so relative volume
    paths in the template continue to resolve correctly. Caller is responsible for deletion.
    """
    txt = orig_compose.read_text(encoding="utf-8")
    new_txt, n = SERVICE_KEY_PATTERN.subn(r'\1services:\2\3client-' + site + ':', txt, count=1)
    if n == 0:
        err("Could not rewrite service name 'client' -> 'client-<site>' in compose file.")
        sys.exit(14)

    new_txt, results_n = RESULTS_SERVICE_KEY_PATTERN.subn(
        r'\1\2results-agent-' + site + ':',
        new_txt,
        count=1,
    )
    if results_n == 0:
        err("Could not rewrite service name 'results-agent' -> 'results-agent-<site>' in compose file.")
        sys.exit(14)

    out_path = orig_compose.with_name(f"docker-compose.client.{site}.{os.getpid()}.yml")
    out_path.write_text(new_txt, encoding="utf-8")
    info(f"Rendered TEMP compose: {out_path.name} (service: client-{site})")
    return out_path

def _mysql_connect():
    host = os.environ.get("DUALITY_MYSQL_HOST", "localhost")
    port = int(os.environ.get("DUALITY_MYSQL_PORT", "3306"))
    user = os.environ.get("DUALITY_MYSQL_USER", "root")
    password = os.environ.get("DUALITY_MYSQL_PASSWORD", "")
    db = os.environ.get("DUALITY_MYSQL_DB", "duality_local")

    try:
        _mysql, driver = ensure_mysql_driver(warn=warn)
        if _mysql is None or driver is None:
            raise RuntimeError("No MySQL driver available")
        if driver == "mysql.connector":
            conn = _mysql.connect(host=host, port=port, user=user, password=password, database=db)
        else:
            conn = _mysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=db,
                charset="utf8mb4",
                autocommit=False,
            )
        return conn, driver
    except Exception as e:
        err(f"No MySQL driver found or connection failed: {e}")
        sys.exit(12)

def _ensure_role(cur, role_name: str) -> int:
    cur.execute(
        "INSERT INTO defined_roles (name, description) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), description=VALUES(description)",
        (role_name, "NVFLARE client role"),
    )
    return cur.lastrowid

def _ensure_user(cur, username: str, role_id: int) -> int:
    cur.execute(
        "INSERT INTO users (username, password_hash, role_id) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), role_id=VALUES(role_id)",
        (username, "DISABLED", role_id),
    )
    return cur.lastrowid

def _ensure_client_mapping(cur, site: str, user_id: int) -> int:
    cur.execute(
        "INSERT INTO nvflare_clients (client_name, user_id, description) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), user_id=VALUES(user_id)",
        (site, user_id, f"Auto-created for {site}"),
    )
    return cur.lastrowid

def _username_for_site(site: str) -> str:
    if site.strip().lower() == "site3":
        return "initiator"
    return f"client_{site}"

def _get_existing_user_id(cur, username: str) -> int | None:
    cur.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    if not row:
        return None
    return int(row[0])

def _datasource_source_for_mysql(raw_value: str) -> str:
    source = raw_value.strip()
    if not source or _is_remote_datasource(source):
        return source

    normalized = _normalize_datasource_value(source)
    if isinstance(normalized, Path):
        return f"/data/client/{normalized.name}"
    return str(normalized)

def _datasource_records_from_env(site: str) -> list[dict[str, int | None | str]]:
    records: list[dict[str, int | None | str]] = []
    matches = _get_datasource_env_matches(site)

    for key, raw_value in matches:
        parsed = _parse_datasource_env_key(site, key)
        if not parsed:
            continue

        project_id_value, datasource_group_id_value = parsed
        raw_source = raw_value.strip()
        if not raw_source:
            continue
        source = _datasource_source_for_mysql(raw_source)

        try:
            project_id = int(project_id_value)
        except (TypeError, ValueError):
            warn(f"Skipping datasource env key with invalid project id: {key}")
            continue

        datasource_group_id = None
        if datasource_group_id_value is not None:
            try:
                datasource_group_id = int(datasource_group_id_value)
            except (TypeError, ValueError):
                warn(f"Skipping datasource env key with invalid datasource group id: {key}")
                continue

        records.append(
            {
                "project_id": project_id,
                "datasource_group_id": datasource_group_id,
                "source": source,
                "env_key": key,
            }
        )

    if records:
        return records

    env_key = f"DUALITY_CLIENT_{site.upper()}_DATASOURCE"
    override = os.environ.get(env_key)
    if override and override.strip():
        records.append(
            {
                "project_id": 1,
                "datasource_group_id": None,
                "source": _datasource_source_for_mysql(override.strip()),
                "env_key": env_key,
            }
        )

    return records

def _ensure_user_datasource(cur, user_id: int, project_id: int, source: str, datasource_group_id: int | None) -> str:
    if datasource_group_id is None:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM users_fhir_source_by_project
            WHERE user_id = %s
              AND project_id = %s
              AND datasource_group IS NULL
            """,
            (user_id, project_id),
        )
        count_row = cur.fetchone()
        count = int(count_row[0] or 0) if count_row else 0

        if count:
            cur.execute(
                """
                UPDATE users_fhir_source_by_project
                SET source = %s,
                    datasource_group = NULL
                WHERE user_id = %s
                  AND project_id = %s
                  AND datasource_group IS NULL
                """,
                (source, user_id, project_id),
            )
            return "updated"

        cur.execute(
            """
            INSERT INTO users_fhir_source_by_project (user_id, project_id, source, datasource_group)
            VALUES (%s, %s, %s, NULL)
            """,
            (user_id, project_id, source),
        )
        return "inserted"

    cur.execute(
        """
        SELECT COUNT(*)
        FROM users_fhir_source_by_project
        WHERE user_id = %s
          AND project_id = %s
          AND datasource_group = %s
        """,
        (user_id, project_id, datasource_group_id),
    )
    count_row = cur.fetchone()
    count = int(count_row[0] or 0) if count_row else 0

    if count:
        cur.execute(
            """
            UPDATE users_fhir_source_by_project
            SET source = %s,
                datasource_group = %s
            WHERE user_id = %s
              AND project_id = %s
              AND datasource_group = %s
            """,
            (source, datasource_group_id, user_id, project_id, datasource_group_id),
        )
        return "updated"

    cur.execute(
        """
        INSERT INTO users_fhir_source_by_project (user_id, project_id, source, datasource_group)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, project_id, source, datasource_group_id),
    )
    return "inserted"

def ensure_user_datasources(site: str, user_id: int):
    records = _datasource_records_from_env(site)
    if not records:
        info(f"MySQL: no datasource env entries found for '{site}'.")
        return

    conn, _driver = _mysql_connect()
    try:
        cur = conn.cursor()
        for record in records:
            action = _ensure_user_datasource(
                cur,
                user_id=user_id,
                project_id=int(record["project_id"]),
                source=str(record["source"]),
                datasource_group_id=record["datasource_group_id"],
            )
            info(
                f"MySQL: {action} datasource for site='{site}', user_id={user_id}, "
                f"project_id={record['project_id']}, datasource_group_id={record['datasource_group_id']}, "
                f"source={record['source']}"
            )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        conn.rollback()
        err(f"MySQL datasource registration failed for '{site}': {e}")
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
        sys.exit(19)

def ensure_client_registered(site: str):
    conn, _driver = _mysql_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.id, u.id, u.username FROM nvflare_clients c "
            "JOIN users u ON u.id = c.user_id "
            "WHERE c.client_name = %s",
            (site,),
        )
        existing = cur.fetchone()

        site_normalized = site.strip().lower()

        if site_normalized == "site3":
            username = "initiator"
            user_id = _get_existing_user_id(cur, username)
            if user_id is None:
                raise RuntimeError("Existing user 'initiator' was not found in users table.")
            client_id = _ensure_client_mapping(cur, site, user_id)
            conn.commit()

            if existing:
                existing_client_id, existing_user_id, existing_username = existing[0], existing[1], existing[2]
                if existing_user_id != user_id or existing_username != username:
                    info(
                        f"MySQL: updated mapping for '{site}' "
                        f"from client_id={existing_client_id}, user_id={existing_user_id}, username={existing_username} "
                        f"to client_id={client_id}, user_id={user_id}, username={username}"
                    )
                else:
                    info(f"MySQL: existing mapping for '{site}' -> client_id={client_id}, user_id={user_id}, username={username}")
            else:
                info(f"MySQL: registered '{site}' -> client_id={client_id}, user_id={user_id}, username={username}")

            cur.close()
            conn.close()
            return client_id, user_id

        role_id = _ensure_role(cur, "client")
        username = f"client_{site}"
        user_id = _ensure_user(cur, username, role_id)
        client_id = _ensure_client_mapping(cur, site, user_id)
        conn.commit()

        if existing:
            existing_client_id, existing_user_id, existing_username = existing[0], existing[1], existing[2]
            if existing_user_id != user_id or existing_username != username:
                info(
                    f"MySQL: updated mapping for '{site}' "
                    f"from client_id={existing_client_id}, user_id={existing_user_id}, username={existing_username} "
                    f"to client_id={client_id}, user_id={user_id}, username={username}"
                )
            else:
                info(f"MySQL: existing mapping for '{site}' -> client_id={client_id}, user_id={user_id}, username={username}")
        else:
            info(f"MySQL: registered '{site}' -> client_id={client_id}, user_id={user_id}, role_id={role_id}, username={username}")

        cur.close()
        conn.close()
        return client_id, user_id
    except Exception as e:
        conn.rollback()
        err(f"MySQL registration failed for '{site}': {e}")
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
        sys.exit(13)

def ping_backend_login(quiet: bool = False) -> bool:
    # Hit backend /user/role to initialize DB/tables. Returns True on HTTP 200.
    # quiet=True suppresses the per-attempt info/warn output (for retry pollers that
    # report their own aggregate outcome).
    base = os.environ.get("DUALITY_BACKEND_URL", "http://localhost:8000")
    url = f"{base.rstrip('/')}/user/role"
    # "initiator" is seeded by the backend; an unknown username makes /user/role 404.
    payload = {"username": "initiator"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                if not quiet:
                    info(f"Backend /user/role call succeeded ({url})")
                return True
            if not quiet:
                warn(f"Backend /user/role returned status {resp.status}")
            return False
    except Exception as e:
        if not quiet:
            warn(f"Could not contact backend at {url}. Try backend rebuild\nError status: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Create and run a Duality NVFLARE client via docker-compose.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--site", help="Site name (e.g., site1, site2) when building/running or --tar-kit.", type=str)
    g.add_argument("--tar-file", type=str, help="Path to an existing client_<site>_startup_kit.tar")
    parser.add_argument("--env-file", default=None, help="Optional path to env file (defaults to repo .env.local if present)")
    parser.add_argument("--tar-kit", action="store_true", help="Only create the client startup kit tar and exit")
    parser.add_argument("--compose-file", default=str(THIS_DIR / "docker-compose.client-template.yml"), help="Compose TEMPLATE path")
    parser.add_argument(
        "--project",
        default="duality-client",
        help="Compose project name to group client build/run resources (default: duality-client)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the build cache for the selected client and, when applicable, its results-agent image",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the selected site's NVFLARE client and any companion results-agent container, then exit",
    )
    args = parser.parse_args()

    if args.tar_kit and not args.site:
        err("--tar-kit requires --site and cannot be used with --tar-file.")
        sys.exit(1)
    if args.tar_kit and args.tar_file:
        err("--tar-kit cannot be combined with --tar-file.")
        sys.exit(1)

    load_env(Path(args.env_file) if args.env_file else None)
    check_docker()

    if args.stop:
        if not args.site:
            err("--stop requires --site and cannot be used with --tar-file.")
            sys.exit(1)
        stop_site_containers(args.site)
        return

    workspace = Path(os.environ.get("DUALITY_NVFLARE_WORKSPACE", REPO_ROOT / "nvflare_workspace"))

    # Build or select the client kit tar
    if args.site:
        site = args.site
        client_dir = find_participant_dir(workspace, site)
        if not client_dir:
            err(f"Could not find client folder for '{site}' under workspace: {workspace}")
            sys.exit(6)
        dist_dir = REPO_ROOT / "dist"
        client_tar = dist_dir / f"client_{site}_startup_kit.tar"
        if args.tar_kit:
            tar_client_kit(client_dir, client_tar)
            info(f"Tar created at {client_tar}")
            if ask_yes_no(
                "Also create/ensure a client entry in MySQL so this site can receive broadcasted jobs?",
                default=True
            ):
                _client_id, user_id = ensure_client_registered(site)
                ensure_user_datasources(site, user_id)
                info("Database entry created/ensured.")
            else:
                info("Skipped creating DB entry. You can add it later via `python3 main.py clientdb --site <name>`.")
            return
        tar_client_kit(client_dir, client_tar)
    else:
        client_tar = Path(args.tar_file).expanduser().resolve()
        if not client_tar.exists():
            err(f"Tar file not found: {client_tar}")
            sys.exit(8)
        site = infer_site_from_tar(client_tar)
        if not site:
            err("Unable to infer site from tar filename. Expected 'client_siteX_startup_kit.tar'")
            sys.exit(9)

    project_sources = collect_datasources_for_site(site)

    # Sanity checks
    if not (THIS_DIR / "client.Dockerfile").exists():
        err("client_utils/client.Dockerfile is missing")
        sys.exit(10)
    if not (THIS_DIR / "docker-compose.client-template.yml").exists():
        err("client_utils/docker-compose.client-template.yml is missing")
        sys.exit(11)
    is_initiator_site = site.strip().lower() == "site3"
    if not is_initiator_site and not (THIS_DIR / "client-results-agent" / "Dockerfile").exists():
        err("client_utils/client-results-agent/Dockerfile is missing")
        sys.exit(12)

    # Ensure DB tables exist and register this client
    ping_backend_login()
    _client_id, user_id = ensure_client_registered(site)
    ensure_user_datasources(site, user_id)

    # Stage selected local datasource files into the Docker build context so they land inside the image.
    stage_local_datasources_for_build(site, project_sources)
    stage_local_wheel_for_build()

    # Keep site3 on the existing shared initiator path because the local backend may
    # already mount REPO_ROOT/job-results for initiator-side retrieval. Other simulated
    # clients get isolated subdirectories so the same job/workflow IDs cannot overwrite
    # one another's local_results.json files.
    results_root = (REPO_ROOT / "job-results").resolve()
    job_results_dir = results_root if is_initiator_site else results_root / site
    job_results_dir.mkdir(parents=True, exist_ok=True)
    client_results_port = None if is_initiator_site else get_site_results_port(site)

    # Compose-time environment for variable substitution inside docker-compose.client-template.yml.
    # Compose interpolates the entire template even when site3 starts only the client
    # service, so give the unused results-agent port expression a valid placeholder.
    env = dict(DEF_ENV)
    env.update({
        "SITE": site,
        "CLIENT_TAR": str(client_tar.resolve()),
        "JOB_RESULTS_DIR": str(job_results_dir),
        "CLIENT_JOB_SAVE_LOCATION": "/job-results",
        "ENABLE_JOB_RESULTS_SYMLINK": "true",
        "CLIENT_RESULTS_PORT": str(client_results_port if client_results_port is not None else 8088),
        "DUALITY_UI_ORIGINS": os.environ.get("DUALITY_UI_ORIGINS", ""),
    })

    base_compose = Path(args.compose_file).resolve()
    temp_compose = render_compose_for_site_temp(base_compose, site)

    project = args.project
    compose_services = [f"client-{site}"]
    if not is_initiator_site:
        compose_services.append(f"results-agent-{site}")

    info(f"Using compose project: {project} (services: {', '.join(compose_services)})")
    # This also removes a stale site3 results-agent left by an older launcher version.
    remove_existing_site_containers(site)

    cmd = [
        "docker", "compose", "-p", project, "-f", str(temp_compose),
        "up", "-d", "--build", *compose_services,
    ]

    try:
        # `docker compose up --build` has no --no-cache; that option lives on
        # `build`. So when requested, do a cache-busting build first, then up.
        if getattr(args, "no_cache", False):
            build_cmd = [
                "docker", "compose", "-p", project, "-f", str(temp_compose),
                "build", "--no-cache", *compose_services,
            ]
            info("$ " + " ".join(build_cmd))
            subprocess.run(build_cmd, env=env, check=True)
        info("$ " + " ".join(cmd))
        subprocess.run(cmd, env=env, check=True)
        copy_site3_model_files(site)

        if is_initiator_site:
            info(
                f"Initiator client '{site}' is running.\n"
                f"  NVFLARE logs: docker logs -f duality-client-{site}\n"
                f"  Results directory: {job_results_dir}\n"
                "  Results are served by the existing backend; no companion results-agent was started."
            )
        else:
            info(
                f"Client '{site}' is running.\n"
                f"  NVFLARE logs: docker logs -f duality-client-{site}\n"
                f"  Results API logs: docker logs -f duality-client-results-{site}\n"
                f"  Results API: http://127.0.0.1:{client_results_port}"
            )
    finally:
        cleanup_runtime_artifacts(temp_compose)

if __name__ == "__main__":
    main()
