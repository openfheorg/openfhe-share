# NVFlare Job Packaging and Templates

## Files and Directories Covered

| Path | Role |
| --- | --- |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Active backend staging logic that builds a generated NVFlare job directory from a template. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobRunner.py` | Submits the generated job directory through the NVFlare admin kit. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobUploader.py` | Deprecated uploader implementation. Current staging/submission uses local job directories and `NVFlareJobRunner`. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobMonitor.py` | Monitors submitted NVFlare jobs after packaging and submission. |
| `app/core/job_runner/nvflare_jobs/jobs/configs/` | Example/static function configuration JSON files used as reference inputs. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/` | Main NVFlare job template copied for normal analytical jobs. |
| `app/core/job_runner/nvflare_jobs/jobs/participation_confirmation/` | Separate NVFlare job template copied for participation confirmation jobs. |
| `app/core/job_runner/nvflare_jobs/apis/` | Runtime Python modules packaged into the NVFlare job wheel and referenced by generated job config. |
| `app/core/job_runner/nvflare_jobs/workflows/` | Custom workflow code referenced by generated server config. |
| `app/core/job_runner/nvflare_jobs/scripts/` | Simulator, parser, result-generation, profiling, and helper scripts. |
| `app/core/job_runner/nvflare_jobs/wheels/` | `APIWheelBuilderCI.py` and CI wheel packaging support for the published `duality_nvflare_lib` package. |
| `app/core/job_runner/nvflare_jobs/docs/` | Supporting NVFlare, workflow, profiling, and sequence documentation. |

## Packaging Model

The backend packages NVFlare jobs by copying an on-disk template directory into a generated local job directory, then patching selected files in that generated copy.

The active staging class is `NVFlareJobStager`. It does not modify the source template in place. It builds the generated job under:

```text
/tmp/nvflare_jobs/jobs/{job_template_name}
```

For the default job template, the generated path is:

```text
/tmp/nvflare_jobs/jobs/nvflare_job_template
```

For participation confirmation jobs, the generated path is:

```text
/tmp/nvflare_jobs/jobs/participation_confirmation
```

Before writing a generated job, `_build_local_job_dir()` deletes the existing generated directory for the same template with `shutil.rmtree(job_dir)` and recreates it. This keeps stale generated files from previous runs out of the next submission for that template name.

## Template Selection

`NVFlareJobStager.__init__()` accepts `job_template_name`.

If no template name is supplied, it uses:

```text
nvflare_job_template
```

The participation flow uses the separate template name corresponding to the `SupportedFunction.PARTICIPATION_CONFIRMATION` value.

Template directories are resolved under:

```text
app/core/job_runner/nvflare_jobs/jobs/{job_template_name}
```

If the selected template directory does not exist, `_build_local_job_dir()` raises `FileNotFoundError`.

## Main Job Template

The main template is:

```text
app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/
```

It contains the client app, server app, and default `meta.json` used as the source copy for analytical NVFlare jobs.

| Template Path | Purpose |
| --- | --- |
| `meta.json` | Static template metadata. The generated job overwrites this file with the selected client deploy map. |
| `app_client/config/config_fed_client.json` | Client-side NVFlare config. Includes `AnalyticsExecutor`, profiler, progress sender, event conversion, and TensorBoard writer components. |
| `app_client/config/log_config.json` | Client logging configuration copied unchanged. |
| `app_client/custom/analytics_executor.py` | Client executor code copied into the generated job. |
| `app_client/custom/requirements.txt` | Client runtime requirements copied unchanged. |
| `app_client/custom/__init__.py` | Client custom package marker copied unchanged. |
| `app_server/config/config_fed_server.json` | Server-side NVFlare config. This is the main generated file patched by `NVFlareJobStager`. |
| `app_server/config/log_config.json` | Server logging configuration copied unchanged. |
| `app_server/config/README.txt` | Server config note copied unchanged. |
| `app_server/custom/analytics_aggregator.py` | Server aggregator code copied into the generated job. |
| `app_server/custom/analytics_persistor.py` | Server persistor code copied into the generated job. |
| `app_server/custom/backend_webhook_receiver.py` | Server webhook receiver for backend progress events. |
| `app_server/custom/backend_webhook_writer.py` | Server webhook writer for backend progress events. |
| `app_server/custom/global_schema.json` | Global schema used by analytics and by staging logic for some OpenFHE parameter calculations. |
| `app_server/custom/sm.py` | Server-side support module copied unchanged. |
| `app_server/custom/__init__.py` | Server custom package marker copied unchanged. |

## Participation Confirmation Template

The participation confirmation template is:

```text
app/core/job_runner/nvflare_jobs/jobs/participation_confirmation/
```

It is separate from the analytical job template and contains only the files required to ask selected clients to confirm participation.

| Template Path | Purpose |
| --- | --- |
| `app_client/config/config_fed_client.json` | Client config for participation confirmation. |
| `app_client/custom/executor.py` | Client executor for participation response behavior. |
| `app_client/custom/__init__.py` | Client custom package marker copied unchanged. |
| `app_server/config/config_fed_server.json` | Server config for participation confirmation. |
| `app_server/custom/response_aggregator.py` | Server aggregator for participation responses. |
| `app_server/custom/sm.py` | Server-side support module copied unchanged. |
| `app_server/custom/__init__.py` | Server custom package marker copied unchanged. |

## Generated Job Directory Build

`NVFlareJobStager.stage_job()` calls `_build_local_job_dir(job_template)` and returns the generated path as a string.

The build sequence is:

1. Resolve the selected template path under `app/core/job_runner/nvflare_jobs/jobs/`.
2. Resolve the generated job path under `/tmp/nvflare_jobs/jobs/`.
3. Delete the generated job directory if it already exists.
4. Recreate the generated job directory.
5. Copy all non-bytecode files from the template to the generated job directory.
6. Write `app_client/custom/model_file_sources.json` when selected model workflows need initiator-supplied model files.
7. Insert model-upload workflows before model-consuming workflows.
8. Parse the selected participating clients CSV into a client list.
9. Patch `app_server/config/config_fed_server.json` when applicable.
10. Build the generated `filters.json` payload.
11. Write `filters.json` to both `app_client/custom/filters.json` and `app_server/custom/filters.json` when payload data exists.
12. Overwrite generated `meta.json` with the selected client deploy map.
13. Log staging completion with `JobRunnerStatus.JOB_UPLOAD`.

## Files Copied Without Direct Stager Mutation

`_copytree()` recursively copies all files from the source template into the generated job directory, excluding `.pyc` and `.pyo` files.

The following template files are copied before any generated patches are applied:

| Source Template Path | Generated Path |
| --- | --- |
| `jobs/{template}/meta.json` | `/tmp/nvflare_jobs/jobs/{template}/meta.json` |
| `jobs/{template}/app_client/config/*` | `/tmp/nvflare_jobs/jobs/{template}/app_client/config/*` |
| `jobs/{template}/app_client/custom/*` | `/tmp/nvflare_jobs/jobs/{template}/app_client/custom/*` |
| `jobs/{template}/app_server/config/*` | `/tmp/nvflare_jobs/jobs/{template}/app_server/config/*` |
| `jobs/{template}/app_server/custom/*` | `/tmp/nvflare_jobs/jobs/{template}/app_server/custom/*` |

After the copy, `NVFlareJobStager` may overwrite or add generated files in the copied directory.

## Generated or Patched Files

| Generated Job File | Source | Current Behavior |
| --- | --- | --- |
| `meta.json` | Generated by `_build_local_job_dir()` | Overwrites the template `meta.json` with selected clients, `min_clients`, `deploy_map`, `job_name`, and lowercased `name`. |
| `app_server/config/config_fed_server.json` | Copied from template, patched by `_update_server_config_text()` | Updates server timing, workflow `min_clients`, workflow wait/check settings, analytics workflows, threshold workflow, encrypted biomarker workflow, and persistor OpenFHE args. |
| `app_client/custom/filters.json` | Generated by `_build_local_job_dir()` | Written when filters, function map, threshold config, or project data exists. |
| `app_server/custom/filters.json` | Generated by `_build_local_job_dir()` | Same payload as client `filters.json`. Used by server aggregator/persistor logic. |
| `app_client/custom/model_file_sources.json` | Generated by `_build_local_job_dir()` | Written when selected model workflows require initiator-supplied model files. Contains initiator-local source paths, not backend-readable paths. |
| `app_server/custom/{model_key}_{Cancer}_cutoff.csv` | Written at runtime by model-upload aggregation when needed | Compatibility artifact for downstream LCS meta-analysis. For encrypted LCS it contains only threshold metadata needed by the later workflow. |
| Runtime encrypted/plaintext model artifacts under `app_server/custom/` | Uploaded by `workflow_model_upload__<model_key>` | Created after the job starts. The backend stager does not pre-copy these files. |

## `meta.json` Generation

The generated `meta.json` is built from the parsed participating clients list.

The generated shape is:

```json
{
  "name": "nvflare_job_template",
  "resource_spec": {},
  "min_clients": 1,
  "deploy_map": {
    "app_client": ["site-1"],
    "app_server": ["server"]
  },
  "job_name": "nvflare_job_template"
}
```

`name` is the lowercased template name. `job_name` is the template name. `min_clients` is `max(1, len(parsed_clients))`. `deploy_map.app_client` is the parsed participating client list. `deploy_map.app_server` is always `['server']`.

Client parsing is handled by `_parse_clients()`. It treats commas as separators and supports backslash escaping for commas inside client identifiers.

## Server Config Patching

`app_server/config/config_fed_server.json` is patched by `_update_server_config_text()`.

Before parsing JSON, `_update_server_config_text()` removes block comments and line comments from the raw text. If JSON parsing fails or the parsed object does not contain a `workflows` list, the method returns `None` and the template config is left unchanged.

When patching succeeds, the stager writes formatted JSON back to the generated server config file.

Current server-level patches:

| Field | Generated Value |
| --- | --- |
| `server.heart_beat_timeout` | `120` |
| `server.task_request_interval` | `0.5` |

Current workflow-level patches applied to existing workflows:

| Field | Generated Value |
| --- | --- |
| `args.min_clients` | Parsed client count, with minimum `1`. |
| `args.wait_time_after_min_received` | `0` (moot once `min_clients` = all clients; trims per-round grace latency) |
| `args.task_check_period` | `0.1` |
| encrypted biomarker workflow `args.train_timeout` | `600` when the existing value is `0`. |

## Function Map Packaging

`NVFlareJobStager` receives `functions_map` from the job submission path. The constructor normalizes it into this shape:

```text
Dict[str, List[Dict[str, str]]]
```

Function names are uppercased. A single dict value is wrapped into a one-element list. Non-dict/non-list config values are ignored.

During server config patching, `_build_stat_analytics_workflows()` uses the existing `workflow_stat_analytics_template` workflow in `config_fed_server.json` as a base template. It removes that template workflow from the final workflow list and replaces it with generated stat analytics workflows.

For each function config:

1. Start with workload defaults from the template workflow.
2. Merge the submitted function config.
3. Resolve `computation_type` from the config or `FUNCTION_TO_COMPUTATION_TYPE`.
4. Ensure `global_schema` defaults to `global_schema.json`.
5. Coerce submitted workload args to the supported property types defined for the function.
6. Apply allowed custom configuration variables into the staged filter object when matching filter column names exist.
7. Create a copied workflow with `train_task_name` set to `task_stat_analytics`.
8. Set workflow `min_clients` to the parsed client count.
9. Set generated workflow `workload_args`.
10. Record the generated workflow ID through `NVFlareJobsManager.ensure_and_set_workflow_for_function_config()` when a manager is available.

For regular analytics workflows, generated workflow IDs use:

```text
workflow_stat_analytics_1
workflow_stat_analytics_2
workflow_stat_analytics_3
```

If a generated ID collides with an existing workflow ID, `_get_unique_workflow_id()` appends an incrementing suffix such as `_2` to avoid duplicate IDs.

## Workflow Group Model Expansion

Workflow group selections are passed into the stager as `workflow_group_data`.

The current selected modeling method list is read from:

```text
workflow_group_data["predictive_modeling_method_ids"]["selected_values"]
```

The selected values are normalized into a unique ordered list of non-empty strings.

When a function config has `is_biomarker_discovery` set to `true` or `1`, selected modeling methods expand that single config into one config per selected model key. The expanded configs receive:

```text
model_key = {selected_model_key}
```

The same expansion is applied to project function metadata inside the generated `filters.json` payload so the runtime project configuration matches the generated workflows.

For biomarker discovery stat workflows, generated workflow IDs use the selected model key directly:

```text
workflow_stat_analytics__cox_lasso
workflow_stat_analytics__logistic_reg
```

This double-underscore pattern is intentional for model-specific stat analytics workflows.

## Threshold Workflow Packaging

When a threshold is present and functions are selected, `_insert_threshold_workflow()` inserts a threshold workflow into the generated server config.

The threshold workflow is skipped for the participation confirmation template.

Threshold workflow template selection:

| Threshold Method | Workflow Template ID |
| --- | --- |
| `ThresholdMethod.PROTECTED` | `workflow_threshold_samples_secure` |
| Other threshold methods | `workflow_threshold_samples_unsecure` |

The generated threshold workflow receives:

| Field | Value |
| --- | --- |
| `args.min_clients` | Parsed client count. |
| `args.workload_args.min_global_samples` | `int(threshold.threshold)` when conversion succeeds. |
| `args.workload_args.workflows` | Map of generated stat workflow IDs to their workload args. |

The threshold workflow is inserted immediately after the first keygen workflow when a keygen workflow is present. If no keygen workflow is present, it is appended to the end of the workflow list.

## Encrypted Biomarker Workflow Packaging

`_insert_enc_biomarker_disc_workflow()` inserts an encrypted biomarker discovery workflow when the selected function configs include a model with `model_type` equal to the encrypted model type.

The inserted workflow is based on `ENC_BIOMARKER_DISC_WORKFLOW_TEMPLATE`.

Default encrypted biomarker workflow characteristics:

| Field | Value |
| --- | --- |
| `id` | `workflow_enc_biomarker_disc_1` |
| `path` | `workflow_runtime.customSAG` (in-job wrapper around `duality_nvflare_workflows.customSAG.customSAG`) |
| `train_task_name` | `task_enc_biomarker_disc` |
| `train_timeout` | `600` |
| `workload_args.computation_type` | `biomarker_enc_risk_group_computation` |
| `workload_args.global_schema` | `global_schema.json` |

The stager does not insert a duplicate encrypted biomarker workflow if one is already present in the workflow list.

When inserted, the workflow is placed before the first Kaplan-Meier workflow. The stager also copies the submitted cancer type and selected model keys into the encrypted biomarker workflow workload args when available.

## OpenFHE and Persistor Argument Packaging

`_update_persistor_openfhe_args()` updates the `persistor` component in `app_server/config/config_fed_server.json` for non-participation jobs.

Current participation/client exclusion args written to the persistor:

| Persistor Arg | Source |
| --- | --- |
| `non_contributing_clients` | `NVFlareJobStager.non_contributing_clients` |
| `exclude_analyzing_clients` | `NVFlareJobStager.exclude_analyzing_clients` |

Current server data ownership overrides:

| Persistor Arg | Generated Value |
| --- | --- |
| `is_server_data_owner` | `false` |
| `is_server_contributing_to_aggregation` | `false` |

OpenFHE parameter generation is driven by selected computations, threshold method, encrypted model usage, and the number of data owners. The stager updates:

| Persistor Arg | Behavior |
| --- | --- |
| `mult_depth` | Set to the ceiling of the required multiplication depth. |
| `generate_mult_keys` | Enabled when selected computations require multiplication keys. |
| `generate_index_keys` | Enabled when selected computations or encrypted model workflow require index keys. |
| `generate_sum_keys` | Enabled when selected computations require sum keys. |
| `indices` | Set to selected required indices, or the encrypted biomarker index list when encrypted model handling applies. |

For encrypted biomarker workflows, index-key generation uses:

```text
[1, 2, 4, 8, 16, 32, 64, 128, 256, -511]
```

The default encrypted biomarker index key generation flag is `true`.

## Biomarker Model File Source Packaging

Biomarker model files are not copied by backend staging. The backend stores model-file locations as initiator User Settings and stages only the source metadata needed by the runtime upload workflow.

The staged metadata file is:

```text
app_client/custom/model_file_sources.json
```

It contains selected source rows for the initiator user, including project, datasource group, lookup key/value, model key, artifact type, and source path. The source path is meaningful to the initiator/leader site. The backend and NVFlare server should not assume they can open that path.

The normal runtime flow is:

1. `workflow_model_upload__<model_key>` is inserted before the model-consuming workflow.
2. The initiator/leader site receives `task_model_upload`.
3. The initiator reads the source paths from `model_file_sources.json` on its own filesystem.
4. The initiator uploads the required model artifacts.
5. The server aggregator writes runtime artifacts into `app_server/custom`.
6. Later workflows read from `app_server/custom`.

For encrypted Exceptional Response Discrimination, the uploaded encrypted cutoff artifact is used for encrypted scoring, while the non-secret `ER_threshold` from the initiator cutoff CSV is written into a small compatibility cutoff CSV for the later meta-analysis resolver.

If an expected model source path is invalid, the runtime model-upload workflow fails on the initiator/leader site. Backend staging does not open model files.

## `filters.json` Packaging

The generated `filters.json` payload is built in `_build_local_job_dir()`.

The payload can include:

| Key | Source |
| --- | --- |
| Existing filter data | `MySQLRetriever.stage_filters_by_id(filters_id)` when a filter ID is supplied and resolves successfully. |
| `functions_map` | Expanded model-specific function map when workflow model selections apply, otherwise normalized submitted function map. |
| `threshold_config` | Threshold ID, method, and numeric threshold value when a threshold object is present. |
| `project` | JSON-encoded project metadata from `ProjectsManager.get_project(project_id, datasource_group_id=...)`. |

When model-selection expansion applies, the generated `project.functions` array is also expanded so project metadata contains one biomarker function entry per selected model key.

The same JSON payload is written to:

```text
app_client/custom/filters.json
app_server/custom/filters.json
```

No `filters.json` file is written when the payload is empty.

## Datasource Group Effects

`datasource_group_id` affects packaging in two places:

1. `ProjectsManager.get_project(project_id, datasource_group_id=...)` resolves project metadata using the selected datasource group context.
2. Model file source records are selected from the initiator user settings for the submitted project and datasource group.

The datasource group ID is not written as a standalone top-level generated file. It is represented through selected project metadata and through the selected biomarker model asset directory.

## Client Participation Effects

Client participation affects packaging through three inputs:

| Input | Packaging Effect |
| --- | --- |
| `clients_list` | Parsed into `meta.json.deploy_map.app_client` and used to calculate `min_clients`. |
| `non_contributing_clients` | Written into server persistor args for non-participation jobs. |
| `exclude_analyzing_clients` | Written into server persistor args for non-participation jobs. |

`non_contributing_clients` and `exclude_analyzing_clients` are normalized to unique, non-empty strings before packaging.

## Runtime Library and Workflow References

The generated NVFlare job carries only job-specific template code and small runtime bootstrap wrappers. Shared API and workflow code is distributed as the published `duality_nvflare_lib` wheel.

The wheel contains the packages built from:

```text
app/core/job_runner/nvflare_jobs/apis/      -> duality_nvflare_apis
app/core/job_runner/nvflare_jobs/workflows/ -> duality_nvflare_workflows
```

The main analytical job template avoids direct config references to `duality_nvflare_apis` and `duality_nvflare_workflows`. NVFlare loads local wrapper modules first. In the public branch those wrappers require the already-installed local snapshot wheel and then import the wheel-backed implementation; they never contact a package registry.

Current template/runtime routing:

| Config Reference | Runtime Area | Behavior |
| --- | --- | --- |
| `analytics_executor.AnalyticsExecutor` | `app_client/custom/analytics_executor.py` | Client shim. Ensures the wheel is current, then loads `analytics_executor_impl.AnalyticsExecutor`. |
| `analytics_aggregator.AnalyticsAggregator` | `app_server/custom/analytics_aggregator.py` | Server shim. Ensures the wheel is current, then loads `analytics_aggregator_impl.AnalyticsAggregator`. |
| `analytics_persistor.AnalyticsPersistor` | `app_server/custom/analytics_persistor.py` | Server shim. Ensures the wheel is current, then loads `analytics_persistor_impl.AnalyticsPersistor`. |
| `profiler_runtime.Profiler` | `app_client/custom/profiler_runtime.py` and `app_server/custom/profiler_runtime.py` | Wrapper around `duality_nvflare_apis.profiler.Profiler`. |
| `profiler_runtime.ProfileSummaryPersistor` | `app_server/custom/profiler_runtime.py` | Wrapper around `duality_nvflare_apis.profiler.ProfileSummaryPersistor`. |
| `profiler_runtime.ProfileSummaryAggregator` | `app_server/custom/profiler_runtime.py` | Wrapper around `duality_nvflare_apis.profiler.ProfileSummaryAggregator`. |
| `workflow_runtime.customSAG` | `app_server/custom/workflow_runtime.py` | Wrapper around `duality_nvflare_workflows.customSAG.customSAG`. |
| `backend_webhook_writer.BackendWebhookWriter` | `app_server/custom/backend_webhook_writer.py` | Job-bundled backend progress writer. |
| `backend_webhook_receiver.BackendWebhookReceiver` | `app_server/custom/backend_webhook_receiver.py` | Job-bundled backend progress receiver. |

`app_client/custom/duality_wheel_runtime.py` and
`app_server/custom/duality_wheel_runtime.py` are local-only guards. They check that
`duality_nvflare_lib` is already installed and then import the implementation. They do
not run `pip`, query GitLab, or replace the installed wheel.

The package name can still be overridden with `DUALITY_NVFLARE_LIB_PACKAGE`, but the
public runtime has no package-index/update configuration. Standalone and simulator
launchers install the committed snapshot wheel locally before NVFlare job code starts.

The stager does not rebuild the wheel during job staging. It stages templates, generated config, filters, metadata, and model CSV assets only.

### Building the Public Snapshot Wheel

The wheel is built with `APIWheelBuilderCI.py`. The public branch uses the static
PEP-440 snapshot version `0+phase1.snapshot` and consumes the wheel locally rather than
publishing/re-resolving it at job startup.

```bash
python3 backend/app/core/job_runner/nvflare_jobs/wheels/APIWheelBuilderCI.py
```

The release artifact used by standalone is committed as:

```text
standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
```

When `apis/` or `workflows/` changes, rebuild that snapshot and test it before updating
the public branch.

## Submission Boundary

`NVFlareJobStager` stops after creating the generated job directory and logging `JobRunnerStatus.JOB_UPLOAD`.

Submission is handled by `NVFlareJobRunner.run_job()`.

`NVFlareJobRunner` submits the staged path through the NVFlare admin kit with:

```text
submit_job {absolute_generated_job_path}
```

It parses the assigned NVFlare job ID from the admin output and returns:

```text
(job_id, server_jobs_folder)
```

The server-side output path is calculated from:

```text
nvflare_provision.client_to_server_job_save_location/{job_id}
```

## Deprecated Uploader

`NVFlareJobUploader.py` is marked as deprecated in the file itself. The previous implementation contains commented-out logic for zip creation, SSH upload, remote unzip, and remote cleanup. Current active packaging behavior is handled by `NVFlareJobStager`, and current submission behavior is handled by `NVFlareJobRunner`.

## Current Packaging Failure Modes

| Failure | Behavior |
| --- | --- |
| Template directory does not exist | `_build_local_job_dir()` raises `FileNotFoundError`. |
| Expected model source is missing or unreadable on initiator | `workflow_model_upload__<model_key>` fails when the initiator/leader site resolves its saved path. |
| Server config cannot be parsed or does not contain `workflows` | Server config patch returns `None`; template server config is left unchanged. |
| Exception while patching server config | Exception is printed and re-raised. |
| No filters/functions/threshold/project payload exists | `filters.json` is not written. |
| No stat analytics template workflow exists | Function workflow generation is skipped and existing workflows are left as-is. |
| No stat workflows exist when thresholding is requested | Threshold workflow insertion is skipped. |
| No Kaplan-Meier workflow exists when encrypted biomarker insertion is requested | Encrypted biomarker workflow insertion is skipped. |

## Safe Packaging Change Guidance

When changing job packaging behavior:

1. Treat `jobs/nvflare_job_template/` and `jobs/participation_confirmation/` as source templates.
2. Make generated job changes in `NVFlareJobStager`, not by mutating template files during runtime.
3. Keep generated files under `/tmp/nvflare_jobs/jobs/{template}`.
4. Keep `meta.json.deploy_map` generation aligned with the selected participating clients.
5. Preserve the model-specific workflow ID pattern `workflow_stat_analytics__{model_key}` for predictive modeling workflows.
6. Preserve `filters.json` symmetry between client and server unless the runtime code is changed to expect different payloads.
7. Keep saved model file source paths aligned to the selected project, datasource group, model key, lookup value, and artifact type. Default filenames follow `{model_key}_{lookup_value}_{artifact_type}.csv`.
8. Keep OpenFHE persistor args synchronized with any new computation type that requires different key/depth behavior.
9. Do not rely on `NVFlareJobUploader.py` for current runtime packaging unless it is intentionally revived and re-integrated.


## Runtime Datasource Request Receiver

The server job template includes `app_server/custom/datasource_request_receiver.py` and registers it in `app_server/config/config_fed_server.json` as `datasource_request_receiver`.

The receiver registers an aux message handler for:

```text
duality.datasource.lookup
```

Clients use that topic to request the datasource for their site/project/datasource-group context. The receiver calls backend `POST /clients/datasource/source` and returns the resolved source to the requesting client.

The client app no longer requires a staged `DUALITY_FHIR_BASE_CONFIG.json` file. `app_client/custom/analytics_executor.py` reads `custom/filters.json`, requests datasource from the server before data tasks, and assigns `analytics_manager.stat_data_path` from the server reply.
