from unittest.mock import patch

from app.core.EnvironmentManager import Environment
from app.core.aws.ResourceConfigProvider import ResourceConfigProvider
from app.core.aws.SecretsManager import MySQLSecret


def test_local_mysql_config_uses_environment(monkeypatch):
    monkeypatch.setenv("DUALITY_MYSQL_HOST", "mysql.local")
    monkeypatch.setenv("DUALITY_MYSQL_PORT", "3307")
    monkeypatch.setenv("DUALITY_MYSQL_USER", "tester")
    monkeypatch.setenv("DUALITY_MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("DUALITY_MYSQL_DB", "unit_db")

    cfg = ResourceConfigProvider.get_mysql_config(Environment.LOCAL)

    assert cfg == MySQLSecret("tester", "secret", "mysql.local", 3307, "unit_db")


def test_local_ssh_config_is_blank():
    cfg = ResourceConfigProvider.get_nvflare_ec2_ssh_config(Environment.LOCAL)
    assert cfg.host == ""
    assert cfg.username == ""
    assert cfg.port == 22


def test_dev_mysql_config_uses_secret_password_and_fixed_cluster():
    secret = MySQLSecret("aws_user", "rotating", "ignored", 9999, "ignored")
    with patch(
        "app.core.aws.ResourceConfigProvider.SecretsManager.get_mysql_secret",
        return_value=secret,
    ) as get_secret:
        cfg = ResourceConfigProvider.get_mysql_config(Environment.DEV, check_cached=False)

    get_secret.assert_called_once_with(
        secret_name="example-database-secret",
        check_cached=False,
    )
    assert cfg.username == "aws_user"
    assert cfg.password == "rotating"
    assert cfg.dbname == "duality_dev"
    assert cfg.port == 3306
