import asyncio
import json
from pathlib import Path

from app.core.job_runner.nvflare_jobs import taskflow_service


def _reset_taskflow_state():
    taskflow_service._TASKS.clear()
    taskflow_service._MEMORY_STATUS.clear()


def test_taskflow_generation_runs_in_background_and_exposes_artifacts(tmp_path, monkeypatch, capsys):
    _reset_taskflow_state()
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path))
    job_id = "job_123"

    def fake_generate(nvflare_job_id, **_kwargs):
        # Exercise a couple of the runtime stage wrappers without changing the
        # report generator itself.
        taskflow_service.taskflow_report.collect_trace_files([], nvflare_job_id)
        taskflow_service.taskflow_report._read_records([])

        out_dir = tmp_path / nvflare_job_id / "taskflow"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "taskflow.timeline.svg").write_text("<svg></svg>", encoding="utf-8")
        (out_dir / "taskflow.rounds.json").write_text(
            json.dumps([{"workflow": "wf", "round": "1", "contributions": 2}]),
            encoding="utf-8",
        )
        summary = {
            "events": 10,
            "spans": 3,
            "edges": 4,
            "rounds": 1,
            "parties": ["server:server", "client:site1"],
            "artifacts": ["taskflow.timeline.svg"],
        }
        (out_dir / "index.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    monkeypatch.setattr(taskflow_service.taskflow_report, "generate_report_for_job", fake_generate)

    async def scenario():
        started = await taskflow_service.ensure_generation_started(job_id)
        assert started["state"] in {"queued", "running"}

        for _ in range(100):
            await asyncio.sleep(0.01)
            if taskflow_service.get_generation_status(job_id)["state"] == "complete":
                break

        diagnostics = taskflow_service.get_diagnostics(job_id)
        assert diagnostics["status"]["state"] == "complete"
        assert diagnostics["status"]["elapsed_sec"] >= 0
        assert "trace_discovery" in diagnostics["timings"]
        assert "trace_read_merge" in diagnostics["timings"]
        assert "total" in diagnostics["timings"]
        assert diagnostics["summary"]["events"] == 10
        assert diagnostics["rounds"][0]["contributions"] == 2
        assert "taskflow.timeline.svg" in {item["filename"] for item in diagnostics["artifacts"]}
        assert taskflow_service.get_artifact_path(job_id, "taskflow.timeline.svg") == (
            tmp_path / job_id / "taskflow" / "taskflow.timeline.svg"
        )
        # Raw diagnostic files may exist on disk for backend/support use, but the
        # user-facing artifact endpoint intentionally exposes only the timeline.
        assert taskflow_service.get_artifact_path(job_id, "taskflow.rounds.json") is None
        assert taskflow_service.get_artifact_path(job_id, "taskflow.perfetto.json") is None
        assert taskflow_service.get_artifact_path(job_id, "index.json") is None
        assert taskflow_service.get_artifact_path(job_id, "../../etc/passwd") is None

    asyncio.run(scenario())

    output = capsys.readouterr().out
    assert "[TASKFLOW] GENERATION START" in output
    assert "stage=trace_discovery" in output
    assert "step=collect_trace_files" in output
    assert "stage=trace_read_merge" in output
    assert "step=_read_records" in output
    assert "timestamp_utc=" in output
    assert "step_elapsed_sec=" in output
    assert "[TASKFLOW] GENERATION END" in output


def test_existing_taskflow_report_is_immediately_complete(tmp_path, monkeypatch):
    _reset_taskflow_state()
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path))
    job_id = "already_done"
    out_dir = tmp_path / job_id / "taskflow"
    out_dir.mkdir(parents=True)
    (out_dir / "index.json").write_text(json.dumps({"events": 2}), encoding="utf-8")

    async def scenario():
        status = await taskflow_service.ensure_generation_started(job_id)
        assert status["state"] == "complete"
        assert status["progress"] == 100

    asyncio.run(scenario())


def test_no_trace_marker_reports_unavailable(tmp_path, monkeypatch):
    _reset_taskflow_state()
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path))
    job_id = "no_trace_job"
    out_dir = tmp_path / job_id / "taskflow"
    out_dir.mkdir(parents=True)
    (out_dir / ".no-trace").write_text("no trace files found\n", encoding="utf-8")

    diagnostics = taskflow_service.get_diagnostics(job_id)
    assert diagnostics["status"]["state"] == "unavailable"
    assert diagnostics["status"]["progress"] == 100


def test_deleted_report_folder_invalidates_complete_memory_state(tmp_path, monkeypatch):
    _reset_taskflow_state()
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path))
    job_id = "deleted_complete_report"

    taskflow_service._MEMORY_STATUS[job_id] = {
        "state": "complete",
        "progress": 100,
        "label": "Federated taskflow diagnostics are ready",
    }

    status = taskflow_service.get_generation_status(job_id)
    assert status["state"] == "idle"
    assert job_id not in taskflow_service._MEMORY_STATUS


def test_deleted_no_trace_folder_invalidates_unavailable_memory_state(tmp_path, monkeypatch):
    _reset_taskflow_state()
    monkeypatch.setenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION", str(tmp_path))
    job_id = "deleted_no_trace_report"

    taskflow_service._MEMORY_STATUS[job_id] = {
        "state": "unavailable",
        "progress": 100,
        "label": "No taskflow trace data is available for this job",
    }

    status = taskflow_service.get_generation_status(job_id)
    assert status["state"] == "idle"
    assert job_id not in taskflow_service._MEMORY_STATUS
