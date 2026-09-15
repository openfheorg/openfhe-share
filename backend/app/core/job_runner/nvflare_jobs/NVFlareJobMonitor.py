import os
import re
import time
from typing import Optional

from app.core.nvflare.NVFlareServerProvider import NVFlareProvision
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.mysql.managers.NVFlareJobsManager import NVFlareJobsManager
from app.core.nvflare.NVFlareAdminKitManager import NVFlareAdminKitManager

ROW_RE = re.compile(
    r"^\|\s*([0-9a-fA-F\-]+)\s*\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|$"
)

class NVFlareJobMonitor:
    def __init__(
        self,
        nvflare_manager: NVFlareJobsManager,
        job_id: str,
        status_writer: JobStatusWriter,
    ):
        self.nvflare_manager = nvflare_manager
        self.job_id = job_id
        self.status_writer = status_writer
        self._admin_mgr = NVFlareAdminKitManager()

        self.submit_time: Optional[str] = None
        self.run_duration: Optional[str] = None

    def _parse_list_jobs_row(self, text: str):
        for ln in text.splitlines():
            m = ROW_RE.match(ln.strip())
            if m and m.group(2).strip() != "NAME":
                row = {
                    "job_id": m.group(1).strip(),
                    "name": m.group(2).strip(),
                    "status": m.group(3).strip(),
                    "submit_time": m.group(4).strip(),
                    "run_duration": m.group(5).strip(),
                }
                if row["job_id"] == self.job_id:
                    return row
        return None

    def _loop_body_parse_and_update(self, out_text: str) -> tuple[bool, Optional[str]]:
        row = self._parse_list_jobs_row(out_text)
        last_status = None
        if row:
            status = row["status"]
            self.submit_time = row["submit_time"]
            self.run_duration = row["run_duration"]
            last_status = self.nvflare_manager.set_nvflare_job_status(status)
            self.nvflare_manager.set_submission_timing(self.submit_time, self.run_duration)
            if status.startswith("FINISHED:"):
                return True, last_status
        return False, last_status

    def wait_for_completion(
        self,
        poll_interval: int = 2,
        timeout: int = 900,
    ) -> str:
        if not self.job_id:
            raise RuntimeError("No NVFlare job_id recorded for job")

        start = time.time()
        last_status = None

        while time.time() - start < timeout:
            # self.status_writer.log(
            #     f"NVFlareJobMonitor: Monitoring job activity on {self.job_id}",
            #     JobRunnerStatus.JOB_ANALYSIS,
            # )
            code, out = self._admin_mgr.run(commands=[f"list_jobs {self.job_id}"], timeout=300)
            if code != 0:
                # transient admin hiccup; wait and retry
                time.sleep(poll_interval)
                continue

            finished, last_status = self._loop_body_parse_and_update(out)
            if finished:
                return last_status

            time.sleep(poll_interval)

        raise TimeoutError(
            f"Job {self.job_id} did not complete within {timeout} seconds (last status: {last_status})."
        )
