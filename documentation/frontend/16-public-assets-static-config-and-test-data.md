# Public Assets, Static Config, and Test Data

## Files Covered

| File/Directory | Role |
| --- | --- |
| `public/index.html` | HTML entrypoint for the React bundle. |
| `public/favicon.ico` | Browser favicon. |
| `public/manifest.json` | Web app manifest. |
| `public/robots.txt` | Robots metadata. |
| `public/icons/` | UI icon assets used across navigation, job runner, results, roles, and workflow screens. |
| `public/logos/` | Application logo assets. |
| `public/status-images/` | Status and illustration images used by the UI. |
| `public/filters/` | Static filter configuration JSON files. |
| `public/analysis_config/` | Static analysis configuration JSON files. |
| `public/SO/` | Static Sequence Ontology JSON data. |
| `public/test-data/` | Runtime location expected by local/test datasource loading logic. Ships the browser-preview zips for the initiating site's datasources: `Biomarker_MSKChord_FHIR_Data_training_bundle_v4.zip` and `Survivability_FHIR_Data_part1_v1.zip`. |
| `src/constants/Constants.tsx` | Constants that may reference public/static paths. |

## Public Directory Role

The `public/` directory contains files served directly by the React application. Files in this directory are not imported through the TypeScript module system. They are loaded by browser URL path at runtime.

The current frontend uses public assets for:

- browser metadata and PWA metadata
- top-level logos and footer logos
- navigation icons
- function-selection icons
- project icons
- status/progress illustrations
- static filter schemas
- static analysis configuration schemas
- Sequence Ontology data
- local/test datasource zip files expected under `/test-data/`

Runtime paths in the source are root-relative paths such as `/icons/...`, `/logos/...`, `/filters/...`, `/analysis_config/...`, `/status-images/...`, and `/test-data/...`.

## Public Directory Tree

The uploaded frontend package contains this public tree:

```text
public/
  SO/
    so-codes.json
  analysis_config/
    analysis_data.json
    analysis_query.json
  apple-touch-icon.png
  favicon.ico
  fhir_server.png
  filters/
    cancer_type/
      backup/
        patient_query.json
      observation/
        observation_filters.json
      patient/
        patient_query.json
    default/
      observation/
        observation_data.json
      patient/
        patient_query.json
  icons/
    function_icon_Chi.png
    function_icon_Count.png
    function_icon_EncFil.png
    function_icon_LogCal.png
    function_icon_Mean.png
    function_icon_SA.png
    function_icon_Std.png
    function_icon_TTest.png
    function_icon_feedback.png
    nav_icon_filters_manager.png
    nav_icon_job_history.png
    nav_icon_job_runner.png
    nav_icon_nvflare_manager.png
    nav_icon_participation_manager.png
    nav_icon_projects_list.png
    nav_icon_home.png
    nav_icon_users_login.png
    nav_icon_users_manager.png
    projects/
      1/
        icon.png
      2/
        icon.png
  index.html
  logo192.png
  logo512.png
  logos/
    dfci_logo.png
    duality.ico
    duality_logo.png
    icf_logo.png
    icf_logo2.png
    nvflare.png
    nvflare_logo.png
    openfhe_logo.png
    share.png
  manifest.json
  metadata.json
  robots.txt
  status-images/
    icons/
      analysis-failure.png
      broadcasting-participation-job.png
      checking-client-participation.png
      client-analysis.png
      client-compute.png
      client-encryption.png
      client-participation-established.png
      client-preparing.png
      client-results.png
      collaborative-decryption.png
      done.png
      error.png
      failure.png
      filters-processing.png
      interactive-key-generation.png
      job-analysis.png
      job-broadcast.png
      job-defining.png
      job-received.png
      job-results.png
      participation-empty.png
      participation-failed.png
      processing.png
      queued.png
      server-analysis.png
      server-compute.png
      server-encryption.png
      server-preparing.png
      server-results.png
      ssh-connected.png
      ssh-connecting.png
      threshold-failure.png
      warning.png
    new/
      86f3566d-8b55-4fca-bd5c-28247ad458a8.png
      ae7b0cfe-7bf2-4c7e-ab47-17bb5ae68c6b.png
      job-received.png
  test-data/
```

`src/images/` is listed in the planning table, but the uploaded source package does not contain files under `src/images/`, and the reviewed source does not import images from `src/images/`.

## Browser Entrypoint and Metadata Files

| File | Usage |
| --- | --- |
| `public/index.html` | CRA-style HTML template. It contains the `root` mount point used by `src/index.tsx`. It references `%PUBLIC_URL%/favicon.ico`, `%PUBLIC_URL%/logo192.png`, `%PUBLIC_URL%/manifest.json`, and `%PUBLIC_URL%/logo192.png` for the apple touch icon. |
| `public/manifest.json` | Defines the app name/short name, start URL, display mode, theme/background colors, and app icons `logo192.png` and `logo512.png`. |
| `public/robots.txt` | Static robots metadata. |
| `public/favicon.ico` | Browser tab favicon. |
| `public/apple-touch-icon.png` | Present in the package but not directly referenced by `index.html`; `index.html` references `logo192.png` for apple touch icon. |
| `public/metadata.json` | Present in the package. No reviewed source file references it directly. |

## Icons

### Navigation Icons

Navigation icons are loaded from `public/icons/` by `src/pages/NavigationSelector.tsx`. The current navigation tree uses explicit Home, Projects, project submenu, and NVFlare Manager items. Project icons use `public/icons/projects/{project.id}/icon.png`; global navigation items use explicit `/icons/nav_icon_*.png` paths.

| Asset | Current source reference |
| --- | --- |
| `public/icons/nav_icon_job_history.png` | Job History title and project landing Recent Jobs visual language; project submenu text itself is iconless. |
| `public/icons/nav_icon_job_runner.png` | Job Runner title and supported-function section visual language; project submenu text itself is iconless. |
| `public/icons/nav_icon_nvflare_manager.png` | `NavigationSelector.tsx` NVFlare Manager option. Also appears as a commented `iconPath` in `NVFlareManagerMain.tsx`. |
| `public/icons/nav_icon_projects_list.png` | `NavigationSelector.tsx` Projects accordion. |
| `public/icons/nav_icon_users_manager.png` | Retained asset for User Manager-related UI; not currently a persistent landing navigation item. |
| `public/icons/nav_icon_filters_manager.png` | Retained asset for Filters Manager-related UI; not currently a persistent landing navigation item. |
| `public/icons/nav_icon_participation_manager.png` | Participation-related asset retained for other UI/history. Home navigation now uses `nav_icon_home.png`. |
| `public/icons/nav_icon_home.png` | `NavigationSelector.tsx` global Home option. This asset replaced the former results-viewer icon filename. |
| `public/icons/nav_icon_users_login.png` | Used by `src/pages/LoginPage.tsx`. |

### Function Icons

`src/components/FunctionSelector.tsx` defines built-in function cards with icon filenames and renders them with:

```tsx
src={"/icons" + option.icon}
```

| Asset | FunctionSelector meaning |
| --- | --- |
| `public/icons/function_icon_SA.png` | Survival Analysis card. |
| `public/icons/function_icon_Chi.png` | Chi-square test card. |
| `public/icons/function_icon_Mean.png` | Mean card. |
| `public/icons/function_icon_Std.png` | Standard deviation card. |
| `public/icons/function_icon_TTest.png` | T-test card. |
| `public/icons/function_icon_EncFil.png` | Encrypted/filter-oriented card definition in `FunctionSelector.tsx`. |
| `public/icons/function_icon_Count.png` | Count card definition in `FunctionSelector.tsx`. |
| `public/icons/function_icon_LogCal.png` | Logistic/calculation-oriented card definition in `FunctionSelector.tsx`. |
| `public/icons/function_icon_feedback.png` | Present in assets but not referenced in the reviewed active source. |

### Project Icons

`src/components/ProjectListComponent.tsx` displays project icons by project ID:

```tsx
src={`/icons/projects/${project.id}/icon.png`}
```

The uploaded public assets include icons for project IDs `1` and `2` only:

- `public/icons/projects/1/icon.png`
- `public/icons/projects/2/icon.png`

If the backend returns a project with an ID that does not have a matching public icon path, the browser image request will fail and the broken image behavior will be handled by the browser. There is no source-level fallback image in `ProjectListComponent.tsx`.

## Logos and Shared Images

| Asset | Current source reference |
| --- | --- |
| `public/logos/share.png` | Rendered by `HeaderBar.tsx` as the main SHARE header logo. |
| `public/fhir_server.png` | Referenced in `HeaderBar.tsx` in a commented datasource display block. It is not active in the current rendered code path. |
| `public/logos/openfhe_logo.png` | Rendered by `FooterBar.tsx`; clicking it opens the OpenFHE website. |
| `public/logos/icf_logo2.png` | Rendered by `FooterBar.tsx`; clicking it opens the ICF website. |
| `public/logos/duality_logo.png` | Rendered by `FooterBar.tsx`; clicking it opens the Duality website. |
| `public/logos/dfci_logo.png` | Rendered by `FooterBar.tsx`; clicking it opens the Dana-Farber website. |
| `public/logos/nvflare_logo.png` | Present and referenced only inside commented footer code. |
| `public/logos/nvflare.png` | Present but not referenced in reviewed active source. |
| `public/logos/icf_logo.png` | Present but not referenced in reviewed active source. |
| `public/logos/duality.ico` | Present but not referenced in reviewed active source. |

## Status Images

`src/features/job_runner/pages/JobSubmissionPage.tsx` uses status images from:

```tsx
const STATUS_ICON_BASE = "/status-images/icons";
```

The page maps backend/status text to normalized status visual keys. It then uses the matching filename under `/status-images/icons`.

### Primary status visuals currently active in `PRIMARY_STATUS_FLOW`

| Key | Label | Asset |
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

Several status visual entries are present in assets but commented out in the primary flow, including `queued`, `filters-processing`, `broadcasting-participation-job`, `client-participation-established`, `ssh-connecting`, `ssh-connected`, `client-preparing`, `server-preparing`, `client-analysis`, and `server-analysis`.

### Secondary status visuals currently active in `SECONDARY_STATUS_VISUALS`

| Key | Label | Asset |
| --- | --- | --- |
| `participation-failed` | Participation Failed | `participation-failed.png` |
| `participation-empty` | Participation Empty | `participation-empty.png` |
| `analysis-failure` | Analysis Failure | `analysis-failure.png` |
| `threshold-not-met` | Threshold Not Met | `threshold-failure.png` |
| `failure` | Failure | `failure.png` |
| `warning` | Warning | `warning.png` |
| `error` | Error | `error.png` |

### Status alias behavior

`JobSubmissionPage.tsx` normalizes incoming status strings by lowercasing, replacing underscores/hyphens with spaces, collapsing whitespace, and looking up aliases. Examples:

| Incoming normalized text | Visual key |
| --- | --- |
| `checking client participation` | `checking-client-participation` |
| `broadcasting participation job` | `checking-client-participation` |
| `monitoring participation responses` | `checking-client-participation` |
| `client participation established` | `client-participation-established` |
| `no clients accepted participation` | `participation-empty` |
| `processing filters` | `job-defining` |
| `uploading nvflare job` | `job-defining` |
| `defining nvflare job` | `job-defining` |
| `broadcasting nvflare job` | `job-broadcast` |
| `job broadcast received` | `job-received` |
| `interactive key generation` | `interactive-key-generation` |
| `executing keygen workflow` | `interactive-key-generation` |
| `client encryption processing` | `client-compute` |
| `server encryption processing` | `server-compute` |
| `client performing analysis` | `client-compute` |
| `server performing analysis` | `server-compute` |
| `client processing results` | `client-results` |
| `server processing results` | `server-results` |
| `threshold not met` | `threshold-not-met` |
| `analysis failure` | `analysis-failure` |
| `exception encountered` | `error` |

`public/status-images/new/` contains three additional images. No reviewed active source references that directory.

## Static Filter Configuration

Static filter configuration is loaded from `/filters/...` paths. The app uses two related mechanisms:

1. `ProjectListComponent.tsx` hydrates backend project records with filter schemas based on `project.filter_system`.
2. Filter screens and manager screens load specific public JSON files directly.

### Filter file list

| File | Role |
| --- | --- |
| `public/filters/default/patient/patient_query.json` | Default Patient query controls. Loaded during project hydration and displayed by the filter manager. |
| `public/filters/default/observation/observation_data.json` | Default Observation local data controls and local-pass configuration. Loaded during project hydration and displayed by the filter manager. |
| `public/filters/cancer_type/patient/patient_query.json` | Cancer-type Patient data selection schema. Loaded by `FilterScreenPatients_CancerType.tsx`. |
| `public/filters/cancer_type/backup/patient_query.json` | Backup copy of the cancer-type Patient query schema. No reviewed source loads this backup path. |
| `public/filters/cancer_type/observation/observation_filters.json` | Cancer-type Observation filter file. Loaded during project hydration when the project filter system is `cancer_type`. |

### Filter files referenced by code but missing from the uploaded package

The source intentionally attempts to load several possible schema paths and tolerates missing files in some locations.

| Referenced path | Referencing source | Missing-file behavior |
| --- | --- | --- |
| `/filters/{filterSystem}/patient/patient_data.json` | `ProjectListComponent.tsx` hydration path list | Failed fetch is ignored; the schema key is omitted from `project.filter_schemas`. |
| `/filters/{filterSystem}/observation/observation_query.json` | `ProjectListComponent.tsx` hydration path list | Failed fetch is ignored; the schema key is omitted from `project.filter_schemas`. |
| `/filters/default/observation/observation_query.json` | `FilterManagerPage.tsx` | The manager records an error for that config card if the response is not OK. |
| `/filters/{filterSystem}/observation/observation_query.json` | `FilterScreenObservationsFHIR.tsx` | Used as `querySchemaUrl`. Missing-file behavior depends on `FilterControlsSection`; it attempts to fetch and parse the URL. |

### Filter schema shape

The shared frontend schema type is represented by `src/types/FilterSchema.tsx` and the equivalent utility imports in the job runner. The current shape is:

```ts
type FilterType =
  | "PATIENT_QUERY"
  | "PATIENT_DATA"
  | "OBSERVATION"
  | "OBSERVATION_QUERY"
  | "OBSERVATION_DATA";

interface FilterSchema {
  version?: string;
  resource?: { type?: string } | string;
  controls?: ControlSchema[];
  defaultsResolver?: Record<string, any>;
}

interface ControlSchema {
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

`ControlOption` supports `label`, `value`, and `token`. Some public config options also carry extra fields such as `code`; the code is used by cancer-type patient loading to map FHIR Condition coding values back to display labels.

`save.targets` compiles selected UI values into `Condition` objects:

```ts
interface Condition {
  filter_type: FilterType;
  column_name: string;
  operator: string;
  value?: string;
  values?: string[];
}
```

### Supported filter control types

`FilterControlsSection.tsx` actively renders these control types:

| Type | Behavior |
| --- | --- |
| `select` | Single dropdown using `options[].value` and `options[].label`. |
| `token-select` | Single dropdown using `options[].value` or `options[].token`. |
| `multi-select` | Scrollable checkbox list. |
| `multi-select-grid` | Grid checkbox list. |
| `number` | Numeric input. |
| `checkbox` | Boolean checkbox. |
| `date-range` | Two-date input stored as `[start, end]`. |
| `hidden` | Not rendered. |
| `label` | Static display label/text. |

`ui.span` controls layout width: `full`, `half`, or `third`. `ui.editable === false`, `disabled === true`, or a locked parent section disables the control.

### Filter defaults

`FilterControlsSection.tsx` resolves normal defaults directly. It also supports default resolver tokens beginning with `$`. The implemented resolver functions are:

| Resolver function | Behavior |
| --- | --- |
| `today` | Returns today as `YYYY-MM-DD`. |
| `offset` | Adds configured years, months, and/or days to the current date and returns `YYYY-MM-DD`. |

The uploaded `default/patient/patient_query.json` uses values like `$today-100y` and `$today`. The current resolver implementation only resolves strings when they exactly match a key in `defaultsResolver`. If a token is not found in `defaultsResolver`, the original string is left unchanged.

### Filter config loaded during project selection

`ProjectListComponent.tsx` hydrates each backend project with public filter schemas. It builds the filter-system path from:

```ts
const filterSystem = String(project.filter_system || "DEFAULT").trim().toLowerCase();
```

It tries these schema paths under `/filters/{filterSystem}/`:

| Filter type | Relative path |
| --- | --- |
| `PATIENT_QUERY` | `patient/patient_query.json` |
| `PATIENT_DATA` | `patient/patient_data.json` |
| `OBSERVATION` | `observation/observation_filters.json` |
| `OBSERVATION_QUERY` | `observation/observation_query.json` |
| `OBSERVATION_DATA` | `observation/observation_data.json` |

If a schema fetch fails, that schema is skipped. The project still loads with the schemas that were found.

### Filter config loaded by job runner screens

`FilterScreenPatients_CancerType.tsx` loads:

```text
/filters/cancer_type/patient/patient_query.json
```

It uses that schema to build cancer-type option maps keyed by SNOMED code and label/value. Those maps are then used while loading local test data to derive patient `cancer_type` values from Condition resources.

`FilterScreenObservationsFHIR.tsx` builds these public schema URLs from the selected project filter system:

```text
/filters/{filterSystem}/observation/observation_query.json
/filters/{filterSystem}/observation/observation_data.json
```

### Filter config manager behavior

`FilterManagerPage.tsx` is a static-config editor/viewer. It loads three hardcoded default-scope config paths:

| Key | Path | Title |
| --- | --- | --- |
| `patientQuery` | `/filters/default/patient/patient_query.json` | Patient Query |
| `observationQuery` | `/filters/default/observation/observation_query.json` | Observation Query |
| `observationData` | `/filters/default/observation/observation_data.json` | Observation Data |

The manager keeps separate loaded and edited copies in component state. Users can edit config values in the UI, reset a card back to its loaded config, and copy the edited JSON to the clipboard. There is no backend save endpoint in this component; copy-to-clipboard is the output mechanism.

## Static Analysis Configuration

Analysis configuration is loaded from:

- `public/analysis_config/analysis_query.json`
- `public/analysis_config/analysis_data.json`

`src/features/user_manager/pages/AnalysisManager.tsx` uses root-relative paths:

```ts
const queryPath = `/analysis_config/analysis_query.json`;
const dataPath = `/analysis_config/analysis_data.json`;
```

It fetches both files with `cache: "no-store"`.

### Analysis file list

| File | Role |
| --- | --- |
| `public/analysis_config/analysis_query.json` | Defines query-side resource/parameter requirements for each computation property. |
| `public/analysis_config/analysis_data.json` | Defines data-side resource, extractor, and argument wiring for each computation property. |

### Analysis config shape

Both analysis config files use the same top-level structure:

```ts
interface AnalysisQueryConfigFile {
  version?: string;
  computations?: Record<string, QueryComputationConfig>;
}

interface QueryComputationConfig {
  properties?: Record<string, QueryPropertyConfig>;
}

interface QueryPropertyConfig {
  columns?: Record<string, QueryColumnConfig>;
}

interface QueryColumnConfig {
  resources?: QueryResourceConfig[];
}

interface QueryResourceConfig {
  resourceType?: string;
  params?: QueryResourceParam[];
}
```

`analysis_data.json` uses the same `version -> computations -> properties -> columns` structure, but each data column uses:

```ts
interface DataColumnConfig {
  resourceType?: string;
  extractor?: string;
  args?: Record<string, any>;
}
```

The uploaded files both have `version: 1` and these computation keys:

- `kaplan-meier`
- `mean`
- `stdev`
- `chi2`
- `t-test`

Example property keys include:

| Computation | Example properties |
| --- | --- |
| `kaplan-meier` | `group_column_id`, `time_column_id`, `censoring_column_id` |
| `mean` | `data_column_id` |
| `stdev` | `data_column_id` |
| `chi2` | category/group style properties depending on config contents |
| `t-test` | data/group style properties depending on config contents |

### Analysis manager behavior

`AnalysisManager.tsx` loads both analysis files in parallel. It keeps loaded and edited versions of both configs in state. Users can:

- edit top-level version values
- edit computation/property/resource/column configuration through the rendered manager controls
- reset both configs to their originally loaded versions
- copy query config JSON to the clipboard
- copy data config JSON to the clipboard

There is no backend save endpoint in `AnalysisManager.tsx`; copy-to-clipboard is the output mechanism.

If either fetch returns a non-OK response, the page displays a red error card. If loading succeeds, the page renders config header controls and computation/property sections.

## Sequence Ontology Static Data

`public/SO/so-codes.json` is a large Sequence Ontology JSON file. The reviewed source package contains the file, but the reviewed active `src/` files do not directly fetch `/SO/so-codes.json`.

The file is therefore a static data asset available to the application, but no current frontend component in the uploaded package appears to consume it directly.

## Test Data Loading and Cache Busting

`public/test-data/` ships the browser-preview zips for the initiating site's datasources (`Biomarker_MSKChord_FHIR_Data_training_bundle_v4.zip`, `Survivability_FHIR_Data_part1_v1.zip`). The code expects local/test datasource files to be served from this directory at runtime.

The primary reviewed test-data loader is `src/features/job_runner/pages/filters/cancer_type/FilterScreenPatients_CancerType.tsx`. General Statistics uses the same resolution rules in `src/features/job_runner/utils/LocalBundlePreview.ts`, which additionally extracts `MedicationStatement` and `Observation` resources for the local patient and observation screens.

### Datasource URL normalization

The loader receives a datasource source string from selected project datasource metadata. It takes the basename and normalizes it to a zip file under `/test-data/`:

| Input source basename | Normalized fallback URL |
| --- | --- |
| `example.zip` | `/test-data/example.zip` |
| `example.json` | `/test-data/example.zip` |
| `example` | `/test-data/example.zip` |

### `_v#` version suffix support

The loader supports cache-busting/versioned test-data files using `_v#` suffixes. It strips any existing trailing `_v#` from the stem, then probes:

```text
/test-data/{stem}.zip
/test-data/{stem}_v1.zip
/test-data/{stem}_v2.zip
...
/test-data/{stem}_v200.zip
```

It selects the highest version found. After at least one match is found, it stops early after 10 consecutive misses. If no versioned or unversioned file is found by probing, it returns the normalized fallback URL.

### Existence probing

For each candidate URL, the loader appends a cache-busting query string:

```text
?_={Date.now()}-{randomString}
```

It first tries a `HEAD` request with `cache: "no-store"`. If the server returns `405`, it falls back to a `GET` request with a `Range: bytes=0-0` header. A response is considered a real datasource file only if it is OK and the content type does not include `text/html`.

### Loading and caching behavior

After resolving the latest URL, the actual zip fetch uses:

```ts
fetch(zipUrl, { cache: "force-cache" })
```

The loader then:

1. Tracks download progress when `Content-Length` is available.
2. Reads the zip as bytes.
3. Uses `fflate.unzipSync` to unzip in the browser.
4. Finds the first `.json` file inside the zip.
5. Parses the JSON.
6. Builds a patient preview from FHIR Bundle entries.
7. Extracts `Patient` resources.
8. Uses `Condition` resources and cancer-type schema mappings to assign `cancer_type` values to patients.

Progress labels include:

- `Preparing datasource load...`
- `Downloading datasource... {percent}%`
- `Loading datasource...`
- `Reading from datasource...`
- `Datasource loaded.`
- `Reading datasource records...`
- `Parsing datasource records...`
- `Building patient preview...`
- `Loaded {count} patients.`

### Test data error behavior

The loader throws explicit errors for:

- empty datasource source
- failed zip fetch
- missing JSON file in the zip
- unreadable JSON entry in the zip
- invalid/unparseable JSON

The component stores datasource loading errors in `datasourceLoadError` and displays datasource progress/error state as part of the cancer-type patient filter screen.

## Runtime Path Behavior

The current source uses root-relative public paths for static assets and config. Examples:

| Path pattern | Used by |
| --- | --- |
| `/icons/...` | `NavigationSelector.tsx`, `FunctionSelector.tsx`, `LoginPage.tsx`, `ProjectListComponent.tsx` |
| `/logos/...` | `HeaderBar.tsx`, `FooterBar.tsx` |
| `/status-images/icons/...` | `JobSubmissionPage.tsx` |
| `/filters/...` | `ProjectListComponent.tsx`, `FilterScreenPatients_CancerType.tsx`, `FilterScreenObservationsFHIR.tsx`, `FilterManagerPage.tsx` |
| `/analysis_config/...` | `AnalysisManager.tsx` |
| `/test-data/...` | `FilterScreenPatients_CancerType.tsx` |

The reviewed source does not use `process.env.PUBLIC_URL` for runtime asset/config fetches inside React components. `PUBLIC_URL` appears only in `public/index.html` template links.

Because paths are root-relative, the app assumes it is hosted at the domain root or behind hosting/routing that serves these paths from the same origin root. If the app is deployed under a non-root base path, these public asset/config requests would need path handling changes.

## Public Config Versus Backend Config

Static public config is not the same as backend configuration.

| Config source | Examples | Runtime behavior |
| --- | --- | --- |
| Public static JSON | `/filters/...`, `/analysis_config/...` | Served by the frontend static host; editable by replacing public files and redeploying/rehosting assets. |
| Backend API | `/projects/list`, `/projects/fhir/source`, saved filters, job config/results | Served by FastAPI/backend routes through `API_BASE`. |
| Derived frontend state | selected datasource group, selected filters, selected workflow group data, selected functions | Built in React state and submitted to backend. |

The public filter files are runtime inputs because components fetch them after the React app loads. Changing them does not require TypeScript recompilation, but in a built static deployment the changed JSON files still need to be present on the deployed static host.

## Missing Asset and Missing Config Behavior

Missing public assets and config have different behavior depending on caller:

| Caller | Missing behavior |
| --- | --- |
| Browser image tags | Broken image behavior unless the component implements a fallback. Reviewed image callers do not implement explicit fallback images. |
| `ProjectListComponent.tsx` filter schema hydration | Failed schema fetch is ignored; that schema is omitted from `project.filter_schemas`. |
| `FilterControlsSection.tsx` schema URL fetch | Attempts to fetch and parse JSON. The component shows `Loading controls…` while no schema is set; there is no local error panel in this component. |
| `FilterManagerPage.tsx` | Per-config error is stored and displayed for failed config fetches. |
| `AnalysisManager.tsx` | Any failed query/data config fetch sets a page-level error. |
| `FilterScreenPatients_CancerType.tsx` cancer-type schema fetch | Logs error and falls back to empty code/label maps. |
| `FilterScreenPatients_CancerType.tsx` test-data zip fetch | Stores and displays datasource load error. |

## Implementation Notes for Future Changes

- Add new project icons under `public/icons/projects/{project.id}/icon.png` if the backend returns new project IDs.
- Keep function icon filenames aligned with the `icon` strings in `FunctionSelector.tsx`.
- Keep navigation icon filenames aligned with `NavigationSelector.tsx` option definitions.
- Keep status icon filenames aligned with `JobSubmissionPage.tsx` `StatusVisual.filename` values and alias map.
- When adding new filter systems, create the matching directory under `public/filters/{filter_system.toLowerCase()}/` and provide the schemas expected by `ProjectListComponent.tsx`.
- When adding local/test datasource files, place zip files under `public/test-data/` and use `_v#` suffixes for cache-busting updates.
- The uploaded package does not include the local test data zip files; production or local runtime behavior depends on those files being supplied separately when local/test datasource loading is used.
