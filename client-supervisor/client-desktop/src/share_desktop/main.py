from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from share_desktop.app_window import DualityClientWindow
from share_desktop.config import load_config
from share_desktop.icons import client_icon
from share_desktop.paths import resolve_repo_root
from share_desktop.theme import apply_share_theme


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SHARE Client desktop")
    parser.add_argument(
        "--repo-root",
        default="",
        help="Path to the client-supervisor root containing local-results-api/ and install.ini. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Optional INI config override. Defaults to client-desktop/share-client.ini plus ~/.duality-client/share-client.ini.",
    )
    parser.add_argument(
        "--env",
        default="",
        help="Client environment. Overrides config default_env.",
    )
    # Retained only so older desktop shortcuts do not fail. The authenticated
    # /user/role response is now the sole source of the client site.
    parser.add_argument("--site", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = resolve_repo_root(Path(args.repo_root).expanduser() if args.repo_root else None)
    config = load_config(repo_root, Path(args.config).expanduser() if args.config else None)

    app = QApplication(sys.argv)
    app.setApplicationName("SHARE Client")
    app.setWindowIcon(client_icon("idle"))
    apply_share_theme(app)
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())

    window = DualityClientWindow(
        repo_root=repo_root,
        config=config,
        initial_env=args.env.strip() or config.default_env,
    )
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
