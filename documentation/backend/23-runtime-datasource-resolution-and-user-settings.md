# Runtime Datasource and Model File Resolution from User Settings

## Purpose

Runtime datasource resolution and biomarker model-file resolution are now owned by backend user/project settings instead of client-side FHIR base config files or backend-bundled model directories. NVFlare clients no longer need a generated `DUALITY_FHIR_BASE_CONFIG.json` file or a `DUALITY_NVFLARE_FHIR_BASE_CONFIG` environment variable. A client receives the datasource for a job at runtime through the NVFlare server.

This keeps datasource selection and model-file selection aligned with the User Settings model used by the frontend and backend database.

## Runtime Flow

The current job-time datasource flow is:

```text
client analytics_executor
  -> reads job-local custom/filters.json
  -> extracts project_id and selected datasource_group.id
  -> sends NVFlare aux request to the server on duality.datasource.lookup

NVFlare server datasource_request_receiver
  -> receives the request from the client site
  -> calls backend POST /clients/datasource/source
  -> sends client_name, project_id, datasource_group_id, and the internal secret outside local mode

backend ClientRoutes
  -> maps client_name to users through nvflare_clients
  -> resolves the latest users_fhir_source_by_project row for that user/project/group
  -> returns source, source_type, datasource group metadata, and datasource record id

NVFlare server
  -> replies to the requesting client over the NVFlare aux channel

client analytics_executor
  -> assigns analytics_manager.stat_data_path
  -> registers the runtime datasource with FHIRBaseConfigResolver for downstream utilities
```

The server-side workflow does not read `filters.json` to determine datasource context. `filters.json` stays client-local because it is already staged into the client job app and contains the selected project/datasource group.

## Files Involved

| File | Responsibility |
| --- | --- |
| `app/api/routes/ClientRoutes.py` | Provides `/clients/datasource/source` for trusted server-side datasource lookup by NVFlare client/site identity. |
| `app/api/routes/UserRoutes.py` | Provides `/user/role` session lookup, `/user/datasource/apply`, `/user/model-files/list`, and `/user/model-files/apply` for saving User Settings changes. |
| `app/api/routes/ProjectRoutes.py` | Provides `/projects/list` and `/projects/fhir/source`. |
| `app/core/mysql/MySQLConnectionProvider.py` | Creates datasource tables, datasource groups, default site/client mappings, and environment-specific seeded datasource values. |
| `app/core/mysql/managers/UsersManager.py` | Resolves users, client mappings, current datasource records, user project datasource payloads, datasource updates, and model-file source settings. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Stages `model_file_sources.json` and inserts model-upload workflows before model-consuming workflows. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/custom/analytics_executor.py` | Reads `filters.json`, requests datasource from the server, sets the runtime datasource path/URL, and runs initiator/leader-side model-upload tasks. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_aggregator.py` | Server-side model-upload aggregation writes runtime artifacts into `app_server/custom`. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/datasource_request_receiver.py` | Handles `duality.datasource.lookup` aux requests and calls the backend. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/config/config_fed_server.json` | Registers `datasource_request_receiver` as a server-side component/event handler. |
| `app/core/job_runner/nvflare_jobs/apis/FHIRBaseConfigResolver.py` | Holds runtime project/source mappings registered by the client after datasource lookup. |

## Backend Endpoint Contracts

### `POST /user/role`

The login/session lookup returns the user role, user id, and datasource assignments grouped by project. The frontend uses this to seed `UserRoleContext`.

Request:

```json
{
  "username": "client_site1"
}
```

Response shape:

```json
{
  "username": "client_site1",
  "role": "CLIENT",
  "user_id": 2,
  "projects": [
    {
      "project_id": 2,
      "project_name": "Biomarker Model Validation for Cancer Prognosis",
      "datasources": [
        {
          "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json",
          "datasource_group_id": 1,
          "datasource_group_name": "MSKChord",
          "is_default_group": true
        }
      ]
    }
  ]
}
```

### `POST /user/datasource/apply`

`UserSettingsPage` sends changed datasource fields to this endpoint. The route accepts either `user_id` or `username`, validates each source, upserts datasource records, and returns the refreshed project datasource payload.

Request:

```json
{
  "user_id": 2,
  "updates": [
    {
      "project_id": 2,
      "datasource_group_id": 1,
      "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json"
    },
    {
      "project_id": 1,
      "datasource_group_id": null,
      "source": "https://example-fhir-server.test/fhir"
    }
  ]
}
```

Validation rules:

| Source type | Rule |
| --- | --- |
| FHIR server URL | Must be a valid `http://` or `https://` URL and must end with `/fhir` after trailing slashes are removed. |
| JSON datasource | Must end with `.json`. |

Response shape:

```json
{
  "user_id": 2,
  "updated_datasources": [],
  "projects": []
}
```

### `POST /user/model-files/list`

`UserSettingsPage` calls this endpoint to load the current user's model file source rows. The response is grouped by project and datasource group so the UI can show only the rows for the selected group.

Typical row shape:

```json
{
  "project_id": 2,
  "datasource_group_id": 1,
  "datasource_group_name": "MSKChord",
  "model_file_lookup_key": "cancer_type",
  "model_file_lookup_value": "Non-Small Cell Lung Cancer",
  "model_key": "logistic_reg",
  "artifact_type": "cutoff",
  "source": "/data/model_files/project_2/datasource_group_1/logistic_reg_Non-Small Cell Lung Cancer_cutoff.csv"
}
```

### `POST /user/model-files/apply`

`UserSettingsPage` sends changed model file source rows to this endpoint. The route stores initiator-local paths in `users_model_file_source_by_project`. These paths are not validated against the backend container filesystem because they are read later by the initiator/leader site during model upload.

Request:

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
      "artifact_type": "weights",
      "source": "/data/model_files/project_2/datasource_group_1/logistic_reg_Non-Small Cell Lung Cancer_weights.csv"
    }
  ]
}
```

The persisted `source` must be meaningful on the initiator/leader site's filesystem.

### `POST /clients/datasource/source`

The NVFlare server calls this endpoint when a client requests its datasource at job runtime. Clients do not call this endpoint directly.

Request:

```json
{
  "client_name": "site1",
  "project_id": 2,
  "datasource_group_id": 2
}
```

Non-local requests also include `$pw` for the backend internal secret check.

Response shape:

```json
{
  "status": "SUCCESS",
  "requested_client_name": "site1",
  "client_name": "site1",
  "username": "client_site1",
  "user_id": 2,
  "project_id": 2,
  "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json",
  "source_type": "json",
  "datasource_group": 1,
  "datasource_group_id": 1,
  "datasource_group_name": "MSKChord",
  "is_default_group": true,
  "datasource_record_id": 15
}
```

### `POST /projects/list`

`UserSettingsPage` uses this endpoint to load project metadata and datasource group definitions. If a project defines datasource groups, the settings page renders one editable datasource field per group. If a project has no datasource groups, the page renders one project-level datasource field.

### `POST /projects/fhir/source`

This endpoint remains available for resolving a user's project datasource by username/project/group and optionally executing a FHIR query when the source is a FHIR server. It is useful for validation, preview, and general project datasource lookup outside the NVFlare aux-request path.

## Datasource String Semantics

The string stored in `users_fhir_source_by_project.source` must be the value that runtime code can use.

| Environment | Biomarker JSON datasource values stored in backend | Why |
| --- | --- | --- |
| `LOCAL` | `/data/client/<filename>.json` | This is the path inside the running standalone client container after local JSON data is staged into the image. |
| `DEV` and non-local backend defaults | `/path/to/site1/fhir_data/...`, `/path/to/site2/fhir_data/...`, `/path/to/initiator/fhir_data/...` | These are the current development WorkSpaces/EC2 filesystem locations. |
| FHIR endpoint sources | `http://.../fhir` or `https://.../fhir` | The analytics engine treats non-JSON sources as FHIR server bases. |

Standalone `.env.local` datasource values are host-side staging paths used by client utilities to find local JSON files. They are not the same as the runtime values stored in backend for local execution.

Example local distinction:

```text
.env.local staging source:
nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json

backend LOCAL runtime source:
/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json
```

## Default Local and Dev Biomarker Sources

For local standalone backend seeding, biomarker datasource rows use container paths:

| Site | User | Group | Local backend source |
| --- | --- | --- | --- |
| `site1` | `client_site1` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json` |
| `site2` | `client_site2` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json` |
| `site3` | `initiator` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_training_bundle.json` |

The site-to-user mapping is:

| NVFlare site | Backend user |
| --- | --- |
| `site1` | `client_site1` |
| `site2` | `client_site2` |
| `site3` | `initiator` |

`site3` is the initiator site.

## Runtime Model File Resolution

Model file resolution follows the same user/project/datasource-group model as datasource resolution, but the file paths are interpreted by the initiator/leader site instead of by normal client sites.

```text
UserSettingsPage
  -> saves model file source rows in users_model_file_source_by_project

NVFlareJobStager
  -> selects rows for the submitted project, datasource group, model key, lookup value, and artifact type
  -> writes app_client/custom/model_file_sources.json
  -> inserts workflow_model_upload__<model_key> before model-consuming workflows

initiator / leader site
  -> receives task_model_upload
  -> reads model_file_sources.json
  -> opens the saved source paths on its own filesystem
  -> uploads open-access or encrypted artifacts

server aggregator
  -> writes runtime artifacts into app_server/custom

later workflows
  -> consume the uploaded artifacts from app_server/custom
```

The backend and the NVFlare server do not use the saved model-file `source` values as backend-local paths. This is intentional: model files are owned by the initiator site.

For encrypted Exceptional Response Discrimination, the encrypted model-upload flow writes encrypted model artifacts for scoring and also writes a minimal compatibility cutoff CSV containing the non-secret `ER_threshold` needed by `workflow_stat_analytics_meta_analysis__logistic_reg`. This preserves the downstream resolver contract without requiring the backend or server to read the original cutoff CSV.

### Model File Source Semantics

| Environment | Typical model file source value | Why |
| --- | --- | --- |
| `LOCAL` | `/data/model_files/project_2/datasource_group_1/...` | Path visible to the local initiator/leader container that performs `task_model_upload`. |
| `DEV` and non-local defaults | `/path/to/initiator/models/project_2/datasource_group_1/...` | Path visible to the initiator host/container in the current development deployment. |

Default filenames usually follow:

```text
{model_key}_{lookup_value}_{artifact_type}.csv
```

Examples:

```text
cox_lasso_Non-Small Cell Lung Cancer_weights.csv
cox_lasso_Non-Small Cell Lung Cancer_cutoff.csv
logistic_reg_Non-Small Cell Lung Cancer_weights.csv
logistic_reg_Non-Small Cell Lung Cancer_cutoff.csv
```

## Retired Config-File Runtime

The standalone client runtime no longer depends on these artifacts:

```text
DUALITY_FHIR_BASE_CONFIG.json
DUALITY_NVFLARE_FHIR_BASE_CONFIG
```

Local JSON files are still staged into client containers, but datasource selection is resolved through backend settings at job runtime. The staged local files land under:

```text
/data/client/
```
