# User Manager Filter and Analysis Config

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/user_manager/UserManagerMain.tsx` | User manager feature wrapper. |
| `src/features/user_manager/pages/FilterManagerPage.tsx` | Filter configuration manager screen. |
| `src/features/user_manager/pages/AnalysisManager.tsx` | Analysis configuration manager screen. |
| `src/components/HeaderTitle.tsx` | Shared title component used by the user manager screen. |
| `src/pages/NavigationSelector.tsx` | Navigation rail used inside the user manager feature wrapper. |
| `src/components/ProjectName.tsx` | Shared project name/description display used in the user manager header title. |
| `public/filters/` | Static filter configuration JSON used by filter manager screens and related job-runner filter behavior. |
| `public/analysis_config/` | Static analysis configuration JSON used by analysis manager screens. |

## Feature Role

The user manager feature is currently a configuration inspection and editing workspace for project-related filter and analysis JSON. It is not a user-account administration UI in the current frontend archive.

The current areas are:

- filter configuration, rendered by `FilterManagerPage.tsx`
- analysis configuration, rendered by `AnalysisManager.tsx`

Both pages load static JSON files from `public/` using `fetch(..., { cache: "no-store" })`, keep editable copies in React state, allow reset-to-loaded behavior, and provide copy-to-clipboard actions. The current code does not persist edits back to the backend or write files from the browser.

## Entrypoint from `App.tsx`

`App.tsx` renders `UserManagerMain` when the top-level screen is `users_manager` and a project has been selected.

```tsx
<UserManagerMain
  key={`users_manager:${screenReloadKeys.users_manager ?? 0}`}
  project={project}
  setMainScreen={setScreen}
  fhirServer={errorMessage ? null : fhirServer}
/>
```

The feature receives the selected `Project` object, the top-level screen setter, and the current FHIR server display value. If `App.tsx` has detected an invalid FHIR server URL, it passes `null` instead of the invalid server string.

`users_manager` remains a top-level `AppScreen` that can render when a project is selected, but it is not currently exposed as an item in the new Home/Projects/NVFlare landing navigation.

## `UserManagerMain.tsx`

### Props

| Prop | Type | Required | Source | Use |
| --- | --- | --- | --- | --- |
| `setMainScreen` | `(screen: AppScreen) => void` | Yes | `App.tsx` | Returns to the landing environment or moves to another top-level screen. |
| `project` | `Project` | Yes | `App.tsx` selected project state | Passed to child manager pages and displayed in the title. |
| `fhirServer` | `string \| null \| undefined` | No | `App.tsx` derived selected datasource/FHIR source | Passed to child manager pages for display. |

### Local State

| State | Type | Initial value | Purpose |
| --- | --- | --- | --- |
| `screen` | `"filter_manager" \| "analysis_manager"` | `"filter_manager"` | Selects which manager page is visible. |
| `animate` | `boolean` | `true` | Toggles the `animate-in` class after screen changes. |

### Rendered Layout

`UserManagerMain` renders:

1. A `NavigationSelector` in `variant="nav"` mode.
2. A `HeaderTitle` titled `Users Manager:` followed by `ProjectNameWithDescription`.
3. A short description: `Manage source, filter, and analysis configuration used to align analysis data requirements to a FHIR source.`
4. Two buttons: `Filter Manager` and `Analysis Manager`.
5. Either `FilterManagerPage` or `AnalysisManager`.

The internal manager selection buttons use `primary-button` when active and `secondary-button` when inactive.

### Navigation Behavior

`UserManagerMain` remains a separately routed feature screen. It is not currently part of the new persistent project navigation tree.

## Filter Manager Page

`FilterManagerPage.tsx` loads and displays static filter JSON files. It allows the loaded JSON to be reshaped in memory through form fields and JSON textareas.

### Props

| Prop | Type | Required | Use |
| --- | --- | --- | --- |
| `project` | `Project` | Yes | Displayed in the page context card. The label is resolved from `project.name`, `project.project_name`, `project.id`, or `Unknown Project`. |
| `fhirServer` | `string \| null \| undefined` | No | Displayed in the page context card. Missing values render as `No FHIR server URL provided`. |

### Local Types

`FilterManagerPage.tsx` defines these local configuration interfaces:

```ts
type Primitive = string | number | boolean | null;

interface OptionConfig {
  label?: string;
  value?: string | number | boolean;
  [key: string]: any;
}

interface ControlConfig {
  id?: string;
  field?: string;
  label?: string;
  type?: string;
  default?: any;
  options?: OptionConfig[];
  fhir?: Record<string, any>;
  query?: Record<string, any>;
  save?: Record<string, any>;
  localPass?: Record<string, any>;
  ui?: Record<string, any>;
  [key: string]: any;
}

interface ResourceConfig {
  type?: string;
  [key: string]: any;
}

interface FilterConfigFile {
  version?: string;
  resource?: ResourceConfig;
  controls?: ControlConfig[];
  defaultsResolver?: Record<string, any>;
  localPass?: Record<string, any>;
  [key: string]: any;
}
```

The page also tracks each loaded file as a `LoadedFilterConfig`:

```ts
interface LoadedFilterConfig {
  key: string;
  title: string;
  description: string;
  path: string;
  systemScope: string;
  loadedConfig: FilterConfigFile | null;
  editedConfig: FilterConfigFile | null;
  loading: boolean;
  error: string | null;
  copied: boolean;
}
```

### Configs Loaded by the Page

The page currently hardcodes `FILTER_CONFIGS` with these entries:

| Key | Title | Path | Scope | Notes |
| --- | --- | --- | --- | --- |
| `patientQuery` | `Patient Query` | `/filters/default/patient/patient_query.json` | `DEFAULT` | Present in the uploaded archive. |
| `observationQuery` | `Observation Query` | `/filters/default/observation/observation_query.json` | `DEFAULT` | Referenced by code, but this exact file is not present in the uploaded archive. |
| `observationData` | `Observation Data` | `/filters/default/observation/observation_data.json` | `DEFAULT` | Present in the uploaded archive. |

The missing `observation_query.json` path means the Observation Query card will enter an error state in the current uploaded frontend unless that file is added to `public/filters/default/observation/` or the code is changed to point at an existing file.

### Actual Files Under `public/filters/`

The uploaded frontend archive contains:

| File | Top-level keys | Notes |
| --- | --- | --- |
| `public/filters/default/patient/patient_query.json` | `version`, `resource`, `controls`, `defaultsResolver` | DEFAULT Patient query controls. |
| `public/filters/default/observation/observation_data.json` | `version`, `resource`, `localPass`, `controls` | DEFAULT Observation local-pass and metrics controls. |
| `public/filters/cancer_type/patient/patient_query.json` | `version`, `resource`, `controls`, `defaultsResolver` | Cancer-type Patient query controls. |
| `public/filters/cancer_type/observation/observation_filters.json` | `version`, `resource`, `controls` | Cancer-type Observation filter metadata. |
| `public/filters/cancer_type/backup/patient_query.json` | `version`, `resource`, `controls`, `defaultsResolver` | Backup copy of cancer-type Patient query controls. |

Only the DEFAULT patient query and DEFAULT observation data files are loaded by `FilterManagerPage.tsx` in the current code.

### Filter Config JSON Shape

A filter config file is expected to follow this general shape:

```json
{
  "version": "2.0",
  "resource": {
    "type": "Patient"
  },
  "controls": [
    {
      "id": "gender",
      "field": "gender",
      "label": "Gender",
      "type": "select",
      "default": "",
      "options": [
        { "label": "Any", "value": "" },
        { "label": "Male", "value": "male" }
      ],
      "fhir": {},
      "query": {},
      "save": {},
      "localPass": {},
      "ui": {}
    }
  ],
  "defaultsResolver": {},
  "localPass": {}
}
```

Supported properties are permissive. The manager preserves unknown root-level and control-level keys through `Additional JSON` fields.

### Filter Control Types Present in Config

The uploaded filter config files include these control types:

| Type | Example file | Example control | Purpose |
| --- | --- | --- | --- |
| `select` | `default/patient/patient_query.json` | `gender`, `medication` | Single value choice. |
| `date-range` | `default/patient/patient_query.json` | `birthDate`, `death-date` | Two-value date range. |
| `multi-select-grid` | `default/observation/observation_data.json` | `deletionRegions`, `amplificationRegions` | Multi-value region selection. |
| `number` | `default/observation/observation_data.json` | `minDeletions`, `minAmplifications`, `minTotal` | Numeric threshold controls. |
| `label` | `cancer_type/observation/observation_filters.json` | `observation_filters_info` | Informational display metadata. |

`FilterManagerPage.tsx` does not render these controls as end-user filter inputs. It renders the config fields used to define those controls.

### State and Editing Behavior

`FilterManagerPage` owns a single state object:

```ts
const [configs, setConfigs] = useState<Record<string, LoadedFilterConfig>>({});
```

On mount, it initializes one loading card per `FILTER_CONFIGS` entry, then loads all configured paths concurrently with `Promise.all`.

For each successful file load:

- `loadedConfig` is set to the parsed JSON.
- `editedConfig` is set to the same parsed JSON object.
- `loading` becomes `false`.
- `error` becomes `null`.

For each failed file load:

- `loading` becomes `false`.
- `error` becomes the caught error message or `Failed to load config.`
- the card renders the error text in red.

The page uses an `active` flag in the effect cleanup to avoid writing state after unmount.

### Editable Fields

For each loaded config, the page displays and edits:

- root `version`
- `resource.type`
- additional `resource` JSON excluding `type`
- `defaultsResolver` JSON when present on the root object
- `localPass` JSON when present on the root object
- each control under `controls`

For each control, the page displays and edits:

- `id`
- `field`
- `label`
- `type`
- `default`
- `options` JSON
- `fhir` JSON
- `query` JSON
- `save` JSON
- `localPass` JSON
- `ui` JSON
- additional JSON for unknown control fields

JSON textareas use `parseJsonOrFallback`. Invalid JSON does not show a validation message; the prior object is retained as the fallback.

`fromJsonInput` is used for default values. Empty text becomes an empty string. Valid JSON is parsed into the corresponding JSON value. Invalid JSON remains as the raw string.

### Actions

| Action | Behavior |
| --- | --- |
| `Reset to Loaded Config` | Replaces `editedConfig` with a deep clone of `loadedConfig`. |
| `Copy JSON` | Copies the current `editedConfig` to the clipboard as pretty-printed JSON. The button text changes to `Copied` for 1.5 seconds. |

There is no save button and no backend update call.

## Analysis Manager Page

`AnalysisManager.tsx` loads and displays the static analysis query/data configuration pair. It lets users compare and edit the query-side requirements and data-side extractor definitions used for analysis computations.

### Props

| Prop | Type | Required | Use |
| --- | --- | --- | --- |
| `project` | `Project` | Yes | Displayed in the page context card. The label is resolved from `project.name`, `project.project_name`, `project.id`, or `Unknown Project`. |
| `fhirServer` | `string \| null \| undefined` | No | Displayed in the page context card. Missing values render as `No FHIR server URL provided`. |

`AnalysisManager.tsx` computes `projectKey` from `project.id || "project1"`, but the current page does not use that key in the loaded file paths.

### Local Types

Analysis query configuration:

```ts
interface QueryResourceParam {
  name?: string;
  value?: string | number | boolean;
  values?: Array<string | number | boolean>;
  [key: string]: any;
}

interface QueryResourceConfig {
  resourceType?: string;
  params?: QueryResourceParam[];
  [key: string]: any;
}

interface QueryColumnConfig {
  resources?: QueryResourceConfig[];
  [key: string]: any;
}

interface QueryPropertyConfig {
  columns?: Record<string, QueryColumnConfig>;
  [key: string]: any;
}

interface QueryComputationConfig {
  properties?: Record<string, QueryPropertyConfig>;
  [key: string]: any;
}

interface AnalysisQueryConfigFile {
  version?: string;
  computations?: Record<string, QueryComputationConfig>;
  [key: string]: any;
}
```

Analysis data configuration:

```ts
interface DataColumnConfig {
  resourceType?: string;
  extractor?: string;
  args?: Record<string, any>;
  [key: string]: any;
}

interface DataPropertyConfig {
  columns?: Record<string, DataColumnConfig>;
  [key: string]: any;
}

interface DataComputationConfig {
  properties?: Record<string, DataPropertyConfig>;
  [key: string]: any;
}

interface AnalysisDataConfigFile {
  version?: string;
  computations?: Record<string, DataComputationConfig>;
  [key: string]: any;
}
```

Page state:

```ts
interface LoadedAnalysisConfigs {
  loadedQueryConfig: AnalysisQueryConfigFile | null;
  editedQueryConfig: AnalysisQueryConfigFile | null;
  loadedDataConfig: AnalysisDataConfigFile | null;
  editedDataConfig: AnalysisDataConfigFile | null;
  loading: boolean;
  error: string | null;
  copiedQuery: boolean;
  copiedData: boolean;
}
```

### Configs Loaded by the Page

`AnalysisManager.tsx` loads:

| Config | Path | Required by current page |
| --- | --- | --- |
| Analysis query config | `/analysis_config/analysis_query.json` | Yes |
| Analysis data config | `/analysis_config/analysis_data.json` | Yes |

Both files are loaded with `fetch(path, { cache: "no-store" })` inside a single effect. If either fetch fails, the page sets one page-level error and does not render the editor.

### Actual Files Under `public/analysis_config/`

The uploaded frontend archive contains:

| File | Top-level keys | Computation keys |
| --- | --- | --- |
| `public/analysis_config/analysis_query.json` | `version`, `computations` | `kaplan-meier`, `mean`, `stdev`, `chi2`, `t-test` |
| `public/analysis_config/analysis_data.json` | `version`, `computations` | `kaplan-meier`, `mean`, `stdev`, `chi2`, `t-test` |

### Analysis Query JSON Shape

The query config maps each computation to properties, each property to candidate columns, and each column to one or more FHIR resource requirements.

```json
{
  "version": "1",
  "computations": {
    "kaplan-meier": {
      "properties": {
        "group_column_id": {
          "columns": {
            "sex": {
              "resources": [
                { "resourceType": "Patient" }
              ]
            },
            "arid1a": {
              "resources": [
                {
                  "resourceType": "Observation",
                  "params": [
                    { "name": "code", "value": "69548-6" }
                  ]
                }
              ]
            }
          }
        }
      }
    }
  }
}
```

### Analysis Data JSON Shape

The data config maps each computation/property/column to the local extractor definition used to derive the analysis column from loaded resources.

```json
{
  "version": "1",
  "computations": {
    "kaplan-meier": {
      "properties": {
        "group_column_id": {
          "columns": {
            "sex": {
              "resourceType": "Patient",
              "extractor": "patient_gender"
            },
            "arid1a": {
              "resourceType": "Observation",
              "extractor": "observation_variant_value_by_parent_code_and_gene_code",
              "args": {
                "parentCode": "69548-6",
                "geneComponentCode": "48018-6"
              }
            }
          }
        }
      }
    }
  }
}
```

### State and Editing Behavior

`AnalysisManager` owns a single `LoadedAnalysisConfigs` state object initialized with both configs empty, `loading: true`, `error: null`, and both copied flags false.

On successful load:

- `loadedQueryConfig` receives `analysis_query.json`.
- `editedQueryConfig` receives `analysis_query.json`.
- `loadedDataConfig` receives `analysis_data.json`.
- `editedDataConfig` receives `analysis_data.json`.
- `loading` becomes `false`.

On failure:

- `loading` becomes `false`.
- `error` becomes the thrown message or `Failed to load analysis configs.`

Like the filter page, the analysis page uses an `active` flag to avoid setting state after unmount.

### Computation and Column Rendering

`computationKeys` is derived as the union of keys from `editedQueryConfig.computations` and `editedDataConfig.computations`.

For each computation, the page builds a union of property keys from the query-side and data-side configs. For each property, it builds a union of column keys from the query-side and data-side columns.

Each rendered column shows two side-by-side panels:

| Panel | Editable fields |
| --- | --- |
| Query Side | `resources` JSON and additional query JSON. |
| Data Side | `resourceType`, `extractor`, `args` JSON, and additional data JSON. |

Unknown per-column keys are preserved through the additional JSON textareas.

### Actions

| Action | Behavior |
| --- | --- |
| `Reset to Loaded Configs` | Restores both edited configs from deep clones of the loaded configs. |
| `Copy Query JSON` | Copies the current edited query config to the clipboard and toggles `copiedQuery` for 1.5 seconds. |
| `Copy Data JSON` | Copies the current edited data config to the clipboard and toggles `copiedData` for 1.5 seconds. |
| Whole Config JSON textareas | Allow direct editing of the full query and data JSON objects. Invalid JSON falls back to the previous object. |

There is no backend save/update behavior.

## Public Configuration and Rebuild Behavior

Both manager pages load files from the `public/` directory at runtime using absolute public paths. In a built React app, those files are served as static assets.

Changing the JSON files does not require changing TypeScript code, but the deployed static asset must be updated in the hosted frontend environment. Local development changes under `public/` are picked up by the dev server as static assets.

The pages do not currently select different config files by project ID, datasource group, or FHIR server. They display the current project and FHIR server for context only.

## Relationship to Job Runner

The user manager pages expose the same kinds of static configuration that the job runner/filter/analysis flow depends on, but they are not wired into the job runner through shared state.

Current relationship:

| Area | Relationship |
| --- | --- |
| Filter config | `public/filters/` contains filter definitions used by frontend filter behavior elsewhere. `FilterManagerPage` displays and edits copies in local state only. |
| Analysis config | `public/analysis_config/` contains computation query/data definitions. `AnalysisManager` displays and edits copies in local state only. |
| Job submission | No direct submit payload integration from these manager pages. |
| Backend persistence | No current backend endpoints are called by these pages. |
| Results/export | No direct state handoff from these manager pages to results or export. |

## Backend Calls

The current user manager files do not import API constants from `Constants.tsx` and do not call backend endpoints.

All data loading in this feature is static asset loading through browser `fetch`:

- `/filters/default/patient/patient_query.json`
- `/filters/default/observation/observation_query.json`
- `/filters/default/observation/observation_data.json`
- `/analysis_config/analysis_query.json`
- `/analysis_config/analysis_data.json`

## Error and Loading Behavior

| Page | Loading behavior | Error behavior |
| --- | --- | --- |
| `FilterManagerPage` | Initializes one loading card per configured file and shows `Loading config...` per card. | Failed files show the error message in red inside that file's card; other successful files still render. |
| `AnalysisManager` | Shows a page-level `Loading analysis configs...` message while both files load. | If either config fails, shows one page-level red error and does not render the editor. |

Clipboard copy failures are silently swallowed in both pages.

Invalid JSON typed into textareas does not show a visible error. The prior value is retained through `parseJsonOrFallback`.

## Known Current Gaps

- `src/features/user_manager/utils/` is listed conceptually, but no such directory exists in the uploaded frontend archive.
- `FilterManagerPage.tsx` references `/filters/default/observation/observation_query.json`, but the uploaded archive contains `/filters/default/observation/observation_data.json` only under that DEFAULT observation path.
- `users_manager` can still be rendered by `App.tsx`, but the current persistent landing navigation does not expose it as a menu option.
- `HeaderBar.tsx` is not used by the current user manager implementation. The feature uses `NavigationSelector`, `HeaderTitle`, and `ProjectNameWithDescription`.
- The manager pages are in-browser editors only. They can reset and copy JSON, but they cannot save changes to disk, public assets, or backend storage.
- `AnalysisManager.tsx` computes a `projectKey`, but the current static paths do not use it.


## User Settings Page

`UserSettingsPage.tsx` manages the current user's project datasource settings and, for projects that enable model file settings, initiator-local model file locations. It is separate from the user manager's filter/analysis configuration screens, but it uses the same backend project metadata and user session context.

The page:

1. Loads projects from `POST /projects/list`.
2. Reads current user datasource assignments from `UserRoleContext`.
3. Lets the user select a project.
4. Lets the user select a datasource group when the project defines groups.
5. Shows the selected group's datasource field in `Datasource Group Location`.
6. Shows the selected group's model file rows in `Model File Locations` when model file settings are enabled.
7. Supports manual model file paths or derived paths from a pattern.
8. Validates changed datasource fields.
9. Sends datasource updates to `POST /user/datasource/apply`.
10. Sends model file source updates to `POST /user/model-files/apply`.
11. Updates local session project datasource state from returned `projects` payloads.

The page does not use browser file selection or `fakepath` values. For local standalone JSON datasources, saved runtime values should point to `/data/client/<filename>.json` because that is where the client container reads staged JSON files. Model file paths are different: they must point to locations that are readable by the initiator/leader site during `workflow_model_upload__<model_key>`.
The page does not use browser file selection or `fakepath` values. For local standalone JSON datasources, saved runtime values should point to `/data/client/<filename>.json` because that is where the client container reads staged JSON files.
