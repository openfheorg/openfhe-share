from unittest.mock import Mock, patch

import pytest

from app.core.job_runner.nvflare_jobs.NVFlareJobMonitor import NVFlareJobMonitor


JOB_ID = "12345678-1234-1234-1234-123456789abc"


def _monitor():
    manager = Mock()
    writer = Mock()
    with patch(
        "app.core.job_runner.nvflare_jobs.NVFlareJobMonitor.NVFlareAdminKitManager"
    ) as manager_cls:
        monitor = NVFlareJobMonitor(manager, JOB_ID, writer)
    monitor._admin_mgr = manager_cls.return_value
    return monitor, manager


def test_parse_list_jobs_row_returns_matching_job():
    monitor, _ = _monitor()
    text = f"""
| JOB ID | NAME | STATUS | SUBMIT TIME | RUN DURATION |
| {JOB_ID} | demo | RUNNING | now | 2s |
"""
    row = monitor._parse_list_jobs_row(text)
    assert row == {
        "job_id": JOB_ID,
        "name": "demo",
        "status": "RUNNING",
        "submit_time": "now",
        "run_duration": "2s",
    }


def test_loop_updates_status_and_detects_finished():
    monitor, manager = _monitor()
    manager.set_nvflare_job_status.return_value = "DONE"
    text = f"| {JOB_ID} | demo | FINISHED:COMPLETED | now | 5s |"

    finished, last = monitor._loop_body_parse_and_update(text)

    assert finished is True
    assert last == "DONE"
    manager.set_submission_timing.assert_called_once_with("now", "5s")


def test_wait_for_completion_retries_transient_admin_failure():
    monitor, _ = _monitor()
    monitor._admin_mgr.run.side_effect = [
        (1, "temporary"),
        (0, f"| {JOB_ID} | demo | FINISHED:COMPLETED | now | 1s |"),
    ]
    monitor._loop_body_parse_and_update = Mock(return_value=(True, "DONE"))

    with patch("app.core.job_runner.nvflare_jobs.NVFlareJobMonitor.time.sleep"):
        assert monitor.wait_for_completion(poll_interval=0, timeout=5) == "DONE"


def test_wait_for_completion_requires_job_id():
    monitor, _ = _monitor()
    monitor.job_id = ""
    with pytest.raises(RuntimeError, match="No NVFlare job_id"):
        monitor.wait_for_completion()


def test_wait_for_completion_times_out():
    monitor, _ = _monitor()
    monitor._admin_mgr.run.return_value = (0, "")
    with patch(
        "app.core.job_runner.nvflare_jobs.NVFlareJobMonitor.time.time",
        side_effect=[0, 0, 2],
    ), patch("app.core.job_runner.nvflare_jobs.NVFlareJobMonitor.time.sleep"):
        with pytest.raises(TimeoutError):
            monitor.wait_for_completion(poll_interval=0, timeout=1)
