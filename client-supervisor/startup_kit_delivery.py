from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

DEFAULT_CONTENT_API_BASE = "https://api.example.org"
DEFAULT_STARTUP_KIT_PATH = "/clients/content/startup-kit"
SITE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

APP_HOME = Path.home() / ".duality-client"
INBOX_DIR = APP_HOME / "inbox"
# Site workspaces live directly under APP_HOME (for example ~/.duality-client/site1)
# so they persist independently of the client-supervisor source checkout.
WORKSPACE_BASE_DIR = APP_HOME


@dataclass(frozen=True)
class StartupKitInstallResult:
    archive_path: Path
    workspace: Path
    backup_workspace: Path | None = None


def validate_site_name(site: str) -> str:
    normalized = (site or "").strip()
    if not SITE_NAME_PATTERN.fullmatch(normalized):
        raise RuntimeError(
            "Invalid site name. Use a simple NVFlare client name such as site1 or site4."
        )
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("error")
            if detail:
                return str(detail)
    except Exception:
        pass
    return f"HTTP {exc.code} {exc.reason}"


def download_startup_kit(
    site: str,
    *,
    api_base_url: str | None = None,
    startup_kit_path: str | None = None,
    timeout_seconds: int = 300,
    inbox_dir: Path = INBOX_DIR,
) -> Path:
    """Download a site's startup-kit tar from the SHARE backend.

    The response is streamed into a ``.part`` file, verified against the
    backend SHA-256 header when present, and then atomically moved into the
    managed SHARE Client inbox.
    """
    site = validate_site_name(site)
    api_base = (
        api_base_url
        or os.environ.get("DUALITY_CONTENT_API_BASE_URL")
        or os.environ.get("DUALITY_BACKEND_URL")
        or DEFAULT_CONTENT_API_BASE
    ).strip().rstrip("/")
    endpoint_path = (
        startup_kit_path
        or os.environ.get("DUALITY_STARTUP_KIT_PATH")
        or DEFAULT_STARTUP_KIT_PATH
    ).strip()
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"
    url = f"{api_base}{endpoint_path}"

    inbox_dir = inbox_dir.expanduser().resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)
    final_path = inbox_dir / f"share-client-{site}-startup-kit.tar.gz"
    part_path = final_path.with_name(f"{final_path.name}.part")
    part_path.unlink(missing_ok=True)

    payload = json.dumps({"client_name": site}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/gzip"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            expected_sha = (
                response.headers.get("X-SHARE-Artifact-SHA256")
                or response.headers.get("x-share-artifact-sha256")
                or ""
            ).strip().lower()
            with part_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
    except urllib.error.HTTPError as exc:
        part_path.unlink(missing_ok=True)
        raise RuntimeError(f"Startup-kit download failed for {site}: {_error_detail(exc)}") from exc
    except urllib.error.URLError as exc:
        part_path.unlink(missing_ok=True)
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Could not reach the startup-kit service at {url}: {reason}") from exc
    except Exception:
        part_path.unlink(missing_ok=True)
        raise

    if not part_path.exists() or part_path.stat().st_size == 0:
        part_path.unlink(missing_ok=True)
        raise RuntimeError(f"The startup-kit service returned an empty archive for {site}.")

    if expected_sha:
        actual_sha = _sha256(part_path)
        if actual_sha.lower() != expected_sha:
            part_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Startup-kit checksum mismatch for {site}: expected {expected_sha}, got {actual_sha}."
            )

    validate_startup_tar(part_path, expected_site=site)
    os.replace(part_path, final_path)
    return final_path


def inspect_startup_tar(path: Path) -> tuple[str, bool]:
    path = path.expanduser().resolve()
    with tarfile.open(path, "r:*") as archive:
        members = [member for member in archive.getmembers() if (member.name or "").strip()]
        if not members:
            raise RuntimeError(f"Startup-kit archive is empty: {path}")

        roots: list[str] = []
        has_start = False
        for member in members:
            clean = member.name.strip().replace("\\", "/").lstrip("/")
            parts = [part for part in clean.split("/") if part and part != "."]
            if not parts:
                continue
            if parts[0] not in roots:
                roots.append(parts[0])
            if len(parts) >= 2 and parts[-2:] == ["startup", "start.sh"]:
                has_start = True

        if len(roots) != 1:
            found = ", ".join(roots) if roots else "none"
            raise RuntimeError(
                f"Startup-kit archive must contain exactly one top-level site folder; found: {found}"
            )
        return roots[0], has_start


def validate_startup_tar(path: Path, *, expected_site: str | None = None) -> str:
    root_name, has_start = inspect_startup_tar(path)
    if expected_site and root_name != validate_site_name(expected_site):
        raise RuntimeError(
            f"Downloaded startup kit is for '{root_name}', but '{expected_site}' was requested."
        )
    if not has_start:
        raise RuntimeError(
            f"Startup-kit archive does not contain {root_name}/startup/start.sh."
        )
    return root_name


def _safe_members(archive: tarfile.TarFile, destination: Path) -> Iterable[tarfile.TarInfo]:
    destination = destination.resolve()
    for member in archive.getmembers():
        member_name = (member.name or "").replace("\\", "/")
        if member_name.startswith("/"):
            raise RuntimeError(f"Unsafe absolute tar member blocked: {member.name}")
        target = (destination / member_name).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"Unsafe tar member blocked: {member.name}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"Startup-kit links are not allowed: {member.name}")
        if not (member.isdir() or member.isfile()):
            raise RuntimeError(f"Unsupported startup-kit entry type: {member.name}")
        yield member


def _backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = target.with_name(f"{target.name}.backup-{stamp}")
    counter = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.backup-{stamp}-{counter}")
        counter += 1
    return candidate


def install_startup_kit(
    archive_path: Path,
    destination_base: Path | None = None,
    *,
    expected_site: str,
    replace_existing: bool = True,
) -> StartupKitInstallResult:
    """Install a downloaded startup kit through a staging directory.

    Existing workspaces are never overwritten in place. When replacement is
    enabled, the current site folder is renamed to a timestamped backup before
    the staged replacement is moved into place.
    """
    archive_path = archive_path.expanduser().resolve()
    site = validate_startup_tar(archive_path, expected_site=expected_site)
    destination_base = (destination_base or WORKSPACE_BASE_DIR).expanduser().resolve()
    destination_base.mkdir(parents=True, exist_ok=True)

    target = (destination_base / site).resolve()
    if target.parent != destination_base:
        raise RuntimeError(f"Unsafe startup-kit target folder: {target}")
    if target.exists() and not replace_existing:
        raise FileExistsError(f"Workspace already exists: {target}")

    staging = Path(
        tempfile.mkdtemp(prefix=f".share-client-{site}-install-", dir=str(destination_base))
    ).resolve()
    backup: Path | None = None

    try:
        with tarfile.open(archive_path, "r:*") as archive:
            archive.extractall(staging, members=_safe_members(archive, staging))

        staged_workspace = (staging / site).resolve()
        if not (staged_workspace / "startup" / "start.sh").is_file():
            raise RuntimeError(
                f"Extracted startup kit but startup/start.sh was not found under {staged_workspace}."
            )

        if target.exists():
            backup = _backup_path(target)
            target.rename(backup)

        try:
            staged_workspace.rename(target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                backup.rename(target)
            raise

        (target / "job-results").mkdir(parents=True, exist_ok=True)
        return StartupKitInstallResult(
            archive_path=archive_path,
            workspace=target,
            backup_workspace=backup,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
