"""Background taskflow-report generation and retrieval for result viewing.

The result APIs should never wait for the diagnostic report to be rendered.
This module owns the small amount of orchestration needed to start the report
in a worker thread, persist progress beside the report, and expose the finished
summary/artifacts to API routes.
"""

from __future__ import annotations

import asyncio
import functools
import json
import mimetypes
import sys
import traceback
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app import taskflow_report



_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_STATUS_FILENAME = ".generation-status.json"
# The Results UI only needs the rendered timeline as a file artifact. Summary
# metrics and per-round timing are returned as structured JSON by
# ``get_diagnostics``; the remaining raw taskflow files stay server-side.
_ALLOWED_ARTIFACTS = {
    "taskflow.timeline.svg",
}

_TASKS: dict[str, asyncio.Task] = {}
_TASKS_LOCK = asyncio.Lock()
_MEMORY_STATUS: dict[str, Dict[str, Any]] = {}
_MEMORY_STATUS_LOCK = threading.Lock()


# The renderer itself remains untouched. These wrappers add timing/progress around
# the existing taskflow_report functions at runtime. A thread-local context keeps
# concurrent report generations isolated from one another.
_REPORT_STAGE_META = {
    "trace_discovery": (12, "Locating taskflow traces"),
    "trace_read_merge": (24, "Reading and merging taskflow traces"),
    "causal_graph": (38, "Building causal taskflow graph"),
    "round_analysis": (50, "Analyzing federated rounds"),
    "diagnostic_artifacts": (60, "Writing taskflow diagnostic artifacts"),
    "timeline_svg": (75, "Rendering taskflow timeline"),
    "finalize_report": (95, "Finalizing taskflow diagnostics"),
}

_REPORT_FUNCTION_STAGES = {
    "collect_trace_files": "trace_discovery",
    "_read_records": "trace_read_merge",
    "_build_case_graph": "causal_graph",
    "_round_analysis": "round_analysis",
    "_perfetto_from_graph": "diagnostic_artifacts",
    "_mermaid_from_graph": "diagnostic_artifacts",
    "_dot_from_graph": "diagnostic_artifacts",
    "_rounds_txt": "diagnostic_artifacts",
    "_write_timeline_svg": "timeline_svg",
    "_index_md": "finalize_report",
    "_chown_to_host": "finalize_report",
}

_REPORT_TIMING_CONTEXT = threading.local()
_REPORT_WRAPPERS_INSTALLED = False
_REPORT_WRAPPERS_LOCK = threading.Lock()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _ReportTimingContext:
    def __init__(self, nvflare_job_id: str):
        self.nvflare_job_id = str(nvflare_job_id)
        self.started_at = time.perf_counter()
        self.timings: Dict[str, float] = {}
        self._seen_stages: set[str] = set()

    def begin(self, stage: str, function_name: Optional[str] = None) -> float:
        progress, label = _REPORT_STAGE_META[stage]
        print(
            f"[TASKFLOW] START | job={self.nvflare_job_id} | stage={stage} | "
            f"step={function_name or stage} | progress={progress} | "
            f"timestamp_utc={_utc_timestamp()} | total_elapsed_sec={self.elapsed():.3f}",
            flush=True,
        )

        if stage not in self._seen_stages:
            self._seen_stages.add(stage)
            _set_status(
                self.nvflare_job_id,
                "running",
                progress,
                label,
                stage=stage,
                stage_timings_sec=self.snapshot(),
                elapsed_sec=self.elapsed(),
            )
        return time.perf_counter()

    def finish(
        self,
        stage: str,
        started_at: float,
        function_name: Optional[str] = None,
    ) -> None:
        elapsed = max(0.0, time.perf_counter() - started_at)
        self.timings[stage] = self.timings.get(stage, 0.0) + elapsed
        print(
            f"[TASKFLOW] END | job={self.nvflare_job_id} | stage={stage} | "
            f"step={function_name or stage} | timestamp_utc={_utc_timestamp()} | "
            f"step_elapsed_sec={elapsed:.3f} | stage_elapsed_sec={self.timings[stage]:.3f} | "
            f"total_elapsed_sec={self.elapsed():.3f}",
            flush=True,
        )

    def elapsed(self) -> float:
        return max(0.0, time.perf_counter() - self.started_at)

    def snapshot(self) -> Dict[str, float]:
        return {key: round(value, 3) for key, value in self.timings.items()}

    def final_timings(self) -> Dict[str, float]:
        total = self.elapsed()
        measured = sum(self.timings.values())
        payload = self.snapshot()
        payload["uninstrumented_overhead"] = round(max(0.0, total - measured), 3)
        payload["total"] = round(total, 3)
        return payload


def _install_report_stage_wrappers() -> None:
    """Wrap report stages once without changing taskflow_report.py itself."""
    global _REPORT_WRAPPERS_INSTALLED
    if _REPORT_WRAPPERS_INSTALLED:
        return

    with _REPORT_WRAPPERS_LOCK:
        if _REPORT_WRAPPERS_INSTALLED:
            return

        for function_name, stage in _REPORT_FUNCTION_STAGES.items():
            original = getattr(taskflow_report, function_name, None)
            if original is None or getattr(original, "_duality_taskflow_timing_wrapper", False):
                continue

            @functools.wraps(original)
            def wrapped(*args, __original=original, __stage=stage, **kwargs):
                context = getattr(_REPORT_TIMING_CONTEXT, "current", None)
                if context is None:
                    return __original(*args, **kwargs)
                started_at = context.begin(__stage, function_name=__original.__name__)
                try:
                    return __original(*args, **kwargs)
                finally:
                    context.finish(
                        __stage,
                        started_at,
                        function_name=__original.__name__,
                    )

            wrapped._duality_taskflow_timing_wrapper = True
            setattr(taskflow_report, function_name, wrapped)

        _REPORT_WRAPPERS_INSTALLED = True


def _generate_report_with_instrumentation(
    nvflare_job_id: str,
    case_label: str,
    context: _ReportTimingContext,
):
    _install_report_stage_wrappers()
    _REPORT_TIMING_CONTEXT.current = context
    try:
        return taskflow_report.generate_report_for_job(
            nvflare_job_id,
            case_label=case_label,
        )
    finally:
        try:
            del _REPORT_TIMING_CONTEXT.current
        except AttributeError:
            pass


def is_valid_job_id(nvflare_job_id: str) -> bool:
    return bool(nvflare_job_id and _JOB_ID_RE.fullmatch(str(nvflare_job_id)))


def _job_results_root() -> Optional[Path]:
    explicit = (os.getenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION") or "").strip()
    if explicit:
        return Path(explicit)
    workspace = (os.getenv("DUALITY_NVFLARE_WORKSPACE") or "/nvflare").strip() or "/nvflare"
    return Path(workspace) / "job-results"


def _report_dir(nvflare_job_id: str) -> Optional[Path]:
    root = _job_results_root()
    if root is None:
        return None
    return root / str(nvflare_job_id) / "taskflow"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _set_status(
    nvflare_job_id: str,
    state: str,
    progress: int,
    label: str,
    error: Optional[str] = None,
    stage: Optional[str] = None,
    stage_timings_sec: Optional[Dict[str, float]] = None,
    elapsed_sec: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state": state,
        "progress": max(0, min(100, int(progress))),
        "label": label,
    }
    if error:
        payload["error"] = error
    if stage:
        payload["stage"] = stage
    if stage_timings_sec is not None:
        payload["stage_timings_sec"] = dict(stage_timings_sec)
    if elapsed_sec is not None:
        payload["elapsed_sec"] = round(max(0.0, float(elapsed_sec)), 3)

    with _MEMORY_STATUS_LOCK:
        _MEMORY_STATUS[str(nvflare_job_id)] = dict(payload)

    report_dir = _report_dir(nvflare_job_id)
    if report_dir is not None:
        try:
            _atomic_write_json(report_dir / _STATUS_FILENAME, payload)
        except OSError:
            # Memory status is enough for the current process if the filesystem
            # is temporarily unwritable; report generation itself remains best-effort.
            pass
    return payload


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _existing_report_state(nvflare_job_id: str) -> Optional[Dict[str, Any]]:
    report_dir = _report_dir(nvflare_job_id)
    if report_dir is None:
        return None

    index_path = report_dir / "index.json"
    if index_path.exists():
        complete = {
            "state": "complete",
            "progress": 100,
            "label": "Federated taskflow diagnostics are ready",
        }
        status = _read_json(report_dir / _STATUS_FILENAME)
        if isinstance(status, dict):
            for key in ("stage_timings_sec", "elapsed_sec"):
                if key in status:
                    complete[key] = status[key]
        return complete

    if (report_dir / ".no-trace").exists():
        return {
            "state": "unavailable",
            "progress": 100,
            "label": "No taskflow trace data is available for this job",
        }

    status = _read_json(report_dir / _STATUS_FILENAME)
    if isinstance(status, dict):
        return status
    return None


def get_generation_status(nvflare_job_id: str) -> Dict[str, Any]:
    # While this process is actively generating a report, prefer its live status
    # over filesystem artifacts that may appear just before finalization ends.
    with _MEMORY_STATUS_LOCK:
        memory = _MEMORY_STATUS.get(str(nvflare_job_id))
        if memory is not None and memory.get("state") in {"queued", "running"}:
            return dict(memory)

    existing = _existing_report_state(nvflare_job_id)
    if existing is not None:
        return existing

    with _MEMORY_STATUS_LOCK:
        memory = _MEMORY_STATUS.get(str(nvflare_job_id))
        if memory is not None:
            state = memory.get("state")
            if state in {"complete", "unavailable"}:
                # Terminal taskflow state is persisted by concrete artifacts
                # (index.json or .no-trace). If those files were removed, the
                # in-memory status is stale and must not prevent regeneration.
                _MEMORY_STATUS.pop(str(nvflare_job_id), None)
            else:
                return dict(memory)

    return {
        "state": "idle",
        "progress": 0,
        "label": "Taskflow diagnostics have not been generated yet",
    }


async def _run_generation(nvflare_job_id: str, case_label: str) -> None:
    timing_context = _ReportTimingContext(nvflare_job_id)
    print(
        f"[TASKFLOW] GENERATION START | job={nvflare_job_id} | "
        f"timestamp_utc={_utc_timestamp()}",
        flush=True,
    )
    try:
        _set_status(
            nvflare_job_id,
            "running",
            5,
            "Preparing federated taskflow diagnostics",
            stage="prepare",
            elapsed_sec=timing_context.elapsed(),
        )
        result = await asyncio.to_thread(
            _generate_report_with_instrumentation,
            nvflare_job_id,
            case_label,
            timing_context,
        )

        timings = timing_context.final_timings()
        report_dir = _report_dir(nvflare_job_id)
        if report_dir is not None and (report_dir / "index.json").exists():
            _set_status(
                nvflare_job_id,
                "complete",
                100,
                "Federated taskflow diagnostics are ready",
                stage="complete",
                stage_timings_sec=timings,
                elapsed_sec=timings["total"],
            )
        elif report_dir is not None and (report_dir / ".no-trace").exists():
            _set_status(
                nvflare_job_id,
                "unavailable",
                100,
                "No taskflow trace data is available for this job",
                stage="complete",
                stage_timings_sec=timings,
                elapsed_sec=timings["total"],
            )
        elif result is not None:
            # This covers custom output locations while still reporting success
            # for the process that generated the report.
            _set_status(
                nvflare_job_id,
                "complete",
                100,
                "Federated taskflow diagnostics are ready",
                stage="complete",
                stage_timings_sec=timings,
                elapsed_sec=timings["total"],
            )
        else:
            _set_status(
                nvflare_job_id,
                "unavailable",
                100,
                "Taskflow diagnostics could not be generated from the available trace data",
                stage="complete",
                stage_timings_sec=timings,
                elapsed_sec=timings["total"],
            )

        print(
            f"[TASKFLOW] GENERATION END | job={nvflare_job_id} | "
            f"timestamp_utc={_utc_timestamp()} | total_elapsed_sec={timings['total']:.3f} | "
            f"timings={timings}",
            flush=True,
        )
    except Exception as exc:  # pragma: no cover - taskflow report itself is best-effort
        timings = timing_context.final_timings()
        _set_status(
            nvflare_job_id,
            "failed",
            100,
            "Taskflow diagnostics generation failed",
            error=f"{exc.__class__.__name__}: {exc}",
            stage="failed",
            stage_timings_sec=timings,
            elapsed_sec=timings["total"],
        )
        print(
            f"[TASKFLOW] GENERATION FAILED | job={nvflare_job_id} | "
            f"timestamp_utc={_utc_timestamp()} | total_elapsed_sec={timings['total']:.3f} | "
            f"error={exc.__class__.__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
    finally:
        async with _TASKS_LOCK:
            current = _TASKS.get(str(nvflare_job_id))
            if current is asyncio.current_task():
                _TASKS.pop(str(nvflare_job_id), None)


async def ensure_generation_started(nvflare_job_id: str, case_label: Optional[str] = None) -> Dict[str, Any]:
    """Start report generation once and return immediately with current status."""
    if not is_valid_job_id(nvflare_job_id):
        raise ValueError("Invalid nvflare_job_id")

    status = get_generation_status(nvflare_job_id)
    if status.get("state") in {"complete", "unavailable"}:
        return status

    async with _TASKS_LOCK:
        task = _TASKS.get(str(nvflare_job_id))
        if task is None or task.done():
            _set_status(nvflare_job_id, "queued", 1, "Queued federated taskflow diagnostics")
            task = asyncio.create_task(
                _run_generation(
                    str(nvflare_job_id),
                    case_label=case_label or str(nvflare_job_id),
                )
            )
            _TASKS[str(nvflare_job_id)] = task

    return get_generation_status(nvflare_job_id)


def get_diagnostics(nvflare_job_id: str) -> Dict[str, Any]:
    if not is_valid_job_id(nvflare_job_id):
        raise ValueError("Invalid nvflare_job_id")

    status = get_generation_status(nvflare_job_id)
    payload: Dict[str, Any] = {
        "status": status,
        "timings": dict(status.get("stage_timings_sec") or {}),
        "summary": None,
        "rounds": [],
        "artifacts": [],
    }

    report_dir = _report_dir(nvflare_job_id)
    if report_dir is None:
        return payload

    summary = _read_json(report_dir / "index.json")
    rounds = _read_json(report_dir / "taskflow.rounds.json")
    if isinstance(summary, dict):
        payload["summary"] = summary
    if isinstance(rounds, list):
        payload["rounds"] = rounds

    artifacts = []
    for filename in sorted(_ALLOWED_ARTIFACTS):
        path = report_dir / filename
        if not path.exists() or not path.is_file():
            continue
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        artifacts.append(
            {
                "filename": filename,
                "media_type": media_type,
                "size_bytes": path.stat().st_size,
            }
        )
    payload["artifacts"] = artifacts
    return payload


def get_artifact_path(nvflare_job_id: str, artifact: str) -> Optional[Path]:
    if not is_valid_job_id(nvflare_job_id):
        return None
    if artifact not in _ALLOWED_ARTIFACTS:
        return None

    report_dir = _report_dir(nvflare_job_id)
    if report_dir is None:
        return None

    path = report_dir / artifact
    if not path.exists() or not path.is_file():
        return None
    return path
