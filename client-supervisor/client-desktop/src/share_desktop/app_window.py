from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QGraphicsDropShadowEffect,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QSizePolicy,
    QTreeWidget,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from share_desktop.config import DesktopConfig
from share_desktop.icons import (
    brand_logo_path,
    client_icon,
    login_illustration_path,
)
from share_desktop.paths import INBOX_DIR, WORKSPACES_DIR, ensure_app_dirs
from share_desktop.runners.results_api_runner import ResultsApiRunner
from share_desktop.runners.nvflare_runner import NvflareRunner
from share_desktop.runners.startup_kit import (
    discover_startup_tars,
    install_startup_tar,
    validate_startup_tar,
)
from share_desktop.services.authentication import AuthenticationService, UserSession
from share_desktop.services.startup_kit_delivery import StartupKitDeliveryService
from share_desktop.services.share_launch import build_share_launch_url
from share_desktop.state import DesktopState, load_state, save_state
from share_desktop.theme import set_role
from share_desktop.widgets.log_console import LogConsole
from share_desktop.widgets.service_card import ServiceCard
from share_desktop.workers.login_worker import LoginWorker
from share_desktop.workers.startup_kit_worker import StartupKitProvisionWorker


class DualityClientWindow(QMainWindow):
    def __init__(self, repo_root: Path, config: DesktopConfig, initial_env: str | None = None) -> None:
        super().__init__()
        ensure_app_dirs()
        self.repo_root = repo_root
        self.config = config
        self.state: DesktopState = load_state()
        # Deployment defaults remain config-driven. The active client site is
        # assigned only after /user/role succeeds and is never user-selectable.
        self.state.share_url = config.share_url
        self.state.results_port = int(config.results_port)
        if initial_env:
            self.state.env = initial_env
        self.session: UserSession | None = None
        self._login_worker: LoginWorker | None = None
        self._startup_kit_worker: StartupKitProvisionWorker | None = None
        self._clear_workspace_if_it_points_at_old_demo_home()
        self.nvflare = NvflareRunner()
        self.results = ResultsApiRunner(
            repo_root=self.repo_root,
            port=self.state.results_port,
            job_results_dir_name=self.config.job_results_dir_name,
        )
        self.last_nvflare_output_at: datetime | None = None
        self._results_service_active = False
        self._results_health_ok: bool | None = None
        self._last_results_state = ""
        self._setup_window()
        self._connect_runners()
        self._setup_tray()
        self._refresh_tar_choices()
        self._sync_state_to_ui()
        self._start_timers()

    def _setup_window(self) -> None:
        self.setWindowTitle("SHARE Client")
        self.setWindowIcon(client_icon("idle"))
        # Open at a clean demo size but allow resizing smaller on Ubuntu desktops
        # where top bars/docks reduce usable screen height.
        self.setMinimumSize(900, 400)
        self.resize(1024, 768)

        self.global_header = self._build_global_header()
        self.login_page = self._build_login_page()

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(24, 28, 16, 8)
        self.sidebar_layout.setSpacing(16)
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(["Overview", "Job Results", "NVFlare Output", "Results API", "Settings"]):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, row=index: self._set_page(row))
            self.sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
        self.sidebar_layout.addStretch(1)

        self.pages = QStackedWidget()
        self.overview_page = self._build_overview_page()
        self.job_results_page = self._build_job_results_page()
        self.nvflare_page = self._build_nvflare_page()
        self.results_page = self._build_results_page()
        self.settings_page = self._build_settings_page()
        for page in [self.overview_page, self.job_results_page, self.nvflare_page, self.results_page, self.settings_page]:
            self.pages.addWidget(page)

        self.pages_shell = QWidget()
        self.pages_shell.setObjectName("contentShell")
        pages_shell_layout = QVBoxLayout(self.pages_shell)
        # Match the web app's left-nav feel: the main white content card starts
        # a little below the top edge, with only a small gutter beside the nav.
        pages_shell_layout.setContentsMargins(0, 18, 12, 12)
        pages_shell_layout.setSpacing(0)
        pages_shell_layout.addWidget(self.pages, 1)

        self.supervisor_shell = QWidget()
        supervisor_layout = QHBoxLayout(self.supervisor_shell)
        supervisor_layout.setContentsMargins(0, 0, 0, 0)
        supervisor_layout.setSpacing(0)
        supervisor_layout.addWidget(self.sidebar)
        supervisor_layout.addWidget(self.pages_shell, 1)

        self.authenticated_stack = QStackedWidget()
        self.authenticated_stack.setObjectName("authenticatedStack")
        self.authenticated_stack.addWidget(self.login_page)
        self.authenticated_stack.addWidget(self.supervisor_shell)

        root = QWidget()
        root.setObjectName("mainRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.global_header)
        layout.addWidget(self.authenticated_stack, 1)
        self.setCentralWidget(root)
        self._set_page(0)
        self._show_login()

    def _build_global_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("appHeader")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 4, 18, 4)
        layout.setSpacing(12)

        self.header_logo_label = QLabel()
        self.header_logo_label.setObjectName("headerLogo")
        self.header_logo_label.setFixedSize(288, 56)
        logo_pixmap = QPixmap(str(brand_logo_path()))
        if not logo_pixmap.isNull():
            self.header_logo_label.setPixmap(
                logo_pixmap.scaled(280, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.header_logo_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.header_account = QWidget()
        self.header_account.setObjectName("headerAccount")
        account_layout = QHBoxLayout(self.header_account)
        account_layout.setContentsMargins(0, 0, 0, 0)
        account_layout.setSpacing(10)

        self.header_user_label = QLabel("")
        self.header_user_label.setObjectName("headerUser")
        self.header_user_label.setTextFormat(Qt.RichText)
        self.header_user_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.account_menu_button = QToolButton()
        self.account_menu_button.setObjectName("accountMenuButton")
        self.account_menu_button.setArrowType(Qt.DownArrow)
        self.account_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.account_menu_button.setToolTip("Account menu")

        self.account_menu = QMenu(self.account_menu_button)
        self.account_menu.setObjectName("accountMenu")
        self.sign_out_action = QAction("Sign Out", self)
        self.sign_out_action.triggered.connect(self.logout)
        self.account_menu.addAction(self.sign_out_action)
        self.account_menu_button.setMenu(self.account_menu)

        account_layout.addWidget(self.header_user_label)
        account_layout.addWidget(self.account_menu_button)
        self.header_account.hide()

        layout.addWidget(self.header_logo_label)
        layout.addStretch(1)
        layout.addWidget(self.header_account)
        return header

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("loginPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        panel = QFrame()
        panel.setObjectName("loginPanel")
        panel.setMinimumWidth(560)
        panel.setMaximumWidth(690)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(38, 32, 38, 30)
        panel_layout.setSpacing(14)

        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 38))
        panel.setGraphicsEffect(shadow)

        title_row = QHBoxLayout()
        title_row.setSpacing(20)
        login_icon = QLabel()
        login_icon.setObjectName("loginIllustration")
        login_pixmap = QPixmap(str(login_illustration_path()))
        if not login_pixmap.isNull():
            login_icon.setPixmap(
                login_pixmap.scaled(96, 78, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        login_icon.setFixedSize(104, 84)
        login_icon.setAlignment(Qt.AlignCenter)
        title = QLabel("System Login")
        title.setObjectName("loginTitle")
        title_row.addWidget(login_icon)
        title_row.addWidget(title)
        title_row.addStretch(1)

        self.login_error_label = QLabel("")
        self.login_error_label.setObjectName("loginError")
        self.login_error_label.setWordWrap(True)
        self.login_error_label.hide()

        username_label = QLabel("Username:")
        username_label.setObjectName("loginFieldLabel")
        self.username_edit = QLineEdit()
        self.username_edit.setObjectName("loginUsername")
        self.username_edit.setClearButtonEnabled(True)
        self.username_edit.textChanged.connect(
            lambda text: self.login_button.setEnabled(bool(text.strip()))
        )
        self.username_edit.returnPressed.connect(self.submit_login)

        password_label = QLabel("Password:")
        password_label.setObjectName("loginFieldLabel")
        self.password_edit = QLineEdit()
        self.password_edit.setObjectName("loginPassword")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(self.submit_login)

        self.login_button = QPushButton("Login")
        self.login_button.setObjectName("loginSubmit")
        set_role(self.login_button, "primary")
        self.login_button.setEnabled(False)
        self.login_button.clicked.connect(self.submit_login)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.login_button)
        button_row.addStretch(1)

        note = QLabel(
            "NOTE: User roles are in development. Use 'client_site1' or 'client_site2' "
            "for CLIENT accounts, and 'initiator' for the site3 INITIATOR account. "
            "No password needed."
        )
        note.setObjectName("loginNote")
        note.setWordWrap(True)

        panel_layout.addLayout(title_row)
        panel_layout.addWidget(self.login_error_label)
        panel_layout.addWidget(username_label)
        panel_layout.addWidget(self.username_edit)
        panel_layout.addWidget(password_label)
        panel_layout.addWidget(self.password_edit)
        panel_layout.addSpacing(6)
        panel_layout.addLayout(button_row)
        panel_layout.addSpacing(4)
        panel_layout.addWidget(note)

        centered = QHBoxLayout()
        centered.addStretch(1)
        centered.addWidget(panel)
        centered.addStretch(1)
        outer.addLayout(centered)
        outer.addStretch(1)
        return page

    def _show_login(self) -> None:
        self.authenticated_stack.setCurrentWidget(self.login_page)
        self.header_user_label.clear()
        self.header_account.hide()
        self.username_edit.setFocus(Qt.OtherFocusReason)
        self._set_tray_authenticated(False)

    def submit_login(self) -> None:
        if self._login_worker is not None and self._login_worker.isRunning():
            return
        username = self.username_edit.text().strip()
        if not username:
            self._show_login_error("Username is required.")
            return

        self._show_login_error("")
        self.username_edit.setEnabled(False)
        self.password_edit.setEnabled(False)
        self.login_button.setEnabled(False)
        self.login_button.setText("Signing in…")

        service = AuthenticationService(
            api_base_url=self.config.authentication_api_base_url,
            user_role_path=self.config.user_role_path,
            timeout_seconds=self.config.login_timeout_seconds,
        )
        worker = LoginWorker(service=service, username=username, parent=self)
        self._login_worker = worker
        worker.completed.connect(self._on_login_complete)
        worker.failed.connect(self._on_login_failed)
        worker.finished.connect(self._on_login_finished)
        worker.start()

    def _on_login_complete(self, session: UserSession) -> None:
        role = (session.role or "").strip().upper()
        client_name = (session.client_name or "").strip()
        if role != "CLIENT":
            self._show_login_error(
                f"The {session.role} account is not assigned to the SHARE Client desktop application."
            )
            return
        if not re.fullmatch(r"site[-_]?\d+", client_name, flags=re.IGNORECASE):
            self._show_login_error(
                "The login succeeded, but the account does not have a valid NVFlare client site assignment."
            )
            return

        self.session = session
        self.state.activate_site(
            client_name,
            default_install_base=str(self._configured_startup_extract_base()),
        )
        if not self.state.startup_install_base:
            self.state.startup_install_base = str(self._configured_startup_extract_base())
        self._clear_workspace_if_it_points_at_old_demo_home()
        save_state(self.state)
        self.password_edit.clear()
        self._refresh_tar_choices()
        self._sync_state_to_ui()
        safe_username = html.escape(session.username or "")
        safe_role = html.escape(role)
        safe_client_name = html.escape(client_name)
        self.header_user_label.setText(
            f"User: <b>{safe_username} ({safe_role}@{safe_client_name})</b>"
        )
        self.header_account.show()
        self.authenticated_stack.setCurrentWidget(self.supervisor_shell)
        self._set_page(0)
        self._set_tray_authenticated(True)

    def _on_login_failed(self, message: str) -> None:
        self._show_login_error(message or "Login failed.")

    def _on_login_finished(self) -> None:
        self.username_edit.setEnabled(True)
        self.password_edit.setEnabled(True)
        self.login_button.setText("Login")
        self.login_button.setEnabled(bool(self.username_edit.text().strip()))
        worker = self._login_worker
        self._login_worker = None
        if worker is not None:
            worker.deleteLater()

    def _show_login_error(self, message: str) -> None:
        normalized = (message or "").strip()
        self.login_error_label.setText(normalized)
        self.login_error_label.setVisible(bool(normalized))

    def logout(self) -> None:
        if self._startup_kit_worker is not None and self._startup_kit_worker.isRunning():
            self._error("Wait for the startup-kit operation to finish before logging out.")
            return
        if self.nvflare.is_running or self._results_service_active:
            if not self._confirm(
                "Sign out of SHARE Client?",
                "The embedded Results API will stop before sign-out so it cannot continue serving the previous site's workspace. NVFlare will continue running until explicitly stopped.",
            ):
                return
        if self.results.is_running:
            self.results.stop()
        save_state(self.state)
        self.session = None
        self.password_edit.clear()
        self._show_login_error("")
        self._show_login()

    def _require_session(self) -> bool:
        if self.session is not None:
            return True
        self._show_login()
        self._show_login_error("Sign in before using the SHARE Client supervisor.")
        return False

    def _assigned_site(self) -> str:
        if self.session is None:
            return ""
        return (self.session.client_name or "").strip()

    def _set_tray_authenticated(self, authenticated: bool) -> None:
        for action_name in ["tray_share_action", "tray_start_action", "tray_stop_action"]:
            action = getattr(self, action_name, None)
            if action is not None:
                action.setEnabled(authenticated)

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("page", "true")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("overviewScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        content = QWidget()
        # This is the real floor for the Overview content. The page itself
        # stays shrinkable, so short preview windows get scrollbars instead
        # of hiding the action row.
        content.setMinimumHeight(470)
        content.setMinimumWidth(640)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 14)
        content_layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("SHARE Client")
        title.setProperty("role", "pageTitle")

        header.addWidget(title)
        header.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_all_button = QPushButton("Start All")
        self.stop_all_button = QPushButton("Stop Gracefully")
        self.kill_button = QPushButton("Force Kill NVFlare")
        self.quit_button = QPushButton("Quit")
        set_role(self.start_all_button, "secondary")
        set_role(self.stop_all_button, "primary")
        set_role(self.kill_button, "danger")
        set_role(self.quit_button, "neutral")
        self.start_all_button.clicked.connect(self.start_all)
        self.stop_all_button.clicked.connect(self.stop_nvflare_gracefully)
        self.kill_button.clicked.connect(self.force_kill_nvflare)
        self.quit_button.clicked.connect(self.quit_app)
        actions.addStretch(1)
        for button in [self.start_all_button, self.stop_all_button, self.kill_button, self.quit_button]:
            actions.addWidget(button)

        self.overview_subtitle = QLabel("Local supervisor for NVFlare and Results API")
        self.overview_subtitle.setProperty("role", "muted")

        cards = QVBoxLayout()
        cards.setSpacing(8)
        self.startup_card = ServiceCard("Startup Kit")
        self.nvflare_card = ServiceCard("Federated Client")
        self.results_card = ServiceCard("Results Service")
        cards.addWidget(self.startup_card)
        cards.addWidget(self.nvflare_card)
        cards.addWidget(self.results_card)

        self.activity_label = QLabel("Recent activity: -")
        self.activity_label.setProperty("role", "overviewActivity")
        self.activity_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        content_layout.addLayout(header)
        content_layout.addWidget(self.overview_subtitle)
        content_layout.addLayout(cards)
        # Keep the operational action row anchored at the bottom of the
        # Overview content when there is room. When there is not, the
        # surrounding scroll area makes it reachable instead of clipping it.
        content_layout.addStretch(1)
        content_layout.addLayout(actions)
        content_layout.addWidget(self.activity_label)

        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)
        return page

    def _build_job_results_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("page", "true")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        layout.addWidget(self._build_job_results_panel(), 1)
        return page

    def _build_job_results_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("jobResultsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(12)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title = QLabel("Local Job Results")
        title.setProperty("role", "pageTitle")
        subtitle = QLabel("Local NVFlare job history from the configured job save location.")
        subtitle.setProperty("role", "muted")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)

        self.job_results_location_label = QLabel("Job save location: -")
        self.job_results_location_label.setProperty("role", "muted")
        self.refresh_job_results_button = QPushButton("Refresh")
        self.explore_job_results_button = QPushButton("Explore in SHARE")
        set_role(self.refresh_job_results_button, "neutral")
        set_role(self.explore_job_results_button, "secondary")
        self.refresh_job_results_button.clicked.connect(self._refresh_job_results_table)
        self.explore_job_results_button.clicked.connect(self.open_share)
        header.addLayout(header_text)
        header.addStretch(1)
        header.addWidget(self.refresh_job_results_button)
        header.addWidget(self.explore_job_results_button)

        self.job_results_tree = QTreeWidget()
        self.job_results_tree.setObjectName("jobResultsTree")
        self.job_results_tree.setHeaderLabels(["NVFlare Job ID", "Modified", "Size", "Functions / Details"])
        self.job_results_tree.setAlternatingRowColors(True)
        self.job_results_tree.setRootIsDecorated(True)
        self.job_results_tree.setItemsExpandable(True)
        self.job_results_tree.setUniformRowHeights(False)
        self.job_results_tree.setMinimumHeight(175)
        self.job_results_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        header_view = self.job_results_tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)

        layout.addLayout(header)
        layout.addWidget(self.job_results_tree, 1)
        layout.addWidget(self.job_results_location_label)
        return panel

    def _build_startup_settings_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("settingsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel("Startup Kit")
        title.setProperty("role", "sectionTitle")
        description = QLabel(
            "Download the NVFlare startup kit assigned to the authenticated SHARE account and install it in the persistent SHARE Client data directory."
        )
        description.setWordWrap(True)
        description.setProperty("role", "muted")

        site_row = QHBoxLayout()
        site_row.setSpacing(8)
        site_label = QLabel("Assigned site")
        site_label.setMinimumWidth(105)
        self.startup_site_label = QLabel("Sign in to resolve your assigned client site")
        self.startup_site_label.setWordWrap(True)
        self.startup_site_label.setProperty("role", "path")
        site_row.addWidget(site_label)
        site_row.addWidget(self.startup_site_label, 1)

        install_row = QHBoxLayout()
        install_row.setSpacing(8)
        install_label = QLabel("Managed workspace")
        install_label.setMinimumWidth(105)
        self.install_location_edit = QLineEdit()
        self.install_location_edit.setReadOnly(True)
        install_row.addWidget(install_label)
        install_row.addWidget(self.install_location_edit, 1)

        download_row = QHBoxLayout()
        download_row.addStretch(1)
        self.download_install_button = QPushButton("Download and Install Startup Kit")
        set_role(self.download_install_button, "primary")
        self.download_install_button.clicked.connect(self.download_and_install_startup_kit)
        download_row.addWidget(self.download_install_button)

        self.startup_progress = QProgressBar()
        self.startup_progress.setRange(0, 100)
        self.startup_progress.setValue(0)
        self.startup_progress.setTextVisible(True)
        self.startup_progress.hide()

        self.startup_status_label = QLabel()
        self.startup_status_label.setWordWrap(True)
        self.startup_status_label.setProperty("role", "path")

        offline_label = QLabel("Offline / existing archive")
        offline_label.setProperty("role", "muted")

        tar_row = QHBoxLayout()
        tar_row.setSpacing(8)
        self.tar_combo = QComboBox()
        self.refresh_tars_button = QPushButton("Refresh")
        self.browse_tar_button = QPushButton("Browse…")
        self.install_tar_button = QPushButton("Install Existing Archive")
        set_role(self.refresh_tars_button, "neutral")
        set_role(self.browse_tar_button, "neutral")
        set_role(self.install_tar_button, "secondary")
        self.refresh_tars_button.clicked.connect(self._refresh_tar_choices)
        self.browse_tar_button.clicked.connect(self.browse_tar)
        self.install_tar_button.clicked.connect(self.install_selected_tar)
        tar_row.addWidget(self.tar_combo, 1)
        tar_row.addWidget(self.refresh_tars_button)
        tar_row.addWidget(self.browse_tar_button)
        tar_row.addWidget(self.install_tar_button)

        self.startup_help_label = QLabel(
            f"Downloaded archives are cached in {INBOX_DIR}. The assigned site workspace and job-results directory are kept under {WORKSPACES_DIR} so they persist when the supervisor source code moves or is replaced."
        )
        self.startup_help_label.setWordWrap(True)
        self.startup_help_label.setProperty("role", "muted")

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(site_row)
        layout.addLayout(install_row)
        layout.addLayout(download_row)
        layout.addWidget(self.startup_progress)
        layout.addWidget(self.startup_status_label)
        layout.addWidget(offline_label)
        layout.addLayout(tar_row)
        layout.addWidget(self.startup_help_label)
        panel.setMinimumHeight(320)
        return panel

    def _build_nvflare_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("page", "true")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.nvflare_console = LogConsole("NVFlare startup-kit output")

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        self.start_nvflare_button = QPushButton("Start NVFlare")
        self.stop_nvflare_button = QPushButton("Stop with stop_fl.sh")
        self.kill_nvflare_button = QPushButton("Force Kill")
        set_role(self.start_nvflare_button, "secondary")
        set_role(self.stop_nvflare_button, "primary")
        set_role(self.kill_nvflare_button, "danger")
        self.start_nvflare_button.clicked.connect(self.start_nvflare)
        self.stop_nvflare_button.clicked.connect(self.stop_nvflare_gracefully)
        self.kill_nvflare_button.clicked.connect(self.force_kill_nvflare)
        for button in [self.start_nvflare_button, self.stop_nvflare_button, self.kill_nvflare_button]:
            controls.addWidget(button)

        layout.addWidget(self.nvflare_console, 1)
        layout.addLayout(controls)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("page", "true")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.results_console = LogConsole("Results API / embedded Uvicorn output")

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        self.start_results_button = QPushButton("Start Results Service")
        self.restart_results_button = QPushButton("Restart Results Service")
        self.stop_results_button = QPushButton("Stop Results Service")
        self.health_results_button = QPushButton("Health Check")
        set_role(self.start_results_button, "secondary")
        set_role(self.restart_results_button, "primary")
        set_role(self.stop_results_button, "warning")
        set_role(self.health_results_button, "neutral")
        self.start_results_button.clicked.connect(self.start_results)
        self.restart_results_button.clicked.connect(self.restart_results)
        self.stop_results_button.clicked.connect(self.stop_results)
        self.health_results_button.clicked.connect(self.check_results_health)
        for button in [self.start_results_button, self.restart_results_button, self.stop_results_button, self.health_results_button]:
            controls.addWidget(button)

        layout.addWidget(self.results_console, 1)
        layout.addLayout(controls)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("page", "true")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("Settings")
        title.setProperty("role", "pageTitle")

        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        scroll_content = QWidget()
        # The settings panels should shrink with the window until they hit a
        # readable floor, then use scrollbars instead of squeezing controls or
        # overflowing off-screen.
        scroll_content.setMinimumWidth(640)
        scroll_content.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        startup_panel = self._build_startup_settings_panel()

        settings_panel = QFrame()
        settings_panel.setObjectName("settingsPanel")
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(12, 10, 12, 10)
        settings_layout.setSpacing(8)

        settings_title = QLabel("Application Settings")
        settings_title.setProperty("role", "sectionTitle")

        form = QFormLayout()
        self.settings_username_label = QLabel("-")
        self.settings_username_label.setProperty("role", "path")
        self.settings_role_label = QLabel("-")
        self.settings_role_label.setProperty("role", "path")
        self.settings_site_label = QLabel("-")
        self.settings_site_label.setProperty("role", "path")
        self.env_combo = QComboBox()
        self.env_combo.addItems(["aws"])
        self.workspace_label = QLabel("-")
        self.workspace_label.setWordWrap(True)
        self.workspace_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.workspace_label.setProperty("role", "path")
        self.repo_root_label = QLabel(str(self.repo_root))
        self.repo_root_label.setWordWrap(True)
        self.repo_root_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.repo_root_label.setProperty("role", "path")
        self.config_label = QLabel("\n".join(str(path) for path in self.config.loaded_from) or "No INI loaded")
        self.config_label.setWordWrap(True)
        self.config_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.config_label.setProperty("role", "path")
        self.content_api_label = QLabel(
            f"{self.config.content_api_base_url}{self.config.startup_kit_download_path}"
        )
        self.content_api_label.setWordWrap(True)
        self.content_api_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.content_api_label.setProperty("role", "path")
        self.authentication_api_label = QLabel(
            f"{self.config.authentication_api_base_url}{self.config.user_role_path}"
        )
        self.authentication_api_label.setWordWrap(True)
        self.authentication_api_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.authentication_api_label.setProperty("role", "path")
        self.job_results_label = QLabel(self.config.job_results_dir_name)
        self.job_results_label.setWordWrap(True)
        self.job_results_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.job_results_label.setProperty("role", "path")
        self.health_interval_label = QLabel(f"{self.config.results_health_interval_seconds}s")
        self.health_interval_label.setProperty("role", "path")
        self.share_url_combo = QComboBox()
        self.share_url_combo.setEditable(True)
        self.share_url_combo.addItems(self.config.share_recent_urls)
        self.save_settings_button = QPushButton("Save settings")
        set_role(self.save_settings_button, "primary")
        self.save_settings_button.clicked.connect(self.save_settings_from_ui)
        form.addRow("Signed-in user", self.settings_username_label)
        form.addRow("Role", self.settings_role_label)
        form.addRow("Assigned site", self.settings_site_label)
        form.addRow("Environment", self.env_combo)
        form.addRow("Workspace", self.workspace_label)
        form.addRow("Repo root", self.repo_root_label)
        form.addRow("Config", self.config_label)
        form.addRow("Login API", self.authentication_api_label)
        form.addRow("Content API", self.content_api_label)
        form.addRow("Job results dir", self.job_results_label)
        form.addRow("Health interval", self.health_interval_label)
        form.addRow("SHARE URL", self.share_url_combo)

        settings_layout.addWidget(settings_title)
        settings_layout.addLayout(form)
        settings_layout.addWidget(self.save_settings_button, 0, Qt.AlignLeft)
        # Application Settings contains the tallest label/value stack, so it
        # gets a larger floor than the Startup Kit panel. When the window is
        # too short, the scroll area appears rather than squeezing inputs.
        settings_panel.setMinimumHeight(445)

        scroll_layout.addWidget(startup_panel)
        scroll_layout.addWidget(settings_panel)
        scroll_layout.addStretch(1)
        scroll_area.setWidget(scroll_content)

        layout.addWidget(title)
        layout.addWidget(scroll_area, 1)
        return page

    def _connect_runners(self) -> None:
        self.nvflare.output.connect(self._on_nvflare_output)
        self.nvflare.state_changed.connect(self._on_nvflare_state)
        self.nvflare.exited.connect(lambda code: self._on_nvflare_output(f"\n[NVFlare exited with code {code}]\n"))
        self.results.output.connect(self._on_results_output)
        self.results.state_changed.connect(self._on_results_state)
        self.results.health_changed.connect(self._on_results_health)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray.setIcon(client_icon("idle"))
        self.tray.setToolTip("SHARE Client")
        menu = self.tray.contextMenu()
        if menu is None:
            from PySide6.QtWidgets import QMenu
            menu = QMenu()
        open_action = QAction("Open Status", self)
        self.tray_share_action = QAction("Explore SHARE", self)
        self.tray_start_action = QAction("Start All", self)
        self.tray_stop_action = QAction("Stop Gracefully", self)
        quit_action = QAction("Quit", self)
        open_action.triggered.connect(self.show)
        self.tray_share_action.triggered.connect(self.open_share)
        self.tray_start_action.triggered.connect(self.start_all)
        self.tray_stop_action.triggered.connect(self.stop_nvflare_gracefully)
        quit_action.triggered.connect(self.quit_app)
        for action in [open_action, self.tray_share_action, self.tray_start_action, self.tray_stop_action, quit_action]:
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self._set_tray_authenticated(self.session is not None)
        self.tray.show()

    def _start_timers(self) -> None:
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2000)

        # Observe the embedded Results API and recover it after repeated health
        # failures. Closing the window to the tray keeps this timer and Uvicorn alive.
        self.results_health_timer = QTimer(self)
        self.results_health_timer.timeout.connect(self._periodic_results_health_check)
        self.results_health_timer.start(max(5, self.config.results_health_interval_seconds) * 1000)

        # Populate once on launch. After that, refresh is explicit to avoid
        # stealing table/tree focus while the user is inspecting rows.
        QTimer.singleShot(0, self._refresh_job_results_table)

    def _set_page(self, row: int) -> None:
        row = max(0, min(row, len(getattr(self, "nav_buttons", [])) - 1))
        self.pages.setCurrentIndex(row)
        for index, button in enumerate(getattr(self, "nav_buttons", [])):
            selected = index == row
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _refresh_tar_choices(self) -> None:
        current = self.state.startup_kit_tar
        self.tar_combo.clear()
        tars = discover_startup_tars(self.repo_root)
        resolved_tars = [path.resolve() for path in tars]
        if current and Path(current).exists() and Path(current).resolve() not in resolved_tars:
            tars.insert(0, Path(current).resolve())
        for tar in tars:
            self.tar_combo.addItem(str(tar), str(tar))

        selected = False
        if current:
            current_resolved = str(Path(current).expanduser().resolve())
            idx = self.tar_combo.findData(current_resolved)
            if idx >= 0:
                self.tar_combo.setCurrentIndex(idx)
                selected = True

        if not selected and self.state.site:
            preferred_names = {
                f"{self.state.site}.tar.gz",
                f"{self.state.site}.tgz",
                f"{self.state.site}.tar",
                f"share-client-{self.state.site}-startup-kit.tar.gz",
            }
            for idx in range(self.tar_combo.count()):
                data = self.tar_combo.itemData(idx)
                if data and Path(str(data)).name in preferred_names:
                    self.tar_combo.setCurrentIndex(idx)
                    self.state.startup_kit_tar = str(Path(str(data)).expanduser().resolve())
                    save_state(self.state)
                    break
        self.refresh_status()

    def download_and_install_startup_kit(self) -> None:
        if not self._require_session():
            return
        if self._startup_kit_worker is not None and self._startup_kit_worker.isRunning():
            self._error("A startup-kit download or installation is already running.")
            return
        if self.nvflare.is_running or self._results_service_active:
            self._error("Stop NVFlare and the Results API before replacing or installing a startup-kit workspace.")
            return

        site = self._assigned_site()
        if not site:
            self._error("The signed-in account does not have an assigned client site.")
            return

        destination_base = self._startup_extract_base()
        try:
            destination_base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._error(f"Could not use the managed SHARE Client data directory: {exc}")
            return
        target_workspace = destination_base / site
        replace_existing = False
        if target_workspace.exists():
            replace_existing = self._confirm(
                "Replace Existing Workspace?",
                f"{target_workspace} already exists.\n\n"
                "The existing workspace will be renamed to a timestamped backup before the new startup kit is installed.",
            )
            if not replace_existing:
                return

        self.state.site = site
        self.state.startup_install_base = str(destination_base)
        self.state.startup_kit_tar = ""
        self.state.workspace_root = ""
        save_state(self.state)

        service = StartupKitDeliveryService(
            api_base_url=self.config.content_api_base_url,
            startup_kit_path=self.config.startup_kit_download_path,
            timeout_seconds=self.config.startup_kit_download_timeout_seconds,
        )
        worker = StartupKitProvisionWorker(
            service=service,
            site=site,
            destination_base=destination_base,
            replace_existing=replace_existing,
            parent=self,
        )
        self._startup_kit_worker = worker
        worker.status_changed.connect(self._on_startup_provision_status)
        worker.progress_changed.connect(self._on_startup_download_progress)
        worker.completed.connect(self._on_startup_provision_complete)
        worker.failed.connect(self._on_startup_provision_failed)
        worker.finished.connect(self._on_startup_provision_finished)

        self._set_startup_provision_controls_enabled(False)
        self.startup_progress.setRange(0, 0)
        self.startup_progress.show()
        self.startup_status_label.setText(f"Preparing download for {site}…")
        worker.start()

    def _set_startup_provision_controls_enabled(self, enabled: bool) -> None:
        for control in [
            self.download_install_button,
            self.refresh_tars_button,
            self.browse_tar_button,
            self.install_tar_button,
        ]:
            control.setEnabled(enabled)

    def _on_startup_provision_status(self, message: str) -> None:
        self.startup_status_label.setText(message)

    def _on_startup_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            percent = max(0, min(100, int(downloaded * 100 / total)))
            self.startup_progress.setRange(0, 100)
            self.startup_progress.setValue(percent)
            self.startup_progress.setFormat(f"Downloading… {percent}%")
        else:
            self.startup_progress.setRange(0, 0)
            self.startup_progress.setFormat("Downloading…")

    def _on_startup_provision_complete(self, archive_path: str, workspace_path: str, backup_path: str) -> None:
        workspace = Path(workspace_path).expanduser().resolve()
        (workspace / self.config.job_results_dir_name).mkdir(parents=True, exist_ok=True)
        self.state.startup_kit_tar = str(Path(archive_path).expanduser().resolve())
        self.state.workspace_root = str(workspace)
        self.state.startup_install_base = str(workspace.parent)
        save_state(self.state)
        self._refresh_tar_choices()
        self._sync_state_to_ui()
        self.startup_progress.setRange(0, 100)
        self.startup_progress.setValue(100)
        self.startup_progress.setFormat("Installed")
        self.startup_status_label.setText(f"Ready: {workspace}")
        self.nvflare_console.append(
            f"[Desktop] Downloaded {archive_path} and installed the startup kit at {workspace}\n"
        )
        message = f"Startup kit installed successfully.\n\nWorkspace: {workspace}"
        if backup_path:
            message += f"\n\nPrevious workspace backup: {backup_path}"
        QMessageBox.information(self, "SHARE Client", message)

    def _on_startup_provision_failed(self, message: str) -> None:
        self.startup_progress.setRange(0, 100)
        self.startup_progress.setValue(0)
        self.startup_progress.setFormat("Failed")
        self.startup_status_label.setText(f"Download/install failed: {message}")
        self._error(message)

    def _on_startup_provision_finished(self) -> None:
        self._set_startup_provision_controls_enabled(True)
        worker = self._startup_kit_worker
        self._startup_kit_worker = None
        if worker is not None:
            worker.deleteLater()
        self.refresh_status()

    def browse_tar(self) -> None:
        if not self._require_session():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose startup kit tar",
            str(INBOX_DIR),
            "Tar files (*.tar *.tar.gz *.tgz);;All files (*)",
        )
        if not path:
            return
        self.state.startup_kit_tar = str(Path(path).expanduser().resolve())
        save_state(self.state)
        self._refresh_tar_choices()

    def install_selected_tar(self) -> None:
        if not self._require_session():
            return
        if self.nvflare.is_running or self._results_service_active:
            self._error("Stop NVFlare and the Results API before replacing or installing a startup-kit workspace.")
            return
        tar_path = self._selected_tar_path()
        if tar_path is None:
            self._error("No startup-kit tar selected.")
            return

        site = self._assigned_site()
        if not site:
            self._error("The signed-in account does not have an assigned client site.")
            return
        destination_base = self._startup_extract_base()
        target_workspace = destination_base / site
        replace_existing = False
        if target_workspace.exists():
            replace_existing = self._confirm(
                "Replace Existing Workspace?",
                f"{target_workspace} already exists.\n\n"
                "The existing workspace will be renamed to a timestamped backup before this archive is installed.",
            )
            if not replace_existing:
                return


        try:
            validate_startup_tar(tar_path, expected_site=site)
            install = install_startup_tar(
                tar_path,
                destination_base,
                expected_site=site,
                replace_existing=replace_existing,
            )
            workspace = install.workspace
            (workspace / self.config.job_results_dir_name).mkdir(parents=True, exist_ok=True)
            self.state.site = site
            self.state.startup_kit_tar = str(tar_path)
            self.state.startup_install_base = str(destination_base)
            self.state.workspace_root = str(workspace)
            save_state(self.state)
            self._sync_state_to_ui()
            self.nvflare_console.append(f"[Desktop] Installed {tar_path} at {workspace}\n")
        except Exception as exc:
            self._error(str(exc))

    def start_all(self) -> None:
        if not self._require_session():
            return
        workspace = self._ensure_workspace_installed()
        if workspace is None:
            return
        self.start_nvflare()
        self.start_results()

    def start_nvflare(self) -> None:
        if not self._require_session():
            return
        workspace = self._ensure_workspace_installed()
        if workspace is None:
            return
        try:
            self.nvflare.start(workspace, env=self._process_env())
        except Exception as exc:
            self._error(str(exc))

    def stop_nvflare_gracefully(self) -> None:
        workspace = self._workspace_path()
        if workspace is None:
            self._error("No installed startup kit workspace found.")
            return
        if not self._confirm("Stop Federated Client?", "This will run startup/stop_fl.sh with input 'y'. Any active job may be interrupted."):
            return
        try:
            self.nvflare.graceful_stop(workspace)
        except Exception as exc:
            self._error(str(exc))

    def force_kill_nvflare(self) -> None:
        if not self._confirm("Force Kill NVFlare?", "This bypasses stop_fl.sh and terminates the process group directly. Use only if the client is stuck."):
            return
        self.nvflare.force_kill(self._workspace_path())

    def start_results(self) -> None:
        if not self._require_session():
            return
        workspace = self._ensure_workspace_installed()
        if workspace is None:
            return
        try:
            self.results.start(workspace, site=self.state.site)
        except Exception as exc:
            self._error(str(exc))

    def restart_results(self) -> None:
        if not self._require_session():
            return
        workspace = self._ensure_workspace_installed()
        if workspace is None:
            return
        try:
            self.results.restart(workspace, site=self.state.site)
        except Exception as exc:
            self._error(str(exc))

    def stop_results(self) -> None:
        if self.results.is_running and not self._confirm(
            "Stop Results Service?",
            "This will stop the embedded local Results API. SHARE result pages will be unavailable until it is started again.",
        ):
            return
        try:
            self.results.stop()
        except Exception as exc:
            self._error(str(exc))

    def check_results_health(self) -> None:
        self.results_console.append("[Health] checking results service...\n")
        self.results.check_health_async(attempts=4, delay_ms=750)

    def open_share(self) -> None:
        self._open_share_launch()

    def _open_share_launch(self, nvflare_job_id: str | None = None) -> None:
        if not self._require_session():
            return

        self.save_settings_from_ui(show_message=False)
        assert self.session is not None

        try:
            launch_url = build_share_launch_url(
                self.state.share_url,
                username=self.session.username,
                nvflare_job_id=nvflare_job_id,
            )
        except ValueError as exc:
            self._error(str(exc))
            return

        if not webbrowser.open_new_tab(launch_url):
            self._error("Could not open SHARE in the system web browser.")

    def save_settings_from_ui(self, show_message: bool = True) -> None:
        if not self._require_session():
            return
        self.state.env = self.env_combo.currentText().strip() or "aws"
        self.state.share_url = self.share_url_combo.currentText().strip() or self.config.share_url
        save_state(self.state)
        self._refresh_tar_choices()
        self._sync_state_to_ui()
        if show_message:
            QMessageBox.information(self, "Saved", "Settings saved.")

    def refresh_status(self) -> None:
        self._refresh_cards()
        self._refresh_status_icon()
        self._refresh_tray()

    def _refresh_cards(self) -> None:
        tar_path = self._selected_tar_path()
        workspace = self._workspace_path()
        provisioning = self._startup_kit_worker is not None and self._startup_kit_worker.isRunning()
        if provisioning:
            self.startup_card.set_state("Installing", f"Preparing {self.state.site}")
        elif workspace and (workspace / "startup" / "start.sh").exists():
            self.startup_card.set_state("✓ Ready", str(workspace))
            self.startup_status_label.setText(f"Ready: {workspace}")
        elif tar_path:
            self.startup_card.set_state("Tar selected", str(tar_path))
            self.startup_status_label.setText(f"Selected tar: {tar_path}")
        else:
            self.startup_card.set_state("Missing", "Download a site startup kit in Settings")
            self.startup_status_label.setText(
                f"No startup kit is installed for {self.state.site}. Download one above or select an existing archive."
            )

        if workspace:
            self.nvflare.set_workspace(workspace)
        if self.nvflare.is_running:
            detail = self.nvflare.status_detail()
            if self.last_nvflare_output_at:
                age = max(0, int((datetime.now(timezone.utc) - self.last_nvflare_output_at).total_seconds()))
                detail += f" · last output {age}s ago"
            self.nvflare_card.set_state("● Running", detail)
            self.activity_label.setText(detail)
        else:
            self.nvflare_card.set_state("Stopped", "NVFlare startup-kit worker is not running")

        # Health check is intentionally manual most of the time. This card reflects last health signal.
        if not self.results_card.status.text():
            self.results_card.set_state("Not checked", f"Embedded Uvicorn · port {self.state.results_port}")

    def _status_icon_state(self) -> str:
        if self._last_results_state == "error":
            return "error"
        if self._results_service_active and self._results_health_ok is False:
            return "error"
        if self.nvflare.is_running or self._results_service_active:
            return "active"
        return "idle"

    def _refresh_status_icon(self) -> None:
        icon_state = self._status_icon_state()
        icon = client_icon(icon_state)
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        if getattr(self, "tray", None) is not None and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.setIcon(icon)

    def _refresh_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_state = self._status_icon_state()
        if icon_state == "error":
            text = "SHARE Client — attention needed"
        elif self.nvflare.is_running:
            if self.last_nvflare_output_at:
                age = max(0, int((datetime.now(timezone.utc) - self.last_nvflare_output_at).total_seconds()))
                if age <= 15:
                    text = "SHARE Client — activity detected"
                else:
                    text = "SHARE Client — running"
            else:
                text = "SHARE Client — running"
        elif self._results_service_active:
            text = "SHARE Client — results service active"
        else:
            text = "SHARE Client — stopped"
        self.tray.setToolTip(text)

    def _view_job_results_in_share(self, job_id: str) -> None:
        self._open_share_launch(nvflare_job_id=job_id)

    def _refresh_job_results_table(self) -> None:
        tree = getattr(self, "job_results_tree", None)
        if tree is None:
            return
        job_dir = self._current_job_results_dir()
        if job_dir is None:
            self.job_results_location_label.setText("Job save location: not available until a startup kit workspace is installed.")
            tree.clear()
            return

        self.job_results_location_label.setText(f"Job save location: {job_dir}")
        expanded_paths = self._expanded_job_paths()
        tree.clear()
        entries = self._job_result_entries(job_dir)
        for entry in entries:
            item = QTreeWidgetItem([
                str(entry["job_id"]),
                str(entry["modified"]),
                str(entry["size"]),
                str(entry["function_summary"]),
            ])
            item.setData(0, Qt.UserRole, entry["location"])
            tree.addTopLevelItem(item)

            if entry.get("placeholder"):
                continue

            functions = entry.get("functions", [])
            if functions:
                for function in functions:
                    function_item = QTreeWidgetItem([
                        f"Function: {function['name']}",
                        function["modified"],
                        function["size"],
                        function["file_count"],
                    ])
                    item.addChild(function_item)
            else:
                empty_item = QTreeWidgetItem(["No function folders found", "", "", ""])
                empty_item.setFirstColumnSpanned(True)
                item.addChild(empty_item)

            link_item = QTreeWidgetItem(["", "", "", ""])
            link_item.setFirstColumnSpanned(True)
            item.addChild(link_item)
            link_button = QPushButton("View These Results in SHARE")
            link_button.setCursor(Qt.PointingHandCursor)
            link_button.setFlat(True)
            set_role(link_button, "link")
            link_button.clicked.connect(
                lambda checked=False, job_id=str(entry["job_id"]): self._view_job_results_in_share(job_id)
            )
            tree.setItemWidget(link_item, 0, link_button)

            if str(entry["location"]) in expanded_paths:
                item.setExpanded(True)

        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        tree.resizeColumnToContents(2)
        tree.resizeColumnToContents(3)

    def _current_job_results_dir(self) -> Path | None:
        workspace = self._workspace_path()
        if workspace is None:
            expected = self._expected_workspace_for_site()
            if (expected / self.config.job_results_dir_name).exists():
                workspace = expected
            else:
                return None
        return workspace / self.config.job_results_dir_name

    def _expanded_job_paths(self) -> set[str]:
        tree = getattr(self, "job_results_tree", None)
        if tree is None:
            return set()
        expanded: set[str] = set()
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.isExpanded():
                value = item.data(0, Qt.UserRole)
                if value:
                    expanded.add(str(value))
        return expanded

    def _job_result_entries(self, job_dir: Path) -> list[dict[str, object]]:
        if not job_dir.exists():
            return [{
                "job_id": "No results folder yet",
                "modified": "-",
                "size": "-",
                "function_summary": "-",
                "location": str(job_dir),
                "functions": [],
                "placeholder": True,
            }]
        try:
            children = [child for child in job_dir.iterdir() if not child.name.startswith(".")]
        except OSError as exc:
            return [{
                "job_id": "Unable to read job results",
                "modified": "-",
                "size": "-",
                "function_summary": "-",
                "location": str(exc),
                "functions": [],
                "placeholder": True,
            }]

        job_folders = [child for child in children if child.is_dir()]
        if not job_folders:
            return [{
                "job_id": "No result artifacts found",
                "modified": "-",
                "size": "-",
                "function_summary": "-",
                "location": str(job_dir),
                "functions": [],
                "placeholder": True,
            }]

        job_folders.sort(key=lambda path: self._latest_mtime(path), reverse=True)
        entries: list[dict[str, object]] = []
        for job_path in job_folders[:50]:
            functions = self._job_function_entries(job_path)
            function_names = [str(function["name"]) for function in functions]
            if not function_names:
                function_summary = "No function folders"
            elif len(function_names) <= 3:
                function_summary = ", ".join(function_names)
            else:
                function_summary = f"{len(function_names)} functions: " + ", ".join(function_names[:3]) + f", +{len(function_names) - 3} more"

            entries.append({
                "job_id": job_path.name,
                "modified": self._format_timestamp(self._latest_mtime(job_path)),
                "size": self._format_bytes(self._path_size(job_path)),
                "function_summary": function_summary,
                "location": str(job_path),
                "functions": functions,
                "placeholder": False,
            })
        return entries

    def _job_function_entries(self, job_path: Path) -> list[dict[str, str]]:
        try:
            function_dirs = [child for child in job_path.iterdir() if child.is_dir() and not child.name.startswith(".")]
        except OSError:
            return []
        function_dirs.sort(key=lambda path: self._latest_mtime(path), reverse=True)
        functions: list[dict[str, str]] = []
        for function_path in function_dirs:
            file_count = self._file_count(function_path)
            functions.append({
                "name": function_path.name,
                "modified": self._format_timestamp(self._latest_mtime(function_path)),
                "size": self._format_bytes(self._path_size(function_path)),
                "file_count": f"{file_count} file" if file_count == 1 else f"{file_count} files",
                "location": str(function_path),
            })
        return functions

    def _file_count(self, path: Path) -> int:
        if path.is_file():
            return 1
        count = 0
        try:
            for _, _, files in os.walk(path):
                count += len(files)
                if count > 10000:
                    return count
        except OSError:
            return count
        return count

    def _latest_mtime(self, path: Path) -> float:
        try:
            latest = path.stat().st_mtime
        except OSError:
            return 0.0
        if path.is_dir():
            try:
                for root, dirs, files in os.walk(path):
                    for name in dirs + files:
                        try:
                            latest = max(latest, (Path(root) / name).stat().st_mtime)
                        except OSError:
                            continue
            except OSError:
                pass
        return latest

    def _path_size(self, path: Path) -> int:
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total = 0
        file_count = 0
        try:
            for root, _, files in os.walk(path):
                for name in files:
                    file_count += 1
                    if file_count > 10000:
                        return total
                    try:
                        total += (Path(root) / name).stat().st_size
                    except OSError:
                        continue
        except OSError:
            return total
        return total

    def _format_timestamp(self, timestamp: float) -> str:
        if not timestamp:
            return "-"
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %I:%M %p")

    def _format_bytes(self, size: int) -> str:
        value = float(size)
        for unit in ["B", "KB", "MB", "GB"]:
            if value < 1024 or unit == "GB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def _configured_startup_extract_base(self) -> Path:
        # Startup kits are application data, not source-tree content. Keep all
        # assigned-site workspaces directly under ~/.duality-client.
        return WORKSPACES_DIR.expanduser().resolve()

    def _startup_extract_base(self) -> Path:
        return self._configured_startup_extract_base()

    def _expected_workspace_for_site(self) -> Path:
        site = (self.state.site or "__unassigned__").strip()
        return (self._startup_extract_base() / site).expanduser().resolve()

    def _clear_workspace_if_it_points_at_old_demo_home(self) -> None:
        managed_base = self._configured_startup_extract_base()
        changed = self.state.startup_install_base != str(managed_base)
        self.state.startup_install_base = str(managed_base)

        if self.state.workspace_root:
            current = Path(self.state.workspace_root).expanduser().resolve()
            expected = self._expected_workspace_for_site()
            if current != expected:
                self.state.workspace_root = ""
                changed = True

        if changed:
            save_state(self.state)

    def _sync_state_to_ui(self) -> None:
        assigned_site = self._assigned_site()
        self.startup_site_label.setText(assigned_site or "Sign in to resolve your assigned client site")
        self.settings_username_label.setText(self.session.username if self.session else "-")
        self.settings_role_label.setText(self.session.role if self.session else "-")
        self.settings_site_label.setText(assigned_site or "-")
        self.env_combo.setCurrentText(self.state.env)
        self.install_location_edit.setText(str(self._expected_workspace_for_site()) if assigned_site else str(self._startup_extract_base()))
        self.workspace_label.setText(self.state.workspace_root or "-")
        self.job_results_label.setText(
            str(Path(self.state.workspace_root) / self.config.job_results_dir_name)
            if self.state.workspace_root
            else self.config.job_results_dir_name
        )
        self.share_url_combo.setCurrentText(self.state.share_url)
        self.results.port = int(self.state.results_port)
        self.results.job_results_dir_name = self.config.job_results_dir_name
        self._refresh_job_results_table()
        self.refresh_status()

    def _ensure_workspace_installed(self) -> Path | None:
        workspace = self._workspace_path()
        if workspace is not None and (workspace / "startup" / "start.sh").exists():
            return workspace

        tar_path = self._selected_tar_path()
        if tar_path is None:
            self._error(
                "No startup kit is installed. Use Settings > Startup Kit to download and install one."
            )
            return None

        try:
            validate_startup_tar(tar_path, expected_site=self.state.site)
            install = install_startup_tar(
                tar_path,
                self._startup_extract_base(),
                expected_site=self.state.site,
                replace_existing=False,
            )
            workspace = install.workspace
            (workspace / self.config.job_results_dir_name).mkdir(parents=True, exist_ok=True)
            self.state.startup_kit_tar = str(tar_path)
            self.state.workspace_root = str(workspace)
            self.state.startup_install_base = str(workspace.parent)
            save_state(self.state)
            self._sync_state_to_ui()
            self.nvflare_console.append(f"[Desktop] Installed {tar_path} at {workspace}\n")
            return workspace
        except FileExistsError:
            self._error(
                "A workspace already exists in the managed SHARE Client data directory, but it is not currently recorded as the active workspace. "
                "Use Settings > Startup Kit to install or replace it explicitly."
            )
            return None
        except Exception as exc:
            self._error(str(exc))
            return None

    def _selected_tar_path(self) -> Path | None:
        value = self.tar_combo.currentData()
        if not value:
            value = self.state.startup_kit_tar
        if not value:
            return None
        path = Path(str(value)).expanduser().resolve()
        return path if path.exists() else None

    def _workspace_path(self) -> Path | None:
        expected = self._expected_workspace_for_site()
        if not self.state.workspace_root:
            if (expected / "startup" / "start.sh").is_file():
                self.state.workspace_root = str(expected)
                save_state(self.state)
                return expected
            return None

        path = Path(self.state.workspace_root).expanduser().resolve()
        if path != expected:
            self.state.workspace_root = ""
            save_state(self.state)
            return None
        return path if path.exists() else None

    def _job_results_host_dir(self, workspace: Path) -> Path:
        # NVFlare and the embedded Results API share this host directory directly.
        path = workspace / self.config.job_results_dir_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _process_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["DUALITY_TOOLKIT_ROOT"] = str(self.repo_root)
        env["DUALITY_CLIENT_SITE"] = self.state.site
        env["DUALITY_CLIENT_ENV"] = self.state.env
        if self.state.workspace_root:
            workspace = Path(self.state.workspace_root).expanduser().resolve()
            env["DUALITY_CLIENT_WORKSPACE"] = str(workspace)
            env["DUALITY_NVFLARE_WORKSPACE"] = str(workspace)
            job_results_dir = self._job_results_host_dir(workspace)
            env["DUALITY_NVFLARE_JOB_SAVE_LOCATION"] = str(job_results_dir)
            self.nvflare_console.append(f"[Desktop] NVFlare job results host path: {job_results_dir}\n")
        return env

    def _periodic_results_health_check(self) -> None:
        # The embedded runner owns recovery. Three consecutive periodic failures
        # trigger one controlled restart while the app remains open.
        self.results.check_health_async(attempts=1, delay_ms=0, recover=True)

    def _on_nvflare_output(self, text: str) -> None:
        self.last_nvflare_output_at = datetime.now(timezone.utc)
        self.nvflare_console.append(text)
        self.refresh_status()

    def _on_nvflare_state(self, state: str) -> None:
        self.nvflare_console.append(f"[NVFlare state: {state}]\n")
        self.refresh_status()

    def _on_results_output(self, text: str) -> None:
        self.results_console.append(text)

    def _on_results_state(self, state: str) -> None:
        self._last_results_state = state
        if state == "error":
            self._results_service_active = False
        elif state == "stopped":
            self._results_service_active = False
            self._results_health_ok = None
        elif state in {"running", "starting", "restarting", "recovering", "stopping"}:
            self._results_service_active = True

        self.results_console.append(f"[Results state: {state}]\n")
        if state == "running":
            self.results_card.set_state("● Running", f"Embedded Uvicorn · 127.0.0.1:{self.state.results_port}")
            QTimer.singleShot(500, lambda: self.results.check_health_async(attempts=6, delay_ms=500))
        elif state == "stopped":
            self.results_card.set_state("Stopped", f"Embedded Uvicorn · port {self.state.results_port}")
        else:
            self.results_card.set_state(state, f"Embedded Uvicorn · port {self.state.results_port}")
        self.refresh_status()

    def _on_results_health(self, ok: bool, msg: str) -> None:
        self._results_health_ok = ok
        if ok:
            self._results_service_active = True
        elif not self.results.is_running:
            self._results_service_active = False
        self.results_card.set_state("✓ Healthy" if ok else "Unhealthy", msg)
        self.refresh_status()

    def _confirm(self, title: str, message: str) -> bool:
        result = QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return result == QMessageBox.Yes

    def _error(self, message: str) -> None:
        QMessageBox.critical(self, "SHARE Client", message)

    def quit_app(self) -> None:
        # The embedded Results API belongs to this application process. Stop it
        # before quitting; NVFlare remains independently controlled.
        try:
            self.results.shutdown_for_app_exit(timeout_seconds=5)
        except Exception:
            pass
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            self.tray.showMessage("SHARE Client", "Still running in the system tray.", QSystemTrayIcon.Information, 2000)
        else:
            event.accept()
            self.quit_app()
