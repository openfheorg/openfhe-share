"""Shared fixtures for deterministic backend unit tests."""

import os

import pytest

# Prevent boto3 from probing EC2 metadata during test collection.
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("SHARE_ENV", "local")
os.environ.setdefault("DUALITY_ADMIN_TAR", "/tmp/nonexistent-admin-kit.tar.gz")


@pytest.fixture(autouse=True)
def reset_process_caches(monkeypatch):
    """Reset module-level singleton/cache state that can leak between tests."""
    from app.core.EnvironmentManager import EnvironmentProvider

    EnvironmentProvider._cached_env = None
    monkeypatch.setenv("SHARE_ENV", "local")

    try:
        from app.core.aws.SecretsManager import SecretsManager

        SecretsManager._cached_mysql_secret = None
    except Exception:
        pass

    try:
        from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider

        MySQLConnectionProvider._instance = None
    except Exception:
        pass

    yield

    EnvironmentProvider._cached_env = None
