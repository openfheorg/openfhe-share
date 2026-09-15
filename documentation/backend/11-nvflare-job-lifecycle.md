# NVFlare Job Lifecycle

## Files Covered

| File | Role |
| --- | --- |
| `app/api/routes/NVFlareRoutes.py` | Defines `/nvflare/jobs/submit`, validates the submission payload, resolves threshold config, and enqueues the job. |
| `app/core/job_runner/JobRunnerService.py` | Singleton queue service that assigns the backend UUID, creates the `JobStatusWriter`, and runs NVFlare tasks on a daemon worker thread. |
| `app/core/job_runner/job_tasks/NVFlareJobTask.py` | Main standard NVFlare job task. Orchestrates filter persistence, job record creation, participation, staging, submit, monitor, and final status logging. |
| `app/core/job_runner/job_tasks/NVFlareParticipationJobTask.py` | Participation confirmation task. Determines which clients must confirm, broadcasts the participation job when needed, waits for responses, and returns accepted clients. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Builds staged NVFlare job directories from templates and injects filters, function config, project metadata, workflow config, threshold config, datasource context, participation overrides, and model-file source metadata for initiator-side runtime upload. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobUploader.py` | Deprecated legacy upload implementation. The current lifecycle stages local job directories and submits them through `NVFlareJobRunner`. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobRunner.py` | Submits a staged job through the NVFlare admin kit by running `submit_job <job_path>`. Parses the NVFlare-assigned job UUID from admin output. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobMonitor.py` | Polls the NVFlare admin kit with `list_jobs <job_id>`, persists status/timing updates, and returns the terminal NVFlare status. |
| `app/core/mysql/managers/NVFlareJobsManager.py` | Persists internal NVFlare job records, function/config links, threshold links, datasource logs, workflow group logs, NVFlare assigned IDs, paths, statuses, and submission timing. |
| `app/core/mysql/job_tracking/JobStatusWriter.py` | Writes user-facing job-runner status/log lines to `job_runner_log` by backend UUID. |

## Endpoint Entry Point

The standard job lifecycle starts at:

```text
POST /nvflare/jobs/submit
```

The handler is `submit_nvflare_job()` in `app/api/routes/NVFlareRoutes.py`.

The request body currently supports these lifecycle inputs:

| Field | Required | Use |
| --- | --- | --- |
| `filters` | Yes | Stored or reused through `FiltersManager.save_or_get_filter_id()` and later written into staged job `filters.json`. |
| `project_id` | Yes | Parsed as an integer and passed through the full lifecycle. Used to load project metadata and datasource-specific project config. |
| `datasource_group` | No | Parsed as an integer when provided. Passed to job tracking, project lookup, and biomarker model directory resolution. |
| `functions_map` | Yes | Must be an object. Normalized by `_normalize_functions_map()` before being passed to the queue and stager. |
| `workflow_group_data` | No | Must be an object when provided. Logged to job history and used by the stager for predictive modeling workflow expansion. |
| `non_contributing_clients` | No | Must be an array of strings when provided. Stored on the job and passed into participation/staging. |
| `exclude_analyzing_clients` | No | Must be an array of strings when provided. Stored on the job and passed into participation/staging. |
| `threshold_config` | No | When provided, resolves or creates a `Threshold` row through `ThresholdManager.get_or_create()`. |
| `submitter` | No | Trimmed username used by the participation task to auto-accept the submitting user's mapped client when applicable. |

Validation failures return HTTP 400 responses from the route before the job is queued. A successful submission returns:

```json
{
  "job_id": "<backend job runner UUID>",
  "status": "QUEUED"
}
```

The returned `job_id` is the backend job-runner UUID stored in `job_runner_log`. It is separate from the NVFlare-assigned job UUID parsed later from `fl_admin` output.

## Queue and Worker Behavior

`JobRunnerService` is a process-local singleton created by `JobRunnerService.get_instance()`.

The service owns:

| Member | Purpose |
| --- | --- |
| `task_queue` | A standard Python `queue.Queue()` holding pending job requests. |
| `job_registry` | In-memory map of backend job UUID to `JobStatusWriter`. |
| `thread` | Daemon worker thread named `JobRunnerService`. |

`request_job_run()` validates that `functions_map` is a non-empty dictionary and delegates to `_make_request()`.

`_make_request()`:

1. Creates a backend UUID with `uuid.uuid4()`.
2. Creates `JobStatusWriter(job_id)`.
3. Logs `Job queued.` with `JobRunnerStatus.QUEUED`.
4. Stores the writer in `job_registry`.
5. Adds the work tuple to `task_queue`.
6. Returns the backend UUID to the route.

The worker thread runs `_worker()` forever. It pulls one queued item at a time and constructs `NVFlareJobTask(...)`. The implementation is serial: the single worker consumes jobs sequentially, not in parallel. If the task raises an exception, `_worker()` prints the traceback and logs `JobRunnerService exception: ...` with `JobRunnerStatus.FAILURE`, then marks the queue item done.

## Standard Job Lifecycle Trace

The current standard lifecycle is:

1. `NVFlareRoutes.submit_nvflare_job()` receives and validates the payload.
2. `ThresholdManager.get_or_create()` resolves `threshold_config` when present.
3. `JobRunnerService.get_instance().request_job_run(...)` enqueues the work.
4. `JobRunnerService._worker()` creates `NVFlareJobTask(...)` and calls `run_nvflare_job()`.
5. `NVFlareJobTask.run_nvflare_job()` logs initiation with `JobRunnerStatus.PROCESSING`.
6. `FiltersManager(project_id, filters, status_writer).save_or_get_filter_id()` stores or reuses the submitted filters.
7. In non-local environments, `SSHConnectionProvider.get_instance().run("hostname && uptime")` verifies SSH connectivity to the NVFlare server.
8. `NVFlareProvisionProvider().get_nvflare_instance()` resolves NVFlare provision/configuration paths.
9. `NVFlareJobsManager.establish_job_entry_id(...)` creates the internal NVFlare job record.
10. `NVFlareJobsManager.log_job_run_context(...)` logs datasource group and workflow group selections.
11. `NVFlareParticipationJobTask(...).get_participation_client_list()` determines the accepted participating client CSV.
12. If no clients are accepted, the task logs `No participating clients found for this job!` with `JobRunnerStatus.FAILURE` and returns without staging or submitting the standard job.
13. `NVFlareJobsManager.set_nvflare_job_status(NVFlareStatus.STAGING)` records staging state.
14. `NVFlareJobStager(...).stage_job()` builds the staged job directory.
15. `NVFlareJobsManager.set_nvflare_job_path(final_job_path)` records the staged path.
16. `NVFlareJobRunner(...).run_job()` runs `submit_job <absolute staged job path>` through `NVFlareAdminKitManager`.
17. `NVFlareJobsManager.set_nvflare_assigned_id(nvflare_job_generated_id)` stores the NVFlare-assigned UUID.
18. `NVFlareJobsManager.set_nvflare_output_path(nvflare_output_path)` stores the computed server-side output path.
19. `NVFlareJobMonitor(...).wait_for_completion(poll_interval=10, timeout=600)` polls `list_jobs <nvflare_job_id>` until terminal status or timeout.
20. `NVFlareJobTask` logs final completion with `JobRunnerStatus.DONE` unless the final NVFlare status maps to a failure status, in which case it logs `JobRunnerStatus.FAILURE`.
21. `NVFlareJobsManager.complete()` closes the manager cursor and connection.

## Job Status Logging

`JobStatusWriter` is tied to the backend job-runner UUID returned to the frontend. It writes to `job_runner_log`.

`log(message, status)`:

- prefixes each message with a UTC ISO timestamp;
- inserts or updates the row by `uuid`;
- appends log text using `CONCAT(IFNULL(log, ''), '\n', VALUES(log))`;
- updates the current status when a `JobRunnerStatus` value is provided;
- commits after each write.

The writer checks for a manual `STOP` status before each log write. If the row for the backend UUID has `status = 'STOP'`, the writer appends an exit message, commits, and terminates the process with `os._exit(0)`.

`safe_status_update()` prints a timestamped status message to stdout and, when a writer is provided, persists the same message through `JobStatusWriter.log()`.

## Internal NVFlare Job Record

`NVFlareJobsManager.establish_job_entry_id()` creates the internal job-tracking record before the NVFlare job is staged or submitted.

The creation flow:

1. Persists threshold data when needed through `_persist_threshold_if_needed()`.
2. Inserts a row in `nvflare_jobs` with `project_id`, `filter_id`, optional `threshold_id`, and comma-separated participation override fields.
3. Stores the new internal job ID on the manager as `self.nvflare_job_id`.
4. Delegates function/config linking to `FunctionsManager.attach_functions_and_configs_to_job()`.
5. Returns the internal `nvflare_jobs.id`.

After the row exists, the manager updates it through:

| Method | Behavior |
| --- | --- |
| `set_nvflare_job_status(status)` | Updates the NVFlare status and returns the normalized status string. |
| `set_nvflare_assigned_id(assigned_id)` | Stores the NVFlare-assigned job UUID. |
| `set_nvflare_job_path(job_path)` | Stores the staged job path. |
| `set_nvflare_output_path(output_path)` | Stores the expected output path. |
| `set_submission_timing(submit_time, run_duration)` | Stores timing values parsed from `list_jobs`. |
| `set_participation_client_overrides(...)` | Updates participation override fields when needed. |
| `set_workflow_for_function_config(...)` | Records a workflow ID for an already-resolved function config. |
| `ensure_and_set_workflow_for_function_config(...)` | Ensures a function config exists and records its workflow ID. |

`log_job_run_context()` writes datasource and workflow group context:

- `_upsert_job_datasource_log()` writes `nvflare_job_datasource_log` for the internal job, project, and optional datasource group.
- `_replace_job_workflow_group_log()` rewrites `nvflare_job_workflow_groups` and `nvflare_job_workflow_group_options` for the submitted workflow selections.

Unknown workflow group keys or option values are skipped and logged through `safe_status_update()` with `JobRunnerStatus.PROCESSING`.

## Participation Confirmation Lifecycle

Participation is part of the standard job lifecycle. The standard job is not staged until participation is resolved.

`NVFlareParticipationJobTask.get_participation_client_list()` performs this flow:

1. Reads the current NVFlare client snapshot through `NVFlareClientSnapshot().get_clients()`.
2. Removes any client that appears in both `non_contributing_clients` and `exclude_analyzing_clients`. These clients are excluded from both roles and do not receive participation requests.
3. Creates `ParticipationManager()`.
4. Logs `Participation job initializing...` with `JobRunnerStatus.PARTICIPATION_INITIAL_CHECK`.
5. If `username` was provided, looks up mapped client names with `get_client_names_for_username(username)`.
6. If the submitting user's mapped client is not excluded, attempts `auto_accept_participation_for_username(...)`.
7. Records requested participation roles for online clients using `record_pending_participation()` or `record_participation()`.
8. Builds `broadcast_clients_list` from clients still in `PENDING` confirmation status.
9. If no clients are pending, returns accepted clients immediately.
10. If clients are pending, stages and submits a participation confirmation job using the `participation_confirmation` template.
11. Polls MySQL every 5 seconds until all pending clients respond or the 900 second default timeout expires.
12. Logs that the participation step finished with `JobRunnerStatus.PARTICIPATION_ESTABLISHED`.
13. Returns only clients with accepted participation via `list_clients_with_accepted_participation_csv(...)`.

If no accepted clients remain, `_accepted_clients()` logs `No client participation list established.` with `JobRunnerStatus.PARTICIPATION_EMPTY` and returns an empty string.

The participation job uses the same staging and runner machinery as standard jobs, but passes `job_template_name=SupportedFunction.PARTICIPATION_CONFIRMATION.lower()` into `NVFlareJobStager`. The participation branch sets the NVFlare job status to `STAGING` before staging and to `PROCESSING` after the participation job is submitted.

## Staging Responsibilities

`NVFlareJobStager.stage_job()` is the current staging entry point. It lowercases the selected template name, calls `_build_local_job_dir(job_template)`, logs `NVFlareJobStager: Job staging complete` with `JobRunnerStatus.JOB_UPLOAD`, and returns the staged path.

The current local staging constants are:

| Constant | Value |
| --- | --- |
| `LOCAL_NVFLARE_JOBS_DIR` | `app/core/job_runner/nvflare_jobs/jobs` |
| `LOCAL_JOB_ROOT` | `/tmp/nvflare_jobs/jobs` |
| `DEFAULT_JOB_TEMPLATE` | `nvflare_job_template` |
| `DEFAULT_GLOBAL_SCHEMA` | `global_schema.json` |

`_build_local_job_dir()`:

1. Resolves the template under `LOCAL_NVFLARE_JOBS_DIR`.
2. Raises `FileNotFoundError` when the template does not exist.
3. Removes any existing staged directory for that template under `/tmp/nvflare_jobs/jobs`.
4. Copies the template directory recursively while skipping `.pyc` and `.pyo` files.
5. Writes model-file source metadata when selected model workflows require initiator-supplied model files.
6. Inserts model-upload workflows before the workflows that consume uploaded model artifacts.
7. Parses the participating client CSV.
8. Computes `client_count = max(1, len(clients))`.
9. Patches `app_server/config/config_fed_server.json` when possible.
10. Builds a staged `filters_json_obj` payload.
11. Writes `filters.json` to both `app_client/custom/filters.json` and `app_server/custom/filters.json` when there is a payload.
12. Writes `meta.json` at the job root.
13. Returns the staged job directory path.

### Staged `filters.json`

The staged `filters.json` payload can include:

| Key | Source |
| --- | --- |
| Submitted filters | Loaded from `MySQLRetriever.stage_filters_by_id(filters_id)`. |
| `functions_map` | Expanded functions map from `_expand_functions_map_for_selected_models()` or the normalized submitted functions map. |
| `threshold_config` | `id`, `method`, and `threshold` from the resolved `Threshold`. |
| `project` | JSON-encoded `Project` loaded through `ProjectsManager.get_project(project_id, datasource_group_id=...)`. |

The project payload may include expanded project functions when predictive modeling workflow selections require multiple model-specific function entries.

### Staged `meta.json`

The stager writes:

```json
{
  "name": "<job_template>",
  "resource_spec": {},
  "min_clients": <client_count>,
  "deploy_map": {
    "app_client": ["<client names>"],
    "app_server": ["server"]
  },
  "job_name": "<job_template>"
}
```

`client_count` is always at least `1`, even when the parsed client list is empty.

## Server Config Patching

`_update_server_config_text()` reads the server config as JSON after stripping block comments and line comments. It returns patched JSON text or `None` when no supported patch can be applied.

Current patches include:

- `server.heart_beat_timeout = 120`;
- `server.task_request_interval = 0.5`;
- workflow `args.min_clients = client_count`;
- workflow `args.wait_time_after_min_received = 0` (the controller already waits for all `min_clients`, so the post-min grace window is moot — set to 0 to trim per-round latency);
- workflow `args.task_check_period = 0.1`;
- encrypted biomarker workflow `train_timeout = 600` when currently unset/zero;
- stat analytics workflow regeneration from the submitted `functions_map`;
- optional threshold workflow insertion;
- optional encrypted biomarker discovery workflow insertion;
- OpenFHE persistor argument updates for non-participation jobs.

For non-participation jobs, `_update_persistor_openfhe_args()` also injects the current participation overrides into the persistor component:

```json
{
  "non_contributing_clients": ["..."],
  "exclude_analyzing_clients": ["..."]
}
```

It also sets the current server ownership flags to:

```json
{
  "is_server_data_owner": false,
  "is_server_contributing_to_aggregation": false
}
```

The same method calculates OpenFHE-related persistor arguments from encrypted model selection, threshold mode, computation types, client count, and schema-derived group count for Kaplan-Meier workflows.

## Function and Workflow Expansion

The stager normalizes `functions_map` to uppercase function keys with a list of configuration dictionaries per function.

Predictive modeling workflow expansion is driven by:

```text
workflow_group_data.predictive_modeling_method_ids.selected_values
```

When selected model keys are present and a function config has `is_biomarker_discovery` set to `true` or `1`, the stager duplicates that function config per selected model key and injects:

```json
{
  "model_key": "<selected model key>"
}
```

Stat analytics workflow generation is handled by `_build_stat_analytics_workflows()`.

Key behavior:

- Starts from the first template workflow whose `args.train_task_name` is `task_stat_analytics`.
- Removes template stat analytics workflows from the original workflow list.
- Keeps non-analytics workflows in template order.
- Keeps the profile consolidation workflow with ID `workflow_consolidate_profile_summaries` as a tail workflow after generated stat workflows.
- Applies workload defaults from the template and overlays submitted function config.
- Derives `computation_type` from the function config or `FUNCTION_TO_COMPUTATION_TYPE`.
- Ensures `global_schema` defaults to `global_schema.json`.
- Coerces workload argument types using `SupportedFunction.get_property_type()`.
- Applies allowed custom config variables into staged filters.
- Calls `NVFlareJobsManager.ensure_and_set_workflow_for_function_config()` to record the workflow ID for the function config.

For selected biomarker model keys, generated stat workflow IDs use:

```text
workflow_stat_analytics__<selected_model_key>
```

If a generated workflow ID already exists in the workflow list, `_get_unique_workflow_id()` appends `_2`, `_3`, and so on until the ID is unique.

For non-model-expanded stat analytics workflows, generated IDs use:

```text
workflow_stat_analytics_<index>
```

## Threshold Workflow Insertion

`_insert_threshold_workflow()` adds a threshold samples workflow only when:

- `threshold` is present;
- the job template is not `participation_confirmation`;
- there is at least one generated stat analytics workflow.

Template selection:

| Threshold method | Template ID |
| --- | --- |
| `ThresholdMethod.PROTECTED` | `workflow_threshold_samples_secure` |
| Other threshold methods | `workflow_threshold_samples_unsecure` |

The threshold workflow sets:

- `args.min_clients` to the computed client count;
- `args.workload_args.min_global_samples` from `threshold.threshold` when it can be parsed as an integer;
- `args.workload_args.workflows` to the generated stat analytics workflow map.

If a keygen workflow is present, the threshold workflow is inserted immediately after keygen. Otherwise it is appended to the workflow list.

## Encrypted Biomarker Discovery Handling

Encrypted biomarker discovery handling is only active when `_is_encrypted_model()` finds a submitted config with:

```json
{
  "model_type": "encrypted"
}
```

When active, `_insert_enc_biomarker_disc_workflow()` inserts `ENC_BIOMARKER_DISC_WORKFLOW_TEMPLATE` before the first Kaplan-Meier workflow, unless an encrypted biomarker discovery workflow is already present.

The inserted workflow:

- has base ID `workflow_enc_biomarker_disc_1`;
- uses `workflow_runtime.customSAG` (the in-job wrapper around `duality_nvflare_workflows.customSAG.customSAG`);
- runs train task `task_enc_biomarker_disc`;
- uses computation type `biomarker_enc_risk_group_computation`;
- sets `train_timeout` to `600` seconds;
- sets `min_clients` to the computed client count;
- injects `cancer_type` from function config when present;
- injects `model_keys` from selected predictive modeling method values when present.

The template `min_clients` is `0`, which `customSAG` interprets specially as "aggregate only after **all** clients respond" (the stager patches in the concrete client count at insertion). For the hidden-result PQC rounds, `customSAG` also sends one tailored task per client (asymmetric dispatch) and runs a round-2 wait barrier that blocks until every per-client task completes before aggregation — see [18-openfhe-and-encrypted-workflows.md](18-openfhe-and-encrypted-workflows.md#per-round-analytics-flow-under-hidden-result-routing).

Model-file resolution is now handled through initiator-side runtime upload instead of backend-side file copying.

The stager does not read model CSV files and does not require the backend container to have model files mounted. When selected biomarker workflows need model artifacts, the stager writes `app_client/custom/model_file_sources.json`. That file contains the model source locations saved for the initiator user, keyed by project, datasource group, model lookup value, model key, and artifact type.

At job runtime, `workflow_model_upload__<model_key>` is inserted before the first workflow that consumes those model artifacts. The initiator/leader site reads `model_file_sources.json`, resolves the saved paths on its own filesystem, and uploads the required artifacts into the NVFlare job. Open-access workflows upload plaintext model files for downstream use. Encrypted workflows upload encrypted model artifacts and only the scalar metadata required by later Exceptional Response Discrimination (previously Logistic Calibration Statistics - LCS) workflows, such as `ER_threshold` for the meta-analysis.

Missing model files now fail at the model-upload workflow on the initiator/leader site, not during backend staging.

## Submit Through NVFlare Admin Kit

`NVFlareJobRunner.run_job()` submits a staged job by constructing:

```text
submit_job <absolute staged job path>
```

It executes that command through:

```python
NVFlareAdminKitManager().run(commands=[submit_command], timeout=300)
```

The runner normalizes line endings in the output and parses the assigned NVFlare job UUID using a regex that accepts output shaped like:

```text
Submitted job: <uuid>
Job submitted: <uuid>
```

Failure behavior:

- If the admin command exit code is non-zero, `run_job()` raises `RuntimeError` with the raw output.
- If the command succeeds but the assigned UUID cannot be parsed, `run_job()` raises `RuntimeError` with the raw output.

On success, it computes the expected server-side output path as:

```text
<nvflare_provision.client_to_server_job_save_location>/<nvflare assigned job uuid>
```

It logs `NVFlareJobRunner: Job broadcasted successfully` with `JobRunnerStatus.JOB_BROADCAST` and returns:

```python
(nvflare_job_generated_id, nvflare_output_path)
```

## Monitoring Through NVFlare Admin Kit

`NVFlareJobMonitor.wait_for_completion()` requires the NVFlare-assigned job UUID. If it is missing, it raises `RuntimeError`.

The monitor loops until timeout:

1. Runs `list_jobs <job_id>` through `NVFlareAdminKitManager().run(..., timeout=300)`.
2. If the admin command fails, treats it as transient, sleeps for the poll interval, and retries.
3. Parses table rows using `ROW_RE`.
4. Finds the row whose job ID matches the monitored job.
5. Extracts `status`, `submit_time`, and `run_duration`.
6. Calls `NVFlareJobsManager.set_nvflare_job_status(status)`.
7. Calls `NVFlareJobsManager.set_submission_timing(submit_time, run_duration)`.
8. Treats any status beginning with `FINISHED:` as terminal and returns the normalized status from `NVFlareJobsManager`.

The standard job task calls:

```python
wait_for_completion(poll_interval=10, timeout=600)
```

If no terminal status is reached before timeout, the monitor raises `TimeoutError` containing the last observed status.

## Final Status Handling

After monitoring returns, `NVFlareJobTask` logs:

```text
NVFlareJobTask: job completed with a status of <final status>.
```

The log status is:

| Final NVFlare status | Job runner status |
| --- | --- |
| Present in `FAILURE_JOB_RUNNER_STATUSES` | `JobRunnerStatus.FAILURE` |
| Any other returned final status | `JobRunnerStatus.DONE` |

`FAILURE_JOB_RUNNER_STATUSES` currently includes:

- `FINISHED:ABANDONED`
- `FINISHED:EXECUTION_EXCEPTION`
- `FINISHED:FAILED`
- `FINISHED:SERVER_ERROR`

## Deprecated Uploader

`NVFlareJobUploader.py` remains in the codebase but is marked as a deprecated class. Its previous zip/upload/unzip implementation is commented out. The active lifecycle does not call `NVFlareJobUploader`; jobs are staged locally by `NVFlareJobStager` and submitted directly by `NVFlareJobRunner` through the admin kit.

## Local and Non-Local Differences

The lifecycle branches on `EnvironmentProvider.get_env()` in the task classes.

| Area | Local behavior | Non-local behavior |
| --- | --- | --- |
| Standard job task SSH check | Skipped. | Runs `hostname && uptime` through `SSHConnectionProvider` before job record creation continues. |
| Participation job SSH check | Skipped. | Runs `hostname && uptime` through `SSHConnectionProvider`; on exception logs failure and returns an empty client list. |
| Job staging | Uses local template copy under `/tmp/nvflare_jobs/jobs`. | Uses the same stager path logic in current code. |
| Job submit/monitor | Uses `NVFlareAdminKitManager`. | Uses `NVFlareAdminKitManager`. |

## Main Tables Touched

| Table | Lifecycle use |
| --- | --- |
| `job_runner_log` | Backend UUID status/log stream written by `JobStatusWriter`. |
| `defined_filters` and related filter tables | Filter persistence/reuse through `FiltersManager`. |
| `defined_thresholds` | Threshold lookup/create through `ThresholdManager` and `NVFlareJobsManager`. |
| `nvflare_jobs` | Internal job record, paths, NVFlare assigned ID, status, timing, participation overrides. |
| `nvflare_job_functions` | Function links for a job. |
| `nvflare_job_function_configs` | Function config links for a job. |
| `defined_function_config_sets` and related config tables | Function config persistence and workflow ID binding. |
| `nvflare_job_datasource_log` | Datasource group selected for the job. |
| `nvflare_job_workflow_groups` | Workflow groups selected for the job. |
| `nvflare_job_workflow_group_options` | Workflow group options selected for the job. |
| `nvflare_client_participation` | Client participation confirmation state and requested contributing/analyzing roles. |

## Error Handling Summary

| Stage | Failure behavior |
| --- | --- |
| Route validation | Returns HTTP 400 with a JSON status/error message. |
| Threshold parsing | Returns HTTP 400 for invalid threshold method or value. |
| Queue worker exception | Catches the exception, prints traceback, and logs `JobRunnerService exception` as `Failure`. |
| Filter persistence/staging failure | Propagates to the worker exception handler unless caught by lower-level code. |
| Non-local SSH check in standard job | Logs failure but the current standard task does not immediately return. |
| Non-local SSH check in participation job | Logs failure and returns an empty client list. |
| No accepted clients | Logs failure/empty participation and skips standard job staging/submission. |
| Missing job template | Raises `FileNotFoundError`. |
| Missing expected biomarker model file | Raises `FileNotFoundError`. |
| `submit_job` admin command non-zero exit | Raises `RuntimeError`. |
| Unable to parse NVFlare assigned job ID | Raises `RuntimeError`. |
| `list_jobs` admin command non-zero exit | Treated as transient; monitor sleeps and retries. |
| Monitor timeout | Raises `TimeoutError`. |

## Auth and Security Assumptions

`/nvflare/jobs/submit` currently has a code comment indicating it should be put behind a bearer token, but the route itself does not enforce bearer-token authentication in the current backend code. It accepts the submitted `submitter` string from the request body and uses it for participation auto-accept logic.

The lifecycle relies on the frontend and surrounding deployment controls to provide the intended user context until route-level authentication is implemented.
