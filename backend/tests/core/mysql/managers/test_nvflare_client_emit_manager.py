from unittest.mock import Mock, patch

import pytest

from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus
from app.core.mysql.managers import NVFlareClientEmitManager as module


@pytest.mark.parametrize(
    "code,is_server,expected",
    [
        (100, False, JobRunnerStatus.JOB_RECEIVED),
        (720, False, JobRunnerStatus.THRESHOLD_NOT_MET),
        (900, True, JobRunnerStatus.ERROR),
        (300, False, JobRunnerStatus.CLIENT_COMPUTE),
        (300, True, JobRunnerStatus.SERVER_COMPUTE),
        (400, False, JobRunnerStatus.CLIENT_ENCRYPTION),
        (410, True, JobRunnerStatus.SERVER_ANALYSIS),
        (600, False, JobRunnerStatus.CLIENT_RESULTS),
        (None, False, JobRunnerStatus.PROCESSING),
    ],
)
def test_resolve_status(code, is_server, expected):
    assert module._resolve_status(code, is_server) is expected


@pytest.mark.parametrize("value,expected", [("4", 4), (2.0, 2), (None, None), ("x", None)])
def test_to_int(value, expected):
    assert module._to_int(value) == expected


def test_log_progress_formats_client_round_and_function():
    manager = object.__new__(module.NVFlareClientEmitManager)
    manager.job_runner_id = "runner"
    manager.writer = Mock()
    module._RECENT_KEYS.clear()

    with patch.object(module, "safe_status_update") as update:
        manager.log_progress(
            code=410,
            round_num=0,
            client_name="site2",
            function_name="mean",
        )

    writer, status, message = update.call_args.args
    assert writer is manager.writer
    assert status is JobRunnerStatus.CLIENT_ANALYSIS
    assert "Client site2" in message
    assert "round 1" in message


def test_log_progress_deduplicates_recent_events():
    manager = object.__new__(module.NVFlareClientEmitManager)
    manager.job_runner_id = "runner"
    manager.writer = Mock()
    module._RECENT_KEYS.clear()

    with patch.object(module, "safe_status_update") as update, patch.object(module.time, "time", return_value=10):
        manager.log_progress(code=300, round_num=0, client_name="site1")
        manager.log_progress(code=300, round_num=0, client_name="site1")

    update.assert_called_once()
