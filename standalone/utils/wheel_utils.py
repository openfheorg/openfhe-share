from pathlib import Path
from typing import Optional
import shutil

def inject_latest_duality_nvflare_lib(
    repo_root: Path,
    target_dir: Path,
    info=None,
    warn=None,
    err=None,
) -> Optional[Path]:
    def log(fn, prefix, msg):
        if fn:
            fn(msg)
        else:
            print(prefix + msg, flush=True)

    src = (
        repo_root
        / "backend"
        / "app"
        / "core"
        / "job_runner"
        / "nvflare_jobs"
        / "wheels"
    )

    if not src.exists():
        log(warn, "[WARN] ", f"Wheel directory not found: {src}")
        return None

    wheels = sorted(
        src.glob("duality_nvflare_lib-*.whl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not wheels:
        log(warn, "[WARN] ", f"No duality_nvflare_lib wheels found in {src}")
        return None

    target_dir.mkdir(parents=True, exist_ok=True)

    for f in target_dir.glob("duality_nvflare_lib-*.whl"):
        try:
            f.unlink()
        except OSError:
            pass

    latest = wheels[0]
    dest = target_dir / latest.name

    try:
        shutil.copy2(latest, dest)
        log(info, "[INFO] ", f"Copied duality_nvflare_lib wheel to {dest}")
        return dest
    except Exception as e:
        log(err, "[ERROR] ", f"Failed to copy duality_nvflare_lib wheel: {e}")
        return None
