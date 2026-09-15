from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from share_desktop.services.authentication import AuthenticationService, UserSession


class LoginWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: AuthenticationService,
        username: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.username = username

    def run(self) -> None:
        try:
            session: UserSession = self.service.login(self.username)
            self.completed.emit(session)
        except Exception as exc:
            self.failed.emit(str(exc))
