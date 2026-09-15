from pathlib import Path

from app.core.EnvironmentManager import Environment
from app.core.nvflare.NVFlareServerProvider import NVFlareProvisionProvider


def test_local_provision_uses_workspace_host_and_default_results(monkeypatch, tmp_path):
    monkeypatch.setenv("DUALITY_NVFLARE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DUALITY_NVFLARE_HOST", "server.example")
    monkeypatch.delenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", raising=False)

    provision = NVFlareProvisionProvider.get_nvflare_instance(Environment.LOCAL)

    base = Path(provision.base_location)
    assert base == (tmp_path / "workspace").resolve()
    assert Path(provision.admin_location) == base / "admin@share.local"
    assert Path(provision.server_location) == base / "server.example"
    assert Path(provision.client_to_server_job_save_location) == base / "job-results"


def test_local_provision_honors_explicit_job_save(monkeypatch, tmp_path):
    monkeypatch.setenv("DUALITY_NVFLARE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path / "results"))

    provision = NVFlareProvisionProvider.get_nvflare_instance(Environment.LOCAL)

    assert Path(provision.client_to_server_job_save_location) == (tmp_path / "results").resolve()


def test_dev_provision_has_expected_admin_and_site_results_paths():
    provision = NVFlareProvisionProvider.get_nvflare_instance(Environment.DEV)
    assert provision.admin_location.endswith("/admin@share.local")
    assert provision.server_location.endswith("/nvflare.example.org")
    assert provision.client_to_server_job_save_location.endswith("/site3/job-results")
