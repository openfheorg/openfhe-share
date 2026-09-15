from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from share_desktop.paths import STATE_PATH, ensure_app_dirs


@dataclass
class SiteWorkspaceState:
    startup_kit_tar: str = ""
    startup_install_base: str = ""
    workspace_root: str = ""

    @classmethod
    def from_value(cls, value: object) -> "SiteWorkspaceState":
        if not isinstance(value, dict):
            return cls()
        return cls(
            startup_kit_tar=str(value.get("startup_kit_tar") or ""),
            startup_install_base=str(value.get("startup_install_base") or ""),
            workspace_root=str(value.get("workspace_root") or ""),
        )


@dataclass
class DesktopState:
    # site is the most recently activated site, not an authenticated session.
    # Login is intentionally kept in memory only.
    site: str = ""
    env: str = "aws"
    startup_kit_tar: str = ""
    startup_install_base: str = ""
    workspace_root: str = ""
    results_port: int = 8088
    share_url: str = "http://localhost:3000"
    site_workspaces: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def startup_dir(self) -> Path | None:
        if not self.workspace_root:
            return None
        return Path(self.workspace_root).expanduser().resolve() / "startup"

    @property
    def job_results_dir(self) -> Path | None:
        if not self.workspace_root:
            return None
        return Path(self.workspace_root).expanduser().resolve() / "job-results"

    def remember_active_site(self) -> None:
        site = (self.site or "").strip()
        if not site:
            return
        self.site_workspaces[site] = asdict(
            SiteWorkspaceState(
                startup_kit_tar=self.startup_kit_tar,
                startup_install_base=self.startup_install_base,
                workspace_root=self.workspace_root,
            )
        )

    def activate_site(self, site: str, default_install_base: str = "") -> None:
        normalized_site = (site or "").strip()
        if not normalized_site:
            raise ValueError("An assigned client site is required.")

        self.remember_active_site()
        self.site = normalized_site
        saved = SiteWorkspaceState.from_value(self.site_workspaces.get(normalized_site))
        self.startup_kit_tar = saved.startup_kit_tar
        self.startup_install_base = saved.startup_install_base or default_install_base
        self.workspace_root = saved.workspace_root

    def clear_active_workspace(self) -> None:
        self.startup_kit_tar = ""
        self.workspace_root = ""
        self.remember_active_site()


def load_state() -> DesktopState:
    ensure_app_dirs()
    if not STATE_PATH.exists():
        return DesktopState()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return DesktopState()

        state = DesktopState(
            site=str(data.get("site") or ""),
            env=str(data.get("env") or "aws"),
            startup_kit_tar=str(data.get("startup_kit_tar") or ""),
            startup_install_base=str(data.get("startup_install_base") or ""),
            workspace_root=str(data.get("workspace_root") or ""),
            results_port=_safe_int(data.get("results_port"), 8088),
            share_url=str(data.get("share_url") or "http://localhost:3000"),
            site_workspaces=_normalize_site_workspaces(data.get("site_workspaces")),
        )

        # Migrate the pre-login flat state into the per-site map once.
        if state.site and state.site not in state.site_workspaces and (
            state.startup_kit_tar or state.startup_install_base or state.workspace_root
        ):
            state.remember_active_site()
        return state
    except Exception:
        return DesktopState()


def save_state(state: DesktopState) -> None:
    ensure_app_dirs()
    state.remember_active_site()
    STATE_PATH.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def _normalize_site_workspaces(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for raw_site, raw_state in value.items():
        site = str(raw_site or "").strip()
        if not site:
            continue
        normalized[site] = asdict(SiteWorkspaceState.from_value(raw_state))
    return normalized


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
