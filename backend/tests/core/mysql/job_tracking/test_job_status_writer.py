from unittest.mock import Mock, patch

from app.core.mysql.job_tracking.JobStatusWriter import (
    JobRunnerStatus,
    JobStatusWriter,
    safe_status_update,
)


def _writer():
    value = object.__new__(JobStatusWriter)
    value.job_id = "job-1"
    value.connection = Mock()
    value.cursor = Mock()
    import threading

    value.status_lock = threading.Lock()
    return value


def test_status_stringification():
    assert str(JobRunnerStatus.JOB_BROADCAST) == "Broadcasting NVFlare Job"


def test_log_ignores_blank_messages():
    writer = _writer()
    writer.log(None, JobRunnerStatus.PROCESSING)
    writer.cursor.execute.assert_not_called()


def test_log_updates_status_and_commits():
    writer = _writer()
    writer.cursor.fetchone.return_value = None

    writer.log("started", JobRunnerStatus.PROCESSING)

    assert writer.cursor.execute.call_count == 2
    args = writer.cursor.execute.call_args.args[1]
    assert args[0] == "job-1"
    assert "started" in args[1]
    assert args[2] == "Processing"
    writer.connection.commit.assert_called_once()


def test_log_without_status_uses_two_parameter_insert():
    writer = _writer()
    writer.cursor.fetchone.return_value = None

    writer.log("message")

    assert len(writer.cursor.execute.call_args.args[1]) == 2


def test_safe_status_update_delegates_to_writer(capsys):
    writer = Mock()
    safe_status_update(writer, JobRunnerStatus.DONE, "complete")
    writer.log.assert_called_once_with("complete", status=JobRunnerStatus.DONE)
    assert "complete" in capsys.readouterr().out
