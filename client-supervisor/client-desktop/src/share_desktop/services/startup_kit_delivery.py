from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from share_desktop.paths import INBOX_DIR
from share_desktop.runners.startup_kit import validate_startup_tar

ProgressCallback = Callable[[int, int], None]
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StartupKitDownloadResult:
    archive_path: Path
    sha256: str
    size_bytes: int


class StartupKitDeliveryService:
    def __init__(
        self,
        api_base_url: str,
        startup_kit_path: str,
        timeout_seconds: int = 300,
        inbox_dir: Path = INBOX_DIR,
    ) -> None:
        self.api_base_url = api_base_url.strip().rstrip("/")
        self.startup_kit_path = "/" + startup_kit_path.strip().lstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.inbox_dir = inbox_dir.expanduser().resolve()

    @property
    def endpoint_url(self) -> str:
        if not self.api_base_url:
            raise RuntimeError("Content-delivery API base URL is not configured.")
        return f"{self.api_base_url}{self.startup_kit_path}"

    def download_startup_kit(
        self,
        client_name: str,
        *,
        progress_callback: ProgressCallback | None = None,
        status_callback: StatusCallback | None = None,
    ) -> StartupKitDownloadResult:
        site = (client_name or "").strip()
        if not site:
            raise RuntimeError("A client site must be selected.")

        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.inbox_dir / f"share-client-{site}-startup-kit.tar.gz"
        partial_path = final_path.with_suffix(final_path.suffix + ".part")
        partial_path.unlink(missing_ok=True)

        if status_callback:
            status_callback(f"Requesting startup kit for {site}…")

        hasher = hashlib.sha256()
        bytes_written = 0
        expected_size = 0

        try:
            with requests.post(
                self.endpoint_url,
                json={"client_name": site},
                stream=True,
                timeout=(15, self.timeout_seconds),
                headers={"Accept": "application/gzip"},
            ) as response:
                if response.status_code >= 400:
                    raise RuntimeError(self._error_message(response))

                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type and content_type not in {
                    "application/gzip",
                    "application/x-gzip",
                    "application/octet-stream",
                }:
                    raise RuntimeError(
                        f"Startup-kit service returned unexpected content type: {content_type}"
                    )

                try:
                    expected_size = max(0, int(response.headers.get("Content-Length", "0") or 0))
                except ValueError:
                    expected_size = 0

                with partial_path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        output.write(chunk)
                        hasher.update(chunk)
                        bytes_written += len(chunk)
                        if progress_callback:
                            progress_callback(bytes_written, expected_size)

                if bytes_written == 0:
                    raise RuntimeError("Startup-kit service returned an empty file.")

                actual_sha256 = hasher.hexdigest()
                expected_sha256 = (
                    response.headers.get("X-SHARE-Artifact-SHA256", "").strip().lower()
                )
                if expected_sha256 and actual_sha256.lower() != expected_sha256:
                    raise RuntimeError(
                        "Startup-kit checksum verification failed. The downloaded file was not installed."
                    )

            if status_callback:
                status_callback("Validating downloaded startup kit…")
            validate_startup_tar(partial_path, expected_site=site)
            os.replace(partial_path, final_path)

            return StartupKitDownloadResult(
                archive_path=final_path,
                sha256=hasher.hexdigest(),
                size_bytes=bytes_written,
            )
        except Exception:
            partial_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("message") or "").strip()
            elif payload:
                detail = str(payload).strip()
        except (ValueError, json.JSONDecodeError):
            detail = response.text.strip()[:500]

        if not detail:
            detail = response.reason or "Request failed"
        return f"Startup-kit download failed ({response.status_code}): {detail}"
