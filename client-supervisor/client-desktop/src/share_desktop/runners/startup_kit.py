from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from share_desktop.paths import INBOX_DIR, WORKSPACES_DIR


@dataclass(frozen=True)
class StartupKitInstallResult:
    workspace: Path
    backup_workspace: Path | None = None


def discover_startup_tars(repo_root: Path) -> list[Path]:
    # ``repo_root`` is retained for caller compatibility. Startup-kit archives
    # are now delivered by the backend and cached only in the managed inbox;
    # the former repo tar_files directories no longer exist.
    _ = repo_root
    candidates: list[Path] = []
    if INBOX_DIR.exists():
        candidates.extend(sorted(INBOX_DIR.glob("*.tar.gz")))
        candidates.extend(sorted(INBOX_DIR.glob("*.tgz")))
        candidates.extend(sorted(INBOX_DIR.glob("*.tar")))
    # Preserve order but dedupe.
    seen: set[Path] = set()
    out: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            out.append(resolved)
            seen.add(resolved)
    return out


def _tar_mode(path: Path) -> str:
    # Auto-detection also works for in-progress names such as
    # ``site4.tar.gz.part`` while they are being checksum-validated.
    return "r:*"


def inspect_startup_tar(path: Path) -> tuple[str, bool]:
    path = path.expanduser().resolve()
    with tarfile.open(path, _tar_mode(path)) as archive:
        members = [member for member in archive.getmembers() if member.name and member.name.strip()]
        if not members:
            raise RuntimeError(f"Tar file is empty: {path}")

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

        if not roots:
            raise RuntimeError(f"Could not determine tar root: {path}")
        if len(roots) != 1:
            raise RuntimeError(
                f"Startup-kit archive must contain exactly one top-level site folder; found: {', '.join(roots)}"
            )
        return roots[0], has_start


def validate_startup_tar(path: Path, expected_site: str | None = None) -> str:
    root_name, has_start = inspect_startup_tar(path)
    if expected_site and root_name != expected_site:
        raise RuntimeError(
            f"Downloaded startup kit is for '{root_name}', but '{expected_site}' was requested."
        )
    if not has_start:
        raise RuntimeError(
            f"Tar inspected but no startup/start.sh was found. Root appears to be: {root_name}"
        )
    return root_name


def _safe_members(archive: tarfile.TarFile, destination: Path) -> Iterable[tarfile.TarInfo]:
    destination = destination.resolve()
    for member in archive.getmembers():
        member_name = member.name.replace("\\", "/")
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
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = target.with_name(f"{target.name}.backup-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.backup-{timestamp}-{counter}")
        counter += 1
    return candidate


def install_startup_tar(
    path: Path,
    destination_base: Path = WORKSPACES_DIR,
    *,
    expected_site: str | None = None,
    replace_existing: bool = False,
) -> StartupKitInstallResult:
    """Safely install a startup-kit archive through a staging directory.

    The tar must contain a single top-level site directory and
    ``<site>/startup/start.sh``. Existing workspaces are never overwritten
    silently. When replacement is allowed, the current workspace is renamed to
    a timestamped backup before the staged workspace is moved into place.
    """
    path = path.expanduser().resolve()
    root_name = validate_startup_tar(path, expected_site=expected_site)
    destination_base = destination_base.expanduser().resolve()
    destination_base.mkdir(parents=True, exist_ok=True)

    target_workspace = (destination_base / root_name).resolve()
    if target_workspace.parent != destination_base:
        raise RuntimeError(f"Unsafe startup-kit root folder: {root_name}")
    if target_workspace.exists() and not replace_existing:
        raise FileExistsError(f"Workspace already exists: {target_workspace}")

    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".share-client-{root_name}-install-", dir=str(destination_base))
    ).resolve()
    backup_workspace: Path | None = None

    try:
        with tarfile.open(path, _tar_mode(path)) as archive:
            archive.extractall(staging_dir, members=_safe_members(archive, staging_dir))

        staged_workspace = (staging_dir / root_name).resolve()
        startup_dir = staged_workspace / "startup"
        if not (startup_dir / "start.sh").is_file():
            raise RuntimeError(f"Extracted startup kit but start.sh was not found under: {startup_dir}")

        if target_workspace.exists():
            backup_workspace = _backup_path(target_workspace)
            target_workspace.rename(backup_workspace)

        try:
            staged_workspace.rename(target_workspace)
        except Exception:
            if backup_workspace is not None and backup_workspace.exists() and not target_workspace.exists():
                backup_workspace.rename(target_workspace)
            raise

        (target_workspace / "job-results").mkdir(parents=True, exist_ok=True)
        return StartupKitInstallResult(
            workspace=target_workspace,
            backup_workspace=backup_workspace,
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def extract_startup_tar(path: Path, destination_base: Path = WORKSPACES_DIR) -> Path:
    """Compatibility wrapper for the original phase-1 caller."""
    return install_startup_tar(path, destination_base).workspace
