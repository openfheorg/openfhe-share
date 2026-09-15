# Observability, Logging, and Troubleshooting

## Files Covered

| File | Role |
| --- | --- |
| `app/api/routes/*.py` | Route-level request logging, validation messages, traceback responses, and endpoint-specific troubleshooting signals. |
| `app/api/routes/JobRunnerRoutes.py` | Polling status endpoint, direct websocket status stream, API Gateway websocket bridge, job info lookup, result lookup, function config lookup, and result mapping lookup. |
| `app/api/routes/NVFlareRoutes.py` | NVFlare progress callback, job submission, job history, and crypto audit logging. |
| `app/api/routes/ClientRoutes.py` | Client connection status, participation status, participation submission logging, and participation error responses. |
| `app/core/mysql/job_tracking/JobStatusWriter.py` | Persists user-visible job status and log output in `job_runner_log`; also prints status updates to stdout. |
| `app/core/mysql/job_tracking/JobStatusRetriever.py` | Reads `job_runner_log` and enriches status responses with referenced NVFlare job IDs, run duration, and function names. |
| `app/core/mysql/job_tracking/NVFlareJobsDataRetriever.py` | Reads result JSON files from local filesystem or SSH-backed NVFlare output paths. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobMonitor.py` | Polls NVFlare admin `list_jobs`, updates `nvflare_jobs.status`, and records submit/run timing. |
| `app/core/job_runner/nvflare_jobs/apis/profiler.py` | Runtime profiler that writes `profile_summary.json` and the per-party `trace.jsonl` event stream at run end. |
| `app/core/job_runner/nvflare_jobs/apis/trace_filter.py` | Server-side task data filter that stamps a correlation id on outbound tasks and appends `trace_filter.jsonl` dispatch records. |
| `app/core/job_runner/nvflare_jobs/taskflow_report.py` | Host-side renderer that merges collected trace streams into Perfetto/Mermaid/Graphviz/round/timeline artifacts under the job save location. |
| `app/core/mysql/managers/NVFlareClientEmitManager.py` | Converts NVFlare runtime progress callback codes into human-readable job status log messages. |
| `app/core/mysql/managers/NVFlareJobsManager.py` | Persists NVFlare job metadata, status, function/config mappings, datasource logs, workflow group logs, crypto audit records, and history responses. |

## Observability Model

The backend currently has four main observability surfaces:

1. Container/stdout logging from `print(..., flush=True)`, `logging.exception(...)`, and `traceback.print_exc()`.
2. Persisted job status and status log data in MySQL table `job_runner_log`.
3. NVFlare job metadata, result paths, workflow metadata, and history records in the `nvflare_jobs` family of tables.
4. File-based profiling and trace artifacts written into the NVFlare job-results tree: `profile_summary.json`, per-party `trace.jsonl`, and the rendered `taskflow/` report directory.

There is no centralized structured logger configured in the backend code. Most operational visibility comes from direct stdout messages and from database-backed status records. In local Docker or standalone runtime, stdout is the terminal/container log. In deployed container runtime, stdout/stderr is expected to be collected by the container platform log driver, such as ECS/CloudWatch when running in AWS.

## Runtime Log Locations

| Area | Location | Notes |
| --- | --- | --- |
| FastAPI route logs | Process stdout/stderr | Route files use `print(..., flush=True)` heavily. Dockerfile sets `PYTHONUNBUFFERED=1`, so messages are emitted immediately. |
| Python exception logging | Process stdout/stderr | Route code uses `logging.exception(...)` in some paths and `traceback.format_exc().splitlines()` in responses. No custom logger configuration is present. |
| User-visible job progress | MySQL `job_runner_log` | Written by `JobStatusWriter.log()` and read by `/jobs/status` plus websocket status routes. |
| Job metadata/history | MySQL `nvflare_jobs` and related tables | Written by `NVFlareJobsManager`; read by `/nvflare/jobs/history`, `/jobs/info`, and result/config lookup routes. |
| NVFlare runtime progress callbacks | `/nvflare/client/emit_progress` into `job_runner_log` | `NVFlareClientEmitManager` maps numeric runtime codes to readable messages and status labels. |
| NVFlare result files | Local filesystem in local mode; SSH path in non-local mode | `NVFlareJobsDataRetriever` reads JSON outputs from the NVFlare job-results tree. |
| Profiling metrics | `Profiler` writes `profile_summary.json` per party; the backend reads `<job-results-root>/<nvflare_job_id>/profile_summary.json` | Returned by `/jobs/results/mapping` as `profile_summary` when readable. |
| Per-party causal event trace | `trace.jsonl` beside each party's `profile_summary.json`, plus a copy under `<trace sink>/traces/<nvflare_job_id>/<site>/trace.jsonl` | Written by `Profiler` at run end. The sink directory comes from `DUALITY_TRACE_SINK_DIR`, defaulting to `/job-results`. |
| Server dispatch correlation records | `trace_filter.jsonl` beside the server's `trace.jsonl` | Written by `TraceCorrelationFilter` so server dispatch events can be paired exactly with client task receipts. |
| Rendered taskflow report | `<job save location>/<nvflare_job_id>/taskflow/` | Written host-side by `taskflow_report.generate_report_for_job()` as a background side effect of `POST /jobs/results`. |
| Websocket stream state | In-memory process dictionary | API Gateway websocket connections are tracked in `_ACTIVE_API_GATEWAY_CONNECTIONS`; this state is not persisted across backend process restarts. |

## Status Table Schema

### `job_runner_log`

`job_runner_log` is the primary user-visible job status table.

| Column | Type | Purpose |
| --- | --- | --- |
| `uuid` | `VARCHAR(36)` primary key | Backend job runner UUID returned from `/nvflare/jobs/submit` as `job_id`. |
| `status` | `VARCHAR(255)` | Current high-level status string for the job. |
| `log` | `MEDIUMTEXT` | Newline-delimited log messages. Each persisted line is timestamped by `JobStatusWriter.log()`. |
| `create_date` | `DATETIME` | Initial row creation timestamp. |
| `update_date` | `DATETIME` | Updated whenever the log or status changes. |

Indexes:

| Index | Columns | Purpose |
| --- | --- | --- |
| `idx_create_date` | `create_date DESC` | Supports recent log/status lookup patterns. |
| `idx_update_date` | `update_date` | Supports update-time inspection. |

`JobStatusWriter.log()` uses `INSERT ... ON DUPLICATE KEY UPDATE` so the first update creates the row and later updates append to `log`. When a status is supplied, the current `status` column is also replaced.

## Job Metadata and History Tables

### `nvflare_jobs`

`nvflare_jobs` records one row per staged/submitted NVFlare job. The row is linked back to the user-visible status row through `job_runner_id`.

| Column | Purpose |
| --- | --- |
| `id` | Internal MySQL job ID. |
| `project_id` | Project that owns the job. |
| `nvflare_assigned_id` | NVFlare-assigned job ID returned by the NVFlare admin command. |
| `filter_id` | Filter definition used by the job. |
| `threshold_config_id` | Optional threshold config. |
| `status` | Current NVFlare job status from manager/monitor logic. |
| `job_path` | Staged job artifact path. |
| `output_path` | NVFlare result/output path. |
| `job_runner_id` | Backend job runner UUID from `job_runner_log.uuid`. |
| `submit_time` | Submit time parsed from NVFlare `list_jobs`. |
| `run_duration` | Run duration parsed from NVFlare `list_jobs`. |
| `non_contributing_clients` | Comma-separated client names excluded from contribution. |
| `exclude_analyzing_clients` | Comma-separated client names excluded from analysis. |
| `create_date`, `update_date` | Row timestamps. |

Related tables used by status/history/result flows:

| Table | Purpose |
| --- | --- |
| `nvflare_job_functions` | Links jobs to supported functions. |
| `nvflare_job_function_configs` | Links jobs to function config sets and workflow IDs. |
| `defined_function_config_sets` | Stores unique function configuration hashes. |
| `defined_function_config_set_members` | Links config sets to individual config properties. |
| `defined_function_config_properties` | Stores property/value pairs such as model/open-encrypted settings. |
| `nvflare_job_datasource_log` | Records datasource group context for a submitted job. |
| `nvflare_job_workflow_groups` | Records workflow group selections at the job level. |
| `nvflare_job_workflow_group_options` | Records selected workflow group options. |
| `nvflare_job_crypto_audit` | Stores encrypted workflow crypto parameter audit records. |

## Job Status Writer Behavior

`JobStatusWriter` is constructed with a backend job runner UUID. It opens a MySQL connection and owns a cursor for the lifetime of the writer.

Important behavior:

- `log(log_message, status=None)` returns immediately when `log_message` is empty.
- Each log entry is prefixed with a UTC ISO timestamp.
- Log entries append to `job_runner_log.log` using a newline separator.
- If `status` is provided, `job_runner_log.status` is updated to the supplied value.
- Writes are guarded by a `threading.Lock` to avoid interleaving log writes from the same writer instance.
- The function checks whether the row has status `STOP`. If so, it appends a stop message, commits it, and calls `os._exit(0)` as a hard process kill switch.
- Database write exceptions are printed using `traceback.print_exc()`.
- `complete()` closes the cursor and connection.

`safe_status_update(status_writer, status, message)` is the standard helper for runtime status updates. It always prints this format to stdout:

```text
[<status-or-log>] [<utc-iso-timestamp>] <message>
```

When a `JobStatusWriter` is supplied, it also persists the message and status to `job_runner_log`.

## Status Values

The current `JobRunnerStatus` enum includes these labels:

| Status | Meaning |
| --- | --- |
| `Queued` | Job accepted by backend but not yet progressed. |
| `Processing` | General processing state. |
| `Checking Client Participation` | Participation prerequisites are being checked. |
| `Broadcasting Participation Job` | Participation confirmation job is being broadcast. |
| `Monitoring Participation Responses` | Participation responses are being monitored. |
| `Client Participation Established` | Participation has been established. |
| `Participation Failed` | Participation flow failed. |
| `No Clients Accepted Participation` | Participation flow completed without accepted clients. |
| `Processing Filters` | Filter processing is underway. |
| `Establishing Secure Connection` | Secure connection setup is underway. |
| `Secure Connection Established` | Secure connection setup completed. |
| `Uploading NVFlare Job` | NVFlare job upload stage. |
| `Defining NVFlare Job` | Job definition/metadata stage. |
| `Broadcasting NVFlare Job` | NVFlare job broadcast/submission stage. |
| `Job Broadcast Received` | Runtime callback indicates a client/server received the job. |
| `Client Compute` | Client runtime compute stage. |
| `Server Compute` | Server runtime compute stage. |
| `Interactive Key Generation` | Encrypted workflow key generation stage. |
| `Collaborative Decryption` | Encrypted workflow collaborative decryption stage. |
| `Client Encryption Processing` | Client encrypted-processing stage. |
| `Server Encryption Processing` | Server encrypted-processing stage. |
| `Client Performing Analysis` | Client analysis stage. |
| `Server Performing Analysis` | Server analysis stage. |
| `Client Processing Results` | Client result-writing/processing stage. |
| `Server Processing Results` | Server result-writing/processing stage. |
| `Performing Analysis` | General analysis stage. |
| `Aggregating Job Results` | Aggregation stage. |
| `Threshold Not Met` | Threshold requirement failed. |
| `Analysis Failure` | Analysis failure state. |
| `Failure` | General failure state. |
| `Warning` | Warning state. |
| `Error` | Error state. |
| `DONE` | Terminal successful completion state. |

`NVFlareJobsManager.set_nvflare_job_status()` can preserve a job-runner failure state over an NVFlare status update. The current override set includes `Threshold Not Met`.

## Job Status Retrieval

`JobStatusRetriever.get_status_by_uuid(uuid)` reads the `job_runner_log` row and enriches it with linked NVFlare job details.

The retriever:

1. Selects the `job_runner_log` row by `uuid`.
2. Looks up `nvflare_jobs` rows where `job_runner_id = uuid`.
3. Adds `referenced_by`, a list of non-empty `nvflare_assigned_id` values.
4. Adds `run_duration` from the first linked NVFlare job row that has a run duration.
5. Adds `nvflare_jobs`, including internal job ID, NVFlare-assigned ID, run duration, and function names.
6. Adds `functions`, a sorted unique list of function names across linked jobs.

The retriever has a simple retry wrapper around SQL execution. It defaults to three attempts with exponential delay starting at 0.2 seconds.

## `/jobs/status` Polling Endpoint

`POST /jobs/status` reads `job_runner_log` through `JobStatusRetriever`.

Request example:

```json
{
  "job_id": "backend-job-runner-uuid"
}
```

Response when no row exists yet:

```json
{
  "job_id": "backend-job-runner-uuid",
  "status": "QUEUED",
  "log": [],
  "last_update": "None",
  "functions": []
}
```

Response when status exists:

```json
{
  "job_id": "backend-job-runner-uuid",
  "status": "Client Processing Results",
  "log": [
    "[2026-04-28T20:01:00+00:00] NVFlareJobsManager: Logged NVFlare job 12 linked to functions ['stat_analytics'] with configs",
    "[2026-04-28T20:01:05+00:00] Client site-1: [Statistical Analytics] Results written to JSON (round 1)"
  ],
  "last_update": "2026-04-28T20:01:05",
  "functions": ["stat_analytics"],
  "referenced_by": ["<nvflare-assigned-id>"],
  "run_duration": "00:01:42"
}
```

Error response behavior:

- SQL or unexpected errors return HTTP 400.
- Response includes `status: "Exception occured while retrieving job status"` and a traceback split into `log` lines.
- The misspelling `occured` is present in the current code and should be treated as current behavior.

## Direct Websocket Status Endpoints

Endpoints:

| Endpoint | Purpose |
| --- | --- |
| `WEBSOCKET /jobs/status/ws/{job_id}` | Streams status for a job ID. |
| `WEBSOCKET /jobs/status/ws/local/{job_id}` | Same handler as above; separate route for local websocket usage. |

The websocket handler:

1. Accepts the websocket.
2. Opens a `JobStatusRetriever`.
3. Polls MySQL every `0.5` seconds.
4. Builds the same response payload used by `/jobs/status`.
5. Sends a `job_status` message only when the payload changes.
6. Sends a `heartbeat` message every `10` seconds when there is no status change.
7. Requires an acknowledgement for every outbound websocket message.
8. Stops streaming when status uppercases to `DONE` or `FAILURE`.
9. Closes with code `1008` when the frontend does not acknowledge a message within `5` seconds.
10. Attempts to send `job_status_error` and closes with code `1011` on unexpected internal errors.

Outbound status message shape:

```json
{
  "type": "job_status",
  "message_id": "generated-message-id",
  "requires_ack": true,
  "job_id": "backend-job-runner-uuid",
  "status": "Client Compute",
  "log": [],
  "last_update": "2026-04-28T20:01:05",
  "functions": []
}
```

Heartbeat shape:

```json
{
  "type": "heartbeat",
  "message_id": "generated-message-id",
  "requires_ack": true,
  "job_id": "backend-job-runner-uuid"
}
```

Acknowledgement expected from the frontend:

```json
{
  "type": "ack",
  "message_id": "generated-message-id"
}
```

## API Gateway Websocket Bridge

Endpoints:

| Endpoint | Purpose |
| --- | --- |
| `POST /jobs/status/ws/connect` | Registers an API Gateway websocket connection and starts a background status stream task. |
| `POST /jobs/status/ws/ack` | Records acknowledgement for a previously sent websocket message. |
| `POST /jobs/status/ws/disconnect` | Removes in-memory state for a connection. |
| `POST /jobs/status/ws/default` | Dispatches `ack` route messages or returns an ok response for other default route calls. |

The API Gateway websocket bridge keeps active state in module-level `_ACTIVE_API_GATEWAY_CONNECTIONS`. Each connection stores:

- `connection_id`
- `job_id`
- `management_endpoint`
- `stop_event`
- background task handle
- pending acknowledgement message ID/event

The code derives the API Gateway Management API endpoint from `domainName` and `stage` in the request context. If those values are absent, it falls back to the hardcoded websocket URL:

```text
wss://ws.example.org/prod
```

Connect request example:

```json
{
  "connectionId": "abc123",
  "job_id": "backend-job-runner-uuid",
  "requestContext": {
    "domainName": "ws.example.org",
    "stage": "prod"
  }
}
```

Connect response example:

```json
{
  "ok": true,
  "connection_id": "abc123",
  "job_id": "backend-job-runner-uuid",
  "management_endpoint": "https://ws.example.org/prod"
}
```

Ack request example:

```json
{
  "connectionId": "abc123",
  "message_id": "generated-message-id"
}
```

Ack response example:

```json
{
  "ok": true,
  "connection_id": "abc123",
  "message_id": "generated-message-id",
  "acknowledged": true
}
```

Disconnect response example:

```json
{
  "ok": true,
  "connection_id": "abc123"
}
```

Important runtime assumptions:

- API Gateway websocket connection state is in memory only.
- Backend restarts remove active connection state.
- Multiple backend replicas would not share this connection map.
- Acknowledgements are required for messages sent through API Gateway as well as direct websockets.
- `GoneException` is treated as a closed API Gateway connection.
- Acknowledgement timeout causes the backend to attempt connection deletion.

## NVFlare Runtime Progress Callback

Endpoint:

```text
POST /nvflare/client/emit_progress
```

This endpoint receives progress events from NVFlare runtime code. In non-local environments it checks `$pw` against the MySQL password from `ResourceConfigProvider.get_mysql_config()`. It retries config retrieval without cache if the first password check fails.

Payload fields used by `NVFlareClientEmitManager`:

```json
{
  "job_id": "nvflare-assigned-job-id",
  "client_name": "site-1",
  "origin": "site-1",
  "scalars": {
    "code": 400,
    "round": 0
  },
  "function": "stat_analytics"
}
```

The manager:

1. Looks up `job_runner_id` from `nvflare_jobs` by `nvflare_assigned_id`.
2. Creates a `JobStatusWriter` for that backend job runner ID when found.
3. Extracts `code` and `round` from `payload.scalars`.
4. Uses `origin` or `client_name` as the site label.
5. Maps the numeric code to a human-readable message.
6. Maps the numeric code to a `JobRunnerStatus`.
7. Deduplicates repeated events for three seconds using `(job_runner_id, site, function, code, round)`.
8. Writes the message to stdout and `job_runner_log` via `safe_status_update()`.

Current progress code mapping includes:

| Code | Message | Typical status mapping |
| --- | --- | --- |
| `100` | Job broadcast received | `Job Broadcast Received` |
| `101` | Executing keygen workflow | `Interactive Key Generation` |
| `300` | Parameters loaded | Client/server compute |
| `400` | Encrypting local statistics | Client/server encryption processing |
| `410` | Preprocessing (reference) | Client/server analysis |
| `420` | Preprocessing (encrypted) | Client/server encryption processing |
| `500` | Collaborative decryption | Collaborative decryption/encryption processing path |
| `600` | Post-processing | Client/server results |
| `702` | Results written to JSON | Client/server results |
| `710` | Aggregating results from all sources | Server results |
| `711` | Aggregation complete; running analysis | Server analysis |
| `712` | Writing aggregated results to JSON | Server results |
| `720` | Threshold limit not met | `Threshold Not Met` |
| `900` | Exception encountered | `Error` |
| `1100`-`1240` | Encrypted biomarker workflow events | Encrypted workflow compute/analysis/results statuses |

Codes not in the map are logged as `Event code <code>` and default to `Processing` unless otherwise mapped.

## PQC round diagnostics (NVFlare audit log)

Separately from the numeric progress codes, the hidden-result PQC workflows emit human-readable diagnostic lines through the NVFlare `custom`/`custom_logger` channel, which land in the NVFlare runtime `audit_log.txt` (server) and the client logs. These are the primary surface for debugging encrypted leader/non-leader dispatch:

| Line (substring) | Source | Meaning |
| --- | --- | --- |
| `PQC round-2 per-client specs (...): accepted_data=... leader_map=... specs=...` | server aggregator | Which non-leaders the round-2 per-client payloads were built for. |
| `PQC round-2 (...): analyzing non-leaders ... are MISSING from per_client_specs` | server aggregator (ERROR) | A non-leader would receive an empty round-3 payload (should not occur with the wait barrier). |
| `PQC round-3 (...): leader '...' round-2 submission is ABSENT/empty ...` | server aggregator (ERROR + raise) | The round advanced before the leader submitted; the combo is failed loudly rather than silently. |
| `... PQC round 2 build (...): enc_weights keys=...` | leader client | Which non-leaders the leader actually built payloads for. |
| `... PQC round 3: missing per-client payload (got ...) ...; skipping this combo's result ...` | non-leader client (ERROR) | Graceful round-3 skip — that combo's result is absent for the run; the job continues. |
| `_await_asymmetric_completion: waited Xs ... (closed the round-2 wait race)` | server controller (`customSAG`) | The round-2 wait barrier blocked until a slow client's task completed before aggregation. |

## NVFlare Job Monitor

`NVFlareJobMonitor.wait_for_completion()` polls the NVFlare admin kit with:

```text
list_jobs <nvflare_assigned_job_id>
```

Default behavior:

| Setting | Value |
| --- | --- |
| Poll interval | `2` seconds |
| Timeout | `900` seconds |
| Command timeout | `300` seconds |

The monitor parses table rows that match this shape:

```text
| <job_id> | <name> | <status> | <submit_time> | <run_duration> |
```

When the target job row is found, the monitor:

- captures `status`
- captures `submit_time`
- captures `run_duration`
- updates `nvflare_jobs.status`
- updates `nvflare_jobs.submit_time` and `nvflare_jobs.run_duration`
- returns when status starts with `FINISHED:`

If admin command execution returns a non-zero code, the monitor treats it as transient and retries until timeout. If the timeout elapses, it raises:

```text
Job <job_id> did not complete within <timeout> seconds (last status: <last_status>).
```

## Job History Endpoint

Endpoint:

```text
POST /nvflare/jobs/history
```

Request example:

```json
{
  "project_id": 1,
  "function_names": ["stat_analytics"],
  "filter_mode": "ANY",
  "date_filter": {
    "mode": "ON",
    "create_date": "2026-04-28"
  }
}
```

Behavior:

- `project_id` is required and must parse as an integer.
- `function_names` defaults to an empty list.
- `filter_mode` defaults to `ANY`; `ONLY` requires the job to have exactly the supplied functions.
- `date_filter.mode` supports `ON`, `BEFORE`, and `AFTER` when `date_filter.create_date` is a non-empty string.
- Legacy top-level `create_date` is still used when `date_filter` is not valid.
- `NVFlareJobsManager.get_nvflare_jobs()` prints the SQL it establishes for the selected query path.
- History responses are ordered by `nvflare_jobs.create_date DESC`.

Success response shape:

```json
{
  "status": "SUCCESS",
  "nvflare_jobs": [
    {
      "id": 12,
      "project_id": 1,
      "nvflare_assigned_id": "nvflare-job-id",
      "filter_id": 3,
      "threshold_config_id": 1,
      "status": "FINISHED:COMPLETED",
      "job_path": "/path/to/staged/job",
      "output_path": "/path/to/job-results/nvflare-job-id",
      "job_runner_id": "backend-job-runner-uuid",
      "non_contributing_clients": "site-2",
      "exclude_analyzing_clients": null,
      "submit_time": "2026-04-28T20:01:00",
      "run_duration": "00:01:42",
      "create_date": "2026-04-28T20:00:55",
      "update_date": "2026-04-28T20:02:42",
      "functions": ["stat_analytics"],
      "functions_map": {},
      "threshold": {
        "id": 1,
        "method": "PROTECTED",
        "threshold": 2
      },
      "datasource_log": {
        "project_id": 1,
        "datasource_group_id": 1,
        "datasource_group_name": "DEFAULT",
        "create_date": "2026-04-28T20:00:55",
        "update_date": "2026-04-28T20:00:55"
      },
      "workflow_groups": [],
      "workflow_group_data": {},
      "crypto_audit_record": null
    }
  ]
}
```

Error behavior:

| Case | Response |
| --- | --- |
| Missing/invalid `project_id` | HTTP 400, `{"status":"FAILURE","error":"project_id is required"}` |
| Unexpected exception | HTTP 500, `{"status":"FAILURE","error":"Internal error"}` plus traceback printed to stdout/logging. |

## Job Info Endpoint

Endpoint:

```text
POST /jobs/info
```

Accepted lookup fields:

- `nvflare_job_id`
- `nvflare_assigned_id`
- `job_runner_id`
- `id`

At least one must be present. Multiple supplied values are ORed together in the SQL where clause.

Request example:

```json
{
  "job_runner_id": "backend-job-runner-uuid"
}
```

Response when found:

```json
{
  "job": {
    "id": 12,
    "project_id": 1,
    "nvflare_assigned_id": "nvflare-job-id",
    "filter_id": 3,
    "threshold_config_id": 1,
    "status": "FINISHED:COMPLETED",
    "job_path": "/path/to/staged/job",
    "output_path": "/path/to/job-results/nvflare-job-id",
    "job_runner_id": "backend-job-runner-uuid",
    "non_contributing_clients": "site-2",
    "exclude_analyzing_clients": null,
    "submit_time": "2026-04-28T20:01:00",
    "run_duration": "00:01:42",
    "create_date": "2026-04-28T20:00:55",
    "update_date": "2026-04-28T20:02:42",
    "functions": ["stat_analytics"],
    "threshold": {
      "id": 1,
      "method": "PROTECTED",
      "threshold": 2
    }
  }
}
```

Response when no row matches:

```json
{
  "job": null
}
```

Error behavior:

| Case | Response |
| --- | --- |
| No lookup field supplied | HTTP 400, `{"error":"nvflare_job_id, job_runner_id, or id is required."}` |
| Unexpected exception | HTTP 500, `{"error":"Failed to fetch NVFlare job information: [...]"}` |

## Result Retrieval Endpoint

Endpoint:

```text
POST /jobs/results
```

Request example:

```json
{
  "nvflare_job_id": "nvflare-job-id",
  "function": "stat_analytics",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Behavior:

1. Validates `nvflare_job_id`, `function`, and `workflow_id`, and rejects an `nvflare_job_id` that does not match `[A-Za-z0-9_-]+`.
2. Converts `function` to `SupportedFunction`.
3. Creates `NVFlareJobsDataRetriever`.
4. Reads workflow result files from local filesystem in local mode or over SSH in non-local mode.
5. Reads function config for the workflow from MySQL.
6. Runs `taskflow_report.generate_report_for_job()` in a worker thread as a fire-and-forget side effect.
7. Returns `job_data` and `function_config`.

Response shape:

```json
{
  "job_data": {
    "initiator_results": {},
    "aggregate_results": {},
    "aggregate_processed_results": {},
    "workflow_error": null,
    "paths": {
      "initiator_used": ".../initiator/raw_results.json",
      "aggregated_used": ".../aggregated/raw_results.json",
      "aggregate_processed_used": ".../aggregated/processed_results.json",
      "workflow_error_used": ""
    }
  },
  "function_config": {
    "model_type": "open_access"
  }
}
```

Result file lookup order for initiator data:

1. `initiator/raw_results.json`
2. `initiator/results.json`
3. `client/*/error.json`
4. `local/local_results.json`
5. `local/error.json`

Aggregated data lookup:

| Output | Path |
| --- | --- |
| Aggregate raw/standard results | `aggregated/raw_results.json`, then `aggregated/results.json` |
| Aggregate processed results | `aggregated/processed_results.json` |
| Workflow-level error | `error.json` at workflow directory level |

When a file is missing, unreadable, empty, or invalid JSON, the relevant response field becomes an object with an `error` string instead of raising immediately.

Error behavior:

| Case | Response |
| --- | --- |
| Missing `nvflare_job_id` | HTTP 400, `{"error":"nvflare_job_id is required."}` |
| `nvflare_job_id` outside `[A-Za-z0-9_-]+` | HTTP 400, `{"error":"Invalid nvflare_job_id."}` |
| Missing `function` | HTTP 400, `{"error":"function is required."}` |
| Missing `workflow_id` | HTTP 400, `{"error":"workflow_id is required."}` |
| Unsupported function | HTTP 400, `{"error":"Unsupported function '<name>'"}` |
| Unexpected retriever exception | HTTP 500, `{"error":"Failed to fetch workflow data: [...]"}` |
| Taskflow report generation failure | No effect on the response. The call is wrapped in `try`/`except: pass` and `generate_report_for_job()` returns `None` instead of raising. |

The `nvflare_job_id` charset check exists because the value is used as a filesystem path component during result lookup. `NVFlareJobsDataRetriever.__init__` enforces the same rule and raises `ValueError` when it fails.

## Function Config Endpoint

Endpoint:

```text
POST /jobs/function/config
```

Request example:

```json
{
  "nvflare_job_id": "nvflare-job-id",
  "function": "stat_analytics",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Response shape:

```json
{
  "function_config": {
    "model_type": "open_access"
  }
}
```

This endpoint uses the same validation rules as `/jobs/results`, but returns only the function config for the requested workflow.

## Result Mapping Endpoint

Endpoint:

```text
POST /jobs/results/mapping
```

Request example:

```json
{
  "nvflare_job_id": "nvflare-job-id",
  "function": "stat_analytics"
}
```

Behavior:

- Converts `function` with `SupportedFunction.from_name()`.
- Lists workflow directories under the job/function computation type.
- Reads `profile_summary.json` from the job root when available.

Response shape:

```json
{
  "workflow_dirs": [
    "workflow_stat_analytics__cox_lasso",
    "workflow_stat_analytics__logistic_reg"
  ],
  "profile_summary": {}
}
```

If `profile_summary.json` is missing or unreadable, `profile_summary` is omitted.

## Result Filesystem Paths

`NVFlareJobsDataRetriever` determines result paths differently by environment.

### Local mode

Local mode uses `EnvironmentProvider.get_env() == Environment.LOCAL` and reads result files directly from disk.

Root path resolution:

1. If `DUALITY_NVFLARE_JOB_SAVE_LOCATION` is set, use it.
2. Otherwise use `DUALITY_NVFLARE_WORKSPACE`, defaulting to `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00`.
3. Append `DUALITY_NVFLARE_HOST` and `job-results`.

Final shape:

```text
<jobs-root>/<nvflare_job_id>/<computation_type>/<workflow_id>/...
```

### Non-local mode

Non-local mode uses `SSHConnectionProvider` and `NVFlareProvisionProvider.get_nvflare_instance()`. The base path is:

```text
<nvflare_provision.client_to_server_job_save_location>/<nvflare_job_id>/<computation_type>/<workflow_id>/...
```

The retriever shells out with commands such as `cat <remote_path>`, `find <client_dir> -mindepth 1 -maxdepth 1 -type d`, and `ls -1 <dir>`.

## Profiling and Trace Artifacts

Profiling output is file-based and lives in the NVFlare job-results tree rather than in MySQL.

### Runtime profiler output

`apis/profiler.py` runs inside the NVFlare job as an `FLComponent` on the server and on each client. It records per-workflow, per-round runtime and communication metrics plus system metrics, and at run end writes two files per party:

| File | Content |
| --- | --- |
| `profile_summary.json` | Accumulated per-workflow/per-round durations, payload sizes, and system metrics for that party. Consumed by the `task_profile_consolidate` workflow; the collected copy at the job root is what `/jobs/results/mapping` returns. |
| `trace.jsonl` | One JSON record per key lifecycle event, written beside `profile_summary.json`. |

Each `trace.jsonl` record carries `seq`, `ts_wall`, `ts_mono`, `kind`, `event`, `role`, `site`, `workflow`, `round`, `task_id`, `task_name`, `corr_id`, `peer`, and `meta`. The `kind` values are stable internal names mapped from NVFlare event types by the profiler's `_EVENT_KIND` table, so downstream tooling does not depend on raw NVFlare event strings. Traced kinds include `run_start`, `run_end`, `workflow_start`, `round_start`, `round_done`, the client lifecycle (`pull_start`, `task_recv`, `compute_end`, `send_start`, `send_end`), and the server lifecycle (`dispatch_start`, `dispatch_end`, `result_recv`, `submission_done`, `agg_start`, `agg_end`).

The profiler also writes a copy of each party's trace to a shared sink so host-side tooling can find all parties in one place:

| Variable | Default | Behavior |
| --- | --- | --- |
| `DUALITY_TRACE_SINK_DIR` | `/job-results` | Sink root. The copy is written to `<sink>/traces/<nvflare_job_id>/<site>/trace.jsonl`. The copy is skipped when the sink directory does not exist. |
| `DUALITY_HOST_UID` | None | When set and the process is running as root, written trace/report directories are recursively chowned back to this uid so the host can delete or regenerate them. |
| `DUALITY_HOST_GID` | Falls back to `DUALITY_HOST_UID` | Group used by the same chown behavior. |

`apis/trace_filter.py` registers `TraceCorrelationFilter` in the server's `task_data_filters`. On each outbound task it stamps a correlation id onto the `Shareable` header `__duality_trace_corr__` and appends a matching `dispatch_msg` record to `trace_filter.jsonl` beside the server's `trace.jsonl`. The shared correlation id lets server dispatch be paired exactly with client receipt instead of by `(workflow, round)` timing. The filter is a pass-through that swallows every error, so it cannot affect the federated computation.

### Host-side taskflow report

`taskflow_report.py` is a post-run, host-side renderer. It does no work inside the NVFlare containers. `generate_report_for_job()` is invoked as a background side effect of `POST /jobs/results`.

Collection roots, in order:

1. `job_save_location`, defaulting to `DUALITY_NVFLARE_JOB_SAVE_LOCATION`, which holds the collected leader/per-site traces.
2. `workspace_root`, defaulting to `DUALITY_NVFLARE_WORKSPACE`, which holds the server trace and any co-located client traces.

It matches any `trace.jsonl` or `trace_filter.jsonl` under a `job-results` tree whose path contains the job id as a component, deduplicating by resolved real path, then writes to:

```text
<DUALITY_NVFLARE_JOB_SAVE_LOCATION>/<nvflare_job_id>/taskflow/
```

Artifacts written into that directory:

| File | Content |
| --- | --- |
| `taskflow.perfetto.json` | Chrome Trace Event format. Open in `https://ui.perfetto.dev` or `chrome://tracing`. |
| `taskflow.seq.mmd` | Mermaid `sequenceDiagram` of correlated messages. |
| `taskflow.lamport.dot` | Graphviz causal/space-time graph. |
| `taskflow.rounds.json`, `taskflow.rounds.txt` | Per-round straggler and RTT decomposition. |
| `taskflow.timeline.svg` | Time-based swimlane. Best-effort; skipped with a note when matplotlib is unavailable. |
| `index.json`, `index.md` | Event/lane/span/edge counts, correlation split between id-matched and fallback edges, causal depth, straggler wait totals, party list, and the artifact list. |

Generation behavior:

| Case | Behavior |
| --- | --- |
| `index.json` or `.no-trace` already present in the output directory | Skipped, unless the caller passes `force=True`. |
| No trace files found for the job | Writes a `.no-trace` marker so later result fetches do not re-scan the workspace tree, and returns `None`. |
| Non id-safe job id, no readable roots, or no job save location | Returns `None` without writing. |
| Any exception during collection or rendering | Swallowed; returns `None`. Report generation never affects results delivery. |

## Route-Level Logging Patterns

### `ClientRoutes.py`

Notable stdout messages include:

- raw `/clients/connection/status` payload
- resolved username
- connection snapshot returned by `NVFlareClientSnapshot`
- participation function sanitization decisions
- resolved `filter_id`
- participation rows fetched from database
- participation map built from database rows
- updated client entries
- participation manager close message
- bad non-local password received for participation submit
- missing required field messages
- invalid confirmation string
- participation persistence success/failure
- traceback lines for client status and participation exceptions

### `FilterRoutes.py`

Notable stdout/logging messages include:

- `fetch_single_filter` called
- missing `filter_id`
- payload received for single filter lookup
- retrieved single filter payload
- `fetch_filters` called
- number of filters retrieved
- exception logging for filter lookup failures

Several messages are prefixed `NVFlareRoutes` even though they are emitted from `FilterRoutes.py`; this is current behavior.

### `FunctionRoutes.py`

This route logs:

- `fetch_supported_functions` called
- request body received
- number of supported functions retrieved
- exceptions while fetching supported functions

### `JobRunnerRoutes.py`

Notable stdout messages include:

- websocket connection attempt and connection-state messages
- websocket disconnect messages
- websocket acknowledgement timeout messages
- API Gateway websocket acknowledgement timeout messages
- API Gateway connection-gone messages
- API Gateway client errors
- status websocket stream exceptions
- `/jobs/status` exception tracebacks

### `NVFlareRoutes.py`

Notable stdout/logging messages include:

- bad `$pw` on non-local progress callback
- `/nvflare/job_history` called
- number of job history rows retrieved
- job history exceptions
- `submit_nvflare_job` request body
- missing filters
- received filter payload
- participation settings submitted with the job
- enqueued backend job ID
- crypto audit request received
- bad crypto audit `$pw`
- missing crypto audit fields
- crypto audit persistence success/failure

### `ProjectRoutes.py`

Project routes log datasource and query-related failures through JSON error responses and traceback output where exceptions are caught. `/projects/fhir/source` is also a first-check endpoint for source metadata because it resolves user/project/source type, datasource group state, and optional FHIR query execution.

## Request/Response Error Style

The backend does not use one uniform error envelope. Current patterns include:

| Pattern | Examples |
| --- | --- |
| `{"status": "FAILURE", "error": "..."}` | Project/job history/filter validation failures. |
| `{"status": "Please provide <field>"}` | Missing fields in participation and crypto audit submit endpoints. |
| `{"error": "..."}` | Job info/result/config/mapping validation failures. |
| `{"status": "Exception occurred ...", "log": [...]}` | Participation and crypto audit exception paths. |
| `{"job_id": ..., "status": "Exception occured ...", "log": [...]}` | `/jobs/status` exception path. |
| HTTP 401 with `Unauthorized` | Non-local password failures for callback-style endpoints. |

Many exception responses include `traceback.format_exc().splitlines()`. This is useful during development but should be treated as sensitive in hardened deployments because stack traces can expose file paths and implementation details.

## How to Identify Job IDs

The backend uses two important job identifiers.

| Identifier | Source | Where Stored | Where Used |
| --- | --- | --- | --- |
| Backend job runner UUID | Returned from `/nvflare/jobs/submit` as `job_id` | `job_runner_log.uuid`, `nvflare_jobs.job_runner_id` | `/jobs/status`, websocket status routes, `/jobs/info` lookup by `job_runner_id`. |
| NVFlare-assigned job ID | Returned by NVFlare admin job submission and saved later | `nvflare_jobs.nvflare_assigned_id` | `/jobs/results`, `/jobs/function/config`, `/jobs/results/mapping`, progress callback lookup, history display. |
| Internal MySQL job ID | Auto-increment ID from `nvflare_jobs.id` | `nvflare_jobs.id` and child tables | Job history joins, datasource/workflow logs, `/jobs/info` lookup by `id`. |

First checks:

1. After job submission, capture the backend `job_id` from `/nvflare/jobs/submit`.
2. Use `/jobs/status` with that value to inspect `job_runner_log`.
3. Once available, inspect `referenced_by` in `/jobs/status`; this lists the NVFlare-assigned job IDs linked to the backend job runner UUID.
4. Use `/jobs/info` with `job_runner_id` to retrieve the internal MySQL row and NVFlare-assigned ID.
5. Use `/jobs/results/mapping` with the NVFlare-assigned ID to list workflow directories.
6. Use `/jobs/results` with NVFlare-assigned ID, function, and workflow ID to retrieve actual outputs.

## Inspecting Generated Job Artifacts

Use `nvflare_jobs.job_path` as the starting point for staged artifacts. Use `nvflare_jobs.output_path` or `NVFlareJobsDataRetriever` path rules for outputs.

Generated job artifact checks:

1. Confirm a row exists in `nvflare_jobs` for the backend `job_runner_id`.
2. Check `job_path` for the staged NVFlare job directory.
3. Confirm generated config files exist under the staged job's `app_client/config` and `app_server/config` paths.
4. Confirm runtime/custom files exist under `app_client/custom` and `app_server/custom`.
5. For biomarker workflows, confirm `app_client/custom/model_file_sources.json` was staged when model files are required, and confirm `workflow_model_upload__<model_key>` wrote runtime artifacts under `app_server/custom` after the job started.
6. Check `output_path` after the job has been submitted and result directories are created.
7. Under the output path, inspect `<computation_type>/<workflow_id>/initiator`, `aggregated`, `local`, `client`, and workflow-level `error.json` locations.

Result endpoint file checks:

| Result field | First paths to inspect |
| --- | --- |
| `initiator_results` | `initiator/raw_results.json`, `initiator/results.json`, client error files, local fallback files. |
| `aggregate_results` | `aggregated/raw_results.json`, `aggregated/results.json`. |
| `aggregate_processed_results` | `aggregated/processed_results.json`. |
| `workflow_error` | `<workflow_id>/error.json`. |
| `profile_summary` | `<nvflare_job_id>/profile_summary.json`. |

Trace and taskflow artifact checks:

| Artifact | First paths to inspect |
| --- | --- |
| Per-party event trace | `trace.jsonl` beside each `profile_summary.json`, and `<trace sink>/traces/<nvflare_job_id>/<site>/trace.jsonl`. |
| Server dispatch correlation records | `trace_filter.jsonl` beside the server's `trace.jsonl`. |
| Rendered taskflow report | `<job save location>/<nvflare_job_id>/taskflow/index.json` and `index.md`. |
| Known trace-less job | `<job save location>/<nvflare_job_id>/taskflow/.no-trace`. |

## Troubleshooting Checklist

### Backend will not start

First checks:

1. Confirm dependencies install from `requirements.txt` and `nvflare` installs in the container.
2. Confirm environment variables required by `EnvironmentProvider`, MySQL config, AWS config, SSH config, and NVFlare path config are present.
3. Confirm the backend can import `app.main:app`.
4. Confirm MySQL is reachable because startup code initializes database/schema/default data through `MySQLConnectionProvider`.
5. Check stdout/stderr for Python import errors, MySQL connection errors, or missing package errors.
6. Use `GET /health` after startup to confirm FastAPI is responding.

### MySQL connection failure

First checks:

1. Confirm local `.env` or deployed secret/config values for MySQL host, port, username, password, and database.
2. Confirm the MySQL server is reachable from the backend container/network.
3. Confirm database user permissions allow database creation, table creation, inserts, updates, and index/alter checks.
4. Check stdout/stderr for connection provider tracebacks.
5. Confirm AWS Secrets Manager access if running non-local and config is expected to come from secrets.

Symptoms:

- Backend startup fails during schema initialization.
- `/projects/list`, `/functions/supported_functions`, `/filters/fetch_filters`, or `/jobs/status` returns traceback-based errors.
- `JobStatusWriter.log()` prints database exceptions and status does not appear in `/jobs/status`.

### Database schema or default data missing

First checks:

1. Confirm startup completed without MySQL initialization errors.
2. Check that `defined_roles`, `defined_projects`, `defined_functions`, `defined_fhir_filters`, `threshold_configs`, `nvflare_clients`, datasource groups, workflow groups, and user FHIR source rows were seeded.
3. Confirm `CREATE TABLE IF NOT EXISTS` statements are running against the expected database.
4. Confirm any startup ALTER/index checks completed.
5. Recheck the runtime database name; stale or wrong database selection is a common cause of empty project/function/filter responses.

Symptoms:

- `/projects/list` returns empty or missing projects.
- `/functions/supported_functions` returns no functions.
- Filter lookup cannot resolve a filter ID.
- Job submission fails because filters/functions/configs cannot be resolved.

### Project list empty

First checks:

1. Confirm `defined_projects` has rows.
2. Confirm backend is pointing to the expected MySQL database.
3. Check `/projects/list` response and backend stdout.
4. Confirm `ProjectsManager.get_project_list()` can query datasource group summaries without join errors.

### Datasource source missing or wrong

First checks:

1. Confirm `/projects/fhir/source` request includes the expected `username`, `project_id`, and optional `datasource_group`.
2. Confirm the username exists in `users`.
3. Confirm `users_fhir_source_by_project` has a row for that user/project/group combination.
4. Confirm `defined_project_datasource_groups` contains the requested group when group-specific sources are used.
5. Check whether the returned source ends with `.json`; this determines `source_type = json` rather than `fhir_server`.
6. If `execute_query` is true and the source is a FHIR server, check FHIR server availability separately.

Symptoms:

- Frontend cannot load local JSON or FHIR server source metadata.
- Source type does not match expected local/server behavior.
- Datasource group display is missing or falls back unexpectedly.

### Filters or functions not returned

First checks:

1. Confirm `defined_functions` has supported function rows.
2. Confirm project/function restrictions allow the expected functions.
3. Confirm `defined_fhir_filters` has filters for the project.
4. Confirm `defined_fhir_filter_conditions` has conditions linked to the filter ID.
5. Check stdout messages from `FilterRoutes.py` and `FunctionRoutes.py`.
6. Confirm request `project_id` parses as an integer where required.

Common response strings:

| Response | Likely cause |
| --- | --- |
| `filter_id must be an integer` | `/filters/fetch_single_filter` received a non-integer ID. |
| `project_id is required` | Filter lookup request omitted or supplied invalid `project_id`. |
| `Failed to fetch filters` | Manager/database exception; check stdout traceback. |

### Job submission fails before queueing

First checks:

1. Confirm `/nvflare/jobs/submit` payload includes `filters`.
2. Confirm `project_id` parses as an integer.
3. Confirm `datasource_group`, when provided, parses as an integer.
4. Confirm `functions_map` is present and is an object.
5. Confirm `functions_map` contains at least one non-empty function key.
6. Confirm `workflow_group_data`, when provided, is an object.
7. Confirm `non_contributing_clients` and `exclude_analyzing_clients`, when provided, are arrays of strings.
8. Confirm `threshold_config`, when provided, has a valid method and integer threshold.

Common response strings:

| Response | Cause |
| --- | --- |
| `Submission must include filters` | Missing/empty `filters`. |
| `project_id is required` | Missing or invalid `project_id`. |
| `datasource_group must be an integer when provided` | Non-integer datasource group value. |
| `Please provide functions` | Missing `functions_map`. |
| `functions must be an object mapping function_id -> { args }` | `functions_map` is not an object. |
| `Invalid functions payload` | `_normalize_functions_map()` failed. |
| `functions must contain at least one function` | Normalized map has no usable function keys. |
| `workflow_group_data must be an object when provided` | `workflow_group_data` was supplied as another type. |
| `Invalid threshold method` | Threshold method is not accepted by `ThresholdMethod`. |
| `Invalid threshold value` | Threshold value cannot be parsed as integer. |

### Job stays `QUEUED`

A `QUEUED` response from `/jobs/status` means no `job_runner_log` row exists yet for the backend job UUID.

First checks:

1. Confirm `/nvflare/jobs/submit` returned the job ID being polled.
2. Check backend stdout for `submit_nvflare_job enqueued job <job_id>`.
3. Check whether `JobRunnerService` background execution started.
4. Check for exceptions immediately after request submission in container logs.
5. Check whether the background job has permission/connectivity to MySQL; without status writes, `/jobs/status` continues to show `QUEUED`.

### Job stages but does not run

First checks:

1. Inspect `/jobs/status` log lines for staging/upload/defining/broadcast statuses.
2. Check `nvflare_jobs.job_path` and confirm the staged job directory exists.
3. Check backend stdout from stager/runner/uploader code.
4. Confirm admin kit paths are valid.
5. Confirm NVFlare server workspace paths are valid.
6. Confirm SSH is available in non-local mode when required.
7. Confirm generated job config references valid clients, workflows, and custom code.

### Job uploads or broadcasts but status does not complete

First checks:

1. Check `nvflare_jobs.nvflare_assigned_id`; if it is missing, runner submission likely did not complete.
2. Check `NVFlareJobMonitor` behavior by looking for repeated admin `list_jobs` activity and timeout errors.
3. Confirm the NVFlare admin command `list_jobs <job_id>` returns a row for the target job.
4. Confirm the parsed row status begins with `FINISHED:` when completed.
5. Check whether admin command calls are returning non-zero exit codes; the monitor treats these as transient and retries silently until timeout.
6. Check runtime progress callbacks from clients through `/nvflare/client/emit_progress`.

### Status remains running but results exist

First checks:

1. Use `/jobs/results/mapping` with the NVFlare-assigned ID to see whether workflow directories exist.
2. Use `/jobs/results` for each workflow to confirm result files are readable.
3. Check whether `NVFlareJobMonitor` parsed a `FINISHED:` status from `list_jobs`.
4. Check whether `nvflare_jobs.status`, `submit_time`, and `run_duration` updated.
5. If result files exist but monitor did not finish, verify the admin kit output format still matches the row regex expected by `NVFlareJobMonitor`.

### Websocket status does not update

First checks for direct websocket:

1. Confirm the frontend uses `/jobs/status/ws/{job_id}` or `/jobs/status/ws/local/{job_id}` with the backend job runner UUID.
2. Confirm the frontend sends ack messages with the exact `message_id` received.
3. Check for close code `1008`, which indicates ack timeout.
4. Check backend stdout for `websocket ack timeout` or `job_status_ws hit exception`.
5. Confirm `/jobs/status` polling works for the same job ID; if polling has no updates, websocket will not either.

First checks for API Gateway websocket:

1. Confirm `/jobs/status/ws/connect` receives both `connectionId` and `job_id`.
2. Confirm the backend can create an `apigatewaymanagementapi` client for the derived management endpoint.
3. Confirm API Gateway route events provide `domainName` and `stage`, or that the hardcoded fallback endpoint is correct.
4. Confirm the frontend/client sends ack messages back through `/jobs/status/ws/ack` with the correct `connectionId` and `message_id`.
5. Check for `GoneException`, ack timeout, or API Gateway client error messages in stdout.
6. Remember that connection state is process-local and is lost on backend restart.

### Results missing

First checks:

1. Confirm you are using the NVFlare-assigned job ID, not the backend job runner UUID, for `/jobs/results`.
2. Confirm `function` is accepted by `SupportedFunction`.
3. Confirm `workflow_id` matches an existing workflow directory. Use `/jobs/results/mapping` to list workflow directories.
4. Confirm local/non-local mode points to the expected result root.
5. Inspect the result file lookup order documented above.
6. Check for invalid JSON in result files; the retriever returns `Invalid JSON in <path>: <error>`.
7. Check for missing aggregate files; the retriever returns per-field `error` objects instead of a full endpoint failure when files are missing.
8. Check SSH connectivity in non-local mode.

Common error strings:

| Error | Likely cause |
| --- | --- |
| `Unreadable file: <path> (not found)` | Expected result file is missing. |
| `Invalid JSON in <path>` | Result file exists but cannot be parsed as JSON. |
| `Empty file: <path>` | Remote file exists but is empty. |
| `No site folders found under <client_dir>` | Client output directory is missing or empty. |
| `SSH provider unavailable in local mode` | Remote read method was invoked while configured for local mode. |
| `No computation_type mapping for function <name>` | Function is not mapped in `FUNCTION_TO_COMPUTATION_TYPE`. |

### Participation status incorrect

First checks:

1. Confirm `/clients/connection/status` returns the expected client names from `NVFlareClientSnapshot`.
2. Confirm `/clients/participation/status` uses the same function map, filters, threshold, and role-selection exclusions as job submission.
3. Confirm filter resolution produced the expected `filter_id`.
4. Confirm `nvflare_client_participation` contains rows for the client/filter/threshold combination.
5. Confirm `nvflare_client_participation_functions` and `nvflare_client_participation_function_configs` match the requested function/config set.
6. Confirm contributing/analyzing flags match `non_contributing_clients` and `exclude_analyzing_clients`; rows with mismatched role flags are intentionally ignored.
7. Check stdout for the canonical function map, participation rows fetched, and participation map built.

Common response strings:

| Response | Cause |
| --- | --- |
| `project_id is required` | Participation status request included `participation_status` but omitted/invalid `project_id`. |
| `Confirmation must be ACCEPT or REJECT` | Participation submit received a confirmation outside the enum. |
| `Failed to persist confirmation.` | `ParticipationManager.record_participation()` returned no ID. |
| `Invalid threshold_config payload` | Threshold config in participation submit could not be parsed. |

### NVFlare clients offline or stale

First checks:

1. Call `/clients/connection/status` with the expected username.
2. Check stdout for the raw payload, resolved username, and returned snapshot.
3. Verify `NVFlareClientSnapshot` can access the NVFlare server/admin context it depends on.
4. Verify default `nvflare_clients` rows exist and client names match the NVFlare site names.
5. Confirm server/client clock and heartbeat/check-in assumptions used by snapshot logic.
6. Confirm project-specific exclusions are not hiding expected clients where applicable.

### Encrypted workflow config or audit missing

First checks:

1. Confirm the selected function config includes encrypted workflow settings where expected.
2. Confirm OpenFHE runtime files were packaged into the generated job.
3. Confirm encrypted biomarker workflows include `workflow_model_upload__<model_key>` before model-consuming workflows, and confirm the initiator/leader site can read the saved User Settings model-file paths.
4. Confirm `/nvflare/jobs/audit/submit` is called by runtime code with the required fields.
5. In non-local environments, confirm `$pw` matches the expected MySQL password check.
6. Check `nvflare_job_crypto_audit` for a row where `nvflare_job_id` equals `nvflare_jobs.nvflare_assigned_id`.
7. Check `/nvflare/jobs/history`; it attaches `crypto_audit_record` when an audit row exists.

Common crypto audit response strings:

| Response | Cause |
| --- | --- |
| `Please provide <field>` | Required audit field is missing/empty. |
| `Invalid crypto audit payload` | Numeric/string parsing failed. |
| `Failed to persist crypto audit record.` | Audit manager returned no inserted/updated ID. |
| `Exception occurred while recording crypto audit` | Unexpected exception while recording audit. |

## Operational First-Check SQL

These queries are useful during local troubleshooting. Adjust database/schema names as needed.

Find the current job status row:

```sql
SELECT uuid, status, update_date, log
FROM job_runner_log
WHERE uuid = '<backend-job-runner-uuid>';
```

Find the NVFlare job linked to a backend job runner UUID:

```sql
SELECT id, project_id, nvflare_assigned_id, status, job_path, output_path, job_runner_id,
       submit_time, run_duration, create_date, update_date
FROM nvflare_jobs
WHERE job_runner_id = '<backend-job-runner-uuid>'
ORDER BY id DESC;
```

Find functions linked to an NVFlare job row:

```sql
SELECT j.id, j.nvflare_assigned_id, f.name
FROM nvflare_jobs j
JOIN nvflare_job_functions jf ON jf.job_id = j.id
JOIN defined_functions f ON f.id = jf.function_id
WHERE j.id = <internal-nvflare-job-id>
ORDER BY f.name;
```

Find workflow IDs/config sets linked to a job:

```sql
SELECT j.id, j.nvflare_assigned_id, jfc.workflow_id, f.name, cs.id AS config_set_id, cs.label
FROM nvflare_jobs j
JOIN nvflare_job_function_configs jfc ON jfc.job_id = j.id
JOIN defined_function_config_sets cs ON cs.id = jfc.function_config_id
JOIN defined_functions f ON f.id = cs.function_id
WHERE j.id = <internal-nvflare-job-id>
ORDER BY jfc.workflow_id;
```

Find datasource context for a job:

```sql
SELECT jl.*, dg.group_name
FROM nvflare_job_datasource_log jl
LEFT JOIN defined_project_datasource_groups dg ON dg.id = jl.datasource_group_id
WHERE jl.nvflare_job_id = <internal-nvflare-job-id>;
```

Find workflow group selections for a job:

```sql
SELECT wg.group_key, wg.group_label, opt.option_key, opt.option_label, opt.option_value
FROM nvflare_job_workflow_groups jwg
JOIN defined_project_workflow_groups wg ON wg.id = jwg.workflow_group_id
LEFT JOIN nvflare_job_workflow_group_options jwgo ON jwgo.nvflare_job_workflow_group_id = jwg.id
LEFT JOIN defined_project_workflow_group_options opt ON opt.id = jwgo.workflow_group_option_id
WHERE jwg.nvflare_job_id = <internal-nvflare-job-id>
ORDER BY wg.page_order, opt.option_order;
```

Find crypto audit record:

```sql
SELECT *
FROM nvflare_job_crypto_audit
WHERE nvflare_job_id = '<nvflare-assigned-job-id>';
```

## Current Observability Gaps

The current backend provides enough visibility for local/work-in-progress debugging, but several areas are not hardened yet:

- No centralized structured logger is configured.
- No request correlation ID middleware is present.
- Many endpoints return raw tracebacks in JSON responses.
- Several route files use `print()` rather than a configured logger.
- Some route log prefixes are inaccurate, such as `FilterRoutes.py` messages that say `NVFlareRoutes`.
- API Gateway websocket connection state is in memory only.
- Websocket terminal-state detection only stops on `DONE` and `FAILURE`, while other error-like statuses may still require polling or manual inspection.
- `NVFlareJobMonitor` silently retries non-zero admin command results until timeout, so admin command failures may require direct container/admin-kit log inspection.
- `job_runner_log` stores a growing `MEDIUMTEXT` log per job; there is no log rotation or per-line table.
- Taskflow report generation is deliberately silent: both the route call and `generate_report_for_job()` swallow exceptions without logging, so a missing `taskflow/` directory has to be diagnosed by checking for trace files and the `.no-trace` marker directly.
- The `STOP` kill-switch behavior terminates the whole process/container through `os._exit(0)`.

## Practical Debugging Sequence

For a failed or stuck analytics job, use this sequence:

1. Start with the backend job runner UUID returned by `/nvflare/jobs/submit`.
2. Call `/jobs/status` and inspect `status`, `log`, `last_update`, `functions`, and `referenced_by`.
3. Check container stdout/stderr around the submit time for route/service/stager exceptions.
4. Use `/jobs/info` with `job_runner_id` to find the internal MySQL job ID, NVFlare-assigned ID, staged job path, output path, and function list.
5. Query `nvflare_jobs` directly if `/jobs/info` fails.
6. If no NVFlare-assigned ID exists, focus on staging/upload/run submission.
7. If an NVFlare-assigned ID exists but status is not terminal, inspect NVFlare admin `list_jobs <id>` behavior and monitor timeout messages.
8. If status is terminal but results are missing, call `/jobs/results/mapping` to list workflow directories.
9. For each workflow directory, call `/jobs/results` with the NVFlare-assigned ID, function, and workflow ID.
10. Inspect result file error strings to determine whether the missing piece is initiator output, aggregate output, processed output, workflow-level error output, local fallback output, or SSH access.
11. For encrypted jobs, also check `/nvflare/jobs/history` for `crypto_audit_record` and inspect `nvflare_job_crypto_audit` directly.
12. For participation-related issues, call `/clients/connection/status`, then `/clients/participation/status`, then inspect `nvflare_client_participation` and child function/config tables.
