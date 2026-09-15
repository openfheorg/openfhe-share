from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

PRIMARY_BLUE = "#3F5FFF"
PRIMARY_BLUE_HOVER = "#2F4FCC"
PRIMARY_BLUE_DARK = "#162A90"
PAGE_BG = "#F9F9F9"
PANEL_BG = "#FFFFFF"
TEXT = "#212121"
MUTED = "#666666"
BORDER = "#E0E0E0"
BORDER_DARK = "#CCCCCC"
FOCUS_RING = "rgba(63, 95, 255, 0.20)"
SECONDARY_GREEN = "#6AE68B"
SECONDARY_GREEN_HOVER = "#5AD07A"
WARNING = "#F59E0B"
WARNING_HOVER = "#D97706"
DANGER = "#DC2626"
DANGER_HOVER = "#B91C1C"
LOG_BG = "#FFFFFF"
LOG_FG = TEXT


QSS = f"""
* {{
    font-family: "Segoe UI", "Roboto", "Ubuntu", "Arial", sans-serif;
    color: {TEXT};
    font-size: 11pt;
    font-weight: 400;
}}

QMainWindow {{
    background: {PAGE_BG};
}}

QWidget#mainRoot {{
    background: {PAGE_BG};
}}

QFrame#appHeader {{
    background: #FFFFFF;
    border: none;
    border-bottom: 1px solid {BORDER};
}}

QLabel#headerLogo, QWidget#headerAccount {{
    background: transparent;
}}

QLabel#headerUser {{
    color: {TEXT};
    font-size: 13pt;
    font-weight: 400;
}}

QToolButton#accountMenuButton {{
    background: #FFFFFF;
    color: #111111;
    border: 2px solid #1F1F1F;
    border-radius: 6px;
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    padding: 0;
}}

QToolButton#accountMenuButton:hover,
QToolButton#accountMenuButton:pressed,
QToolButton#accountMenuButton:checked {{
    background: #F7F7F7;
}}

QToolButton#accountMenuButton::menu-indicator {{
    image: none;
    width: 0;
}}

QMenu#accountMenu {{
    background: #FFFFFF;
    color: #202044;
    border: 1px solid {BORDER_DARK};
    padding: 8px 0;
}}

QMenu#accountMenu::item {{
    background: transparent;
    color: #202044;
    padding: 11px 34px;
    font-size: 12pt;
    font-weight: 700;
}}

QMenu#accountMenu::item:selected {{
    background: #F3F4F8;
}}

QWidget#loginPage {{
    background: {PAGE_BG};
}}

QFrame#loginPanel {{
    background: #FFFFFF;
    border: 1px solid {BORDER_DARK};
    border-radius: 8px;
}}

QLabel#loginTitle {{
    color: {PRIMARY_BLUE};
    font-size: 25px;
    font-weight: 700;
}}

QLabel#loginFieldLabel {{
    color: {TEXT};
    font-size: 12pt;
    font-weight: 400;
}}

QLineEdit#loginUsername, QLineEdit#loginPassword {{
    min-height: 36px;
    font-size: 12pt;
    border-radius: 7px;
}}

QPushButton#loginSubmit {{
    min-width: 360px;
    min-height: 36px;
    font-size: 12pt;
}}

QLabel#loginNote {{
    color: {TEXT};
    font-size: 11pt;
    line-height: 1.35;
}}

QLabel#loginError {{
    color: {DANGER};
    background: #FEF2F2;
    border: 1px solid #FCA5A5;
    border-radius: 4px;
    padding: 7px 9px;
    font-weight: 600;
}}

QWidget#contentShell {{
    background: {PAGE_BG};
}}

QWidget[page="true"] {{
    background: {PANEL_BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}

QScrollArea#settingsScrollArea, QScrollArea#overviewScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea#settingsScrollArea > QWidget > QWidget,
QScrollArea#overviewScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: #F3F4F6;
    border: 1px solid {BORDER_DARK};
    border-radius: 4px;
    width: 14px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: #9CA3AF;
    border: 1px solid #6B7280;
    border-radius: 4px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: #6B7280;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    border: none;
    background: transparent;
}}

QScrollBar:horizontal {{
    background: #F3F4F6;
    border: 1px solid {BORDER_DARK};
    border-radius: 4px;
    height: 14px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: #9CA3AF;
    border: 1px solid #6B7280;
    border-radius: 4px;
    min-width: 28px;
}}

QScrollBar::handle:horizontal:hover {{
    background: #6B7280;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    border: none;
    background: transparent;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

QLabel[role="pageTitle"] {{
    color: {PRIMARY_BLUE};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.2px;
}}

QLabel[role="sectionTitle"] {{
    color: {PRIMARY_BLUE};
    font-size: 19px;
    font-weight: 700;
    letter-spacing: -0.1px;
}}

QLabel[role="muted"] {{
    color: {MUTED};
}}

QLabel[role="path"] {{
    color: #374151;
    background: #F9FAFB;
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 6px;
}}

QWidget#sidebar {{
    background: {PAGE_BG};
    border: none;
    border-radius: 0;
}}

QPushButton#navButton[nav="true"] {{
    background: transparent;
    border: none;
    color: #333333;
    font-size: 12pt;
    font-weight: 400;
    text-align: left;
    padding: 4px 8px;
    min-height: 26px;
    margin: 0;
}}

QPushButton#navButton[nav="true"]:hover {{
    background: transparent;
    color: {PRIMARY_BLUE};
    font-weight: 700;
}}

QPushButton#navButton[nav="true"][selected="true"] {{
    background: transparent;
    color: #212121;
    font-weight: 700;
}}

QPushButton#navButton[nav="true"][selected="true"]:hover {{
    background: transparent;
    color: #212121;
    font-weight: 700;
}}

QFrame#serviceCard {{
    background: {PANEL_BG};
    border: 1px solid {BORDER_DARK};
    border-radius: 4px;
    padding: 8px;
}}

QFrame#serviceCard[state="healthy"], QFrame#serviceCard[state="running"] {{
    border-color: #C7F3D3;
}}

QFrame#serviceCard[state="attention"] {{
    border-color: #FACC15;
}}

QFrame#serviceCard[state="error"] {{
    border-color: #FCA5A5;
}}

QLabel#cardTitle {{
    color: {PRIMARY_BLUE};
    font-weight: 700;
    font-size: 14px;
}}

QLabel#cardStatus[state="healthy"], QLabel#cardStatus[state="running"] {{
    color: #15803D;
    font-weight: 700;
}}

QLabel#cardStatus[state="attention"] {{
    color: #B45309;
    font-weight: 700;
}}

QLabel#cardStatus[state="error"] {{
    color: {DANGER};
    font-weight: 700;
}}

QLabel#cardDetail {{
    color: #4B5563;
}}

QPushButton {{
    background: {PRIMARY_BLUE};
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 7px 12px;
    font-size: 10.5pt;
    font-weight: 500;
    min-height: 28px;
}}

QPushButton:hover {{
    background: {PRIMARY_BLUE_HOVER};
}}

QPushButton:pressed {{
    padding-top: 8px;
    padding-bottom: 6px;
}}

QPushButton:disabled {{
    background: #CCCCCC;
    color: #666666;
}}

QPushButton[role="secondary"] {{
    background: {SECONDARY_GREEN};
    color: {TEXT};
}}

QPushButton[role="secondary"]:hover {{
    background: {SECONDARY_GREEN_HOVER};
}}

QPushButton[role="neutral"] {{
    background: #FFFFFF;
    color: {PRIMARY_BLUE};
    border: 1px solid {PRIMARY_BLUE};
}}

QPushButton[role="neutral"]:hover {{
    background: rgba(63, 95, 255, 0.06);
}}

QPushButton[role="warning"] {{
    background: {WARNING};
    color: #FFFFFF;
}}

QPushButton[role="warning"]:hover {{
    background: {WARNING_HOVER};
}}

QPushButton[role="danger"] {{
    background: {DANGER};
    color: #FFFFFF;
}}

QPushButton[role="danger"]:hover {{
    background: {DANGER_HOVER};
}}

QPushButton[role="small"] {{
    padding: 4px 8px;
    min-height: 22px;
    font-size: 9pt;
}}

QPushButton[role="link"] {{
    background: transparent;
    color: {PRIMARY_BLUE};
    border: none;
    border-radius: 0;
    padding: 0;
    min-height: 18px;
    font-size: 10.5pt;
    font-weight: 600;
    text-align: left;
}}

QPushButton[role="link"]:hover {{
    background: transparent;
    color: {PRIMARY_BLUE_HOVER};
    text-decoration: underline;
}}

QTreeWidget#jobResultsTree {{
    background: #FFFFFF;
    border: 1px solid {BORDER_DARK};
    border-radius: 4px;
    alternate-background-color: #F3F4F6;
    selection-background-color: rgba(63, 95, 255, 0.12);
    selection-color: {TEXT};
}}

QTreeWidget#jobResultsTree::item {{
    min-height: 24px;
    padding: 2px 4px;
}}

QTreeWidget#jobResultsTree::item:selected {{
    background: rgba(63, 95, 255, 0.12);
    color: {TEXT};
}}

QHeaderView::section {{
    background: #FFFFFF;
    color: {TEXT};
    border: 1px solid {BORDER_DARK};
    padding: 4px 6px;
    font-weight: 600;
}}


QProgressBar {{
    background: #F3F4F6;
    border: 1px solid {BORDER_DARK};
    border-radius: 4px;
    min-height: 20px;
    text-align: center;
}}

QProgressBar::chunk {{
    background: {PRIMARY_BLUE};
    border-radius: 3px;
}}

QComboBox, QLineEdit, QTextEdit, QPlainTextEdit {{
    background: #FFFFFF;
    border: 1px solid #B4B4B4;
    border-radius: 6px;
    padding: 5px 7px;
    min-height: 28px;
    selection-background-color: {PRIMARY_BLUE};
}}

QComboBox:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {PRIMARY_BLUE};
}}

QComboBox::drop-down {{
    width: 24px;
    border-left: 1px solid {BORDER};
}}

QPlainTextEdit#logText {{
    background: {LOG_BG};
    color: {LOG_FG};
    border: 1px solid {BORDER_DARK};
    border-radius: 4px;
    padding: 8px;
    selection-background-color: rgba(63, 95, 255, 0.20);
    selection-color: {TEXT};
}}

QWidget#logConsole {{
    background: transparent;
}}

QFormLayout QLabel {{
    color: #374151;
}}

QMessageBox {{
    background: {PAGE_BG};
}}
"""


def set_role(widget: QWidget, role: str) -> None:
    widget.setProperty("role", role)
    _refresh_widget_style(widget)


def set_state(widget: QWidget, state: str) -> None:
    widget.setProperty("state", state)
    _refresh_widget_style(widget)


def _refresh_widget_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_share_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    share_font = QFont()
    # Match the web app declaration as closely as Qt allows. Qt will use the
    # first installed family from this ordered list on the current OS.
    try:
        share_font.setFamilies(["Segoe UI", "Roboto", "Ubuntu", "Arial", "sans-serif"])
    except AttributeError:
        share_font.setFamily("Segoe UI")
    share_font.setPointSize(11)
    share_font.setWeight(QFont.Weight.Normal)
    app.setFont(share_font)
    app.setStyleSheet(QSS)
