# Job Submission, Status, and Websocket Handling

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_runner/pages/JobSubmissionPage.tsx` | Final job review, submission, live status tracking, websocket handling, polling fallback, and submitted-job actions. |
| `src/features/job_runner/components/SubmissionOverview.tsx` | Read-only review panel for submitted filters, functions, threshold config, datasource group, and workflow group choices. |
| `src/features/job_runner/JobRunnerMain.tsx` | Carries selected filters, functions, threshold config, datasource group, workflow group data, and saved job info into the submission and results steps. |
| `src/features/job_history/components/JobHistoryTable.tsx` | Displays job history, fetches job logs/status, live-tracks expanded running jobs, and refreshes terminal jobs from history. |
| `src/features/job_history/pages/ResultsPage.tsx` | Loads selected job information, workflow mappings, workflow result payloads, function config, profile/system metrics, and exportable result sections. |
| `src/features/job_history/utils/JobsDataUtils.tsx` | Central result/history utility layer for `/jobs/info`, `/jobs/results/mapping`, `/jobs/results`, and `/jobs/function/config`. |
| `src/types/JobsDataTypes.tsx` | TypeScript shapes for `NVFlareJob`, `JobLogData`, threshold payloads, crypto audit records, datasource log records, and workflow group history data. |
| `src/constants/Constants.tsx` | API base URL and endpoint constants used by submit, history, status, result, mapping, and function-config calls. |

## Source Notes

The current frontend does not contain these paths from the original outline:

- `src/features/job_runner/pages/job_submission/`
- `src/features/job_runner/pages/submitted_jobs/`
- `src/constants/ExecutionStep.ts`

The implemented submission screen is `src/features/job_runner/pages/JobSubmissionPage.tsx`. Submitted-job behavior is handled inside that same component rather than a separate `submitted_jobs` directory. Status display constants are local to `JobSubmissionPage.tsx`, not centralized in an `ExecutionStep.ts` file.

## Job Submission Role

The job submission screen is the final review and execution step in the job runner flow.

It receives the prepared job configuration from `JobRunnerMain.tsx`, renders a review summary through `SubmissionOverview`, displays the NVFlare client snapshot table, builds the backend submit payload, sends the request to the backend, and then tracks the returned job ID until the job reaches a terminal status.

The component also owns the post-submit live status panel. After a successful submission, the same screen shows:

- current job status
- status icon flow
- persistent secondary warning/failure icons
- live job log text area
- button to view results after `DONE`
- disabled failure button after `FAILURE`

## `JobSubmissionPage` Props

`JobSubmissionPage.tsx` defines `JobSubmissionProps` with these props:

| Prop | Type | Purpose |
| --- | --- | --- |
| `project` | `Project` | Selected project metadata. Used for project ID, project functions, fixed function config, workflow groups, and filter payload construction. |
| `submittedFilter` | `FilterCollection` | Selected filter collection that will be transformed for backend submission. |
| `submittedFilterName` | `string` | Display name for the selected filter set. Also passed into `buildFiltersPayload`. |
| `onBack` | `() => void` | Returns to function selection. Button label: `Back to Computation Function Selection`. |
| `viewAnalysisResultsPage` | `() => void` | Moves to the results page after the job reaches `DONE`. |
| `onCancel` | `() => void` optional | Declared in the props interface but not currently destructured or used by the component. |
| `savedJobInfo` | `JobLogData` | Restored job status/log context when returning to the submission screen. |
| `setSavedJobInfo` | `(jobData: JobLogData) => void` | Persists live status/log/job metadata back into `JobRunnerMain.tsx`. |
| `selectedFunctions` | `FunctionConfigs` | Function configuration selected earlier in the job runner flow. |
| `selectedThresholdConfig` | `ThresholdConfig | undefined` | Optional threshold config added to payload only when enabled and complete. |
| `selectedDatasourceGroupId` | `number | null` | Optional datasource group ID added to the submit payload as `datasource_group`. |
| `selectedDatasourceGroupName` | `string | null` | Display-only datasource group name shown in `SubmissionOverview`. |
| `workflowGroupData` | `WorkflowGroupData` optional | Optional workflow group selections added to the submit payload as `workflow_group_data`. |

## Submission Source State

Most values originate earlier in the job runner flow and are passed through `JobRunnerMain.tsx`.

| Payload area | Source in frontend |
| --- | --- |
| `project_id` | `project.id`, passed from `App.tsx` into `JobRunnerMain.tsx`, then into `JobSubmissionPage.tsx`. |
| `submitter` | `username` from `useUserSession()` in `UserRoleContext.tsx`. |
| `filters` | `buildFiltersPayload(submittedFilterName || "Filter Set", submittedFilter, project)`. |
| `functions_map` | `selectedFunctions` merged with fixed project function configuration from `project.functions[*].custom_configuration_fixed`. |
| `datasource_group` | `selectedDatasourceGroupId`, included only when non-null. |
| `workflow_group_data` | `workflowGroupData`, included only when the object has keys. |
| `threshold_config` | `selectedThresholdConfig`, included only when enabled, method is present, and threshold is non-null. |
| `non_contributing_clients` | `clientParticipationSelection.non_contributing_clients`, emitted by `NVFlareClientSnapshot`. |
| `exclude_analyzing_clients` | `clientParticipationSelection.exclude_analyzing_clients`, emitted by `NVFlareClientSnapshot`. |

## Submit Endpoint

The frontend submits jobs to:

```text
POST ${API_BASE}/nvflare/jobs/submit
```

The route suffix is exported as:

```ts
export const API_SUBMIT_JOB = "/nvflare/jobs/submit";
```

The submit call is made in `JobSubmissionPage.handleSubmit()`.

## Final Submit Payload Shape

`handleSubmit()` builds this payload shape:

```json
{
  "project_id": 1,
  "filters": {
    "name": "Example Filter Set",
    "conditions": [
      {
        "filter_type": "PATIENT_DATA",
        "column_name": "Age",
        "operator": ">=",
        "value": "50"
      },
      {
        "filter_type": "OBSERVATION_DATA",
        "column_name": "Cancer_type",
        "operator": "IN",
        "values": ["Breast Carcinoma"]
      }
    ]
  },
  "functions_map": {
    "SURVIVAL_ANALYSIS": [
      {
        "model_type": "Encrypted",
        "time_grid_max": 60
      }
    ]
  },
  "submitter": "username",
  "non_contributing_clients": ["site-2"],
  "exclude_analyzing_clients": ["site-3"],
  "datasource_group": 4,
  "workflow_group_data": {
    "predictive_modeling_method_ids": {
      "group_key": "predictive_modeling_method_ids",
      "selected_values": ["cox_lasso", "logistic_reg"]
    }
  },
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 10
  }
}
```

`filters.conditions[*].filter_type` is one of `PATIENT_QUERY`, `PATIENT_DATA`, `OBSERVATION`, `OBSERVATION_QUERY`, `OBSERVATION_DATA`; scalar operators take `value`, while `IN`, `NOT_IN`, `IN_ALL` and `BETWEEN` take `values`. `model_type` is `Open-access` or `Encrypted`. The `workflow_group_data` key is the project's workflow group key, `predictive_modeling_method_ids` for the biomarker project.

Only the always-present fields are guaranteed:

- `project_id`
- `filters`
- `functions_map`
- `submitter`
- `non_contributing_clients`
- `exclude_analyzing_clients`

The following fields are conditional:

| Field | Included when |
| --- | --- |
| `datasource_group` | `selectedDatasourceGroupId !== null` |
| `workflow_group_data` | `workflowGroupData` exists and has at least one key |
| `threshold_config` | threshold config is enabled, has a method, and has a non-null threshold |

## Function Config Merge Before Submit

Before submission, `JobSubmissionPage.tsx` derives `resolvedFunctionsMap` from `selectedFunctions`.

The helper `getFixedConfigByFunction(project)` scans `project.functions` and creates a map from uppercase function name to `custom_configuration_fixed`.

The helper `mergeFixedIntoSelectedFunctions(selectedFunctions, fixedByFnUpper)` applies fixed properties to selected function config:

- array-valued function configs are mapped item-by-item
- object-valued function configs are converted to a one-item array with fixed values merged in
- non-object values are passed through as-is
- fixed config overwrites any same-named property from the selected config

This means the user-facing function selection may not show every backend-bound config field. Fixed project-level function config is injected at submission time.

## Submission UI Behavior

`JobSubmissionPage` renders three main UI areas:

1. `NVFlareClientSnapshot`
2. `SubmissionOverview`
3. footer action buttons

After a job is submitted and a `job_id` exists, it also renders a status accordion.

### Client Snapshot Section

`NVFlareClientSnapshot` receives:

| Prop | Value |
| --- | --- |
| `projectId` | `project.id` |
| `filtersPayload` | transformed filter payload |
| `functionsMap` | resolved functions map after fixed config merge |
| `thresholdConfig` | selected threshold config |
| `heartbeatWindowMs` | `60000` |
| `onState` | updates `snapshotLoading` and `snapshotClients` |
| `onParticipationSelectionChange` | updates non-contributing/analyzing exclusions |
| `onError` | writes snapshot error into submission `error` state |
| `canSubmit` | current computed submit eligibility |

The snapshot is also the source of `clientParticipationSelection`, which is used in the final payload.

### Submission Overview Section

`SubmissionOverview` receives:

| Prop | Value |
| --- | --- |
| `submittedFilterName` | selected filter set name |
| `submittedFilter` | selected filter collection |
| `selectedFunctions` | resolved functions map |
| `hasSelectedFunctions` | whether the resolved function map has keys |
| `selectedThresholdConfig` | optional threshold config |
| `selectedDatasourceGroupName` | display-only datasource group name |
| `workflowGroupData` | selected workflow group data |
| `project` | selected project |

`SubmissionOverview` displays content only when there is meaningful content to show. It renders filters, selected functions, threshold data, workflow group rows, datasource group display, and function configuration warnings. One current warning rule is defined for `CI_type` values `log-log` or `linear`, warning that survival curves with confidence intervals may disclose event counts and at-risk totals.

## Submit Validation and Disabled Conditions

`JobSubmissionPage.tsx` does not run a separate form-validation function before `handleSubmit()`. The submit button is enabled or disabled through the computed `canSubmit` value.

`canSubmit` is true only when all of these are true:

- not currently submitting
- job has not reached `DONE`
- job has not reached failure state
- at least one function exists in `resolvedFunctionsMap`
- server row is online, when present
- at least one non-server registered client exists
- at least one registered non-server client is connected

The button label explains the first blocking condition from this set:

| Condition | Button text |
| --- | --- |
| `snapshotLoading` | `Loading clients...` |
| `submitting` | `Submitting...` |
| no selected functions | `Select at least one function` |
| no registered non-server clients | `No Registered Clients` |
| server offline | `Server is Offline` |
| no connected registered non-server clients | `No Site Online` |
| eligible | `Submit for Analysis` |
| done | `View Analysis Results` |
| failure | `Failure Occurred` |

A server row is found by `isServer` or by name equal to `server` case-insensitively. If no server row exists, `serverOnline` defaults to `true`.

## Submit Loading, Success, and Error Behavior

On submit:

1. `submitting` is set to `true`.
2. `error` is cleared.
3. persistent secondary status icons are cleared.
4. the payload is built.
5. the payload is posted to `${API_BASE}${API_SUBMIT_JOB}`.

On a non-OK response, the component throws `API ${res.status}`.

On success:

1. response JSON is stored in `result` state.
2. if `data.job_id` exists, `jobId` is set.
3. `startTracking(data.job_id)` begins both polling and websocket status tracking.

On submit failure:

1. `error` is set to a string based on the thrown error.
2. `submitting` is set to `false`.
3. an error panel is displayed in red styling.

The `result` state is currently stored but not rendered directly.

## Backend Submit Response Shape

The only response field required by the current frontend is:

```json
{
  "job_id": "job-runner-id"
}
```

If `job_id` is missing, the frontend stores the response in `result` but does not start live status tracking or show the status accordion.

Other response fields may be returned by the backend, but `JobSubmissionPage.tsx` does not currently read them.

## Submitted Job Flow

The current submitted-job flow is contained inside `JobSubmissionPage.tsx`.

There is no separate submitted-jobs page in the frontend source.

After a successful submit response with `job_id`:

1. the status accordion appears with title `Status: ${jobStatus}`
2. `JobStatusFlow` displays the icon-based progress row
3. job logs are displayed in a read-only textarea when log lines exist
4. the component continues to stream or poll status until terminal state
5. when status becomes `DONE`, the footer button changes to `View Analysis Results`
6. clicking `View Analysis Results` calls `viewAnalysisResultsPage`
7. `JobRunnerMain.tsx` transitions to the results screen using the saved job info

`setSavedJobInfo()` is called on every status update. The saved object includes:

```ts
{
  jobId: id,
  jobStatus: nextStatus || "",
  jobLog: nextLog,
  referencedBy: statusData?.referenced_by || undefined,
  run_duration: statusData?.run_duration || undefined,
  functions: statusData?.functions || fallbackFunctions
}
```

`ResultsPage.tsx` depends on `savedJobInfo.referencedBy?.[0]` as the NVFlare job ID used for result loading.

## Job Status Polling

Both `JobSubmissionPage.tsx` and `JobHistoryTable.tsx` support polling through:

```text
POST ${API_BASE}/jobs/status
```

The route suffix is exported as:

```ts
export const API_JOB_STATUS = "/jobs/status";
```

### Submission Page Polling

`JobSubmissionPage.startPollingLoop(id)` polls every `500` ms.

Request body:

```json
{
  "job_id": "job-runner-id",
  "$pw": "optional-secret-from-REACT_APP_MYSQL_SECRET_PW"
}
```

Response fields read by the component:

| Field | Use |
| --- | --- |
| `status` | Current job status. |
| `log` | Array of log lines shown in the status textarea. |
| `referenced_by` | Saved into `savedJobInfo.referencedBy`; used later by results loading. |
| `run_duration` | Saved into `savedJobInfo.run_duration`. |
| `functions` | Saved into `savedJobInfo.functions`. |

Polling stops when:

- websocket streaming becomes active
- status reaches terminal `DONE` or `FAILURE`
- polling request fails
- component unmounts or tracking is stopped

On polling error, polling is cleared, `submitting` is set to `false`, and `error` becomes `Error polling job status: ...`.

### Job History Polling

`JobHistoryTable.startPollingLoop(job)` also polls every `500` ms.

Request body:

```json
{
  "job_id": "job.job_runner_id"
}
```

The response is converted into table log entries through `mapLogLinesToEntries()` and applied through `applyLiveStatusUpdate()`.

Polling stops when:

- a different job is being tracked
- websocket streaming becomes active
- status reaches terminal `DONE` or `FAILURE`
- polling request fails

When a terminal status arrives, the table clears polling, closes the websocket, and calls `refreshJob(job)` to reload the durable job history row.

## Websocket Handling

The frontend has websocket live status implementations in:

- `src/features/job_runner/pages/JobSubmissionPage.tsx`
- `src/features/job_history/components/JobHistoryTable.tsx`

Both files currently define local constants:

```ts
const WEB_SOCKET = true;
const POLL_INTERVAL = 500;
const API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws";
```

`JobSubmissionPage.tsx` has `WEB_SOCKET_DEBUG = false`.

`JobHistoryTable.tsx` has `WEB_SOCKET_DEBUG = true`.

Although `Constants.tsx` exports `API_JOB_STATUS_WEBSOCKET`, both files currently define their own local `API_JOB_STATUS_WEBSOCKET` constant instead of importing that exported constant.

## Websocket URL Construction

Both websocket implementations use the same URL-building logic.

For local/dev targets, the frontend uses:

```text
${API_BASE}/jobs/status/ws/local/${encodeURIComponent(jobId)}
```

Then it converts protocol:

- `https://` to `wss://`
- `http://` to `ws://`

If no HTTP scheme is present, it uses the current browser location protocol to choose `wss://` or `ws://` and appends the path to `window.location.host`.

For non-local targets, the frontend uses:

```text
${WS_API_BASE}?job_id=${encodeURIComponent(jobId)}
```

`Constants.tsx` defines:

```ts
export const PROD_FALLBACK_API_WS_BASE = "wss://ws.example.org/prod";
```

`WS_API_BASE` currently resolves as:

```ts
export const WS_API_BASE =
  process.env.NODE_ENV === "development"
    ? LOCAL_API_BASE
    : process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_WS_BASE;
```

Because production `WS_API_BASE` prefers `REACT_APP_API_BASE`, websocket production configuration must ensure this variable is websocket-compatible when used for status streaming. Otherwise the fallback websocket base is used only when `REACT_APP_API_BASE` is absent.

## Websocket Message Format

Both websocket implementations expect JSON messages.

Recognized fields:

| Field | Meaning |
| --- | --- |
| `type` | Message type. Expected values include `job_status`, `heartbeat`, and `job_status_error`. |
| `status` | Current job status. |
| `log` | Array of log lines. |
| `referenced_by` | NVFlare job ID/reference list for results lookup. Used by submission flow. |
| `run_duration` | Runtime duration display value. |
| `functions` | Function list for results/history display. |
| `requires_ack` | When true, frontend sends acknowledgement over the websocket. |
| `message_id` | ID echoed back in acknowledgement payload. |

Acknowledgement payload:

```json
{
  "type": "ack",
  "message_id": "message-id-from-backend"
}
```

The acknowledgement is sent only when:

- `requires_ack` is truthy
- `message_id` exists
- websocket `readyState` is `WebSocket.OPEN`

## Websocket Message Behavior

### `heartbeat`

Heartbeat messages are ignored after optional debug logging.

### `job_status`

A `job_status` message is treated as the normal live update.

The frontend:

1. marks websocket streaming as active
2. clears polling
3. applies status/log/run-duration/function/reference data
4. stops tracking when status is terminal

### `job_status_error`

The two frontend implementations handle `job_status_error` differently.

In `JobSubmissionPage.tsx`:

- logs the error to console
- marks websocket streaming as false
- closes the websocket
- falls back to polling if the latest status is not terminal

In `JobHistoryTable.tsx`:

- marks websocket streaming as true
- clears polling
- applies the status update
- stops live tracking
- refreshes the job row from history

### Unknown message types

Messages whose `type` is not `job_status`, `heartbeat`, or `job_status_error` are ignored after optional debug logging.

## Websocket Error and Close Behavior

### Submission Page

On websocket error:

- if the close/error was intentional, do nothing
- if websocket streaming had already started and latest status is not terminal, start polling
- close the websocket

On websocket close:

- clear `wsRef` when it points to the closed socket
- mark websocket connected false
- if close was intentional, do nothing else
- if streaming had started and status is not terminal, start polling
- if streaming had started and the job is still non-terminal, show `Job status stream closed unexpectedly.` or the close reason

On message parse/processing error:

- if streaming has not started, close the websocket and return
- otherwise set `submitting` false, show `Error processing streamed job status.`, start polling, and close websocket

### Job History Table

On websocket error:

- if the close/error was intentional, do nothing
- if the same job is still tracked, streaming had started, and status is not terminal, start polling
- close the websocket

On websocket close:

- clear `wsRef` when it points to the closed socket
- mark websocket connected false
- if close was intentional, do nothing else
- if the same job is still tracked, streaming had started, and status is not terminal, start polling

On message parse/processing error:

- if streaming has not started and the same job is still tracked, close websocket and return
- if the same job is still tracked and status is not terminal, start polling
- close websocket

## Polling Fallback Behavior

`startTracking()` in `JobSubmissionPage.tsx` starts polling first, then opens the websocket.

```ts
startPollingLoop(id);
startWebSocketStream(id);
```

`startLiveTracking()` in `JobHistoryTable.tsx` follows the same pattern.

This means polling is the immediate fallback path and also covers the gap before a websocket begins streaming. Once the websocket receives a valid `job_status` message, `websocketStreamingRef.current` becomes true and polling is cleared.

Polling resumes only when websocket streaming had started and the stream fails before a terminal status, or when `JobSubmissionPage` receives `job_status_error` and the latest status is not terminal.

## Status Display and Status Value Map

`JobSubmissionPage.tsx` contains local status visualization data.

Primary status flow:

| Key | Label | Icon file |
| --- | --- | --- |
| `checking-client-participation` | Checking Client Participation | `checking-client-participation.png` |
| `job-defining` | Job Defining | `job-defining.png` |
| `job-broadcast` | Job Broadcast | `job-broadcast.png` |
| `job-received` | Job Received | `job-received.png` |
| `interactive-key-generation` | Interactive Key Generation | `interactive-key-generation.png` |
| `client-compute` | Client Compute | `client-compute.png` |
| `server-compute` | Server Compute | `server-compute.png` |
| `collaborative-decryption` | Collaborative Decryption | `collaborative-decryption.png` |
| `client-results` | Client Results | `client-results.png` |
| `server-results` | Server Results | `server-results.png` |
| `done` | Done | `done.png` |

Secondary status visuals:

| Key | Label | Icon file |
| --- | --- | --- |
| `participation-failed` | Participation Failed | `participation-failed.png` |
| `participation-empty` | Participation Empty | `participation-empty.png` |
| `analysis-failure` | Analysis Failure | `analysis-failure.png` |
| `threshold-not-met` | Threshold Not Met | `threshold-failure.png` |
| `failure` | Failure | `failure.png` |
| `warning` | Warning | `warning.png` |
| `error` | Error | `error.png` |

`normalizeStatusKey()` converts backend status/log strings to these keys by lowercasing, replacing underscores/hyphens with spaces, normalizing whitespace, and applying an alias map.

Important aliases include:

| Backend/log text | Normalized key |
| --- | --- |
| `queued` | `queued` |
| `processing` | `processing` |
| `checking client participation` | `checking-client-participation` |
| `broadcasting participation job` | `checking-client-participation` |
| `monitoring participation responses` | `checking-client-participation` |
| `client participation established` | `client-participation-established` |
| `participation failed` | `participation-failed` |
| `no clients accepted participation` | `participation-empty` |
| `processing filters` | `job-defining` |
| `ssh connecting` | `job-defining` |
| `ssh connected` | `job-defining` |
| `uploading nvflare job` | `job-defining` |
| `defining nvflare job` | `job-defining` |
| `broadcasting nvflare job` | `job-broadcast` |
| `job broadcast received` | `job-received` |
| `interactive key generation` | `interactive-key-generation` |
| `executing keygen workflow` | `interactive-key-generation` |
| `client compute` | `client-compute` |
| `server compute` | `server-compute` |
| `client encryption processing` | `client-compute` |
| `server encryption processing` | `server-compute` |
| `client performing analysis` | `client-compute` |
| `server performing analysis` | `server-compute` |
| `collaborative decryption` | `collaborative-decryption` |
| `client processing results` | `client-results` |
| `server processing results` | `server-results` |
| `performing analysis` | `job-analysis` |
| `aggregating job results` | `job-results` |
| `threshold not met` | `threshold-not-met` |
| `analysis failure` | `analysis-failure` |
| `failure` | `failure` |
| `warning` | `warning` |
| `error` | `error` |
| `done` | `done` |
| `parameters loaded` | `server-compute` |
| `preprocessing (reference)` | `server-analysis` |
| `preprocessing (encrypted)` | `client-compute` |
| `encrypting local statistics` | `client-compute` |
| `post-processing` | `client-results` |
| `results written to json` | `client-results` |
| `aggregating results from all sources` | `server-results` |
| `aggregation complete; running analysis` | `server-analysis` |
| `writing aggregated results to json` | `server-results` |
| `threshold limit not met` | `threshold-not-met` |
| `exception encountered` | `error` |
| `workflow started` | `client-analysis` |
| `received encrypted ciphertexts` | `server-compute` |
| `loading filters / resolving data paths` | `server-compute` |
| `preprocessing local data` | `client-analysis` |
| `validating model artifacts` | `server-compute` |
| `aggregating encrypted results` | `server-compute` |
| `aggregation complete; sending ciphertext` | `server-compute` |
| `receiving partial decryptions` | `collaborative-decryption` |
| `decrypting aggregated results` | `collaborative-decryption` |
| `risk scores ready; sending to persistor` | `server-results` |
| `validating workflow arguments` | `server-compute` |
| `loading schema metadata` | `server-compute` |
| `validating openfhe parameters` | `server-compute` |
| `saved risk scores` | `server-results` |

If no alias matches, the normalized text is returned with spaces replaced by hyphens.

## Secondary Status Detection

`detectSecondaryStatuses(jobStatus, jobLog)` scans both the current status and all log lines.

Detected secondary statuses are kept in `persistentSecondaryKeys`, so warnings/failures remain visible even if the primary status moves forward.

Additional log-line checks add secondary icons when the lowercased log line contains:

- `exception encountered`
- `threshold limit not met`
- `participation failed`
- `no clients accepted participation`
- `analysis failure`
- ` warning`
- ` failure`
- ` error`

## Terminal Status Rules

`JobSubmissionPage.tsx` treats only these statuses as terminal:

- `DONE`
- `FAILURE`

`JobHistoryTable.tsx` has two status helpers:

`isTerminalStatus()` returns true only for:

- `DONE`
- `FAILURE`

`shouldLiveTrackJob()` decides whether an expanded history row should start live tracking. It returns false when status is empty or when uppercase status is:

- `FINISHED:COMPLETED`
- contains `COMPLETED`
- contains `FAILED`
- contains `CANCELLED`
- contains `ABORTED`

This means history rows with completed, failed, cancelled, or aborted status are not live-tracked. They can still display logs loaded from `POST /jobs/status` when expanded.

## UI Behavior by Job State

| State | Submission page behavior | History table behavior | Results page behavior |
| --- | --- | --- | --- |
| Before submit | Shows client snapshot, submission overview, and submit/footer controls. No status accordion. | Not involved. | Not involved. |
| Submitting | Submit button text becomes `Submitting...`; button disabled. | Not involved. | Not involved. |
| Running/non-terminal | Status accordion appears once `job_id` exists. Polling and websocket tracking run. Logs append in textarea. | Expanded log panel can live-track if status is not completed/failed/cancelled/aborted. | Not available from submission flow until `DONE`. |
| `DONE` | Stops tracking, shows `View Analysis Results`. | Stops live tracking and refreshes row from history. | Loads job info, workflow mappings, results, function config, metrics, filters, and export sections. |
| `FAILURE` | Stops tracking, shows disabled `Failure Occurred` button. Secondary failure/error icons may remain visible. | Stops live tracking and refreshes row from history. | Results page is not reached from the submission footer. History may still allow details/log review depending on table actions. |
| Cancelled/aborted | Not explicitly terminal in `JobSubmissionPage.tsx` unless backend maps to `FAILURE`. | Not live-tracked because `shouldLiveTrackJob()` excludes statuses containing `CANCELLED` or `ABORTED`. | Not specially handled unless result endpoints return data/errors. |
| Missing `job_id` in submit response | Stores response in `result`, but does not open status tracking or show status accordion. | Not involved. | Not reachable from submission flow. |
| Missing `referenced_by` in status response | Status display can still update, but `ResultsPage` will have no `nvflareJobId` because it reads `savedJobInfo.referencedBy?.[0]`. | Not directly affected. | Results loading returns early when there is no `nvflareJobId`. |

## Job History Endpoint

`JobHistoryTable.fetchJobs()` calls:

```text
POST ${API_BASE}/nvflare/jobs/history
```

Request body:

```json
{
  "project_id": 1,
  "function_names": ["SURVIVAL_ANALYSIS", "MEAN"],
  "filter_mode": "ANY",
  "date_filter": {
    "mode": "AFTER",
    "create_date": "2026-04-08"
  }
}
```

Response field read:

```json
{
  "nvflare_jobs": []
}
```

`JobHistoryTable` defaults the date filter to the last 30 days using UTC date formatting. Supported frontend filter modes are `ANY` and `ONLY`. Supported date modes are `ON`, `AFTER`, and `BEFORE`.

`fetchJobs()` shows loading through `RefreshablePanel`. On error, it logs `Failed to fetch NVFlare jobs:` and clears the table to an empty list.

## Job History Row Refresh

`refreshJob(job)` re-calls `/nvflare/jobs/history` with the current query settings, finds the matching job by numeric `id`, and merges the fresh row into state.

It is used after terminal live status and when expanding rows.

If the row is currently expanded, `refreshJob()` also reloads logs through `/jobs/status`.

## Result Loading Contracts

`ResultsPage.tsx` does not call the result endpoints directly. It uses `JobsDataUtils.tsx`.

The session controls which API base the per-workflow helpers use:

```ts
role !== UserRole.CLIENT ? API_BASE : getClientApiBase(client_name)
```

Client users call their local results agent for workflow mapping and workflow results. Other roles call `API_BASE`, and so do `fetchNVFlareJobInfo` and the function config fallback for every role.

### Job Info

`fetchNVFlareJobInfo(nvflareJobId, jobApiSession)` calls:

```text
POST /jobs/info
```

Request body:

```json
{
  "nvflare_job_id": "nvflare-job-id"
}
```

Response shape read:

```ts
type JobInfoResponse = {
  job?: NVFlareJob | null;
  error?: string;
};
```

If `error` is present, the utility throws. Otherwise it returns `job ?? null`.

`ResultsPage.tsx` catches job-info load failure, logs a warning, and continues loading results using `savedJobInfo.functions` when needed.

### Workflow Mapping

`fetchWorkflowMapping(nvflareJobId, funcName, role)` calls:

```text
POST /jobs/results/mapping
```

Request body:

```json
{
  "nvflare_job_id": "nvflare-job-id",
  "function": "SURVIVAL_ANALYSIS"
}
```

Response shape read:

```ts
type MappingResponse = {
  workflow_dirs?: string[];
  profile_summary?: ProfileSummary;
  error?: string;
};
```

If `error` is present, the utility throws.

The frontend sorts workflow IDs with `sortWorkflowIds()`. That sorter gives numeric order to IDs matching `workflow_stat_analytics_(\d+)`; all other IDs retain stable relative order after numeric matches.

`profile_summary`, when present, is enhanced with `combined_workflow_metrics` derived from workflow metrics.

### Job Results

`fetchJobResultsForWorkflow(nvflareJobId, funcName, workflowId, role)` calls:

```text
POST /jobs/results
```

Request body:

```json
{
  "nvflare_job_id": "nvflare-job-id",
  "function": "SURVIVAL_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Response shape read:

```ts
type JobResultsResponse = {
  job_data?: JobsDataShape;
  function_config?: FunctionConfig;
  error?: string;
};
```

If `error` is present, the utility throws.

The utility returns:

```ts
{
  jobData: JobsDataShape,
  functionConfig: FunctionConfig | null,
  workflowError: WorkflowErrorJson | null
}
```

If `function_config` is missing or empty, the utility falls back to the function-config endpoint.

### Function Config Fallback

`fetchFunctionConfigForWorkflow(nvflareJobId, funcName, workflowId, role)` calls:

```text
POST /jobs/function/config
```

Request body:

```json
{
  "nvflare_job_id": "nvflare-job-id",
  "function": "SURVIVAL_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Response shape read:

```ts
type FunctionConfigResponse = {
  function_config?: FunctionConfig;
  error?: string;
};
```

`Constants.tsx` defines this endpoint as a route suffix like the other result constants:

```ts
export const API_JOB_RESULTS_FUNCTION_CONFIG = "/jobs/function/config";
```

`JobsDataUtils.tsx` then calls:

```ts
postJson(`${API_BASE}${API_JOB_RESULTS_FUNCTION_CONFIG}`, ...)
```

The fallback targets `API_BASE` for every role, including a `CLIENT` session whose workflow results were served by a client results agent.

## Results Page Loading Behavior

`ResultsPage.tsx` uses `savedJobInfo.referencedBy?.[0]` as `nvflareJobId`.

If no `nvflareJobId` exists, the load effect returns without fetching result data.

When loading starts, it clears previous workflow states and shows three progress bars:

1. NVFlare Job Information
2. Workflow Mapping
3. Workflow Results Data

Load order:

1. load job info with `/jobs/info`
2. determine functions from `loadedJobInfo.functions`, falling back to `savedJobInfo.functions`
3. load workflow mapping for each supported result function
4. load workflow result data for each workflow ID
5. optionally load function config fallback per workflow
6. attach workflow title suffixes for workflow IDs containing `__`
7. set workflow arrays for survival, mean, standard deviation, chi-square, and t-test
8. set profile/system metrics when available

Supported result function display order:

1. `SURVIVAL_ANALYSIS`
2. `MEAN`
3. `STANDARD_DEVIATION`
4. `CHI_SQUARE_TEST`
5. `T_TEST`

Errors during result loading are displayed in a red-bordered panel using `loadError`.

## Types Used by Status and Results

`JobLogData` is the bridge from live submission tracking into the results page:

```ts
export interface JobLogData {
  jobId?: string;
  jobStatus?: string;
  jobLog?: string[];
  referencedBy?: string[];
  run_duration?: string;
  functions?: string[];
}
```

`NVFlareJob` is the durable job history/result record shape:

```ts
export interface NVFlareJob {
  id: number;
  nvflare_assigned_id?: string;
  filter_id?: number;
  status?: string;
  job_path?: string;
  output_path?: string;
  job_runner_id?: string;
  non_contributing_clients?: string | null;
  exclude_analyzing_clients?: string | null;
  submit_time?: string;
  run_duration?: string;
  create_date: string;
  update_date: string;
  completed_date?: string;
  functions?: string[];
  functions_map?: Record<string, Record<string, string> | Record<string, string>[]>;
  threshold?: ThresholdPayload;
  crypto_audit_record?: CryptoAuditRecord;
  datasource_group_id?: number | null;
  datasource_group_name?: string | null;
  datasource_log?: DatasourceLogPayload;
  workflow_group_data?: Record<string, string[]>;
  workflow_groups?: WorkflowGroupSelection[];
}
```

## Known Implementation Notes

- `JobSubmissionPage.tsx` and `JobHistoryTable.tsx` duplicate websocket URL construction and local websocket constants.
- `Constants.tsx` exports `API_JOB_STATUS_WEBSOCKET`, but the two websocket callers use local `API_JOB_STATUS_WEBSOCKET` constants.
- `WEB_SOCKET` is a hardcoded local constant, not an environment-driven feature flag.
- `JobSubmissionPage.tsx` terminal handling only recognizes `DONE` and `FAILURE`; cancelled or aborted statuses must be mapped by the backend or they may remain non-terminal in the submission screen.
- `JobHistoryTable.tsx` uses broader logic to avoid live-tracking statuses containing `COMPLETED`, `FAILED`, `CANCELLED`, or `ABORTED`.
- `API_JOB_RESULTS_FUNCTION_CONFIG` is defined as a full URL but is used as though it were a route suffix in `JobsDataUtils.tsx`; this should be verified.
- The original outline references `ExecutionStep.ts`, but no such file exists in the provided frontend source.
