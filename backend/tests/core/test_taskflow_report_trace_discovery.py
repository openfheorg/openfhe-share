from pathlib import Path

from app.core.job_runner.nvflare_jobs import taskflow_report


def _touch(path: Path, text: str = "{}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_collect_trace_files_is_scoped_to_requested_job(tmp_path):
    jobs_root = tmp_path / "job-results"
    job_id = "job-target"

    direct_trace = _touch(jobs_root / job_id / "trace_filter.jsonl")
    nested_job_trace = _touch(jobs_root / job_id / "some" / "nested" / "trace.jsonl")
    site1_trace = _touch(jobs_root / "traces" / job_id / "site-1" / "trace.jsonl")
    site2_trace = _touch(jobs_root / "traces" / job_id / "site-2" / "trace.jsonl")

    # These must never be returned for the target job.
    _touch(jobs_root / "other-job" / "trace.jsonl")
    _touch(jobs_root / "traces" / "other-job" / "site-1" / "trace.jsonl")
    site_direct_trace = _touch(jobs_root / "site-3" / job_id / "trace.jsonl")

    found = taskflow_report.collect_trace_files([jobs_root], job_id)

    assert found == sorted(
        [direct_trace, nested_job_trace, site1_trace, site2_trace, site_direct_trace],
        key=lambda path: str(path),
    )


def test_collect_trace_files_accepts_job_directory_directly(tmp_path):
    job_dir = tmp_path / "job-results" / "job-target"
    trace = _touch(job_dir / "trace.jsonl")

    assert taskflow_report.collect_trace_files([job_dir], "job-target") == [trace]


def test_generate_report_does_not_scan_workspace(monkeypatch, tmp_path):
    jobs_root = tmp_path / "job-results"
    workspace = tmp_path / "workspace"
    job_id = "job-target"
    jobs_root.mkdir()
    workspace.mkdir()
    trace = _touch(jobs_root / "traces" / job_id / "site-1" / "trace.jsonl")

    captured_roots = []

    def fake_collect(roots, requested_job_id):
        captured_roots.extend(Path(root) for root in roots)
        assert requested_job_id == job_id
        return [trace]

    def fake_render(trace_files, out_dir, **kwargs):
        assert trace_files == [trace]
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "index.json").write_text("{}", encoding="utf-8")
        return {"events": 1}

    monkeypatch.setattr(taskflow_report, "collect_trace_files", fake_collect)
    monkeypatch.setattr(taskflow_report, "render_run_report", fake_render)
    monkeypatch.setattr(taskflow_report, "_chown_to_host", lambda _path: None)

    result = taskflow_report.generate_report_for_job(
        job_id,
        job_save_location=str(jobs_root),
        workspace_root=str(workspace),
        force=True,
    )

    assert result == {"events": 1}
    assert captured_roots == [jobs_root]
