from unittest.mock import MagicMock

import pytest

from app.core.ssh.SSHConnectionProvider import SSHConnectionProvider


def _provider_without_init():
    return object.__new__(SSHConnectionProvider)


def test_download_once_uses_sftp_and_releases_connection():
    provider = _provider_without_init()
    connection = MagicMock()
    sftp = MagicMock()
    connection.open_sftp.return_value = sftp
    provider.get_connection = MagicMock(return_value=connection)
    provider.release_connection = MagicMock()

    provider._download_once("/remote/site4.tar.gz", "/tmp/site4.tar.gz")

    sftp.get.assert_called_once_with(
        "/remote/site4.tar.gz",
        "/tmp/site4.tar.gz",
    )
    sftp.close.assert_called_once_with()
    provider.release_connection.assert_called_once_with(connection)


def test_download_retries_transient_errors(monkeypatch):
    provider = _provider_without_init()
    provider._download_once = MagicMock(side_effect=[OSError("closed"), None])
    sleep = MagicMock()
    monkeypatch.setattr("app.core.ssh.SSHConnectionProvider.time.sleep", sleep)

    provider.download("/remote/site4.tar.gz", "/tmp/site4.tar.gz", retries=2)

    assert provider._download_once.call_count == 2
    sleep.assert_called_once_with(1)


def test_download_raises_after_retry_exhaustion(monkeypatch):
    provider = _provider_without_init()
    provider._download_once = MagicMock(side_effect=OSError("closed"))
    monkeypatch.setattr(
        "app.core.ssh.SSHConnectionProvider.time.sleep",
        lambda _seconds: None,
    )

    with pytest.raises(RuntimeError, match="SSH unavailable after reconnect attempts"):
        provider.download("/remote/site4.tar.gz", "/tmp/site4.tar.gz", retries=1)

    assert provider._download_once.call_count == 2
