# Filter Screens and Payload Building

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_runner/pages/filters/` | Filter selection, creation, listing, and review screens used by the job runner flow. |
| `src/features/job_runner/utils/FilterPayloadConfigUtils.tsx` | Utilities for converting frontend filter state into backend/job payload format. |
| `src/components/FilterSummary.tsx` | Shared display component for selected filter values. |
| `public/filters/` | Public JSON filter configuration files used by frontend filter screens. |
| `src/constants/Constants.tsx` | Backend API constants for filter-related calls. |
| `src/api/routes/FilterRoutes.py` | Backend route reference for filter lookup behavior. |

## Filter Feature Role

The filter screens collect the patient and observation criteria used to define the cohort for a SHARE/NVFlare job.

The frontend stores filter selections as a `FilterCollection`, then converts that collection into a backend-ready condition list immediately before job submission. The filter flow supports both newly configured filters and previously saved filters loaded from the backend. When a previously saved filter is selected, the filter controls are treated as locked and the saved values are carried forward instead of being overwritten by edits.

Filter selections are part of the final `/nvflare/jobs/submit` payload under the `filters` field. The payload is built from the current project schema, the selected or newly created filter set, and the generated filter set name.

## Filter Screen Area

Filter-related job runner screens live under:

```text
src/features/job_runner/pages/filters/
```

Current files under this directory are:

| File | Role |
| --- | --- |
| `FilterHistoryTable.tsx` | Lists saved filter sets for the selected project, lets the user search/paginate rows, select an existing filter set, expand details, refresh the list, or start a new filter set. |
| `FilterScreenPatients.tsx` | Router component for patient filter screens. It chooses the cancer-type patient screen when `filterSystem` is `CANCER_TYPE`; otherwise it renders the default patient screen. |
| `default/FilterScreenPatients.tsx` | Default FHIR-server-backed patient query screen. Builds a Patient query preview, executes preview queries through the project FHIR source backend proxy, displays matched patients, and writes patient query/data filters into `FilterCollection`. |
| `default/FilterScreenPatientsJSON.tsx` | Local-bundle patient filter screen used for General Statistics when the user's datasource is a `.json` file. Receives patients and medications preloaded by `utils/LocalBundlePreview.ts`, filters them in the browser (gender, birth date range, medication tokens with comma-separated OR semantics) using the same `PATIENT_QUERY` schema controls, and writes the same filter payload as the default screen. |
| `cancer_type/FilterScreenPatients_CancerType.tsx` | Cancer-type patient filter screen. Loads cancer-type options, resolves local/test patient data, filters patients by selected cancer type, and writes the cancer-type filter into `patientDataFilters`. |
| `FilterScreenObservationsFHIR.tsx` | Observation/genetic variant filter screen. Loads observation query/data schemas, previews or loads Observation data, computes per-patient variant metrics, applies local observation filters, and writes observation query/data filters into `FilterCollection`. |

`JobRunnerMain.tsx` renders these screens as part of the internal job runner state machine:

| Job runner screen | Component |
| --- | --- |
| `filterHistory` | `FilterHistoryTable` |
| `patientFilters` | `FilterScreenPatients`, or `default/FilterScreenPatientsJSON` for a local General Statistics bundle |
| `variantTable` | `FilterScreenObservationsFHIR` |

The filter screens are not standalone application routes. They are internal branches inside `JobRunnerMain.tsx`, which controls progression from saved/new filter selection, to patient filtering, to observation filtering, then onward to workflow group selection or function selection.

## Filter State Owned by `JobRunnerMain.tsx`

`JobRunnerMain.tsx` owns the filter state passed between filter screens.

The blank filter shape is:

```ts
export const BLANK_FILTER_CONFIG: FilterCollection = {
  patientQueryFilters: "{}",
  patientDataFilters: "{}",
  observationQueryFilters: "{}",
  observationDataFilters: "{}"
};
```

The filter-related state includes:

| State | Type/shape | Purpose |
| --- | --- | --- |
| `newFilterSet` | `FilterCollection` | Mutable filter set being built by the current flow. |
| `selectedPreviouslySavedFilterSet` | `FilterCollection` | Filter set reconstructed from a saved backend filter row. |
| `submittedFilterSet` | `FilterCollection` | Effective filter set used at submission/review time. |
| `submittedFilterSetName` | `string` | Name sent with the backend filter payload. For new filters this is generated from selected values. |
| `selectedFilterName` | `string` | Non-empty when the user selected a saved filter set. Used to lock filter editing. |
| `patients` | `Patient[]` | Patient data available to the job runner flow. |
| `variantPatients` | `Patient[]` | Patients that passed the patient filter step. |
| `observations` | `Observation[]` | Observation data available to the job runner flow. |
| `geneticObsForVariantPage` | `Observation[]` | Observations whose subject references match selected patient records. |
| `selectedFinalPatients` | `Patient[]` | Final cohort passed into the job submission screen. |
| `selectedDatasourceGroupId` | `number \| null` | Datasource group chosen for grouped datasource projects. |

`updateNewFilterCollection` updates one bucket in `newFilterSet`:

```ts
const updateNewFilterCollection = <K extends keyof FilterCollection>(key: K, jsonString: string): void => {
  setNewFilterSet((prev) => ({ ...prev, [key]: jsonString }));
};
```

The active filter set is selected as follows:

- If `selectedFilterName` is non-empty, the selected saved filter set is used.
- Otherwise, the newly configured filter set is used.
- Missing buckets are normalized back to `{}` strings.

`submittedFilterSetName` is the selected saved filter name when a saved filter is used. For new filters, `JobRunnerMain.tsx` generates a compact name from meaningful patient and observation values, such as gender, age range, medication, cancer type, deletion/amplification counts, total count, and region count.

## Selected Filter State Type

The selected filter state uses `FilterCollection` from `src/types/FilterSchema.tsx` and re-exported by `FilterPayloadConfigUtils.tsx`:

```ts
export interface FilterCollection {
  patientQueryFilters: string;
  patientDataFilters: string;
  observationQueryFilters: string;
  observationDataFilters: string;
}
```

Each field is a JSON string, not an object. Empty buckets are represented as the string:

```json
{}
```

Typical populated bucket examples:

```json
{
  "gender": "female",
  "medication": "J7527,J9299",
  "birthDate": ["1926-05-08", "2026-05-08"]
}
```

```json
{
  "cancer_type": "Non-Small Cell Lung Cancer"
}
```

```json
{
  "deletionRegions": ["10q23.31", "9p21.3"],
  "amplificationRegions": ["8q24.3"]
}
```

```json
{
  "variantAssessmentCode": "69548-6",
  "minDeletions": 1,
  "minAmplifications": 0,
  "minTotal": 2
}
```

## Public Filter Configuration

Static filter configuration lives under:

```text
public/filters/
```

Current public filter JSON files are:

| File | Role |
| --- | --- |
| `public/filters/default/patient/patient_query.json` | Default Patient filter schema. Defines gender, medication, birth date, and deceased date controls. |
| `public/filters/default/observation/observation_data.json` | Default Observation local filtering schema. Defines variant assessment code, deletion regions, amplification regions, minimum deletions, minimum amplifications, and minimum total variant filters. Also includes local observation model and patient metric rules. |
| `public/filters/cancer_type/patient/patient_query.json` | Cancer-type filter schema. Defines the cancer type select list and stores the selected cancer type as patient data. |
| `public/filters/cancer_type/backup/patient_query.json` | Backup copy of the cancer-type patient query schema. It is not directly referenced by the current filter screen routing. |
| `public/filters/cancer_type/observation/observation_filters.json` | Cancer-type observation placeholder schema. It currently contains a label stating that no observation filters are required for that pipeline. |

`FilterControlsSection.tsx` can load schemas in two ways:

1. Prefer `project.filter_schemas[filterType]` when the selected project provides a schema through backend project metadata.
2. Fall back to `schemaUrl` and fetch a public JSON file with `cache: "no-store"`.

`default/FilterScreenPatients.tsx` primarily uses the project `PATIENT_QUERY` schema for Patient query preview and `FilterControlsSection` rendering.

`FilterScreenObservationsFHIR.tsx` builds schema URLs from the project filter system:

```ts
const fs = (filterSystem || "default").toLowerCase();
const querySchemaUrl = `/filters/${fs}/observation/observation_query.json`;
const dataSchemaUrl = `/filters/${fs}/observation/observation_data.json`;
```

In the uploaded frontend package, `default/observation/observation_data.json` exists, but `default/observation/observation_query.json` does not. The component catches failed schema loads and sets that schema to `null`. The data schema is still used for local observation filtering when available.

## Filter JSON Schema Shape

Filter JSON files use the TypeScript interfaces in `src/types/FilterSchema.tsx`.

Top-level schema shape:

```ts
export interface FilterSchema {
  version?: string;
  resource?: { type?: string } | string;
  controls?: ControlSchema[];
  defaultsResolver?: Record<string, any>;
}
```

Control shape:

```ts
export interface ControlSchema {
  id: string;
  field?: string;
  label?: string;
  type:
    | "select"
    | "multi-select"
    | "multi-select-grid"
    | "number"
    | "checkbox"
    | "date-range"
    | "hidden"
    | "token-select"
    | "label"
    | string;
  default?: any;
  disabled?: boolean;
  options?: ControlOption[];
  fhir?: ControlFHIR;
  query?: QuerySchema;
  save?: SaveSchema;
  ui?: {
    span?: "full" | "half" | "third";
    editable?: boolean;
  };
}
```

Option shape:

```ts
export interface ControlOption {
  label: string;
  value?: string;
  token?: string;
}
```

Some cancer-type options also include a `code` field in the JSON. The shared `ControlOption` type does not currently declare `code`, but the uploaded cancer-type schema includes it alongside `label` and `value`. The cancer-type screen uses the selected value for storage and local filtering.

Save target shape:

```ts
export interface SaveTargetSchema {
  filter_type?: FilterType;
  column_name?: string;
  filter_group?: FilterType;
  field?: string;
  operator: string;
  valueFrom?: "value";
  transform?: "int" | "float" | "string";
}
```

Supported filter types:

```ts
export type FilterType =
  | "PATIENT_QUERY"
  | "PATIENT_DATA"
  | "OBSERVATION"
  | "OBSERVATION_QUERY"
  | "OBSERVATION_DATA";
```

Condition shape:

```ts
export interface Condition {
  filter_type: FilterType;
  column_name: string;
  operator: string;
  value?: string;
  values?: string[];
}
```

## Current Public Control Inventory

| File | Control ID | Type | Stored filter target |
| --- | --- | --- | --- |
| `default/patient/patient_query.json` | `gender` | `select` | `PATIENT_QUERY.gender = value` |
| `default/patient/patient_query.json` | `medication` | `select` | `PATIENT_QUERY.medication = value` |
| `default/patient/patient_query.json` | `birthDate` | `date-range` | `PATIENT_QUERY.birthDate BETWEEN values` |
| `default/patient/patient_query.json` | `death-date` | `date-range` | `PATIENT_QUERY.deceased_date BETWEEN values` |
| `default/observation/observation_data.json` | `variantAssessmentCode` | `select` | `OBSERVATION_DATA.variantAssessmentCode IN value` |
| `default/observation/observation_data.json` | `deletionRegions` | `multi-select-grid` | `OBSERVATION_DATA.deletionRegions IN values` |
| `default/observation/observation_data.json` | `amplificationRegions` | `multi-select-grid` | `OBSERVATION_DATA.amplificationRegions IN values` |
| `default/observation/observation_data.json` | `minDeletions` | `number` | `OBSERVATION_DATA.minDeletions >= value`, transformed as int |
| `default/observation/observation_data.json` | `minAmplifications` | `number` | `OBSERVATION_DATA.minAmplifications >= value`, transformed as int |
| `default/observation/observation_data.json` | `minTotal` | `number` | `OBSERVATION_DATA.minTotal >= value`, transformed as int |
| `cancer_type/patient/patient_query.json` | `cancer_type` | `select` | `PATIENT_DATA.cancer_type = value` |
| `cancer_type/observation/observation_filters.json` | `observation_filters_info` | `label` | No saved filter target. Display-only label. |

## Shared Filter Controls Rendering

`FilterControlsSection.tsx` is the shared schema-driven filter control renderer.

Important props include:

| Prop | Purpose |
| --- | --- |
| `project` | Selected project. Used to prefer project-level filter schemas before public JSON fallback. |
| `filterType` | Filter schema key such as `PATIENT_QUERY` or `OBSERVATION_DATA`. |
| `schemaUrl` | Public JSON URL used when the project does not provide the schema. |
| `initialConditions` | Existing condition list used to repopulate controls. |
| `initialValues` | Existing bucket values used to repopulate controls. |
| `lock` | Prevents user edits when a saved filter is selected. |
| `onCompiledChange` | Receives `{ conditions, fhirParams }` whenever compiled values change. |

The component renders:

| Control type | UI behavior |
| --- | --- |
| `select` | Renders a `<select>` using `options[].label` and `options[].value`. |
| `token-select` | Renders a `<select>` using `options[].value` or `options[].token`. |
| `multi-select` | Renders a scrollable checkbox list. |
| `multi-select-grid` | Renders a grid of checkbox options. |
| `number` | Renders an `<input type="number">`. |
| `checkbox` | Renders an `<input type="checkbox">`. |
| `date-range` | Renders two date inputs for start and end. |
| `label` | Renders display text only. |
| `hidden` | Does not render. |
| other string | Renders a plain text input fallback. |

Controls are disabled when:

- `lock` is true,
- `control.ui.editable === false`, or
- `control.disabled === true`.

When no schema is available yet, the component displays:

```text
Loading controls…
```

If a public schema fetch fails inside `FilterControlsSection.tsx`, there is no local `catch` in that component. The failed fetch will reject the async effect. In contrast, `FilterScreenObservationsFHIR.tsx` catches schema fetch failures for observation schemas and sets the failed schema to `null`.

## Backend Filter Lookup

The saved-filter table calls the backend filter list endpoint.

Constants:

```ts
export const API_FILTERS_FETCH_SINGLE = "/filters/fetch_single_filter";
export const API_FILTERS_FETCH = "/filters/fetch_filters";
```

`FilterHistoryTable.tsx` imports `API_BASE` and `API_FILTERS_FETCH` and calls:

```http
POST /filters/fetch_filters
Content-Type: application/json
```

Request body:

```json
{
  "project_id": 1
}
```

Expected response shape used by the frontend:

```json
{
  "filters": [
    {
      "id": 123,
      "name": "Example Filter",
      "create_date": "2026-04-01T12:00:00",
      "update_date": "2026-04-01T12:00:00",
      "conditions": [
        {
          "filter_type": "PATIENT_QUERY",
          "column_name": "gender",
          "operator": "=",
          "value": "female"
        }
      ]
    }
  ]
}
```

The frontend maps each row into:

```ts
interface FilterHistoryRow {
  id: number;
  name: string;
  create_date: string;
  update_date: string;
  filter_collection: FilterCollection;
}
```

`conditions` are converted back into a `FilterCollection` through:

```ts
buildDefaultFilterCollectionFromConditions(r.conditions || [], project)
```

If the request fails, `FilterHistoryTable.tsx` logs `Failed to fetch filters`, clears the row list, clears the selected/expanded row, and stops loading.

`API_FILTERS_FETCH_SINGLE` is declared in constants but is not used by the current filter screens in the uploaded frontend package.

## Patient Filter Flow

Before any dispatch, `JobRunnerMain.tsx` checks whether the project is `General Statistics` and the session `fhir_source` ends with `.json`. If so it renders `default/FilterScreenPatientsJSON.tsx` with patients and medications already loaded from the local bundle, and `FilterScreenPatients.tsx` is not used.

`FilterScreenPatients.tsx` dispatches between two patient filter implementations based on `filterSystem`:

```ts
const fs = String(filterSystem || "DEFAULT").trim().toUpperCase();

if (fs === "CANCER_TYPE") {
  return <FilterScreenPatients_CancerType {...rest} />;
}

return <DefaultFilterScreenPatients {...rest} />;
```

### Default Patient Filter Screen

`default/FilterScreenPatients.tsx` handles FHIR Patient query filters.

It receives from `JobRunnerMain.tsx`:

| Prop | Purpose |
| --- | --- |
| `project` | Selected project and schema metadata. |
| `patients` | Current patient array. |
| `medications` | Medication array. Present in props but not central to the current FHIR preview path. |
| `onBack` | Returns to filter history. |
| `onProceedToVariants` | Continues with all matched patients after preview. |
| `setFilterCollection` | Writes JSON buckets into `newFilterSet`. |
| `existingQueryFilter` | Existing `patientQueryFilters` JSON string. |
| `existingPatientFilter` | Existing `patientDataFilters` JSON string. |
| `lockFilterConfig` | Locks edits when using a saved filter. |
| `selectedDatasourceGroupId` | Datasource group sent to FHIR source lookup. |
| `onSelectedDatasourceGroupIdChange` | Updates selected datasource group. |

The screen:

1. Builds initial control values from `existingQueryFilter` and `existingPatientFilter`.
2. Compiles `PATIENT_QUERY` conditions from `FilterControlsSection`.
3. Builds a FHIR query preview such as `/Patient?gender=female&birthdate=ge1926-05-08&birthdate=le2026-05-08`.
4. Calls `POST /projects/fhir/source` through `API_PROJECTS_FHIR_SOURCE` to execute preview/count queries against the selected project datasource.
5. Displays preview rows in a TanStack table.
6. On continue, writes the compiled patient conditions into `patientQueryFilters` and `patientDataFilters`, unless `lockFilterConfig` is true.
7. Passes matched patients to the observation step.

FHIR source request body used by the default patient screen:

```json
{
  "username": "user@example.com",
  "project_id": 1,
  "datasource_group": 2,
  "execute_query": "/Patient?_count=200&_total=accurate"
}
```

Response fields used by the screen include:

```ts
interface ProjectFHIRSourceQueryResponse {
  username?: string;
  user_id?: number;
  project_id?: number;
  source?: string;
  source_type?: "json" | "fhir_server";
  datasource_group?: number | null;
  datasource_group_name?: string | null;
  is_default_group?: boolean;
  query_executed?: boolean;
  query_execution_message?: string;
  executed_url?: string;
  query_status_code?: number;
  query_results?: FhirBundle<FhirPatientResource>;
}
```

The default patient preview requires a FHIR server source. If the current FHIR source is missing, it displays an error. If the current FHIR source ends with `.json`, preview query execution is blocked with the message that preview query is only supported for FHIR server sources.

### Cancer-Type Patient Filter Screen

`cancer_type/FilterScreenPatients_CancerType.tsx` handles cancer-type filtering.

It loads:

```text
/filters/cancer_type/patient/patient_query.json
```

The schema defines a `cancer_type` select control with cancer labels, user-facing values, and SNOMED-style codes. The save target stores the selected value in:

```json
{
  "cancer_type": "Non-Small Cell Lung Cancer"
}
```

under `patientDataFilters`.

When continuing, this screen clears `patientQueryFilters` and writes the resolved patient data filter:

```ts
setFilterCollection("patientQueryFilters", JSON.stringify({}));
setFilterCollection("patientDataFilters", resolvedPatientDataFilters);
```

The cancer-type path is local/test-data oriented rather than a general FHIR query preview path.

## Observation Filter Flow

`FilterScreenObservationsFHIR.tsx` handles Observation/genetic variant filtering.

It receives from `JobRunnerMain.tsx`:

| Prop | Purpose |
| --- | --- |
| `filterSystem` | Used to resolve `/filters/{filterSystem}/observation/...` schema URLs. |
| `patients` | Patient list from the previous filter step. |
| `project` | Selected project and schema metadata. |
| `rawObservations` | Observations already available from previous local/test-data flow. |
| `reviewSubmission` | Continues to workflow group selection or function selection with final patients. |
| `onBack` | Returns to patient filters or filter history depending on the active flow. |
| `setFilterCollection` | Writes observation query/data buckets into `newFilterSet`. |
| `existingQueryFilter` | Existing `observationQueryFilters` JSON string. |
| `existingDataFilter` | Existing `observationDataFilters` JSON string. |
| `lockFilterConfig` | Locks edits when using a saved filter. |
| `selectedDatasourceGroupId` | Datasource group used when executing FHIR source queries. |

The screen loads:

```text
/filters/{filterSystem}/observation/observation_query.json
/filters/{filterSystem}/observation/observation_data.json
```

Missing schema files are caught and set to `null`.

The default observation data schema includes a `localPass` section. The screen uses `localPass.observationModel` to normalize Observations and `localPass.patientMetrics` to compute patient-level metrics such as deletion count, amplification count, duplication count, total count, deletion region set, amplification region set, and variant assessment codes.

When submitting observation filters, the screen writes:

```json
{
  "deletionRegions": ["10q23.31"],
  "amplificationRegions": ["8q24.3"]
}
```

into `observationQueryFilters`, and writes numeric/data thresholds into `observationDataFilters`:

```json
{
  "variantAssessmentCode": "69548-6",
  "minDeletions": 1,
  "minAmplifications": 0,
  "minTotal": 2
}
```

Then it calls `reviewSubmission(filteredData.map((row) => row.patient))`.

The continue/submit button is effectively gated by:

```ts
const canSubmit = hasPreviewed && filteredData.length > 0;
```

## Payload Building

`FilterPayloadConfigUtils.tsx` turns the stored `FilterCollection` into the shape sent in `JobSubmissionPage.tsx`.

Important exported types and functions:

| Export | Purpose |
| --- | --- |
| `Condition` | Backend condition shape. |
| `FilterCollection` | Four-bucket selected filter state. |
| `FilterSchema`, `ControlSchema`, `QuerySchema`, `SaveSchema`, `SaveTargetSchema` | Schema-driven filter control and save target types. |
| `createEmptyFilterCollection()` | Returns a four-bucket collection initialized to `{}` strings. |
| `getInitialValuesFromCollection(collection, project)` | Rehydrates control values from stored JSON buckets and project schemas. |
| `buildFiltersPayload(name, collection, project)` | Builds `{ name, conditions }` for job submission. |
| `buildDefaultFilterCollectionFromConditions(conditions, project)` | Reconstructs a `FilterCollection` from saved backend conditions. |

The output shape from `buildFiltersPayload` is:

```ts
{
  name: string;
  conditions: Condition[];
}
```

Example output:

```json
{
  "name": "G:female,A:1926-2026,D:1,A:0,T:2,R:1",
  "conditions": [
    {
      "filter_type": "PATIENT_QUERY",
      "column_name": "gender",
      "operator": "=",
      "value": "female"
    },
    {
      "filter_type": "PATIENT_QUERY",
      "column_name": "birthDate",
      "operator": "BETWEEN",
      "values": ["1926-05-08", "2026-05-08"]
    },
    {
      "filter_type": "OBSERVATION_DATA",
      "column_name": "minTotal",
      "operator": ">=",
      "value": "2"
    }
  ]
}
```

### Collection Bucket Mapping

`FilterPayloadConfigUtils.tsx` maps filter types to collection buckets as follows:

| Filter type | Collection bucket |
| --- | --- |
| `PATIENT_QUERY` | `patientQueryFilters` |
| `PATIENT_DATA` | `patientDataFilters` |
| `OBSERVATION` | `observationQueryFilters` |
| `OBSERVATION_QUERY` | `observationQueryFilters` |
| `OBSERVATION_DATA` | `observationDataFilters` |

### Empty Value Handling

Values are skipped when they are:

- `undefined`,
- `null`,
- an empty or whitespace-only string,
- an empty array, or
- an array where every item is blank.

Empty objects are serialized back as:

```json
{}
```

### Control Value Handling

| Control type | Stored/output behavior |
| --- | --- |
| `date-range` | Stored as up to two values. Output uses `values` and normally a `BETWEEN` operator. |
| `multi-select` | Stored as a string array. Output uses `values`. |
| `multi-select-grid` | Stored as a string array. Output uses `values`. |
| `number` | Rehydrated as a number where possible. `buildFiltersPayload` emits string `value`; direct observation submit logic may store numeric values in the JSON bucket. |
| `checkbox` | Rehydrated as boolean. Output emits string `"true"` or `"false"`. |
| `select` / `token-select` / text fallback | Stored as a scalar string. Output uses `value`. |

`buildFiltersPayload` uses the project’s `filter_schemas` as the source of truth. A control only becomes a backend condition if its schema includes `save.targets` with a valid `filter_group`/`filter_type`, field/column name, and operator.

Conditions are deduplicated by JSON string equality before being returned.

## Job Submission Integration

`JobSubmissionPage.tsx` builds the filters payload with:

```ts
const filtersPayload = useMemo(
  () =>
    buildFiltersPayload(
      submittedFilterName || "Filter Set",
      submittedFilter,
      project,
    ),
  [submittedFilterName, submittedFilter, project],
);
```

The final job submission payload includes this value under the `filters` field:

```json
{
  "project_id": 1,
  "filters": {
    "name": "Example Filter",
    "conditions": []
  },
  "functions_map": {},
  "submitter": "user@example.com",
  "non_contributing_clients": [],
  "exclude_analyzing_clients": [],
  "datasource_group": 2,
  "workflow_group_data": {},
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 10
  }
}
```

`datasource_group`, `workflow_group_data`, and `threshold_config` are conditional fields:

- `datasource_group` is included only when `selectedDatasourceGroupId !== null`.
- `workflow_group_data` is included only when the object exists and has keys.
- `threshold_config` is included only when threshold config is enabled and has a method and value.

The submit call is:

```http
POST /nvflare/jobs/submit
Content-Type: application/json
```

The backend receives the filter condition list through `payload.filters.conditions`.

## Filter Summary

`src/components/FilterSummary.tsx` displays the selected filter set in later screens.

It accepts filter JSON strings for patient query, patient data, observation query, and observation data buckets, parses them defensively, and renders meaningful values grouped by filter category. It is used by job runner review/submission screens and job history/results display areas to show what cohort criteria were applied.

The component handles empty or invalid JSON defensively by falling back to an empty object. Empty categories are not emphasized as populated filter sections.

## Error and Loading Behavior

| Area | Loading behavior | Error/failure behavior |
| --- | --- | --- |
| `FilterHistoryTable.tsx` | Sets `loading` while `POST /filters/fetch_filters` is in progress. Uses `RefreshablePanel` for manual refresh. | On failure, logs `Failed to fetch filters`, clears rows and selected/expanded row state, and stops loading. |
| `FilterControlsSection.tsx` | Displays `Loading controls…` while no schema is available. | Does not catch failed public schema fetches locally. Project-provided schemas avoid public fetch. |
| `default/FilterScreenPatients.tsx` | Uses `isPreviewLoading` during FHIR preview/count/full-fetch. Clears previous preview state before executing. | Shows errors when no FHIR source exists, when the source is JSON instead of FHIR server, when the proxy request fails, or when backend query status is >= 400. |
| `cancer_type/FilterScreenPatients_CancerType.tsx` | Loads public schema and local/test patient data before previewing/filtering. | Throws and displays schema/data fetch errors such as failed cancer type schema fetches or failed test-data fetches. |
| `FilterScreenObservationsFHIR.tsx` | Tracks preview loading, progress percent, progress labels, completion text, query result count, and queried observations. | Catches missing observation schema fetches by setting schema to `null`; preview/runtime errors are stored in `previewError`. |
| `JobSubmissionPage.tsx` | Sets `submitting` while posting `/nvflare/jobs/submit`; starts polling/websocket tracking when a `job_id` is returned. | On non-OK submit response or thrown exception, sets `error` and clears submitting state. |

## Important Implementation Notes

The filter documentation should treat the project schema as authoritative at runtime. The public JSON files are still important because they are used as fallbacks and because the uploaded frontend package includes public filter schemas for default and cancer-type behavior.

The current frontend stores selected filter buckets as JSON strings, then converts them to condition arrays at submission time. Saved backend filters are returned as condition arrays, then converted back into JSON-string buckets for display/reuse.

The frontend distinguishes between:

- query filters that can become FHIR search parameters,
- data filters that are applied locally to already-loaded patient/observation data,
- saved filter rows from MySQL/backend, and
- the final backend submission payload under `filters`.
