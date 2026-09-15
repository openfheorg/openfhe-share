# Stat analytics profiling events (`StatAnalyticsEventType`)

This document describes **application-defined NVFlare events** used for **deeper per-phase profiling** of statistical / HE workflows, alongside the built-in profiler in `openfhe_flare/apis/profiler.py`.

## Purpose

- Emit **START** / **END** pairs around logical phases (setup, preprocess, encrypt, decrypt, etc.) from executors and aggregators.
- The **Profiler** component subscribes to these events and accumulates durations into `phase_breakdown_sec` per **workflow** and **round** in `profile_summary.json`.
- Avoids scattering manual timers; follows the same **event-driven** style as `EventType.*` and `AppEventType.*`.

## Event naming

- **Prefix:** all strings start with `stat_analytics_`.
- **Pattern:** `stat_analytics_<phase>_<start|end>`  
  Example: `stat_analytics_encrypt_start`, `stat_analytics_decrypt_end`.
- **Python constants:** `StatAnalyticsEventType.ENCRYPT_START`, `ENCRYPT_END`, etc. (see `openfhe_flare/apis/stat_analytics_event_type.py`).

## Phase keys (output JSON)

The profiler maps each event to a **phase key** used in `phase_breakdown_sec` by stripping `_start` / `_end` from the part after `stat_analytics_`:

| Constant suffix | String value (example) | `phase_breakdown_sec` key |
|-----------------|------------------------|---------------------------|
| `SETUP_*` | `stat_analytics_setup_start` | `setup` |
| `PREPROCESS_*` | `stat_analytics_preprocess_start` | `preprocess` |
| `POSTPROCESS_*` | `stat_analytics_postprocess_start` | `postprocess` |
| `COMPUTE_*` | `stat_analytics_compute_start` | `compute` |
| `AGGREGATE_*` | `stat_analytics_aggregate_start` | `aggregate` |
| `AGGREGATE_REFERENCE_*` | `stat_analytics_aggregate_reference_start` | `aggregate_reference` |
| `ENCRYPT_*` | `stat_analytics_encrypt_start` | `encrypt` |
| `DECRYPT_*` | `stat_analytics_decrypt_start` | `decrypt` |
| `ENCRYPT_PQC_*` | `stat_analytics_encrypt_pqc_start` | `encrypt_pqc` |
| `DECRYPT_PQC_*` | `stat_analytics_decrypt_pqc_start` | `decrypt_pqc` |

Multi-part names (e.g. `aggregate_reference`, `encrypt_pqc`) are parsed correctly by `parse_stat_analytics_phase_event()`.

## Semantic mapping (what each phase measures)

| Phase key | Typical location | What it wraps |
|-----------|------------------|----------------|
| **setup** | Client/server | Args, filters, `set_props_from_init_load`, path resolution, metadata prep. |
| **preprocess** | Client/server | `preprocess()`, `preprocess_reference()`, `handle_pre_count`, server biomarker prep after setup. |
| **postprocess** | Client/server | `postprocess()`, `postprocess_reference()`, final formatting. |
| **compute** | `HEExecutor`, `HEAggregator` only | KeyGen rounds, `task_init_mix` — **not** stat-analytics `exec_encrypt_stat_analytics`. |
| **aggregate** | Server | `openfhe_manager.aggregate_stat_analytics(...)` (HE ciphertext aggregation across clients). |
| **aggregate_reference** | Client + server | `analytics_manager.aggregate_reference(...)` (clear-text / local combine). |
| **encrypt** | Client | `exec_encrypt_stat_analytics(...)`. |
| **decrypt** | Client + server | Client: `_decrypt_stat_analytics_*`. Server: `server_decrypt_stat_analytics_r0`, `server_decrypt_round0` (HE path). |
| **encrypt_pqc** | Client (lead) | `build_payload_vector` when hiding result from server. |
| **decrypt_pqc** | Client | `decrypt_payload` (PQC round). |

## Usage pattern

Components inherit from `FLComponent` (executors, aggregators) and call:

```python
from openfhe_flare.apis.stat_analytics_event_type import StatAnalyticsEventType

self.fire_event(StatAnalyticsEventType.PREPROCESS_START, fl_ctx)
try:
    ...
finally:
    self.fire_event(StatAnalyticsEventType.PREPROCESS_END, fl_ctx)
```

Every **START** must have a matching **END** for the same phase (LIFO nesting is supported).

## Profiler behavior

- Listens in `Profiler.handle_event()` for events parsed by `parse_stat_analytics_phase_event()`.
- Accumulates **seconds** into `RoundMetrics.phase_breakdown_sec[phase_key]` per workflow/round.
- **Client:** If `CURRENT_ROUND` is missing in `fl_ctx` during `execute()` (common), the profiler uses latched `(workflow, round)` from `BEFORE_TASK_EXECUTION` so phases align with `client_compute_time_sec` (see profiler implementation).

## Output

Written to **`jobs/<job_id>/profile_summary.json`** (per party), under each workflow → round:

```json
"phase_breakdown_sec": {
  "preprocess": 3.286862756,
  "encrypt": 0.15284807,
  "setup": 0.059202045
}
```

## Interpreting totals

- **`phase_breakdown_sec`** sums **instrumented** application phases only.
- **`client_compute_time_sec`** / **`server_compute_time_sec`** come from NVFlare task boundaries and (on the server) include dispatch/accept/aggregation windows. They are **not** required to equal the sum of phases; gaps are normal where framework time or uninstrumented code runs. Fully wrapped rounds often land near **~99%** of compute time; thinly instrumented rounds (e.g. a single `postprocess` span) can be much lower.

## Related files

| File | Role |
|------|------|
| `openfhe_flare/apis/stat_analytics_event_type.py` | Event constants and `parse_stat_analytics_phase_event()`. |
| `openfhe_flare/apis/profiler.py` | Profiler, `phase_breakdown_sec`, client round latching. |
| `openfhe_flare/apis/HEExecutor.py` | KeyGen / `init_mix` **compute** phases. |
| `openfhe_flare/apis/HEAggregator.py` | KeyGen **compute**, decryption **decrypt**. |
| `jobs/stat_analytics/app/custom/analytics_executor.py` | Stat workflow **setup** / **preprocess** / **encrypt** / **decrypt** / **PQC** / **aggregate_reference**. |
| `jobs/stat_analytics/app/custom/analytics_aggregator.py` | Server **setup** / **preprocess** / **aggregate** / **aggregate_reference** / **decrypt** / **postprocess**. |

## See also

- `docs/NVFLARE_SG_Sequence*.mmd` — built-in NVFlare event order vs RTT/compute metrics.
- `README.md` — optional profiler component registration on server and client configs.
