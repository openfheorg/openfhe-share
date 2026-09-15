"""Runner-only pytest plugin preserving the sweep's custom per-case details.

The unmodified sweep tests attach ``sweep_detail`` to the call report through
``tests/conftest.py``. JUnit XML does not retain arbitrary report attributes, so
this plugin writes one JSON record per final test outcome for the runner's
concise pytest report.

xdist-aware (lean mode runs cases in parallel with pytest-xdist): test reports
are produced on the workers and forwarded to the controller, so (a) only the
controller truncates and writes the events file -- workers would race and
duplicate -- and (b) ``sweep_detail``, a non-standard report attribute xdist
would otherwise drop, is packed/unpacked through the report (de)serialization
hooks. In serial mode (full mode) none of this triggers and behavior is
unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


_EVENT_PATH_ENV = "DUALITY_RUNNER_PYTEST_EVENTS"
_PHASE_PRIORITY = {"setup": 1, "teardown": 2, "call": 3}


def _event_path() -> Path:
    raw = os.environ.get(_EVENT_PATH_ENV, "").strip()
    if not raw:
        raise RuntimeError(f"{_EVENT_PATH_ENV} is required for pytest_sweep_reporter.")
    return Path(raw)


def _is_xdist_worker() -> bool:
    # xdist sets this env var only inside its worker subprocesses.
    return bool(os.environ.get("PYTEST_XDIST_WORKER"))


def pytest_sessionstart(session: Any) -> None:
    """Start each run with a fresh JSONL event stream (controller/serial only)."""
    if _is_xdist_worker():
        return
    path = _event_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


@pytest.hookimpl(hookwrapper=True)
def pytest_report_to_serializable(config: Any, report: Any):
    """Carry the custom ``sweep_detail`` across the xdist worker->controller boundary."""
    outcome = yield
    data = outcome.get_result()
    if isinstance(data, dict):
        detail = getattr(report, "sweep_detail", None)
        if detail is not None:
            data["sweep_detail"] = detail


@pytest.hookimpl(hookwrapper=True)
def pytest_report_from_serializable(config: Any, data: Any):
    outcome = yield
    report = outcome.get_result()
    if report is not None and isinstance(data, dict) and "sweep_detail" in data:
        report.sweep_detail = data["sweep_detail"]


def _reason(report: Any) -> str:
    if not (report.failed or report.skipped):
        return ""
    value = getattr(report, "longreprtext", None) or str(getattr(report, "longrepr", ""))
    return " ".join(str(value).split())


def pytest_runtest_logreport(report: Any) -> None:
    """Persist one final outcome per test (controller/serial writer only).

    Under xdist ``logreport`` fires on both the worker and the controller; only
    the controller writes so records are neither duplicated nor interleaved.
    """
    if _is_xdist_worker():
        return
    # The normal sweep outcome is the call report. Setup/teardown reports are
    # retained only if they terminate the test before a call report exists.
    if report.when == "call":
        pass
    elif report.when in {"setup", "teardown"} and (report.failed or report.skipped):
        pass
    else:
        return

    detail = getattr(report, "sweep_detail", None)
    record = {
        "nodeid": report.nodeid,
        "outcome": report.outcome,
        "phase": report.when,
        "phase_priority": _PHASE_PRIORITY.get(report.when, 0),
        "detail": detail if isinstance(detail, str) and detail.strip() else "",
        "reason": _reason(report),
        "duration_seconds": round(float(getattr(report, "duration", 0.0) or 0.0), 6),
    }
    with _event_path().open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
