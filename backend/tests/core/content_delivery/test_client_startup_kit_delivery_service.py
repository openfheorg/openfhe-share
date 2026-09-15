from pathlib import Path
import tarfile
from unittest.mock import patch

import pytest

from app.core.content_delivery.ClientStartupKitDeliveryService import (
    ClientSiteNotFoundError,
    ClientStartupKitDeliveryService,
    InvalidClientNameError,
    InvalidClientSiteError,
)
from app.core.nvflare.NVFlareServerProvider import NVFlareProvision


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    provision = NVFlareProvision(
        base_location=str(root),
        admin_location=str(root / "admin@share.local"),
        server_location=str(root / "server"),
        client_to_server_job_save_location=str(root / "job-results"),
    )
    with patch(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "NVFlareProvisionProvider.get_nvflare_instance",
        return_value=provision,
    ):
        yield root


def test_create_archive_packages_site_and_excludes_python_cache(workspace):
    startup = workspace / "site2" / "startup"
    startup.mkdir(parents=True)
    (startup / "start.sh").write_text("#!/bin/bash\n")
    cache = workspace / "site2" / "__pycache__"
    cache.mkdir()
    (cache / "cached.pyc").write_bytes(b"cache")
    (workspace / "site2" / "compiled.pyo").write_bytes(b"compiled")

    artifact = ClientStartupKitDeliveryService().create_archive("site2")
    try:
        with tarfile.open(artifact.path, "r:gz") as archive:
            names = set(archive.getnames())
        assert "site2/startup/start.sh" in names
        assert "site2/__pycache__" not in names
        assert "site2/compiled.pyo" not in names
        assert len(artifact.sha256) == 64
    finally:
        artifact.cleanup()
    assert not artifact.path.exists()


def test_normalizes_flattened_windows_permissions(workspace, monkeypatch):
    startup = workspace / "site2" / "startup"
    startup.mkdir(parents=True)
    regular = startup / "client.key"
    regular.write_text("secret")
    script = startup / "stop_fl.sh"
    script.write_text("#!/bin/bash\n")
    # Windows does not expose meaningful POSIX chmod state. Force the
    # Docker Desktop flattened-permission branch and verify the archive modes
    # produced by that branch rather than relying on host chmod behavior.
    monkeypatch.setattr(
        ClientStartupKitDeliveryService,
        "_permissions_are_flattened",
        staticmethod(lambda _site_path: True),
    )

    artifact = ClientStartupKitDeliveryService().create_archive("site2")
    try:
        with tarfile.open(artifact.path, "r:gz") as archive:
            members = {member.name: member for member in archive.getmembers()}
        assert members["site2"].mode == 0o755
        assert members["site2/startup"].mode == 0o755
        assert members["site2/startup/client.key"].mode == 0o644
        assert members["site2/startup/stop_fl.sh"].mode == 0o755
    finally:
        artifact.cleanup()


def test_preserves_member_permissions_when_normalization_is_disabled():
    directory = tarfile.TarInfo("site2")
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o750

    regular = tarfile.TarInfo("site2/startup/client.key")
    regular.type = tarfile.REGTYPE
    regular.mode = 0o600

    script = tarfile.TarInfo("site2/startup/stop_fl.sh")
    script.type = tarfile.REGTYPE
    script.mode = 0o700

    for member, expected_mode in (
        (directory, 0o750),
        (regular, 0o600),
        (script, 0o700),
    ):
        filtered = ClientStartupKitDeliveryService._archive_filter(
            member,
            normalize_permissions=False,
        )
        assert filtered is member
        assert filtered.mode == expected_mode


@pytest.mark.parametrize("name", ["../site2", "site2/other", "/site2", "site 2"])
def test_rejects_unsafe_client_names(workspace, name):
    with pytest.raises(InvalidClientNameError):
        ClientStartupKitDeliveryService().create_archive(name)


def test_reports_missing_site(workspace):
    with pytest.raises(ClientSiteNotFoundError):
        ClientStartupKitDeliveryService().create_archive("site99")


def test_requires_startup_folder(workspace):
    (workspace / "site2").mkdir()
    with pytest.raises(InvalidClientSiteError):
        ClientStartupKitDeliveryService().create_archive("site2")


def _remote_provision():
    return NVFlareProvision(
        base_location="/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00",
        admin_location="/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/admin@share.local",
        server_location="/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/server",
        client_to_server_job_save_location="/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/site3/job-results",
    )


def test_non_local_archive_is_built_on_ec2_and_downloaded(monkeypatch):
    from unittest.mock import MagicMock

    from app.core.EnvironmentManager import Environment

    ssh = MagicMock()
    ssh.run.side_effect = [
        (0, "OK", ""),
        (0, "", ""),
        (0, "", ""),
    ]

    def download(remote_path, local_path, retries):
        assert "/tar_files/.site4." in remote_path
        assert remote_path.endswith(".tar.gz.tmp")
        assert retries == 2
        Path(local_path).write_bytes(b"remote startup kit")

    ssh.download.side_effect = download

    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "EnvironmentProvider.get_env",
        lambda: Environment.DEV,
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "NVFlareProvisionProvider.get_nvflare_instance",
        lambda: _remote_provision(),
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "SSHConnectionProvider.get_instance",
        lambda: ssh,
    )

    artifact = ClientStartupKitDeliveryService().create_archive("site4")
    try:
        assert artifact.path.read_bytes() == b"remote startup kit"
        assert artifact.size_bytes == len(b"remote startup kit")
        assert len(artifact.sha256) == 64
        assert artifact.download_filename == "share-client-site4-startup-kit.tar.gz"

        validation_command = ssh.run.call_args_list[0].args[0]
        archive_command = ssh.run.call_args_list[1].args[0]
        cleanup_command = ssh.run.call_args_list[2].args[0]

        assert "WORKSPACE_MISSING" in validation_command
        assert "SITE_MISSING" in validation_command
        assert "STARTUP_MISSING" in validation_command
        assert "tar_files/site4.tar.gz" in archive_command
        assert "--exclude='*/__pycache__'" in archive_command
        assert "--exclude='*.pyc'" in archive_command
        assert "--exclude='*.pyo'" in archive_command
        assert "-C /home/ubuntu/nvflare/workspace/duality_nvflare/prod_00 site4" in archive_command
        assert "ln " in archive_command
        assert "mv -f " in archive_command
        assert cleanup_command.startswith("rm -f ")
    finally:
        artifact.cleanup()


def test_non_local_archive_reports_missing_remote_site(monkeypatch):
    from unittest.mock import MagicMock

    from app.core.EnvironmentManager import Environment

    ssh = MagicMock()
    ssh.run.side_effect = [
        (0, "SITE_MISSING", ""),
        (0, "", ""),
    ]

    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "EnvironmentProvider.get_env",
        lambda: Environment.DEV,
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "NVFlareProvisionProvider.get_nvflare_instance",
        lambda: _remote_provision(),
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "SSHConnectionProvider.get_instance",
        lambda: ssh,
    )

    with pytest.raises(ClientSiteNotFoundError):
        ClientStartupKitDeliveryService().create_archive("site99")

    ssh.download.assert_not_called()


def test_non_local_archive_requires_remote_startup_folder(monkeypatch):
    from unittest.mock import MagicMock

    from app.core.EnvironmentManager import Environment

    ssh = MagicMock()
    ssh.run.side_effect = [
        (0, "STARTUP_MISSING", ""),
        (0, "", ""),
    ]

    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "EnvironmentProvider.get_env",
        lambda: Environment.PROD,
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "NVFlareProvisionProvider.get_nvflare_instance",
        lambda: _remote_provision(),
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "SSHConnectionProvider.get_instance",
        lambda: ssh,
    )

    with pytest.raises(InvalidClientSiteError):
        ClientStartupKitDeliveryService().create_archive("site4")

    ssh.download.assert_not_called()


def test_non_local_download_failure_removes_partial_local_archive(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from app.core.EnvironmentManager import Environment
    from app.core.content_delivery.ClientStartupKitDeliveryService import (
        ClientStartupKitDeliveryError,
    )

    partial_archive = tmp_path / "partial.tar.gz"
    ssh = MagicMock()
    ssh.run.side_effect = [
        (0, "OK", ""),
        (0, "", ""),
        (0, "", ""),
    ]

    def failed_download(_remote_path, local_path, retries):
        assert retries == 2
        Path(local_path).write_bytes(b"partial")
        raise RuntimeError("download failed")

    ssh.download.side_effect = failed_download

    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "EnvironmentProvider.get_env",
        lambda: Environment.TEST,
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "NVFlareProvisionProvider.get_nvflare_instance",
        lambda: _remote_provision(),
    )
    monkeypatch.setattr(
        "app.core.content_delivery.ClientStartupKitDeliveryService."
        "SSHConnectionProvider.get_instance",
        lambda: ssh,
    )
    monkeypatch.setattr(
        ClientStartupKitDeliveryService,
        "_create_temp_archive_path",
        staticmethod(lambda _client_name: partial_archive),
    )

    with pytest.raises(ClientStartupKitDeliveryError):
        ClientStartupKitDeliveryService().create_archive("site4")

    assert not partial_archive.exists()
