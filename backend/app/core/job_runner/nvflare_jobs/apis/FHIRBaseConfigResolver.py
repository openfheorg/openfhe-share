import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import urlsplit, urlunsplit


class FHIRBaseConfigResolver:
    _config_cache: Optional[Dict[str, Any]] = None
    _config_loaded: bool = False
    _runtime_base_by_key: Dict[str, str] = {}
    _runtime_project_by_base: Dict[str, str] = {}
    _runtime_datasource_group_by_base: Dict[str, str] = {}

    @classmethod
    def _runtime_key(
        cls,
        project_id: Union[int, str, None],
        datasource_group_id: Union[int, str, None] = None,
    ) -> str:
        project_key = str(project_id) if project_id is not None else ""
        group_key = str(datasource_group_id) if datasource_group_id is not None else ""
        return f"{project_key}::{group_key}"

    @classmethod
    def register_project_base(
        cls,
        project_id: Union[int, str, None],
        datasource_value: Optional[str],
        datasource_group_id: Union[int, str, None] = None,
    ) -> None:
        if project_id is None or datasource_value is None:
            return

        value = str(datasource_value).strip()
        if not value:
            return

        cls._runtime_base_by_key[cls._runtime_key(project_id, datasource_group_id)] = value
        cls._runtime_base_by_key[cls._runtime_key(project_id, None)] = value

        normalized = cls._normalize_datasource_value(value)
        if normalized is not None:
            cls._runtime_project_by_base[normalized] = str(project_id)
            if datasource_group_id is not None and str(datasource_group_id).strip():
                cls._runtime_datasource_group_by_base[normalized] = str(datasource_group_id).strip()

    @classmethod
    def _load_config(cls) -> Optional[Dict[str, Any]]:
        if cls._config_loaded:
            return cls._config_cache

        cls._config_loaded = True
        config_path_str = os.getenv("DUALITY_NVFLARE_FHIR_BASE_CONFIG")
        if not config_path_str:
            cls._config_cache = None
            return None

        config_path = Path(config_path_str)
        if not config_path.is_file():
            cls._config_cache = None
            return None

        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            cls._config_cache = None
            return None

        if isinstance(data, dict):
            cls._config_cache = data
        else:
            cls._config_cache = None

        return cls._config_cache

    @classmethod
    def _get_default_base(cls) -> str:
        return os.getenv("DUALITY_NVFLARE_FHIR_BASE", "")

    @classmethod
    def _is_simulator_mode(cls) -> bool:
        v = os.getenv("FL_IS_SIMULATOR", "").strip().lower()
        return v in ("1", "true", "yes", "on")

    @classmethod
    def _datasource_version_suffix(cls) -> str:
        """Suffix for DUALITY_*_DATASOURCE_<suffix> (e.g. '2_1' -> ..._DATASOURCE_2_1)."""
        v = os.getenv("DUALITY_SIM_DATASOURCE_VERSION", "2_1").strip()
        return v if v else "2_1"

    @classmethod
    def _site_key_fragment(cls, site_name: str) -> str:
        """Maps client names like site-1 / site1 to SITE1 for env keys."""
        return re.sub(r"[^A-Za-z0-9]", "", site_name).upper()

    @classmethod
    def _resolve_simulator_datasource_path(cls, site_name: Optional[str]) -> Optional[str]:
        """In NVFlare simulator only: path from DUALITY_SERVER_DATASOURCE_* or DUALITY_CLIENT_SITE*_DATASOURCE_*."""
        if not cls._is_simulator_mode():
            return None
        suffix = cls._datasource_version_suffix()
        if site_name is None or not str(site_name).strip():
            key = f"DUALITY_SERVER_DATASOURCE_{suffix}"
        else:
            frag = cls._site_key_fragment(str(site_name))
            key = f"DUALITY_CLIENT_{frag}_DATASOURCE_{suffix}"
        raw = os.getenv(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    @classmethod
    def _expand_relative_datasource_path(cls, raw: str) -> str:
        """Resolve relative paths from .env (repo-root style) when NVFlare cwd is deep under outputs/."""
        p = Path(raw)
        if p.is_absolute():
            return str(p)
        hint = os.getenv("DUALITY_SIM_DATASOURCE_BASE")
        if hint:
            cand = (Path(hint).expanduser().resolve() / raw).resolve()
            if cand.is_file():
                return str(cand)
        cwd = Path.cwd().resolve()
        for base in [cwd, *list(cwd.parents)[:64]]:
            cand = (base / raw).resolve()
            if cand.is_file():
                return str(cand)
        return raw

    @classmethod
    def _normalize_datasource_value(cls, value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None

        normalized = value.strip()
        if not normalized:
            return None

        lower = normalized.lower()
        if lower.startswith("http://") or lower.startswith("https://"):
            parts = urlsplit(normalized)
            scheme = parts.scheme.lower()
            netloc = parts.netloc.lower()
            path = parts.path.rstrip("/") or "/"
            return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))

        try:
            return str(Path(normalized).expanduser().resolve(strict=False))
        except Exception:
            return normalized

    @classmethod
    def _resolve_project_config_value(
        cls,
        cfg: Dict[str, Any],
        project_id: Union[int, str, None],
        datasource_group_id: Union[int, str, None] = None,
    ) -> Optional[str]:
        key = str(project_id)
        group_key = str(datasource_group_id) if datasource_group_id is not None else None

        direct = cfg.get(key)
        if isinstance(direct, str):
            return direct
        if isinstance(direct, dict) and group_key is not None:
            grouped = direct.get(group_key)
            if isinstance(grouped, str):
                return grouped

        projects = cfg.get("projects")
        if isinstance(projects, dict):
            nested = projects.get(key)
            if isinstance(nested, str):
                return nested
            if isinstance(nested, dict) and group_key is not None:
                grouped = nested.get(group_key)
                if isinstance(grouped, str):
                    return grouped

        return None

    @classmethod
    def get_base_for_project(
        cls,
        project_id: Union[int, str, None],
        site_name: Optional[str] = None,
        datasource_group_id: Union[int, str, None] = None,
    ) -> str:
        runtime_value = cls._runtime_base_by_key.get(cls._runtime_key(project_id, datasource_group_id))
        if runtime_value is not None:
            return runtime_value

        if datasource_group_id is not None:
            runtime_value = cls._runtime_base_by_key.get(cls._runtime_key(project_id, None))
            if runtime_value is not None:
                return runtime_value

        sim_path = cls._resolve_simulator_datasource_path(site_name)
        if sim_path is not None:
            return cls._expand_relative_datasource_path(sim_path)

        default_base = cls._get_default_base()
        cfg = cls._load_config()
        if not cfg:
            return default_base

        value = cls._resolve_project_config_value(
            cfg=cfg,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        )

        if isinstance(value, str) and value.strip():
            return value.strip()

        if datasource_group_id is not None:
            fallback_value = cls._resolve_project_config_value(
                cfg=cfg,
                project_id=project_id,
                datasource_group_id=None,
            )
            if isinstance(fallback_value, str) and fallback_value.strip():
                return fallback_value.strip()

        return default_base

    @classmethod
    def get_datasource_group_for_base(cls, fhir_base: Optional[str]) -> Optional[str]:
        """Return the configured datasource-group id for a runtime FHIR source.

        NVFlare clients receive both a datasource URL/path and a datasource group
        in filters.json. ``register_project_base`` records that association for
        the process so downstream FHIR code can select datasource-owned configs.
        The simulator fallback preserves direct utility/test execution where only
        ``DUALITY_SIM_DATASOURCE_VERSION`` is available (for example ``2_1``).
        """
        target = cls._normalize_datasource_value(fhir_base)
        if target is None:
            return None

        runtime_group = cls._runtime_datasource_group_by_base.get(target)
        if runtime_group is not None:
            return runtime_group

        cfg = cls._load_config()
        if isinstance(cfg, dict):
            containers = []
            projects = cfg.get("projects")
            if isinstance(projects, dict):
                containers.append(projects)
            containers.append(cfg)

            for container in containers:
                for project_key, value in container.items():
                    if project_key == "projects" or not isinstance(value, dict):
                        continue
                    for group_key, grouped_value in value.items():
                        if isinstance(grouped_value, str) and cls._normalize_datasource_value(grouped_value) == target:
                            return str(group_key)

        if cls._is_simulator_mode():
            suffix = os.getenv("DUALITY_SIM_DATASOURCE_VERSION", "").strip()
            match = re.match(r"^\d+_(\d+)$", suffix)
            if match:
                return match.group(1)

        return None

    @classmethod
    def get_project_for_base(cls, fhir_base: Optional[str]) -> Optional[str]:
        target = cls._normalize_datasource_value(fhir_base)
        if target is None:
            return None

        runtime_project = cls._runtime_project_by_base.get(target)
        if runtime_project is not None:
            return runtime_project

        cfg = cls._load_config()
        if not cfg:
            return None

        projects = cfg.get("projects")
        if isinstance(projects, dict):
            for key, value in projects.items():
                if isinstance(value, str):
                    if cls._normalize_datasource_value(value) == target:
                        return str(key)
                elif isinstance(value, dict):
                    for grouped_value in value.values():
                        if cls._normalize_datasource_value(grouped_value) == target:
                            return str(key)

        for key, value in cfg.items():
            if key == "projects":
                continue
            if isinstance(value, str):
                if cls._normalize_datasource_value(value) == target:
                    return str(key)
            elif isinstance(value, dict):
                for grouped_value in value.values():
                    if cls._normalize_datasource_value(grouped_value) == target:
                        return str(key)

        return None
