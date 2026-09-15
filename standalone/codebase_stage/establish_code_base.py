import pathlib
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent

SOURCE_DIRS = {
    "backend": WORKSPACE_ROOT / "backend",
    "frontend": WORKSPACE_ROOT / "frontend",
}


def info(m): print(f"[INFO] {m}", flush=True)
def warn(m): print(f"[WARN] {m}", flush=True)


def run(only: str = "all") -> int:
    targets = ("backend", "frontend") if only == "all" else (only,)
    missing = []

    for name in targets:
        src = SOURCE_DIRS[name]
        if src.exists() and src.is_dir():
            info(f"{name.capitalize()} source ready: {src}")
        else:
            warn(f"{name.capitalize()} source directory not found: {src}")
            missing.append(name)

    if missing:
        return 100

    return 0


if __name__ == "__main__":
    print("This module is meant to be run via the orchestrator.\nUse: python main.py")
    sys.exit(1)
