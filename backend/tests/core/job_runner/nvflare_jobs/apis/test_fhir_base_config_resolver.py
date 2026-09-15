import json
from pathlib import Path

from app.core.job_runner.nvflare_jobs.apis.FHIRBaseConfigResolver import FHIRBaseConfigResolver


def reset():
    FHIRBaseConfigResolver._config_cache = None
    FHIRBaseConfigResolver._config_loaded = False
    FHIRBaseConfigResolver._runtime_base_by_key.clear()
    FHIRBaseConfigResolver._runtime_project_by_base.clear()
    FHIRBaseConfigResolver._runtime_datasource_group_by_base.clear()


def test_register_project_base_supports_group_and_reverse_lookup(tmp_path):
    reset()
    source = str(tmp_path / "data.json")
    FHIRBaseConfigResolver.register_project_base(2, source, 3)

    assert FHIRBaseConfigResolver.get_base_for_project(2, datasource_group_id=3) == source
    assert FHIRBaseConfigResolver.get_base_for_project(2) == source
    assert FHIRBaseConfigResolver.get_project_for_base(source) == "2"
    assert FHIRBaseConfigResolver.get_datasource_group_for_base(source) == "3"


def test_normalize_datasource_value_normalizes_url_and_path(tmp_path):
    reset()
    assert FHIRBaseConfigResolver._normalize_datasource_value(" HTTPS://Example.COM/FHIR/ ") == "https://example.com/FHIR"
    assert FHIRBaseConfigResolver._normalize_datasource_value(str(tmp_path / "x")) == str((tmp_path / "x").resolve())
    assert FHIRBaseConfigResolver._normalize_datasource_value(3) is None


def test_config_file_resolves_group_project_and_reverse_lookup(monkeypatch, tmp_path):
    reset()
    config = tmp_path / "bases.json"
    config.write_text(json.dumps({"projects": {"2": {"1": "https://example/fhir1", "2": "https://example/fhir2"}}}))
    monkeypatch.setenv("DUALITY_NVFLARE_FHIR_BASE_CONFIG", str(config))
    monkeypatch.setenv("DUALITY_NVFLARE_FHIR_BASE", "https://default/fhir")

    assert FHIRBaseConfigResolver.get_base_for_project(2, datasource_group_id=2) == "https://example/fhir2"
    assert FHIRBaseConfigResolver.get_project_for_base("https://example/fhir1/") == "2"
    assert FHIRBaseConfigResolver.get_datasource_group_for_base("https://example/fhir2/") == "2"


def test_simulator_datasource_environment_resolution(monkeypatch, tmp_path):
    reset()
    data = tmp_path / "site1.json"
    data.write_text("{}")
    monkeypatch.setenv("FL_IS_SIMULATOR", "true")
    monkeypatch.setenv("DUALITY_SIM_DATASOURCE_VERSION", "2_1")
    monkeypatch.setenv("DUALITY_CLIENT_SITE1_DATASOURCE_2_1", str(data))

    assert FHIRBaseConfigResolver.get_base_for_project(2, site_name="site-1", datasource_group_id=1) == str(data)
    assert FHIRBaseConfigResolver.get_datasource_group_for_base(str(data)) == "1"
