from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from share_desktop.runners.startup_kit import install_startup_tar
from share_desktop.services.startup_kit_delivery import StartupKitDeliveryService


class StartupKitProvisionWorker(QThread):
    progress_changed = Signal(int, int)
    status_changed = Signal(str)
    completed = Signal(str, str, str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        service: StartupKitDeliveryService,
        site: str,
        destination_base: Path,
        replace_existing: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.site = site
        self.destination_base = destination_base
        self.replace_existing = replace_existing

    def run(self) -> None:
        try:
            download = self.service.download_startup_kit(
                self.site,
                progress_callback=self.progress_changed.emit,
                status_callback=self.status_changed.emit,
            )
            self.status_changed.emit("Installing startup kit…")
            install = install_startup_tar(
                download.archive_path,
                self.destination_base,
                expected_site=self.site,
                replace_existing=self.replace_existing,
            )
            backup = str(install.backup_workspace) if install.backup_workspace else ""
            self.completed.emit(
                str(download.archive_path),
                str(install.workspace),
                backup,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
