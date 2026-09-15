"""Build downloadable archives from site-specific NVFlare workspace folders."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import posixpath
import re
import shlex
import tarfile
import tempfile
from typing import Optional
import uuid

from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.nvflare.NVFlareServerProvider import NVFlareProvisionProvider
from app.core.ssh.SSHConnectionProvider import SSHConnectionProvider


_CLIENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_DIRECTORY_MODE = 0o755
_EXECUTABLE_SCRIPT_MODE = 0o755
_REGULAR_FILE_MODE = 0o644
_REMOTE_ARCHIVE_TIMEOUT_SECONDS = 600
_REMOTE_VALIDATION_TIMEOUT_SECONDS = 30
_REMOTE_CLEANUP_TIMEOUT_SECONDS = 30


class ClientStartupKitDeliveryError(RuntimeError):
    """Base exception for startup-kit packaging failures."""


class InvalidClientNameError(ClientStartupKitDeliveryError):
    """Raised when a requested client name cannot safely identify a site folder."""


class ClientSiteNotFoundError(ClientStartupKitDeliveryError):
    """Raised when the requested client site folder does not exist."""


class InvalidClientSiteError(ClientStartupKitDeliveryError):
    """Raised when a site folder does not look like an NVFlare startup kit."""


@dataclass
class ClientStartupKitArtifact:
    """Temporary archive and response metadata returned by the delivery service."""

    path: Path
    download_filename: str
    sha256: str
    size_bytes: int

    def cleanup(self) -> None:
        """Remove the temporary archive after the HTTP response is complete."""
        self.path.unlink(missing_ok=True)


class ClientStartupKitDeliveryService:
    """Package a local or remote client workspace folder as a temporary tar.gz."""

    def create_archive(self, client_name: str) -> ClientStartupKitArtifact:
        normalized_client_name = self._validate_client_name(client_name)

        if EnvironmentProvider.get_env() == Environment.LOCAL:
            return self._create_local_archive(normalized_client_name)

        return self._create_remote_archive(normalized_client_name)

    def _create_local_archive(self, client_name: str) -> ClientStartupKitArtifact:
        workspace_root = self._resolve_workspace_root()
        site_path = self._resolve_site_path(workspace_root, client_name)
        self._validate_site_folder(site_path, client_name)

        archive_path: Optional[Path] = None
        try:
            archive_path = self._create_temp_archive_path(client_name)
            normalize_permissions = self._permissions_are_flattened(site_path)

            with tarfile.open(archive_path, mode="w:gz") as archive:
                archive.add(
                    site_path,
                    arcname=client_name,
                    recursive=True,
                    filter=lambda member: self._archive_filter(
                        member,
                        normalize_permissions=normalize_permissions,
                    ),
                )

            return self._build_artifact(archive_path, client_name)
        except Exception:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)
            raise

    def _create_remote_archive(self, client_name: str) -> ClientStartupKitArtifact:
        """Create the archive on the NVFlare EC2 host and download it over SFTP.

        The EC2 host keeps one stable archive per site at
        ``<workspace>/tar_files/<site>.tar.gz``. Each request first builds a
        unique temporary archive, atomically replaces the stable archive with
        a hard link to those exact bytes, then downloads the unique temporary
        path. This prevents partial published archives and keeps concurrent
        requests from downloading one another's temporary files.
        """
        provision = NVFlareProvisionProvider.get_nvflare_instance()
        workspace_root = str(provision.base_location or "").rstrip("/")
        if not workspace_root:
            raise ClientStartupKitDeliveryError(
                "The configured NVFlare workspace is unavailable"
            )

        remote_archive_dir = posixpath.join(workspace_root, "tar_files")
        remote_final_archive = posixpath.join(
            remote_archive_dir,
            f"{client_name}.tar.gz",
        )
        request_token = uuid.uuid4().hex
        remote_temp_archive = posixpath.join(
            remote_archive_dir,
            f".{client_name}.{request_token}.tar.gz.tmp",
        )
        remote_publish_link = posixpath.join(
            remote_archive_dir,
            f".{client_name}.{request_token}.tar.gz.publish",
        )

        ssh = None
        local_archive: Optional[Path] = None
        try:
            ssh = SSHConnectionProvider.get_instance()
            self._validate_remote_site(
                ssh=ssh,
                workspace_root=workspace_root,
                client_name=client_name,
            )

            archive_command = self._build_remote_archive_command(
                workspace_root=workspace_root,
                client_name=client_name,
                remote_archive_dir=remote_archive_dir,
                remote_temp_archive=remote_temp_archive,
                remote_publish_link=remote_publish_link,
                remote_final_archive=remote_final_archive,
            )
            exit_code, _, stderr = ssh.run(
                archive_command,
                timeout=_REMOTE_ARCHIVE_TIMEOUT_SECONDS,
            )
            if exit_code != 0:
                logging.error(
                    "Remote startup-kit archive creation failed for %s: %s",
                    client_name,
                    stderr.strip(),
                )
                raise ClientStartupKitDeliveryError(
                    "The remote startup-kit archive could not be created"
                )

            local_archive = self._create_temp_archive_path(client_name)
            try:
                ssh.download(
                    remote_temp_archive,
                    str(local_archive),
                    retries=2,
                )
            except Exception as exc:
                raise ClientStartupKitDeliveryError(
                    "The remote startup-kit archive could not be downloaded"
                ) from exc

            if not local_archive.is_file() or local_archive.stat().st_size <= 0:
                raise ClientStartupKitDeliveryError(
                    "The downloaded startup-kit archive is empty"
                )

            return self._build_artifact(local_archive, client_name)
        except Exception:
            if local_archive is not None:
                local_archive.unlink(missing_ok=True)
            raise
        finally:
            if ssh is not None:
                cleanup_command = self._build_remote_cleanup_command(
                    remote_temp_archive,
                    remote_publish_link,
                )
                cleanup_code, _, cleanup_error = ssh.run(
                    cleanup_command,
                    timeout=_REMOTE_CLEANUP_TIMEOUT_SECONDS,
                )
                if cleanup_code != 0:
                    logging.warning(
                        "Unable to remove temporary remote startup-kit files for %s: %s",
                        client_name,
                        cleanup_error.strip(),
                    )

    @staticmethod
    def _validate_client_name(client_name: str) -> str:
        normalized = str(client_name or "").strip()
        if not _CLIENT_NAME_PATTERN.fullmatch(normalized):
            raise InvalidClientNameError(
                "client_name must contain only letters, numbers, periods, underscores, or hyphens"
            )
        return normalized

    @staticmethod
    def _resolve_workspace_root() -> Path:
        provision = NVFlareProvisionProvider.get_nvflare_instance()
        workspace_root = Path(provision.base_location).expanduser().resolve()
        if not workspace_root.is_dir():
            raise ClientStartupKitDeliveryError(
                "The configured NVFlare workspace is unavailable"
            )
        return workspace_root

    @staticmethod
    def _resolve_site_path(workspace_root: Path, client_name: str) -> Path:
        site_path = (workspace_root / client_name).resolve()

        # Client sites must be direct children of the configured workspace.
        if site_path.parent != workspace_root:
            raise InvalidClientNameError("client_name does not resolve to a valid site folder")

        return site_path

    @staticmethod
    def _validate_site_folder(site_path: Path, client_name: str) -> None:
        if not site_path.is_dir():
            raise ClientSiteNotFoundError(
                f"No startup kit was found for client site [{client_name}]"
            )

        startup_path = site_path / "startup"
        if not startup_path.is_dir():
            raise InvalidClientSiteError(
                f"Client site [{client_name}] does not contain an NVFlare startup folder"
            )

    @staticmethod
    def _validate_remote_site(
        *,
        ssh: SSHConnectionProvider,
        workspace_root: str,
        client_name: str,
    ) -> None:
        remote_site = posixpath.join(workspace_root, client_name)
        remote_startup = posixpath.join(remote_site, "startup")
        command = (
            f"if [ ! -d {shlex.quote(workspace_root)} ]; then "
            "printf 'WORKSPACE_MISSING'; "
            f"elif [ ! -d {shlex.quote(remote_site)} ]; then "
            "printf 'SITE_MISSING'; "
            f"elif [ ! -d {shlex.quote(remote_startup)} ]; then "
            "printf 'STARTUP_MISSING'; "
            "else printf 'OK'; fi"
        )

        exit_code, stdout, stderr = ssh.run(
            command,
            timeout=_REMOTE_VALIDATION_TIMEOUT_SECONDS,
        )
        if exit_code != 0:
            logging.error(
                "Unable to validate remote startup-kit workspace for %s: %s",
                client_name,
                stderr.strip(),
            )
            raise ClientStartupKitDeliveryError(
                "The configured NVFlare workspace could not be accessed"
            )

        validation_result = stdout.strip()
        if validation_result == "WORKSPACE_MISSING":
            raise ClientStartupKitDeliveryError(
                "The configured NVFlare workspace is unavailable"
            )
        if validation_result == "SITE_MISSING":
            raise ClientSiteNotFoundError(
                f"No startup kit was found for client site [{client_name}]"
            )
        if validation_result == "STARTUP_MISSING":
            raise InvalidClientSiteError(
                f"Client site [{client_name}] does not contain an NVFlare startup folder"
            )
        if validation_result != "OK":
            raise ClientStartupKitDeliveryError(
                "The remote startup-kit workspace returned an unexpected validation result"
            )

    @staticmethod
    def _build_remote_archive_command(
        *,
        workspace_root: str,
        client_name: str,
        remote_archive_dir: str,
        remote_temp_archive: str,
        remote_publish_link: str,
        remote_final_archive: str,
    ) -> str:
        quote = shlex.quote
        cleanup_paths = f"{quote(remote_temp_archive)} {quote(remote_publish_link)}"
        return (
            "set -eu; "
            f"mkdir -p {quote(remote_archive_dir)}; "
            f"rm -f {cleanup_paths}; "
            "if ! tar "
            "--exclude='*/__pycache__' "
            "--exclude='*.pyc' "
            "--exclude='*.pyo' "
            f"-czpf {quote(remote_temp_archive)} "
            f"-C {quote(workspace_root)} {quote(client_name)}; then "
            f"rm -f {cleanup_paths}; exit 1; fi; "
            f"if ! ln {quote(remote_temp_archive)} {quote(remote_publish_link)}; then "
            f"rm -f {cleanup_paths}; exit 1; fi; "
            f"if ! mv -f {quote(remote_publish_link)} {quote(remote_final_archive)}; then "
            f"rm -f {cleanup_paths}; exit 1; fi"
        )

    @staticmethod
    def _build_remote_cleanup_command(*remote_paths: str) -> str:
        quoted_paths = " ".join(shlex.quote(path) for path in remote_paths)
        return f"rm -f {quoted_paths}"

    @staticmethod
    def _create_temp_archive_path(client_name: str) -> Path:
        temp_file = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f"share-client-{client_name}-",
            suffix=".tar.gz",
            delete=False,
        )
        temp_file.close()
        return Path(temp_file.name)

    @classmethod
    def _build_artifact(
        cls,
        archive_path: Path,
        client_name: str,
    ) -> ClientStartupKitArtifact:
        return ClientStartupKitArtifact(
            path=archive_path,
            download_filename=f"share-client-{client_name}-startup-kit.tar.gz",
            sha256=cls._sha256(archive_path),
            size_bytes=archive_path.stat().st_size,
        )

    @staticmethod
    def _permissions_are_flattened(site_path: Path) -> bool:
        """Detect Docker Desktop mounts that expose every entry as 0777.

        On a normal Linux/macOS filesystem, preserve the source modes exactly.
        When every non-symlink entry is 0777, treat the permissions as a
        Windows bind-mount artifact and apply the known-working startup-kit
        mode pattern while creating the archive.
        """
        entries = [site_path, *site_path.rglob("*")]
        relevant_entries = [entry for entry in entries if not entry.is_symlink()]
        return bool(relevant_entries) and all(
            (entry.stat().st_mode & 0o777) == 0o777
            for entry in relevant_entries
        )

    @staticmethod
    def _archive_filter(
        member: tarfile.TarInfo,
        *,
        normalize_permissions: bool,
    ) -> Optional[tarfile.TarInfo]:
        """Exclude cache artifacts and preserve or repair POSIX modes.

        Normal Linux/macOS source permissions are retained. Docker Desktop
        bind mounts can expose every Windows-hosted entry to the Linux backend
        container as 0777; only in that flattened case are modes repaired to
        match the known-working NVFlare startup-kit tar pattern:

        * directories: 0755
        * shell scripts: 0755
        * other regular files: 0644

        Non-regular entries such as symbolic links retain their entry type and
        metadata.
        """
        member_path = Path(member.name)
        path_parts = member_path.parts
        if "__pycache__" in path_parts:
            return None
        if member_path.suffix.lower() in _EXCLUDED_SUFFIXES:
            return None

        if normalize_permissions:
            if member.isdir():
                member.mode = _DIRECTORY_MODE
            elif member.isfile():
                member.mode = (
                    _EXECUTABLE_SCRIPT_MODE
                    if member_path.suffix.lower() == ".sh"
                    else _REGULAR_FILE_MODE
                )

        return member

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as archive_file:
            for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
