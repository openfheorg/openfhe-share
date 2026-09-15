# Types and Data Models

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/types/` | Shared TypeScript interfaces and domain models. |
| `src/features/job_history/types/` | Not present in the reviewed frontend package. Job history/result types are currently defined in `src/types/JobsDataTypes.tsx`, `src/features/job_history/utils/JobsDataUtils.tsx`, `src/features/job_history/utils/ExportDocTypes.tsx`, and local component props. |
| `src/models/` | Not present in the reviewed frontend package. Domain models currently live under `src/types/` and feature-local files. |
| `src/constants/global_schema.json` | Static global metadata/schema JSON used as source-side reference data. |
| `src/constants/ExecutionStep.ts` | Not present in the reviewed frontend package. Job execution/status display constants currently live inside `JobSubmissionPage.tsx`, `JobHistoryTable.tsx`, and status-image helper logic. |
| `src/constants/Constants.tsx` | Shared constants, API endpoint paths, supported function enum, region constants, and feature descriptions. |
| `src/types/LandingPage.tsx` | Global Home and project landing endpoint response models. |
| Feature-local component props | Props/state shapes defined inline in React component files. |

## Type System Role

The frontend uses a mix of shared TypeScript files, utility-local types, and component-local props interfaces.

The most stable shared domain types are under:

```text
src/types/
```

The results/export type model is not under a dedicated `types/` folder. It is split across:

```text
src/types/JobsDataTypes.tsx
src/features/job_history/utils/JobsDataUtils.tsx
src/features/job_history/utils/ExportDocTypes.tsx
src/features/job_history/components/export/ExportSectionSelectionModal.tsx
```

Several complex runtime objects remain loosely typed with `any`, especially result payloads, function configuration JSON, public config editor JSON, and FHIR/test-data records.

## Shared Types Directory

The reviewed package contains these files under `src/types/`:

| File | Main exports | Primary usage |
| --- | --- | --- |
| `FilterSchema.tsx` | `FilterType`, `Condition`, `FilterCollection`, `SaveTargetSchema`, `SaveSchema`, `ControlFHIR`, `QuerySchema`, `ControlOption`, `ControlSchema`, `FilterSchema` | Filter config JSON, filter screen controls, filter payload building, project filter schemas. |
| `FunctionConfigs.tsx` | `FunctionConfigProps`, `FunctionConfigs`, `ThresholdMethod`, `ThresholdConfig` | Function selector, job runner state, job submission, NVFlare client snapshot. |
| `JobsDataTypes.tsx` | `ThresholdPayload`, `CryptoAuditRecord`, `DatasourceLogPayload`, `WorkflowGroupSelectedOption`, `WorkflowGroupSelection`, `NVFlareJob`, `JobLogEntry`, `JobLogData` | Job history table, results page, result section components, job submission saved status. |
| `Medication.tsx` | `Medication` | Job runner filter screens and local/FHIR medication filtering. |
| `Observation.tsx` | `Observation` | Observation filter screen and local observation processing. |
| `ObservationComponent.tsx` | `ObservationComponent` | Nested component type used by `Observation`. |
| `Patient.tsx` | `Patient` | Patient filter screens, observation filtering, variant helper logic. |
| `Project.tsx` | `JsonObject`, `ProjectFunctionCapability`, `FilterSystem`, `ProjectDatasourceGroup`, `ProjectWorkflowGroupOption`, `ProjectWorkflowGroup`, `WorkflowGroupSelection`, `WorkflowGroupData`, `Project` | App-level project state, project list, job runner, job history, user manager, datasource group selector, workflow group selector. |

There is no `src/models/` directory in the reviewed package.

There is no `src/features/job_history/types/` directory in the reviewed package.

## `FilterSchema.tsx`

`FilterSchema.tsx` defines the static filter schema and compiled filter condition model.

### `FilterType`

```ts
export type FilterType =
  | "PATIENT_QUERY"
  | "PATIENT_DATA"
  | "OBSERVATION"
  | "OBSERVATION_QUERY"
  | "OBSERVATION_DATA";
```

These values are used to decide which logical filter bucket a control writes to. `OBSERVATION` is treated as an observation-query-style group by `FilterPayloadConfigUtils.tsx`.

### `Condition`

```ts
export interface Condition {
  filter_type: FilterType;
  column_name: string;
  operator: string;
  value?: string;
  values?: string[];
}
```

`Condition` is the normalized backend/job-facing form produced from user-selected controls. A single condition has one `filter_type`, one `column_name`, one `operator`, and either a scalar `value` or array `values`.

### `FilterCollection`

```ts
export interface FilterCollection {
  patientQueryFilters: string;
  patientDataFilters: string;
  observationQueryFilters: string;
  observationDataFilters: string;
}
```

`FilterCollection` stores each bucket as a JSON string. This is the main selected-filter state passed through the job runner and reused when reconstructing filter selections from backend-saved filters.

### Control and query schema

`ControlSchema` describes each rendered control. Important fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable frontend control identifier. |
| `field` | Logical field name. Used when reading/writing values if present. |
| `label` | User-facing label. |
| `type` | Control type. Supports `select`, `multi-select`, `multi-select-grid`, `number`, `checkbox`, `date-range`, `hidden`, `token-select`, `label`, and arbitrary string fallbacks. |
| `default` | Default value. Currently typed as `any`. |
| `disabled` | Prevents editing in the UI. |
| `options` | `ControlOption[]` with `label`, optional `value`, and optional `token`. |
| `fhir` | FHIR query-generation metadata. |
| `query` | Query metadata used by filter screens. |
| `save` | Targets describing how selected values compile into saved/backend filter fields. |
| `ui` | Layout/editing hints such as `span` and `editable`. |

`SaveTargetSchema` is what connects one UI control to one or more saved/backend filter conditions. It can specify `filter_type`, `column_name`, `filter_group`, `field`, `operator`, `valueFrom`, and optional type transform.

### Primary importers

`FilterSchema.tsx` is imported by:

| Importer | Use |
| --- | --- |
| `src/types/Project.tsx` | Adds filter schema metadata to the `Project` type. |
| `src/features/job_runner/components/FilterControlsSection.tsx` | Renders controls and compiles selected values. |
| `src/features/job_runner/utils/FilterPayloadConfigUtils.tsx` | Converts `FilterCollection` into normalized backend payload conditions. |

## `FunctionConfigs.tsx`

This file defines the selected-function and threshold data model.

```ts
export type FunctionConfigProps = Record<string, string>;
export type FunctionConfigs = Record<string, FunctionConfigProps[]>;

export type ThresholdMethod = "PROTECTED" | "EXPOSED";

export interface ThresholdConfig {
  enabled: boolean;
  threshold: number;
  thresholdMethod: ThresholdMethod;
}
```

`FunctionConfigs` is a map keyed by function name. Each function name maps to an array of configuration objects. This supports one selected function producing multiple configuration entries.

`ThresholdConfig` is used by function selection, the client snapshot request payload, and the final job submission payload. When enabled, `JobSubmissionPage.tsx` submits it as:

```json
{
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 20
  }
}
```

Primary importers:

| Importer | Use |
| --- | --- |
| `src/components/FunctionSelector.tsx` | Builds selected function config and threshold config. |
| `src/components/NVFlareClientSnapshot.tsx` | Includes function/threshold context in participation/status checks. |
| `src/features/job_runner/JobRunnerMain.tsx` | Stores selected function and threshold state. |
| `src/features/job_runner/pages/FunctionSelectionPage.tsx` | Passes selected functions/threshold back to the runner. |
| `src/features/job_runner/pages/JobSubmissionPage.tsx` | Builds `functions_map` and optional `threshold_config` for submit. |

## `JobsDataTypes.tsx`

This file contains the shared job history/results model.

### `NVFlareJob`

`NVFlareJob` represents a job-history row and selected-job metadata.

Important fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `number` | Frontend/internal database job ID. |
| `nvflare_assigned_id` | `string?` | NVFlare-assigned job identifier when available. |
| `filter_id` | `number?` | Saved filter ID. |
| `status` | `string?` | Job status display/source value. |
| `job_path` | `string?` | Backend/staged job path. |
| `output_path` | `string?` | Backend output path. |
| `job_runner_id` | `string?` | Runner identifier if returned. |
| `non_contributing_clients` | `string | null?` | Comma-separated excluded contributing clients. |
| `exclude_analyzing_clients` | `string | null?` | Comma-separated excluded analyzing clients. |
| `submit_time` | `string?` | Submitted timestamp. |
| `run_duration` | `string?` | Runtime duration if returned. |
| `create_date` | `string` | Created timestamp. |
| `update_date` | `string` | Updated timestamp. |
| `completed_date` | `string?` | Completion timestamp. |
| `functions` | `string[]?` | Functions/workflows associated with the job. |
| `functions_map` | `Record<string, Record<string,string> | Record<string,string>[]>?` | Submitted function configuration. |
| `threshold` | `ThresholdPayload?` | Persisted threshold config. |
| `crypto_audit_record` | `CryptoAuditRecord?` | OpenFHE/crypto audit metadata. |
| `datasource_group_id` | `number | null?` | Selected datasource group ID. |
| `datasource_group_name` | `string | null?` | Selected datasource group label. |
| `datasource_log` | `DatasourceLogPayload?` | Datasource log details. |
| `workflow_group_data` | `Record<string, string[]>?` | Compact workflow group data. |
| `workflow_groups` | `WorkflowGroupSelection[]?` | Expanded persisted workflow group selections. |

### Job log state

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

`JobLogData` is used by `JobRunnerMain.tsx`, `JobSubmissionPage.tsx`, `JobHistoryMain.tsx`, and `ResultsPage.tsx` as saved or selected job status context.

## `Patient.tsx`, `Medication.tsx`, `Observation.tsx`, and `ObservationComponent.tsx`

These files define lightweight local/FHIR-style records used by the filter screens.

### `Patient`

```ts
export interface Patient {
  id: string;
  family: string;
  given: string;
  gender: string;
  birthDate: string;
  fullUrl: string;
  deceasedDateTime?: string;
  medication?: string;
}
```

Used by patient filter screens, observation filter screens, and variant helper logic.

### `Medication`

```ts
export interface Medication {
  id: string;
  subjectReference: string;
  medicationCodeableConcept?: {
    coding: { code: string; display: string; system: string }[];
  };
  status: string;
}
```

Used by patient filter screens where medication-related data is needed.

### `Observation`

```ts
export interface Observation {
  id: string;
  subjectReference: string;
  components: ObservationComponent[];
  code?: { coding?: { system?: string; code?: string; display?: string }[] };
  interpretation?: { coding?: { system?: string; code?: string; display?: string }[] }[];
}
```

Used by `FilterScreenObservationsFHIR.tsx` to normalize and filter observation/genetic-variant records.

### `ObservationComponent`

```ts
export interface ObservationComponent {
  code: { coding: { code: string }[] };
  valueQuantity?: { value: number };
  valueCodeableConcept?: { coding: { code: string; display: string }[] };
}
```

## `Project.tsx`

`Project.tsx` is the main app/project model.

### Function capability model

```ts
export interface ProjectFunctionCapability {
  function: string;
  configurable: boolean;
  custom_configuration_fixed?: JsonObject | null;
  custom_configuration_variable?: JsonObject | null;
  override_configuration?: JsonObject | null;
}
```

This drives the function selector and determines what configuration is fixed, variable, or overridden for a function.

### Datasource group model

```ts
export interface ProjectDatasourceGroup {
  id: number;
  project_id: number;
  group_name: string;
  is_default: boolean;
}
```

Used by `App.tsx`, datasource group selector, job runner, headers, job history, and results displays.

### Workflow group model

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

`WorkflowGroupData` is passed from `WorkflowGroupSelectionPage.tsx` into `JobSubmissionPage.tsx` and submitted as `workflow_group_data`.

### `Project`

```ts
export interface Project {
  id: number;
  name: string;
  description?: string | null;
  status?: string | null;
  fixed?: boolean | null;
  function_restrictions_enabled: boolean;
  filter_system?: FilterSystem | null;
  filter_system_allowed_filter_types?: FilterType[] | null;
  filter_schemas: Partial<Record<FilterType, FilterSchema>>;
  functions: ProjectFunctionCapability[];
  datasource_groups_defined?: boolean;
  datasource_groups?: ProjectDatasourceGroup[] | null;
  default_datasource_group?: ProjectDatasourceGroup | null;
  workflow_groups?: ProjectWorkflowGroup[] | null;
  create_date?: string | null;
  update_date?: string | null;
}
```

This type is used widely across top-level app state, job runner, job history, user manager, and shared components.

## Session and Role Types

Session/role types live in `src/context/UserRoleContext.tsx`, not `src/types/`.

### `UserRole`

```ts
export enum UserRole {
  CLIENT = "CLIENT",
  INITIATOR = "INITIATOR",
  OBSERVER = "OBSERVER",
  ADMIN = "ADMIN",
}
```

Role values are consumed by navigation, results loading, client/server API base selection, and display/access behavior.

### `UserProjectDatasource`

```ts
export interface UserProjectDatasource {
  source: string;
  datasource_group_id: number | null;
  datasource_group_name: string | null;
  is_default_group: boolean;
}
```

This represents a user-visible datasource assigned to a project and optionally a datasource group.

### `UserProjectAccess`

```ts
export interface UserProjectAccess {
  project_id: number;
  project_name: string;
  datasources: UserProjectDatasource[];
}
```

### `UserSession`

```ts
export interface UserSession {
  role: UserRole;
  username: string;
  user_id?: number | null;
  fhir_source: string | null;
  projects: UserProjectAccess[];
  selected_project_id?: number | null;
  selected_project_datasources?: UserProjectDatasource[];
}
```

`App.tsx` stores `sessionBase` as `Omit<UserSession, "fhir_source" | "selected_project_id" | "selected_project_datasources"> | null`, then derives a full `session` with the selected project/datasource values.

## Constants and Enum Types

`src/constants/Constants.tsx` defines constants rather than request/response interfaces.

Important exports:

| Export | Type/shape | Notes |
| --- | --- | --- |
| `CLIENT_API_BASE_PORT` | number | Base port for client results agents, `8088`. |
| `CLIENT_API_BASE` | string | Client results agent base for hosted deployments, `http://127.0.0.1:8088`. |
| `IS_LOCAL_APP` | boolean | True for development builds. |
| `IS_STANDALONE_APP` | boolean | True when `REACT_APP_BUILD_FLAVOR` is `local`, which marks the self-hosted standalone bundle. |
| `getClientApiBase` | `(clientName?: string \| null) => string` | Returns `CLIENT_API_BASE` for hosted deployments, otherwise `http://127.0.0.1:${CLIENT_API_BASE_PORT + siteNumber}` derived from a `site<N>` client name. Throws when the name is missing or unparsable. |
| `ALB_API_BASE` | string | HTTP ALB URL constant. |
| `PROD_FALLBACK_API_WS_BASE` | string | Websocket fallback base. |
| `API_BASE` | string | Development uses `http://localhost:8000`; non-development uses `REACT_APP_API_BASE` or production fallback. |
| `WS_API_BASE` | string | Development currently uses `LOCAL_API_BASE`; non-development uses `REACT_APP_API_BASE` or websocket fallback. |
| `API_SUBMIT_JOB` | `"/nvflare/jobs/submit"` | Job submission. |
| `API_JOB_HISTORY` | `"/nvflare/jobs/history"` | Job history. |
| `API_JOB_RESULTS_CONTEXT` | `"/nvflare/jobs/results_context"` | Results context bootstrap for direct results entry. |
| `API_JOB_STATUS` | `"/jobs/status"` | Status polling. |
| `API_JOB_STATUS_WEBSOCKET` | `"/jobs/status/ws"` | Websocket path. |
| `API_JOB_RESULTS` | `"/jobs/results"` | Job results. |
| `API_JOB_RESULTS_MAPPING` | `"/jobs/results/mapping"` | Workflow/result mapping. |
| `API_JOB_RESULTS_FUNCTION_CONFIG` | `"/jobs/function/config"` | Function config endpoint. |
| `API_FILTERS_FETCH_SINGLE` | `"/filters/fetch_single_filter"` | Single saved-filter lookup. |
| `API_FILTERS_FETCH` | `"/filters/fetch_filters"` | Saved-filter list lookup. |
| `API_FUNCTIONS_SUPPORTED` | `"/functions/supported_functions"` | Defined but not imported by any frontend file in the reviewed package. |
| `API_CLIENTS_PARTICIPATION_STATUS` | `"/clients/participation/status"` | Client participation state. |
| `API_CLIENTS_CONNECTION_STATUS` | `"/clients/connection/status"` | Client/server connection state. |
| `API_LANDING_HOME` | `"/landing/home"` | Global Home landing summary. |
| `API_LANDING_PROJECT` | `"/landing/project"` | Per-project landing summary. |
| `API_PROJECTS_LIST` | `"/projects/list"` | Project list. |
| `API_PROJECTS_FHIR_SOURCE` | `"/projects/fhir/source"` | Project datasource/FHIR source lookup. |
| `SupportedFunction` | enum | `SURVIVAL_ANALYSIS`, `CHI_SQUARE_TEST`, `STANDARD_DEVIATION`, `MEAN`, `T_TEST`. |
| `Cytoband` | union from region arrays | Derived from `DELETION_REGIONS` and `AMPLIFICATION_REGIONS`. |

`API_FUNCTIONS_SUPPORTED` is defined but no reviewed frontend file imports it.

## Global Schema JSON

`src/constants/global_schema.json` is static JSON. It is not a TypeScript schema file.

Top-level shape:

```ts
type GlobalSchema = {
  metadata: Record<string, Record<string, number | string>>;
  columns: Record<
    string,
    | {
        type: "numeric";
        global_max?: number;
        global_min?: number;
        global_count?: number;
      }
    | {
        type: "categorical";
        categories: string[];
      }
    | {
        type: "boolean";
      }
  >;
};
```

The reviewed JSON includes metadata such as `max_samples_per_time_step`, `global_count_contingency_table`, and `t_test_age_global_counts`. Column entries include numeric, categorical, and boolean fields such as `income`, `gender`, `Age`, `Sex`, `PBRM1`, `PFS`, `PFS_CNSR`, `OS`, and `OS_CNSR`.

No direct TypeScript import of `global_schema.json` was found in the reviewed source scan. Treat it as static source/reference data unless a future feature imports it.

## Execution Step Types

`src/constants/ExecutionStep.ts` is not present in the reviewed frontend package.

Execution/status display types currently live as local constants and helper types in feature files, mainly:

| File | Status/type role |
| --- | --- |
| `src/features/job_runner/pages/JobSubmissionPage.tsx` | Defines `StatusVisual`, primary status flow, secondary status visuals, status normalization, polling, and websocket handling. |
| `src/features/job_history/components/JobHistoryTable.tsx` | Maps and displays status values for history rows, including live update behavior. |
| `src/components/NVFlareClientSnapshot.tsx` | Defines `ClientStatus` and client/participation display rules. |

## Job History and Results Types

There is no dedicated `src/features/job_history/types/` directory. The job-history/result type model is split across utilities and components.

### `src/features/job_history/utils/JobsDataUtils.tsx`

Exported/shared types:

| Type | Shape/use |
| --- | --- |
| `FunctionConfig` | `Record<string, string>` for per-workflow function config. |
| `WorkflowErrorJson` | Error payload with optional timestamp, job ID, workflow, round, stage, exception type, message, traceback, error, client, and task. |
| `WorkflowJobData` | `{ workflowId, functionName, jobData, functionConfig?, workflowError? }`. Used by the results page. |
| `ProfileSummaryWorkflowRoundMetrics` | Per-round server/client timing and payload metrics. |
| `ProfileSummaryWorkflows` | Workflow-name to round metrics map. |
| `ProfileSummarySystemMetrics` | Wall time, CPU, network, and memory metrics. |
| `CombinedWorkflowMetrics` | Combined server/client workflow metrics. |
| `ProfileSummary` | Job/site/role/extra/workflows/system metrics object. |
| `WorkflowJobDataResponse` | `{ workflows: WorkflowJobData[]; profileSummary: ProfileSummary | null }`. |

Internal response types in the same file:

| Type | Use |
| --- | --- |
| `MappingResponse` | Response from result mapping endpoint. Includes `workflow_dirs`, optional `profile_summary`, and optional `error`. |
| `JobResultsResponse` | Response from job results endpoint. Includes `job_data`, optional `function_config`, and optional `error`. |
| `FunctionConfigResponse` | Response from function config endpoint. Includes optional `function_config` and `error`. |
| `JobInfoResponse` | Response from job info endpoint. Includes optional `job` and `error`. |

`JobsDataShape` is imported from `SurvivabilityComponent.tsx` and is currently `any`, so the exact result payload remains loosely typed.

### `src/features/job_history/utils/ExportDocTypes.tsx`

The export system has a separate report-document model.

```ts
export type ExportFormat = "pdf" | "docx" | "html" | "png";
export type ExportKeyValue = { label: string; value: string };
```

`ExportBlock` is a discriminated union:

| Block kind | Shape |
| --- | --- |
| `heading` | `{ kind: "heading"; text; level?; optionId? }` |
| `paragraph` | `{ kind: "paragraph"; text; optionId? }` |
| `keyValues` | `{ kind: "keyValues"; items; columns?; optionId? }` |
| `table` | `{ kind: "table"; columns; rows; optionId? }` |
| `image` | `{ kind: "image"; dataUrl; alt?; caption?; width?; height?; optionId? }` |
| `html` | `{ kind: "html"; html; optionId? }` |
| `spacer` | `{ kind: "spacer"; mm?; size?; optionId? }` |
| `pageBreak` | `{ kind: "pageBreak"; optionId? }` |

Other export types:

| Type | Meaning |
| --- | --- |
| `ExportSectionOption` | Section/option checkbox metadata: `id`, `label`, optional `checkedByDefault`. |
| `ExportWorkflow` | Per-workflow export section with workflow ID, title, blocks, and options. |
| `ExportSection` | Top-level export section with optional blocks, workflows, and options. |
| `ExportSectionSelection` | Final selected section/options/workflows shape. |
| `ExportDocument` | Full generated report document with title, generated timestamp, and sections. |

### `ExportSectionSelectionModal.tsx`

This file defines the modal-local selection shape:

```ts
export type ExportWorkflowSelectionBySectionId = Record<
  string,
  {
    workflowIds: string[];
    optionSelectionsByWorkflowId: Record<string, string[]>;
  }
>;
```

The modal props are local, not exported:

```ts
interface ExportSectionSelectionModalProps {
  isOpen: boolean;
  format: ExportFormat | null;
  sections: ExportSectionDraft[];
  isExporting?: boolean;
  onBack: () => void;
  onClose: () => void;
  onExport: (
    sectionIds: string[],
    optionSelectionsBySectionId: Record<string, string[]>,
    workflowSelectionsBySectionId: ExportWorkflowSelectionBySectionId
  ) => void;
}
```

## Client Snapshot Types

`src/components/NVFlareClientSnapshot.tsx` exports client status and participation selection types.

### `ClientStatus`

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

### `ClientParticipationSelection`

```ts
export interface ClientParticipationSelection {
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
}
```

This is the exact shape passed into `JobSubmissionPage.tsx` and submitted in the final job payload.

### `ClientSnapshotProps`

The props interface is local:

```ts
interface ClientSnapshotProps {
  projectId?: number;
  filtersPayload?: any;
  functionsMap?: FunctionConfigs;
  thresholdConfig?: ThresholdConfig;
  header?: string;
  heartbeatWindowMs?: number;
  onState?: (state: { loading: boolean; clients: ClientStatus[] }) => void;
  onParticipationSelectionChange?: (selection: ClientParticipationSelection) => void;
  onError?: (message: string) => void;
  compact?: boolean;
  canSubmit?: boolean;
}
```

`filtersPayload` remains typed as `any` because it is a runtime-composed payload.

## Job Submission Request Type

There is no named TypeScript interface for the final job submission request. `JobSubmissionPage.tsx` builds `payload` as `any`.

Verified payload shape:

```ts
type JobSubmissionRequest = {
  project_id: number;
  filters: {
    name: string;
    conditions: Condition[];
  };
  functions_map: FunctionConfigs | Record<string, Record<string, any>[]>;
  submitter: string;
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
  datasource_group?: number;
  workflow_group_data?: WorkflowGroupData;
  threshold_config?: {
    method: ThresholdMethod;
    threshold: number;
  };
};
```

The request is sent to:

```text
POST ${API_BASE}${API_SUBMIT_JOB}
```

with JSON body.

The submit response is stored in `result` as `any`. `JobSubmissionPage.tsx` expects `data.job_id` when status tracking should start.

## Landing Page Types

`src/types/LandingPage.tsx` defines the optimized landing API contracts:

- `LandingHomeJobStatus`
- `LandingHomeUserRole`
- `LandingHomeFunction`
- `LandingHomeSummary`
- `LandingHomeResponse`
- `LandingProjectSummary`
- `LandingProjectResponse`

`LandingProjectSummary` reuses `ProjectDatasourceGroup` and `ProjectFunctionCapability`; recent jobs reuse the existing `NVFlareJob` type.

## Backend Endpoint-to-Type Mapping

| Endpoint constant/path | Caller file(s) | Request type currently represented by | Response type currently represented by |
| --- | --- | --- | --- |
| `POST /user/role` | `src/pages/LoginPage.tsx` | Inline `{ username }` object. No shared request type. | `UserSession`-compatible object with role, username, user ID, FHIR source, and projects. No named response type in caller. |
| `POST ${API_BASE}${API_LANDING_HOME}` | `src/components/SHAREHomeDashboard.tsx` | None. | `LandingHomeResponse` / `LandingHomeSummary`. |
| `POST ${API_BASE}${API_LANDING_PROJECT}` | `src/components/ProjectListComponent.tsx` | `{ project_id: number }`. | `LandingProjectResponse`; recent jobs reuse `NVFlareJob[]`. |
| `POST ${API_BASE}${API_PROJECTS_LIST}` | `src/components/ProjectListComponent.tsx` | No shared named request type. | `Project[]` or project list payload consumed as project rows. |
| `POST ${API_BASE}${API_PROJECTS_FHIR_SOURCE}` | `FilterScreenPatients.tsx`, `FilterScreenObservationsFHIR.tsx` | Inline project/user payloads. | Datasource/FHIR source payload; no shared response type. |
| `POST ${API_BASE}${API_FILTERS_FETCH}` | `FilterHistoryTable.tsx`, `JobHistoryMain.tsx`, `FilterSummarySection.tsx` | Inline project/user payloads. | Filter rows including `FilterCollection`-compatible JSON strings; no shared full response type. |
| `POST ${API_BASE}${API_FILTERS_FETCH_SINGLE}` | `JobHistoryMain.tsx`, `FilterSummarySection.tsx` | Inline filter ID lookup payload. | Single filter payload; no shared full response type. |
| `POST ${API_BASE}${API_CLIENTS_CONNECTION_STATUS}` | `NVFlareClientSnapshot.tsx` | Inline request built from project/filter/function/threshold context. | Normalized into `ClientStatus[]`. Raw response uses `any`. |
| `POST ${API_BASE}${API_CLIENTS_PARTICIPATION_STATUS}` | `NVFlareClientSnapshot.tsx` | Inline request built from project/filter/function/threshold context. | Normalized into `ClientStatus[]` participation fields. Raw response uses `any`. |
| `POST ${API_BASE}${API_SUBMIT_JOB}` | `JobSubmissionPage.tsx` | Runtime `payload: any`; see `JobSubmissionRequest` above. | `result: any`; expects `job_id` for status tracking. |
| `POST ${API_BASE}${API_JOB_HISTORY}` | `JobHistoryTable.tsx` | Inline history lookup payload. | `NVFlareJob[]`/history rows. |
| `POST ${API_BASE}${API_JOB_STATUS}` | `JobSubmissionPage.tsx`, `JobHistoryTable.tsx` | Inline `{ job_id }` style payloads. | Status payload parsed as `any`; feeds status text/log state. |
| `WEBSOCKET ${WS_API_BASE}${API_JOB_STATUS_WEBSOCKET}/{jobId}` | `JobSubmissionPage.tsx`, `JobHistoryTable.tsx` | URL path job ID. | Message parsed as status/log JSON; no named message type. |
| `POST /jobs/info` | `JobsDataUtils.tsx` | Inline job ID payload. | Internal `JobInfoResponse` with `job?: NVFlareJob | null`. |
| `POST ${API_BASE}${API_JOB_RESULTS}` | `JobsDataUtils.tsx` | Inline job/workflow payload. | Internal `JobResultsResponse`. |
| `POST ${API_BASE}${API_JOB_RESULTS_MAPPING}` | `JobsDataUtils.tsx` | Inline job payload. | Internal `MappingResponse`. |
| `POST ${API_BASE}/jobs/function/config` | `JobsDataUtils.tsx` | Inline job/workflow payload. | Internal `FunctionConfigResponse`. |

Backend route file names are not present in the frontend archive. Endpoint implementation files cannot be verified from this package alone.

## Public JSON Schema-to-Type Mapping

### Filter config JSON

Static filter config files map to `FilterSchema` and `ControlSchema` from `src/types/FilterSchema.tsx`.

Expected top-level shape:

```ts
type PublicFilterConfig = FilterSchema;
```

Expected important fields:

```ts
type PublicFilterConfig = {
  version?: string;
  resource?: { type?: string } | string;
  controls?: ControlSchema[];
  defaultsResolver?: Record<string, any>;
};
```

Controls may contain FHIR query metadata, local query metadata, save targets, and UI hints.

### Analysis config JSON

Analysis config editing types are local to `src/features/user_manager/pages/AnalysisManager.tsx`. They are not exported as shared types.

The page defines local flexible interfaces for query/data/config sections with `[key: string]: any`, including entries with optional `args?: Record<string, any>`.

A future cleanup should move these local interfaces into a shared type file if the analysis config becomes a runtime contract used by multiple features.

### Test/local data JSON

FHIR/test-data records are represented with lightweight `Patient`, `Medication`, `Observation`, and `ObservationComponent` interfaces where possible. Some test-data parsing still uses `any` because the raw bundle shape is broader than the normalized frontend records.

## Important Inline Props Interfaces

Many props interfaces are local to component files. Important local props include:

| File | Local props/type | Notes |
| --- | --- | --- |
| `src/App.tsx` | `AppScreen` | Top-level screen union. Exported. |
| `src/pages/LoginPage.tsx` | `LoginPageProps` | Login success callback into `App.tsx`. |
| `src/pages/SHARELandingPage.tsx` | `SHARELandingPageProps` | Authenticated landing/workspace routing callbacks and selected-project context. |
| `src/pages/NavigationSelector.tsx` | `NavigationOption`, `NavigationSelectorProps` | `NavigationOption` is exported; props are local. |
| `src/components/HeaderBar.tsx` | `HeaderBarProps` | Shared selected project/datasource/header props. |
| `src/components/FunctionSelector.tsx` | `FunctionArg`, `FunctionOption`, `FunctionSelectorProps` | `FunctionArg` and `FunctionOption` are exported; props are local. |
| `src/components/NVFlareClientSnapshot.tsx` | `ClientStatus`, `ClientParticipationSelection`, `ClientSnapshotProps` | First two are exported; props are local. |
| `src/features/job_runner/JobRunnerMain.tsx` | `JobRunnerMainProps` | Feature entry props from `App.tsx`. |
| `src/features/job_runner/pages/FunctionSelectionPage.tsx` | `Props` | Function/threshold selection page. |
| `src/features/job_runner/pages/WorkflowGroupSelectionPage.tsx` | `WorkflowGroupSelectionPageProps` | Workflow group screen props. |
| `src/features/job_runner/pages/JobSubmissionPage.tsx` | `JobSubmissionProps` | Final job submission props. |
| `src/features/job_runner/components/FilterControlsSection.tsx` | `FilterControlsSectionProps` | Exported props for schema-driven filter controls. |
| `src/features/job_runner/pages/filters/FilterHistoryTable.tsx` | `FilterHistoryRow`, `FilterHistoryTableProps` | Row type exported; props local. |
| `src/features/job_history/JobHistoryMain.tsx` | `JobHistoryMainProps` | Feature entry props. |
| `src/features/job_history/components/JobHistoryTable.tsx` | `NVFlareJobHistoryPageProps` | History table props. |
| `src/features/job_history/pages/ResultsPage.tsx` | `ResultsPageProps` | Results page props. |
| `src/features/job_history/components/ResultCard.tsx` | `ScalarResultWorkflowProps`, `ResultCardProps` | Scalar result props exported for specific result cards. |
| `src/features/job_history/components/SurvivabilityComponent.tsx` | `KMAggRow`, `JobsDataShape`, `SurvivabilityComponentHandle`, `SurvivabilityComponentProps` | `JobsDataShape` is currently `any`. |
| `src/features/job_history/components/export/ExportFormatModal.tsx` | `ExportFormatModalProps` | Export format modal props. |
| `src/features/job_history/components/export/ExportSectionSelectionModal.tsx` | `ExportWorkflowSelectionBySectionId`, `ExportSectionSelectionModalProps` | Workflow selection type exported; props local. |
| `src/features/nvflare_manager/NVFlareManagerMain.tsx` | `NVFlareManagerMainProps` | Manager feature props. |
| `src/features/user_manager/UserManagerMain.tsx` | `UserManagerMainProps` | User manager feature props. |
| `src/features/user_manager/pages/FilterManagerPage.tsx` | `FilterManagerPageProps` and local config interfaces | Public filter config editor. |
| `src/features/user_manager/pages/AnalysisManager.tsx` | `AnalysisManagerPageProps` and local config interfaces | Public analysis config editor. |

## Known `any` Usage That Should Eventually Become Typed

The reviewed frontend still relies on `any` in several important areas. These are the highest-value typing cleanup targets.

| Area | Current use | Better future type |
| --- | --- | --- |
| Public filter control defaults | `ControlSchema.default?: any`, `defaultsResolver?: Record<string, any>` | Union based on control type: string, string[], number, boolean, `[string, string]`, etc. |
| Project JSON config | `JsonObject = Record<string, any>` | Function config schema for fixed/variable/override config. |
| Function selector config parsing | Multiple `Record<string, any>` and `pf: any` casts | Strong `ProjectFunctionCapability` normalization helpers. |
| Job submission payload | `const payload: any` and `result: any` | Named `JobSubmissionRequest` and `JobSubmissionResponse`. |
| Client snapshot raw responses | Raw response rows and participation maps use `any` | Named `ClientConnectionStatusResponse` and `ClientParticipationStatusResponse`. |
| Job status websocket/polling payloads | Status data parsed as `any` | Named `JobStatusResponse` and websocket message union. |
| Results payloads | `JobsDataShape = any` | Function-specific result payload union for survival, mean, t-test, chi-square, standard deviation. |
| Kaplan-Meier/result parsing | Multiple `any` casts around `S_output`, `times`, CI, raw groups | `SurvivalAnalysisResult` type with legacy/processed variants. |
| Analytics metrics rendering | Metrics use `any` guards | Reuse `ProfileSummary`, `CombinedWorkflowMetrics`, and round metric types consistently. |
| Filter manager editor | Local `[key: string]: any` config interfaces | Shared `FilterSchema` plus extension type for editable extras. |
| Analysis manager editor | Local `[key: string]: any` config interfaces | Shared analysis query/data config schema. |
| Raw FHIR/test-data bundles | Raw entries use `any` | Minimal FHIR Bundle/entry/resource types for Patient, Observation, Condition, Medication. |

## Recommended Type Additions

These are not present today but would reduce runtime ambiguity:

```ts
export type JobSubmissionRequest = {
  project_id: number;
  filters: { name: string; conditions: Condition[] };
  functions_map: FunctionConfigs;
  submitter: string;
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
  datasource_group?: number;
  workflow_group_data?: WorkflowGroupData;
  threshold_config?: {
    method: ThresholdMethod;
    threshold: number;
  };
};

export type JobSubmissionResponse = {
  job_id?: string;
  status?: string;
  message?: string;
  error?: string;
};

export type JobStatusResponse = {
  job_id?: string;
  status?: string;
  jobStatus?: string;
  log?: string[];
  jobLog?: string[];
  run_duration?: string;
  functions?: string[];
  error?: string;
};
```

These additions should be introduced only when matching the backend response exactly, because the current frontend tolerates multiple response shapes.
