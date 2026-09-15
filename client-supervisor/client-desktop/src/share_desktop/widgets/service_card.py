from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from share_desktop.theme import set_state


class ServiceCard(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("serviceCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.status = QLabel("Not started")
        self.status.setObjectName("cardStatus")
        self.detail = QLabel("-")
        self.detail.setObjectName("cardDetail")
        self.detail.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addWidget(self.detail)

    def set_state(self, label: str, detail: str = "") -> None:
        self.status.setText(label)
        if detail:
            self.detail.setText(detail)
        state = self._classify_state(label)
        set_state(self, state)
        set_state(self.status, state)

    @staticmethod
    def _classify_state(label: str) -> str:
        text = (label or "").lower()
        if "healthy" in text or "ready" in text or "running" in text:
            return "healthy" if "healthy" in text or "ready" in text else "running"
        if "error" in text or "unhealthy" in text or "failed" in text or "missing" in text:
            return "error"
        if "starting" in text or "building" in text or "stopping" in text or "selected" in text:
            return "attention"
        return "neutral"
