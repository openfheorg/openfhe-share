import json
from pathlib import Path
from unittest.mock import patch

from app.core.EnvironmentManager import Environment
from app.core.mysql.SupportedFunction import SupportedFunction
from app.core.mysql.job_tracking.NVFlareJobsDataRetriever import NVFlareJobsDataRetriever
from app.core.nvflare.NVFlareServerProvider import NVFlareProvision


def _make_retriever(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path))
    provision = NVFlareProvision("/workspace", "/admin", "/server", str(tmp_path))
    with patch(
        "app.core.mysql.job_tracking.NVFlareJobsDataRetriever.NVFlareProvisionProvider.get_nvflare_instance",
        return_value=provision,
    ), patch(
        "app.core.mysql.job_tracking.NVFlareJobsDataRetriever.EnvironmentProvider.get_env",
        return_value=Environment.LOCAL,
    ):
        return NVFlareJobsDataRetriever("nv-job", SupportedFunction.MEAN)


def test_read_local_json_reports_missing_and_invalid_json(tmp_path, monkeypatch):
    retriever = _make_retriever(tmp_path, monkeypatch)
    data, error = retriever._read_local_json(str(tmp_path / "missing.json"))
    assert data == {}
    assert "not found" in error

    bad = tmp_path / "bad.json"
    bad.write_text("{")
    data, error = retriever._read_local_json(str(bad))
    assert data == {}
    assert "Invalid JSON" in error


def test_prefer_raw_uses_raw_before_results(tmp_path, monkeypatch):
    retriever = _make_retriever(tmp_path, monkeypatch)
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "results.json").write_text(json.dumps({"value": "results"}))
    (folder / "raw_results.json").write_text(json.dumps({"value": "raw"}))

    data, error, used = retriever._read_prefer_raw(str(folder))

    assert data == {"value": "raw"}
    assert error == ""
    assert used.endswith("raw_results.json")


def test_list_workflow_dirs_and_retrieve_data_locally(tmp_path, monkeypatch):
    retriever = _make_retriever(tmp_path, monkeypatch)
    workflow = tmp_path / "nv-job" / "mean" / "wf1"
    (workflow / "initiator").mkdir(parents=True)
    (workflow / "aggregated").mkdir()
    (workflow / "initiator" / "raw_results.json").write_text(json.dumps({"a": 1}))
    (workflow / "aggregated" / "results.json").write_text(json.dumps({"b": 2}))
    (workflow / "aggregated" / "processed_results.json").write_text(json.dumps({"c": 3}))

    assert retriever.list_workflow_dirs() == ["wf1"]
    result = retriever.retrieve_workflow_data("wf1")
    assert result["initiator_results"] == {"a": 1}
    assert result["aggregate_results"] == {"b": 2}
    assert result["aggregate_processed_results"] == {"c": 3}
    assert result["workflow_error"] is None


def test_initiator_falls_back_to_client_error(tmp_path, monkeypatch):
    retriever = _make_retriever(tmp_path, monkeypatch)
    workflow = tmp_path / "workflow"
    site = workflow / "client" / "site1"
    site.mkdir(parents=True)
    (site / "error.json").write_text(json.dumps({"error": "client failed"}))

    data, error, used = retriever._read_initiator_results(str(workflow))

    assert data == {"error": "client failed"}
    assert error == ""
    assert Path(used) == site / "error.json"
