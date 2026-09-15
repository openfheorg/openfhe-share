# Job History and Results Flow

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_history/JobHistoryMain.tsx` | Main entrypoint for the job history feature. Owns the feature-level `jobHistory` versus `results` screen state. |
| `src/features/job_history/components/JobHistoryTable.tsx` | Job history table, job query filters, row expansion, status/log loading, websocket/polling live log updates, and result opening. |
| `src/features/job_history/pages/ResultsPage.tsx` | Results viewer page for selected/completed jobs. Loads job info, workflow mappings, workflow result payloads, function config, metrics, and export sections. |
| `src/features/job_history/utils/JobsDataUtils.tsx` | Utility functions for loading job info, workflow mapping, workflow results, function config fallback, workflow errors, metrics summaries, and display labels. |
| `src/features/job_history/components/AnalyticsMetricsAccordion.tsx` | Displays system and workflow metrics returned with profile summary data. |
| `src/features/job_history/components/NVFlareJobSummary.tsx` | Displays job summary metadata at the top of the results page and can render function links to result sections. |
| `src/features/job_history/components/ResultCard.tsx` | Renders scalar/statistical result cards for mean, standard deviation, chi-square, and t-test workflows. |
| `src/features/job_history/components/SurvivabilityComponent.tsx` | Renders survival analysis result sections, Kaplan-Meier plots, workflow selectors, and survival-related tables. |
| `src/features/job_history/components/FilterSummarySection.tsx` | Expandable job-history row section for a saved filter. |
| `src/features/job_history/components/FunctionConfigSection.tsx` | Expandable job-history row section for submitted function configuration. |
| `src/features/job_history/components/ThresholdConfigSection.tsx` | Expandable job-history row section for threshold configuration. |
| `src/features/job_history/components/DatasourceSelectionSection.tsx` | Expandable job-history row section for datasource group information logged with the job. |
| `src/features/job_history/components/WorkflowGroupSelectionSection.tsx` | Expandable job-history row section for workflow group selections logged with the job. |
| `src/features/job_history/components/ParticipationSection.tsx` | Expandable job-history row section for non-contributing and excluded analyzing clients. |
| `src/features/job_history/components/EncryptionParamsSection.tsx` | Expandable job-history row section for crypto audit parameters. |
| `src/features/job_history/components/LogOutputSection.tsx` | Expandable job-history row section for backend job logs. Opens live tracking when applicable. |
| `src/features/job_history/components/ColumnConfigModal.tsx` | Modal used to select up to three function configuration fields as extra job history table columns. |
| `src/features/job_history/components/export/` | Export modal, section registry, and export context used by the results page. |
| `src/features/job_history/utils/ExportDocTypes.tsx` | Shared export document/section type definitions. |
| `src/features/job_history/utils/ExportDocumentRenderUtils.tsx` | Shared document rendering helpers used by export formats. |
| `src/features/job_history/utils/ExportPdfUtils.tsx` | PDF export implementation. |
| `src/features/job_history/utils/ExportDocxUtils.tsx` | Word/docx export implementation. |
| `src/features/job_history/utils/ExportHtmlUtils.tsx` | HTML export implementation. |
| `src/features/job_history/utils/ExportPngUtils.tsx` | PNG export implementation. |
| `src/constants/Constants.tsx` | Backend endpoint constants used by job history and results. |
| `src/types/JobsDataTypes.tsx` | Job history/result TypeScript interfaces. |
| `src/components/HeaderTitle.tsx` | Shared title/header text component used by `JobHistoryMain.tsx`. |
| `src/components/FilterSummary.tsx` | Shared filter summary display used on the results page and export. |

## Feature Role

The job history feature lets users review submitted jobs, inspect status/log output, open completed results, and export result/report sections.

The feature connects submitted NVFlare jobs back to:

- selected project
- saved filter set
- submitted function configuration
- threshold configuration
- selected datasource group
- selected workflow group options
- contribution/analyzing exclusions
- crypto audit parameters
- job logs and runtime duration
- workflow mappings and per-workflow result payloads
- profile/system metrics
- exportable report sections

## Job History Entrypoint

`src/features/job_history/JobHistoryMain.tsx` is the top-level job history coordinator.

### Props

| Prop | Type | Purpose |
| --- | --- | --- |
| `setMainScreen` | `(screen: AppScreen) => void` | Moves the app within the current top-level screen vocabulary; Job History and Results are normally embedded in `SHARELandingPage`. |
| `project` | `Project` | Selected project metadata, including available functions and project ID. |

### Local Types and Constants

`JobHistoryMain.tsx` defines:

```ts
type JobHistoryScreen = "jobHistory" | "results";
```

It also defines blank fallback objects used when results are opened without populated filter/job state:

```ts
export const BLANK_FILTER_CONFIG: FilterCollection = {
  patientQueryFilters: "{}",
  patientDataFilters: "{}",
  observationQueryFilters: "{}",
  observationDataFilters: "{}"
};
```

```ts
export const BLANK_JOB_DATA: JobLogData = {
  jobId: undefined,
  jobStatus: undefined,
  jobLog: [],
  referencedBy: [],
  run_duration: "",
  functions: []
};
```

### State

| State | Type/Initial Value | Purpose |
| --- | --- | --- |
| `screen` | `JobHistoryScreen`, initially `"jobHistory"` | Chooses between table view and results view. |
| `submittedFilterSet` | `FilterCollection | undefined` | Filter data reconstructed for the selected job before opening results. |
| `submittedFilterSetName` | `string | undefined` | Saved filter name displayed in results/filter summary. |
| `savedJobInfo` | `JobLogData`, initially `BLANK_JOB_DATA` | Minimal job context passed into `ResultsPage`. |
| `animate` | `boolean`, initially `true` | Re-triggers the page transition animation when the internal screen changes. |
| `viewOnly` | `boolean`, initially `false` | Marks results opened from history rather than from the submission flow. |
| `extraColumnKeys` | `string[]`, initially `[]` | Selected function config keys displayed as optional job history columns. |
| `availableExtraColumnKeys` | `string[]`, initially `[]` | Function config keys discovered from loaded jobs. |
| `openColumnConfig` | `boolean`, initially `false` | Controls the extra-column configuration modal. |

`extraColumnKeys` is persisted in `localStorage` using a key scoped to the selected project:

```ts
nvflare_job_history_extra_cols_v1:${project.id || "unknown"}
```

Only the first three selected extra columns are kept.

### Screen Flow

`JobHistoryMain.tsx` no longer renders its own navigation selector. In the main application path it is embedded inside `SHARELandingPage`, which keeps the selected project and Job History submenu state visible in the persistent left rail.

When `screen !== "results"`, it renders a `HeaderTitle` with:

- title: `Job History: <ProjectNameWithDescription project={project} />`
- description: `description_job_history`

When `screen === "results"`, it renders `ResultsPage`; Results owns its current title/header treatment.

The main content branch is:

| Internal Screen | Component | Important Props |
| --- | --- | --- |
| `jobHistory` | `JobHistoryTable` | `project`, `onStartNewAnalysis`, `onReturnToHome`, `onViewResults`, extra column state handlers. |
| `results` | `ResultsPage` | `submittedFilterSetName`, `submittedFilterSet`, `savedJobInfo`, `viewOnly`, `onBackToHistory`, `project`. |

### Opening Results from History

`attemptViewResults(job_data)` is called when `JobHistoryTable` invokes `onViewResults`.

The results button in the table is only enabled for:

```ts
FINISHED:COMPLETED
```

The opening flow is:

1. Check `job_data.filter_id`.
2. POST to `API_BASE + API_FILTERS_FETCH_SINGLE` with `{ filter_id, project_id }`.
3. Convert backend saved filter conditions using `buildDefaultFilterCollectionFromConditions(r.conditions || [], project)`.
4. Require `job_data.nvflare_assigned_id` before opening results.
5. Set `viewOnly` to `true`.
6. Set `savedJobInfo` with:
   - `jobId: job_data.job_runner_id`
   - `jobStatus: job_data.status`
   - `jobLog: []`
   - `referencedBy: [job_data.nvflare_assigned_id]`
   - `run_duration: job_data.run_duration`
   - `functions: job_data.functions`
7. Set `submittedFilterSetName` from the saved filter name.
8. Set `submittedFilterSet` from the converted filter collection.
9. Switch `screen` to `results`.

If the job does not have a filter ID, the saved filter cannot be reconstructed by this flow. If the job does not have `nvflare_assigned_id`, `ResultsPage` does not receive the NVFlare job ID needed to call result endpoints.

### Opening Results from a SHARE Client Launch Link

The top-level `App.tsx` direct-entry route is separate from `JobHistoryMain.attemptViewResults()`.

1. The SHARE Client opens the frontend with a pako-compatible `launch` payload containing `username` and `nvflare_job_id`.
2. `App.tsx` decodes the payload and removes launch fields from the visible URL.
3. `LoginPage` automatically calls `POST /user/role` with the supplied username.
4. `App.tsx` renders `ResultsPage` with `nvflareJobId`, `directEntry`, and `onContextLoaded`.
5. `ResultsPage` calls `POST /nvflare/jobs/results_context` instead of `/jobs/info`.
6. The response supplies the compact job summary, project, datasource-group context, and saved filter.
7. `App.tsx` derives the user's selected project datasources from the login session and resolved project.
8. Workflow mappings and workflow result bodies are then loaded through the same lazy endpoints used by normal history navigation.

Results opened through the internal Job History flow continue to load from the normal job/result endpoints; top-level direct/landing results use `/nvflare/jobs/results_context` to bootstrap project/filter/job context before loading the same workflow result endpoints.

## Job History Table

`src/features/job_history/components/JobHistoryTable.tsx` renders the job history list, query controls, row expansion sections, and live status/log tracking.

### Props

| Prop | Type | Default | Purpose |
| --- | --- | --- | --- |
| `project` | `Project` | required | Supplies selected project ID and function metadata. |
| `onStartNewAnalysis` | `() => void` | no-op | Sends the user to the job runner. |
| `onReturnToHome` | `() => void` | no-op | Returns the user to the selected project landing page through the outer landing workspace. |
| `onViewResults` | `(job: NVFlareJob) => void` | no-op | Opens completed job results. |
| `compact` | `boolean` | `false` | Renders only a compact banner for the most recent job. |
| `extraColumnKeys` | `string[]` | internal state | Controlled list of extra function config columns. |
| `onExtraColumnKeysChange` | `(keys: string[]) => void` | undefined | Controlled setter for extra columns. |
| `onOpenColumnConfig` | `() => void` | undefined | Opens `ColumnConfigModal` in the parent. |
| `onAvailableExtraColumnKeysChange` | `(keys: string[]) => void` | undefined | Reports discovered extra column candidates to the parent. |

### Local Constants

| Constant | Value | Purpose |
| --- | --- | --- |
| `SUCCESS_STATUS` | `"FINISHED:COMPLETED"` | Only status that enables View Results. |
| `PAGE_SIZE` | `10` | Number of jobs per page. |
| `WEB_SOCKET` | `true` | Enables websocket attempt when logs are opened for a live job. |
| `WEB_SOCKET_DEBUG` | `true` | Enables console logging for websocket events. |
| `POLL_INTERVAL` | `500` | Poll interval in milliseconds when polling live status. |
| `API_JOB_STATUS_WEBSOCKET` | `"/jobs/status/ws"` | Local websocket path used by the history table. |
| `DEFAULT_SELECTED_COLUMNS` | `cancer_type`, `model_type`, `time_grid_max` | Preferred extra columns if those keys exist in function config. |

### State

| State | Purpose |
| --- | --- |
| `jobs` | Loaded `NVFlareJob[]` history rows. |
| `expandedJobId` | Currently expanded job row key. |
| `openFilterSummaryFor` | Expanded filter summary section key. |
| `openConfigsFor` | Expanded function config section key. |
| `openLogsFor` | Expanded logs section key. |
| `openThresholdFor` | Expanded threshold section key. |
| `openDatasourceFor` | Expanded datasource section key. |
| `openWorkflowGroupsFor` | Expanded workflow group section key. |
| `openParticipationFor` | Expanded participation section key. |
| `openAuditFor` | Expanded crypto audit section key. |
| `jobLogs` | Map of job key to parsed log entries. |
| `loading` | Main history refresh/loading indicator. |
| `refreshingJobId` | Job row currently refreshing. |
| `page` | Current pagination page. |
| `filterText` | Quick text filter. |
| `supportedFunctions` | Function names derived from `project.functions`. |
| `selectedFunctions` | Function query filter checkbox map. |
| `filterMode` | Function filter mode, `ANY` or `ONLY`. |
| `initializing` | Initial load flag. |
| `createDateMode` | Date filter mode, `ON`, `AFTER`, or `BEFORE`; default is `AFTER`. |
| `createDate` | UTC date string, defaulting to 30 days before the current date. |
| `openQueryFilters` | Query configuration open/closed flag. |
| `uncontrolledExtraColumnKeys` | Internal extra column state when not controlled by parent. |

The component also uses refs for websocket/polling control:

- `pollRef`
- `wsRef`
- `intentionallyClosingWsRef`
- `websocketConnectedRef`
- `websocketStreamingRef`
- `latestTrackedStatusRef`
- `trackedJobKeyRef`

### History Query Request

History is loaded with:

```ts
POST `${API_BASE}${API_JOB_HISTORY}`
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

`function_names` comes from selected function query filters. `filter_mode` is `ANY` or `ONLY`. `date_filter.mode` is `ON`, `AFTER`, or `BEFORE`. The default date is generated as today's UTC date minus 30 days.

Expected response shape:

```json
{
  "nvflare_jobs": [
    {
      "id": 123,
      "nvflare_assigned_id": "job_abc",
      "filter_id": 10,
      "status": "FINISHED:COMPLETED",
      "job_runner_id": "runner_abc",
      "create_date": "2026-04-29T12:00:00",
      "update_date": "2026-04-29T12:05:00",
      "completed_date": "2026-04-29T12:05:00",
      "run_duration": "00:05:00",
      "functions": ["SURVIVAL_ANALYSIS"],
      "functions_map": {
        "SURVIVAL_ANALYSIS": [
          {
            "cancer_type": "Breast Cancer",
            "model_type": "cox_lasso"
          }
        ]
      },
      "datasource_log": {
        "project_id": 2,
        "datasource_group_id": 1,
        "datasource_group_name": "MSKChord"
      },
      "workflow_groups": [],
      "non_contributing_clients": "site-2",
      "exclude_analyzing_clients": "site-3"
    }
  ]
}
```

The table uses `data.nvflare_jobs || []` and falls back to an empty list on failure.

### Job Status/Log Request

Logs and live status use:

```ts
POST `${API_BASE}${API_JOB_STATUS}`
```

Request body:

```json
{
  "job_id": "runner_abc"
}
```

Expected response fields used by the frontend:

```json
{
  "status": "DONE",
  "log": ["[2026-04-29T12:00:00Z] Started job"],
  "run_duration": "00:05:00",
  "functions": ["SURVIVAL_ANALYSIS"]
}
```

Log lines are converted to `JobLogEntry[]` by parsing lines in this format:

```text
[timestamp] message
```

A line without that pattern is stored with an empty timestamp and the full line as the message.

### Table Columns

The main table columns are:

| Column | Source |
| --- | --- |
| Job | `job.id` plus expand/collapse caret. |
| Function(s) | `functions_map` keys if available; otherwise `job.functions`. Function names are title-cased for display. |
| Up to three extra columns | Selected dynamic keys from function config. Fixed project config keys are excluded. |
| Status | `job.status || "Not Available"`. |
| Created | `new Date(job.create_date).toLocaleString() + " UTC"`. |
| Actions | Row refresh button when expanded, plus `View Results`. |

The table includes a gear button to configure optional columns. The source keys come from non-fixed keys in `functions_map` and are normalized to lowercase.

### Quick Filter

The quick filter searches a lowercase string built from:

- `job.id`
- `job.nvflare_assigned_id`
- `job.status`
- `job.job_runner_id`
- `job.job_path`
- `job.output_path`
- `job.create_date`
- `job.update_date`
- `job.completed_date`
- function display values
- searchable function config values

Changing `filterText` resets the page to 1.

### Row Expansion

Clicking a row expands it. Pressing Enter or Space on a focused row also expands it.

Expanding a row:

1. Calls `refreshJob(job)`.
2. Sets `expandedJobId`.
3. Opens filter summary by default when the job has `filter_id`.
4. Closes the other sections.
5. Stops existing live tracking.
6. Loads logs if they are not already loaded.

Collapsing a row clears all open section keys and stops live tracking.

Expanded row sections are shown conditionally:

| Section | Component | Condition |
| --- | --- | --- |
| Filter Summary | `FilterSummarySection` | `!!job.filter_id` |
| Function Configuration | `FunctionConfigSection` | Always shown when expanded. |
| Threshold Configuration | `ThresholdConfigSection` | `!!job.threshold` or `threshold_config_id` exists. |
| Datasource Selection | `DatasourceSelectionSection` | `!!job.datasource_log` |
| Participation | `ParticipationSection` | `non_contributing_clients` or `exclude_analyzing_clients` has values. |
| Workflow Group Selection | `WorkflowGroupSelectionSection` | `job.workflow_groups?.length > 0` |
| Encryption Parameters | `EncryptionParamsSection` | `!!job.crypto_audit_record` |
| Log Output | `LogOutputSection` | Always shown when expanded. |

The expanded row also includes a Total Runtime Duration field and an Expand All/Collapse All button.

### Status and Live Tracking Rules

`shouldLiveTrackJob(status)` returns `false` when status is empty or already completed/failed/cancelled/aborted:

- exactly `FINISHED:COMPLETED`
- contains `COMPLETED`
- contains `FAILED`
- contains `CANCELLED`
- contains `ABORTED`

`isTerminalStatus(status)` currently returns `true` for:

- `DONE`
- `FAILURE`

Live tracking starts only when the Logs section is open for the expanded job and `shouldLiveTrackJob(job.status)` is true.

### Websocket and Polling Behavior

When live tracking starts, the table starts polling first and then opens a websocket if `WEB_SOCKET` is true.

The websocket URL is built by `buildJobStatusWebSocketUrl(jobId)`:

- For local development, it builds `${API_BASE}/jobs/status/ws/local/{jobId}` and converts `http://` to `ws://` or `https://` to `wss://`.
- For non-local API bases, it uses `${WS_API_BASE}?job_id={jobId}`.

Polling uses `/jobs/status` every 500 milliseconds. Polling stops if:

- the tracked job changes
- the websocket begins streaming
- a terminal status is received
- the request fails

Websocket messages are parsed as JSON. Expected websocket message fields include:

```json
{
  "type": "job_status",
  "status": "DONE",
  "log": ["[timestamp] message"],
  "run_duration": "00:05:00",
  "functions": ["SURVIVAL_ANALYSIS"],
  "requires_ack": true,
  "message_id": "message-1"
}
```

If `requires_ack` and `message_id` are present and the socket is open, the frontend sends:

```json
{
  "type": "ack",
  "message_id": "message-1"
}
```

Message type behavior:

| Message Type | Behavior |
| --- | --- |
| `heartbeat` | Logged in debug mode and ignored. |
| `job_status_error` | Applies status update, stops tracking, and refreshes the job row. |
| `job_status` | Applies logs/runtime/functions, stops polling, and refreshes the row on terminal status. |
| Other values | Ignored. |

On websocket message parsing errors, websocket errors, or unexpected close events, the component may fall back to polling when the socket had already been streaming and the latest tracked status is not terminal.

### Compact Mode

When `compact` is true, the table returns a `CompactBanner` for only the most recent job by `create_date`. If no jobs are loaded, it renders nothing. The banner displays:

- Created date/time with `UTC` suffix
- Status

## Job Types

`src/types/JobsDataTypes.tsx` defines the frontend job shapes used by history and results.

### NVFlareJob

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

### JobLogData

`ResultsPage` receives a smaller job context object from `JobHistoryMain`:

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

`referencedBy[0]` is treated as the NVFlare assigned job ID for result loading.

## Result Loading Flow

`src/features/job_history/pages/ResultsPage.tsx` loads result data after a completed job is opened.

### Props

| Prop | Type | Purpose |
| --- | --- | --- |
| `onBack` | `() => void` | Returns to submission details when not in view-only history mode. |
| `onStartOver` | `() => void` | Starts the flow over when not in view-only history mode. |
| `submittedFilterSet` | `FilterCollection` | Filter set displayed at the bottom of results and included in export. |
| `submittedFilterSetName` | `string` | Filter set name displayed with filter summary/export. |
| `savedJobInfo` | `JobLogData | undefined` | Normal-flow job context, including `referencedBy[0]` NVFlare job ID and functions. |
| `nvflareJobId` | `string | undefined` | Explicit NVFlare-assigned job ID used by the top-level direct-entry route. |
| `directEntry` | `boolean | undefined` | Selects `/nvflare/jobs/results_context` bootstrap instead of `/jobs/info`. |
| `onContextLoaded` | `((project: Project) => void) | undefined` | Lets `App.tsx` hydrate selected project and datasource context after direct bootstrap. |
| `viewOnly` | `boolean | undefined` | Controls footer buttons for history-opened results. |
| `onBackToHistory` | `() => void | undefined` | Returns from view-only results to job history. |
| `project` | `Project | undefined` | Selected project metadata; direct entry resolves it asynchronously. |

### State

| State | Purpose |
| --- | --- |
| `survivabilityWorkflows` | Loaded survival analysis workflow result objects. |
| `tTestWorkflows` | Loaded t-test workflow result objects. |
| `meanWorkflows` | Loaded mean workflow result objects. |
| `chi2Workflows` | Loaded chi-square workflow result objects. |
| `stDevWorkflows` | Loaded standard deviation workflow result objects. |
| `activeSurvIndex` | Active survival workflow index. |
| `activeMeanIndex` | Active mean workflow index. |
| `activeChi2Index` | Active chi-square workflow index. |
| `activeStDevIndex` | Active standard deviation workflow index. |
| `activeTTestIndex` | Active t-test workflow index. |
| `loading` | Result load in progress. |
| `loadError` | Result load error message. |
| `exportFormatModalOpen` | Controls export format modal. |
| `exportSectionModalOpen` | Controls export section selection modal. |
| `selectedExportFormat` | Selected export format: PDF, DOCX, HTML, or PNG. |
| `exportableSections` | Sections available for export after format selection. |
| `exporting` | Export generation/loading flag. |
| `profileSummary` | Profile/system metrics returned from workflow mapping. |
| `nvflareJobInfo` | Full job metadata loaded from `/jobs/info`. |
| `jobInfoProgress` | Progress bar state for job info load. |
| `mappingProgress` | Progress bar state for workflow mapping load. |
| `resultsProgress` | Progress bar state for workflow result load. |

### Supported Result Function Load Order

Results are loaded only for functions present in the job info or fallback `savedJobInfo.functions`.

The load order is:

1. `SURVIVAL_ANALYSIS`
2. `MEAN`
3. `STANDARD_DEVIATION`
4. `CHI_SQUARE_TEST`
5. `T_TEST`

### Endpoint Base Selection

`JobsDataUtils.tsx` uses `resolveResultsApiBase(userSession)`, which takes the session object `{ role, client_name }` built by `ResultsPage.tsx`:

```ts
role !== UserRole.CLIENT ? API_BASE : getClientApiBase(client_name)
```

Initiator and other roles load result endpoints from `API_BASE`. Client users load them from the results agent selected by `getClientApiBase(client_name)`: `CLIENT_API_BASE` for hosted deployments, or `http://127.0.0.1:${CLIENT_API_BASE_PORT + siteNumber}` for local development and standalone builds, where `site1` resolves to `8089`, `site2` to `8090`, and so on.

Only `fetchWorkflowMapping` and `fetchJobResultsForWorkflow` use that base. `fetchResultsContext`, `fetchNVFlareJobInfo`, and the function config fallback always use `API_BASE`.

### Results Endpoint Sequence

For a completed job, `ResultsPage` uses the explicit `nvflareJobId` prop when supplied, otherwise `savedJobInfo?.referencedBy?.[0]`.

The load sequence branches only for the initial metadata lookup:

1. Direct entry: `fetchResultsContext(nvflareJobId)`; normal history entry: `fetchNVFlareJobInfo(nvflareJobId, role)`
2. Determine functions from `loadedJobInfo.functions` or `savedJobInfo.functions`.
3. For each supported function present in the job:
   - `fetchWorkflowMapping(nvflareJobId, functionName, role)`
4. For each workflow ID returned by mapping:
   - `fetchJobResultsForWorkflow(nvflareJobId, functionName, workflowId, role)`
5. If workflow results do not include non-empty function config:
   - `fetchFunctionConfigForWorkflow(nvflareJobId, functionName, workflowId, role)` is attempted as a fallback.
6. Set workflow arrays by function.
7. Reset active workflow indices to 0.

### Job Info Request

`JobsDataUtils.tsx` defines the job info path locally:

```ts
const API_JOB_INFO = "/jobs/info";
```

Request:

```json
{
  "nvflare_job_id": "job_abc"
}
```

Expected response:

```json
{
  "job": {
    "id": 123,
    "nvflare_assigned_id": "job_abc",
    "status": "FINISHED:COMPLETED",
    "run_duration": "00:05:00",
    "functions": ["SURVIVAL_ANALYSIS"]
  }
}
```

If the response contains `error`, the utility throws that message. `ResultsPage` catches job info load errors separately, logs a warning, and continues with fallback functions from `savedJobInfo` when available.

### Workflow Mapping Request

Endpoint:

```ts
POST `${base}${API_JOB_RESULTS_MAPPING}`
```

Request:

```json
{
  "nvflare_job_id": "job_abc",
  "function": "SURVIVAL_ANALYSIS"
}
```

Expected response:

```json
{
  "workflow_dirs": ["workflow_stat_analytics__cox_lasso", "workflow_stat_analytics__logistic_reg"],
  "profile_summary": {
    "job_id": "job_abc",
    "site": "server",
    "role": "server",
    "extra": {},
    "workflows": {},
    "system_metrics": {
      "wall_time_sec": 300,
      "cpu_util_pct": 20,
      "cpu_user_pct": 10,
      "cpu_system_pct": 5,
      "cpu_iowait_pct": 0,
      "cpu_steal_pct": 0,
      "net_tx_bytes_total": 1000,
      "net_rx_bytes_total": 1000,
      "net_tx_mb_s": 0.1,
      "net_rx_mb_s": 0.1,
      "rss_max_kb": 100000
    }
  }
}
```

The utility sorts workflow IDs with numeric awareness for IDs matching:

```text
workflow_stat_analytics_(number)
```

Workflow IDs that do not match that numeric pattern are preserved after numeric IDs in original order.

If a profile summary is returned, the utility adds `combined_workflow_metrics` using `getCombinedWorkflowMetrics(profile_summary.workflows)`.

### Workflow Results Request

Endpoint:

```ts
POST `${base}${API_JOB_RESULTS}`
```

Request:

```json
{
  "nvflare_job_id": "job_abc",
  "function": "SURVIVAL_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Expected response:

```json
{
  "job_data": {},
  "function_config": {
    "cancer_type": "Breast Cancer",
    "model_type": "cox_lasso"
  }
}
```

If `job_data` is missing, the utility uses `{}`. If `function_config` is missing or empty, the function config fallback endpoint is attempted.

### Function Config Fallback Request

Endpoint constant:

```ts
API_JOB_RESULTS_FUNCTION_CONFIG = "/jobs/function/config"
```

`JobsDataUtils.tsx` calls:

```ts
postJson(`${API_BASE}${API_JOB_RESULTS_FUNCTION_CONFIG}`, body)
```

The fallback always targets `API_BASE`, even for a `CLIENT` session whose workflow results came from a client results agent.

Request body:

```json
{
  "nvflare_job_id": "job_abc",
  "function": "SURVIVAL_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Expected response:

```json
{
  "function_config": {
    "cancer_type": "Breast Cancer",
    "model_type": "cox_lasso"
  }
}
```

Errors from this fallback are swallowed inside `fetchJobResultsForWorkflow`; failed fallback simply leaves `functionConfig` as `null`.

### WorkflowJobData Shape

`JobsDataUtils.tsx` creates this result shape:

```ts
export type WorkflowJobData = {
  workflowId: string;
  functionName: string;
  jobData: JobsDataShape;
  functionConfig?: FunctionConfig | null;
  workflowError?: WorkflowErrorJson | null;
};
```

`ResultsPage` also attaches a display suffix derived from workflow IDs containing `__`. For example:

```text
workflow_stat_analytics__cox_lasso -> Cox Lasso
workflow_stat_analytics__logistic_reg -> Logistic Reg
```

### Workflow Error Detection

`getWorkflowErrorFromJobData(jobData)` checks explicit error fields first:

- `workflow_error`
- `workflowError`
- `error_json`
- `errorJson`
- `workflow_error_json`
- `workflowErrorJson`

It also checks common result containers:

- `initiator_results`
- `local_results`
- `local.local_results`
- `initiator_processed_results`
- `local_processed_results`
- `local.local_processed_results`

A workflow error is recognized when the object includes a non-empty string field such as `error`, `message`, `traceback`, or `exception_type`.

## Results Rendering

`ResultsPage` renders inside an `ExportProvider`.

The root result content is wrapped in:

```html
<div id="share-results-export-root" className="child-container-results-page">
```

This root is used for PNG export.

### Job Summary

At the top of the results page:

```tsx
<NVFlareJobSummary nvflareJob={nvflareJobInfo} enableFunctionLinks />
```

Function links use result section anchors with `scrollMarginTop: "6rem"`. Anchor IDs are built by normalizing the function name:

```text
result-function-survival-analysis
result-function-mean
result-function-standard-deviation
result-function-chi-square-test
result-function-t-test
```

### Loading UI

While loading, the page shows a `Loading Results Data` panel with three progress bars:

- NVFlare Job Information
- Workflow Mapping
- Workflow Results Data

Each progress state includes `completed`, `total`, and `label`.

### Error UI

If result loading fails, `loadError` is rendered in a white bordered panel with red text.

The high-level `load()` method catches thrown errors and uses:

```ts
err?.message || "Failed to load workflow results."
```

### Function Sections

Results render by available workflow arrays:

| Function | Component |
| --- | --- |
| `SURVIVAL_ANALYSIS` | `SurvivabilityComponent` |
| `T_TEST` | `TTestResultCard` |
| `MEAN` | `MeanResultCard` |
| `CHI_SQUARE_TEST` | `Chi2ResultCard` |
| `STANDARD_DEVIATION` | `StDevResultCard` |

Survival results render first when present. Scalar/statistical result cards are sorted by descending workflow count and then by title. Scalar result cards render in a grid:

- one result section: one column
- more than one result section: two columns

### System Metrics

If `profileSummary` exists, the page renders:

```tsx
<SystemMetricsAccordion
  metrics={profileSummary.system_metrics}
  combinedMetrics={profileSummary.combined_workflow_metrics}
  runDurationTime={runDurationTime}
  role={role}
/>
```

`runDurationTime` comes from `nvflareJobInfo.run_duration` first and then `savedJobInfo.run_duration`.

### Filters Overview

The page always renders:

```tsx
<FilterSummary submittedFilterSet={submittedFilterSet} submittedFilterSetName={submittedFilterSetName} />
```

This appears after metrics and is also included as an export section.

### Footer Buttons

When `viewOnly` is true, the footer buttons are:

- `Back to Job History`
- `Export As...`

When `viewOnly` is false, the footer buttons are:

- `Back to Submission Details`
- `Export As...`
- `⟳ Start Over`

`Export As...` is disabled while `loading` is true.

## Export Relationship

The results page builds exportable sections only after the user selects an export format.

Export flow:

1. User clicks `Export As...`.
2. `ExportFormatModal` opens.
3. User selects `pdf`, `docx`, `html`, or `png`.
4. The page collects registered sections from `useExportRegistry().getSections()`.
5. The page prepends a `Job Summary` section.
6. The page appends a `Filters Overview` section.
7. `ExportSectionSelectionModal` opens.
8. The user selects sections/options/workflows.
9. The page creates an `ExportDocument` with title `SHARE Job Results Export`.
10. The page calls the selected export utility.

The generated export filename uses:

```text
share-results-{YYYY-MM-DD-HH-MM-SS}.pdf|docx|html|png
```

`Filters Overview` is forced to the end of selected export sections before export.

### Job Summary Export Section

`buildJobSummaryExportSection()` collects any available values from `nvflareJobInfo` or `savedJobInfo` for:

- Job ID
- Status
- Project
- Submitted By
- Created
- Started
- Completed
- Functions

If none are available, it exports a paragraph saying no job summary details are available.

### Filters Overview Export Section

`buildFiltersOverviewExportSection()` exports:

- filter set name
- each filter collection group as a heading
- a table of flattened filter rows when values exist
- `No filters applied.` when a group is empty

## Backend Endpoints Used

| Endpoint | Constant / Definition | Caller | Purpose |
| --- | --- | --- | --- |
| `POST /nvflare/jobs/history` | `API_JOB_HISTORY` | `JobHistoryTable.fetchJobs`, `JobHistoryTable.refreshJob` | Load job history rows and refresh a single row from the latest history response. |
| `POST /jobs/status` | `API_JOB_STATUS` | `JobHistoryTable.fetchJobLogs`, polling loop | Load logs/runtime/functions and poll live job status. |
| `WEBSOCKET /jobs/status/ws/local/{job_id}` | local path in `JobHistoryTable` | `JobHistoryTable.startWebSocketStream` | Local websocket status stream. |
| `WEBSOCKET {WS_API_BASE}?job_id={job_id}` | `WS_API_BASE` | `JobHistoryTable.startWebSocketStream` | Non-local/API Gateway websocket status stream. |
| `POST /filters/fetch_single_filter` | `API_FILTERS_FETCH_SINGLE` | `JobHistoryMain.attemptViewResults` and `FilterSummarySection` | Load saved filter details by ID. |
| `POST /jobs/info` | local `API_JOB_INFO` in `JobsDataUtils.tsx` | `fetchNVFlareJobInfo` | Load selected NVFlare job metadata for normal Job History navigation. |
| `POST /nvflare/jobs/results_context` | `API_JOB_RESULTS_CONTEXT` | `fetchResultsContext` | Reconstruct compact job, project, datasource-group, and filter context for direct SHARE Client entry. |
| `POST /jobs/results/mapping` | `API_JOB_RESULTS_MAPPING` | `fetchWorkflowMapping` | Load workflow directories and optional profile/system metrics for a function. |
| `POST /jobs/results` | `API_JOB_RESULTS` | `fetchJobResultsForWorkflow` | Load per-function/per-workflow result payload and optional function config. |
| `POST /jobs/function/config` | intended path; current exported constant includes `API_BASE` | `fetchFunctionConfigForWorkflow` fallback | Load function config when result response does not include it. |

## Job ID Versus NVFlare Job ID Rules

The frontend uses several job identifiers:

| Field | Meaning / Usage |
| --- | --- |
| `NVFlareJob.id` | Numeric database row ID. Displayed in the table's Job column and used to match refreshed history rows. |
| `NVFlareJob.job_runner_id` | Backend runner/job status ID. Used for `/jobs/status` requests and live status tracking. |
| `NVFlareJob.nvflare_assigned_id` | NVFlare assigned job ID. Passed to `ResultsPage` as `savedJobInfo.referencedBy[0]` and used for `/jobs/info`, `/jobs/results/mapping`, and `/jobs/results`. |
| `JobLogData.referencedBy[0]` | Normal Job History source for the NVFlare job ID. |
| Direct `nvflareJobId` prop | SHARE Client launch-link source for the same NVFlare-assigned ID/job-folder UUID. |

The history row key used internally is:

```ts
job.job_runner_id || job.id.toString()
```

## Status Value Map

| Status Value / Pattern | Current UI Behavior |
| --- | --- |
| `FINISHED:COMPLETED` | Enables `View Results`; treated as not live-trackable. |
| Contains `COMPLETED` | Treated as not live-trackable. |
| Contains `FAILED` | Treated as not live-trackable. |
| Contains `CANCELLED` | Treated as not live-trackable. |
| Contains `ABORTED` | Treated as not live-trackable. |
| `DONE` | Treated as terminal for websocket/polling; triggers row refresh. |
| `FAILURE` | Treated as terminal for websocket/polling; triggers row refresh. |
| Empty/missing | Displays `Not Available`; not live-trackable. |
| Any other non-empty status | Displayed as-is; can be live-tracked when Logs section is open. |

## Error and Loading Behavior

### Job History Table

| Scenario | Behavior |
| --- | --- |
| Initial load | `initializing` and `loading` feed `RefreshablePanel` loading state. |
| History request fails | Error is logged to console and `jobs` becomes `[]`. |
| No jobs returned | Displays `No job history found.` |
| Quick filter has no matches | Displays `No jobs match your filter.` |
| Row refresh in progress | Expanded row refresh button is disabled and shows `…`. |
| Log fetch fails | Error is logged and the job's logs become `[]`. |
| Websocket parse/error/close | Debug logs are written when enabled; polling may resume if the socket had been streaming and the job is not terminal. |

### Results Page

| Scenario | Behavior |
| --- | --- |
| No `savedJobInfo.referencedBy[0]` | Load function returns without requesting results. |
| Job info request fails | Warning is logged; page can continue using `savedJobInfo.functions`. |
| Workflow mapping/results request fails | Load error panel is shown. |
| Function config fallback fails | Fallback failure is swallowed; `functionConfig` remains `null`. |
| No result sections and no error | Renders no empty-state message. |
| Export while results are loading | Export button is disabled. |

## Result Sections by Supported Function

| Supported Function | Result Page Section | Workflow-Aware | Export Integration |
| --- | --- | --- | --- |
| `SURVIVAL_ANALYSIS` | `SurvivabilityComponent` | Yes; receives `survivabilityWorkflows`, `activeSurvIndex`, and analytics workflows. | Registered through result/export components under the export provider. |
| `MEAN` | `MeanResultCard` | Yes; receives `meanWorkflows`, `activeMeanIndex`, and analytics workflows. | Registered through result/export components under the export provider. |
| `STANDARD_DEVIATION` | `StDevResultCard` | Yes; receives `stDevWorkflows`, `activeStDevIndex`, and analytics workflows. | Registered through result/export components under the export provider. |
| `CHI_SQUARE_TEST` | `Chi2ResultCard` | Yes; receives `chi2Workflows`, `activeChi2Index`, and analytics workflows. | Registered through result/export components under the export provider. |
| `T_TEST` | `TTestResultCard` | Yes; receives `tTestWorkflows`, `activeTTestIndex`, and analytics workflows. | Registered through result/export components under the export provider. |

## Known Implementation Notes

- Top-level navigation is state-driven through `App.tsx`; job history does not use URL routing.
- `JobHistoryMain.tsx` reconstructs results-page filter state by reloading the saved filter by `filter_id` before opening results.
- The results flow depends on `nvflare_assigned_id` for result endpoints, not the numeric history row ID.
- The history table's dynamic extra columns intentionally exclude project function `custom_configuration_fixed` keys.
- Live job tracking starts only when a live-trackable job's Log Output section is open.
- `API_JOB_RESULTS_FUNCTION_CONFIG` is exported as a full URL, but `JobsDataUtils.tsx` treats it like a path by prefixing it with `base`. This should be corrected before depending heavily on the fallback function-config request.
