from pathlib import Path
from typing import List, Optional, Tuple


DEFAULT_JOB_RESULTS_DIR_NAME = "job-results"


def _is_under_root(root: Path, p: Path) -> bool:
    try:
        p.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


class NVFlareWorkspaceReader:
    def __init__(
        self,
        workspace_root: str,
        job_results_dir_name: Optional[str] = None,
    ):
        self.root = Path(workspace_root).expanduser().resolve(strict=False)
        self.job_results_dir_name = (job_results_dir_name or DEFAULT_JOB_RESULTS_DIR_NAME).strip() or DEFAULT_JOB_RESULTS_DIR_NAME

        if not self.root.exists() or not self.root.is_dir():
            raise RuntimeError(f"Workspace root does not exist or is not a directory: {self.root}")

    def job_results_dir(self) -> Path:
        p = (self.root / self.job_results_dir_name).resolve(strict=False)
        if not _is_under_root(self.root, p):
            raise RuntimeError("Invalid job results directory path")
        return p

    def list_jobs(self, limit: int = 200) -> List[Tuple[str, Path, float]]:
        return []
