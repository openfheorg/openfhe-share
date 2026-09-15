from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.job_runner.nvflare_jobs.apis.fhir.fhir_project_config import (
    _normalized_key,
    resolve_project_config_path,
)


def test_normalized_key():
    assert _normalized_key(None) is None
    assert _normalized_key("  ") is None
    assert _normalized_key(" 2 ") == "2"


def test_resolve_project_config_prefers_datasource_group_then_project_then_default(tmp_path):
    root = tmp_path / "config"
    group = root / "project_2" / "datasource_group_1"
    project = root / "project_2"
    group.mkdir(parents=True)
    (group / "cfg.json").write_text("group")
    (project / "cfg.json").write_text("project")
    (root / "cfg.json").write_text("default")

    with patch(
        "app.core.job_runner.nvflare_jobs.apis.fhir.fhir_project_config._candidate_config_roots",
        return_value=[root],
    ):
        assert resolve_project_config_path("pkg", "cfg.json", 2, 1) == group / "cfg.json"
        (group / "cfg.json").unlink()
        assert resolve_project_config_path("pkg", "cfg.json", 2, 1) == project / "cfg.json"
        (project / "cfg.json").unlink()
        assert resolve_project_config_path("pkg", "cfg.json", 2, 1) == root / "cfg.json"


def test_resolve_project_config_defaults_missing_project_to_project_1(tmp_path):
    root = tmp_path / "config"
    target = root / "project_1" / "cfg.json"
    target.parent.mkdir(parents=True)
    target.write_text("project1")
    with patch(
        "app.core.job_runner.nvflare_jobs.apis.fhir.fhir_project_config._candidate_config_roots",
        return_value=[root],
    ):
        assert resolve_project_config_path("pkg", "cfg.json") == target


def test_resolve_project_config_reports_search_paths(tmp_path):
    root = tmp_path / "config"
    root.mkdir()
    with patch(
        "app.core.job_runner.nvflare_jobs.apis.fhir.fhir_project_config._candidate_config_roots",
        return_value=[root],
    ):
        with pytest.raises(FileNotFoundError, match="Searched"):
            resolve_project_config_path("pkg", "missing.json", 2, 1)
