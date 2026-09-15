# Job Runner Flow

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_runner/JobRunnerMain.tsx` | Main coordinator for the job runner workflow. |
| `src/features/job_runner/pages/filters/` | Filter creation, filter listing, and filter selection screens. |
| `src/features/job_runner/pages/workflow_group_selection/` | Workflow group selection screen. |
| `src/features/job_runner/pages/functions/` | Function selection screen. |
| `src/features/job_runner/pages/job_submission/` | Final job review/submission screen. |
| `src/features/job_runner/pages/submitted_jobs/` | Submitted job confirmation/status screen. |
| `src/features/job_runner/components/` | Job runner-specific shared components. |
| `src/features/job_runner/utils/` | Job runner helper utilities. |
| `src/components/FunctionSelector.tsx` | Shared function/workflow selector used by job runner screens. |
| `src/components/HeaderBar.tsx` | Shared header used inside job runner flow. |
| `src/components/FilterSummary.tsx` | Shared filter summary display. |
| `src/constants/Constants.tsx` | Backend API endpoint constants used by job runner calls. |

## Feature Role

The job runner feature is the frontend workflow for configuring and submitting a SHARE/NVFlare job.

It collects:

- selected project context
- selected datasource group context
- selected filters
- selected workflow group data
- selected function or functions
- threshold values
- contributing/analyzing party choices
- NVFlare client participation state

The final output of the flow is a job submission payload sent to the backend.

## Main Coordinator

`JobRunnerMain.tsx` coordinates the internal job runner page flow.

It is responsible for holding job-runner-level state and deciding which job runner page is currently visible.

This includes state related to:

- selected filters
- selected function configuration
- threshold values
- workflow group selections
- selected project/datasource context
- navigation between job runner pages
- final submission flow

The full state list should be documented when expanding this file.

## Expected Page Flow

The job runner flow is organized as a multi-step workflow.

The current flow should be documented around these stages:

1. Enter Job Runner from the main navigation screen.
2. Load or select filters.
3. Select workflow group options when applicable.
4. Select function/workflow execution options.
5. Review the final job submission configuration.
6. Submit the job to the backend.
7. Show submitted job confirmation/status context.

## Filter Step

Filter pages live under:

- `src/features/job_runner/pages/filters/`

This section should document:

- how filters are loaded
- how filter configuration is rendered
- how selected filter values are stored
- how filter values are transformed into backend payload format
- how saved/existing filter behavior works
- how the filter summary is displayed in later screens

Filter payload logic is documented more deeply in `08-filter-screens-and-payload-building.md`.

## Workflow Group Step

Workflow group selection lives under:

- `src/features/job_runner/pages/workflow_group_selection/`

This step supports project-level grouped workflow choices, such as selecting modeling methods or related execution options.

This section should document:

- where workflow group data comes from
- how options are displayed
- how selected options are stored
- whether at-least-one selection is enforced
- how selected workflow groups affect the final job submission payload

Workflow group behavior is documented more deeply in `09-workflow-group-selection.md`.

## Function Selection Step

Function selection lives under:

- `src/features/job_runner/pages/functions/`
- `src/components/FunctionSelector.tsx`

This step determines which configured backend/NVFlare function or workflow the job will run.

This section should document:

- how supported functions are fetched
- how functions are displayed
- how a function is selected
- how function config is carried into submission
- how function choice interacts with workflow group choice

## Job Submission Step

The final submission screen lives under:

- `src/features/job_runner/pages/job_submission/`

This step assembles the payload for the backend `/nvflare/jobs/submit` endpoint.

The payload should include the project, user, datasource group, filters, threshold, selected function/workflow configuration, workflow group data, and participation-related exclusions.

This section should document:

- full payload shape
- where each payload field comes from
- frontend validation before submit
- submit button disabled conditions
- loading/error behavior
- response handling after submission

## Submitted Job Step

Submitted job display lives under:

- `src/features/job_runner/pages/submitted_jobs/`

This step confirms job submission and may show submitted job context or link the user into job status/history behavior.

This section should document:

- submitted job response shape
- what is displayed after submit
- how the user navigates back
- how the user reaches job history/results after submission

## Backend Endpoints Used

The job runner feature uses backend endpoints for:

- supported functions
- filters
- client connection status
- client participation status
- participation submission
- NVFlare job submission

The exact constants and caller files should be documented in `04-api-configuration-and-backend-contracts.md`.

## Implementation Details Verified From Source

### Internal Page/State Machine

`JobRunnerMain.tsx` uses an internal in-memory screen union named `JobRunnerScreen`:

```ts
type JobRunnerScreen =
  | "filterHistory"
  | "patientFilters"
  | "variantTable"
  | "workflow_groups"
  | "functionSelection"
  | "submit_function"
  | "results";
```

The first screen is `filterHistory`.

`JobRunnerMain.tsx` does not use URL routing or React Router for this workflow. It computes an ordered screen list from the selected project configuration:

```ts
const orderedScreens = useMemo<JobRunnerScreen[]>(() => {
  const s: JobRunnerScreen[] = ["filterHistory"];
  if (supportsPatientScreens) s.push("patientFilters");
  if (supportsObservationScreen) s.push("variantTable");
  if (supportsWorkflowGroups) s.push("workflow_groups");
  s.push("functionSelection", "submit_function", "results");
  return s;
}, [supportsPatientScreens, supportsObservationScreen, supportsWorkflowGroups]);
```

The project controls which optional screens appear:

| Condition | Source | Effect |
| --- | --- | --- |
| `supportsPatientScreens` | `project.filter_system_allowed_filter_types` contains `PATIENT_QUERY` or `PATIENT_DATA`, or the allowed list is missing/empty | Adds `patientFilters`. |
| `supportsObservationScreen` | `project.filter_system_allowed_filter_types` contains `OBSERVATION`, `OBSERVATION_QUERY`, or `OBSERVATION_DATA`, or the allowed list is missing/empty | Adds `variantTable`. |
| `supportsWorkflowGroups` | `project.workflow_groups` is a non-empty array | Adds `workflow_groups`. |

Navigation is handled by `getNextScreen`, `getPrevScreen`, and `processAndSetScreen`. `processAndSetScreen` clears saved job status when entering `patientFilters`, `variantTable`, or `functionSelection` because those stages can change the job definition.

### `JobRunnerMain.tsx` State

| State | Type/Initial Value | Purpose |
| --- | --- | --- |
| `screen` | `JobRunnerScreen`, initially `"filterHistory"` | Current internal job runner page. |
| `patients` | `Patient[]`, initially `[]` | Patient data passed into patient filtering screens. In this frontend snapshot it is initialized but not populated inside `JobRunnerMain.tsx`. |
| `medications` | `Medication[]`, initially `[]` | Medication data passed into patient filtering screens. In this frontend snapshot it is initialized but not populated inside `JobRunnerMain.tsx`. |
| `observations` | `Observation[]`, initially `[]` | Observation data used to derive observations for selected patients. In this frontend snapshot it is initialized but not populated inside `JobRunnerMain.tsx`. |
| `variantPatients` | `Patient[]`, initially `[]` | Patients selected by the patient filter stage and passed into the observation stage. |
| `geneticObsForVariantPage` | `Observation[]`, initially `[]` | Observations filtered to selected patients before observation filtering. |
| `selectedFinalPatients` | `Patient[]`, initially `[]` | Patients returned from observation filtering. This state is set but is not passed into the submission payload in this snapshot. |
| `newFilterSet` | `FilterCollection`, initially `BLANK_FILTER_CONFIG` | New filter collection being built by the user. |
| `selectedPreviouslySavedFilterSet` | `FilterCollection`, initially `BLANK_FILTER_CONFIG` | Filter collection reconstructed from a saved backend filter. |
| `submittedFilterSet` | `FilterCollection`, initially `BLANK_FILTER_CONFIG` | Effective filter collection used by function selection, submission, and results. |
| `submittedFilterSetName` | `string`, initially `""` | Saved filter name or generated filter name. |
| `selectedFilterName` | `string`, initially `""` | Name of the selected saved filter. Empty means the user is creating a new filter set. |
| `savedJobInfo` | `JobLogData`, initially `BLANK_JOB_DATA` | Submitted job ID, status, log, referenced result IDs, duration, and functions retained while moving between submission/results views. |
| `animate` | `boolean`, initially `true` | Re-applies the `animate-in` class when the internal screen changes. |
| `viewOnly` | `boolean`, initially `false` | Passed to `ResultsPage`. In this flow it remains false unless expanded later. |
| `selectedFunctions` | `FunctionConfigs`, initially `{}` | Function configuration selected in `FunctionSelectionPage`. |
| `selectedThresholdConfig` | `ThresholdConfig | undefined` | Threshold settings selected through `FunctionSelector`. Defaults are supplied when rendering the function selection page. |
| `selectedDatasourceGroupId` | `number | null`, initially `null` | Active datasource group for the selected project. Initialized from the user session project datasource metadata. |
| `workflowGroupData` | `WorkflowGroupData`, initially `{}` | Selected workflow group options keyed by group key. |

Constants in the coordinator:

```ts
export const BLANK_FILTER_CONFIG: FilterCollection = {
  patientQueryFilters: "{}",
  patientDataFilters: "{}",
  observationQueryFilters: "{}",
  observationDataFilters: "{}"
};

export const BLANK_JOB_DATA: JobLogData = {
  jobId: undefined,
  jobStatus: undefined,
  jobLog: [],
  referencedBy: [],
  run_duration: undefined
};

const DEFAULT_THRESHOLD_CONFIG: ThresholdConfig = {
  enabled: false,
  threshold: 10,
  thresholdMethod: "PROTECTED"
};
```

### Page Components Rendered by `JobRunnerMain.tsx`

| Screen | Component | Render Condition |
| --- | --- | --- |
| `filterHistory` | `FilterHistoryTable` | Always available as the first job runner screen. |
| `patientFilters` | `FilterScreenPatientsJSON` when the General Statistics datasource is a local `.json` bundle; otherwise `FilterScreenPatients` | Only when `supportsPatientScreens` is true. |
| `variantTable` | `FilterScreenObservations` from `FilterScreenObservationsFHIR.tsx` | Only when `supportsObservationScreen` is true. |
| `workflow_groups` | `WorkflowGroupSelectionPage` | Only when `supportsWorkflowGroups` is true. |
| `functionSelection` | `FunctionSelectionPage` | Always part of the final flow. |
| `submit_function` | `JobSubmissionPage` | Always part of the final flow after function selection. |
| `results` | `ResultsPage` from `job_history` | Used after a job reaches `DONE` and the user selects `View Analysis Results`. |

`JobRunnerMain.tsx` no longer renders its own navigation selector. The persistent Home/Projects navigation is owned by the outer `SHARELandingPage` workspace, and Job Runner renders only the right-hand project workflow content.

### Props Passed to Each Page

#### `FilterHistoryTable`

```tsx
<FilterHistoryTable
  project={project}
  onBackToProjectPage={() => setMainScreen("home")}
  onUseFilter={(config, name) => {
    setSelectedPreviouslySavedFilterSet(config);
    setSelectedFilterName(name);
    handleAfterHistory();
  }}
  onCreateNewFilterSet={() => {
    setSelectedPreviouslySavedFilterSet(BLANK_FILTER_CONFIG);
    setSelectedFilterName("");
    setNewFilterSet(BLANK_FILTER_CONFIG);
    handleAfterHistory();
  }}
/>
```

A saved filter locks later filter controls because `selectedFilterName` becomes non-empty. Creating a new filter clears selected saved-filter state and starts from `BLANK_FILTER_CONFIG`.

#### `FilterScreenPatients`

```tsx
<FilterScreenPatients
  project={project}
  filterSystem={project.filter_system || "DEFAULT"}
  patients={patients}
  medications={medications}
  onBack={() => processAndSetScreen("filterHistory")}
  onProceedToVariants={handleAfterPatients}
  setFilterCollection={updateNewFilterCollection}
  existingQueryFilter={selectedFilterName && selectedPreviouslySavedFilterSet?.patientQueryFilters !== "{}"
    ? selectedPreviouslySavedFilterSet?.patientQueryFilters
    : newFilterSet?.patientQueryFilters}
  existingPatientFilter={selectedFilterName && selectedPreviouslySavedFilterSet?.patientDataFilters !== "{}"
    ? selectedPreviouslySavedFilterSet?.patientDataFilters
    : newFilterSet?.patientDataFilters}
  lockFilterConfig={!!selectedFilterName}
  selectedDatasourceGroupId={selectedDatasourceGroupId}
  onSelectedDatasourceGroupIdChange={setSelectedDatasourceGroupId}
/>
```

`FilterScreenPatients.tsx` is a wrapper. If `filterSystem` is `CANCER_TYPE`, it renders `pages/filters/cancer_type/FilterScreenPatients_CancerType.tsx`; otherwise it renders `pages/filters/default/FilterScreenPatients.tsx`.

#### `FilterScreenPatientsJSON`

When `project.name` is `General Statistics` and the session `fhir_source` ends with `.json`, `JobRunnerMain.tsx` renders `pages/filters/default/FilterScreenPatientsJSON.tsx` instead of `FilterScreenPatients`. On entering that state it calls `loadGeneralStatisticsPreviewData` from `utils/LocalBundlePreview.ts`, which resolves the datasource basename to a zip under `public/test-data/` (probing `_v#` suffixes the same way the cancer-type screen does), unzips it in the browser with `fflate`, and fills `patients`, `medications`, and `observations`. The screen receives `loading` and `loadError` in addition to the props listed above, filters the in-browser patient list locally, and writes the same `PATIENT_QUERY` / `PATIENT_DATA` payload as the default screen.

Only `Survivability_FHIR_Data_part1_v1.zip` ships in `public/test-data/`, so the browser preview resolves for the `initiator` (site 3) datasource; the NVFlare job itself reads each site's full bundle from `/data/client/` inside the client container.

#### `FilterScreenObservations`

```tsx
<FilterScreenObservations
  filterSystem={project.filter_system || "DEFAULT"}
  patients={variantPatients}
  project={project}
  rawObservations={geneticObsForVariantPage}
  reviewSubmission={(selectedFinal) => {
    setSelectedFinalPatients(selectedFinal);
    processAndSetScreen(supportsWorkflowGroups ? "workflow_groups" : "functionSelection");
  }}
  onBack={() => {
    const back = supportsPatientScreens ? "patientFilters" : "filterHistory";
    processAndSetScreen(back);
  }}
  setFilterCollection={updateNewFilterCollection}
  existingQueryFilter={selectedFilterName && selectedPreviouslySavedFilterSet?.observationQueryFilters !== "{}"
    ? selectedPreviouslySavedFilterSet?.observationQueryFilters
    : newFilterSet?.observationQueryFilters}
  existingDataFilter={selectedFilterName && selectedPreviouslySavedFilterSet?.observationDataFilters !== "{}"
    ? selectedPreviouslySavedFilterSet?.observationDataFilters
    : newFilterSet?.observationDataFilters}
  lockFilterConfig={!!selectedFilterName}
  selectedDatasourceGroupId={selectedDatasourceGroupId}
/>
```

The observation screen fetches observation data through the project FHIR source proxy and then performs a local data-filter pass before continuing.

#### `WorkflowGroupSelectionPage`

```tsx
<WorkflowGroupSelectionPage
  project={project}
  workflowGroupData={workflowGroupData}
  setWorkflowGroupData={setWorkflowGroupData}
  onBack={() => processAndSetScreen(getPrevScreen("workflow_groups"))}
  onNext={() => processAndSetScreen(getNextScreen("workflow_groups"))}
/>
```

Workflow group choices are persisted in `workflowGroupData` and passed through to final submission.

#### `FunctionSelectionPage`

```tsx
<FunctionSelectionPage
  project={project}
  onBack={() => processAndSetScreen(getPrevScreen("functionSelection"))}
  onNext={() => processAndSetScreen("submit_function")}
  setSelectedFunctions={setSelectedFunctions}
  existingFunctions={selectedFunctions}
  setSelectedThresholdConfig={setSelectedThresholdConfig}
  existingThresholdConfig={selectedThresholdConfig || DEFAULT_THRESHOLD_CONFIG}
  filterSet={effectiveFilterSet}
  backToButtonText={...}
/>
```

The back button label is derived from the actual previous screen. It can be `Back to Workflow Selection`, `Back to Observation Filters`, `Back to Patient Filters`, or `Back to Filter History`.

#### `JobSubmissionPage`

```tsx
<JobSubmissionPage
  project={project}
  onBack={() => processAndSetScreen("functionSelection")}
  submittedFilterName={submittedFilterSetName || ""}
  submittedFilter={effectiveFilterSet}
  onCancel={() => processAndSetScreen("filterHistory")}
  viewAnalysisResultsPage={() => processAndSetScreen("results")}
  savedJobInfo={savedJobInfo}
  setSavedJobInfo={setSavedJobInfo}
  selectedFunctions={selectedFunctions}
  selectedThresholdConfig={selectedThresholdConfig}
  selectedDatasourceGroupId={selectedDatasourceGroupId}
  selectedDatasourceGroupName={selectedDatasourceGroupName}
  workflowGroupData={workflowGroupData}
/>
```

`onCancel` is passed but is not used by the current `JobSubmissionPage` implementation.

#### `ResultsPage`

```tsx
<ResultsPage
  onBack={() => processAndSetScreen("submit_function")}
  submittedFilterSetName={submittedFilterSetName ? submittedFilterSetName : ""}
  submittedFilterSet={effectiveFilterSet}
  onStartOver={() => processAndSetScreen("filterHistory")}
  savedJobInfo={savedJobInfo}
  viewOnly={viewOnly}
  onBackToHistory={onBackToHistory}
  project={project}
/>
```

The results page is imported from the job history feature and reused here for immediate post-submission result viewing.

### Filter History Step

`FilterHistoryTable.tsx` calls:

```ts
fetch(`${API_BASE}${API_FILTERS_FETCH}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ project_id: project.id })
});
```

The expected response shape is:

```ts
{
  filters: Array<{
    id: number;
    name: string;
    create_date?: string;
    update_date?: string;
    conditions?: Condition[];
  }>;
}
```

Rows are mapped into:

```ts
export interface FilterHistoryRow {
  id: number;
  name: string;
  create_date?: string;
  update_date?: string;
  filter_collection: FilterCollection;
}
```

`conditions` from the backend are converted back into the frontend `FilterCollection` shape with `buildDefaultFilterCollectionFromConditions(r.conditions || [], project)`.

UI behavior:

- The table starts loading when filters are fetched.
- If `project.id` is missing, rows and selection are cleared and no request is made.
- If the request fails, the error is logged to the console and the table is reset to an empty state.
- A quick-filter text input filters by ID, name, create date, or update date.
- Rows are paginated with `PAGE_SIZE = 10`.
- Selecting a row expands it and displays `FilterSummary`.
- The primary button says `Use Selected Filter Set` when a row is selected; otherwise it says `Create New Filter Set`.

### Patient Filter Step

`FilterScreenPatients.tsx` chooses the patient filter implementation based on `project.filter_system`:

| `filterSystem` | Component Rendered |
| --- | --- |
| Any value, when the project is `General Statistics` and the session `fhir_source` ends with `.json` | `pages/filters/default/FilterScreenPatientsJSON.tsx` (chosen in `JobRunnerMain.tsx` before `FilterScreenPatients.tsx` is consulted) |
| `CANCER_TYPE` | `pages/filters/cancer_type/FilterScreenPatients_CancerType.tsx` |
| Any other value or missing value | `pages/filters/default/FilterScreenPatients.tsx` |

Both implementations receive the selected datasource group and can update `selectedDatasourceGroupId` through `onSelectedDatasourceGroupIdChange`.

When the patient stage completes, `handleAfterPatients` stores selected patients in `variantPatients`, filters existing observation state to those patients, and advances to:

- `variantTable` if observation screens are supported
- `workflow_groups` if observation screens are skipped and workflow groups exist
- `functionSelection` otherwise

### Observation Filter Step

`FilterScreenObservationsFHIR.tsx` loads public filter schemas from the frontend public folder based on `filterSystem`:

```ts
const fs = (filterSystem || "default").toLowerCase();
const querySchemaUrl = `/filters/${fs}/observation/observation_query.json`;
const dataSchemaUrl = `/filters/${fs}/observation/observation_data.json`;
```

The current query controls block is commented out in the rendered JSX, but the component still builds and displays a FHIR query preview and uses the local data-filter controls.

The FHIR preview/fetch call goes through the backend project FHIR source proxy:

```ts
fetch(`${API_BASE}${API_PROJECTS_FHIR_SOURCE}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    username: userSession.username,
    project_id: project.id,
    datasource_group: selectedDatasourceGroupId,
    execute_query: executeQuery
  })
});
```

The expected response shape is represented by `ProjectFHIRSourceQueryResponse`:

```ts
interface ProjectFHIRSourceQueryResponse {
  fhir_source?: string | null;
  fhir_source_type?: string | null;
  datasource_group?: number | null;
  datasource_group_name?: string | null;
  datasource_groups?: any[];
  query_results?: any;
  query_status_code?: number;
}
```

Important behavior:

- If no patient subject IDs are available, preview is blocked with `No subject IDs were supplied from the patient filter stage.`
- If no FHIR source is available, preview fails with `No FHIR source is available for this user and project.`
- If the FHIR source ends in `.json`, preview fails with `Preview query is only supported for FHIR server sources.`
- Subject IDs are batched and fetched page-by-page using FHIR bundle `next` links.
- The progress label and percentage are updated as batches complete.
- Returned observations are deduplicated by observation ID.
- Local observation data filters are applied after the FHIR fetch.
- The continue button is disabled until the user has previewed and at least one filtered patient row remains.

On submit, the screen writes observation filter JSON back into `newFilterSet` unless `lockFilterConfig` is true.

### Workflow Group Step

`WorkflowGroupSelectionPage.tsx` reads `project.workflow_groups`, sorts groups by `page_order` and then label/key, and sorts options by `option_order` and then label/value.

The project workflow group shape is defined in `src/types/Project.tsx`:

```ts
export interface ProjectWorkflowGroupOption {
  id?: number;
  option_key?: string;
  option_label?: string;
  option_value: string;
  option_order?: number;
}

export interface ProjectWorkflowGroup {
  id?: number;
  group_key: string;
  group_label: string;
  group_description?: string | null;
  min_selected?: number | null;
  max_selected?: number | null;
  is_required?: boolean;
  page_order?: number;
  options: ProjectWorkflowGroupOption[];
}

export interface WorkflowGroupSelection {
  group_key: string;
  selected_values: string[];
}

export type WorkflowGroupData = Record<string, WorkflowGroupSelection>;
```

Validation uses `min_selected` and `max_selected` from each group. In this component, missing `min_selected` is treated as `0`; `is_required` is not used by this page's validation. The next button is disabled until every group passes validation.

The stored selection shape is:

```ts
{
  [groupKey]: {
    group_key: groupKey,
    selected_values: ["..."]
  }
}
```

### Function Selection Step

`FunctionSelectionPage.tsx` wraps the shared `FunctionSelector` component.

Props passed into `FunctionSelector`:

```tsx
<FunctionSelector
  onSelectionFunctionConfigChange={emitSelectedFunctions}
  initialSelectedFunctions={existingFunctions}
  onThresholdSamplesChange={emitSelectedThresholdConfig}
  initialSelectedThresholdConfig={existingThresholdConfig}
  project={project}
  filterSet={filterSet}
/>
```

Function selection page validation:

- The next button is disabled when no function config has been selected.
- The next button is disabled when duplicate function configurations are detected.
- Duplicate detection normalizes each config by sorting keys and comparing the JSON signature.
- Duplicate messages identify the function and duplicate config numbers.

This screen does not call the backend directly. Supported functions and function restrictions are driven by the selected `project` object and the shared `FunctionSelector` behavior.

### Job Submission Step

`JobSubmissionPage.tsx` assembles the final backend payload.

The filter payload is built from the effective filter set and project schemas:

```ts
const filtersPayload = buildFiltersPayload(
  submittedFilterName || "Filter Set",
  submittedFilter,
  project
);
```

`buildFiltersPayload` returns:

```ts
{
  name: string;
  conditions: Condition[];
}
```

Each condition has the frontend schema-driven shape:

```ts
{
  filter_type: FilterType;
  column_name: string;
  operator: string;
  value?: string;
  values?: string[];
}
```

Selected function configs are merged with project-level fixed function config before submission. `getFixedConfigByFunction(project)` reads `project.functions[].custom_configuration_fixed`, and `mergeFixedIntoSelectedFunctions` applies those fixed values to each selected function config.

The submission endpoint call is:

```ts
fetch(`${API_BASE}${API_SUBMIT_JOB}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
```

The payload is assembled as:

```ts
const payload: any = {
  project_id: project.id,
  filters: filtersPayload,
  functions_map: resolvedFunctionsMap,
  submitter: username,
  non_contributing_clients: clientParticipationSelection.non_contributing_clients,
  exclude_analyzing_clients: clientParticipationSelection.exclude_analyzing_clients
};

if (selectedDatasourceGroupId !== null) {
  payload.datasource_group = selectedDatasourceGroupId;
}

if (workflowGroupData && Object.keys(workflowGroupData).length > 0) {
  payload.workflow_group_data = workflowGroupData;
}

if (
  selectedThresholdConfig &&
  selectedThresholdConfig.enabled &&
  selectedThresholdConfig.thresholdMethod &&
  selectedThresholdConfig.threshold != null
) {
  payload.threshold_config = {
    method: selectedThresholdConfig.thresholdMethod,
    threshold: selectedThresholdConfig.threshold
  };
}
```

Example final payload shape:

```json
{
  "project_id": 1,
  "filters": {
    "name": "CT:Breast Cancer,D:1,A:0,T:2,R:3",
    "conditions": [
      {
        "filter_type": "PATIENT_DATA",
        "column_name": "cancer_type",
        "operator": "=",
        "value": "Breast Cancer"
      },
      {
        "filter_type": "OBSERVATION_DATA",
        "column_name": "minDeletions",
        "operator": ">=",
        "value": "1"
      }
    ]
  },
  "functions_map": {
    "SURVIVAL_ANALYSIS": [
      {
        "model_type": "open_access"
      }
    ]
  },
  "submitter": "username",
  "non_contributing_clients": ["site-2"],
  "exclude_analyzing_clients": ["site-3"],
  "datasource_group": 5,
  "workflow_group_data": {
    "modeling_methods": {
      "group_key": "modeling_methods",
      "selected_values": ["cox_lasso", "logistic_reg"]
    }
  },
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 10
  }
}
```

The example values above illustrate the frontend payload structure. Actual condition names, operators, function keys, and workflow group keys come from the selected project and filter schemas.

### Participation, Contributing, and Analyzing Party Integration

`JobSubmissionPage.tsx` renders `NVFlareClientSnapshot` before the submission overview.

```tsx
<NVFlareClientSnapshot
  projectId={project.id}
  filtersPayload={filtersPayload}
  functionsMap={resolvedFunctionsMap}
  thresholdConfig={selectedThresholdConfig}
  heartbeatWindowMs={60000}
  onState={({ loading, clients }) => {
    setSnapshotLoading(loading);
    setSnapshotClients(clients);
  }}
  onParticipationSelectionChange={setClientParticipationSelection}
  onError={(msg) => setError(msg)}
  canSubmit={canSubmit}
/>
```

When `functionsMap` and `filtersPayload` are present, `NVFlareClientSnapshot` calls the participation status endpoint:

```ts
fetch(`${API_BASE}${API_CLIENTS_PARTICIPATION_STATUS}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
  signal: controller.signal
});
```

The participation body includes:

```ts
{
  include_connection_state: includeConnectionState,
  participation_status: {
    filters: filtersPayload,
    project_id: projectId,
    functions: functionsMap,
    non_contributing_clients: [...],
    exclude_analyzing_clients: [...],
    threshold_config?: {
      method: string,
      threshold: number
    }
  }
}
```

If the logged-in role is `INITIATOR`, the body also includes `username`.

If participation context is not available, the component calls the connection status endpoint instead:

```ts
fetch(`${API_BASE}${API_CLIENTS_CONNECTION_STATUS}`, ...)
```

Client rows are expected under `data.clients`. Each row is mapped into:

```ts
export interface ClientStatus {
  id: string;
  name: string;
  connected: boolean;
  participation?: "ACCEPT" | "REJECT" | "PENDING" | null;
  lastConnect: string;
  isInitiator?: boolean;
  isSubmittedUser?: boolean;
  isServer?: boolean;
  registered?: boolean;
  contributingParty?: boolean;
  analyzingParty?: boolean;
}
```

Participation selection emitted back to `JobSubmissionPage` has this shape:

```ts
export interface ClientParticipationSelection {
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
}
```

Status and selection rules:

- A client is considered connected if its last check-in is within `heartbeatWindowMs`, which is `60000` in job submission.
- A server row is considered online unless `server_online === false`.
- Server rows are not selectable for participation controls.
- Initiator and server analyzing checkboxes are locked on the client side.
- Contributing and analyzing checkboxes are disabled when `canSubmit` is false.
- Checkbox tooltips distinguish locked controls from temporarily disabled controls.
- Party status shows `Participation`, `Analyzing`, and `Contributing` lines.
- Server party status uses `Participation: Always Active`, `Analyzing: No`, and `Contributing: No`.

### Submit Button Validation

`JobSubmissionPage.tsx` computes submit eligibility as:

```ts
const canSubmit =
  !submitting &&
  !isDone &&
  !isFailure &&
  hasSelectedFunctions &&
  serverOnline &&
  registeredJobEligibleClients.length > 0 &&
  connectedRegisteredJobEligibleClients.length > 0;
```

Button text explains the blocking condition:

| Condition | Button Text |
| --- | --- |
| `submitting` | `Submitting...` |
| No selected functions | `Select at least one function` |
| No registered non-server clients | `No Registered Clients` |
| Server offline | `Server is Offline` |
| No connected registered non-server clients | `No Site Online` |
| Eligible | `Submit for Analysis` |
| Job done | `View Analysis Results` |
| Job failure | `Failure Occurred` |

`FunctionSelectionPage` also prevents continuing to submission if no functions are selected or duplicate function configs exist.

`WorkflowGroupSelectionPage` prevents continuing to function selection while workflow group min/max validation fails.

`FilterScreenObservationsFHIR.tsx` prevents continuing until FHIR observation data has been fetched and local filtering leaves at least one patient row.

### Job Status Tracking After Submit

After a successful submit, the response is stored in local state. If `data.job_id` exists, the page sets `jobId` and starts status tracking.

Polling endpoint:

```ts
fetch(`${API_BASE}${API_JOB_STATUS}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ job_id: id, $pw: process.env.REACT_APP_MYSQL_SECRET_PW ?? "" })
});
```

Polling interval:

```ts
const POLL_INTERVAL = 500;
```

Websocket behavior is enabled by:

```ts
const WEB_SOCKET = true;
```

The websocket path constant used in this file is:

```ts
const API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws";
```

`buildJobStatusWebSocketUrl(jobId)` builds either:

- local development-style URL: `${API_BASE}${API_JOB_STATUS_WEBSOCKET}/local/${jobId}`, converted from `http` to `ws`
- deployed websocket URL: `${WS_API_BASE}/${jobId}`

Expected websocket messages:

| Message Type | Behavior |
| --- | --- |
| `heartbeat` | Ignored after optional debug logging. |
| `job_status` | Applies `status`, `log`, `referenced_by`, `run_duration`, and `functions` to saved job state. |
| `job_status_error` | Closes the websocket and falls back to polling if the current status is not terminal. |
| Any other `type` | Ignored. |

If a websocket message has `requires_ack` and `message_id`, the frontend sends:

```json
{
  "type": "ack",
  "message_id": "..."
}
```

Terminal statuses are determined by:

```ts
function isTerminalStatus(status: string | null | undefined): boolean {
  const s = String(status || "").toUpperCase();
  return s === "DONE" || s === "FAILURE";
}
```

When a terminal status is reached, polling/websocket tracking stops and `submitting` becomes false.

### Saved Job Info Passed to Results

`JobSubmissionPage` updates `savedJobInfo` through `setSavedJobInfo` whenever job status updates arrive:

```ts
setSavedJobInfo({
  jobId: id,
  jobStatus: nextStatus || "",
  jobLog: nextLog,
  referencedBy: statusData?.referenced_by || undefined,
  run_duration: statusData?.run_duration || undefined,
  functions: statusData?.functions || fallbackFunctions
});
```

`ResultsPage` receives that object from `JobRunnerMain.tsx`. This lets the user move from submitted-job status into analysis results without going through the separate job history screen.

### Error and Loading Behavior

| Step | Loading State | Error Behavior |
| --- | --- | --- |
| Filter history | `loading` in `FilterHistoryTable`; `RefreshablePanel` displays refresh/loading state | Failed fetch logs `Failed to fetch filters` to the console and clears rows/selection. |
| Patient filters | Controlled by the selected patient filter implementation | Existing filters are locked when a saved filter is selected. |
| Observation filters | `isPreviewLoading`, progress label, progress percent, completed text | Preview errors are shown inline in a red error panel; failed preview clears fetched observation state. |
| Workflow groups | No backend loading; source is `project.workflow_groups` | Validation errors are shown below options and disable next. |
| Function selection | No direct backend loading in this wrapper | Duplicate configuration messages are shown in an error container and disable next. |
| Client snapshot | `snapshotLoading` from `NVFlareClientSnapshot`; submit button says `Loading clients...` | Client refresh errors call `setError("Failed to refresh clients list.")`. |
| Job submit | `submitting` controls button text and disables resubmission | Submit failures show an inline red error panel with API/message details. |
| Job status polling | Interval runs every 500ms until terminal status or failure | Polling errors stop tracking and show `Error polling job status: ...`. |
| Job status websocket | Websocket starts alongside polling; polling stops after streaming begins | `job_status_error`, websocket errors, or unexpected close can fall back to polling or show a stream error. |

### Backend Endpoints Used by This Flow

All endpoint constants come from `src/constants/Constants.tsx`, except `JobSubmissionPage.tsx` also defines a local `API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws"` constant.

| Frontend File | Endpoint Constant | Request Purpose |
| --- | --- | --- |
| `FilterHistoryTable.tsx` | `API_FILTERS_FETCH` | Fetch saved filters for the selected project. |
| `FilterScreenObservationsFHIR.tsx` | `API_PROJECTS_FHIR_SOURCE` | Execute a project-scoped FHIR query through the backend proxy. |
| `NVFlareClientSnapshot.tsx` | `API_CLIENTS_CONNECTION_STATUS` | Fetch client/server connection state when participation context is not included. |
| `NVFlareClientSnapshot.tsx` | `API_CLIENTS_PARTICIPATION_STATUS` | Fetch client/server connection plus participation state for a pending job definition. |
| `JobSubmissionPage.tsx` | `API_SUBMIT_JOB` | Submit the final SHARE/NVFlare job request. |
| `JobSubmissionPage.tsx` | `API_JOB_STATUS` | Poll submitted job status. |
| `JobSubmissionPage.tsx` | local `API_JOB_STATUS_WEBSOCKET` | Stream submitted job status over websocket. |

The uploaded frontend source does not include backend route implementation files. Backend route ownership cannot be verified from `frontend.zip` alone.

### Current Code Notes

- `JobRunnerMain.tsx` initializes `patients`, `medications`, and `observations` as empty arrays, but this file does not populate them.
- `selectedFinalPatients` is set after observation filtering but is not used by `JobSubmissionPage` in this snapshot.
- `onCancel` is passed into `JobSubmissionPage` but is not declared in the component destructuring and is not rendered.
- The observation query control block in `FilterScreenObservationsFHIR.tsx` is commented out in JSX, but the component still builds the query preview from query schema state and `queryFhirParams`.
- `WorkflowGroupSelectionPage.tsx` validates `min_selected` and `max_selected`; it does not use `is_required` when `min_selected` is missing.
- `JobSubmissionPage.tsx` imports `API_JOB_STATUS` and `WS_API_BASE` from constants but defines its own local websocket path constant.
