from unittest.mock import Mock, patch

import pytest

from app.core.job_runner.nvflare_jobs.NVFlareJobRunner import NVFlareJobRunner, _normalize
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus
from app.core.nvflare.NVFlareServerProvider import NVFlareProvision


JOB_ID = "12345678-1234-1234-1234-123456789abc"


def _runner(tmp_path):
    provision = NVFlareProvision(
        base_location="/base",
        admin_location="/admin",
        server_location="/server",
        client_to_server_job_save_location="/job-results",
    )
    writer = Mock()
    with patch(
        "app.core.job_runner.nvflare_jobs.NVFlareJobRunner.NVFlareAdminKitManager"
    ) as manager_cls:
        runner = NVFlareJobRunner(provision, writer, str(tmp_path / "job"))
    runner._admin_mgr = manager_cls.return_value
    return runner, writer


def test_normalize_line_endings():
    assert _normalize("a\r\nb\rc") == "a\nb\nc"
    assert _normalize(None) == ""


@pytest.mark.parametrize(
    "output",
    [
        f"Submitted job: {JOB_ID}",
        f"Job submitted - {JOB_ID}",
        f"SUBMITTED JOB : {JOB_ID}",
    ],
)
def test_run_job_parses_supported_submit_output(tmp_path, output):
    runner, writer = _runner(tmp_path)
    runner._admin_mgr.run.return_value = (0, output)

    job_id, path = runner.run_job()

    assert job_id == JOB_ID
    assert path == f"/job-results/{JOB_ID}"
    writer.log.assert_called_once_with(
        "NVFlareJobRunner: Job broadcasted successfully",
        JobRunnerStatus.JOB_BROADCAST,
    )


def test_run_job_raises_on_admin_failure(tmp_path):
    runner, _ = _runner(tmp_path)
    runner._admin_mgr.run.return_value = (1, "failed")
    with pytest.raises(RuntimeError, match="exit 1"):
        runner.run_job()


def test_run_job_raises_when_id_missing(tmp_path):
    runner, _ = _runner(tmp_path)
    runner._admin_mgr.run.return_value = (0, "submission accepted")
    with pytest.raises(RuntimeError, match="could not parse"):
        runner.run_job()
