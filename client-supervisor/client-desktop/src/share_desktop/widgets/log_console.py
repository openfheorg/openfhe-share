from __future__ import annotations

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QLabel

from share_desktop.theme import set_role


class LogConsole(QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("logConsole")
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "pageTitle")
        self.text = QPlainTextEdit()
        self.text.setObjectName("logText")
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        font = QFont("Monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.text.setFont(font)

        self.clear_button = QPushButton("Clear view")
        set_role(self.clear_button, "neutral")
        self.clear_button.clicked.connect(self.text.clear)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.text)

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self.text.moveCursor(QTextCursor.End)
        self.text.insertPlainText(chunk)
        self.text.moveCursor(QTextCursor.End)
