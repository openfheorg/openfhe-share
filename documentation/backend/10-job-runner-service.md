# Job Runner Service

## Files Covered

| File | Role |
| --- | --- |
| `app/core/job_runner/JobRunnerService.py` | Singleton queue service that accepts backend job requests, creates the job runner status writer, records the initial queued state, and dispatches queued jobs on a daemon worker thread. |
| `app/core/job_runner/job_tasks/NVFlareJobTask.py` | End-to-end task object for a standard NVFlare analysis job. It saves filters, creates the NVFlare job database entry, confirms participation, stages the job, submits it through NVFlare admin tooling, monitors it, and writes final status. |
| `app/core/job_runner/job_tasks/NVFlareParticipationJobTask.py` | Participation-confirmation task used inside the standard job flow before the analysis job is staged. It records pending participation, broadcasts the participation job when needed, waits for responses, and returns the accepted client list. |
| `app/api/routes/NVFlareRoutes.py` | Defines `POST /nvflare/jobs/submit`, validates the submission payload, normalizes functions, resolves threshold configuration, and queues the job through `JobRunnerService`. |
| `app/api/routes/ClientRoutes.py` | Defines participation status and participation submission endpoints. Participation responses are persisted through `ParticipationManager`; the standard job flow later reads those records through `NVFlareParticipationJobTask`. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Builds the NVFlare job folder from templates and submitted function/client/filter/workflow context. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobRunner.py` | Submits a staged job through NVFlare admin tooling and returns the NVFlare-assigned job ID and output path. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobMonitor.py` | Polls NVFlare for server-side job completion and returns the final NVFlare status. |
| `app/core/mysql/job_tracking/JobStatusWriter.py` | Persists job runner log and status updates in `job_runner_log`. |
| `app/core/mysql/managers/NVFlareJobsManager.py` | Creates and updates `nvflare_jobs` records, job/function links, datasource logs, workflow group logs, NVFlare-assigned IDs, job paths, output paths, and NVFlare statuses. |
| `app/core/mysql/managers/FiltersManager.py` | Saves or resolves the submitted filter set before job creation. |
| `app/core/mysql/managers/ThresholdManager.py` | Resolves or creates threshold configuration records when threshold settings are submitted. |
| `app/core/mysql/managers/ParticipationManager.py` | Reads and writes participation decisions, pending participation records, user/client auto-accept mappings, and accepted-client CSV output. |

## Service Role

`JobRunnerService.py` is the backend queue and dispatch layer for NVFlare analysis jobs.

The service does not directly stage, upload, submit, or monitor NVFlare jobs. Instead, it performs these responsibilities:

1. Maintains a singleton service instance for the running backend process.
2. Creates a FIFO in-memory `queue.Queue` for requested jobs.
3. Creates a daemon worker thread named `JobRunnerService`.
4. Creates a UUID job runner ID for each submitted job.
5. Creates a `JobStatusWriter` for the job runner ID.
6. Logs the initial `Queued` state.
7. Stores the `JobStatusWriter` in an in-memory `job_registry` keyed by job runner ID.
8. Pushes the job arguments onto the queue.
9. Has the worker thread consume jobs serially and execute `NVFlareJobTask.run_nvflare_job()`.

The service intentionally runs queued jobs one at a time on the worker thread. The class comment describes the queue as executing tasks sequentially with no parallel running tasks.

## Singleton and Threading Behavior

`JobRunnerService.get_instance()` uses a class-level lock and double-check pattern to create one `JobRunnerService` instance per backend process.

The constructor initializes:

| Field | Type/Value | Purpose |
| --- | --- | --- |
| `task_queue` | `queue.Queue()` | FIFO queue of submitted job argument tuples. |
| `job_registry` | `Dict[str, JobStatusWriter]` | In-memory lookup of job runner ID to status writer. |
| `thread` | `threading.Thread(target=self._worker, daemon=True, name="JobRunnerService")` | Background daemon thread that consumes queued jobs. |

The worker thread starts immediately when the singleton is created.

Because `job_registry` is process-local memory, it is useful only within the currently running backend process. Persisted status and logs are stored through `JobStatusWriter` in MySQL and are the authoritative state for status endpoints.

## Public Methods

| Method | Purpose |
| --- | --- |
| `get_instance()` | Returns the singleton `JobRunnerService` instance, creating it if needed. |
| `request_job_run(...)` | Validates that `functions_map` is a non-empty dictionary and queues a standard NVFlare job. Returns the generated job runner UUID. |
| `get_status_writer(job_id)` | Returns the in-memory `JobStatusWriter` for a job runner ID if the current process still has it registered. |

## `request_job_run(...)` Arguments

`request_job_run()` accepts the normalized job context that has already been parsed and validated by the route layer.

| Argument | Type | Source | Use |
| --- | --- | --- | --- |
| `project_id` | integer-like | `POST /nvflare/jobs/submit` body `project_id` | Stored on `NVFlareJobTask`, passed to managers/stager, and required when creating the `nvflare_jobs` record. |
| `functions_map` | `Dict[str, Dict[str, str]]` in type hints; actual normalized route output may contain lists of config dictionaries | Normalized from request `functions_map` by `_normalize_functions_map()` | Drives function links, job staging, participation matching, and workflow generation. |
| `filters` | request object/list/string depending frontend payload | Request body `filters` | Saved/resolved through `FiltersManager.save_or_get_filter_id()`. |
| `threshold` | `Threshold` or `None` | Request body `threshold_config`, resolved through `ThresholdManager.get_or_create()` | Linked to job creation and participation matching when provided. |
| `username` | `str` or `None` | Request body `submitter` | Used by participation flow for submitting-user auto-accept logic. |
| `datasource_group_id` | `int` or `None` | Request body `datasource_group` | Logged to `nvflare_job_datasource_log` and passed into staging. |
| `workflow_group_data` | `dict` or `None` | Request body `workflow_group_data` | Logged to `nvflare_job_workflow_groups` and passed into staging. |
| `non_contributing_clients` | `List[str]` | Request body `non_contributing_clients` | Stored on the job, passed into participation role recording, and passed into staging. |
| `exclude_analyzing_clients` | `List[str]` | Request body `exclude_analyzing_clients` | Stored on the job, passed into participation role recording, and passed into staging. |

`request_job_run()` raises `ValueError` if `functions_map` is not a non-empty dictionary. `_add_to_queue()` also validates `functions_map` and raises `TypeError` if it is not a non-empty dictionary.

## Job Submission Endpoint

The standard entrypoint is:

```text
POST /nvflare/jobs/submit
```

The route is implemented by `submit_nvflare_job()` in `app/api/routes/NVFlareRoutes.py`.

### Request Fields Used by the Route

| Field | Required | Validation/Normalization | Downstream Use |
| --- | --- | --- | --- |
| `filters` | Yes | Must be present/truthy. | Passed to `FiltersManager` in `NVFlareJobTask`. |
| `project_id` | Yes | Converted to `int`; invalid/missing returns `400`. | Passed to service/task/managers/stager. |
| `datasource_group` | No | Converted to `int` when present; invalid value returns `400`. | Logged and passed to staging. |
| `functions_map` | Yes | Must be an object; normalized by `_normalize_functions_map()`. Empty normalized function names return `400`. | Drives job creation, participation, and staging. |
| `workflow_group_data` | No | Must be an object when present; otherwise returns `400`. | Logged and passed to staging. |
| `non_contributing_clients` | No | Must be an array of strings when present; duplicate/blank entries are removed. | Stored on job and applied to participation/staging. |
| `exclude_analyzing_clients` | No | Must be an array of strings when present; duplicate/blank entries are removed. | Stored on job and applied to participation/staging. |
| `threshold_config` | No | If object, resolves method and integer threshold. Invalid method/value returns `400`. | `ThresholdManager.get_or_create()` returns the persisted `Threshold`. |
| `submitter` | No | Non-empty string is trimmed; otherwise treated as `None`. | Used for participation auto-accept lookup. |

### Function Normalization

`submit_nvflare_job()` calls `_normalize_functions_map()` from `FunctionsManager.py`.

That helper:

- Requires the top-level value to be a dictionary.
- Uppercases function IDs.
- Supports function values as either a single dictionary or a list of dictionaries.
- Converts provided argument values to strings, using an empty string for `None`.
- Backfills known default function properties from `FUNCTION_DEFAULT_PROPERTIES`.
- Clamps invalid `STANDARD_DEVIATION` `std_type` values back to the default.
- Returns a normalized map keyed by uppercase function ID.

### Threshold Resolution

When `threshold_config` is present and is an object, the route reads:

- `thresholdMethod` or `method`
- `threshold`

If no method is provided, the route defaults to `ThresholdMethod.PROTECTED`. The threshold value must convert to an integer. The route then creates a temporary `Threshold(id=None, method=method, threshold=threshold_value)` and persists or reuses it through `ThresholdManager.get_or_create()`.

### Successful Response

After the route queues the job, it returns immediately:

```json
{
  "job_id": "generated-job-runner-uuid",
  "status": "QUEUED"
}
```

The returned `job_id` is the backend job runner UUID, not the later NVFlare-assigned job ID. The initial queue state is also written to `job_runner_log` through `JobStatusWriter.log("Job queued.", status=JobRunnerStatus.QUEUED)`.

### Error Responses

Current route-level validation failures return `400` with simple JSON messages. Current cases include:

| Condition | Response |
| --- | --- |
| Missing/falsey `filters` | `{"status": "Submission must include filters"}` |
| Missing/invalid `project_id` | `{"status": "FAILURE", "error": "project_id is required"}` |
| Invalid `datasource_group` | `{"status": "FAILURE", "error": "datasource_group must be an integer when provided"}` |
| Missing `functions_map` | `{"status": "Please provide functions"}` |
| Non-object `functions_map` | `{"status": "functions must be an object mapping function_id -> { args }"}` |
| Function normalization exception | `{"status": "Invalid functions payload"}` |
| Empty normalized functions | `{"status": "functions must contain at least one function"}` |
| Non-object `workflow_group_data` | `{"status": "workflow_group_data must be an object when provided"}` |
| Invalid `non_contributing_clients` | `{"status": "non_contributing_clients must be an array of strings when provided"}` |
| Invalid `exclude_analyzing_clients` | `{"status": "exclude_analyzing_clients must be an array of strings when provided"}` |
| Invalid threshold method | `{"status": "Invalid threshold method"}` |
| Invalid threshold value | `{"status": "Invalid threshold value"}` |

There is no bearer-token enforcement in this route in the current code. The route has a `# Put behind bearer token` comment, but no implemented route-level authentication check.

## Queue Flow

The queue flow after route validation is:

1. `submit_nvflare_job()` calls `JobRunnerService.get_instance()`.
2. The singleton is created if it does not exist yet, starting the daemon worker thread.
3. The route calls `service.request_job_run(...)`.
4. `request_job_run()` verifies `functions_map` is a non-empty dictionary.
5. `_make_request()` creates a UUID job runner ID.
6. `_make_request()` creates `JobStatusWriter(job_id)`.
7. `JobStatusWriter.log("Job queued.", status=JobRunnerStatus.QUEUED)` inserts or updates `job_runner_log`.
8. `_make_request()` stores the writer in `job_registry[job_id]`.
9. `_add_to_queue()` pushes a tuple of job context values into `task_queue`.
10. The route returns `{"job_id": job_id, "status": "QUEUED"}`.
11. The background worker consumes the queued tuple.
12. The worker creates `NVFlareJobTask(...)` and calls `run_nvflare_job()`.
13. If an exception escapes the task, the worker prints the traceback and writes `JobRunnerService exception: ...` with status `Failure`.
14. The worker calls `task_queue.task_done()` in `finally`.

## Job Status Writer

`JobStatusWriter` is created before a queued job begins executing. It opens a MySQL connection and `DictCursor`, and it uses a `threading.Lock` to serialize writes for that job.

`log(log_message, status=None)`:

- Ignores empty log messages.
- Prepends a UTC ISO timestamp to the message.
- Checks whether the `job_runner_log` row for the UUID has status `STOP`.
- If the row is marked `STOP`, writes a stop message and calls `os._exit(0)`.
- Uses `INSERT ... ON DUPLICATE KEY UPDATE` to append log text to the existing row.
- Updates the current status column when a status is provided.
- Commits after each write.

This means `job_runner_log` is both the job-status table and the accumulated log stream for polling and websocket status endpoints.

## `NVFlareJobTask` Standard Job Flow

`NVFlareJobTask.run_nvflare_job()` performs the standard analysis job lifecycle.

### Constructor State

| Field | Source |
| --- | --- |
| `project_id` | Service queue tuple from route `project_id`. |
| `datasource_group_id` | Service queue tuple from route `datasource_group`. |
| `filters` | Service queue tuple from route `filters`. |
| `status_writer` | Created by `JobRunnerService`. |
| `functions_map` | Normalized function map from route. |
| `threshold` | Optional persisted/resolved `Threshold`. |
| `username` | Optional route `submitter`. |
| `workflow_group_data` | Optional route `workflow_group_data`. |
| `non_contributing_clients` | Optional normalized client-name list; defaults to empty list. |
| `exclude_analyzing_clients` | Optional normalized client-name list; defaults to empty list. |

### Runtime Sequence

1. Builds a comma-separated display string from sorted function names.
2. Logs `NVFlareJobTask: Job initiated for ...` with status `Processing`.
3. Creates `FiltersManager(project_id=..., filters=..., status_writer=...)`.
4. Calls `FiltersManager.save_or_get_filter_id()` and stores the resulting `filters_id`.
5. Closes `FiltersManager` with `complete()`.
6. Reads the runtime environment from `EnvironmentProvider.get_env()`.
7. In non-local environments, checks SSH connectivity through `SSHConnectionProvider.get_instance().run("hostname && uptime")` and logs the result.
8. Gets the NVFlare provision object from `NVFlareProvisionProvider().get_nvflare_instance()`.
9. Creates `NVFlareJobsManager(status_writer=..., project_id=...)`.
10. Calls `NVFlareJobsManager.establish_job_entry_id(...)` with the filter ID, functions map, threshold, and participation override lists.
11. Calls `NVFlareJobsManager.log_job_run_context(datasource_group_id=..., workflow_group_data=...)`.
12. Creates `NVFlareParticipationJobTask(...)` and calls `get_participation_client_list()`.
13. If no accepted participating clients are returned, logs `No participating clients found for this job!` with status `Failure` and returns without staging the analysis job.
14. Sets the NVFlare job status to `STAGING` through `NVFlareJobsManager.set_nvflare_job_status()`.
15. Logs `Begin staging ... job` with status `Defining NVFlare Job`.
16. Creates `NVFlareJobStager(...)` with project, function, client, filter, manager, threshold, datasource group, workflow group, and participation override context.
17. Calls `stage_job()` and stores the returned final job path through `set_nvflare_job_path()`.
18. Logs `Submitting job to server` with status `Broadcasting NVFlare Job`.
19. Creates `NVFlareJobRunner(...)` and calls `run_job()`.
20. Stores the NVFlare-assigned job ID through `set_nvflare_assigned_id()`.
21. Stores the NVFlare output path through `set_nvflare_output_path()`.
22. Creates `NVFlareJobMonitor(...)` with the manager, NVFlare-assigned job ID, and status writer.
23. Calls `wait_for_completion(poll_interval=10, timeout=600)`.
24. Logs final completion with status `DONE` unless the final NVFlare status is in `FAILURE_JOB_RUNNER_STATUSES`, in which case it logs status `Failure`.
25. Calls `NVFlareJobsManager.complete()`.

### MySQL Records Created or Updated

The standard task writes or updates these job-related areas:

| Area | Responsible class/method | Purpose |
| --- | --- | --- |
| Filter records | `FiltersManager.save_or_get_filter_id()` | Deduplicates and resolves the submitted filter set. |
| Job runner log | `JobStatusWriter.log()` | Stores queue, processing, participation, staging, submission, monitoring, failure, and done status/log lines. |
| NVFlare job record | `NVFlareJobsManager.establish_job_entry_id()` | Creates the `nvflare_jobs` row with project, filter, threshold, status, job runner ID, and participation override columns. |
| Job/function links | `FunctionsManager.ensure_functions_exist()` and `FunctionsManager.link_job_functions()` through `NVFlareJobsManager.establish_job_entry_id()` | Links the job to the submitted functions. |
| Datasource log | `NVFlareJobsManager.log_job_run_context()` | Upserts `nvflare_job_datasource_log`. |
| Workflow group log | `NVFlareJobsManager.log_job_run_context()` | Replaces records in `nvflare_job_workflow_groups` and associated selected-option rows when workflow group data is provided. |
| Participation records | `NVFlareParticipationJobTask` through `ParticipationManager` | Creates pending rows, updates role flags, auto-accepts submitter mapping when possible, and reads accepted clients. |
| NVFlare job path | `NVFlareJobsManager.set_nvflare_job_path()` | Stores the staged job path. |
| NVFlare assigned ID | `NVFlareJobsManager.set_nvflare_assigned_id()` | Stores the job ID assigned by NVFlare. |
| NVFlare output path | `NVFlareJobsManager.set_nvflare_output_path()` | Stores the output path returned by `NVFlareJobRunner`. |
| NVFlare status | `NVFlareJobsManager.set_nvflare_job_status()` and progress emission code | Updates backend job state. |

## Participation Confirmation Flow

The participation confirmation flow is not a separate route-triggered task in `JobRunnerService`; it is executed inside `NVFlareJobTask.run_nvflare_job()` before the analysis job is staged.

`NVFlareParticipationJobTask` receives:

| Argument | Purpose |
| --- | --- |
| `project_id` | Project context for staging. |
| `datasource_group_id` | Datasource group context for staging participation job. |
| `functions_map` | Function configuration used for matching participation records. |
| `filters_id` | Saved/resolved filter ID used for matching participation records. |
| `nvflare_provision` | NVFlare provision/admin context used by `NVFlareJobRunner`. |
| `nvflare_jobs_manager` | Existing manager for the parent job record. |
| `status_writer` | Parent job runner status writer. |
| `threshold` | Optional threshold used in participation matching. |
| `timeout_in_seconds` | Response window; standard job flow passes `900`. |
| `nvflare_job_internal_id` | Internal `nvflare_jobs.id` for parent job. |
| `username` | Submitter username for auto-accept behavior. |
| `non_contributing_clients` | Clients not contributing data. |
| `exclude_analyzing_clients` | Clients excluded from analyzing party role. |

### Participation Role Handling

`NVFlareParticipationJobTask` normalizes both participation override lists into sets.

A client that appears in both `non_contributing_clients` and `exclude_analyzing_clients` is placed in `excluded_clients`. The client snapshot is filtered so these clients are excluded from the participation-confirmation workflow entirely.

For the remaining online clients:

- `contributing_party` is recorded as `False` when the client is in `non_contributing_clients`; otherwise `True`.
- `analyzing_party` is recorded as `False` when the client is in `exclude_analyzing_clients`; otherwise `True`.
- Existing participation rows are re-recorded with the updated role flags.
- Missing participation rows are inserted as pending participation records.

### Participation Runtime Sequence

1. Gets the current NVFlare client snapshot through `NVFlareClientSnapshot().get_clients()`.
2. Filters out clients that are excluded from both contributing and analyzing roles.
3. Creates `ParticipationManager()`.
4. Logs participation initialization with status `Checking Client Participation`.
5. If `username` was supplied, looks up client names mapped to that username.
6. If the submitting user maps only to a client excluded from both roles, logs that the mapped client was skipped.
7. Otherwise attempts `auto_accept_participation_for_username(...)` for the submitter.
8. Records requested participation roles for online clients.
9. Builds a CSV list of pending clients with `confirmation=Confirmation.PENDING`.
10. If there are no pending clients, immediately returns the accepted-client CSV.
11. Logs that participation confirmation is required and identifies pending clients.
12. In non-local environments, verifies SSH connectivity before submitting the participation job. On SSH exception, logs failure and returns an empty string.
13. Sets parent NVFlare job status to `STAGING`.
14. Stages the participation confirmation job with `NVFlareJobStager`, using `job_template_name=SupportedFunction.PARTICIPATION_CONFIRMATION.lower()`.
15. Stores the staged participation job path on the parent NVFlare job record.
16. Submits the participation job through `NVFlareJobRunner.run_job()`.
17. Sets parent NVFlare job status to `PROCESSING`.
18. Polls participation records every five seconds until all pending clients respond or the timeout window ends.
19. Logs that participation is finished with status `Client Participation Established`.
20. Returns only clients with accepted participation as a CSV string.

If no accepted clients are found, `_accepted_clients()` logs `No client participation list established.` with status `No Clients Accepted Participation` and returns an empty string.

## Client Participation Endpoints

`ClientRoutes.py` supports participation state outside the job runner queue.

### `POST /clients/participation/status`

This endpoint can return the current connection snapshot and enrich it with participation state for a submitted `participation_status` payload.

Current behavior:

1. Reads JSON body, defaulting to `{}` on JSON parse failure.
2. Reads optional `username`.
3. Reads `include_connection_state`, defaulting to `true`.
4. When connection state is included, gets `NVFlareClientSnapshot().get_clients(username=username)`.
5. If `participation_status` is not an object, returns the client snapshot only.
6. Validates `participation_status.project_id` as an integer.
7. Optionally builds a `Threshold` object from `participation_status.threshold_config`.
8. Normalizes submitted functions into a canonical map for participation matching.
9. Saves/resolves the filter ID with `FiltersManager(project_id=project_id, filters=filters).get_id_by_filters()`.
10. Uses `ParticipationManager.list_client_participation_status(...)` to fetch matching participation rows.
11. Filters participation rows so returned rows match the selected contributing/analyzing role flags.
12. Updates the client snapshot entries with `participation`, `contributing_party`, and `analyzing_party` values.
13. Closes `ParticipationManager`.

If `project_id` is missing or invalid inside `participation_status`, it returns `400` with:

```json
{
  "status": "FAILURE",
  "error": "project_id is required"
}
```

Unhandled exceptions return `500` with an `error` field containing traceback lines.

### `POST /clients/participation/submit`

This endpoint records a client participation response.

Current behavior:

1. Reads the JSON body.
2. In non-local environments, validates `$pw` against the current MySQL password from `ResourceConfigProvider.get_mysql_config()`, with one uncached retry. Bad password returns `401 Unauthorized`.
3. Requires `client_name`, `functions_map`, `filter_id`, and `confirmation`.
4. Requires `functions_map` to be an object.
5. Normalizes functions through `_normalize_functions_map()`.
6. Requires at least one normalized function.
7. Converts `confirmation` to uppercase and requires it to match a `Confirmation` enum member.
8. Optionally parses `threshold_config` into a `Threshold` object.
9. Calls `ParticipationManager.record_participation(...)`.
10. Returns `{"status": "Participation recorded", "id": recorded_id}` on success.
11. Closes `ParticipationManager` in `finally`.

Current validation/error responses include:

| Condition | Response |
| --- | --- |
| Missing required field | `{"status": "Please provide <field>"}` with `400`. |
| Non-object `functions_map` | `{"status": "functions must be an object mapping function_id -> { args }"}` with `400`. |
| Function normalization exception | `{"status": "Invalid functions payload"}` with `400`. |
| Empty normalized functions | `{"status": "functions must contain at least one function"}` with `400`. |
| Invalid confirmation | `{"status": "Confirmation must be ACCEPT or REJECT"}` with `400`. |
| Invalid threshold payload | `{"status": "Invalid threshold_config payload"}` with `400`. |
| Persist failure | `{"status": "Failed to persist confirmation."}` with `500`. |
| Exception while recording | `{"status": "Exception occurred while recording participation", "log": [...]}` with `400`. |

The route contains a `# Put behind bearer token` comment. Current implemented non-local protection is password-based `$pw` validation for this endpoint; bearer-token enforcement is not implemented in the route code.

## NVFlare Job Manager Responsibilities in the Runner Flow

`NVFlareJobsManager.establish_job_entry_id()` creates the internal job record. It requires:

- A filter ID.
- A `project_id` on the manager.
- At least one normalized function.

The inserted `nvflare_jobs` row starts with:

| Column/Value | Description |
| --- | --- |
| `project_id` | Submitted project. |
| `nvflare_assigned_id = NULL` | Filled after `NVFlareJobRunner.run_job()` returns. |
| `filter_id` | Saved/resolved filter record ID. |
| `threshold_config_id` | Persisted threshold config ID when provided. |
| `status = NVFlareStatus.PROCESSING` | Initial manager status for the internal job record. |
| `job_path = NULL` | Filled after staging. |
| `output_path = NULL` | Filled after job submission. |
| `job_runner_id` | UUID generated by `JobRunnerService`. |
| `non_contributing_clients` | CSV of clients excluded from contributing role. |
| `exclude_analyzing_clients` | CSV of clients excluded from analyzing role. |

After inserting the job row, the manager ensures submitted function names exist and links them to the job.

`log_job_run_context()` then:

1. Upserts `nvflare_job_datasource_log` with `nvflare_job_id`, `project_id`, and optional `datasource_group_id`.
2. Deletes and replaces workflow group links for the job based on normalized `workflow_group_data`.
3. Commits both datasource and workflow context changes.

Status/path setters update the same internal `nvflare_jobs` record as the job progresses.

## Staging, Submission, and Monitoring

The runner flow delegates NVFlare-specific work to three classes:

| Class | Called by | Current role in this flow |
| --- | --- | --- |
| `NVFlareJobStager` | `NVFlareJobTask` and `NVFlareParticipationJobTask` | Produces the final staged NVFlare job path from templates and runtime context. |
| `NVFlareJobRunner` | `NVFlareJobTask` and `NVFlareParticipationJobTask` | Submits the staged job through NVFlare admin tooling and returns NVFlare job metadata. |
| `NVFlareJobMonitor` | `NVFlareJobTask` | Waits for the standard analysis job to reach a terminal server-side status. |

The participation job is submitted and then monitored through MySQL participation records, not through `NVFlareJobMonitor`. The standard analysis job is monitored through `NVFlareJobMonitor.wait_for_completion(poll_interval=10, timeout=600)`.

## Status Lifecycle

The job runner status visible through `job_runner_log` is not a strict finite-state machine, but the standard sequence is:

1. `Queued`
2. `Processing`
3. Participation statuses such as `Checking Client Participation`, `Monitoring Participation Responses`, or `Client Participation Established`
4. `Establishing Secure Connection` / `Secure Connection Established` in non-local connectivity checks
5. `Defining NVFlare Job`
6. `Broadcasting NVFlare Job`
7. Progress statuses emitted by NVFlare client/server webhook calls
8. `DONE` or `Failure`

The code also supports many detailed analysis/encryption/result statuses in `JobRunnerStatus`, including client/server compute, encryption, key generation, decryption, analysis, aggregation, threshold-not-met, warning, and error states. Many of these statuses are written by downstream NVFlare progress emission code rather than directly by `JobRunnerService`.

## Local vs Non-Local Behavior

`NVFlareJobTask` and `NVFlareParticipationJobTask` both read `EnvironmentProvider.get_env()`.

| Environment | Behavior |
| --- | --- |
| `Environment.LOCAL` | Skips the SSH connectivity check before NVFlare job submission. |
| Non-local | Attempts `SSHConnectionProvider.get_instance().run("hostname && uptime")` and logs success, unexpected responses, or failure. |

`/clients/participation/submit` also has non-local password protection using `$pw` from the request body and the configured MySQL password. The standard `/nvflare/jobs/submit` route does not currently implement that password gate.

## Failure Behavior

Current failure handling is split across route validation, service worker handling, and task-level checks.

| Layer | Behavior |
| --- | --- |
| Route validation | Returns `400` for known malformed submission fields before queuing. |
| Threshold resolution | Returns `400` for invalid threshold method/value before queuing. |
| `request_job_run()` | Raises `ValueError` if `functions_map` is empty or not a dictionary. The route does not wrap this call in its own `try/except`. |
| Worker thread | Catches exceptions from `NVFlareJobTask.run_nvflare_job()`, prints the traceback, logs failure to `job_runner_log`, and marks the queue item done. |
| `NVFlareJobTask` participation result | Logs `Failure` and returns if no participating clients are accepted. |
| Non-local SSH check in `NVFlareJobTask` | Logs failure if SSH raises an exception, but the method continues to NVFlare provisioning and job creation. |
| Non-local SSH check in `NVFlareParticipationJobTask` | Logs failure and returns an empty accepted-client string if SSH raises an exception. |
| Final NVFlare monitor status | Logs `DONE` unless the final server-provided status is listed in `FAILURE_JOB_RUNNER_STATUSES`; failure statuses are logged as `Failure`. |

## Request and Response Examples

### Minimal Standard Job Submission Shape

```json
{
  "project_id": 1,
  "filters": {
    "conditions": []
  },
  "functions_map": {
    "SURVIVABILITY_ANALYSIS": {
      "model_type": "open_access"
    }
  },
  "submitter": "user@example.com"
}
```

### Standard Job Submission With Datasource, Workflow Group, Threshold, and Participation Role Overrides

```json
{
  "project_id": 1,
  "datasource_group": 2,
  "filters": {
    "conditions": [
      {
        "field": "cancer_type",
        "operator": "equals",
        "value": "Breast Carcinoma"
      }
    ]
  },
  "functions_map": {
    "SURVIVABILITY_ANALYSIS": [
      {
        "model_type": "open_access"
      }
    ]
  },
  "workflow_group_data": {
    "selected_groups": [
      {
        "id": 1,
        "selected_options": ["cox_lasso"]
      }
    ]
  },
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 2
  },
  "submitter": "user@example.com",
  "non_contributing_clients": ["site-2"],
  "exclude_analyzing_clients": ["site-3"]
}
```

### Successful Queue Response

```json
{
  "job_id": "7b9df7b4-bb4c-465c-9772-7dc881114d75",
  "status": "QUEUED"
}
```

## Current Authentication Assumptions

Several relevant endpoints include comments indicating they should be placed behind bearer-token authentication. The current backend route code does not enforce bearer tokens for `/nvflare/jobs/submit`, `/clients/participation/status`, or `/clients/connection/status`.

Implemented route-level protection in this area is limited to password-style `$pw` checks on non-local callback/submit-style endpoints such as:

- `POST /clients/participation/submit`
- `POST /nvflare/client/emit_progress`
- `POST /nvflare/jobs/audit/submit`

The standard job submission route currently trusts the request body once validation passes.
