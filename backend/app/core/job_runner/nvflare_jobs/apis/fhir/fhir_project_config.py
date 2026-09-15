from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Optional, Union


def _candidate_config_roots(package: str):
    roots = []

    try:
        pkg_root = Path(str(files(package)))
        roots.append(pkg_root / "config")
        roots.append(pkg_root.parent / "config")
    except Exception:
        pass

    file_root = Path(__file__).resolve().parent
    roots.append(file_root / "config")
    roots.append(file_root.parent / "config")

    seen = set()
    unique_roots = []
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)
    return unique_roots


def _normalized_key(value: Optional[Union[int, str]]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def resolve_project_config_path(
    package: str,
    filename: str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> Path:
    """Resolve an FHIR config file with datasource-group overrides.

    Lookup order is deliberately narrow-to-broad so a datasource can own its
    semantic contract while existing project-level configs remain a compatible
    fallback:

      config/project_<project>/datasource_group_<group>/<filename>
      config/project_<project>/<filename>
      config/<filename>

    A caller that has no datasource-group context continues to receive the same
    project-level/default resolution behavior as before.
    """
    roots = _candidate_config_roots(package)
    searched = []

    project_key = _normalized_key(project_id)
    group_key = _normalized_key(datasource_group_id)
    if project_key is None:
        # Supports existing simulator callers that historically defaulted to
        # Project 1 when no project context was supplied.
        project_key = "1"

    project_dir = f"project_{project_key}"
    if group_key is not None:
        group_dir = f"datasource_group_{group_key}"
        for config_root in roots:
            datasource_path = config_root / project_dir / group_dir / filename
            searched.append(str(datasource_path))
            if datasource_path.is_file():
                return datasource_path

    for config_root in roots:
        project_path = config_root / project_dir / filename
        searched.append(str(project_path))
        if project_path.is_file():
            return project_path

    for config_root in roots:
        default_path = config_root / filename
        searched.append(str(default_path))
        if default_path.is_file():
            return default_path

    raise FileNotFoundError(
        "Unable to locate config file "
        f"'{filename}' for project_id='{project_id}', "
        f"datasource_group_id='{datasource_group_id}'. Searched: {searched}"
    )
