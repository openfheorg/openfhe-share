# checks if MySQL is reachable and if not tries to install and start it
# loads environment only from .env.local at the repo root or from a provided path
# verifies tcp connectivity and simple auth using mysqlclient or pymysql
# supports basic install flows for macOS with brew and Windows with chocolatey

import os
import sys
import time
import socket
import subprocess
import platform

# repo root is the parent directory of this file's directory
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

def info(m): print("[INFO] " + str(m), flush=True)
def warn(m): print("[WARN] " + str(m), flush=True)
def err(m):  print("[ERROR] " + str(m), flush=True)

# load key value pairs from a .env style file into environment if not already set
# only .env.local is supported by default
def load_env(path: str | None = None):
    # resolve path to use
    if path:
        p = path
        if not os.path.isabs(p):
            p = os.path.join(REPO_ROOT, p)
    else:
        p = os.path.join(REPO_ROOT, ".env.local")

    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        info("Loaded env from " + p)
        return

    err(".env.local not found at " + p)
    sys.exit(1)

# wait for a tcp port to be reachable up to a small timeout
def wait_tcp(host, port, seconds=3):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False

# check if a command is on path
def has(cmd):
    try:
        subprocess.run([cmd, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

# install one or more pip packages and return success
def pip_install(pkgs: list[str]) -> bool:
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + pkgs
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            warn("pip install failed for: " + " ".join(pkgs))
            return False
        return True
    except Exception as e:
        warn("pip install exception: " + str(e))
        return False

# ensure mysqlclient or pymysql is installed and usable
def ensure_mysql_python_deps():
    try:
        pip_install(["mysqlclient"])
    except Exception:
        pass
    try:
        pip_install(["PyMySQL"])
    except Exception:
        pass

    have_mysqlclient = False
    try:
        import MySQLdb  # type: ignore
        have_mysqlclient = True
    except Exception:
        pass

    have_pymysql = False
    try:
        import pymysql  # noqa
        have_pymysql = True
    except Exception:
        pass

    if not have_mysqlclient and have_pymysql:
        try:
            import pymysql
            pymysql.install_as_MySQLdb()
            have_mysqlclient = True
        except Exception:
            pass

    if not have_mysqlclient and not have_pymysql:
        warn("Neither mysqlclient nor PyMySQL could be installed; MySQL auth attempts may fail.")


# attempt a simple auth connect using whichever driver is available
def _py_auth_connect(host: str, port: int, user: str, pwd: str) -> bool:
    try:
        import MySQLdb  # type: ignore
    except Exception:
        try:
            import pymysql as MySQLdb  # type: ignore
        except Exception:
            return False

    try:
        conn = MySQLdb.connect(host=host, user=user, passwd=pwd, port=port, connect_timeout=3)
        try:
            conn.close()
        except Exception:
            pass
        return True
    except Exception:
        return False

# try provider style host handling such as localhost and 127.0.0.1
def try_connect_like_provider(host: str, port: int, user: str, pwd: str) -> bool:
    if _py_auth_connect(host, port, user, pwd):
        return True
    if host.lower() == "localhost":
        if _py_auth_connect("127.0.0.1", port, user, pwd):
            return True
    return False

# install mysql based on the current platform
def install_mysql():
    os_name = platform.system()
    if os_name == "Darwin":
        if not has("brew"):
            err("Homebrew not found. Install from https://brew.sh and re-run.")
            sys.exit(1)
        info("Installing MySQL via Homebrew...")
        subprocess.run(["brew", "install", "mysql@8.0"], check=True)
        info("Starting MySQL service...")
        subprocess.run(["brew", "services", "start", "mysql@8.0"], check=True)
        return

    if os_name == "Windows":
        if not has("choco"):
            info("Chocolatey not found; attempting to install and will request admin consent")
            try:
                from utils.windows_choco_installer import install_chocolatey
            except Exception as e:
                err("Could not import windows_choco_installer: " + str(e))
                sys.exit(1)
            ok = False
            try:
                ok = bool(install_chocolatey())
            except Exception as e:
                err("Chocolatey installation failed or was declined: " + str(e))
            if not ok or not has("choco"):
                err("Chocolatey not available. Install MySQL manually or install Chocolatey and re-run.")
                sys.exit(1)

        info("Installing MySQL via Chocolatey...")
        subprocess.run(["choco", "install", "-y", "mysql"], check=True)
        for svc in ("MySQL80", "mysql"):
            try:
                subprocess.run(
                    'powershell -NoProfile -Command "Start-Service -Name ' + svc + '"',
                    check=False,
                    shell=True,
                )
            except Exception:
                pass
        return

    err("Unsupported OS. Only macOS and Windows are handled by this script.")
    sys.exit(1)

# orchestrator entry point for the mysql stage
def run() -> int:
    load_env()

    ensure_mysql_python_deps()

    host = os.environ.get("DUALITY_MYSQL_HOST", "localhost") or "localhost"
    port = int(os.environ.get("DUALITY_MYSQL_PORT", "3306"))
    user = os.environ.get("DUALITY_MYSQL_USER", "")
    pwd  = os.environ.get("DUALITY_MYSQL_PASSWORD", "")

    tcp_ok = wait_tcp(host if host.lower() != "localhost" else "127.0.0.1", port, seconds=3) \
             or wait_tcp("127.0.0.1", port, seconds=3)

    if tcp_ok:
        if try_connect_like_provider(host, port, user, pwd):
            print("MySQL reachable, authentication OK.")
            return 0
        else:
            print("MySQL reachable, but authentication FAILED.")
            return 2

    install_mysql()
    if not wait_tcp("127.0.0.1", 3306, seconds=180):
        err("MySQL did not become reachable after install or start.")
        return 3

    ensure_mysql_python_deps()

    if try_connect_like_provider("localhost", 3306, user, pwd):
        print("MySQL installed, authentication OK.")
        return 0
    else:
        print("MySQL installed, but authentication FAILED.")
        print("If this is a fresh install, verify the credentials in your env file.")
        return 4

if __name__ == "__main__":
    print("This script is meant to be run via the orchestrator.")
    print("Use:  python main.py mysql")
    sys.exit(1)
