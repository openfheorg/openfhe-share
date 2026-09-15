#!/usr/bin/env python3
"""Container-side adapter for NVFlare biomarker sweep tests.

The host launcher selects a physical Project-2 datasource key and mounts only
that datasource's FHIR files, model package, and source-controlled schema. The
test modules keep a ``2_1`` default for direct execution, but the container
sets the selected datasource key before pytest starts. This keeps FHIR input
selection, model lookup, and datasource-group config resolution aligned.
"""

from __future__ import annotations

import hashlib
import re
import json
import os
import shutil
import subprocess
import sys
import traceback
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SOURCE_JOBS = Path("/source/nvflare_jobs")
SOURCE_MODELS_ROOT = Path("/source-models")
WORK_ROOT = Path("/work")
SOURCE_GLOBAL_SCHEMA = WORK_ROOT / "profile-global_schema.json"
WORK_JOBS = WORK_ROOT / "nvflare_jobs"
WORK_INPUT = WORK_ROOT / "fhir-input"
RESULTS_ROOT = Path("/results")
REPORTER_SOURCE = Path("/work/pytest_sweep_reporter.py")
REPORTER_MODULE = "runner_pytest_sweep_reporter"
TEMPLATE_SCHEMA_REL = Path("jobs") / "nvflare_job_template" / "app_server" / "custom" / "global_schema.json"
SITE_ORDER = ("site1", "site2", "site3")
DATASOURCE_KEY_PATTERN = re.compile(r"^(?P<project>\d+)_(?P<group>\d+)$")


def selected_datasource_key() -> str:
    """Return the physical datasource key selected by the host runner."""
    key = os.getenv("DUALITY_RUNNER_DATASOURCE_KEY", "").strip()
    match = DATASOURCE_KEY_PATTERN.fullmatch(key)
    if not match:
        raise RuntimeError(
            "DUALITY_RUNNER_DATASOURCE_KEY must be '<project_id>_<datasource_group_id>'; "
            f"got {key!r}."
        )
    if match.group("project") != "2":
        raise RuntimeError(
            "The biomarker simulator sweep currently supports Project 2 only; "
            f"got datasource key {key!r}."
        )
    return key


def selected_datasource_group() -> str:
    match = DATASOURCE_KEY_PATTERN.fullmatch(selected_datasource_key())
    assert match is not None
    return match.group("group")


def datasource_env_key(site: str) -> str:
    """Return the selected-key FHIR input environment variable for one site."""
    site_fragment = re.sub(r"[^A-Za-z0-9]", "", site).upper()
    return f"DUALITY_CLIENT_{site_fragment}_DATASOURCE_{selected_datasource_key()}"


def selected_models_group() -> Path:
    return SOURCE_MODELS_ROOT / f"datasource_group_{selected_datasource_group()}"


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str, exit_code: int = 2) -> int:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    return exit_code


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_jobs_source() -> None:
    if not SOURCE_JOBS.is_dir():
        raise RuntimeError(f"NVFlare source is missing: {SOURCE_JOBS}")
    if WORK_JOBS.exists():
        shutil.rmtree(WORK_JOBS)
    shutil.copytree(
        SOURCE_JOBS,
        WORK_JOBS,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "test-results"),
    )


def stage_global_schema() -> dict[str, Any]:
    if not SOURCE_GLOBAL_SCHEMA.is_file():
        raise RuntimeError(
            f"Expected selected global schema mounted at {SOURCE_GLOBAL_SCHEMA}."
        )
    try:
        payload = json.loads(SOURCE_GLOBAL_SCHEMA.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Selected global schema is not valid JSON: {SOURCE_GLOBAL_SCHEMA}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Selected global schema must be a JSON object: {SOURCE_GLOBAL_SCHEMA}")

    target = WORK_JOBS / TEMPLATE_SCHEMA_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_GLOBAL_SCHEMA, target)
    manifest = {
        "physical_datasource": selected_datasource_key(),
        "simulator_runtime_datasource": selected_datasource_key(),
        "source": str(SOURCE_GLOBAL_SCHEMA),
        "target": str(target),
        "sha256": sha256(SOURCE_GLOBAL_SCHEMA),
        "biomarker_covariate_count": len(
            (payload.get("metadata", {}) or {}).get("biomarker_covariates") or []
        ),
    }
    log(
        "Staged selected global schema into copied simulator template: "
        f"physical={manifest['physical_datasource']} covariates="
        f"{manifest['biomarker_covariate_count']} sha256={manifest['sha256']}"
    )
    return manifest


def extract_member(archive_path: Path, site: str) -> Path:
    WORK_INPUT.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            json_members = [
                member for member in archive.namelist()
                if not member.endswith("/") and Path(member).suffix.lower() == ".json"
            ]
            if len(json_members) != 1:
                preview = ", ".join(json_members[:12]) or "<none>"
                raise RuntimeError(
                    f"Cannot determine a unique JSON payload for {site} from {archive_path.name}. "
                    f"Archive JSON members: {preview}"
                )
            member = json_members[0]
            output_path = WORK_INPUT / f"{site}-{Path(member).name}"
            with archive.open(member) as source, output_path.open("wb") as target:
                shutil.copyfileobj(source, target)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Invalid datasource ZIP: {archive_path}") from exc
    return output_path


def resolve_datasources() -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for site in SITE_ORDER:
        raw = os.getenv(f"DUALITY_RUNNER_{site.upper()}_INPUT", "").strip()
        if not raw:
            raise RuntimeError(f"Missing DUALITY_RUNNER_{site.upper()}_INPUT.")
        source_path = Path(raw)
        if not source_path.is_file():
            raise RuntimeError(f"Mounted {site} source does not exist: {source_path}")
        if source_path.suffix.lower() == ".json":
            runtime_path = source_path
            source_kind = "mounted JSON"
        elif source_path.suffix.lower() == ".zip":
            runtime_path = extract_member(source_path, site)
            source_kind = "extracted ZIP"
        else:
            raise RuntimeError(f"Unsupported {site} source type: {source_path}. Supply .json or .zip.")

        env_key = datasource_env_key(site)
        os.environ[env_key] = str(runtime_path)
        resolved[env_key] = {
            "site": site,
            "runtime_path": str(runtime_path),
            "source_kind": source_kind,
            "source_path": str(source_path),
        }
        log(f"Datasource: {env_key} = {runtime_path} ({source_kind})")

    # conftest.py calls setdefault and scripts/run_simulator.py only fills missing
    # values, so this selected physical key survives into all test jobs.
    # It is intentionally the same suffix used by datasource_env_key(), allowing
    # FHIRBaseConfigResolver to select both the correct site input and config group.
    os.environ["DUALITY_SIM_DATASOURCE_VERSION"] = selected_datasource_key()
    return resolved


def resolve_model_files() -> dict[str, Any]:
    models_group = selected_models_group()
    if not models_group.is_dir():
        raise RuntimeError(f"Expected models mounted at {models_group}.")
    files = sorted(path for path in models_group.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"Model directory is empty: {models_group}")
    os.environ["DUALITY_SIM_BIOMARKER_MODELS_ROOT"] = str(SOURCE_MODELS_ROOT)
    log(
        "Biomarker models: DUALITY_SIM_BIOMARKER_MODELS_ROOT="
        f"{SOURCE_MODELS_ROOT} ({len(files)} file(s) for datasource_group_"
        f"{selected_datasource_group()})"
    )
    return {
        "root": str(SOURCE_MODELS_ROOT),
        "datasource_key": selected_datasource_key(),
        "datasource_group": selected_datasource_group(),
        "directory": str(models_group),
        "file_count": len(files),
        "files": [str(path.relative_to(models_group)) for path in files],
    }


def install_pytest_reporter() -> Path:
    """Install the runner-only pytest reporter beside the copied test source."""
    if not REPORTER_SOURCE.is_file():
        raise RuntimeError(f"Runner pytest reporter is missing: {REPORTER_SOURCE}")
    target = WORK_JOBS / f"{REPORTER_MODULE}.py"
    shutil.copy2(REPORTER_SOURCE, target)
    return target



def build_and_install_wheel() -> None:
    builder = WORK_JOBS / "wheels" / "APIWheelBuilderCI.py"
    if not builder.is_file():
        raise RuntimeError(f"Wheel builder not found: {builder}")
    subprocess.run([sys.executable, str(builder)], cwd=WORK_JOBS, check=True)
    wheels = sorted((WORK_JOBS / "wheels").glob("duality_nvflare_lib-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise RuntimeError("No duality_nvflare_lib wheel was produced.")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-index", "--no-deps", str(wheels[-1])],
        cwd=WORK_JOBS,
        check=True,
    )


def parse_json_list(name: str) -> list[str]:
    raw = os.getenv(name, "[]")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON list: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"{name} must be a JSON list of strings.")
    return value


def _collapsed_text(value: str | None, *, limit: int = 600) -> str:
    """Normalize a pytest/JUnit reason into one readable line."""
    if not value:
        return ""
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _read_report_events(path: Path) -> list[dict[str, Any]]:
    """Load runner-plugin reports and keep the final/best phase per node."""
    if not path.is_file():
        return []

    selected: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for order, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        nodeid = record.get("nodeid")
        if not isinstance(nodeid, str) or not nodeid:
            continue
        priority = int(record.get("phase_priority", 0) or 0)
        previous = selected.get(nodeid)
        if previous is None or priority >= previous[0]:
            selected[nodeid] = (priority, order, record)
    return [record for _, _, record in sorted(selected.values(), key=lambda item: item[1])]


def _is_collection_skip(case: Any) -> bool:
    """True for a JUnit entry that is a module skipped during collection, not a test outcome.

    pytest emits one such entry per module with the module path in ``name``, an empty
    ``classname``, and a "collection skipped" message.
    """
    skipped = case.find("skipped")
    if skipped is None:
        return False
    if (skipped.attrib.get("message") or "").strip().lower() == "collection skipped":
        return True
    return not (case.attrib.get("classname") or "").strip()


def _junit_totals(junit_path: Path) -> tuple[dict[str, int], str | None]:
    """Return JUnit totals as the fallback source of truth for the final line.

    ``uncollected`` counts modules skipped during collection (a module-level
    ``pytest.skip`` / ``importorskip``) and they are excluded from ``tests`` / ``skipped``:
    those report a missing dependency in the image, not a cohort that cannot support the
    analysis, and mixing the two makes the skip count unreadable. JUnit records them with an
    empty ``classname`` and a "collection skipped" message.
    """
    totals = {"tests": 0, "passed": 0, "skipped": 0, "failed": 0, "errors": 0, "uncollected": 0}
    if not junit_path.is_file():
        return totals, None
    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return totals, None

    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    for suite in suites:
        tests = int(suite.attrib.get("tests", "0"))
        failures = int(suite.attrib.get("failures", "0"))
        errors = int(suite.attrib.get("errors", "0"))
        skipped = int(suite.attrib.get("skipped", "0"))
        uncollected = sum(
            1
            for case in suite.findall("testcase")
            if _is_collection_skip(case)
        )
        totals["tests"] += tests - uncollected
        totals["failed"] += failures
        totals["errors"] += errors
        totals["skipped"] += skipped - uncollected
        totals["uncollected"] += uncollected
    totals["passed"] = max(0, totals["tests"] - totals["failed"] - totals["errors"] - totals["skipped"])
    return totals, root.attrib.get("time")


def write_pytest_output(
    junit_path: Path,
    events_path: Path,
    output_path: Path,
    exit_code: int,
) -> None:
    """Write the concise per-case summary that the sweep itself reports with -v.

    The unchanged tests add details such as ``beta=... p=... max_delta=...``
    to the pytest call report. Those fields are deliberately captured by the
    runner plugin, because JUnit XML does not preserve arbitrary report attrs.
    The raw combined stream remains in ``full-console-output.txt``.
    """
    events = _read_report_events(events_path)
    totals, total_time = _junit_totals(junit_path)
    # full-console-output.txt is only written in full mode; in lean, point the
    # fallback messages at artifacts that actually exist (junit.xml when present,
    # otherwise the container stdout stream captured by docker logs).
    lean = os.getenv("DUALITY_SWEEP_MODE", "lean").strip().lower() != "full"

    lines = [
        "============================= test session starts ==============================",
        "NVFlare simulator sweep: concise pytest status report",
    ]
    if events:
        lines.extend([f"collected {totals['tests'] or len(events)} item{'s' if (totals['tests'] or len(events)) != 1 else ''}", ""])
        for record in events:
            outcome = str(record.get("outcome", "error")).upper()
            nodeid = str(record.get("nodeid", "<unknown test>"))
            detail = _collapsed_text(str(record.get("detail", "")))
            reason = _collapsed_text(str(record.get("reason", "")))
            if detail:
                suffix = f" [{detail}]"
            elif reason:
                suffix = f" - {reason}"
            else:
                suffix = ""
            lines.append(f"{nodeid} {outcome}{suffix}")
    elif not junit_path.is_file():
        console_hint = (
            "the container stdout (docker logs)"
            if lean
            else "full-console-output.txt for the complete NVFlare/pytest console stream"
        )
        lines.extend([
            "",
            f"pytest exited with code {exit_code}, but no junit.xml was created.",
            f"See {console_hint}.",
        ])
    else:
        events_hint = "junit.xml" if lean else "full-console-output.txt"
        lines.extend([
            "",
            f"No runner pytest-status events were recorded. See {events_hint}.",
        ])

    duration = f" in {total_time}s" if total_time else ""
    # Reported apart from the counts: a module that never imported is an image problem, not a
    # dataset one.
    uncollected = (
        f", {totals['uncollected']} module(s) not collected" if totals.get("uncollected") else ""
    )
    lines.extend([
        "",
        (
            "================= "
            f"{totals['passed']} passed, {totals['skipped']} skipped, "
            f"{totals['failed']} failed, {totals['errors']} errors{uncollected}{duration} "
            "================="
        ),
        "",
    ])
    output_path.write_text("\n".join(lines), encoding="utf-8")



# ---------------------------------------------------------------------------
# Performance summary
# ---------------------------------------------------------------------------
# Each NVFlare party writes a profile_summary.json under its simulator workspace.
# The files are detailed and intentionally remain in place.  This runner-level
# report condenses them into a stable, text-friendly comparison artifact without
# modifying any NVFlare job code or pytest test.

_PROFILE_FILE_NAME = "profile_summary.json"
_WORKSPACE_INDEX_PATTERN = re.compile(r"^(?P<base>.*?)(?P<index>\d+)$")


def _number(value: Any) -> float | None:
    """Return a finite numeric value, or None when the profile field is absent."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return None


def _sum_numbers(values: list[float | None]) -> float:
    return sum(value for value in values if value is not None)


def _fmt_seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _fmt_megabytes(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _short_nodeid(nodeid: str, limit: int = 108) -> str:
    return nodeid if len(nodeid) <= limit else nodeid[: limit - 3] + "..."


def _workspace_order(workspace: str) -> tuple[str, int, str]:
    match = _WORKSPACE_INDEX_PATTERN.search(workspace)
    if match:
        return (match.group("base"), int(match.group("index")), workspace)
    return (workspace, 10**9, workspace)


def _profile_workspace(path: Path, workspace_root: Path) -> str:
    try:
        relative = path.relative_to(workspace_root)
    except ValueError:
        return "<unknown-workspace>"
    return relative.parts[0] if relative.parts else "<unknown-workspace>"


def _profile_case_lookup(events_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Group pytest events by test function, preserving execution order.

    pytest names each case's basetemp ``<function-name-truncated><counter>`` and
    restarts the counter per function, so the counter is the case's index WITHIN
    its function -- not a global index. Returning events grouped by function lets
    ``_event_for_workspace`` resolve a workspace to the correct event even across
    the four interleaved suites of a ``--suite all`` run.
    """
    events = _read_report_events(events_path)
    by_func: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        nodeid = str(event.get("nodeid") or "")
        func = (nodeid.split("::")[-1] if "::" in nodeid else nodeid).split("[")[0]
        by_func.setdefault(func, []).append(event)
    return by_func


def _event_for_workspace(
    workspace: str,
    events_by_func: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Resolve a case's pytest event from its NVFlare basetemp workspace name.

    The workspace's leading text is a truncated prefix of exactly one test
    function's name, and its trailing counter is that function's Nth case. Both
    the basetemp counter and the per-function event order follow run order, so
    they line up. Returns None (caller falls back to the workspace name) if the
    prefix is ambiguous or the counter is out of range.
    """
    match = _WORKSPACE_INDEX_PATTERN.search(workspace)
    if not match:
        return None
    base, index = match.group("base"), int(match.group("index"))
    candidates = [func for func in events_by_func if func.startswith(base)]
    if len(candidates) != 1:
        return None
    events = events_by_func[candidates[0]]
    return events[index] if 0 <= index < len(events) else None


def _load_profile_summaries(workspace_root: Path) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    if not workspace_root.is_dir():
        return profiles

    for path in sorted(workspace_root.rglob(_PROFILE_FILE_NAME)):
        # Avoid unrelated files with the same name if a job produces one outside
        # the ordinary NVFlare job-results tree.
        if "job-results" not in path.parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        site = payload.get("site")
        role = payload.get("role")
        workflows = payload.get("workflows")
        metrics = payload.get("system_metrics")
        if not isinstance(site, str) or not isinstance(workflows, dict):
            continue
        profiles.append(
            {
                "path": str(path),
                "workspace": _profile_workspace(path, workspace_root),
                "site": site,
                "role": role if isinstance(role, str) else "unknown",
                "workflows": workflows,
                "system_metrics": metrics if isinstance(metrics, dict) else {},
            }
        )
    return profiles


def _profile_compute_seconds(round_payload: dict[str, Any]) -> float:
    # Client profiles use client_compute_time_sec.  The fallbacks keep this
    # runner useful for a server profile or a future profiler naming adjustment.
    for key in ("client_compute_time_sec", "server_compute_time_sec", "compute_time_sec"):
        value = _number(round_payload.get(key))
        if value is not None:
            return value
    return 0.0


def _profile_rounds(profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    workflows = profile["workflows"]
    for workflow_name, workflow_rounds in workflows.items():
        if not isinstance(workflow_name, str) or not isinstance(workflow_rounds, dict):
            continue
        for round_name, round_payload in workflow_rounds.items():
            if not isinstance(round_payload, dict):
                continue
            phases = round_payload.get("phase_breakdown_sec")
            phase_values: dict[str, float] = {}
            if isinstance(phases, dict):
                for phase_name, phase_value in phases.items():
                    numeric = _number(phase_value)
                    if isinstance(phase_name, str) and numeric is not None:
                        phase_values[phase_name] = numeric
            rows.append(
                {
                    "workflow": workflow_name,
                    "round": str(round_name),
                    "compute_sec": _profile_compute_seconds(round_payload),
                    "downstream_rtt_sec": _number(round_payload.get("downstream_rtt_sec")) or 0.0,
                    "upstream_rtt_sec": _number(round_payload.get("upstream_rtt_sec")) or 0.0,
                    "phase_breakdown_sec": phase_values,
                }
            )
    return rows


def _performance_manifest(
    *,
    workspace_root: Path,
    events_path: Path,
) -> dict[str, Any]:
    profiles = _load_profile_summaries(workspace_root)
    event_lookup = _profile_case_lookup(events_path)
    _event_count = sum(len(evs) for evs in event_lookup.values())
    cases: dict[str, dict[str, Any]] = {}

    for profile in profiles:
        workspace = profile["workspace"]
        case = cases.setdefault(
            workspace,
            {
                "workspace": workspace,
                "profiles": [],
                "workflow_totals": {},
                "phase_totals": {},
            },
        )
        case["profiles"].append(profile)
        for row in _profile_rounds(profile):
            workflow = row["workflow"]
            workflow_total = case["workflow_totals"].setdefault(
                workflow,
                {"compute_sec": 0.0, "rtt_sec": 0.0, "_round_keys": set()},
            )
            workflow_total["compute_sec"] += row["compute_sec"]
            workflow_total["rtt_sec"] += row["downstream_rtt_sec"] + row["upstream_rtt_sec"]
            workflow_total["_round_keys"].add(row["round"])
            for phase_name, phase_value in row["phase_breakdown_sec"].items():
                key = f"{workflow}::{phase_name}"
                case["phase_totals"][key] = case["phase_totals"].get(key, 0.0) + phase_value

    for case in cases.values():
        for workflow_total in case["workflow_totals"].values():
            workflow_total["rounds"] = len(workflow_total.pop("_round_keys"))

    test_rows: list[dict[str, Any]] = []

    for workspace in sorted(cases, key=_workspace_order):
        case = cases[workspace]
        event = _event_for_workspace(workspace, event_lookup)
        profile_rows = case["profiles"]
        wall_times = [
            _number(profile["system_metrics"].get("wall_time_sec"))
            for profile in profile_rows
        ]
        wall_times = [value for value in wall_times if value is not None]
        rss_mb_values = [
            (_number(profile["system_metrics"].get("rss_max_kb")) or 0.0) / 1024.0
            for profile in profile_rows
            if _number(profile["system_metrics"].get("rss_max_kb")) is not None
        ]
        network_mb_values = [
            ((_number(profile["system_metrics"].get("net_tx_bytes_total")) or 0.0) +
             (_number(profile["system_metrics"].get("net_rx_bytes_total")) or 0.0)) / (1024.0 * 1024.0)
            for profile in profile_rows
        ]
        workflow_total_compute = sum(
            total["compute_sec"] for total in case["workflow_totals"].values()
        )
        workflow_total_rtt = sum(
            total["rtt_sec"] for total in case["workflow_totals"].values()
        )
        nodeid = str(event.get("nodeid")) if event else workspace
        outcome = str(event.get("outcome", "profiled")) if event else "profiled"
        detail = str(event.get("detail", "")) if event else ""
        row = {
            "workspace": workspace,
            "nodeid": nodeid,
            "outcome": outcome,
            "detail": detail,
            "profile_count": len(profile_rows),
            "sites": sorted({str(profile["site"]) for profile in profile_rows}),
            # A simulator test runs sites concurrently, therefore max site wall
            # time is the closest profile-derived approximation of case runtime.
            "wall_time_sec_max_site": max(wall_times) if wall_times else None,
            "compute_time_sec_sum_sites": workflow_total_compute,
            "rtt_sec_sum_sites": workflow_total_rtt,
            "rss_max_mb": max(rss_mb_values) if rss_mb_values else None,
            "network_tx_rx_mb_sum_sites": sum(network_mb_values),
            "workflow_totals": case["workflow_totals"],
            "phase_totals": case["phase_totals"],
        }
        test_rows.append(row)

    return {
        "format_version": 2,
        "physical_datasource": selected_datasource_key(),
        "simulator_runtime_datasource": selected_datasource_key(),
        "profile_summary_file_count": len(profiles),
        "pytest_outcome_event_count": _event_count,
        "profiled_case_count": len(test_rows),
        "unprofiled_pytest_case_count": max(0, _event_count - len(test_rows)),
        "test_cases": test_rows,
    }

def _fmt_round_detail(d: dict[str, Any]) -> str:
    """Format one per-round decomposition line (widths match the report header)."""
    wu, wc = d.get("workers_used"), d.get("workers_cap")
    workers = f"{wu}/{wc}" if wu is not None else "-"
    chunks = str(d.get("chunks")) if d.get("chunks") is not None else "-"
    contrib = d.get("contributions")
    return (
        f"    {str(d.get('workflow'))[:40]:<40} {str(d.get('round')):>5} "
        f"{(str(contrib) if contrib is not None else '-'):>7} "
        f"{_fmt_seconds(d.get('compute_max_sec')):>11} "
        f"{str(d.get('slowest_client') or '-')[:8]:>8} "
        f"{_fmt_seconds(d.get('straggler_gap_sec')):>9} "
        f"{_fmt_seconds(d.get('wait_max_sec')):>8} "
        f"{_fmt_seconds(d.get('fetch_max_sec')):>9} "
        f"{_fmt_seconds(d.get('send_max_sec')):>8} "
        f"{workers:>9} {chunks:>6}"
    )


def _write_performance_output(
    manifest: dict[str, Any],
    output_path: Path,
    traces: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Write a stable, run-only per-case performance report.

    Cancer cohorts vary substantially in record count, so cross-case averages,
    medians, percentiles, and totals obscure the useful signal.  This report
    intentionally keeps every measurement attached to its exact pytest case so
    separate runs can be compared manually, case by case.
    """
    traces = traces or {}
    lines = [
        "========================= performance output =========================",
        "NVFlare simulator sweep profile-summary metrics",
        f"Physical datasource: {manifest['physical_datasource']}",
        f"Profile summaries found: {manifest['profile_summary_file_count']}",
        f"Profiled test cases: {manifest['profiled_case_count']}",
        "",
        "Metric definitions:",
        "  - Wall time is the maximum site-local wall_time_sec for one test case.",
        "  - Compute and RTT are summed across profiled sites, workflows, and rounds.",
        "  - Rounds is the distinct round count per workflow (union across sites, not sites x rounds).",
        "  - Peak RSS is the largest site-local rss_max_kb for one test case.",
        "  - Network is summed site tx + rx counters; use it as communication workload, not physical wire traffic.",
        "  - Trace diagram is the per-case taskflow swimlane (taskflow/<case>.timeline.svg), linked under each case when rendered.",
        "  - Straggler sec is the summed per-round server idle-wait for the slowest client (synchronous-round waste; trace-derived).",
        "  - Straggler '-' means not measurable: fewer than two correlated server result-arrivals that round (e.g. no server trace captured).",
        "  - Round decomposition (per case) splits each round's client RTT into wait/fetch/compute/send and lists HE workers/chunks.",
        "",
        "Per-case metrics:",
        "status    wall sec   compute sec   rtt sec  strag sec  peak RSS MB  network MB  profiles  test",
    ]

    for row in manifest["test_cases"]:
        detail = _collapsed_text(row["detail"], limit=240)
        suffix = f" [{detail}]" if detail else ""
        strag_total = (traces.get(str(row["workspace"])) or {}).get("straggler_total")
        lines.append(
            f"{str(row['outcome']).upper():<8} "
            f"{_fmt_seconds(row['wall_time_sec_max_site']):>9} "
            f"{_fmt_seconds(row['compute_time_sec_sum_sites']):>13} "
            f"{_fmt_seconds(row['rtt_sec_sum_sites']):>9} "
            f"{_fmt_seconds(strag_total):>9} "
            f"{_fmt_megabytes(row['rss_max_mb']):>12} "
            f"{_fmt_megabytes(row['network_tx_rx_mb_sum_sites']):>11} "
            f"{row['profile_count']:>9}  {row['nodeid']}{suffix}"
        )

    lines.extend([
        "",
        "Per-case workflow and phase timings:",
    ])
    for row in manifest["test_cases"]:
        detail = _collapsed_text(row["detail"], limit=240)
        suffix = f" [{detail}]" if detail else ""
        lines.extend([
            "",
            f"{str(row['outcome']).upper()}  {row['nodeid']}{suffix}",
            f"  Sites: {', '.join(row['sites']) or '-'}",
        ])
        case_trace = traces.get(str(row["workspace"])) or {}
        diagram = case_trace.get("timeline")
        if diagram:
            lines.append(f"  Trace diagram: {diagram}")
        lines.extend([
            "  Workflows:",
            "    workflow                                                       rounds  compute sec    rtt sec",
        ])
        workflows = row["workflow_totals"]
        if workflows:
            for workflow, totals in sorted(workflows.items()):
                lines.append(
                    f"    {workflow[:62]:<62} {int(totals['rounds']):>6} "
                    f"{_fmt_seconds(float(totals['compute_sec'])):>12} "
                    f"{_fmt_seconds(float(totals['rtt_sec'])):>10}"
                )
        else:
            lines.append("    -")

        lines.extend([
            "  Phases:",
            "    workflow :: phase                                                     seconds",
        ])
        phases = row["phase_totals"]
        if phases:
            for phase_key, seconds in sorted(phases.items()):
                lines.append(f"    {phase_key[:70]:<70} {_fmt_seconds(float(seconds)):>10}")
        else:
            lines.append("    -")

        detail_rows = case_trace.get("round_detail") or []
        if detail_rows:
            lines.extend([
                "  Round decomposition (trace-derived; strag=server idle-wait for slowest client; "
                "wait/fetch/compute/send=client RTT split; workers=HE used/cap):",
                f"    {'workflow':<40} {'round':>5} {'contrib':>7} {'compute max':>11} "
                f"{'slowest':>8} {'strag gap':>9} {'wait max':>8} {'fetch max':>9} "
                f"{'send max':>8} {'workers':>9} {'chunks':>6}",
            ])
            for d in detail_rows:
                lines.append(_fmt_round_detail(d))

    lines.extend([
        "",
        "Raw per-site source files remain under simulator-workspaces/**/job-results/**/profile_summary.json.",
        "",
    ])
    output_path.write_text("\n".join(lines), encoding="utf-8")

def write_performance_summary(
    events_path: Path,
    workspace_root: Path,
    results_root: Path,
    taskflow_summary: dict[str, Any] | None = None,
) -> None:
    """Create stable performance artifacts after pytest has completed."""
    manifest = _performance_manifest(workspace_root=workspace_root, events_path=events_path)
    traces: dict[str, dict[str, Any]] = {}
    for case in (taskflow_summary or {}).get("cases", []):
        ws = str(case.get("workspace"))
        name = case.get("timeline")
        traces[ws] = {
            "timeline": f"taskflow/{name}" if name else None,
            "straggler_total": case.get("straggler_wait_total_sec"),
            "straggler_max": case.get("straggler_wait_max_sec"),
            "round_detail": case.get("round_detail") or [],
        }
    (results_root / "performance-summary.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    _write_performance_output(manifest, results_root / "performance-output.txt", traces)


# ---------------------------------------------------------------------------
# Taskflow / causal trace (step 1): timestamped event trace -> Perfetto + Mermaid
# ---------------------------------------------------------------------------
# Each party's Profiler writes trace.jsonl beside profile_summary.json. This
# section merges those per-party event streams per test case and emits, under
# <results>/taskflow/:
#   - <workspace>.perfetto.json : Chrome Trace Event format (open in
#     ui.perfetto.dev or chrome://tracing) with one thread per party,
#     compute/dispatch/accept/aggregate/round spans, and flow arrows for
#     correlated task-dispatch and result messages.
#   - <workspace>.seq.mmd : a Mermaid sequenceDiagram of the correlated messages.
# Messages are correlated by NVFlare task id when present. A cross-wire
# Lamport/vector clock and a send-side correlation filter are a later step; with
# no task id the per-party spans still render, only the cross-party arrows drop.

_TRACE_FILE_NAME = "trace.jsonl"

# (role, open_kind, close_kind, label) span pairs, matched FIFO per lane. Serial
# per-party execution in the sweep makes FIFO pairing exact.
_TRACE_SPANS = (
    ("client", "task_recv", "compute_end", "compute"),
    ("client", "compute_end", "send_end", "send"),
    ("client", "pull_start", "task_recv", "wait"),
    ("client", "bg_start", "bg_end", "background"),
    ("server", "dispatch_start", "dispatch_end", "dispatch"),
    ("server", "result_recv", "submission_done", "accept"),
    ("server", "agg_start", "agg_end", "aggregate"),
    ("server", "round_start", "round_done", "round"),
)


def _load_trace_records(workspace_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Group every party's trace records by the test-case workspace.

    Reads the Profiler's ``trace.jsonl`` (per-party event stream) and the
    correlation filter's ``trace_filter.jsonl`` (server-side ``dispatch_msg``
    records carrying the on-wire correlation id) into the same per-case list.
    """
    cases: dict[str, list[dict[str, Any]]] = {}
    if not workspace_root.is_dir():
        return cases
    for file_name in (_TRACE_FILE_NAME, "trace_filter.jsonl"):
        for path in sorted(workspace_root.rglob(file_name)):
            if "job-results" not in path.parts:
                continue
            workspace = _profile_workspace(path, workspace_root)
            records = cases.setdefault(workspace, [])
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if isinstance(record, dict):
                        records.append(record)
            except (OSError, json.JSONDecodeError):
                continue
    return cases


def _ts(record: dict[str, Any]) -> float | None:
    """Wall-clock timestamp, or None when the field is absent/non-numeric.

    Returns None (not 0.0) so span-duration callers can tell a legitimate 0.0
    relative time apart from "no timestamp" and never manufacture a ~1.7e9 s
    span. Ordering / coordinate contexts use _ts_or0 to coerce a missing stamp
    to 0.0 (the historical behaviour) instead.
    """
    return _number(record.get("ts_wall"))


def _ts_or0(record: dict[str, Any]) -> float:
    """Timestamp coerced to 0.0 when missing, for ordering, comparison and
    coordinate math only -- never for span durations (see _ts)."""
    value = _ts(record)
    return value if value is not None else 0.0


def _seq(record: dict[str, Any]) -> int:
    """Best-effort integer ``seq`` for stable ordering; 0 when absent or
    non-numeric. A malformed seq must not raise: the whole report is wrapped in
    a blanket handler that would otherwise silently drop it."""
    try:
        return int(record.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def _causal_clocks(
    count: int,
    party_of: list[int],
    party_count: int,
    prog_edges: list[tuple[int, int]],
    msg_edges: list[tuple[int, int]],
    ts_of: list[float],
) -> tuple[list[int], list[dict[int, int]], bool]:
    """Assign Lamport scalar and vector clocks over the event DAG offline.

    For a completed trace this is equivalent to online Lamport/vector clocks:
    the happens-before relation is program order per party plus every
    send->receive message edge. Processed in topological order (Kahn), so it is
    correct without synchronized wall clocks (multi-host safe). Wall time only
    breaks ties deterministically.
    """
    preds: list[list[int]] = [[] for _ in range(count)]
    indeg = [0] * count
    seen_edge: set[tuple[int, int]] = set()
    for a, b in list(prog_edges) + list(msg_edges):
        if a == b or (a, b) in seen_edge:
            continue
        seen_edge.add((a, b))
        preds[b].append(a)
        indeg[b] += 1

    import heapq

    ready: list[tuple[float, int]] = []
    for node in range(count):
        if indeg[node] == 0:
            heapq.heappush(ready, (ts_of[node], node))
    succs: list[list[int]] = [[] for _ in range(count)]
    for a, b in seen_edge:
        succs[a].append(b)

    lamport = [0] * count
    vclock: list[dict[int, int]] = [dict() for _ in range(count)]
    order: list[int] = []
    while ready:
        _, node = heapq.heappop(ready)
        order.append(node)
        best = 0
        merged: dict[int, int] = {}
        for pred in preds[node]:
            best = max(best, lamport[pred])
            for party, value in vclock[pred].items():
                if value > merged.get(party, 0):
                    merged[party] = value
        lamport[node] = best + 1
        merged[party_of[node]] = merged.get(party_of[node], 0) + 1
        vclock[node] = merged
        for nxt in succs[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(ready, (ts_of[nxt], nxt))

    acyclic = len(order) == count
    if not acyclic:
        # Correlation produced a cycle (a receive dated before its send). Fall
        # back to a wall-clock linearization so the artifact still renders. On a
        # cyclic (should-be-DAG) graph the causal clocks are only approximate:
        # keep the Lamport ranking and give every node a minimal, non-empty
        # vector clock {party: rank} so downstream consumers never see the
        # empty/degenerate clocks the aborted Kahn pass may have left behind.
        for rank, node in enumerate(sorted(range(count), key=lambda n: (ts_of[n], n)), start=1):
            lamport[node] = rank
            vclock[node] = {party_of[node]: rank}
    return lamport, vclock, acyclic


def _build_case_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    recs = [r for r in records if isinstance(r, dict)]
    recs.sort(key=lambda r: (_ts_or0(r), _seq(r)))
    for index, record in enumerate(recs):
        record["_idx"] = index

    def lane_key(record: dict[str, Any]) -> tuple[str, str]:
        return (str(record.get("role") or "?"), str(record.get("site") or "?"))

    lanes: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in recs:
        key = lane_key(record)
        if key not in seen:
            seen.add(key)
            lanes.append(key)
    lanes.sort(key=lambda k: (0 if k[0] == "server" else 1, k[1]))
    lane_index = {key: index for index, key in enumerate(lanes)}

    open_map: dict[tuple[str, str], tuple[str, str]] = {}
    close_map: dict[tuple[str, str], tuple[str, str]] = {}
    for role, open_kind, close_kind, label in _TRACE_SPANS:
        open_map[(role, open_kind)] = (close_kind, label)
        close_map[(role, close_kind)] = (open_kind, label)

    open_queues: dict[tuple[tuple[str, str], str], list[dict[str, Any]]] = {}
    spans: list[dict[str, Any]] = []
    for record in recs:
        role = str(record.get("role") or "?")
        kind = str(record.get("kind") or "")
        lane = lane_key(record)
        if (role, kind) in open_map:
            _, label = open_map[(role, kind)]
            open_queues.setdefault((lane, label), []).append(record)
        if (role, kind) in close_map:
            _, label = close_map[(role, kind)]
            queue = open_queues.get((lane, label))
            if queue:
                opener = queue.pop(0)
                spans.append(
                    {
                        "lane": lane,
                        "label": label,
                        "t0": _ts_or0(opener),
                        "t1": _ts_or0(record),
                        "workflow": opener.get("workflow"),
                        "round": opener.get("round"),
                        "task_id": opener.get("task_id") or record.get("task_id"),
                        "open_idx": opener["_idx"],
                        "meta": record.get("meta"),
                    }
                )

    def make_edge(src: dict[str, Any], dst: dict[str, Any], label: str, method: str) -> dict[str, Any]:
        return {
            "src_idx": src["_idx"],
            "dst_idx": dst["_idx"],
            "src_lane": lane_key(src),
            "dst_lane": lane_key(dst),
            "src_site": str(src.get("site") or "?"),
            "dst_site": str(dst.get("site") or "?"),
            "t0": _ts_or0(src),
            "t1": max(_ts_or0(src), _ts_or0(dst)),
            "corr_id": src.get("corr_id") or dst.get("corr_id") or src.get("task_id") or dst.get("task_id"),
            "label": label,
            "method": method,
            "workflow": dst.get("workflow") or src.get("workflow"),
            "round": dst.get("round") if dst.get("round") is not None else src.get("round"),
        }

    def for_peer(server_events: list[dict[str, Any]], site: str) -> list[dict[str, Any]]:
        # Prefer server events tagged with this client; fall back to all when the
        # peer/client name was not available on the server side.
        matched = [e for e in server_events if e.get("peer") and str(e.get("peer")) == site]
        return matched or server_events

    # A stable correlation key: the profiler's self-stamped corr_id if present,
    # else the NVFlare task id. Either lets dispatch<->receive and send<->receive
    # pair reliably across parties.
    def corr_key(record: dict[str, Any]) -> str | None:
        value = record.get("corr_id") or record.get("task_id")
        return str(value) if value else None

    edges: list[dict[str, Any]] = []
    edged_recv: set[int] = set()
    edged_send: set[int] = set()
    by_key: dict[str, list[dict[str, Any]]] = {}
    for record in recs:
        key = corr_key(record)
        if key:
            by_key.setdefault(key, []).append(record)

    for _key, group in by_key.items():
        recvs = [r for r in group if r.get("role") == "client" and r.get("kind") == "task_recv"]
        dispatches = [r for r in group if r.get("role") == "server" and r.get("kind") in ("dispatch_msg", "dispatch_start", "dispatch_end")]
        sends = [r for r in group if r.get("role") == "client" and r.get("kind") == "send_end"]
        srv_recvs = [r for r in group if r.get("role") == "server" and r.get("kind") in ("result_recv", "submission_done")]
        for recv in recvs:
            candidates = for_peer(dispatches, str(recv.get("site") or "?"))
            if not candidates:
                continue
            before = [d for d in candidates if _ts_or0(d) <= _ts_or0(recv)]
            src = max(before, key=_ts_or0) if before else min(candidates, key=_ts_or0)
            edges.append(make_edge(src, recv, "task", "id"))
            edged_recv.add(recv["_idx"])
        for send in sends:
            candidates = for_peer(srv_recvs, str(send.get("site") or "?"))
            if not candidates:
                continue
            after = [s for s in candidates if _ts_or0(s) >= _ts_or0(send)]
            dst = min(after, key=_ts_or0) if after else max(candidates, key=_ts_or0)
            edges.append(make_edge(send, dst, "result", "id"))
            edged_send.add(send["_idx"])

    # Fallback correlation for events without a usable correlation key
    all_dispatch = [r for r in recs if r.get("role") == "server" and r.get("kind") in ("dispatch_start", "dispatch_end")]
    all_srv_recv = [r for r in recs if r.get("role") == "server" and r.get("kind") in ("result_recv", "submission_done")]

    def _same_wf_pool(candidates: list[dict[str, Any]], event: dict[str, Any]) -> list[dict[str, Any]]:
        same_wf = [c for c in candidates if c.get("workflow") == event.get("workflow")]
        rnd = event.get("round")
        if rnd not in (None, -1):
            same_round = [c for c in same_wf if c.get("round") == rnd]
            return same_round or same_wf
        return same_wf

    for recv in recs:
        if recv["_idx"] in edged_recv or recv.get("role") != "client" or recv.get("kind") != "task_recv":
            continue
        pool = _same_wf_pool(for_peer(all_dispatch, str(recv.get("site") or "?")), recv)
        before = [d for d in pool if _ts_or0(d) <= _ts_or0(recv)]
        src = (max(before, key=_ts_or0) if before else (min(pool, key=_ts_or0) if pool else None))
        if src is not None:
            edges.append(make_edge(src, recv, "task", "fallback"))
    for send in recs:
        if send["_idx"] in edged_send or send.get("role") != "client" or send.get("kind") != "send_end":
            continue
        pool = _same_wf_pool(for_peer(all_srv_recv, str(send.get("site") or "?")), send)
        after = [s for s in pool if _ts_or0(s) >= _ts_or0(send)]
        dst = (min(after, key=_ts_or0) if after else (max(pool, key=_ts_or0) if pool else None))
        if dst is not None:
            edges.append(make_edge(send, dst, "result", "fallback"))

    # De-duplicate identical edges (same endpoints + label).
    unique_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[int, int, str]] = set()
    for edge in edges:
        signature = (edge["src_idx"], edge["dst_idx"], edge["label"])
        if signature not in seen_edges:
            seen_edges.add(signature)
            unique_edges.append(edge)
    edges = unique_edges

    # Program-order edges within each lane (by seq then wall time).
    prog_edges: list[tuple[int, int]] = []
    per_lane: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in recs:
        per_lane.setdefault(lane_key(record), []).append(record)
    for lane_records in per_lane.values():
        # Order by wall time first: a lane may mix the Profiler's and the
        # correlation filter's records, which carry independent seq counters.
        lane_records.sort(key=lambda r: (_ts_or0(r), _seq(r), r["_idx"]))
        for previous, current in zip(lane_records, lane_records[1:]):
            prog_edges.append((previous["_idx"], current["_idx"]))

    msg_edges = [(edge["src_idx"], edge["dst_idx"]) for edge in edges]
    party_of = [lane_index[lane_key(record)] for record in recs]
    ts_of = [_ts_or0(record) for record in recs]
    lamport, vclock, acyclic = _causal_clocks(
        len(recs), party_of, len(lanes), prog_edges, msg_edges, ts_of
    )

    for edge in edges:
        edge["src_lamport"] = lamport[edge["src_idx"]] if lamport else None
        edge["dst_lamport"] = lamport[edge["dst_idx"]] if lamport else None

    t0 = min((t for r in recs if (t := _ts(r)) is not None), default=0.0)
    corr_counts = {
        "by_id": sum(1 for e in edges if e["method"] == "id"),
        "fallback": sum(1 for e in edges if e["method"] == "fallback"),
    }
    return {
        "lanes": lanes,
        "lane_index": lane_index,
        "spans": spans,
        "edges": edges,
        "t0": t0,
        "event_count": len(recs),
        "recs": recs,
        "prog_edges": prog_edges,
        "lamport": lamport,
        "vclock": vclock,
        "acyclic": acyclic,
        "max_lamport": max(lamport) if lamport else 0,
        "correlation": corr_counts,
    }


def _perfetto_from_graph(case_label: str, graph: dict[str, Any]) -> dict[str, Any]:
    lane_index = graph["lane_index"]
    t0 = graph["t0"]
    events: list[dict[str, Any]] = [
        {"ph": "M", "name": "process_name", "pid": 1, "args": {"name": case_label}}
    ]
    for lane, index in lane_index.items():
        events.append(
            {"ph": "M", "name": "thread_name", "pid": 1, "tid": index, "args": {"name": f"{lane[0]}:{lane[1]}"}}
        )
    lamport = graph.get("lamport") or []
    for span in graph["spans"]:
        open_idx = span.get("open_idx")
        events.append(
            {
                "ph": "X",
                "pid": 1,
                "tid": lane_index[span["lane"]],
                "ts": (span["t0"] - t0) * 1_000_000.0,
                "dur": max(0.0, (span["t1"] - span["t0"]) * 1_000_000.0),
                "name": span["label"],
                "args": {
                    "workflow": span.get("workflow"),
                    "round": span.get("round"),
                    "task_id": span.get("task_id"),
                    "lamport": lamport[open_idx] if isinstance(open_idx, int) and open_idx < len(lamport) else None,
                },
            }
        )
    flow_id = 0
    for edge in graph["edges"]:
        flow_id += 1
        events.append(
            {
                "ph": "s",
                "id": flow_id,
                "pid": 1,
                "tid": lane_index[edge["src_lane"]],
                "ts": (edge["t0"] - t0) * 1_000_000.0,
                "name": edge["label"],
                "cat": "msg",
            }
        )
        events.append(
            {
                "ph": "f",
                "bp": "e",
                "id": flow_id,
                "pid": 1,
                "tid": lane_index[edge["dst_lane"]],
                "ts": (edge["t1"] - t0) * 1_000_000.0,
                "name": edge["label"],
                "cat": "msg",
            }
        )
    return {"traceEvents": events, "displayTimeUnit": "ms"}


def _mermaid_from_graph(case_label: str, graph: dict[str, Any], max_edges: int = 400) -> str:
    lines = ["sequenceDiagram", f"    %% {case_label}"]

    def participant_id(site: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", site) or "p"

    participants: list[str] = []
    for _role, site in graph["lanes"]:
        pid = participant_id(site)
        if pid not in participants:
            participants.append(pid)
            lines.append(f"    participant {pid} as {site}")

    if not participants:
        lines.append("    %% no trace events for this case")
        return "\n".join(lines) + "\n"

    edges = sorted(graph["edges"], key=lambda e: e["t0"])
    shown = edges[:max_edges]
    for edge in shown:
        src = participant_id(edge["src_site"])
        dst = participant_id(edge["dst_site"])
        arrow = "->>" if edge["label"] == "task" else "-->>"
        workflow = str(edge.get("workflow") or "").strip()
        label = f"{workflow} r{edge.get('round')}".strip()
        corr = (str(edge.get("corr_id") or ""))[:8]
        tag = f" [{corr}]" if corr else (" [fb]" if edge.get("method") == "fallback" else "")
        lines.append(f"    {src}{arrow}{dst}: {edge['label']} {label}{tag}")
    if len(edges) > len(shown):
        lines.append(f"    Note over {participants[0]}: (+{len(edges) - len(shown)} more messages truncated)")
    if not edges:
        lines.append(
            f"    Note over {participants[0]}: no cross-party messages correlated "
            "(task ids unavailable); see the Perfetto trace for per-party spans"
        )
    return "\n".join(lines) + "\n"


def _dot_from_graph(case_label: str, graph: dict[str, Any], max_nodes: int = 800) -> str:
    """Render the causal DAG as Graphviz DOT: the Lamport / space-time graph.

    One column per party, events chained top-to-bottom in program order and
    labelled with their Lamport clock, and send->receive message edges crossing
    columns. Render with ``dot -Tsvg <case>.lamport.dot -o <case>.svg``.
    """
    recs = graph.get("recs") or []
    lamport = graph.get("lamport") or []
    lanes = graph["lanes"]

    def esc(text: str) -> str:
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    included = set(range(len(recs)))
    truncated = 0
    if len(recs) > max_nodes:
        keep = sorted(range(len(recs)), key=lambda n: (lamport[n] if lamport else n, n))[:max_nodes]
        included = set(keep)
        truncated = len(recs) - len(included)

    lines = [
        f'digraph "taskflow" {{',
        f'  label="{esc(case_label)}  (Lamport depth {graph.get("max_lamport", 0)}'
        f'{"" if graph.get("acyclic", True) else "; CYCLE - wall-clock fallback"})";',
        # Columns come from the per-party node `group` (not clusters, which
        # trigger Graphviz "trouble in init_rank" on inter-column edges).
        "  labelloc=t; fontsize=12; rankdir=TB; splines=polyline;",
        '  node [shape=box, style=rounded, fontsize=9, fontname="monospace"];',
        '  edge [fontsize=8];',
    ]

    lane_records: dict[tuple[str, str], list[int]] = {lane: [] for lane in lanes}
    for record in recs:
        idx = record["_idx"]
        if idx not in included:
            continue
        lane = (str(record.get("role") or "?"), str(record.get("site") or "?"))
        lane_records.setdefault(lane, []).append(idx)

    def group_id(lane: tuple[str, str]) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", f"{lane[0]}_{lane[1]}") or "g"

    # A header node per party keeps its label at the top of the column, and the
    # shared `group` keeps that party's events in a straight vertical line.
    for lane_num, lane in enumerate(lanes):
        grp = group_id(lane)
        idxs = sorted(lane_records.get(lane, []), key=lambda n: (_seq(recs[n]), n))
        lines.append(
            f'  hdr_{lane_num} [label="{esc(lane[0])}:{esc(lane[1])}", shape=box, '
            f'style="filled,rounded", fillcolor="#f3f4f6", group="{grp}"];'
        )
        for idx in idxs:
            record = recs[idx]
            rnd = record.get("round")
            rnd_txt = f" r{rnd}" if rnd not in (None, -1) else ""
            wf = str(record.get("workflow") or "")
            wf_txt = (wf[:22] + "...") if len(wf) > 25 else wf
            clk = lamport[idx] if lamport else "?"
            label = f'L{clk} {esc(record.get("kind"))}\\n{esc(wf_txt)}{esc(rnd_txt)}'
            lines.append(f'  n{idx} [label="{label}", group="{grp}"];')
        # Header sits above the first event; program-order chain runs the column.
        chain = ([f"hdr_{lane_num}"] + [f"n{idx}" for idx in idxs]) if idxs else [f"hdr_{lane_num}"]
        for previous, current in zip(chain, chain[1:]):
            style = "style=invis" if previous == f"hdr_{lane_num}" else 'color="#d1d5db", arrowsize=0.5'
            lines.append(f"  {previous} -> {current} [{style}, weight=10];")

    for edge in graph["edges"]:
        src, dst = edge["src_idx"], edge["dst_idx"]
        if src not in included or dst not in included:
            continue
        color = "#3f5fff" if edge["label"] == "task" else "#f53d3d"
        style = "dashed" if edge.get("method") == "fallback" else "solid"
        wf = str(edge.get("workflow") or "").strip()
        elabel = f'{edge["label"]} {wf} r{edge.get("round")}'.strip()
        lines.append(
            f'  n{src} -> n{dst} [color="{color}", style={style}, constraint=false, '
            f'label="{esc(elabel)}"];'
        )

    if truncated:
        # We keep the lowest-Lamport (earliest) events and drop the most recent,
        # so the note must say the *latest* events were the ones truncated.
        lines.append(
            f'  _trunc [shape=note, color="#9ca3af", '
            f'label="+{truncated} later events truncated; raise max_nodes to see all"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _round_sort_key(round_value: Any) -> tuple[int, Any]:
    try:
        return (0, int(round_value))
    except (TypeError, ValueError):
        return (1, str(round_value))


def _round_analysis(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-(workflow, round) straggler and RTT decomposition, from the trace.

    Decomposes each client's task cycle into idle-wait (polling before the task
    was ready), fetch (task delivery + deserialize), compute, and send
    (result serialize + delivery) -- the split the profiler's single
    ``downstream_rtt`` collapses. Straggler gap is how long the server waited
    between the first and last client's result arrival that round: the classic
    critical-path signal for a synchronous federated round.
    """
    site_by_task: dict[str, str] = {}
    server_by_task: dict[str, dict[str, Any]] = {}
    client_events: dict[str, list[dict[str, Any]]] = {}
    for record in recs:
        role = record.get("role")
        task_id = record.get("task_id")
        if role == "client":
            client_events.setdefault(str(record.get("site") or "?"), []).append(record)
            if record.get("kind") == "task_recv" and task_id:
                site_by_task.setdefault(str(task_id), str(record.get("site") or "?"))
        elif role == "server" and record.get("kind") in ("submission_done", "result_recv") and task_id:
            tid = str(task_id)
            t = _ts_or0(record)
            prior = server_by_task.get(tid)
            if prior is None or t < prior["ts"]:
                server_by_task[tid] = {"wf": record.get("workflow"), "round": record.get("round"), "ts": t}

    rounds: dict[tuple[str, str], dict[str, Any]] = {}
    for site, events in client_events.items():
        events.sort(key=lambda r: (_seq(r), _ts_or0(r)))
        pending_pulls: list[float] = []
        cycle: dict[str, Any] | None = None
        for record in events:
            kind = record.get("kind")
            if kind == "pull_start":
                pending_pulls.append(_ts_or0(record))
            elif kind == "task_recv":
                cycle = {
                    "task_id": str(record.get("task_id") or ""),
                    "wf": record.get("workflow"),
                    "round": record.get("round"),
                    "t_recv": _ts(record),
                    "pulls": pending_pulls,
                    "compute_end": None,
                    "send_start": None,
                    "send_end": None,
                }
                pending_pulls = []
            elif cycle is None:
                continue
            elif kind == "compute_end":
                cycle["compute_end"] = _ts(record)
            elif kind == "send_start":
                cycle["send_start"] = _ts(record)
            elif kind == "send_end":
                cycle["send_end"] = _ts(record)
                meta = server_by_task.get(cycle["task_id"])
                wf = (meta or {}).get("wf") or cycle["wf"]
                rnd = (meta or {}).get("round")
                if rnd is None or rnd == -1:
                    rnd = cycle["round"]
                if wf and wf != "default" and rnd not in (None, -1):
                    pulls = cycle["pulls"]
                    t_recv = cycle["t_recv"]
                    compute_end = cycle["compute_end"]
                    send_end = cycle["send_end"]
                    wait = (max(pulls) - min(pulls)) if len(pulls) >= 2 else 0.0
                    # Guard every subtraction on `is not None`: _ts yields None for a
                    # missing stamp, and truthiness would misread a legitimate 0.0 (or
                    # crash on None) into a ~1.7e9 s phantom span.
                    fetch = (t_recv - max(pulls)) if (pulls and t_recv is not None) else 0.0
                    compute = (compute_end - t_recv) if (compute_end is not None and t_recv is not None) else 0.0
                    send_start = (
                        cycle["send_start"] if cycle["send_start"] is not None
                        else compute_end if compute_end is not None
                        else send_end
                    )
                    send = (send_end - send_start) if (send_end is not None and send_start is not None) else 0.0
                    key = (str(wf), str(rnd))
                    acc = rounds.setdefault(
                        key, {"compute": {}, "wait": {}, "fetch": {}, "send": {}, "clients": set(), "arrivals": {}}
                    )
                    acc["clients"].add(site)
                    # Keep wait/fetch/send per-site (last cycle wins), consistent with
                    # compute -- appending double-counted a site running two cycles in
                    # one round while compute kept only the last value.
                    acc["compute"][site] = max(0.0, compute)
                    acc["wait"][site] = max(0.0, wait)
                    acc["fetch"][site] = max(0.0, fetch)
                    acc["send"][site] = max(0.0, send)
                    if meta is not None:
                        prior = acc["arrivals"].get(site)
                        acc["arrivals"][site] = meta["ts"] if prior is None else min(prior, meta["ts"])
                cycle = None

    analysis: list[dict[str, Any]] = []
    for key in sorted(rounds, key=lambda k: (k[0], _round_sort_key(k[1]))):
        acc = rounds[key]
        compute = acc["compute"]
        arrivals = acc["arrivals"]
        slowest = max(compute, key=compute.get) if compute else None
        row: dict[str, Any] = {
            "workflow": key[0],
            "round": key[1],
            "contributions": len(acc["clients"]),
            "clients": sorted(acc["clients"]),
            "compute_sec": {
                "min": round(min(compute.values()), 4) if compute else None,
                "max": round(max(compute.values()), 4) if compute else None,
                "mean": round(_avg(list(compute.values())), 4) if compute else None,
                "slowest_client": slowest,
            },
        }
        for name in ("wait", "fetch", "send"):
            # acc[name] is now a per-site dict (FIX #11b); average/max over its
            # values, one entry per site, matching the old one-value-per-site list.
            vals = list(acc[name].values())
            row[f"{name}_sec"] = {"mean": round(_avg(vals), 4), "max": round(max(vals), 4) if vals else 0.0}
        if len(arrivals) >= 2:
            gap = max(arrivals.values()) - min(arrivals.values())
            row["straggler_gap_sec"] = round(max(0.0, gap), 4)
            row["straggler_client"] = max(arrivals, key=arrivals.get)
        else:
            row["straggler_gap_sec"] = None
            row["straggler_client"] = None
        analysis.append(row)
    return analysis


def _rounds_txt(case_label: str, analysis: list[dict[str, Any]]) -> str:
    lines = [
        f"Per-round straggler & RTT decomposition  ({case_label})",
        "",
        "Derived from the causal trace. Definitions:",
        "  contrib    = clients whose result the server received this round",
        "  strag gap  = last client's result arrival minus the first, at the server",
        "               (server idle-wait for the slowest client)",
        "  wait       = client idle-polling before the task was ready (max across clients)",
        "  fetch      = task delivery + deserialize at the client (max)",
        "  compute    = client task execution (max, with the slowest client)",
        "  send       = result serialize + delivery (max)",
        "",
        f"{'workflow':<48} {'round':>5} {'contrib':>7} {'compute max':>12} {'slowest':>8} "
        f"{'strag gap':>10} {'wait max':>9} {'fetch max':>10} {'send max':>9}",
    ]

    def sec(row: dict[str, Any], field: str, sub: str) -> str:
        block = row.get(field)
        if not isinstance(block, dict) or block.get(sub) is None:
            return "-"
        return f"{float(block[sub]):.3f}"

    for row in analysis:
        compute = row.get("compute_sec") or {}
        slowest = str(compute.get("slowest_client") or "-")
        strag = row.get("straggler_gap_sec")
        lines.append(
            f"{str(row['workflow'])[:48]:<48} {str(row['round']):>5} "
            f"{str(row.get('contributions', '-')):>7} {sec(row, 'compute_sec', 'max'):>12} "
            f"{slowest[:8]:>8} {(f'{strag:.3f}' if strag is not None else '-'):>10} "
            f"{sec(row, 'wait_sec', 'max'):>9} {sec(row, 'fetch_sec', 'max'):>10} {sec(row, 'send_sec', 'max'):>9}"
        )
    lines.append("")
    return "\n".join(lines)


def _round_detail_row(
    rr: dict[str, Any],
    parallel_by_round: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Flatten one _round_analysis row and merge its HE parallelism stats."""
    par = parallel_by_round.get((str(rr.get("workflow")), str(rr.get("round")))) or {}
    cs = rr.get("compute_sec") or {}
    return {
        "workflow": rr.get("workflow"),
        "round": rr.get("round"),
        "contributions": rr.get("contributions"),
        "compute_max_sec": cs.get("max"),
        "slowest_client": cs.get("slowest_client"),
        "straggler_gap_sec": rr.get("straggler_gap_sec"),
        "straggler_client": rr.get("straggler_client"),
        "wait_max_sec": (rr.get("wait_sec") or {}).get("max"),
        "fetch_max_sec": (rr.get("fetch_sec") or {}).get("max"),
        "send_max_sec": (rr.get("send_sec") or {}).get("max"),
        "workers_used": par.get("workers_used"),
        "workers_cap": par.get("workers_cap"),
        "chunks": par.get("chunks"),
        "section_wall_sec": par.get("section_wall_sec"),
    }


# --------------------------------------------------------------------------- #
# Time-based swimlane (best-effort; requires matplotlib). Mirrors the host-side
# taskflow_report.py renderer so the sweep emits the same trace diagram.
# --------------------------------------------------------------------------- #
_TL_TASK = "#3f5fff"
_TL_RESULT = "#f53d3d"
_TL_COMPUTE_F, _TL_COMPUTE_E = "#e0e6ff", "#3f5fff"
_TL_AGG_F, _TL_AGG_E = "#e7ddfb", "#7c3aed"
_TL_SEND_F, _TL_SEND_E = "#fdecc8", "#d97706"
_TL_BG_F, _TL_BG_E = "#f3f4f6", "#9ca3af"  # background/off-critical-path (hatched)
_TL_LIFELINE = "#cbd5e1"
_TL_INK = "#111827"
_TL_MUTED = "#6b7280"


def _write_timeline_svg(
    graph: dict[str, Any],
    out_path: Path,
    title: str,
    block_labels: dict[int, str] | None = None,
) -> tuple[bool, str | None]:
    """Render the time-based swimlane to SVG. Returns (ok, note-on-skip)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as exc:  # matplotlib missing or headless setup failed
        return False, f"matplotlib unavailable ({exc.__class__.__name__})"

    try:
        lanes = graph["lanes"]
        if not lanes:
            return False, "no lanes"
        t0 = graph["t0"]
        recs = graph["recs"]
        t1 = max((t for r in recs if (t := _ts(r)) is not None), default=t0 + 1)
        xof = {lane: i for i, lane in enumerate(lanes)}
        dur = max(1.0, t1 - t0)

        def yt(t: float) -> float:
            return t - t0

        lo, hi = 0.0, dur

        # Clamp height: at 100 dpi matplotlib's Agg backend rejects figures over
        # 2**16 px (~655 in). Cap at 600 in (~60000 px) so long jobs still render.
        fig_w = max(11.0, 1.85 * len(lanes) + 2.2)
        fig_h = max(5.5, min(dur * 0.28, 80.0))
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        by_lane: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for r in recs:
            by_lane.setdefault((r.get("role"), r.get("site")), []).append(r)
        ranges: dict[str, list[float]] = {}
        for rs in by_lane.values():
            rs.sort(key=lambda r: (_seq(r), _ts_or0(r)))
            cur = None
            for r in rs:
                wf, kind = r.get("workflow"), r.get("kind")
                if kind in ("bg_start", "bg_end"):
                    continue  # async background span -- not part of any workflow's phase box
                if wf and wf != "default":
                    cur = wf
                elif kind in ("compute_end", "send_start", "send_end"):
                    wf = cur
                else:
                    wf = None
                if not wf or wf == "default":
                    continue
                t = _ts_or0(r)
                rng = ranges.setdefault(wf, [t, t])
                rng[0], rng[1] = min(rng[0], t), max(rng[1], t)

        ordered = sorted(ranges.items(), key=lambda kv: kv[1][0])
        xL, xR = -0.46, len(lanes) - 1 + 0.46
        for i, (wf, (a, b)) in enumerate(ordered):
            end = min(b, ordered[i + 1][1][0]) if i + 1 < len(ordered) else b
            y0, y1 = max(yt(a), lo), min(yt(end), hi)
            if y1 <= lo or y0 >= hi:
                continue
            fill = ("#f9fafb", "#f3f4f6")[i % 2]
            ax.add_patch(Rectangle((xL, y0), xR - xL, max(y1 - y0, 1e-3),
                                   facecolor=fill, edgecolor="#e5e7eb", lw=1, zorder=0))
            ax.annotate(str(wf).replace("workflow_", ""), (xL + 0.04, y0), xytext=(0, -2),
                        textcoords="offset points", va="top", ha="left", fontsize=7.0,
                        fontweight="bold", color="#4b5563", zorder=6,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#e5e7eb", alpha=0.92))

        # lifelines + headers
        for lane, x in xof.items():
            ax.plot([x, x], [lo, hi], color=_TL_LIFELINE, lw=1.3, zorder=1)
            ax.annotate(f"{lane[0]}:{lane[1]}", (x, lo), xytext=(0, 10),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=8.0, fontweight="bold", color=_TL_INK,
                        bbox=dict(boxstyle="round,pad=0.35", fc="#eef2ff", ec="#c7d2fe", lw=1))

        # duration bars
        for s in graph["spans"]:
            lane = s["lane"]
            if lane not in xof:
                continue
            hatch = None
            ls = "solid"
            off = 0.0
            if s["label"] == "compute" and lane[0] == "client":
                fc, ec = _TL_COMPUTE_F, _TL_COMPUTE_E
            elif s["label"] == "send" and lane[0] == "client":
                fc, ec = _TL_SEND_F, _TL_SEND_E
            elif s["label"] == "aggregate" and lane[0] == "server":
                fc, ec = _TL_AGG_F, _TL_AGG_E
            elif s["label"] == "background" and lane[0] == "client":
                fc, ec = _TL_BG_F, _TL_BG_E
                hatch, ls, off = "////", (0, (4, 2)), 0.11
            else:
                continue
            x = xof[lane]
            y0, y1 = yt(s["t0"]), yt(s["t1"])
            ax.add_patch(Rectangle((x - 0.07 + off, y0), 0.14, max(y1 - y0, 1e-3),
                                   facecolor=fc, edgecolor=ec, lw=0.9, zorder=3,
                                   hatch=hatch, linestyle=ls))
            if (s["t1"] - s["t0"]) >= 0.75:
                ax.annotate(f"{s['t1']-s['t0']:.2f}s", (x + 0.09 + off, (y0 + y1) / 2),
                            fontsize=6.2, color=ec, va="center", zorder=4)
            label = (block_labels or {}).get(s.get("open_idx"))
            if label:
                ax.annotate(label, (x - 0.1, (y0 + y1) / 2), ha="right", va="center",
                            fontsize=6.2, fontweight="bold", color=ec, zorder=5,
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=ec, lw=0.8, alpha=0.95))

        # messages (horizontal-ish arrows at send/receive time)
        def lane_for(site: Any, role: str) -> tuple[str, str] | None:
            cand = (role, site)
            return cand if cand in xof else None

        for e in graph["edges"]:
            sl = lane_for(e["src_site"], "server" if e["label"] == "task" else "client")
            dl = lane_for(e["dst_site"], "client" if e["label"] == "task" else "server")
            if sl is None or dl is None:
                continue
            col = _TL_TASK if e["label"] == "task" else _TL_RESULT
            ax.annotate("", xy=(xof[dl], yt(e["t1"])), xytext=(xof[sl], yt(e["t0"])),
                        arrowprops=dict(arrowstyle="-|>", color=col, lw=0.9, alpha=0.78,
                                        shrinkA=0, shrinkB=0), zorder=2)
            ax.plot([xof[sl]], [yt(e["t0"])], marker="o", ms=2.2, color=col, zorder=3)

        ax.set_xlim(-0.6, len(lanes) - 0.4)
        ax.set_ylim(hi, lo)  # inverted: time flows downward
        # Case wall-time marker. The y-axis is elapsed from the FIRST event across
        # all parties, but the server starts a few seconds before the clients
        # connect, so the raw envelope (t1 - t0) over-counts. Report the max single
        # party span instead (each party's own first->last event == its profiler
        # wall_time_sec == the performance report's "case wall time"), and draw the
        # line at that elapsed value so axis position and label agree.
        _lane_span: Dict[Tuple[Any, Any], List[float]] = {}
        for r in recs:
            rt = _ts(r)
            if rt is None:
                continue
            lk = (r.get("role"), r.get("site"))
            sp = _lane_span.get(lk)
            if sp is None:
                _lane_span[lk] = [rt, rt]
            else:
                sp[0], sp[1] = min(sp[0], rt), max(sp[1], rt)
        # Max single-party span (each party's own first->last event span, ==
        # its profiler wall_time_sec). Max over ALL parties including the server,
        # whose span covers the whole run.
        wall = max((b - a for a, b in _lane_span.values()), default=dur)
        if lo <= wall <= hi:
            ax.axhline(wall, color="#d97706", lw=1.0, ls=(0, (5, 3)), alpha=0.7, zorder=1)
            ax.annotate(f"case wall {wall:.1f}s", xy=(0.0, wall),
                        xycoords=("axes fraction", "data"), xytext=(4, 2),
                        textcoords="offset points", ha="left", va="bottom",
                        fontsize=6.0, fontweight="bold", color=_TL_INK, zorder=8,
                        bbox=dict(boxstyle="round,pad=0.16", fc="#fef3c7", ec="#d97706", lw=0.7, alpha=0.95))
        ax.set_xticks([])
        ax.set_ylabel("elapsed time (s)", fontsize=8.0, color=_TL_MUTED)
        ax.tick_params(axis="y", labelsize=7.0, colors=_TL_MUTED)
        ax.grid(axis="y", color="#f3f4f6", lw=0.8)
        for sp in ("top", "right", "bottom"):
            ax.spines[sp].set_visible(False)
        ax.spines["left"].set_color("#e5e7eb")
        # Keep metadata out of the top of the timeline so lane/workflow data can
        # begin immediately.  Render the job/timing note as a compact footer.
        title_text = f"{title}   (y = elapsed time; arrows show send/receive timing)"
        footer_fraction = min(0.08, 0.30 / fig_h)
        fig.text(
            0.055,
            max(0.006, footer_fraction * 0.20),
            title_text,
            ha="left",
            va="bottom",
            fontsize=6.2,
            fontweight="normal",
            color=_TL_MUTED,
        )
        fig.tight_layout(rect=(0.0, footer_fraction, 1.0, 1.0), pad=0.15)
        fig.savefig(str(out_path), bbox_inches="tight")
        plt.close(fig)
        return True, None
    except Exception as exc:
        return False, f"timeline render failed ({exc.__class__.__name__}: {exc})"


def build_taskflow_artifacts(
    workspace_root: Path,
    out_dir: Path,
    event_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge per-party traces into per-case Perfetto + Mermaid artifacts."""
    cases = _load_trace_records(workspace_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    total_events = 0
    total_edges = 0

    for workspace in sorted(cases, key=_workspace_order):
        records = cases[workspace]
        total_events += len(records)
        label = workspace
        if event_lookup:
            event = _event_for_workspace(workspace, event_lookup)
            if event and event.get("nodeid"):
                label = str(event["nodeid"])
        graph = _build_case_graph(records)
        total_edges += len(graph["edges"])
        (out_dir / f"{workspace}.perfetto.json").write_text(
            json.dumps(_perfetto_from_graph(label, graph)), encoding="utf-8"
        )
        (out_dir / f"{workspace}.seq.mmd").write_text(
            _mermaid_from_graph(label, graph), encoding="utf-8"
        )
        (out_dir / f"{workspace}.lamport.dot").write_text(
            _dot_from_graph(label, graph), encoding="utf-8"
        )
        rounds = _round_analysis(graph["recs"])
        (out_dir / f"{workspace}.rounds.json").write_text(json.dumps(rounds, indent=2), encoding="utf-8")
        (out_dir / f"{workspace}.rounds.txt").write_text(_rounds_txt(label, rounds), encoding="utf-8")
        parallel_by_round: dict[tuple[str, str], dict[str, Any]] = {}
        for r in graph["recs"]:
            if r.get("kind") == "agg_end":
                par = (r.get("meta") or {}).get("parallel")
                if isinstance(par, dict):
                    parallel_by_round[(str(r.get("workflow")), str(r.get("round")))] = par
        round_detail = [_round_detail_row(rr, parallel_by_round) for rr in rounds]
        block_labels: dict[int, str] = {}
        for s in graph["spans"]:
            par = (s.get("meta") or {}).get("parallel")
            if isinstance(par, dict) and par.get("workers_used") is not None:
                used, cap = par.get("workers_used"), par.get("workers_cap")
                block_labels[s["open_idx"]] = f"{used}w" if used == cap else f"{used}w/cap{cap}"
        timeline_name = f"{workspace}.timeline.svg"
        ok_svg, svg_note = _write_timeline_svg(graph, out_dir / timeline_name, label, block_labels or None)
        if not ok_svg:
            log(f"Taskflow timeline skipped for {label}: {svg_note}")
        measured_strag = [r["straggler_gap_sec"] for r in rounds if r.get("straggler_gap_sec") is not None]
        straggler_total = round(sum(measured_strag), 3) if measured_strag else None
        straggler_max = round(max(measured_strag), 3) if measured_strag else None
        index.append(
            {
                "workspace": workspace,
                "nodeid": label,
                "timeline": timeline_name if ok_svg else None,
                "events": len(records),
                "lanes": len(graph["lanes"]),
                "spans": len(graph["spans"]),
                "edges": len(graph["edges"]),
                "edges_by_id": graph["correlation"]["by_id"],
                "edges_fallback": graph["correlation"]["fallback"],
                "lamport_depth": graph["max_lamport"],
                "acyclic": graph["acyclic"],
                "rounds": len(rounds),
                "straggler_wait_total_sec": straggler_total,
                "straggler_wait_max_sec": straggler_max,
                "round_detail": round_detail,
            }
        )

    summary = {
        "case_count": len(index),
        "event_count": total_events,
        "edge_count": total_edges,
        "cases": index,
    }
    (out_dir / "index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md_lines = [
        "# Taskflow traces",
        "",
        "Per-test-case causal event traces merged from every party's `trace.jsonl`.",
        "",
        "- `*.timeline.svg` — time-based swimlane trace diagram (parties = columns, y = elapsed time).",
        "- `*.perfetto.json` — open in https://ui.perfetto.dev (or chrome://tracing).",
        "- `*.seq.mmd` — render with any Mermaid viewer.",
        "- `*.lamport.dot` — the causal / Lamport graph; render with "
        "`dot -Tsvg <case>.lamport.dot -o <case>.svg`.",
        "- `*.rounds.txt` / `*.rounds.json` — per-round straggler + RTT decomposition "
        "(idle-wait / fetch / compute / send).",
        "",
        "`msgs` counts correlated messages (`id` = task-id/corr-id matched, "
        "`fb` = workflow/round fallback). `L-depth` is the longest happens-before "
        "chain (Lamport clock maximum). `straggler` is the total (and worst single-round) "
        "server idle-wait between the first and last client's result arrival.",
        "",
        "| case | events | lanes | spans | msgs (id/fb) | L-depth | rounds | straggler tot/max (s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in index:
        cyc = "" if row["acyclic"] else " ⚠cycle"
        md_lines.append(
            f"| {row['nodeid']} | {row['events']} | {row['lanes']} | {row['spans']} | "
            f"{row['edges']} ({row['edges_by_id']}/{row['edges_fallback']}) | {row['lamport_depth']}{cyc} | "
            f"{row['rounds']} | {row['straggler_wait_total_sec']}/{row['straggler_wait_max_sec']} |"
        )
    md_lines.append("")
    (out_dir / "index.md").write_text("\n".join(md_lines), encoding="utf-8")
    return summary


def write_taskflow_artifacts(events_path: Path, workspace_root: Path, results_root: Path) -> dict[str, Any]:
    """Create taskflow trace artifacts after pytest has completed."""
    event_lookup = _profile_case_lookup(events_path)
    out_dir = results_root / "taskflow"
    summary = build_taskflow_artifacts(workspace_root, out_dir, event_lookup)
    log(
        f"Taskflow trace: {summary['case_count']} case(s), {summary['event_count']} event(s), "
        f"{summary['edge_count']} correlated message(s) -> {out_dir}"
    )
    return summary


# lean defaults HE workers to 1 (see run_pytest) and pins a reduced ring dimension, so its
# keys are far smaller than at full security and a case needs correspondingly less RAM.
# When the caller forwards OPENFHE_BIOMARKER_MAX_WORKERS > 1, the per-case need scales with it.
# Concurrent cases are capped by BOTH cores and RAM:
#   -n = min(requested-or-auto, cores, floor(RAM-budget / (_LEAN_GB_PER_CASE * HE workers))).
_LEAN_GB_PER_CASE = 8


def _he_worker_count() -> int:
    """Forwarded HE worker count from OPENFHE_BIOMARKER_MAX_WORKERS; always >= 1.

    lean pins this to 1 unless the caller forwarded a larger value. Each additional
    HE worker roughly scales a case's peak RAM, so the -n budget must account for it.
    Treats unset/blank/invalid as 1.
    """
    raw = os.getenv("OPENFHE_BIOMARKER_MAX_WORKERS", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _memory_budget_kb() -> int | None:
    """Best-effort RAM budget in KB: the smaller of MemTotal and any cgroup limit.

    Prefers a cgroup memory limit (v2 ``memory.max`` or v1 ``memory.limit_in_bytes``)
    when it parses to a positive value below MemTotal, so a memory-capped container
    budgets against its real ceiling rather than the host's total RAM. Best-effort:
    returns None only when MemTotal itself can't be read; an unreadable, absent, or
    ``max`` cgroup file just leaves the budget at MemTotal.
    """
    mem_total_kb: int | None = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                    break
    except Exception:
        mem_total_kb = None
    if mem_total_kb is None:
        return None

    budget_kb = mem_total_kb
    for cgroup_path in (
        "/sys/fs/cgroup/memory.max",  # cgroup v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroup v1
    ):
        try:
            with open(cgroup_path, encoding="utf-8") as fh:
                raw = fh.read().strip()
        except OSError:
            continue
        if not raw or raw == "max":  # v2 unlimited sentinel
            continue
        try:
            limit_bytes = int(raw)
        except ValueError:
            continue
        # v1 unlimited is a huge sentinel (~INT64_MAX); the < budget guard skips it.
        if limit_bytes > 0:
            limit_kb = limit_bytes // 1024
            if 0 < limit_kb < budget_kb:
                budget_kb = limit_kb
        break
    return budget_kb


def _lean_worker_count(requested: int) -> int:
    """lean concurrent-case count: min(requested-or-auto, cores, RAM-budget).

    The RAM budget scales with the forwarded HE worker count (each concurrent case
    needs ~``_LEAN_GB_PER_CASE`` GB per HE worker) and uses the smaller of host
    MemTotal and any cgroup memory limit (see ``_memory_budget_kb``).
    """
    cores = os.cpu_count() or 1
    gb_per_case = _LEAN_GB_PER_CASE * max(1, _he_worker_count())
    mem_cap = 2  # conservative fallback when RAM can't be read
    budget_kb = _memory_budget_kb()
    if budget_kb is not None:
        mem_cap = max(1, budget_kb // (gb_per_case * 1024 * 1024))
    cap = max(1, min(cores, mem_cap))
    requested = int(requested)
    return min(requested, cap) if requested > 0 else cap


def run_pytest() -> int:
    test_target = os.getenv("DUALITY_TEST_TARGET", "tests/").strip() or "tests/"
    target_path = Path(test_target)
    if target_path.is_absolute() or ".." in target_path.parts:
        raise RuntimeError("DUALITY_TEST_TARGET must be a safe path relative to nvflare_jobs.")
    keyword = os.getenv("DUALITY_TEST_KEYWORD", "").strip()
    extra_args = parse_json_list("DUALITY_TEST_PYTEST_ARGS")
    # lean (default): pass/fail/skip + test detail only
    lean = os.getenv("DUALITY_SWEEP_MODE", "lean").strip().lower() != "full"

    junit_path = RESULTS_ROOT / "junit.xml"
    pytest_output = RESULTS_ROOT / "pytest-output.txt"
    full_console_output = RESULTS_ROOT / "full-console-output.txt"
    events_path = RESULTS_ROOT / "pytest-status-events.jsonl"
    workspace_root = RESULTS_ROOT / "simulator-workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "-s",
        test_target,
        f"--junitxml={junit_path}",
        f"--basetemp={workspace_root}",
        "-p",
        REPORTER_MODULE,
    ]
    workers = 1
    if lean:
        # DUALITY_SWEEP_JOBS <= 0 means auto (min(cores, RAM cap)).
        workers = _lean_worker_count(int(os.getenv("DUALITY_SWEEP_JOBS", "0") or "0"))
        if workers > 1:
            command.extend(("-n", str(workers)))
    if keyword:
        command.extend(("-k", keyword))
    command.extend(extra_args)

    log("\n=== NVFlare simulator sweep ===")
    log(f"Physical datasource: {os.getenv('DUALITY_RUNNER_DATASOURCE_KEY', 'unknown')}")
    # conftest applies the lean default inside pytest; only an explicit value is known here.
    ring_note = os.getenv("DUALITY_SIM_CKKS_RING_DIM", "").strip() or (
        "lean default (reduced)" if lean else "full security"
    )
    log(f"Sweep mode: {'lean' if lean else 'full'}"
        + (f" (parallel -n {workers}, no profiling/perf artifacts)" if lean
           else " (serial, profiling + performance report)"))
    log(f"CKKS ring dimension: {ring_note}")
    log(f"Python: {sys.executable}")
    try:
        import nvflare  # noqa: PLC0415
        log(f"NVFlare: {nvflare.__version__}")
    except Exception:
        log("NVFlare: import failed unexpectedly")
    log(f"Test target: {test_target}")
    log(f"Results directory: {RESULTS_ROOT}\n")

    environment = os.environ.copy()
    environment["DUALITY_RUNNER_PYTEST_EVENTS"] = str(events_path)
    if lean and not environment.get("OPENFHE_BIOMARKER_MAX_WORKERS", "").strip():
        environment["OPENFHE_BIOMARKER_MAX_WORKERS"] = "1"
    log_file = None if lean else full_console_output.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=WORK_JOBS,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=environment,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            if log_file is not None:
                log_file.write(line)
                log_file.flush()
        exit_code = process.wait()
    finally:
        if log_file is not None:
            log_file.close()

    write_pytest_output(junit_path, events_path, pytest_output, exit_code)
    if lean:
        # Prune the heavy simulator workspaces only on success; keep them on a
        # non-zero exit so a failed sweep can be debugged. The concise
        # pytest-output.txt / junit.xml live under RESULTS_ROOT and are untouched.
        if exit_code == 0:
            shutil.rmtree(workspace_root, ignore_errors=True)
    else:
        taskflow_summary: dict[str, Any] | None = None
        try:
            taskflow_summary = write_taskflow_artifacts(events_path, workspace_root, RESULTS_ROOT)
        except Exception:
            traceback.print_exc()
        write_performance_summary(
            events_path, workspace_root, RESULTS_ROOT, taskflow_summary=taskflow_summary
        )
    return exit_code


def _chown_to_host(path) -> None:
    """Hand ownership of bind-mount outputs back to the host user.

    This container runs as root (required to pip-install the runtime wheel), so
    anything it writes to a bind mount is root-owned on the host, which then can't
    regenerate or delete it without sudo. When DUALITY_HOST_UID/GID are set (the
    sweep runner passes the host's own uid/gid), recursively chown `path` back to
    them. No-op unless running as root with those vars set, so it's harmless
    outside a container.
    """
    try:
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            return
        uid = os.environ.get("DUALITY_HOST_UID", "").strip()
        if not uid:
            return
        uid_i = int(uid)
        gid_i = int(os.environ.get("DUALITY_HOST_GID", "").strip() or uid_i)
        root = Path(path)
        if not root.exists():
            return
        os.chown(root, uid_i, gid_i)
        for sub in root.rglob("*"):
            try:
                os.chown(sub, uid_i, gid_i)
            except OSError:
                pass
    except Exception:
        pass


def main() -> int:
    try:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        copy_jobs_source()
        reporter_path = install_pytest_reporter()
        log(f"Installed runner pytest detail reporter: {reporter_path}")
        schema = stage_global_schema()
        datasources = resolve_datasources()
        models = resolve_model_files()
        (RESULTS_ROOT / "staged-global-schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
        (RESULTS_ROOT / "resolved-datasources.json").write_text(json.dumps(datasources, indent=2), encoding="utf-8")
        (RESULTS_ROOT / "resolved-model-files.json").write_text(json.dumps(models, indent=2), encoding="utf-8")
        log("\nBuilding and installing the local duality_nvflare_lib wheel...")
        build_and_install_wheel()
        exit_code = run_pytest()
        log(f"\n=== pytest exited with code {exit_code} ===")
        return exit_code
    except subprocess.CalledProcessError as exc:
        return fail(f"Command failed ({exc.returncode}): {' '.join(map(str, exc.cmd))}", exc.returncode)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return fail(str(exc))
    finally:
        # Hand freshly written /results back to the host user so it can be read,
        # regenerated, or deleted without sudo (this container runs as root).
        _chown_to_host(RESULTS_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
