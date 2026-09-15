import json
from unittest.mock import Mock, patch

import pytest

from app.core.aws.SecretsManager import MySQLSecret, SecretsManager


def test_get_mysql_secret_requires_name():
    with pytest.raises(ValueError, match="No secret_name"):
        SecretsManager.get_mysql_secret("")


def test_get_mysql_secret_returns_cached_value():
    cached = MySQLSecret("u", "p", "h", 3306, "d")
    SecretsManager._cached_mysql_secret = cached
    SecretsManager._client = Mock()

    assert SecretsManager.get_mysql_secret("ignored") is cached
    SecretsManager._client.get_secret_value.assert_not_called()


def test_get_mysql_secret_parses_secret_string():
    SecretsManager._client = Mock()
    SecretsManager._client.get_secret_value.return_value = {
        "SecretString": json.dumps({"username": "u", "password": "p", "port": "3307"})
    }

    value = SecretsManager.get_mysql_secret("mysql", check_cached=False)

    assert value == MySQLSecret("u", "p", "", 3307, "duality_dev")


def test_get_mysql_secret_retries_then_raises():
    SecretsManager._client = Mock()
    SecretsManager._client.get_secret_value.side_effect = RuntimeError("AWS unavailable")

    with patch("app.core.aws.SecretsManager.time.sleep") as sleep:
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            SecretsManager.get_mysql_secret("mysql", check_cached=False)

    assert SecretsManager._client.get_secret_value.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2, 4]
