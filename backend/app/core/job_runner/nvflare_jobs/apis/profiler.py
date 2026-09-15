"""
NVFlare Profiler: Per-party profiling for federated learning jobs.

Captures:
  1. System metrics: CPU, memory, network (per job)
  2. Per-workflow, per-round: runtime and communication time/payload
  3. Optional ``phase_breakdown_sec`` from :class:`StatAnalyticsEventType` START/END pairs
     (e.g. ``encrypt``, ``decrypt``, ``aggregate``, ``aggregate_reference``, ``compute`` for KeyGen).

Output: profile_summary.json per party (server and each client).

Also defines :class:`ProfileSummaryAggregator` and :class:`ProfileSummaryPersistor` for the
optional ``workflow_consolidate_profile_summaries`` SAG (see ``PROFILE_CONSOLIDATE_WORKFLOW_ID``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nvflare.apis.event_type import EventType
from nvflare.apis.fl_component import FLComponent
from nvflare.apis.fl_constant import FLContextKey, ReservedKey, ReturnCode
from nvflare.apis.fl_context import FLContext
from nvflare.apis.dxo import DataKind, from_shareable
from nvflare.apis.shareable import Shareable
from nvflare.app_common.abstract.aggregator import Aggregator
from nvflare.app_common.abstract.model import ModelLearnable, make_model_learnable
from nvflare.app_common.abstract.model_persistor import ModelPersistor
from nvflare.app_common.app_constant import AppConstants
from nvflare.app_common.app_event_type import AppEventType

from .HEAggregator import HEAggregator
from .stat_analytics_event_type import (
    PROFILE_CONSOLIDATE_WORKFLOW_ID,
    PROFILE_SNAPSHOT_EVENT,
    parse_stat_analytics_phase_event,
)
from . import fhe_timing

# Context keys for payload accumulation (set by HEAggregator / executor)
IN_KEY = "__prof_payload_in_acc"
OUT_KEY = "__prof_payload_out_acc"


def _now_mono() -> float:
    return time.perf_counter()


# ---------------------------------------------------------------------------
# System metrics sampler
# ---------------------------------------------------------------------------


@dataclass
class SystemMetrics:
    """System resource usage over a job's lifetime."""

    wall_time_sec: float = 0.0
    cpu_util_pct: float = 0.0
    cpu_user_pct: float = 0.0
    cpu_system_pct: float = 0.0
    cpu_iowait_pct: float = 0.0
    cpu_steal_pct: float = 0.0
    net_tx_bytes_total: int = 0
    net_rx_bytes_total: int = 0
    net_tx_mb_s: float = 0.0
    net_rx_mb_s: float = 0.0
    rss_max_kb: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_time_sec": round(self.wall_time_sec, 6),
            "cpu_util_pct": round(self.cpu_util_pct, 2),
            "cpu_user_pct": round(self.cpu_user_pct, 2),
            "cpu_system_pct": round(self.cpu_system_pct, 2),
            "cpu_iowait_pct": round(self.cpu_iowait_pct, 2),
            "cpu_steal_pct": round(self.cpu_steal_pct, 2),
            "net_tx_bytes_total": self.net_tx_bytes_total,
            "net_rx_bytes_total": self.net_rx_bytes_total,
            "net_tx_mb_s": round(self.net_tx_mb_s, 6),
            "net_rx_mb_s": round(self.net_rx_mb_s, 6),
            "rss_max_kb": self.rss_max_kb,
        }


class SystemSampler:
    """Lightweight per-job system metrics sampler using psutil."""

    def __init__(self, interval_sec: float = 1.0, include_children: bool = True):
        self.interval = float(interval_sec)
        self.include_children = include_children
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._t0: Optional[float] = None
        self._t1: Optional[float] = None
        self._cpu0 = None
        self._cpu1 = None
        self._net0 = None
        self._net1 = None
        self._rss_max_bytes: int = 0
        self._psutil_ok = False
        self._psutil = None
        self._proc = None

    def _try_init_psutil(self) -> None:
        if self._psutil_ok:
            return
        try:
            import psutil

            self._psutil = psutil
            self._proc = psutil.Process(os.getpid())
            self._psutil_ok = True
        except Exception:
            self._psutil_ok = False
            self._psutil = None
            self._proc = None

    def start(self) -> None:
        self._try_init_psutil()
        self._t0 = _now_mono()
        if self._psutil_ok:
            try:
                self._cpu0 = self._psutil.cpu_times()
            except Exception:
                self._cpu0 = None
            try:
                self._net0 = self._psutil.net_io_counters(pernic=False)
            except Exception:
                self._net0 = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="SystemSampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._t1 = _now_mono()
        if self._psutil_ok:
            try:
                self._cpu1 = self._psutil.cpu_times()
            except Exception:
                self._cpu1 = None
            try:
                self._net1 = self._psutil.net_io_counters(pernic=False)
            except Exception:
                self._net1 = None
        self._stop.set()
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._psutil_ok and self._proc is not None:
                try:
                    rss = self._proc.memory_info().rss
                    if self.include_children:
                        for c in self._proc.children(recursive=True):
                            try:
                                rss += c.memory_info().rss
                            except Exception:
                                pass
                    if rss > self._rss_max_bytes:
                        self._rss_max_bytes = rss
                except Exception:
                    pass
            self._stop.wait(self.interval)

    def results(self) -> SystemMetrics:
        duration = 0.0
        if isinstance(self._t0, float):
            end = self._t1 if isinstance(self._t1, float) else _now_mono()
            if end >= self._t0:
                duration = end - self._t0

        def _to_float(x: Any) -> float:
            try:
                return float(x)
            except Exception:
                return 0.0

        m = SystemMetrics(wall_time_sec=duration)

        if self._cpu0 is not None and self._cpu1 is not None:
            fields = set(dir(self._cpu0)).intersection(dir(self._cpu1))
            deltas: Dict[str, float] = {}
            for f in fields:
                if f.startswith("__"):
                    continue
                try:
                    d = _to_float(getattr(self._cpu1, f)) - _to_float(getattr(self._cpu0, f))
                    deltas[f] = max(0.0, d)
                except Exception:
                    pass
            total = sum(deltas.values()) or 1.0
            idle = deltas.get("idle", 0.0)
            m.cpu_util_pct = 100.0 * max(0.0, 1.0 - idle / total)
            m.cpu_user_pct = 100.0 * deltas.get("user", 0.0) / total
            m.cpu_system_pct = 100.0 * deltas.get("system", 0.0) / total
            m.cpu_iowait_pct = 100.0 * deltas.get("iowait", 0.0) / total
            m.cpu_steal_pct = 100.0 * deltas.get("steal", 0.0) / total

        tx_bytes = rx_bytes = 0
        if self._net0 is not None and self._net1 is not None:
            try:
                tx_bytes = int(self._net1.bytes_sent - self._net0.bytes_sent)
                rx_bytes = int(self._net1.bytes_recv - self._net0.bytes_recv)
            except Exception:
                pass
        m.net_tx_bytes_total = max(0, tx_bytes)
        m.net_rx_bytes_total = max(0, rx_bytes)
        if duration > 0:
            m.net_tx_mb_s = tx_bytes / duration / 1_000_000.0
            m.net_rx_mb_s = rx_bytes / duration / 1_000_000.0
        m.rss_max_kb = int(self._rss_max_bytes // 1024)
        return m


# ---------------------------------------------------------------------------
# Round/workflow extraction (robust for client-side)
# ---------------------------------------------------------------------------


def _extract_round_from_task_data(task_data: Any) -> Optional[int]:
    """Extract current round from task data (Shareable or dict)."""
    if task_data is None:
        return None
    # Shareable has get_header
    if hasattr(task_data, "get_header"):
        rnd = task_data.get_header(AppConstants.CURRENT_ROUND, None)
        if rnd is not None:
            return int(rnd)
    # Dict with __headers__
    if isinstance(task_data, dict):
        headers = task_data.get("__headers__") or {}
        rnd = headers.get(AppConstants.CURRENT_ROUND) or headers.get("current_round")
        if rnd is not None:
            return int(rnd)
        # Cookie jar: CONTRIBUTION_ROUND
        jar = headers.get("__cookie_jar__") or {}
        rnd = jar.get(AppConstants.CONTRIBUTION_ROUND) or jar.get("contribution_round")
        if rnd is not None:
            return int(rnd)
    return None


def _extract_workflow_from_task_data(task_data: Any) -> Optional[str]:
    """Extract workflow name from task data."""
    if task_data is None:
        return None
    if isinstance(task_data, dict):
        jar = (task_data.get("__headers__") or {}).get("__cookie_jar__") or {}
        return jar.get("__workflow__") or jar.get("workflow")
    return None


def _extract_round(fl_ctx: FLContext) -> int:
    """Extract current round from context. Returns -1 if unknown (caller may normalize)."""
    rnd = fl_ctx.get_prop(AppConstants.CURRENT_ROUND, None)
    if rnd is not None:
        return int(rnd)
    task_data = fl_ctx.get_prop(ReservedKey.TASK_DATA, None)
    rnd = _extract_round_from_task_data(task_data)
    if rnd is not None:
        return rnd
    return -1


def _extract_workflow(fl_ctx: FLContext) -> str:
    """Extract workflow name from context."""
    wf = fl_ctx.get_prop(FLContextKey.WORKFLOW, None)
    if wf is not None:
        return wf
    task_data = fl_ctx.get_prop(ReservedKey.TASK_DATA, None)
    wf = _extract_workflow_from_task_data(task_data)
    return wf if wf else "default"


# ---------------------------------------------------------------------------
# Profiler
# ---------------------------------------------------------------------------


@dataclass
class RoundMetrics:
    """Per-round metrics (client or server)."""

    client_compute_time_sec: float = 0.0
    downstream_rtt_sec: float = 0.0
    upstream_rtt_sec: float = 0.0
    server_dispatch_time_sec: float = 0.0
    server_accept_time_sec: float = 0.0
    server_aggregation_time_sec: float = 0.0
    payload_in_bytes: int = 0
    payload_out_bytes: int = 0
    # StatAnalyticsEventType START/END pairs (setup, preprocess, compute, aggregate, postprocess)
    phase_breakdown_sec: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.client_compute_time_sec > 0:
            d["client_compute_time_sec"] = round(self.client_compute_time_sec, 9)
        if self.downstream_rtt_sec > 0:
            d["downstream_rtt_sec"] = round(self.downstream_rtt_sec, 9)
        if self.upstream_rtt_sec > 0:
            d["upstream_rtt_sec"] = round(self.upstream_rtt_sec, 9)
        if self.server_dispatch_time_sec > 0 or self.server_accept_time_sec > 0 or self.server_aggregation_time_sec > 0:
            d["server_dispatch_time_sec"] = round(self.server_dispatch_time_sec, 9)
            d["server_accept_time_sec"] = round(self.server_accept_time_sec, 9)
            d["server_aggregation_time_sec"] = round(self.server_aggregation_time_sec, 9)
            d["server_compute_time_sec"] = round(
                self.server_dispatch_time_sec + self.server_accept_time_sec + self.server_aggregation_time_sec, 9
            )
        if self.payload_in_bytes > 0:
            d["payload_in_bytes"] = self.payload_in_bytes
        if self.payload_out_bytes > 0:
            d["payload_out_bytes"] = self.payload_out_bytes
        if self.phase_breakdown_sec:
            d["phase_breakdown_sec"] = {
                k: round(float(v), 9) for k, v in sorted(self.phase_breakdown_sec.items())
            }
        return d


class Profiler(FLComponent):
    """
    Event-driven profiler for NVFlare jobs.

    Records per-workflow, per-round runtime and communication metrics for server
    and clients, plus system metrics. Writes profile_summary.json per party.

    Client round extraction: Uses BEFORE_TASK_EXECUTION (always fires) to capture
    round from task data, since BEFORE_TASK_DATA_FILTER may not fire when
    task_data_filters is empty.

    Causal event trace (step 1): in addition to the duration accumulators, the
    profiler buffers one timestamped record per key lifecycle event and writes
    ``trace.jsonl`` beside ``profile_summary.json``. Event types are mapped to
    stable internal ``kind`` names via ``_EVENT_KIND`` so downstream tooling does
    not depend on NVFlare's raw event-string values. Messages are correlated by
    NVFlare task id when present; a cross-wire Lamport/vector clock is a later step.
    """

    # NVFlare event type -> stable trace "kind". Only these events are traced.
    _EVENT_KIND = {
        EventType.START_RUN: "run_start",
        EventType.END_RUN: "run_end",
        EventType.ABOUT_TO_END_RUN: "run_about_to_end",
        EventType.START_WORKFLOW: "workflow_start",
        AppEventType.ROUND_STARTED: "round_start",
        AppEventType.ROUND_DONE: "round_done",
        # Client task lifecycle
        EventType.BEFORE_PULL_TASK: "pull_start",
        EventType.BEFORE_TASK_EXECUTION: "task_recv",
        EventType.AFTER_TASK_EXECUTION: "compute_end",
        EventType.BEFORE_SEND_TASK_RESULT: "send_start",
        EventType.AFTER_SEND_TASK_RESULT: "send_end",
        # Server task lifecycle
        EventType.BEFORE_PROCESS_TASK_REQUEST: "dispatch_start",
        EventType.AFTER_PROCESS_TASK_REQUEST: "dispatch_end",
        EventType.TASK_RESULT_RECEIVED: "result_recv",
        EventType.AFTER_PROCESS_SUBMISSION: "submission_done",
        AppEventType.BEFORE_AGGREGATION: "agg_start",
        AppEventType.AFTER_AGGREGATION: "agg_end",
    }

    def __init__(
        self,
        component_id: str = "profiler",
        log_file_name: str = "profile_summary.json",
        role: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        system_interval_sec: float = 1.0,
        system_include_children: bool = True,
    ):
        super().__init__()
        self.id = component_id
        self.log_file_name = log_file_name
        self.extra = extra or {}
        self._role = role
        self._system = SystemSampler(interval_sec=system_interval_sec, include_children=system_include_children)
        self._job_active = False

        # Per-workflow, per-round metrics
        self._rounds: Dict[str, Dict[int, RoundMetrics]] = defaultdict(lambda: defaultdict(RoundMetrics))
        # Timing stacks for server
        self._stacks: Dict[str, Dict[int, Dict[str, deque]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(deque))
        )
        # Payload snapshots at round start
        self._snap: Dict[Tuple[str, int], Dict[str, int]] = {}

        # Client: downstream timer
        self._down_pending: deque = deque()
        # Client: latched (workflow, round) from task data
        self._cached_meta: Optional[Tuple[str, int]] = None
        # Client: compute start time
        self._compute_start_time: Optional[float] = None
        # Client: upstream timer (start_time, workflow, round)
        self._upstream_pending: deque = deque()
        # Client fallback: per-workflow task ordinal when round not in task data
        self._workflow_task_ordinal: Dict[str, int] = defaultdict(int)
        # Stack for StatAnalyticsEventType phase timings: (workflow, round, phase_key, t0)
        self._stat_phase_stack: List[Tuple[str, int, str, float]] = []

        # Causal event trace: timestamped per-event records + local per-party sequence number
        self._trace: List[Dict[str, Any]] = []
        self._trace_seq: int = 0
        self._trace_cap: int = 200_000
        self._trace_task_id: Optional[str] = None
        self._trace_lock = threading.Lock()

    def _resolve_role(self, fl_ctx: FLContext) -> str:
        if self._role:
            return self._role
        site = fl_ctx.get_prop(FLContextKey.SITE_NAME) or fl_ctx.get_identity_name() or ""
        return "server" if site in ("server", "simulator_server") else "client"

    def _site(self, fl_ctx: FLContext) -> str:
        return fl_ctx.get_prop(FLContextKey.SITE_NAME) or fl_ctx.get_identity_name() or "unknown"

    def _job_id(self, fl_ctx: FLContext) -> str:
        try:
            return str(fl_ctx.get_job_id())
        except Exception:
            return fl_ctx.get_prop("job_id", "unknown")

    def _workspace_root(self, fl_ctx: FLContext) -> str:
        return fl_ctx.get_prop(FLContextKey.WORKSPACE_ROOT) or fl_ctx.get_prop(FLContextKey.APP_ROOT) or "."

    def _record_client_round(self, workflow: str, round_idx: int, key: str, delta: float) -> None:
        """Accumulate a client metric for a workflow/round."""
        m = self._rounds[workflow][round_idx]
        if key == "client_compute_time_sec":
            m.client_compute_time_sec += delta
        elif key == "downstream_rtt_sec":
            m.downstream_rtt_sec += delta
        elif key == "upstream_rtt_sec":
            m.upstream_rtt_sec += delta

    def _record_server_round(self, workflow: str, round_idx: int, key: str, delta: float) -> None:
        """Accumulate a server metric for a workflow/round."""
        m = self._rounds[workflow][round_idx]
        if key == "server_dispatch_time_sec":
            m.server_dispatch_time_sec += delta
        elif key == "server_accept_time_sec":
            m.server_accept_time_sec += delta
        elif key == "server_aggregation_time_sec":
            m.server_aggregation_time_sec += delta

    def _handle_stat_analytics_phase_event(
        self, event_type: str, fl_ctx: FLContext, workflow: str, round_idx: int
    ) -> None:
        parsed = parse_stat_analytics_phase_event(event_type)
        if parsed is None:
            return
        phase_key, is_end = parsed
        if not is_end:
            self._stat_phase_stack.append((workflow, round_idx, phase_key, _now_mono()))
            return
        if not self._stat_phase_stack:
            self.log_warning(fl_ctx, f"[Profiler] phase END without START: {phase_key}")
            return
        wf, rnd, pk, t0 = self._stat_phase_stack.pop()
        if pk != phase_key:
            self.log_warning(
                fl_ctx,
                f"[Profiler] phase END mismatch: got {phase_key}, closing {pk}",
            )
            return
        dur = max(0.0, _now_mono() - t0)
        m = self._rounds[wf][rnd]
        m.phase_breakdown_sec[pk] = m.phase_breakdown_sec.get(pk, 0.0) + dur

    def handle_event(self, event_type: str, fl_ctx: FLContext) -> None:
        role = self._resolve_role(fl_ctx)
        workflow = _extract_workflow(fl_ctx)
        round_idx = _extract_round(fl_ctx)

        kind = self._EVENT_KIND.get(event_type)
        if kind is not None:
            try:
                self._record_trace(kind, event_type, fl_ctx, role, workflow, round_idx)
            except Exception:
                pass

        if parse_stat_analytics_phase_event(event_type) is not None:
            # Client: during execute(), CURRENT_ROUND is often unset; workflow may come from task
            # headers but round still -1. Latch (workflow, round) from BEFORE_TASK_EXECUTION.
            if role == "client" and self._cached_meta is not None:
                wf_lm, rnd_lm = self._cached_meta
                if workflow == "default":
                    workflow, round_idx = wf_lm, rnd_lm
                elif round_idx < 0:
                    round_idx = rnd_lm
            self._handle_stat_analytics_phase_event(event_type, fl_ctx, workflow, round_idx)

        # Job lifecycle
        if event_type == EventType.START_RUN:
            # Baseline the OpenFHE counters so this run reports its own library time,
            # not whatever the process accumulated for earlier jobs.
            self._fhe_base = fhe_timing.snapshot()
            self._fhe_base_groups = fhe_timing.groups_snapshot()
            if self._role is None:
                raise ValueError("Profiler role must be set (server or client)")
            if not self._job_active:
                try:
                    self._system.start()
                    self._job_active = True
                except Exception:
                    pass

        elif event_type == EventType.END_RUN:
            if self._job_active:
                try:
                    self._system.stop()
                    self._job_active = False
                except Exception:
                    pass

        elif event_type == EventType.START_WORKFLOW:
            if fl_ctx.get_prop(ReservedKey.WORKFLOW) == PROFILE_CONSOLIDATE_WORKFLOW_ID:
                # Server only: clients never get START_WORKFLOW; they use PROFILE_SNAPSHOT_EVENT.
                self._dump(fl_ctx)

        elif event_type == PROFILE_SNAPSHOT_EVENT:
            # Client: flush before task_profile_consolidate round 0 reads profile_summary.json.
            self._dump(fl_ctx)

        elif event_type == AppEventType.ROUND_STARTED:
            self._snap[(workflow, round_idx)] = {
                "in0": int(fl_ctx.get_prop(IN_KEY, 0)),
                "out0": int(fl_ctx.get_prop(OUT_KEY, 0)),
            }

        # Client metrics
        if role == "client":
            if event_type == EventType.BEFORE_PULL_TASK:
                self._down_pending.append(_now_mono())

            elif event_type == EventType.BEFORE_TASK_EXECUTION:
                # Always fires; task data is available here. Latch workflow/round.
                task_data = fl_ctx.get_prop(ReservedKey.TASK_DATA, None)
                rnd = _extract_round_from_task_data(task_data)
                wf = _extract_workflow_from_task_data(task_data) or workflow
                if wf != "default":
                    if rnd is not None:
                        eff_rnd = rnd
                    else:
                        eff_rnd = self._workflow_task_ordinal[wf]
                        self._workflow_task_ordinal[wf] += 1
                    self._cached_meta = (wf, eff_rnd)

                if self._down_pending:
                    t0 = self._down_pending.pop()
                    eff_wf, eff_rnd = self._cached_meta or (workflow, round_idx)
                    self._record_client_round(eff_wf, eff_rnd, "downstream_rtt_sec", _now_mono() - t0)

                self._compute_start_time = _now_mono()

            elif event_type == EventType.AFTER_TASK_EXECUTION:
                if self._compute_start_time is not None:
                    duration = _now_mono() - self._compute_start_time
                    self._compute_start_time = None
                    eff_wf, eff_rnd = self._cached_meta or (workflow, round_idx)
                    self._record_client_round(eff_wf, eff_rnd, "client_compute_time_sec", duration)
                    self._upstream_pending.append((_now_mono(), eff_wf, eff_rnd))
                    self._cached_meta = None

            elif event_type == EventType.BEFORE_SEND_TASK_RESULT:
                # Upstream timer starts at end of compute; no action here
                pass

            elif event_type == EventType.AFTER_SEND_TASK_RESULT:
                if self._upstream_pending:
                    t0, wf, rnd = self._upstream_pending.pop()
                    self._record_client_round(wf, rnd, "upstream_rtt_sec", _now_mono() - t0)

        # Server metrics
        if role == "server":
            if event_type == EventType.BEFORE_PROCESS_TASK_REQUEST:
                self._stacks[workflow][round_idx]["dispatch_t0"].append(_now_mono())
            elif event_type == EventType.AFTER_PROCESS_TASK_REQUEST:
                if self._stacks[workflow][round_idx]["dispatch_t0"]:
                    t0 = self._stacks[workflow][round_idx]["dispatch_t0"].pop()
                    self._record_server_round(
                        workflow, round_idx, "server_dispatch_time_sec", _now_mono() - t0
                    )
            elif event_type == EventType.TASK_RESULT_RECEIVED:
                self._stacks[workflow][round_idx]["accept_t0"].append(_now_mono())
            elif event_type == EventType.AFTER_PROCESS_SUBMISSION:
                if self._stacks[workflow][round_idx]["accept_t0"]:
                    t0 = self._stacks[workflow][round_idx]["accept_t0"].pop()
                    self._record_server_round(
                        workflow, round_idx, "server_accept_time_sec", _now_mono() - t0
                    )
            elif event_type == AppEventType.BEFORE_AGGREGATION:
                self._stacks[workflow][round_idx]["agg_t0"].append(_now_mono())
            elif event_type == AppEventType.AFTER_AGGREGATION:
                if self._stacks[workflow][round_idx]["agg_t0"]:
                    t0 = self._stacks[workflow][round_idx]["agg_t0"].pop()
                    self._record_server_round(
                        workflow, round_idx, "server_aggregation_time_sec", _now_mono() - t0
                    )

        # Round done: payload deltas
        if event_type == AppEventType.ROUND_DONE:
            snap = self._snap.pop((workflow, round_idx), None)
            if snap is not None:
                in_now = int(fl_ctx.get_prop(IN_KEY, 0))
                out_now = int(fl_ctx.get_prop(OUT_KEY, 0))
                m = self._rounds[workflow][round_idx]
                m.payload_in_bytes = max(0, in_now - snap.get("in0", 0))
                m.payload_out_bytes = max(0, out_now - snap.get("out0", 0))

        if event_type == EventType.ABOUT_TO_END_RUN:
            if self._job_active:
                try:
                    self._system.stop()
                except Exception:
                    pass
                self._job_active = False
            self._dump(fl_ctx)

    # -- Causal event trace helpers -------------------------------------------

    @staticmethod
    def _first_prop(fl_ctx: FLContext, keys: Tuple[str, ...]) -> Optional[Any]:
        for key in keys:
            if not key:
                continue
            try:
                value = fl_ctx.get_prop(key, None)
            except Exception:
                value = None
            if value:
                return value
        return None

    @staticmethod
    def _first_header(task_data: Any, keys: Tuple[str, ...]) -> Optional[Any]:
        if task_data is None:
            return None
        for key in keys:
            if not key:
                continue
            if hasattr(task_data, "get_header"):
                try:
                    value = task_data.get_header(key, None)
                except Exception:
                    value = None
                if value:
                    return value
            if isinstance(task_data, dict):
                headers = task_data.get("__headers__") or {}
                if headers.get(key):
                    return headers.get(key)
        return None

    def _extract_task_id(self, fl_ctx: FLContext, task_data: Any) -> Optional[str]:
        keys = (getattr(FLContextKey, "TASK_ID", None), "__task_id__", "task_id")
        value = self._first_prop(fl_ctx, keys) or self._first_header(task_data, keys)
        return str(value) if value else None

    def _extract_task_name(self, fl_ctx: FLContext, task_data: Any) -> Optional[str]:
        keys = (getattr(FLContextKey, "TASK_NAME", None), "__task_name__", "task_name")
        value = self._first_prop(fl_ctx, keys) or self._first_header(task_data, keys)
        return str(value) if value else None

    def _extract_peer(self, fl_ctx: FLContext) -> Optional[str]:
        keys = (getattr(ReservedKey, "CLIENT_NAME", None), "__client_name__", "client_name")
        value = self._first_prop(fl_ctx, keys)
        return str(value) if value else None

    def _record_trace(
        self,
        kind: str,
        event_type: str,
        fl_ctx: FLContext,
        role: str,
        workflow: str,
        round_idx: int,
    ) -> None:
        if len(self._trace) >= self._trace_cap:
            return
        try:
            task_data = fl_ctx.get_prop(ReservedKey.TASK_DATA, None)
        except Exception:
            task_data = None

        task_id = self._extract_task_id(fl_ctx, task_data)
        if role == "client":
            if kind == "task_recv" and task_id:
                self._trace_task_id = task_id
            elif kind in ("compute_end", "send_start", "send_end") and not task_id:
                task_id = self._trace_task_id

        # Reserved for a future on-wire correlation filter; None until one stamps it.
        corr_id = self._first_header(task_data, ("__duality_trace_corr__", "duality_trace_corr"))

        with self._trace_lock:
            self._trace_seq += 1
            seq = self._trace_seq
        record = {
            "seq": seq,
            "ts_wall": time.time(),
            "ts_mono": _now_mono(),
            "kind": kind,
            "event": str(event_type),
            "role": role,
            "site": self._site(fl_ctx),
            "workflow": workflow,
            "round": round_idx,
            "task_id": task_id,
            "task_name": self._extract_task_name(fl_ctx, task_data),
            "corr_id": str(corr_id) if corr_id else None,
            "peer": self._extract_peer(fl_ctx) if role == "server" else None,
        }
        if kind == "agg_end":
            try:
                stats = fl_ctx.get_prop("__duality_parallel_stats", None)
                if stats:
                    record["meta"] = {"parallel": stats}
                    fl_ctx.set_prop("__duality_parallel_stats", None, private=True, sticky=False)
            except Exception:
                pass
        with self._trace_lock:
            self._trace.append(record)

        if role == "client" and kind == "send_end":
            self._trace_task_id = None

    def record_async_span(self, site, workflow, label, t0_wall, t1_wall, t0_mono=None, t1_mono=None):
        """Record a background/async span as a paired bg_start/bg_end in the trace."""
        try:
            pairs = (("bg_start", t0_wall, t0_mono), ("bg_end", t1_wall, t1_mono))
            with self._trace_lock:
                for kind, tw, tm in pairs:
                    self._trace_seq += 1
                    self._trace.append({
                        "seq": self._trace_seq,
                        "ts_wall": float(tw),
                        "ts_mono": float(tm) if tm is not None else float(tw),
                        "kind": kind,
                        "event": "async",
                        "role": "client",
                        "site": str(site),
                        "workflow": workflow,
                        "round": -1,
                        "task_id": None,
                        "task_name": None,
                        "corr_id": None,
                        "peer": None,
                        "meta": {"async_label": str(label)},
                    })
        except Exception:
            pass

    def _dump_trace(self, out_dir: Path, fl_ctx: FLContext) -> None:
        payload = "".join(json.dumps(record, sort_keys=True) + "\n" for record in self._trace)
        try:
            trace_fn = out_dir / "trace.jsonl"
            trace_fn.write_text(payload, encoding="utf-8")
            self.log_info(fl_ctx, f"[Profiler] wrote {trace_fn} ({len(self._trace)} events)")
        except Exception:
            pass
        self._dump_trace_to_sink(payload, fl_ctx)

    def _dump_trace_to_sink(self, payload: str, fl_ctx: FLContext) -> None:
        sink = os.getenv("DUALITY_TRACE_SINK_DIR") or "/job-results"
        try:
            base = Path(sink)
            if not base.is_dir():
                return
            dest_dir = base / "traces" / str(self._job_id(fl_ctx)) / str(self._site(fl_ctx))
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "trace.jsonl").write_text(payload, encoding="utf-8")
            self.log_info(fl_ctx, f"[Profiler] wrote trace copy -> {dest_dir / 'trace.jsonl'}")
            self._chown_to_host(base / "traces" / str(self._job_id(fl_ctx)))
        except Exception:
            pass

    @staticmethod
    def _chown_to_host(path) -> None:
        """Hand ownership of written trace/summary files back to the host user.

        The FL containers run as root, so trace.jsonl / profile_summary.json land
        root-owned on the host's bind-mounted job-results tree, which the host then
        can't delete without sudo. When DUALITY_HOST_UID/GID are set (the standalone
        launcher passes the host's own ids), recursively chown `path` back to them.
        No-op unless running as root with those vars set.
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

    def _dump(self, fl_ctx: FLContext) -> None:
        job_id = self._job_id(fl_ctx)
        site = self._site(fl_ctx)
        role = self._resolve_role(fl_ctx)
        out_dir = Path("job-results") / str(job_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        result: Dict[str, Any] = {
            "job_id": job_id,
            "site": site,
            "role": role,
            "extra": dict(self.extra),
            # Time spent inside OpenFHE, measured at the library boundary rather than
            # inferred from the phase breakdown. Includes pool-worker time, which the
            # aggregating process merges in as each chunk completes.
            "openfhe": fhe_timing.summary_since(
                getattr(self, "_fhe_base", None),
                previous_groups=getattr(self, "_fhe_base_groups", None),
            ),
            "workflows": {},
        }

        for wf_name, rounds in self._rounds.items():
            out_rounds: Dict[str, Any] = {}
            for r, m in sorted(rounds.items()):
                d = m.to_dict()
                if d:
                    out_rounds[str(r)] = d
            if out_rounds:
                result["workflows"][wf_name] = out_rounds

        try:
            sysm = self._system.results()
            if sysm and (sysm.wall_time_sec > 0 or sysm.rss_max_kb > 0):
                result["system_metrics"] = sysm.to_dict()
        except Exception:
            pass

        if role == "server":
            comm = self._collect_client_rtts(fl_ctx)
            if comm:
                result["communication"] = {"clients": comm}

        fn = out_dir / self.log_file_name
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        self.log_info(fl_ctx, f"[Profiler] wrote {fn}")

        self._dump_trace(out_dir, fl_ctx)
        self._chown_to_host(out_dir)

    def _collect_client_rtts(self, fl_ctx: FLContext) -> Dict[str, Any]:
        ws = self._workspace_root(fl_ctx)
        if not ws or not os.path.isdir(ws):
            return {}
        out: Dict[str, Any] = {}
        for root, dirs, files in os.walk(ws):
            if os.path.basename(root) != "results":
                continue
            if self.log_file_name not in files:
                continue
            fn = os.path.join(root, self.log_file_name)
            try:
                with open(fn, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if data.get("role") != "client":
                continue
            client_site = data.get("site", "unknown_client")
            wf_map: Dict[str, Dict[str, Any]] = {}
            for pipe, rounds in (data.get("workflows") or {}).items():
                wf_rounds = {}
                for r, row in (rounds or {}).items():
                    d = {}
                    for k in ["downstream_rtt_sec", "upstream_rtt_sec", "client_compute_time_sec"]:
                        if k in row:
                            d[k] = row[k]
                    if d:
                        wf_rounds[str(r)] = d
                if wf_rounds:
                    wf_map[pipe] = wf_rounds
            if wf_map:
                out[client_site] = wf_map
        return out


# ---------------------------------------------------------------------------
# Profile-summary consolidation workflow (server-only SAG components)
# ---------------------------------------------------------------------------


class ProfileSummaryPersistor(ModelPersistor):
    """Minimal persistor so the consolidate SAG does not load the full HE global model."""

    def __init__(self):
        super().__init__()

    def load_model(self, fl_ctx: FLContext) -> ModelLearnable:
        # Non-empty weights so ScatterAndGather does not substitute fl_ctx GLOBAL_MODEL.
        return make_model_learnable({"_profile_consolidate_placeholder": 0.0}, {})

    def save_model(self, model: ModelLearnable, fl_ctx: FLContext) -> None:
        return None


def _load_server_profile_summary_for_consolidate(fl_ctx: FLContext) -> Optional[Dict[str, Any]]:
    jid = fl_ctx.get_job_id()
    if not jid:
        return None
    path = Path("job-results") / str(jid) / "profile_summary.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class ProfileSummaryAggregator(Aggregator):
    """Round 0: collect each client's profile JSON; round 1: send merged bundle to leader only."""

    def __init__(self, leader_client_name: str = "site1"):
        super().__init__()
        self.leader_client_name = leader_client_name
        self.accepted_data: Dict[str, Any] = {}

    def accept(self, shareable: Shareable, fl_ctx: FLContext) -> bool:
        contributor = shareable.get_peer_prop(key=ReservedKey.IDENTITY_NAME, default="?")
        rc = shareable.get_return_code()
        if rc and rc != ReturnCode.OK:
            self.log_warning(fl_ctx, f"[ProfileSummaryAggregator] skip {contributor} rc={rc}")
            return False
        try:
            dxo = from_shareable(shareable)
        except Exception:
            self.log_exception(fl_ctx, "[ProfileSummaryAggregator] invalid shareable")
            return False
        if dxo.data_kind != DataKind.WEIGHTS:
            self.log_error(fl_ctx, "[ProfileSummaryAggregator] expected WEIGHTS DXO")
            return False
        fl_ctx.set_prop(
            "__prof_payload_in_acc",
            fl_ctx.get_prop("__prof_payload_in_acc", 0) + len(shareable.to_bytes()),
            sticky=True,
        )
        self.accepted_data[contributor] = dxo.data if dxo.data else {}
        return True

    def aggregate(self, fl_ctx: FLContext) -> Shareable:
        r = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        if r == 0:
            by_site: Dict[str, Any] = dict(self.accepted_data)
            srv = _load_server_profile_summary_for_consolidate(fl_ctx)
            if srv is not None:
                site_key = srv.get("site") if isinstance(srv.get("site"), str) else None
                by_site[site_key or "server"] = srv
            payload = {"by_site": by_site}
            return HEAggregator.get_shareable_data(
                payload,
                fl_ctx,
                metadata={"round": 1},
                target_clients=[self.leader_client_name],
            )
        return HEAggregator.get_shareable_data({}, fl_ctx, metadata={"round": (r or 0) + 1})

    def reset(self, fl_ctx: Optional[FLContext] = None) -> None:
        self.accepted_data = {}
