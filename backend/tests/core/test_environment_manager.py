from unittest.mock import patch

import pytest

from app.core.EnvironmentManager import Environment, EnvironmentProvider


def test_environment_string_values():
    assert str(Environment.DEV) == "dev"
    assert str(Environment.LOCAL) == "local"


def test_get_env_reads_and_caches(monkeypatch):
    monkeypatch.setenv("SHARE_ENV", "test")
    assert EnvironmentProvider.get_env() is Environment.TEST

    monkeypatch.setenv("SHARE_ENV", "prod")
    assert EnvironmentProvider.get_env() is Environment.TEST


def test_get_env_exits_when_missing(monkeypatch):
    monkeypatch.delenv("SHARE_ENV", raising=False)
    with patch("app.core.EnvironmentManager.os._exit", side_effect=SystemExit(1)) as exit_mock:
        with pytest.raises(SystemExit):
            EnvironmentProvider.get_env()
    exit_mock.assert_called_once_with(1)


def test_get_env_exits_when_invalid(monkeypatch):
    monkeypatch.setenv("SHARE_ENV", "sandbox")
    with patch("app.core.EnvironmentManager.os._exit", side_effect=SystemExit(1)):
        with pytest.raises(SystemExit):
            EnvironmentProvider.get_env()
