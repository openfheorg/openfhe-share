from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


ASSET_DIR = Path(__file__).resolve().parent / "assets"
ICON_DIR = ASSET_DIR / "icons"
BRANDING_DIR = ASSET_DIR / "branding"
_VALID_STATES = {"idle", "active", "error"}


def icon_path(state: str = "idle") -> Path:
    """Return the packaged SHARE Client icon path for a status state."""
    normalized = (state or "idle").strip().lower()
    if normalized not in _VALID_STATES:
        normalized = "idle"
    return ICON_DIR / f"share-client-{normalized}.png"


def brand_logo_path() -> Path:
    """Return the packaged SHARE wordmark used in the persistent header."""
    return BRANDING_DIR / "share-logo.png"


def login_illustration_path() -> Path:
    """Return the packaged illustration used by the SHARE login card."""
    return BRANDING_DIR / "share-login.png"


def client_icon(state: str = "idle") -> QIcon:
    """Build a Qt icon for the requested SHARE Client status state."""
    return QIcon(str(icon_path(state)))
