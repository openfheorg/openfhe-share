import importlib
import importlib.metadata
import importlib.util
import os
import subprocess
import sys
import threading
from datetime import datetime
from typing import Any, Dict, Optional

PACKAGE_NAME = os.getenv("DUALITY_NVFLARE_LIB_PACKAGE", "duality_nvflare_lib")
_LOCK = threading.Lock()


def _log(message: str) -> None:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    print(f"[{ts}] [DualityWheelRuntime] {message}", flush=True)


def _installed_version() -> Optional[str]:
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None


def _print_completed_output(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, end="", flush=True)


def ensure_duality_nvflare_lib_current() -> Dict[str, Any]:
    """Require an already-installed local wheel; never contact the package registry."""
    with _LOCK:
        installed = _installed_version()
        if installed is None:
            raise RuntimeError(
                f"{PACKAGE_NAME} is not installed. Public simulator/standalone runtimes "
                "require the wheel bundled with the checkout to be installed locally."
            )
        _log(f"local-only wheel; installed={installed}")
        return {
            "status": "local-only",
            "before": installed,
            "after": installed,
            "updated": False,
        }


# Deps the wheel declares in install_requires but that the launchers intentionally
# skip with ``--no-deps``. They are normally baked into the container image, but to be robust
# against an image that predates them (or a venv where they were never installed)
# we install any that are missing once per process, from PyPI (not the duality
# package index, which only serves duality_nvflare_lib).
_EXTRA_RUNTIME_DEPS = {"statsmodels": "statsmodels==0.14.4"}
_extra_deps_ensured = False


def _ensure_extra_runtime_deps() -> None:
    global _extra_deps_ensured
    if _extra_deps_ensured:
        return
    _extra_deps_ensured = True
    missing = [
        spec for mod, spec in _EXTRA_RUNTIME_DEPS.items()
        if importlib.util.find_spec(mod) is None
    ]
    if not missing:
        return
    _log(f"installing missing runtime deps from PyPI: {missing}")
    completed = subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
            "--index-url", "https://pypi.org/simple", *missing,
        ],
        text=True,
        capture_output=True,
    )
    _print_completed_output(completed)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Failed to install runtime deps {missing}; pip exited with {completed.returncode}"
        )


def build_component(module_name: str, class_name: str, *args: Any, **kwargs: Any) -> Any:
    ensure_duality_nvflare_lib_current()
    _ensure_extra_runtime_deps()
    sys.modules.pop(module_name, None)
    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    component_class = getattr(module, class_name)
    return component_class(*args, **kwargs)
