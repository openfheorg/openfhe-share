"""
Application-defined event types for statistical / HE analytics workflows.

Use START/END pairs so the Profiler (and other listeners) can measure phase durations
without scattering timer code. String values follow NVFlare's lowercase+underscore style.

Phase keys (JSON ``phase_breakdown_sec``) are derived by stripping ``_start`` / ``_end`` from
the suffix after the ``stat_analytics_`` prefix, e.g.:

  ``stat_analytics_encrypt_start`` → ``encrypt``
  ``stat_analytics_aggregate_reference_start`` → ``aggregate_reference``

Naming convention:

  - **setup** / **preprocess** / **postprocess** — orchestration and data prep.
  - **aggregate** — server ``aggregate_stat_analytics`` (HE ciphertext aggregation).
  - **aggregate_reference** — ``aggregate_reference`` (clear-text / local combine).
  - **encrypt** — ``exec_encrypt_stat_analytics`` (client).
  - **decrypt** — ``_decrypt_stat_analytics_*``, ``server_decrypt_stat_analytics_r0``,
    ``server_decrypt_round0`` (multi-party decrypt on server).
  - **encrypt_pqc** / **decrypt_pqc** — PQC payload wrap/unwrap on client.
  - **compute** — reserved for KeyGen / ``init_mix`` and other non-stat-analytics crypto
    in ``HEExecutor`` / ``HEAggregator`` (narrower than old generic “COMPUTE”).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

_PREFIX = "stat_analytics_"

# Last workflow in fed server config: 2-round SAG to merge per-site profile_summary.json on the leader.
PROFILE_CONSOLIDATE_WORKFLOW_ID = "workflow_consolidate_profile_summaries"

# Clients do not receive EventType.START_WORKFLOW (server_runner only). The executor fires this
# before reading profile_summary.json so Profiler flushes to disk for task_profile_consolidate r0.
PROFILE_SNAPSHOT_EVENT = "duality_profile_snapshot"


class StatAnalyticsEventType:
    """Phase boundaries for executor and aggregator instrumentation."""

    SETUP_START = "stat_analytics_setup_start"
    SETUP_END = "stat_analytics_setup_end"

    PREPROCESS_START = "stat_analytics_preprocess_start"
    PREPROCESS_END = "stat_analytics_preprocess_end"

    # KeyGen, init_mix, and other HE lifecycle in HEExecutor / HEAggregator (not stat-analytics encrypt)
    COMPUTE_START = "stat_analytics_compute_start"
    COMPUTE_END = "stat_analytics_compute_end"

    # Server: openfhe_manager.aggregate_stat_analytics(...)
    AGGREGATE_START = "stat_analytics_aggregate_start"
    AGGREGATE_END = "stat_analytics_aggregate_end"

    # Client + server: analytics_manager.aggregate_reference(...)
    AGGREGATE_REFERENCE_START = "stat_analytics_aggregate_reference_start"
    AGGREGATE_REFERENCE_END = "stat_analytics_aggregate_reference_end"

    POSTPROCESS_START = "stat_analytics_postprocess_start"
    POSTPROCESS_END = "stat_analytics_postprocess_end"

    # Client: exec_encrypt_stat_analytics
    ENCRYPT_START = "stat_analytics_encrypt_start"
    ENCRYPT_END = "stat_analytics_encrypt_end"

    # Client: _decrypt_stat_analytics_*; server: server_decrypt_stat_analytics_r0, server_decrypt_round0
    DECRYPT_START = "stat_analytics_decrypt_start"
    DECRYPT_END = "stat_analytics_decrypt_end"

    # Client: PQC build_payload_vector
    ENCRYPT_PQC_START = "stat_analytics_encrypt_pqc_start"
    ENCRYPT_PQC_END = "stat_analytics_encrypt_pqc_end"

    # Client: PQC decrypt_payload
    DECRYPT_PQC_START = "stat_analytics_decrypt_pqc_start"
    DECRYPT_PQC_END = "stat_analytics_decrypt_pqc_end"


def parse_stat_analytics_phase_event(event_type: str) -> Optional[Tuple[str, bool]]:
    """
    If ``event_type`` is a StatAnalytics phase event, returns (phase_key, is_end).

    ``phase_key`` is the suffix before ``_start`` / ``_end``, e.g. ``encrypt``,
    ``aggregate_reference``, ``encrypt_pqc``.
    ``is_end`` is False for *_START, True for *_END.
    """
    if not isinstance(event_type, str) or not event_type.startswith(_PREFIX):
        return None
    rest = event_type[len(_PREFIX) :]
    if rest.endswith("_start"):
        return (rest[: -len("_start")], False)
    if rest.endswith("_end"):
        return (rest[: -len("_end")], True)
    return None


def is_stat_analytics_phase_event(event_type: Any) -> bool:
    return parse_stat_analytics_phase_event(event_type) is not None
