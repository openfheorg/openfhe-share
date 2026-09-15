from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from share_desktop.paths import APP_HOME


DEFAULT_API_BASE = "https://api.example.org"


@dataclass(frozen=True)
class DesktopConfig:
    default_env: str = "aws"
    share_url: str = "http://localhost:3000"
    share_recent_urls: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    results_port: int = 8088
    results_health_interval_seconds: int = 30
    job_results_dir_name: str = "job-results"
    startup_extract_base: str = "app_home"
    content_api_base_url: str = DEFAULT_API_BASE
    startup_kit_download_path: str = "/clients/content/startup-kit"
    startup_kit_download_timeout_seconds: int = 300
    authentication_api_base_url: str = DEFAULT_API_BASE
    user_role_path: str = "/user/role"
    login_timeout_seconds: int = 30
    loaded_from: list[Path] = field(default_factory=list)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_dir_name(value: str, fallback: str) -> str:
    text = (value or "").strip().strip("/")
    if not text or ".." in text or "/" in text or "\\" in text:
        return fallback
    return text


def _safe_positive_int(parser: configparser.ConfigParser, section: str, option: str, fallback: int) -> int:
    try:
        return max(1, parser.getint(section, option, fallback=fallback))
    except ValueError:
        return fallback


def _normalize_path(value: str, fallback: str) -> str:
    normalized = (value or fallback).strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def load_config(repo_root: Path, explicit_config: Path | None = None) -> DesktopConfig:
    """Load SHARE Client desktop settings from INI files.

    Precedence is:
    1. client-desktop/share-client.ini inside the repo/prototype folder
    2. ~/.duality-client/share-client.ini as a local machine override
    3. --config <path> as an explicit final override

    The assigned NVFlare site does not come from configuration. It is resolved
    from the authenticated /user/role response at runtime.
    """
    parser = configparser.ConfigParser()

    candidates: list[Path] = [
        repo_root / "client-desktop" / "share-client.ini",
        APP_HOME / "share-client.ini",
    ]
    if explicit_config is not None:
        candidates.append(explicit_config.expanduser())

    loaded: list[Path] = []
    for candidate in candidates:
        path = candidate.expanduser().resolve()
        if path.exists():
            parser.read(path, encoding="utf-8")
            loaded.append(path)

    default_env = parser.get("client", "default_env", fallback="aws").strip() or "aws"
    share_url = parser.get("share", "url", fallback="http://localhost:3000").strip() or "http://localhost:3000"
    recent_urls = _split_csv(parser.get("share", "recent_urls", fallback=""))
    if share_url not in recent_urls:
        recent_urls.insert(0, share_url)
    if "http://localhost:3000" not in recent_urls:
        recent_urls.append("http://localhost:3000")

    results_port = _safe_positive_int(parser, "results", "port", 8088)
    health_interval = max(5, _safe_positive_int(parser, "results", "health_interval_seconds", 30))

    job_results_dir_name = _safe_dir_name(
        parser.get("nvflare", "job_results_dir_name", fallback="job-results"),
        "job-results",
    )
    startup_extract_base = parser.get("startup_kit", "extract_base", fallback="app_home").strip() or "app_home"

    content_api_base_url = parser.get(
        "content_delivery",
        "api_base_url",
        fallback=DEFAULT_API_BASE,
    ).strip().rstrip("/")
    startup_kit_download_path = _normalize_path(
        parser.get(
            "content_delivery",
            "startup_kit_path",
            fallback="/clients/content/startup-kit",
        ),
        "/clients/content/startup-kit",
    )
    startup_kit_download_timeout_seconds = _safe_positive_int(
        parser,
        "content_delivery",
        "download_timeout_seconds",
        300,
    )

    authentication_api_base_url = parser.get(
        "authentication",
        "api_base_url",
        fallback=content_api_base_url or DEFAULT_API_BASE,
    ).strip().rstrip("/")
    user_role_path = _normalize_path(
        parser.get("authentication", "user_role_path", fallback="/user/role"),
        "/user/role",
    )
    login_timeout_seconds = _safe_positive_int(
        parser,
        "authentication",
        "login_timeout_seconds",
        30,
    )

    return DesktopConfig(
        default_env=default_env,
        share_url=share_url,
        share_recent_urls=recent_urls,
        results_port=results_port,
        results_health_interval_seconds=health_interval,
        job_results_dir_name=job_results_dir_name,
        startup_extract_base=startup_extract_base,
        content_api_base_url=content_api_base_url,
        startup_kit_download_path=startup_kit_download_path,
        startup_kit_download_timeout_seconds=startup_kit_download_timeout_seconds,
        authentication_api_base_url=authentication_api_base_url,
        user_role_path=user_role_path,
        login_timeout_seconds=login_timeout_seconds,
        loaded_from=loaded,
    )
