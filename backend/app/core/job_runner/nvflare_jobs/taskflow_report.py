"""Host-side taskflow / causal-trace report for a single deployment run.

Merges the per-party ``trace.jsonl`` streams the Profiler writes (the server, the
leader client, and any other client trace reachable on the host) into one causal
graph and renders, under an output directory:

  - ``taskflow.perfetto.json``   Chrome Trace Event format (open in
                                 https://ui.perfetto.dev or chrome://tracing)
  - ``taskflow.seq.mmd``         Mermaid sequenceDiagram of correlated messages
  - ``taskflow.lamport.dot``     Graphviz causal / space-time graph
  - ``taskflow.rounds.{txt,json}`` per-round straggler + RTT decomposition
  - ``taskflow.timeline.svg``    time-based swimlane (best-effort; needs matplotlib)
  - ``index.json`` / ``index.md``  counts, correlation split, causal depth

This is a *post-run, host-side* renderer. It does no work inside the FL
containers: the Profiler only appends events and dumps ``trace.jsonl`` at run
end, and all the graph/clock/render work happens here, after the fact.

The pure-graph core (``_causal_clocks`` / ``_build_case_graph`` and the emitters)
mirrors the sweep's ``tests/docker_simulator_runner/container_entrypoint.py``.
It is kept standalone on purpose so production result-retrieval never imports the
test harness. Any change to the causal-graph algorithm should be mirrored there.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_TRACE_FILE_NAME = "trace.jsonl"
_TRACE_FILTER_FILE_NAME = "trace_filter.jsonl"

# (role, open_kind, close_kind, label) span pairs, matched FIFO per lane.
_TRACE_SPANS = (
    ("client", "task_recv", "compute_end", "compute"),
    ("client", "compute_end", "send_end", "send"),
    ("client", "pull_start", "task_recv", "wait"),
    ("server", "dispatch_start", "dispatch_end", "dispatch"),
    ("server", "result_recv", "submission_done", "accept"),
    ("server", "agg_start", "agg_end", "aggregate"),
    ("server", "round_start", "round_done", "round"),
    ("client", "bg_start", "bg_end", "background"),
)


def _number(value: Any) -> Optional[float]:
    """Return a finite numeric value, or None when the field is absent."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return None


def _ts(record: Dict[str, Any]) -> Optional[float]:
    """Wall-clock timestamp, or None when the field is absent/non-numeric.

    Returns None (not 0.0) so span-duration callers can tell a legitimate 0.0
    relative time apart from "no timestamp" and never manufacture a ~1.7e9 s
    span. Ordering / coordinate contexts use _ts_or0 to coerce a missing stamp
    to 0.0 (the historical behaviour) instead.
    """
    return _number(record.get("ts_wall"))


def _ts_or0(record: Dict[str, Any]) -> float:
    """Timestamp coerced to 0.0 when missing, for ordering, comparison and
    coordinate math only -- never for span durations (see _ts)."""
    value = _ts(record)
    return value if value is not None else 0.0


def _seq(record: Dict[str, Any]) -> int:
    """Best-effort integer ``seq`` for stable ordering; 0 when absent or
    non-numeric. A malformed seq must not raise: the whole report is wrapped in
    a blanket handler that would otherwise silently drop it."""
    try:
        return int(record.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def _chown_to_host(path) -> None:
    """Hand ownership of a written output dir back to the host user.

    When this runs inside a root container (e.g. the standalone backend writing
    the report to a bind-mounted job-results tree), the artifacts are root-owned
    on the host, which then can't regenerate or delete them without sudo. When
    DUALITY_HOST_UID/GID are set, recursively chown `path` back to them. No-op
    unless running as root with those vars set.
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


def _causal_clocks(
    count: int,
    party_of: List[int],
    party_count: int,
    prog_edges: List[Tuple[int, int]],
    msg_edges: List[Tuple[int, int]],
    ts_of: List[float],
) -> Tuple[List[int], List[Dict[int, int]], bool]:
    """Assign Lamport scalar and vector clocks over the event DAG offline.

    Equivalent to online Lamport/vector clocks for a completed trace: the
    happens-before relation is program order per party plus every send->receive
    message edge, processed in topological order (Kahn). Correct without
    synchronized wall clocks (multi-host safe); wall time only breaks ties.
    """
    preds: List[List[int]] = [[] for _ in range(count)]
    indeg = [0] * count
    seen_edge: set = set()
    for a, b in list(prog_edges) + list(msg_edges):
        if a == b or (a, b) in seen_edge:
            continue
        seen_edge.add((a, b))
        preds[b].append(a)
        indeg[b] += 1

    import heapq

    ready: List[Tuple[float, int]] = []
    for node in range(count):
        if indeg[node] == 0:
            heapq.heappush(ready, (ts_of[node], node))
    succs: List[List[int]] = [[] for _ in range(count)]
    for a, b in seen_edge:
        succs[a].append(b)

    lamport = [0] * count
    vclock: List[Dict[int, int]] = [dict() for _ in range(count)]
    order: List[int] = []
    while ready:
        _, node = heapq.heappop(ready)
        order.append(node)
        best = 0
        merged: Dict[int, int] = {}
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


def _build_case_graph(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    recs = [r for r in records if isinstance(r, dict)]
    recs.sort(key=lambda r: (_ts_or0(r), _seq(r)))
    for index, record in enumerate(recs):
        record["_idx"] = index

    def lane_key(record: Dict[str, Any]) -> Tuple[str, str]:
        return (str(record.get("role") or "?"), str(record.get("site") or "?"))

    lanes: List[Tuple[str, str]] = []
    seen: set = set()
    for record in recs:
        key = lane_key(record)
        if key not in seen:
            seen.add(key)
            lanes.append(key)
    lanes.sort(key=lambda k: (0 if k[0] == "server" else 1, k[1]))
    lane_index = {key: index for index, key in enumerate(lanes)}

    open_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
    close_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for role, open_kind, close_kind, label in _TRACE_SPANS:
        open_map[(role, open_kind)] = (close_kind, label)
        close_map[(role, close_kind)] = (open_kind, label)

    open_queues: Dict[Tuple[Tuple[str, str], str], List[Dict[str, Any]]] = {}
    spans: List[Dict[str, Any]] = []
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
                        # structured extras the Profiler stamped on the close event
                        # (e.g. {"parallel": {"workers_used": ...}} on agg_end)
                        "meta": record.get("meta"),
                    }
                )

    def make_edge(src: Dict[str, Any], dst: Dict[str, Any], label: str, method: str) -> Dict[str, Any]:
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

    def for_peer(server_events: List[Dict[str, Any]], site: str) -> List[Dict[str, Any]]:
        # Prefer server events tagged with this client; fall back to all when the
        # peer/client name was not available on the server side.
        matched = [e for e in server_events if e.get("peer") and str(e.get("peer")) == site]
        return matched or server_events

    # A stable correlation key: the profiler's self-stamped corr_id if present,
    # else the NVFlare task id. Either lets dispatch<->receive and send<->receive
    # pair reliably across parties.
    def corr_key(record: Dict[str, Any]) -> Optional[str]:
        value = record.get("corr_id") or record.get("task_id")
        return str(value) if value else None

    edges: List[Dict[str, Any]] = []
    edged_recv: set = set()
    edged_send: set = set()
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for record in recs:
        key = corr_key(record)
        if key:
            by_key.setdefault(key, []).append(record)

    for _key, group in by_key.items():
        recvs = [r for r in group if r.get("role") == "client" and r.get("kind") == "task_recv"]
        dispatches = [
            r for r in group
            if r.get("role") == "server" and r.get("kind") in ("dispatch_msg", "dispatch_start", "dispatch_end")
        ]
        sends = [r for r in group if r.get("role") == "client" and r.get("kind") == "send_end"]
        srv_recvs = [
            r for r in group
            if r.get("role") == "server" and r.get("kind") in ("result_recv", "submission_done")
        ]
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

    # Fallback correlation for events without a usable correlation key: pair by
    # workflow (+ the server's peer/client tag when known), with the round as a
    # *soft* preference. The client's first task of a workflow arrives before it
    # can read the round, so its task_recv is tagged round -1; requiring an exact
    # round match would drop exactly those initial server->client sends. So we
    # match within the workflow and prefer the same round only when the client
    # side actually has a real round, then disambiguate by time.
    all_dispatch = [
        r for r in recs if r.get("role") == "server" and r.get("kind") in ("dispatch_start", "dispatch_end")
    ]
    all_srv_recv = [
        r for r in recs if r.get("role") == "server" and r.get("kind") in ("result_recv", "submission_done")
    ]

    def _same_wf_pool(candidates: List[Dict[str, Any]], event: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    unique_edges: List[Dict[str, Any]] = []
    seen_edges: set = set()
    for edge in edges:
        signature = (edge["src_idx"], edge["dst_idx"], edge["label"])
        if signature not in seen_edges:
            seen_edges.add(signature)
            unique_edges.append(edge)
    edges = unique_edges

    # Program-order edges within each lane (by wall time then seq).
    prog_edges: List[Tuple[int, int]] = []
    per_lane: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for record in recs:
        per_lane.setdefault(lane_key(record), []).append(record)
    for lane_records in per_lane.values():
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


def _perfetto_from_graph(case_label: str, graph: Dict[str, Any]) -> Dict[str, Any]:
    lane_index = graph["lane_index"]
    t0 = graph["t0"]
    events: List[Dict[str, Any]] = [
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


def _mermaid_from_graph(case_label: str, graph: Dict[str, Any], max_edges: int = 400) -> str:
    lines = ["sequenceDiagram", f"    %% {case_label}"]

    def participant_id(site: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", site) or "p"

    participants: List[str] = []
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


def _dot_from_graph(case_label: str, graph: Dict[str, Any], max_nodes: int = 800) -> str:
    """Render the causal DAG as Graphviz DOT: the Lamport / space-time graph."""
    recs = graph.get("recs") or []
    lamport = graph.get("lamport") or []
    lanes = graph["lanes"]

    def esc(text: Any) -> str:
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    included = set(range(len(recs)))
    truncated = 0
    if len(recs) > max_nodes:
        keep = sorted(range(len(recs)), key=lambda n: (lamport[n] if lamport else n, n))[:max_nodes]
        included = set(keep)
        truncated = len(recs) - len(included)

    lines = [
        'digraph "taskflow" {',
        f'  label="{esc(case_label)}  (Lamport depth {graph.get("max_lamport", 0)}'
        f'{"" if graph.get("acyclic", True) else "; CYCLE - wall-clock fallback"})";',
        # Columns come from the per-party node `group` (not clusters, which
        # trigger Graphviz "trouble in init_rank" on inter-column edges).
        "  labelloc=t; fontsize=12; rankdir=TB; splines=polyline;",
        '  node [shape=box, style=rounded, fontsize=9, fontname="monospace"];',
        '  edge [fontsize=8];',
    ]

    lane_records: Dict[Tuple[str, str], List[int]] = {lane: [] for lane in lanes}
    for record in recs:
        idx = record["_idx"]
        if idx not in included:
            continue
        lane = (str(record.get("role") or "?"), str(record.get("site") or "?"))
        lane_records.setdefault(lane, []).append(idx)

    def group_id(lane: Tuple[str, str]) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", f"{lane[0]}_{lane[1]}") or "g"

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


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _round_sort_key(round_value: Any) -> Tuple[int, Any]:
    try:
        return (0, int(round_value))
    except (TypeError, ValueError):
        return (1, str(round_value))


def _round_analysis(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-(workflow, round) straggler and RTT decomposition, from the trace.

    Decomposes each client's task cycle into idle-wait, fetch, compute and send,
    and reports the straggler gap: how long the server waited between the first
    and last client's result that round (the critical-path signal of a
    synchronous federated round). Client-side rounds are unreliable (the first
    often reads -1); the server's (workflow, round) is authoritative, joined by
    task id.
    """
    site_by_task: Dict[str, str] = {}
    server_by_task: Dict[str, Dict[str, Any]] = {}
    client_events: Dict[str, List[Dict[str, Any]]] = {}
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

    rounds: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for site, events in client_events.items():
        events.sort(key=lambda r: (_seq(r), _ts_or0(r)))
        pending_pulls: List[float] = []
        cycle: Optional[Dict[str, Any]] = None
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

    # Server-derived straggler (deployment path): when only the server + leader
    # traces are on the host we cannot attribute submissions to individual sites
    # (peer is unset), but the server still timestamps every client's result. The
    # spread of submission arrivals within a (workflow, round) is the straggler
    # wait on that round's critical path -- computable from the server trace alone.
    server_arrivals: Dict[Tuple[str, str], List[float]] = {}
    arrivals_by_task: Dict[Tuple[str, str], Dict[str, float]] = {}
    for record in recs:
        if record.get("role") != "server" or record.get("kind") not in ("submission_done", "result_recv"):
            continue
        wf = record.get("workflow")
        rnd = record.get("round")
        if not wf or wf == "default" or rnd in (None, -1):
            continue
        key = (str(wf), str(rnd))
        task_id = record.get("task_id")
        t = _ts_or0(record)
        if task_id:
            # De-dup exactly like server_by_task: at most one arrival per task id
            # per round (keep the earliest), so a submission that emits both
            # submission_done and result_recv is not counted twice.
            per_task = arrivals_by_task.setdefault(key, {})
            tid = str(task_id)
            if tid not in per_task or t < per_task[tid]:
                per_task[tid] = t
        else:
            # Records without a task id each count once (unchanged behavior).
            server_arrivals.setdefault(key, []).append(t)
    for key, per_task in arrivals_by_task.items():
        server_arrivals.setdefault(key, []).extend(per_task.values())

    analysis: List[Dict[str, Any]] = []
    keys = set(rounds) | set(server_arrivals)
    for key in sorted(keys, key=lambda k: (k[0], _round_sort_key(k[1]))):
        acc = rounds.get(key)
        compute = acc["compute"] if acc else {}
        client_arrivals = acc["arrivals"] if acc else {}
        srv_ts = sorted(server_arrivals.get(key, []))
        slowest = max(compute, key=compute.get) if compute else None
        row: Dict[str, Any] = {
            "workflow": key[0],
            "round": key[1],
            # Prefer the server's count of received results; it sees every site,
            # while the client-cycle count only covers sites we have traces for.
            "contributions": max(len(srv_ts), len(acc["clients"]) if acc else 0),
            "clients": sorted(acc["clients"]) if acc else [],
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
            vals = list(acc[name].values()) if acc else []
            row[f"{name}_sec"] = {"mean": round(_avg(vals), 4), "max": round(max(vals), 4) if vals else 0.0}
        # Submission spread from the server (all sites, unattributed).
        row["submission_spread_sec"] = round(srv_ts[-1] - srv_ts[0], 4) if len(srv_ts) >= 2 else 0.0
        if len(client_arrivals) >= 2:
            # Per-site attribution available (multiple client traces): name the straggler.
            gap = max(client_arrivals.values()) - min(client_arrivals.values())
            row["straggler_gap_sec"] = round(max(0.0, gap), 4)
            row["straggler_client"] = max(client_arrivals, key=client_arrivals.get)
            row["straggler_source"] = "client_arrivals"
        elif len(srv_ts) >= 2:
            row["straggler_gap_sec"] = row["submission_spread_sec"]
            row["straggler_client"] = None
            row["straggler_source"] = "server_submission_spread"
        else:
            row["straggler_gap_sec"] = 0.0
            row["straggler_client"] = None
            row["straggler_source"] = None
        analysis.append(row)
    return analysis


def _rounds_txt(case_label: str, analysis: List[Dict[str, Any]]) -> str:
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

    def sec(row: Dict[str, Any], field: str, sub: str) -> str:
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


# --------------------------------------------------------------------------- #
# Single-run collection + orchestration
# --------------------------------------------------------------------------- #
def collect_trace_files(search_roots: Iterable[Path], job_id: str) -> List[Path]:
    """Find trace files for one job without walking unrelated job history.

    ``search_roots`` are job-results roots.  The Profiler writes/copies traces for
    a completed job into only two job-scoped locations beneath that root:

      - ``<job-results>/<job_id>/`` (leader/server trace + trace_filter.jsonl)
      - ``<job-results>/traces/<job_id>/`` (per-party trace copies)

    ...but only from the perspective of the container that wrote them.  A client
    whose container mounts its OWN per-site directory as ``/job-results`` drops its
    sink copy at ``<job-results>/<site>/traces/<job_id>/<site>/`` instead, so on the
    host those parties sit one level deeper than the shared root.  Missing them does
    not fail the report -- it silently renders a diagram with fewer lanes than the
    job had parties -- so the per-site directories are searched too.

    Search recursively *inside those job-scoped directories only*.  This keeps all
    traces required by the taskflow report while avoiding an ``rglob`` across
    every historical job and the broader NVFlare workspace.
    """
    found: "dict[str, Path]" = {}
    job_id = str(job_id)

    for root in search_roots:
        try:
            root = Path(root)
        except TypeError:
            continue
        if not root.is_dir():
            continue

        scoped_roots: List[Path]
        if root.name == job_id:
            # Also support callers that already provide the job directory itself.
            scoped_roots = [root]
        else:
            scoped_roots = [root / job_id, root / "traces" / job_id]
            # Per-site result directories: one extra level, still job-scoped, so
            # this stays bounded and never walks unrelated job history.
            try:
                for child in sorted(root.iterdir()):
                    if not child.is_dir() or child.name in (job_id, "traces"):
                        continue
                    scoped_roots.append(child / job_id)
                    scoped_roots.append(child / "traces" / job_id)
            except OSError:
                pass

        for scoped_root in scoped_roots:
            if not scoped_root.is_dir():
                continue
            for file_name in (_TRACE_FILE_NAME, _TRACE_FILTER_FILE_NAME):
                for path in scoped_root.rglob(file_name):
                    try:
                        key = str(path.resolve())
                    except OSError:
                        key = str(path)
                    found.setdefault(key, path)

    return sorted(found.values(), key=lambda p: str(p))


def _read_records(trace_files: Sequence[Path]) -> List[Dict[str, Any]]:
    """Read and merge trace records from several files into one list.

    Deduplicates identical records across files by (role, site, seq, kind,
    ts_wall) so a party's stream that happens to appear in two collected
    locations is not counted twice.
    """
    records: List[Dict[str, Any]] = []
    seen: set = set()
    for path in trace_files:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            sig = (
                record.get("role"),
                record.get("site"),
                record.get("seq"),
                record.get("kind"),
                record.get("ts_wall"),
            )
            if sig in seen:
                continue
            seen.add(sig)
            records.append(record)
    return records


def render_run_report(
    trace_files: Sequence[Path],
    out_dir: Path,
    case_label: Optional[str] = None,
    title: Optional[str] = None,
    prefix: str = "taskflow",
    timeline: bool = True,
) -> Dict[str, Any]:
    """Merge one run's traces, render all taskflow artifacts, return a summary.

    Never raises on empty/partial input: with no records it writes an ``index``
    noting that, and returns zero counts. The timeline is best-effort (skipped,
    with a note, when matplotlib is unavailable).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    label = case_label or "run"
    records = _read_records(trace_files)

    summary: Dict[str, Any] = {
        "case_label": label,
        "trace_files": [str(p) for p in trace_files],
        "events": len(records),
        "artifacts": [],
    }

    if not records:
        summary.update({"lanes": 0, "spans": 0, "edges": 0, "rounds": 0, "note": "no trace records found"})
        (out_dir / "index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (out_dir / "index.md").write_text(
            f"# Taskflow trace\n\nNo `trace.jsonl` events were found for **{label}**. "
            "The Profiler writes one per party at run end; none were reachable on the host.\n",
            encoding="utf-8",
        )
        return summary

    graph = _build_case_graph(records)
    rounds = _round_analysis(graph["recs"])

    def _write(name: str, text: str) -> None:
        (out_dir / name).write_text(text, encoding="utf-8")
        summary["artifacts"].append(name)

    _write(f"{prefix}.perfetto.json", json.dumps(_perfetto_from_graph(label, graph)))
    _write(f"{prefix}.seq.mmd", _mermaid_from_graph(label, graph))
    _write(f"{prefix}.lamport.dot", _dot_from_graph(label, graph))
    _write(f"{prefix}.rounds.json", json.dumps(rounds, indent=2))
    _write(f"{prefix}.rounds.txt", _rounds_txt(label, rounds))

    # Worker badges for parallel blocks, straight from the trace: the Profiler
    # stamps the HE pool's stats onto each aggregation's agg_end event, which
    # _build_case_graph carries onto the span as meta.parallel. No side channel.
    block_labels: Dict[int, str] = {}
    for s in graph["spans"]:
        par = (s.get("meta") or {}).get("parallel") if isinstance(s.get("meta"), dict) else None
        if par and par.get("workers_used"):
            used, cap = par.get("workers_used"), par.get("workers_cap")
            block_labels[s["open_idx"]] = f"{used}w" if used == cap else f"{used}w/cap{cap}"

    timeline_note = None
    if timeline:
        ok, timeline_note = _write_timeline_svg(
            graph, out_dir / f"{prefix}.timeline.svg", title or label, block_labels=block_labels or None
        )
        if ok:
            summary["artifacts"].append(f"{prefix}.timeline.svg")

    straggler_total = round(sum(r.get("straggler_gap_sec") or 0.0 for r in rounds), 3)
    straggler_max = round(max((r.get("straggler_gap_sec") or 0.0 for r in rounds), default=0.0), 3)
    summary.update(
        {
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
            "parties": [f"{r}:{s}" for r, s in graph["lanes"]],
        }
    )
    if timeline_note:
        summary["timeline_note"] = timeline_note

    (out_dir / "index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "index.md").write_text(_index_md(label, summary, timeline_note, prefix), encoding="utf-8")
    return summary


def _index_md(label: str, summary: Dict[str, Any], timeline_note: Optional[str], prefix: str = "taskflow") -> str:
    cyc = "" if summary.get("acyclic", True) else " ⚠cycle"
    lines = [
        f"# Taskflow trace — {label}",
        "",
        "Causal event trace merged from every party's `trace.jsonl` reachable on the host "
        "(server + leader client, plus any other client trace present).",
        "",
        f"- **parties:** {', '.join(summary.get('parties') or []) or '—'}",
        f"- **events:** {summary.get('events', 0)}  ·  **spans:** {summary.get('spans', 0)}  "
        f"·  **messages:** {summary.get('edges', 0)} "
        f"(id {summary.get('edges_by_id', 0)} / fallback {summary.get('edges_fallback', 0)})",
        f"- **causal depth (Lamport):** {summary.get('lamport_depth', 0)}{cyc}",
        f"- **rounds:** {summary.get('rounds', 0)}  ·  **straggler wait total/max:** "
        f"{summary.get('straggler_wait_total_sec', 0)}/{summary.get('straggler_wait_max_sec', 0)} s",
        "",
        "## Artifacts",
        f"- `{prefix}.perfetto.json` — open in https://ui.perfetto.dev (or chrome://tracing).",
        f"- `{prefix}.seq.mmd` — render with any Mermaid viewer.",
        f"- `{prefix}.lamport.dot` — causal / Lamport graph; render with "
        f"`dot -Tsvg {prefix}.lamport.dot -o {prefix}.svg`.",
        f"- `{prefix}.rounds.txt` / `.rounds.json` — per-round straggler + RTT decomposition.",
    ]
    if f"{prefix}.timeline.svg" in (summary.get("artifacts") or []):
        lines.append(f"- `{prefix}.timeline.svg` — time-based swimlane (parties = columns, y = elapsed time).")
    elif timeline_note:
        lines.append(f"- _timeline.svg not rendered: {timeline_note}_")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Time-based swimlane (best-effort; requires matplotlib)
# --------------------------------------------------------------------------- #
# Palette aligned to the standalone dashboard: brand indigo (#3F5FFF) as the
# primary, the dashboard danger red for results, dashboard slate/gray neutrals,
# and violet/amber accents (harmonizing with the indigo) so span types stay
# distinguishable.
_TL_TASK = "#3f5fff"                                       # brand indigo (task arrows)
_TL_RESULT = "#f53d3d"                                     # dashboard danger red (result arrows)
_TL_COMPUTE_F, _TL_COMPUTE_E = "#e0e6ff", "#3f5fff"        # compute: light indigo / brand indigo
_TL_AGG_F, _TL_AGG_E = "#e7ddfb", "#7c3aed"               # server aggregate: light violet / violet
_TL_SEND_F, _TL_SEND_E = "#fdecc8", "#d97706"            # send/network: light amber / amber
_TL_BG_F, _TL_BG_E = "#f3f4f6", "#9ca3af"                 # background/off-critical-path (hatched, gray)
_TL_LIFELINE = "#cbd5e1"                                   # dashboard slate-300
_TL_INK = "#111827"                                        # dashboard ink (gray-900)
_TL_MUTED = "#6b7280"                                      # dashboard muted (gray-500)


def _write_timeline_svg(
    graph: Dict[str, Any],
    out_path: Path,
    title: str,
    block_labels: Optional[Dict[int, str]] = None,
) -> Tuple[bool, Optional[str]]:
    """Render the time-based swimlane to SVG. Returns (ok, note-on-skip).

    ``block_labels`` optionally maps a span's ``open_idx`` to a short text badge
    (e.g. worker count) drawn next to that duration bar. Worker/parallelism data
    is not in the trace, so callers supply it out-of-band (parsed from the server
    log); when omitted, bars are unlabelled.
    """
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

        # workflow bounding boxes: each workflow is a sequential phase; box its
        # events over their time span. Client compute/send events carry "default"
        # as workflow, so inherit from that party's most recent task_recv.
        by_lane: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}
        for r in recs:
            by_lane.setdefault((r.get("role"), r.get("site")), []).append(r)
        ranges: Dict[str, List[float]] = {}
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
        def lane_for(site: Any, role: str) -> Optional[Tuple[str, str]]:
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


# --------------------------------------------------------------------------- #
# Deployment entry point (standalone, LOCAL mode)
# --------------------------------------------------------------------------- #
def generate_report_for_job(
    nvflare_job_id: str,
    job_save_location: Optional[str] = None,
    workspace_root: Optional[str] = None,
    out_dir: Optional[Path] = None,
    case_label: Optional[str] = None,
    title: Optional[str] = None,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Build the taskflow report for one finished job from host-reachable traces.

    Collects every ``trace.jsonl`` the Profiler wrote/copied for
    ``nvflare_job_id`` from that job's directories under ``job_save_location``
    (default ``$DUALITY_NVFLARE_JOB_SAVE_LOCATION``), merges them, and writes the
    artifacts to ``<job_save_location>/<job_id>/taskflow/`` (override with
    ``out_dir``). ``workspace_root`` is retained for call compatibility but is no
    longer scanned because server/client traces are exported to job-results.

    Best-effort and idempotent: returns ``None`` (never raises) when no trace is
    found or writing fails, and skips regeneration when a report already exists
    unless ``force`` is set. Intended to run host-side after a run completes, so
    it adds nothing to the federated run itself.
    """
    try:
        # nvflare_job_id is used to build write paths below; reject anything that
        # isn't an id-safe token (defense in depth against path traversal).
        if not nvflare_job_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(nvflare_job_id)):
            return None
        job_save_location = job_save_location or os.getenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION")
        # Taskflow traces are exported into the same job-results tree used by
        # the Results API.  Do not walk the broader NVFlare workspace: the job id
        # already scopes us to the exact result/trace directories we need.
        roots: List[Path] = []
        if job_save_location:
            path = Path(job_save_location)
            if path.is_dir():
                roots.append(path)
        if not roots:
            return None

        if out_dir is None:
            if not job_save_location:
                return None
            out_dir = Path(job_save_location) / str(nvflare_job_id) / "taskflow"
        out_dir = Path(out_dir)

        no_trace_marker = out_dir / ".no-trace"
        if not force and ((out_dir / "index.json").exists() or no_trace_marker.exists()):
            return None  # already generated / known trace-less for this job

        files = collect_trace_files(roots, str(nvflare_job_id))
        if not files:
            # Record a marker so we don't re-scan the whole workspace tree on
            # every subsequent results fetch for a job that has no traces.
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                no_trace_marker.write_text("no trace files found\n", encoding="utf-8")
                _chown_to_host(out_dir)
            except OSError:
                pass
            return None

        result = render_run_report(
            files,
            out_dir,
            case_label=case_label or str(nvflare_job_id),
            title=title or case_label or str(nvflare_job_id),
        )
        _chown_to_host(out_dir)
        return result
    except Exception:
        # A reporting failure must never affect results delivery.
        return None
