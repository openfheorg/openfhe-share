"""On-wire correlation stamp for the causal trace (companion to the Profiler).

Registered in the server's ``task_data_filters`` so it runs on each *outbound*
task. It does two things, both best-effort:

1. Stamps a unique correlation id onto the task ``Shareable`` header
   (``__duality_trace_corr__``). The client Profiler already reads that header at
   task receipt (``corr_id`` in its trace records).
2. Appends a matching server-side ``dispatch_msg`` record -- carrying the same
   correlation id -- to ``trace_filter.jsonl`` beside the Profiler's
   ``trace.jsonl``.

Because the two ends share the correlation id, the taskflow emitter can pair
server dispatch -> client receive *exactly*, instead of by the
``(workflow, round)`` timing fallback the server's own dispatch events force
(``BEFORE_PROCESS_TASK_REQUEST`` carries no task id or peer, and fires on empty
polls too).

The filter is a pure pass-through: it only adds a header and writes a trace line.
It never inspects or mutates the DXO payload, and it swallows every error, so it
cannot affect the federated computation even if something in it fails.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from nvflare.apis.filter import Filter
from nvflare.apis.fl_constant import FLContextKey, ReservedKey
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable
from nvflare.app_common.app_constant import AppConstants

CORR_HEADER = "__duality_trace_corr__"
_TRACE_FILE_NAME = "trace_filter.jsonl"


class TraceCorrelationFilter(Filter):
    """Stamp a per-message correlation id and log the server-side dispatch."""

    _lock = threading.Lock()
    _seq = 0

    def process(self, shareable: Shareable, fl_ctx: FLContext) -> Shareable:
        try:
            self._stamp_and_record(shareable, fl_ctx)
        except Exception:
            # Never let a trace concern disturb the task data path.
            pass
        return shareable

    def _stamp_and_record(self, shareable: Shareable, fl_ctx: FLContext) -> None:
        corr = None
        try:
            corr = shareable.get_header(CORR_HEADER)
        except Exception:
            corr = None
        if not corr:
            corr = uuid.uuid4().hex
            shareable.set_header(CORR_HEADER, corr)

        site = fl_ctx.get_prop(FLContextKey.SITE_NAME) or fl_ctx.get_identity_name() or "simulator_server"
        try:
            job_id = str(fl_ctx.get_job_id())
        except Exception:
            job_id = str(fl_ctx.get_prop("job_id", "unknown"))
        workflow = fl_ctx.get_prop(FLContextKey.WORKFLOW, None) or "default"
        raw_round = fl_ctx.get_prop(AppConstants.CURRENT_ROUND, None)
        try:
            round_idx = int(raw_round) if raw_round is not None else -1
        except (TypeError, ValueError):
            round_idx = -1

        task_name_key = getattr(FLContextKey, "TASK_NAME", None)
        peer_key = getattr(ReservedKey, "CLIENT_NAME", None)
        record: dict[str, Any] = {
            "ts_wall": time.time(),
            "ts_mono": time.perf_counter(),
            "kind": "dispatch_msg",
            "event": "task_data_filter",
            "role": "server",
            "site": str(site),
            "workflow": workflow,
            "round": round_idx,
            "task_id": None,
            "task_name": fl_ctx.get_prop(task_name_key, None) if task_name_key else None,
            "corr_id": corr,
            "peer": fl_ctx.get_prop(peer_key, None) if peer_key else None,
        }

        out_dir = Path("job-results") / job_id
        with TraceCorrelationFilter._lock:
            TraceCorrelationFilter._seq += 1
            record["seq"] = TraceCorrelationFilter._seq
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                with open(out_dir / _TRACE_FILE_NAME, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
            except Exception:
                pass
