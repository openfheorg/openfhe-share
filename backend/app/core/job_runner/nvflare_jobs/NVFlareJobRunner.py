import os
import re
from typing import Tuple

from app.core.nvflare.NVFlareServerProvider import NVFlareProvision
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.nvflare.NVFlareAdminKitManager import NVFlareAdminKitManager

# Regex for parsing the assigned job ID from fl_admin console output
ASSIGNED_ID_RE = re.compile(
    r"(?:Submitted\s+job|Job\s+submitted)\s*[:\-]\s*([A-Fa-f0-9\-]{36})",
    re.IGNORECASE,
)


def _normalize(out: str) -> str:
    return (out or "").replace("\r\n", "\n").replace("\r", "\n")


class NVFlareJobRunner:
    # Submits a job via fl_admin.sh and returns (job_id, server_jobs_folder).

    def __init__(
        self,
        nvflare_provision: NVFlareProvision,
        status_writer: JobStatusWriter,
        final_job_path: str,
    ):
        self.nvflare_provision = nvflare_provision
        self.status_writer = status_writer
        self.job_path = os.path.abspath(final_job_path)
        self._admin_mgr = NVFlareAdminKitManager()

    def run_job(self) -> Tuple[str, str]:
        # Run submit_job against the staged job path
        submit_command = f"submit_job {self.job_path}"
        print(
            f"NVFlareJobRunner: about to run admin command: {submit_command}",
            flush=True,
        )
        print(
            f"NVFlareJobRunner: resolved absolute job_path: {self.job_path}",
            flush=True,
        )
        print(
            "NVFlareJobRunner: invoking NVFlareAdminKitManager.run(...)",
            flush=True,
        )

        code, output = self._admin_mgr.run(
            commands=[submit_command], timeout=300
        )
        output = _normalize(output)

        print(
            f"NVFlareJobRunner: admin command exit code: {code}",
            flush=True,
        )
        print(
            f"NVFlareJobRunner: raw submit_job output:\n{output}",
            flush=True,
        )

        if code != 0:
            print(
                "NVFlareJobRunner: submit_job failed before job ID could be parsed",
                flush=True,
            )
            raise RuntimeError(f"fl_admin run failed with exit {code}:\n{output}")

        m = ASSIGNED_ID_RE.search(output)
        if not m:
            print(
                "NVFlareJobRunner: failed to parse assigned job ID from submit_job output",
                flush=True,
            )
            raise RuntimeError(
                f"could not parse assigned job ID from submit_job output:\n{output}"
            )

        job_id = m.group(1)
        output_path = f"{self.nvflare_provision.client_to_server_job_save_location}/{job_id}"

        print(
            f"NVFlareJobRunner: parsed job_id: {job_id}",
            flush=True,
        )
        print(
            f"NVFlareJobRunner: computed server-side output path: {output_path}",
            flush=True,
        )

        self.status_writer.log(
            "NVFlareJobRunner: Job broadcasted successfully",
            JobRunnerStatus.JOB_BROADCAST,
        )

        return job_id, output_path
