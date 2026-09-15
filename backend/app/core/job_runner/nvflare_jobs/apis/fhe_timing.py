"""Measure time spent inside OpenFHE itself, per operation, per process.

The ``Profiler`` times application phases -- preprocess, aggregate, encrypt -- and
each of those mixes library work with the Python around it. That is enough to
*bound* OpenFHE's share of a run but not to state it: the last analysis could only
put the encrypted chain somewhere between 36% and 69%. This module closes the gap by
timing the library calls themselves, so an FHE upgrade can be measured against a real
"before" instead of an inferred one.

Three ways in, chosen per call site so that no site has to be rewritten by hand:

* ``wrap_module_callables(globals(), names)`` rebinds free functions (``Serialize``,
  the ``Deserialize*`` family) inside a module's namespace. Every existing call site
  is covered without edits.
* ``TimedProxy(cc)`` wraps a CryptoContext so every method call through it is timed.
  Only ever hand a proxy to code you control -- a pybind11 function that expects a
  real CryptoContext will reject it. The wrappers above unwrap proxies defensively,
  but a module whose free functions were never wrapped will not.
* ``timed(label)`` / ``call(label, fn, ...)`` for one-off sites.

Cost is two ``perf_counter`` reads and a dict update per call: tens of nanoseconds
against operations that take milliseconds. Totals are per-process, so a pool worker
accumulates its own; ``delta_since`` and ``merge`` move them back to the parent.

Every entry point swallows its own errors. This is measurement, and it must never be
able to fail a federated run.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from time import perf_counter

try:
    # CLOCK_MONOTONIC is system-wide on Linux, so a worker's timestamps are
    # comparable with the parent's. perf_counter's reference point is documented as
    # undefined, which is fine for durations but not for unioning intervals across
    # processes.
    _CLOCK = time.CLOCK_MONOTONIC

    def _now() -> float:
        return time.clock_gettime(_CLOCK)
except Exception:  # pragma: no cover - non-Linux fallback
    _now = perf_counter

# label -> [calls, seconds]. Process-global on purpose: a pool worker keeps its own.
_TOTALS: dict[str, list] = {}
# prefix -> {group_id: seconds}. Concurrent producers (pool workers) are tracked
# per group so the parent can report the critical path, not just the CPU sum.
_GROUPS: dict[str, dict] = {}
# prefix -> {group_id: [(start, end), ...]} of busy intervals, used to compute the
# union across concurrent workers (their overlap is what wall clock actually sees).
_GROUP_INTERVALS: dict[str, dict] = {}
# Own intervals, recorded only where asked for (a pool worker); the parent does not
# need them because its own time is already serial.
_INTERVALS: list = []
_RECORD_INTERVALS = False
_MAX_INTERVALS = 500_000
_LOCK = threading.Lock()


def enable_intervals(enabled: bool = True) -> None:
    """Record busy intervals in this process (call in a pool worker)."""
    global _RECORD_INTERVALS
    _RECORD_INTERVALS = bool(enabled)


def _observe(label: str, t0: float, t1: float) -> None:
    """Record one call: always its duration, plus its interval where enabled."""
    record(label, t1 - t0)
    if _RECORD_INTERVALS:
        try:
            with _LOCK:
                if _INTERVALS and t0 <= _INTERVALS[-1][1]:
                    # Touching or overlapping the previous call: extend rather than
                    # append. Calls inside one worker are sequential, so this keeps
                    # the list short without ever inflating busy time.
                    if t1 > _INTERVALS[-1][1]:
                        _INTERVALS[-1][1] = t1
                elif len(_INTERVALS) < _MAX_INTERVALS:
                    _INTERVALS.append([t0, t1])
        except Exception:
            pass


def intervals_snapshot() -> list:
    """This process's busy intervals as ``[[start, end], ...]``."""
    try:
        with _LOCK:
            return [[a, b] for a, b in _INTERVALS]
    except Exception:
        return []


def union_seconds(intervals) -> float:
    """Elapsed time covered by at least one interval -- the staggered metric.

    Unlike the per-worker max this accounts for workers that overlap only partially,
    which is the actual wall time the group spent inside the library.
    """
    try:
        spans = sorted((a, b) for a, b in intervals if b > a)
    except Exception:
        return 0.0
    total, cur_start, cur_end = 0.0, None, None
    for a, b in spans:
        if cur_end is None:
            cur_start, cur_end = a, b
        elif a > cur_end:
            total += cur_end - cur_start
            cur_start, cur_end = a, b
        elif b > cur_end:
            cur_end = b
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def record(label: str, seconds: float) -> None:
    """Add one observation. Never raises."""
    try:
        with _LOCK:
            entry = _TOTALS.get(label)
            if entry is None:
                _TOTALS[label] = [1, seconds]
            else:
                entry[0] += 1
                entry[1] += seconds
    except Exception:
        pass


@contextmanager
def timed(label: str):
    """Time a block. The block still runs if timing itself fails."""
    t0 = perf_counter()
    try:
        yield
    finally:
        record(label, perf_counter() - t0)


def call(label: str, fn, *args, **kwargs):
    """Time a single call and return its result."""
    t0 = perf_counter()
    try:
        return fn(*args, **kwargs)
    finally:
        record(label, perf_counter() - t0)


# --------------------------------------------------------------------------- proxy --

class TimedProxy:
    """Times every method call made through it; other attributes pass straight through.

    ``__fhe_raw__`` exposes the wrapped object for the cases that need the real thing.
    """

    __slots__ = ("__fhe_raw__", "_prefix", "_cache")

    def __init__(self, raw, prefix: str = "cc."):
        object.__setattr__(self, "__fhe_raw__", raw)
        object.__setattr__(self, "_prefix", prefix)
        object.__setattr__(self, "_cache", {})

    def __getattr__(self, name):
        raw = object.__getattribute__(self, "__fhe_raw__")
        attr = getattr(raw, name)
        if not callable(attr):
            return attr
        cache = object.__getattribute__(self, "_cache")
        wrapper = cache.get(name)
        if wrapper is None:
            label = object.__getattribute__(self, "_prefix") + name
            def wrapper(*args, _fn=attr, _label=label, **kwargs):
                t0 = _now()
                try:
                    return _fn(*args, **kwargs)
                finally:
                    _observe(_label, t0, _now())
            cache[name] = wrapper
        return wrapper

    def __repr__(self):
        return f"TimedProxy({object.__getattribute__(self, '__fhe_raw__')!r})"


def unwrap(obj):
    """Return the wrapped object if this is a proxy, else the object itself."""
    if type(obj) is TimedProxy:
        return object.__getattribute__(obj, "__fhe_raw__")
    return obj


# ------------------------------------------------------------------ namespace wrap --

def _free_wrapper(label: str, fn):
    def wrapper(*args, **kwargs):
        # Unwrap defensively: these are the functions a CryptoContext gets passed to
        # (Serialize), and a proxy reaching pybind11 would be a hard failure.
        if args and any(type(a) is TimedProxy for a in args):
            args = tuple(unwrap(a) for a in args)
        t0 = _now()
        try:
            return fn(*args, **kwargs)
        finally:
            _observe(label, t0, _now())
    wrapper.__name__ = getattr(fn, "__name__", label)
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    wrapper.__fhe_wrapped__ = fn
    return wrapper


def wrap_module_callables(namespace: dict, names, prefix: str = "") -> list:
    """Rebind the named callables in ``namespace`` to timed versions.

    Idempotent: a name already wrapped is left alone, so re-importing a module cannot
    stack wrappers. Returns the names actually wrapped.
    """
    wrapped = []
    for name in names:
        try:
            fn = namespace.get(name)
            if fn is None or not callable(fn) or hasattr(fn, "__fhe_wrapped__"):
                continue
            namespace[name] = _free_wrapper(prefix + name, fn)
            wrapped.append(name)
        except Exception:
            continue
    return wrapped


# ------------------------------------------------------------------------ reporting --

def snapshot() -> dict:
    """Cumulative totals for this process: ``{label: [calls, seconds]}``."""
    try:
        with _LOCK:
            return {k: [v[0], v[1]] for k, v in _TOTALS.items()}
    except Exception:
        return {}


def delta_since(previous: dict) -> dict:
    """Totals accumulated since ``previous``.

    A pool worker is initialised once and then handles several tasks, so returning
    the cumulative snapshot per task would count its startup cost repeatedly.
    """
    now = snapshot()
    out = {}
    for label, (calls, seconds) in now.items():
        before = previous.get(label)
        if before is None:
            out[label] = [calls, seconds]
        else:
            d_calls, d_secs = calls - before[0], seconds - before[1]
            if d_calls or d_secs:
                out[label] = [d_calls, d_secs]
    return out


def merge(other: dict, prefix: str = "", group=None, intervals=None) -> None:
    """Fold another process's snapshot into this one's totals.

    ``prefix`` namespaces the incoming labels. Pool workers run concurrently, so
    their seconds add up to CPU time rather than elapsed time: merged unlabelled,
    they would inflate the process total past its own wall clock. Keeping them under
    a prefix lets a reader separate "time this process spent" from "CPU time the
    pool spent".

    ``group`` identifies the concurrent producer (a worker pid). Totals are kept per
    group so ``summary`` can report the largest single worker -- the critical path,
    which is what a faster library would actually shorten -- alongside the sum.
    """
    if not other:
        return
    try:
        with _LOCK:
            if group is not None:
                bucket = _GROUPS.setdefault(prefix or "", {})
                bucket[group] = bucket.get(group, 0.0) + sum(v[1] for v in other.values())
                if intervals:
                    # A worker ships its cumulative list each task, so the newest
                    # snapshot supersedes the previous one. Replacing avoids both
                    # duplicate spans and unbounded growth.
                    ib = _GROUP_INTERVALS.setdefault(prefix or "", {})
                    ib[group] = [[a, b] for a, b in intervals]
            for label, pair in other.items():
                label = prefix + label
                entry = _TOTALS.get(label)
                if entry is None:
                    _TOTALS[label] = [pair[0], pair[1]]
                else:
                    entry[0] += pair[0]
                    entry[1] += pair[1]
    except Exception:
        pass


def reset() -> None:
    try:
        with _LOCK:
            _TOTALS.clear()
            _GROUPS.clear()
            _GROUP_INTERVALS.clear()
            _INTERVALS.clear()
    except Exception:
        pass


def summary_since(previous: dict, top: int = 0, previous_groups: dict | None = None) -> dict:
    """``summary`` restricted to what accumulated since ``previous``.

    Totals are per-process and a container can serve more than one job, so a report
    for *this* run has to be a delta rather than the running total.
    """
    try:
        snap = delta_since(previous or {})
        ops = {k: {"calls": v[0], "seconds": round(v[1], 6)} for k, v in snap.items()}
        if top:
            ops = dict(sorted(ops.items(), key=lambda kv: -kv[1]["seconds"])[:top])
        return {
            "seconds": round(sum(v[1] for v in snap.values()), 6),
            "calls": sum(v[0] for v in snap.values()),
            "ops": ops,
            "groups": _group_stats(previous_groups),
        }
    except Exception:
        return {"seconds": 0.0, "calls": 0, "ops": {}}


def groups_snapshot() -> dict:
    """``{prefix: {group_id: seconds}}`` for this process."""
    try:
        with _LOCK:
            return {k: dict(v) for k, v in _GROUPS.items()}
    except Exception:
        return {}


def _group_stats(previous: dict | None = None) -> dict:
    """Per-prefix concurrency stats: worker count, CPU sum, and critical path.

    ``max_seconds`` is a LOWER bound on the wall time the group spent in the
    library: staggered workers can cover more elapsed time than any single one.
    """
    out = {}
    previous = previous or {}
    try:
        with _LOCK:
            snap = {k: dict(v) for k, v in _GROUPS.items()}
        for prefix, bucket in snap.items():
            before = previous.get(prefix, {})
            # A worker is a fresh process per job, so a pid carried over from an
            # earlier run contributes a zero delta and must not count as a worker.
            vals = [sec - before.get(gid, 0.0) for gid, sec in bucket.items()]
            live = [gid for gid, sec in bucket.items() if sec - before.get(gid, 0.0) > 0]
            vals = [v for v in vals if v > 0]
            if not vals:
                continue
            # Union across the workers of THIS run: the elapsed time during which at
            # least one of them was inside the library. Between max (one worker) and
            # the CPU sum (all of them, as if serial).
            spans = []
            for gid in live:
                spans.extend(_GROUP_INTERVALS.get(prefix, {}).get(gid, []))
            busy = union_seconds(spans) if spans else 0.0
            out[prefix or "(none)"] = {
                "workers": len(vals),
                "cpu_seconds": round(sum(vals), 6),
                "max_seconds": round(max(vals), 6),
                "busy_seconds": round(busy, 6) if busy else None,
            }
    except Exception:
        pass
    return out


def summary(top: int = 0) -> dict:
    """Compact report: total seconds, total calls, per-operation and per-group stats."""
    try:
        snap = snapshot()
        ops = {k: {"calls": v[0], "seconds": round(v[1], 6)} for k, v in snap.items()}
        if top:
            ops = dict(sorted(ops.items(), key=lambda kv: -kv[1]["seconds"])[:top])
        return {
            "seconds": round(sum(v[1] for v in snap.values()), 6),
            "calls": sum(v[0] for v in snap.values()),
            "ops": ops,
            "groups": _group_stats(),
        }
    except Exception:
        return {"seconds": 0.0, "calls": 0, "ops": {}}
