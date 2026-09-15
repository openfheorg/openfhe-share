# User Settings and Datasource / Model File Management

## Purpose

`UserSettingsPage` lets the current user configure project-specific runtime values that are stored in backend MySQL and consumed by NVFlare jobs. The page now covers two related settings areas:

| Area | Stored value | Runtime consumer |
| --- | --- | --- |
| Datasource Group Location | JSON file path or FHIR `/fhir` URL for the current user/project/datasource group. | NVFlare clients request this from the server at job runtime through the datasource lookup aux channel. |
| Model File Locations | Initiator-local model artifact paths for project/datasource group/model/lookup/artifact combinations. | The initiator/leader site reads these paths during `workflow_model_upload__<model_key>` and uploads model artifacts for open-access or encrypted workflows. |

The page replaces static client-side datasource config files and backend-bundled biomarker model directories. Runtime file locations are user/project settings, not files copied by the backend stager.

## Files Covered

| File | Area |
| --- | --- |
| `src/pages/UserSettingsPage.tsx` | Project datasource group and model file settings UI. |
| `src/context/UserRoleContext.tsx` | User session, user id, projects, selected project, and datasource context. |
| `src/constants/Constants.tsx` | `API_BASE` and `API_PROJECTS_LIST`. |
| `src/types/Project.ts` | Project, datasource group, and model-file-settings metadata used to render fields. |
| `src/components/HeaderBar.tsx` | Navigation path to user settings/sign out behavior. |

## Page-Level Selection

The page loads project metadata from `POST /projects/list`, then combines that project metadata with the current session datasource assignments from `UserRoleContext`.

The user selects:

1. Project.
2. Datasource group for that project, when groups exist.

The selected datasource group drives both the datasource editor and the model file editor. This prevents all groups from being shown at once and keeps the model file rows scoped to the group that will be used by the submitted job.

## Datasource Group Location Section

For the selected project/group, the datasource section renders the saved runtime datasource value.

- If the project defines datasource groups, the page renders the selected group's datasource field.
- If the project does not define datasource groups, the page renders one project-level datasource field.
- Existing values are prefilled from `userSession.projects` or `userSession.selected_project_datasources`.
- Mode radio buttons select JSON file path mode or FHIR server URL mode.
- Datasource text fields remain directly editable.
- The page does not browse for files and does not depend on browser `fakepath` values.

## Datasource Field Model

Internally the page builds `DataSourceField` entries from selected project metadata:

```ts
type DataSourceMode = "json_file" | "fhir_server";

interface DataSourceField {
  key: string;
  label: string;
  datasource_group_id: number | string | null;
  datasource_group_name: string | null;
  is_default_group: boolean;
}
```

The editable value is tracked as a `DataSourceSetting`:

```ts
interface DataSourceSetting {
  mode: DataSourceMode;
  value: string;
  valuesByMode: {
    json_file: string;
    fhir_server: string;
  };
}
```

`valuesByMode` preserves the user's current JSON-path value and FHIR-server value when switching radio modes, so changing modes does not erase the other mode's value.

## Datasource Validation Rules

The page validates only changed datasource fields when Apply is clicked.

| Mode | Validation |
| --- | --- |
| `json_file` | The trimmed value must end with `.json`. |
| `fhir_server` | The normalized value must be a valid `http://` or `https://` URL and must end with `/fhir`. |

FHIR URLs are normalized by trimming the input and removing trailing slashes before submission.

## Model File Locations Section

Projects that enable model file settings render a separate `Model File Locations` section for the selected datasource group. These paths are intended to be local to the initiator/leader site, not the browser and not the backend container.

Each model file record includes:

```ts
interface UserModelFileRecord {
  project_id: number | string;
  datasource_group?: number | string | null;
  datasource_group_id?: number | string | null;
  datasource_group_name?: string | null;
  model_file_lookup_key: string;
  model_file_lookup_value: string;
  model_key: string;
  artifact_type: string;
  source: string;
}
```

The current biomarker records use cancer type as the lookup dimension, model keys such as `cox_lasso` and `logistic_reg`, and artifact types such as `weights` and `cutoff`.

## Model File Location Modes

The model file section supports two modes:

| Mode | Behavior |
| --- | --- |
| Manual | Each model file row has an editable source path. |
| Pattern | The page derives all visible model file paths from pattern fields. Individual row inputs are read-only previews. |

Pattern mode has these editable fields:

| Field | Example |
| --- | --- |
| Parent location | `/data/model_files/` |
| Project folder | `project_${project_id}/` |
| Datasource group folder | `datasource_group_${datasource_group_id}/` |
| Filename pattern by artifact | `${model_key}_${lookup_value}_weights.csv` or `${model_key}_${lookup_value}_cutoff.csv` |

Supported markers are:

```text
${project_id}
${datasource_group_id}
${datasource_group_name}
${model_key}
${lookup_key}
${lookup_value}
${artifact_type}
```

When existing saved paths match the current project and datasource group, the page can infer pattern values from those concrete paths. For example, a saved path containing `project_2/datasource_group_1/` for project id `2` and datasource group id `1` can be represented as `project_${project_id}/datasource_group_${datasource_group_id}/`.

## Apply Flow

When Apply is clicked:

1. Datasource values are trimmed and compared with their initially loaded values.
2. Model file values are trimmed and compared with their initially loaded values.
3. Only changed datasource rows are sent to `POST /user/datasource/apply`.
4. Only changed model file rows are sent to `POST /user/model-files/apply`.
5. Refreshed response payloads reset the local change baselines.
6. A temporary success notice is shown when settings are saved or when no changes are detected.

Datasource request payload shape:

```json
{
  "user_id": 2,
  "updates": [
    {
      "project_id": 2,
      "datasource_group_id": 1,
      "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json"
    }
  ]
}
```

Model file apply payload shape:

```json
{
  "user_id": 1,
  "updates": [
    {
      "project_id": 2,
      "datasource_group_id": 1,
      "model_file_lookup_key": "cancer_type",
      "model_file_lookup_value": "Non-Small Cell Lung Cancer",
      "model_key": "logistic_reg",
      "artifact_type": "cutoff",
      "source": "/data/model_files/project_2/datasource_group_1/logistic_reg_Non-Small Cell Lung Cancer_cutoff.csv"
    }
  ]
}
```

If `user_id` is not available in context, the page sends `username` instead.

## Backend Endpoints Used

| Endpoint | Caller | Purpose |
| --- | --- | --- |
| `POST /user/role` | Login/session setup | Returns role, user id, and project datasource assignments for `UserRoleContext`. |
| `POST /projects/list` | `UserSettingsPage` | Loads project metadata, datasource groups, model-file-settings flag, filter systems, function restrictions, and workflow groups. |
| `POST /user/datasource/apply` | `UserSettingsPage` | Persists changed datasource settings for the current user. |
| `POST /user/model-files/list` | `UserSettingsPage` | Loads current user's model file source rows grouped by project and datasource group. |
| `POST /user/model-files/apply` | `UserSettingsPage` | Persists changed model file source rows for the current user. |
| `POST /projects/fhir/source` | Project datasource consumers | Resolves a datasource for a username/project/group and can optionally execute a FHIR query for server sources. |
| `POST /clients/datasource/source` | NVFlare server | Resolves the runtime datasource for a client/site during job execution. The frontend does not call this endpoint. |

## Relationship to Job Execution

Datasource settings flow:

```text
UserSettingsPage saves users_fhir_source_by_project
NVFlare client reads filters.json for project/group context
NVFlare client asks server for datasource
NVFlare server calls backend /clients/datasource/source
Backend reads the saved user datasource setting
Client receives and uses the datasource at runtime
```

Model file settings flow:

```text
UserSettingsPage saves users_model_file_source_by_project
NVFlare backend stager writes app_client/custom/model_file_sources.json
workflow_model_upload__<model_key> runs before model-consuming workflows
initiator/leader site reads the saved paths from its own filesystem
initiator uploads open-access or encrypted model artifacts
server writes runtime artifacts into app_server/custom
later workflows consume those runtime artifacts
```

This is why datasource and model file settings can be changed through the UI without generating a client-side datasource config file or bundling model CSVs into the backend job template.

## Local Standalone Path Rules

In local standalone runs, datasource values saved in backend must be the runtime paths visible inside the client container:

```text
/data/client/<filename>.json
```

The `.env.local` datasource values used by standalone client utilities are host-side staging paths, for example:

```text
nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json
```

Those host-side paths are used to copy JSON files into the client image. They are not the final datasource path used by analytics code inside the running container.

Model file paths are different: they must be valid on the initiator/leader site that performs model upload. In local standalone runs the seeded default model root is usually:

```text
/data/model_files/project_<project_id>/datasource_group_<datasource_group_id>/
```

In non-local development deployments, the seeded default model root is usually an initiator host path such as:

```text
/path/to/initiator/models/project_<project_id>/datasource_group_<datasource_group_id>/
```
