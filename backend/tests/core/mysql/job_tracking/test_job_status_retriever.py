from unittest.mock import Mock, patch

from app.core.mysql.job_tracking.JobStatusRetriever import JobStatusRetriever


def _retriever(cursor=None):
    value = object.__new__(JobStatusRetriever)
    value.max_retries = 3
    value.base_delay = 0.1
    value.connection = Mock()
    value.cursor = cursor or Mock()
    return value


def test_exec_retries_with_exponential_delay():
    cursor = Mock()
    cursor.execute.side_effect = [RuntimeError("one"), RuntimeError("two"), None]
    cursor.fetchone.return_value = {"ok": True}
    retriever = _retriever(cursor)

    with patch("app.core.mysql.job_tracking.JobStatusRetriever.time.sleep") as sleep:
        result = retriever._exec("SELECT 1", (), fetch="one")

    assert result == {"ok": True}
    assert [call.args[0] for call in sleep.call_args_list] == [0.1, 0.2]


def test_get_status_enriches_referenced_jobs_and_functions():
    retriever = _retriever()
    retriever._exec = Mock(
        side_effect=[
            {"uuid": "runner", "status": "DONE"},
            [
                {"id": 2, "nvflare_assigned_id": "nv2", "run_duration": "5s"},
                {"id": 1, "nvflare_assigned_id": "nv1", "run_duration": None},
            ],
            [
                {"job_id": 1, "name": "MEAN"},
                {"job_id": 2, "name": "T_TEST"},
            ],
        ]
    )

    row = retriever.get_status_by_uuid("runner")

    assert row["referenced_by"] == ["nv2", "nv1"]
    assert row["run_duration"] == "5s"
    assert row["functions"] == ["MEAN", "T_TEST"]
    assert row["nvflare_jobs"][0]["functions"] == ["T_TEST"]
    assert row["nvflare_jobs"][1]["functions"] == ["MEAN"]


def test_get_status_returns_none_when_job_missing():
    retriever = _retriever()
    retriever._exec = Mock(return_value=None)
    assert retriever.get_status_by_uuid("missing") is None
    retriever._exec.assert_called_once()
