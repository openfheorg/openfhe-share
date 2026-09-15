# API Configuration and Backend Contracts

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/constants/Constants.tsx` | Central frontend constants, including backend API endpoint URLs, websocket base URL behavior, supported function names, cytoband lists, and feature descriptions. |
| `src/pages/LoginPage.tsx` | Calls the user role endpoint during login. |
| `src/pages/SHARELandingPage.tsx` | Authenticated landing/workspace shell that hosts `ProjectListComponent`. |
| `src/components/SHAREHomeDashboard.tsx` | Calls the global Home landing summary endpoint. |
| `src/components/ProjectListComponent.tsx` | Calls the project list endpoint and hydrates each project with public filter schema JSON. |
| `src/App.tsx` | Holds selected project/session state, derives selected datasource/FHIR source from the login payload, validates FHIR URLs, and passes project/session context into feature modules. |
| `src/context/UserRoleContext.tsx` | Defines the frontend session, project access, and datasource interfaces used by API responses. |
| `src/features/job_runner/` | Builds filters, datasource-group selection, workflow-group selection, client participation selections, status tracking, and job submission payloads. |
| `src/features/job_history/` | Calls job history, job status, job info, result, result mapping, function config, and saved filter endpoints. |
| `src/components/NVFlareClientSnapshot.tsx` | Calls client connection and participation status endpoints. |
| `src/features/user_manager/pages/AnalysisManager.tsx` | Loads public analysis config JSON files. |
| `src/features/user_manager/pages/FilterManagerPage.tsx` | Loads public filter config JSON files for manager display. |

## API Constant Source

Backend endpoint URLs are centralized in `src/constants/Constants.tsx`.

This file should be treated as the frontend source of truth for backend URL construction where a constant exists. Several endpoint strings still remain hardcoded outside `Constants.tsx`; those are listed in [Known Hardcoded Endpoint Strings](#known-hardcoded-endpoint-strings).

## Base URL Selection

| Constant | Current value/logic | Notes |
| --- | --- | --- |
| `LOCAL_API_BASE` | `http://localhost:8000` | Used for development `API_BASE`. Not exported. |
| `CLIENT_API_BASE_PORT` | `8088` | Base port for the per-site client results agents. |
| `CLIENT_API_BASE` | `http://127.0.0.1:${CLIENT_API_BASE_PORT}` | Single co-located results agent used by hosted deployments. |
| `IS_LOCAL_APP` | `process.env.NODE_ENV === "development"` | True for `npm start` development builds. |
| `IS_STANDALONE_APP` | `process.env.REACT_APP_BUILD_FLAVOR === "local"` | True for the self-hosted standalone bundle. That bundle is a production build, so `NODE_ENV` cannot distinguish it; `REACT_APP_BUILD_FLAVOR` is baked in at image build time by `standalone/docker_stage/frontend.Dockerfile` and defaults to `local`. |
| `PROD_FALLBACK_API_BASE` | `https://api.example.org` | Used when not in development and `REACT_APP_API_BASE` is not set. |
| `ALB_API_BASE` | `http://api.example.org` | Exported, but no current frontend import was found in the uploaded source. |
| `PROD_FALLBACK_API_WS_BASE` | `wss://ws.example.org/prod` | Used as websocket fallback when not in development and `REACT_APP_API_BASE` is not set. |
| `API_BASE` | Development: `LOCAL_API_BASE`; otherwise `process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_BASE` | Main backend API base. |
| `WS_API_BASE` | Development: `LOCAL_API_BASE`; otherwise `process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_WS_BASE` | Current code uses `REACT_APP_API_BASE` for websocket override. There is no separate `REACT_APP_WS_API_BASE` in `Constants.tsx`. |

### Client Results Base Selection

Client result data is not served by `API_BASE`. It is served by a local results agent, and the base URL is resolved by the exported function:

```ts
export function getClientApiBase(clientName?: string | null): string
```

Resolution rules:

| Condition | Result |
| --- | --- |
| Neither `IS_LOCAL_APP` nor `IS_STANDALONE_APP` | Returns `CLIENT_API_BASE`. Hosted browsers reach a single co-located results agent. |
| Local development or standalone, `clientName` matches `/^site[-_]?(\d+)$/i` | Returns `http://127.0.0.1:${CLIENT_API_BASE_PORT + siteNumber}`, so `site1` resolves to `8089`, `site2` to `8090`, and so on. Each simulated site runs its own agent. |
| Local development or standalone, `clientName` missing or not a `site<N>` name | Throws `The logged-in client does not have a valid NVFlare client name: {name or <missing>}`. |
| Local development or standalone, site number is not a safe integer of at least `1` | Throws `Invalid NVFlare client site number in {name}`. |

The client name comes from the session. `/user/role` returns `client_name`, `LoginPage.tsx` stores it on the session, and `ResultsPage.tsx` passes `{ role, client_name }` into the result helpers in `JobsDataUtils.tsx`.

## Full Constant Table

| Constant | Value | Imported by |
| --- | --- | --- |
| `CLIENT_API_BASE_PORT` | `8088` | No direct imports found. Used by `CLIENT_API_BASE` and `getClientApiBase`. |
| `CLIENT_API_BASE` | `http://127.0.0.1:8088` | No direct imports found. Returned by `getClientApiBase` for hosted deployments. |
| `IS_LOCAL_APP` | `process.env.NODE_ENV === "development"` | No direct imports found. Used by `getClientApiBase`. |
| `IS_STANDALONE_APP` | `process.env.REACT_APP_BUILD_FLAVOR === "local"` | No direct imports found. Used by `getClientApiBase`. |
| `getClientApiBase` | Function returning the per-site or hosted client results base URL | `src/features/job_history/utils/JobsDataUtils.tsx` |
| `ALB_API_BASE` | `http://api.example.org` | No imports found. |
| `PROD_FALLBACK_API_WS_BASE` | `wss://ws.example.org/prod` | No direct imports found. Used by `WS_API_BASE`. |
| `API_BASE` | Environment-derived backend base URL | `src/components/NVFlareClientSnapshot.tsx`, `src/components/ProjectListComponent.tsx`, `src/features/job_history/components/FilterSummarySection.tsx`, `src/features/job_history/components/JobHistoryTable.tsx`, `src/features/job_history/JobHistoryMain.tsx`, `src/features/job_history/utils/JobsDataUtils.tsx`, `src/features/job_runner/pages/filters/default/FilterScreenPatients.tsx`, `src/features/job_runner/pages/filters/FilterHistoryTable.tsx`, `src/features/job_runner/pages/filters/FilterScreenObservationsFHIR.tsx`, `src/features/job_runner/pages/JobSubmissionPage.tsx`, `src/pages/LoginPage.tsx` |
| `WS_API_BASE` | Environment-derived websocket base URL | `src/features/job_history/components/JobHistoryTable.tsx`, `src/features/job_runner/pages/JobSubmissionPage.tsx` |
| `API_SUBMIT_JOB` | `/nvflare/jobs/submit` | `src/features/job_runner/pages/JobSubmissionPage.tsx` |
| `API_JOB_HISTORY` | `/nvflare/jobs/history` | `src/features/job_history/components/JobHistoryTable.tsx` |
| `API_JOB_RESULTS_CONTEXT` | `/nvflare/jobs/results_context` | `src/features/job_history/utils/JobsDataUtils.tsx` |
| `API_JOB_STATUS` | `/jobs/status` | `src/features/job_history/components/JobHistoryTable.tsx`, `src/features/job_runner/pages/JobSubmissionPage.tsx` |
| `API_JOB_STATUS_WEBSOCKET` | `/jobs/status/ws` | No imports found. The same string is locally redeclared in `JobSubmissionPage.tsx` and `JobHistoryTable.tsx`. |
| `API_JOB_RESULTS` | `/jobs/results` | `src/features/job_history/utils/JobsDataUtils.tsx` |
| `API_JOB_RESULTS_MAPPING` | `/jobs/results/mapping` | `src/features/job_history/utils/JobsDataUtils.tsx` |
| `API_JOB_RESULTS_FUNCTION_CONFIG` | `/jobs/function/config` | `src/features/job_history/utils/JobsDataUtils.tsx` |
| `API_FILTERS_FETCH_SINGLE` | `/filters/fetch_single_filter` | `src/features/job_history/components/FilterSummarySection.tsx`, `src/features/job_history/JobHistoryMain.tsx` |
| `API_FILTERS_FETCH` | `/filters/fetch_filters` | `src/features/job_runner/pages/filters/FilterHistoryTable.tsx` |
| `API_FUNCTIONS_SUPPORTED` | `/functions/supported_functions` | No imports found in the uploaded source. Project functions are currently read from the selected `Project` object. |
| `API_CLIENTS_PARTICIPATION_STATUS` | `/clients/participation/status` | `src/components/NVFlareClientSnapshot.tsx` |
| `API_CLIENTS_CONNECTION_STATUS` | `/clients/connection/status` | `src/components/NVFlareClientSnapshot.tsx` |
| `API_LANDING_HOME` | `/landing/home` | `src/components/SHAREHomeDashboard.tsx` |
| `API_LANDING_PROJECT` | `/landing/project` | `src/components/ProjectListComponent.tsx` |
| `API_PROJECTS_LIST` | `/projects/list` | `src/components/ProjectListComponent.tsx` |
| `API_PROJECTS_FHIR_SOURCE` | `/projects/fhir/source` | `src/features/job_runner/pages/filters/default/FilterScreenPatients.tsx`, `src/features/job_runner/pages/filters/FilterScreenObservationsFHIR.tsx` |
| `SupportedFunction` | Enum: `SURVIVAL_ANALYSIS`, `CHI_SQUARE_TEST`, `STANDARD_DEVIATION`, `MEAN`, `T_TEST` | `src/features/job_history/pages/ResultsPage.tsx` |
| `DELETION_REGIONS` | Static cytoband list | No imports found in the uploaded source. |
| `AMPLIFICATION_REGIONS` | Static cytoband list | No imports found in the uploaded source. |
| `Cytoband` | Union type derived from deletion/amplification region lists | No imports found in the uploaded source. |
| `description_job_runner` | Job runner screen description text | `src/features/job_runner/JobRunnerMain.tsx` |
| `description_job_history` | Job history screen description text | `src/features/job_history/JobHistoryMain.tsx` |
| `description_nvflare_manager` | NVFlare manager screen description text | `src/features/nvflare_manager/NVFlareManagerMain.tsx` |

## Backend Endpoint Areas

| Area | Backend purpose | Current frontend callers |
| --- | --- | --- |
| User/session | Resolve user role and project access metadata. | `LoginPage.tsx` |
| Landing summaries | Fetch global Home and selected-project landing read models. | `SHAREHomeDashboard.tsx`, `ProjectListComponent.tsx` |
| Projects | Fetch full project configuration list. | `ProjectListComponent.tsx` |
| Project FHIR source proxy | Execute selected datasource/FHIR queries through the backend. | `FilterScreenPatients.tsx`, `FilterScreenObservationsFHIR.tsx` |
| Filters | Fetch saved filter sets and a single saved filter set. | `FilterHistoryTable.tsx`, `FilterSummarySection.tsx`, `JobHistoryMain.tsx` |
| Clients | Fetch NVFlare connection and participation state. | `NVFlareClientSnapshot.tsx` |
| NVFlare jobs | Submit jobs and fetch job history. | `JobSubmissionPage.tsx`, `JobHistoryTable.tsx` |
| Job status | Poll or stream live job status and logs. | `JobSubmissionPage.tsx`, `JobHistoryTable.tsx` |
| Job results | Fetch job info, workflow mapping, workflow result payloads, and function config. | `JobsDataUtils.tsx` |

Backend implementation details for the landing endpoints are documented in `../backend/24-landing-page-summary-endpoints.md`; the remainder of this document focuses on the frontend-facing contracts and callers.

## Shared Frontend Types

### `UserSession`

Defined in `src/context/UserRoleContext.tsx`.

```ts
interface UserSession {
  role: UserRole;
  username: string;
  user_id?: number | null;
  client_id?: number | null;
  client_name?: string | null;
  fhir_source: string | null;
  projects: UserProjectAccess[];
  selected_project_id?: number | null;
  selected_project_datasources?: UserProjectDatasource[];
}
```

### `UserProjectAccess`

```ts
interface UserProjectAccess {
  project_id: number;
  project_name: string;
  datasources: UserProjectDatasource[];
}
```

### `UserProjectDatasource`

```ts
interface UserProjectDatasource {
  source: string;
  datasource_group_id: number | null;
  datasource_group_name: string | null;
  is_default_group: boolean;
}
```

### `Project`

Defined in `src/types/Project.tsx`. The selected project carries project metadata, function capabilities, filter schema metadata, datasource group metadata, and workflow group metadata.

Important fields used by API-related flows include:

```ts
interface Project {
  id: number;
  name: string;
  function_restrictions_enabled: boolean;
  filter_system?: FilterSystem | null;
  filter_system_allowed_filter_types?: FilterType[] | null;
  filter_schemas: Partial<Record<FilterType, FilterSchema>>;
  functions: ProjectFunctionCapability[];
  datasource_groups_defined?: boolean;
  datasource_groups?: ProjectDatasourceGroup[] | null;
  default_datasource_group?: ProjectDatasourceGroup | null;
  workflow_groups?: ProjectWorkflowGroup[] | null;
}
```

### `NVFlareJob`

Defined in `src/types/JobsDataTypes.tsx`. Job history and result screens depend on this shape.

Important fields include:

```ts
interface NVFlareJob {
  id: number;
  nvflare_assigned_id?: string;
  filter_id?: number;
  status?: string;
  job_runner_id?: string;
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

## Login Contract

### Caller

`src/pages/LoginPage.tsx`

### Endpoint

`POST ${API_BASE}/user/role`

This endpoint is hardcoded in `LoginPage.tsx` and does not currently have a constant in `Constants.tsx`.

### Request

```json
{
  "username": "initiator"
}
```

The password field exists in the UI but is not sent to the backend.

### Expected response

```json
{
  "role": "INITIATOR",
  "username": "initiator",
  "user_id": 1,
  "client_id": null,
  "client_name": null,
  "projects": [
    {
      "project_id": 1,
      "project_name": "Example Project",
      "datasources": [
        {
          "source": "http://example/fhir",
          "datasource_group_id": null,
          "datasource_group_name": null,
          "is_default_group": true
        }
      ]
    }
  ]
}
```

### Frontend handling

`LoginPage.tsx` trims the username, posts `{ username }`, and expects `data.role` to exist. On success, it calls `onLogin` with:

```ts
{
  role: data.role as UserRole,
  username: data.username || trimmedUsername,
  user_id: data.user_id ?? null,
  client_id: data.client_id ?? null,
  client_name: typeof data.client_name === "string" ? data.client_name : null,
  projects: Array.isArray(data.projects) ? data.projects : []
}
```

`client_id` and `client_name` come from the NVFlare client mapped to the user. For a `CLIENT` session, `client_name` is the site name that later selects the client results base URL.

`App.tsx` stores that object in `sessionBase`, clears the selected project, and moves to `home`, which renders global Home when no project is selected.

### Error and loading behavior

There is no explicit loading spinner for login. The submit button is disabled only when the username is empty.

Failure behavior:

| Condition | UI behavior |
| --- | --- |
| `!res.ok` | Attempts to parse JSON and displays `data.error || "Login failed"`. |
| Response lacks `role` | Displays `Role not found for user`. |
| Fetch/network exception | Displays `Network error`. |

### Navigation/access behavior

The returned `role` is stored in `UserRoleContext`. Other modules use role helpers such as `useUserRole()`, `useUserSession()`, and `useClientName()` to branch behavior. For example, `JobsDataUtils.tsx` resolves workflow result requests through `getClientApiBase(client_name)` instead of `API_BASE` when the role is `CLIENT`.

## Landing Page Contracts

### Global Home

Caller: `src/components/SHAREHomeDashboard.tsx`

Endpoint:

```http
POST ${API_BASE}${API_LANDING_HOME}
```

No request body is required. The frontend expects `status: "SUCCESS"` and a `home` object typed as `LandingHomeSummary`. It includes total jobs/users/functions, grouped job statuses, grouped user roles, and the backend function catalog.

The component retains the last successful payload while revalidating so refresh/navigation does not blank the Home screen.

### Project Landing

Caller: `src/components/ProjectListComponent.tsx`

Endpoint:

```http
POST ${API_BASE}${API_LANDING_PROJECT}
Content-Type: application/json

{
  "project_id": 2
}
```

The frontend expects `status: "SUCCESS"`, a `project` object typed as `LandingProjectSummary`, and `recent_jobs` containing at most the landing-page recent-job set. The response supplies project counts/capabilities/datasource groups plus recent jobs without requiring the full Job History payload.

The full `/projects/list` contract remains in use for complete project configuration and public filter-schema hydration.

## Project Contracts

### Project list caller

`src/components/ProjectListComponent.tsx`, hosted by `src/pages/SHARELandingPage.tsx`.

### Endpoint

`POST ${API_BASE}${API_PROJECTS_LIST}`

Constant value: `/projects/list`

### Request

```json
{}
```

The caller sends no request body; it only sets `method: "POST"` and `Content-Type: application/json`.

### Expected response

```json
{
  "projects": [
    {
      "id": 1,
      "name": "Example Project",
      "description": "Project description",
      "status": "ACTIVE",
      "fixed": true,
      "function_restrictions_enabled": true,
      "filter_system": "DEFAULT",
      "filter_system_allowed_filter_types": ["PATIENT_QUERY", "PATIENT_DATA"],
      "functions": [],
      "datasource_groups_defined": false,
      "datasource_groups": [],
      "default_datasource_group": null,
      "workflow_groups": [],
      "create_date": "2026-01-01T00:00:00",
      "update_date": "2026-01-01T00:00:00"
    }
  ]
}
```

### Frontend handling

`ProjectListComponent.tsx` validates that `data.projects` is an array. Each project is passed through `hydrateProjectFilterSchemas`, which loads public filter schema files based on `project.filter_system`.

The selected `Project` object is passed back to `App.tsx`; `App.tsx` stores it in `project` and keeps the user in the `home` landing environment so the project landing page is shown.

### Error and loading behavior

`ProjectListComponent.tsx` keeps local `projects`, `loading`, and `error` state.

| Condition | UI behavior |
| --- | --- |
| Request starts | `loading` becomes `true`, `error` is cleared. |
| `!res.ok` | Attempts to parse JSON and displays `data.error || "Failed to load projects"`. |
| Response does not contain `projects` array | Displays `Invalid response from server`. |
| Fetch/network exception | Displays `Network error`. |
| Request finishes | `loading` becomes `false`. |

`ProjectListComponent.tsx` owns project-list loading/error state and can report it through `onStateChange` when used by a caller that needs the status.

## Project FHIR Source Contract

### Callers

- `src/features/job_runner/pages/filters/default/FilterScreenPatients.tsx`
- `src/features/job_runner/pages/filters/FilterScreenObservationsFHIR.tsx`

### Endpoint

`POST ${API_BASE}${API_PROJECTS_FHIR_SOURCE}`

Constant value: `/projects/fhir/source`

### Request

```json
{
  "username": "initiator",
  "project_id": 1,
  "datasource_group": 2,
  "execute_query": "Patient?gender=female"
}
```

`datasource_group` is the selected datasource group ID. It may be `null` when no explicit group is selected.

### Expected response

The exact response type is defined locally as `ProjectFHIRSourceQueryResponse` in the filter screens. The frontend expects a JSON payload that can support the patient/observation filter execution flows. The backend response is consumed as parsed JSON and then mapped into local patient or observation result state.

### Error and loading behavior

Both callers throw when `!response.ok` with an error message that includes the HTTP status. The screens manage their own preview/execution loading state around the request.

### Datasource source selection in `App.tsx`

`App.tsx` does not call `/projects/fhir/source` directly. It derives the currently displayed FHIR source from the login/session payload:

1. Find the selected project entry in `sessionBase.projects`.
2. Read that entry's `datasources` array.
3. Prefer the datasource where `is_default_group` is true.
4. Fall back to the first datasource.
5. Hide the source on `login`, `home`, and `nvflare_manager` screens; project workflow screens derive it from the active project datasource assignments.
6. Validate non-JSON sources as URLs ending in `/fhir`.

If validation fails, `HeaderBar` receives `null` and `userSession.fhir_source` is set to `null`.

## Public Filter Schema Loading

Some filter definitions are frontend public JSON files, not backend API calls.

### Project schema hydration

`ProjectListComponent.tsx` loads the following files for each project based on `project.filter_system`:

| Filter type | Public path |
| --- | --- |
| `PATIENT_QUERY` | `/filters/{filter_system}/patient/patient_query.json` |
| `PATIENT_DATA` | `/filters/{filter_system}/patient/patient_data.json` |
| `OBSERVATION` | `/filters/{filter_system}/observation/observation_filters.json` |
| `OBSERVATION_QUERY` | `/filters/{filter_system}/observation/observation_query.json` |
| `OBSERVATION_DATA` | `/filters/{filter_system}/observation/observation_data.json` |

If a schema fetch fails or returns non-OK, that schema is skipped. The project still loads.

### Runtime schema controls

`FilterControlsSection.tsx` first looks for a matching schema on the selected project. If no project schema exists, it fetches the provided `schemaUrl` with `cache: "no-store"`.

`FilterScreenObservationsFHIR.tsx` loads:

- `/filters/{filter_system}/observation/observation_query.json`
- `/filters/{filter_system}/observation/observation_data.json`

`FilterScreenPatients_CancerType.tsx` loads:

- `/filters/cancer_type/patient/patient_query.json`
- versioned test data under the public test-data folder using HEAD/GET probing and zip loading logic

`FilterManagerPage.tsx` loads manager-visible public config files:

- `/filters/default/patient/patient_query.json`
- `/filters/default/observation/observation_query.json`
- `/filters/default/observation/observation_data.json`

`AnalysisManager.tsx` loads:

- `/analysis_config/analysis_query.json`
- `/analysis_config/analysis_data.json`

## Saved Filter Contracts

### Fetch saved filters

Caller: `src/features/job_runner/pages/filters/FilterHistoryTable.tsx`

Endpoint:

`POST ${API_BASE}${API_FILTERS_FETCH}`

Constant value: `/filters/fetch_filters`

Request:

```json
{
  "project_id": 1
}
```

Expected response:

```json
{
  "filters": [
    {
      "id": 10,
      "name": "Saved filter name",
      "create_date": "2026-01-01T00:00:00",
      "update_date": "2026-01-01T00:00:00",
      "conditions": []
    }
  ]
}
```

Frontend handling:

- Maps each row into `FilterHistoryRow`.
- Converts `conditions` into a `FilterCollection` using `buildDefaultFilterCollectionFromConditions`.
- Clears selected and expanded filter IDs after loading.
- Resets pagination to page 1.

Error/loading behavior:

- Sets `loading` to `true` before request.
- On non-OK response or exception, logs `Failed to fetch filters` and clears rows.
- Sets `loading` to `false` in `finally`.

### Fetch one saved filter

Callers:

- `src/features/job_history/JobHistoryMain.tsx`
- `src/features/job_history/components/FilterSummarySection.tsx`

Endpoint:

`POST ${API_BASE}${API_FILTERS_FETCH_SINGLE}`

Constant value: `/filters/fetch_single_filter`

Request:

```json
{
  "filter_id": 10,
  "project_id": 1
}
```

Expected response:

```json
{
  "filter": {
    "id": 10,
    "name": "Saved filter name",
    "conditions": []
  }
}
```

Frontend handling:

- `JobHistoryMain.tsx` uses this when opening a previous job's results. It converts conditions into the current project filter collection and stores view-only job information.
- `FilterSummarySection.tsx` uses this to render a filter summary for a job history row.

Error/loading behavior:

- `JobHistoryMain.tsx` throws on non-OK response from the inner fetch helper.
- `FilterSummarySection.tsx` catches failures and sets `filterSet` to `null`.

## Client Connection and Participation Contracts

### Caller

`src/components/NVFlareClientSnapshot.tsx`

### Endpoints

| Mode | Endpoint |
| --- | --- |
| Connection state only | `POST ${API_BASE}${API_CLIENTS_CONNECTION_STATUS}` (`/clients/connection/status`) |
| Participation state | `POST ${API_BASE}${API_CLIENTS_PARTICIPATION_STATUS}` (`/clients/participation/status`) |

### Connection request

```json
{
  "project_id": 1,
  "username": "initiator"
}
```

`username` is included when the current role is `INITIATOR` and a username exists.

### Participation request

When participation data is requested, the request body includes `include_connection_state` and `participation_status`:

```json
{
  "project_id": 1,
  "username": "initiator",
  "include_connection_state": true,
  "participation_status": {
    "filters": {},
    "project_id": 1,
    "functions": {},
    "non_contributing_clients": ["site-2"],
    "exclude_analyzing_clients": ["site-3"],
    "threshold_config": {
      "method": "PROTECTED",
      "threshold": 20
    }
  }
}
```

`threshold_config` is included only when threshold settings are enabled and available.

### Expected response

```json
{
  "clients": [
    {
      "id": "client-1",
      "client_name": "site-1",
      "connected": true,
      "participation": "ACCEPT",
      "last_connect_time": "2026-01-01T00:00:00Z",
      "registered": true,
      "contributing_party": true,
      "analyzing_party": true
    }
  ]
}
```

The frontend maps backend client rows into `ClientStatus`:

```ts
interface ClientStatus {
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

### Frontend handling

`NVFlareClientSnapshot` supports connection-only and participation-aware modes. It can call the participation endpoint with connection-state inclusion, or merge a participation-only response into existing connection rows.

It reports state upward through:

```ts
onState?: (state: { loading: boolean; clients: ClientStatus[] }) => void;
onParticipationSelectionChange?: (selection: ClientParticipationSelection) => void;
onError?: (message: string) => void;
```

The submitted selection shape is:

```ts
interface ClientParticipationSelection {
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
}
```

### Error/loading behavior

The component uses local loading state and an abort controller. On non-OK response it throws `Clients API {status}`. Errors are surfaced through component state and optional `onError` callback.

## Job Submission Contract

### Caller

`src/features/job_runner/pages/JobSubmissionPage.tsx`

### Endpoint

`POST ${API_BASE}${API_SUBMIT_JOB}`

Constant value: `/nvflare/jobs/submit`

### Request

```json
{
  "project_id": 1,
  "filters": {},
  "functions_map": {
    "SURVIVAL_ANALYSIS": [
      {
        "name": "value"
      }
    ]
  },
  "submitter": "initiator",
  "non_contributing_clients": ["site-2"],
  "exclude_analyzing_clients": ["site-3"],
  "datasource_group": 2,
  "workflow_group_data": {
    "modeling_method": {
      "group_key": "modeling_method",
      "selected_values": ["cox_lasso"]
    }
  },
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 20
  }
}
```

Optional fields:

| Field | Included when |
| --- | --- |
| `datasource_group` | `selectedDatasourceGroupId !== null` |
| `workflow_group_data` | `workflowGroupData` exists and has keys |
| `threshold_config` | Threshold is enabled, method exists, and threshold is not null |

### Expected response

```json
{
  "job_id": "job-runner-id",
  "status": "QUEUED"
}
```

Only `job_id` is required by the current frontend to begin tracking. The full response is also stored in local `result` state.

### Frontend handling

On submit, the page:

1. Sets `submitting` to `true`.
2. Builds filters with `buildFiltersPayload`.
3. Builds the selected functions map.
4. Adds client contribution/analyzing exclusions from `NVFlareClientSnapshot`.
5. Adds datasource group, workflow group data, and threshold config when available.
6. Posts the payload.
7. Stores the response.
8. If `data.job_id` exists, stores it and starts status tracking.

### Error/loading behavior

On non-OK response, the code throws `API {status}`. On exception, it displays a composed submit error and sets `submitting` to `false`.

## Job Status Polling Contract

### Callers

- `src/features/job_runner/pages/JobSubmissionPage.tsx`
- `src/features/job_history/components/JobHistoryTable.tsx`

### Endpoint

`POST ${API_BASE}${API_JOB_STATUS}`

Constant value: `/jobs/status`

### Job submission polling request

```json
{
  "job_id": "job-runner-id",
  "$pw": "optional value from REACT_APP_MYSQL_SECRET_PW"
}
```

`JobSubmissionPage.tsx` includes `$pw`; `JobHistoryTable.tsx` does not.

### Job history polling/log request

```json
{
  "job_id": "job-runner-id"
}
```

### Expected response

```json
{
  "status": "DONE",
  "log": ["line 1", "line 2"],
  "run_duration": "00:01:23",
  "functions": ["SURVIVAL_ANALYSIS"]
}
```

### Frontend handling

`JobSubmissionPage.tsx` polls every `500` ms until websocket streaming takes over or a terminal status is reached. Terminal statuses are `DONE` and `FAILURE`.

`JobHistoryTable.tsx` also polls every `500` ms when live tracking a history row. Its terminal-status helper treats `DONE`, `FAILURE`, and strings containing failed/cancelled/aborted variants as terminal.

### Error/loading behavior

`JobSubmissionPage.tsx` stops polling and displays `Error polling job status: {message}` when polling fails.

`JobHistoryTable.tsx` stops polling and logs polling failures to the console.

## Job Status Websocket Contract

### Callers

- `src/features/job_runner/pages/JobSubmissionPage.tsx`
- `src/features/job_history/components/JobHistoryTable.tsx`

### Current local constant behavior

Both files locally redeclare:

```ts
const API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws";
```

This duplicates the exported constant in `Constants.tsx`.

### URL building

For local API bases, the websocket URL becomes:

```text
ws://localhost:8000/jobs/status/ws/local/{job_id}
```

For non-local API bases, the websocket URL becomes:

```text
{WS_API_BASE}?job_id={job_id}
```

The URL builder converts local `http://` to `ws://` and local `https://` to `wss://`.

### Expected message format

```json
{
  "type": "job_status",
  "status": "CLIENT_COMPUTE",
  "log": ["line 1", "line 2"],
  "run_duration": "00:01:23",
  "functions": ["SURVIVAL_ANALYSIS"],
  "message_id": "message-1",
  "requires_ack": true
}
```

Heartbeat messages are supported:

```json
{
  "type": "heartbeat"
}
```

Error messages are supported:

```json
{
  "type": "job_status_error",
  "status": "FAILURE",
  "message": "error text"
}
```

### Acknowledgement behavior

If a websocket message includes both `requires_ack` and `message_id`, and the socket is open, the frontend sends:

```json
{
  "type": "ack",
  "message_id": "message-1"
}
```

### Fallback behavior

Both websocket callers start polling first and then open the websocket. If websocket messages begin streaming, polling is stopped. If the websocket closes unexpectedly while tracking is still active and the current status is not terminal, `JobHistoryTable.tsx` restarts polling. `JobSubmissionPage.tsx` can display `Job status stream closed unexpectedly.` depending on close state.

## Job History Contract

### Caller

`src/features/job_history/components/JobHistoryTable.tsx`

### Endpoint

`POST ${API_BASE}${API_JOB_HISTORY}`

Constant value: `/nvflare/jobs/history`

### Request

```json
{
  "project_id": 1,
  "function_names": ["SURVIVAL_ANALYSIS"],
  "filter_mode": "ALL",
  "date_filter": {
    "mode": "last_30_days",
    "create_date": ""
  }
}
```

The actual `filter_mode`, date mode, and create date values come from local table state.

### Expected response

```json
{
  "nvflare_jobs": [
    {
      "id": 1,
      "job_runner_id": "job-runner-id",
      "nvflare_assigned_id": "nvflare-assigned-id",
      "status": "DONE",
      "filter_id": 10,
      "functions": ["SURVIVAL_ANALYSIS"],
      "functions_map": {},
      "datasource_group_id": 2,
      "datasource_group_name": "Example Group",
      "datasource_log": {
        "project_id": 1,
        "datasource_group_id": 2,
        "datasource_group_name": "Example Group"
      },
      "workflow_groups": [],
      "crypto_audit_record": null,
      "create_date": "2026-01-01T00:00:00",
      "update_date": "2026-01-01T00:00:00"
    }
  ]
}
```

### Frontend handling

The table stores `data.nvflare_jobs || []` in local state. It refreshes the job list after terminal live status updates and can refresh a single job row by re-fetching history and matching by `id`.

### Error/loading behavior

- `fetchJobs` sets `loading` to `true` before the request and `false` in `finally`.
- On error, it logs `Failed to fetch NVFlare jobs:` and clears jobs.
- `refreshJob` sets `refreshingJobId`, re-fetches history, updates the matching row, refreshes logs when the row is expanded, and clears `refreshingJobId` in `finally`.

## Job Results Contracts

All result helpers are in `src/features/job_history/utils/JobsDataUtils.tsx`.

### API base selection

```ts
function resolveResultsApiBase(userSession: JobApiSession): string {
  const role = typeof userSession === "string" ? userSession : userSession?.role;

  if (role !== UserRole.CLIENT) {
    return API_BASE;
  }

  const clientName =
    typeof userSession === "string" ? null : userSession?.client_name;

  return getClientApiBase(clientName);
}
```

`JobApiSession` accepts a bare `UserRole`, a `Pick<UserSession, "role" | "client_name">`, or a nullish value. A bare role string carries no client name, so a `CLIENT` session passed that way makes `getClientApiBase` throw in local development and standalone builds. `ResultsPage.tsx` passes the object form.

Only the two per-workflow helpers select their base this way. The remaining helpers always use `API_BASE`:

| Helper | Base used |
| --- | --- |
| `fetchWorkflowMapping` | `resolveResultsApiBase(userSession)` |
| `fetchJobResultsForWorkflow` | `resolveResultsApiBase(userSession)` |
| `fetchResultsContext` | `API_BASE` |
| `fetchNVFlareJobInfo` | `API_BASE` |
| `fetchFunctionConfigForWorkflow` | `API_BASE` |

See [Client Results Base Selection](#client-results-base-selection) for how `getClientApiBase` maps a site name to a port.

### Shared request helper

All result helpers use `postJson`, which sends POST JSON and throws:

```text
Request failed {status}: {responseText || url}
```

when `!res.ok`.

### Fetch job info

Endpoint:

`POST ${API_BASE}/jobs/info`

The path is hardcoded as `const API_JOB_INFO = "/jobs/info"` inside `JobsDataUtils.tsx`. This helper always uses `API_BASE`, including for `CLIENT` sessions.

Request:

```json
{
  "nvflare_job_id": "nvflare-assigned-id"
}
```

Expected response:

```json
{
  "job": {
    "id": 1,
    "nvflare_assigned_id": "nvflare-assigned-id",
    "job_runner_id": "job-runner-id",
    "status": "DONE"
  }
}
```

If `data.error` exists, the helper throws it. Otherwise it returns `data.job ?? null`.

### Fetch workflow mapping

Endpoint:

`POST ${base}${API_JOB_RESULTS_MAPPING}`

Constant value: `/jobs/results/mapping`

Request:

```json
{
  "nvflare_job_id": "nvflare-assigned-id",
  "function": "SURVIVAL_ANALYSIS"
}
```

Expected response:

```json
{
  "workflow_dirs": ["workflow_stat_analytics__cox_lasso"],
  "profile_summary": {
    "job_id": "nvflare-assigned-id",
    "site": "server",
    "role": "server",
    "extra": {},
    "workflows": {},
    "system_metrics": {
      "wall_time_sec": 0,
      "cpu_util_pct": 0,
      "cpu_user_pct": 0,
      "cpu_system_pct": 0,
      "cpu_iowait_pct": 0,
      "cpu_steal_pct": 0,
      "net_tx_bytes_total": 0,
      "net_rx_bytes_total": 0,
      "net_tx_mb_s": 0,
      "net_rx_mb_s": 0,
      "rss_max_kb": 0
    }
  }
}
```

The helper sorts workflow IDs and derives `combined_workflow_metrics` from `profile_summary.workflows`.

### Fetch workflow result payload

Endpoint:

`POST ${base}${API_JOB_RESULTS}`

Constant value: `/jobs/results`

Request:

```json
{
  "nvflare_job_id": "nvflare-assigned-id",
  "function": "SURVIVAL_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Expected response:

```json
{
  "job_data": {},
  "function_config": {}
}
```

The helper returns:

```ts
{
  jobData: JobsDataShape;
  functionConfig: FunctionConfig | null;
  workflowError: WorkflowErrorJson | null;
}
```

If `function_config` is missing or empty, it attempts to fetch function config separately.

### Fetch workflow function config

Endpoint:

`POST ${API_BASE}${API_JOB_RESULTS_FUNCTION_CONFIG}`

Constant value: `/jobs/function/config`

`API_JOB_RESULTS_FUNCTION_CONFIG` is a bare path like the other endpoint constants, and `fetchFunctionConfigForWorkflow` prepends `API_BASE` itself:

```ts
postJson<FunctionConfigResponse>(`${API_BASE}${API_JOB_RESULTS_FUNCTION_CONFIG}`, ...)
```

Request body:

```json
{
  "nvflare_job_id": "nvflare-assigned-id",
  "function": "SURVIVAL_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Expected response:

```json
{
  "function_config": {}
}
```

### Job ID usage

| ID | Frontend usage |
| --- | --- |
| `job_runner_id` / submit response `job_id` | Used for live status polling/websocket tracking through `/jobs/status`. |
| `nvflare_assigned_id` / `nvflare_job_id` | Used for results APIs: `/jobs/info`, `/jobs/results/mapping`, `/jobs/results`, `/jobs/function/config`. |
| Numeric `id` | Used by job history table to match and refresh rows. |

## Result Viewer Data Dependencies

The results viewer depends on a combination of job history metadata, saved filter metadata, result payloads, workflow mapping, and function config.

| Data | Source |
| --- | --- |
| Job status, function names, datasource group, workflow groups, participation exclusions, crypto audit record | `/nvflare/jobs/history` response as `NVFlareJob` fields |
| Live log output and live run duration | `/jobs/status` polling/websocket response |
| Saved filter summary | `/filters/fetch_single_filter` |
| Workflow IDs per function | `/jobs/results/mapping` |
| Profile/system metrics | `/jobs/results/mapping` `profile_summary` |
| Function-level result payload | `/jobs/results` |
| Function config | `/jobs/results` inline `function_config` or `/jobs/function/config` fallback |
| Exportable report sections | Derived from the same result viewer state used by PDF, DOCX, HTML, and PNG export utilities |

## Function Contracts

`API_FUNCTIONS_SUPPORTED` exists with value `/functions/supported_functions`, but no caller was found in the uploaded source. Current function availability is taken from the selected `Project` object returned by `/projects/list` and stored in `project.functions`.

## Public Config and API Interaction

The frontend uses four kinds of data sources:

| Source type | Examples | Notes |
| --- | --- | --- |
| Backend-provided configuration | `/user/role`, `/projects/list`, `/clients/*`, `/nvflare/jobs/*`, `/jobs/*`, `/filters/*` saved filters | Returned by the FastAPI/backend service selected by `API_BASE` or `CLIENT_API_BASE`. |
| Frontend public JSON configuration | `/filters/{system}/...`, `/analysis_config/...`, public test data files | Served from the React public folder. These are not backend API calls. |
| Hardcoded constants | Endpoint constants, supported function enum, cytoband arrays, feature descriptions | Defined in `Constants.tsx` unless listed as hardcoded elsewhere. |
| Derived payload values | `datasource_group`, `workflow_group_data`, `threshold_config`, `non_contributing_clients`, `exclude_analyzing_clients` | Built from selected project/session/UI state before submission or participation checks. |

## Known Hardcoded Endpoint Strings

| String/path | File | Notes |
| --- | --- | --- |
| `/user/role` | `src/pages/LoginPage.tsx` | Backend login/session endpoint. No constant currently exists. |
| `/jobs/info` | `src/features/job_history/utils/JobsDataUtils.tsx` | Result helper endpoint. No exported constant currently exists. |
| `/jobs/status/ws` | `src/features/job_runner/pages/JobSubmissionPage.tsx`, `src/features/job_history/components/JobHistoryTable.tsx` | Duplicates exported `API_JOB_STATUS_WEBSOCKET`. |
| `/filters/{filter_system}/patient/patient_query.json` | `src/components/ProjectListComponent.tsx`, `src/features/job_runner/pages/filters/cancer_type/FilterScreenPatients_CancerType.tsx`, `src/features/job_runner/components/FilterControlsSection.tsx` through `schemaUrl` | Public JSON config, not backend API. |
| `/filters/{filter_system}/patient/patient_data.json` | `src/components/ProjectListComponent.tsx` | Public JSON config, not backend API. |
| `/filters/{filter_system}/observation/observation_filters.json` | `src/components/ProjectListComponent.tsx` | Public JSON config, not backend API. |
| `/filters/{filter_system}/observation/observation_query.json` | `src/components/ProjectListComponent.tsx`, `src/features/job_runner/pages/filters/FilterScreenObservationsFHIR.tsx`, `FilterControlsSection.tsx` through `schemaUrl` | Public JSON config, not backend API. |
| `/filters/{filter_system}/observation/observation_data.json` | `src/components/ProjectListComponent.tsx`, `src/features/job_runner/pages/filters/FilterScreenObservationsFHIR.tsx`, `FilterControlsSection.tsx` through `schemaUrl` | Public JSON config, not backend API. |
| `/analysis_config/analysis_query.json` | `src/features/user_manager/pages/AnalysisManager.tsx` | Public JSON config. |
| `/analysis_config/analysis_data.json` | `src/features/user_manager/pages/AnalysisManager.tsx` | Public JSON config. |
| `/Patient` | `src/features/job_runner/pages/filters/default/FilterScreenPatients.tsx` | FHIR query path fragment, not a backend route. |

Image/icon/logo paths were also found throughout the UI, but they are static assets rather than API contracts.

## Known Implementation Notes

1. `getClientApiBase` throws instead of falling back when a `CLIENT` session has no `site<N>` client name in local development or standalone builds. Result screens for a client user therefore depend on `/user/role` returning `client_name`.
2. `API_JOB_STATUS_WEBSOCKET` is exported from `Constants.tsx`, but both websocket callers redeclare the same path locally.
3. `WS_API_BASE` uses `REACT_APP_API_BASE` in production builds. If `REACT_APP_API_BASE` is an HTTPS REST endpoint rather than a WSS endpoint, the non-local websocket URL builder will return that HTTPS URL with `?job_id=...` instead of a WSS URL.
4. Backend route implementation files cannot be identified from the uploaded frontend zip. This document avoids naming backend source files that were not provided.


## User Settings Datasource and Model File Endpoints

`UserSettingsPage` uses the same `API_BASE` convention as the rest of the frontend and connects to these backend contracts:

| Endpoint | Frontend use |
| --- | --- |
| `POST /projects/list` | Loads project metadata, datasource group definitions, model-file-settings flags, and function/workflow metadata used to render settings fields. |
| `POST /user/datasource/apply` | Saves changed datasource settings for the current user. |
| `POST /user/model-files/list` | Loads current model file source settings for the current user. |
| `POST /user/model-files/apply` | Saves changed model file source settings for the current user. |
| `POST /user/role` | Login/session setup returns `user_id`, `projects`, and project datasource assignments consumed through `UserRoleContext`. |

`POST /clients/datasource/source` is part of the runtime NVFlare server lookup path and is not called by frontend code. Model file source rows are also not opened by the browser or backend; they are saved as initiator-local paths and consumed by the runtime model-upload workflow.

`UserSettingsPage` submits only changed datasource and model file fields. JSON datasource values must end with `.json`; FHIR server values must normalize to a valid URL ending in `/fhir`. Model file source values must be non-empty strings when changed, but they are not browser file inputs and should not contain browser `fakepath` values.
