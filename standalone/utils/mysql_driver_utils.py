from __future__ import annotations

import importlib
import site
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS_DIR = REPO_ROOT / ".deps" / "python"


def _add_local_deps() -> None:
    LOCAL_DEPS_DIR.mkdir(parents=True, exist_ok=True)
    site.addsitedir(str(LOCAL_DEPS_DIR))


def _import_mysql_connector():
    try:
        return importlib.import_module("mysql.connector"), "mysql.connector"
    except Exception:
        return None, None


def _import_pymysql():
    try:
        return importlib.import_module("pymysql"), "pymysql"
    except Exception:
        return None, None


def _pip_install_local(pkgs: list[str], warn=None) -> bool:
    try:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(LOCAL_DEPS_DIR),
        ] + pkgs
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            if warn:
                warn("pip install failed for: " + " ".join(pkgs))
            return False
        return True
    except Exception as e:
        if warn:
            warn("pip install exception: " + str(e))
        return False


def ensure_mysql_driver(warn=None):
    _add_local_deps()

    for loader in (_import_mysql_connector, _import_pymysql):
        module, driver_name = loader()
        if module is not None:
            return module, driver_name

    _pip_install_local(["mysql-connector-python", "PyMySQL"], warn=warn)
    _add_local_deps()

    for loader in (_import_mysql_connector, _import_pymysql):
        module, driver_name = loader()
        if module is not None:
            return module, driver_name

    return None, None
