#!/usr/bin/env python3
"""Regenerate taskflow trace artifacts from an existing sweep results directory.

The container normally writes ``<results>/taskflow/`` automatically after a
sweep (see ``container_entrypoint.write_taskflow_artifacts``). This standalone
CLI re-runs the same emitter host-side against a results directory that already
contains ``simulator-workspaces/**/trace.jsonl`` (for example, to re-render after
editing the emitter, without a full Docker rerun).

    python build_taskflow_trace.py <results-dir> [--out <dir>]

<results-dir> is a single ``simulator-sweep-<stamp>`` folder. The emitter logic
lives in ``container_entrypoint.py`` so there is one source of truth.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parent
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

import container_entrypoint as ce  # noqa: E402  (path set above)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", help="A simulator-sweep-<stamp> results directory.")
    parser.add_argument(
        "--out",
        help="Output directory for taskflow artifacts. Defaults to <results-dir>/taskflow.",
    )
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir).expanduser().resolve()
    workspace_root = results_dir / "simulator-workspaces"
    if not workspace_root.is_dir():
        print(f"ERROR: no simulator-workspaces under {results_dir}", file=sys.stderr)
        return 2

    events_path = results_dir / "pytest-status-events.jsonl"
    event_lookup = ce._profile_case_lookup(events_path)
    out_dir = Path(args.out).expanduser().resolve() if args.out else results_dir / "taskflow"

    summary = ce.build_taskflow_artifacts(workspace_root, out_dir, event_lookup)
    print(
        f"Taskflow trace: {summary['case_count']} case(s), {summary['event_count']} event(s), "
        f"{summary['edge_count']} correlated message(s)\n  -> {out_dir}"
    )
    if summary["case_count"] == 0:
        print(
            "No trace.jsonl files were found. This results dir predates the profiler "
            "event-trace change, or the workspaces are unreadable.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
