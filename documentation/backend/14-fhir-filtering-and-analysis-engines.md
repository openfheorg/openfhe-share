# FHIR Filtering and Analysis Engines

## Runtime Datasource Resolver Behavior

`FHIRBaseConfigResolver` receives runtime datasource mappings from `analytics_executor.py` after the client obtains its datasource from the NVFlare server. The resolver can then answer downstream project/source lookups without a client-side config file.

Current priority for job runtime is:

1. Runtime mapping registered by the client for `project_id` and optional `datasource_group_id`.
2. Simulator datasource environment variables when simulator mode is active.
3. `DUALITY_NVFLARE_FHIR_BASE` fallback when no runtime or simulator mapping exists.

`DUALITY_NVFLARE_FHIR_BASE_CONFIG` is not required for standalone client job execution.

## Files Covered

| File | Role |
| --- | --- |
| `app/core/job_runner/nvflare_jobs/apis/FHIRBaseConfigResolver.py` | Resolves the FHIR server URL or local JSON bundle path used by generated NVFlare jobs. |
| `app/core/job_runner/nvflare_jobs/apis/utils.py` | Runtime analytics utility layer that loads the source, applies filters, and requests computation-specific DataFrames. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/fhir_project_config.py` | Locates project-specific FHIR config JSON files. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/fhir_patient_query_engine.py` | Builds and executes Patient search queries for FHIR server sources. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/fhir_observation_query_engine.py` | Builds and executes Observation queries for FHIR server sources. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/fhir_observation_data_engine.py` | Applies config-driven Observation filtering against local resource lists. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/fhir_analysis_query_engine.py` | Builds server-side fetch plans for analysis data needed by computation-specific extraction. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/fhir_analysis_data_engine.py` | Extracts computation columns from Patient, Observation, and MedicationStatement resources. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/filter_engine_config.py` | Main config-driven filtering and analysis extraction module used by analytics runtime code. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/biomarker_gene_columns.py` | Shared biomarker gene list and schema expansion helpers. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/config/` | Project-specific JSON schemas for patient filters, observation filters, and analysis extraction. |
| `app/api/routes/ProjectRoutes.py` | `/projects/fhir/source` endpoint that reports configured source metadata and can optionally test a FHIR query. |

## Runtime Source Modes

The analytics runtime supports two source modes:

| Source mode | Input shape | Runtime behavior |
| --- | --- | --- |
| Local JSON bundle | A `.json` file path that loads into a FHIR Bundle-like dictionary with `entry` resources. | The bundle is indexed in memory by patient ID. Patient, condition, observation, medication, and group resources are filtered locally. |
| FHIR server | An `http://` or `https://` base URL. | The runtime issues FHIR REST search requests using `requests`, follows pagination links, and fetches resources by subject IDs in batches. |

`app/core/job_runner/nvflare_jobs/apis/utils.py` chooses the runtime mode in `_load_stat_data_source(stat_data_path)`. A path ending in `.json` is loaded from disk and paired with `filter_engine_config`; an HTTP(S) value is treated as a FHIR server base URL and paired with the same filter engine. Any other value raises `ValueError`.

The backend API endpoint `/projects/fhir/source` also classifies configured user/project sources as `json` when the configured source string ends with `.json`; otherwise it reports `fhir_server`.

## FHIR Base Resolution

`FHIRBaseConfigResolver` is the runtime resolver used by generated NVFlare client and server code to determine the source path or server URL for a project.

### Environment Variables

| Variable | Use |
| --- | --- |
| `DUALITY_NVFLARE_FHIR_BASE` | Default source path or FHIR server URL when no config override applies. |
| `FL_IS_SIMULATOR` | Enables simulator-specific datasource path resolution when set to `1`, `true`, `yes`, or `on`. |
| `DUALITY_SIM_DATASOURCE_VERSION` | Version suffix for simulator datasource environment variables. Defaults to `2_1`. |
| `DUALITY_SIM_DATASOURCE_BASE` | Optional base directory for resolving relative simulator datasource paths. |
| `DUALITY_SERVER_DATASOURCE_<suffix>` | Simulator server datasource path when the runtime caller has no site name. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<suffix>` | Simulator client datasource path. Site names such as `site-1` are normalized to `SITE1`. |

### Config File Shapes

Project-level mapping:

```json
{
  "1": "C:/data/project_1_bundle.json",
  "2": "https://example-fhir-server.test/fhir"
}
```

Project plus datasource-group mapping:

```json
{
  "projects": {
    "1": {
      "1": "C:/data/project_1_default.json",
      "2": "C:/data/project_1_panel_split.json"
    }
  }
}
```

`get_base_for_project(project_id, site_name=None, datasource_group_id=None)` resolves runtime mappings registered by the client first. Simulator datasource environment variables are used for simulator runs, and `DUALITY_NVFLARE_FHIR_BASE` remains the fallback source value when no runtime or simulator mapping exists.

`get_project_for_base(fhir_base)` normalizes URLs and file paths and searches the configured mapping to infer a project ID from a source path or URL. `utils.py` uses this to pass `project_id` into the filter engine when possible.

## Project Config Resolution

`fhir_project_config.py` resolves JSON config files under `app/core/job_runner/nvflare_jobs/apis/fhir/config/`.

Resolution order:

1. Try import-resource paths for the current package.
2. Try filesystem paths next to `fhir_project_config.py`.
3. If `project_id` is missing, default it to project `1` for simulator support.
4. Search `config/project_<project_id>/<filename>`.
5. Search `config/<filename>`.
6. Raise `FileNotFoundError` with the full searched path list if no file exists.

Current project config files in this backend are:

| Project | File | Role |
| --- | --- | --- |
| `project_1` | `patient_query.json` | Patient search controls for gender, medication, birth date, and deceased date. |
| `project_1` | `observation_data.json` | Local observation-pass schema for genetic variant assessment, deletions, amplifications, duplications, regions, and mutation counts. |
| `project_1` | `analysis_data.json` | Computation-specific column extraction schema for Kaplan-Meier, mean, stdev, chi2, and t-test. |
| `project_2` | `patient_query.json` | Cancer type patient-data control with SNOMED-style codes and canonical display values. |

There is no `project_2/observation_data.json` or `project_2/analysis_data.json` in the current backend. Code paths that require those files for project 2 would raise `FileNotFoundError` unless a fallback `config/<filename>` exists.

## Filter Condition Shape

The filter engine accepts either a list of condition dictionaries or an object with a `conditions` list.

Typical condition fields used by the current code:

| Field | Use |
| --- | --- |
| `filter_type` | Logical group such as `PATIENT_QUERY`, `PATIENT_DATA`, `OBSERVATION_QUERY`, `OBSERVATION`, or `OBSERVATION_DATA`. |
| `column_name` | Backend column/control identifier such as `gender`, `birthDate`, `deceased_date`, `cancer_type`, `deletionRegions`, or `minTotal`. |
| `operator` | Operator matched against the config target, such as `=`, `BETWEEN`, `IN`, or `>=`. |
| `value` | Scalar value for select/number conditions. |
| `values` | Array value for range and multi-select conditions. |

The frontend config save targets use `filter_group` and `field`; `fhir_patient_query_engine.normalize_save_target()` normalizes those to `filter_type` and `column_name` when matching request conditions to controls.

## Patient Query Engine

`fhir_patient_query_engine.py` handles FHIR server Patient queries.

### Important Constants

| Constant | Value | Use |
| --- | --- | --- |
| `DEFAULT_TIMEOUT_SECONDS` | `180` | Timeout for FHIR HTTP GET calls. |
| `DEFAULT_BATCH_SIZE` | `50` | Batch size for subject ID chunks in related resource queries. |
| `DEFAULT_RESOURCE_PAGE_SIZE` | `2400` | `_count` value included in FHIR search requests. |
| `DEBUG` | `True` | Prints FHIR query debugging output. |

### Core Methods

| Method | Behavior |
| --- | --- |
| `resolve_server_url(bundle)` | Accepts either a URL string or a dictionary containing `server_url`; raises `ValueError` when no URL is available. |
| `session()` | Creates a `requests.Session` with `Accept` and `Content-Type` set to `application/fhir+json`. |
| `normalize_filters(filters)` | Converts either a list or an object with `conditions` into a list of condition dictionaries. |
| `bundle_entries_from_url()` | Executes a FHIR search, collects `entry[].resource`, follows `link[relation=next]`, and returns all resources. |
| `load_patient_filter_schema(project_id)` | Loads `patient_query.json` for the project and caches it by project key. |
| `build_patient_search_params(filters, project_id)` | Converts matching patient controls to FHIR search parameters. |
| `query_patients(filters, bundle, project_id)` | Runs the Patient search and returns a map keyed by Patient ID. |
| `query_patient_ids(filters, bundle, project_id)` | Returns only matching Patient IDs. |

### Current Query Control Support

The Patient query engine serializes these query kinds from `patient_query.json`:

| Query kind | FHIR parameter behavior |
| --- | --- |
| `search-param` | Emits `param=value`. Used by the `gender` control. |
| `date-range` | Emits two values for the same param using configured prefixes, usually `ge` and `le`. Used by birth date and death date controls. |
| `reverse-chain-token` | Emits `_has:<resource>:<referenceParam>:<param>=value`. Used by the medication control to search Patient by related MedicationStatement code. |

The server-side patient search always starts with `_count=2400`. It only emits a control parameter when a submitted condition matches the control's configured save target and has a non-empty value.

## Observation Query Engine

`fhir_observation_query_engine.py` handles FHIR server Observation queries and observation caching.

### Core Methods

| Method | Behavior |
| --- | --- |
| `load_observation_filter_schema(project_id)` | Loads `observation_data.json` for the project and caches it by project key. |
| `build_observation_search_params(filters, project_id)` | Builds Observation search parameters from configured observation controls. |
| `fetch_observations_prefiltered(server_url, subject_ids, params, project_id)` | Fetches observations for subject ID batches using FHIR search. |
| `get_cached_observations_by_patient(server_url, subject_ids, project_id)` | Retrieves or fetches observations and stores them in an in-memory cache. |
| `query_observations(filters, server_url, subject_ids, project_id)` | Runs observation search using filters and subject IDs. |
| `query_observations_by_patient(filters, server_url, subject_ids, project_id)` | Returns a patient-to-observations map. |
| `query_observation_patient_ids(filters, server_url, subject_ids, project_id)` | Returns patient IDs that have matching observations. |

The observation query path is used only for FHIR server sources. Local JSON sources use bundle indexing plus `fhir_observation_data_engine.py`.

## Observation Data Engine

`fhir_observation_data_engine.py` evaluates observation filters against local observation resources. It is also used after server-side observation fetches when `OBSERVATION` or `OBSERVATION_DATA` conditions need a local pass.

### Current Project 1 Observation Schema

`project_1/observation_data.json` defines:

| Schema section | Current contents |
| --- | --- |
| `localPass.observationModel.variantAssessmentCode` | Extracts a code using `component_or_text_code`; current value map recognizes `69548-6`. |
| `localPass.observationModel.positive` | Extracts positive/negative state using `interpretation_positive`. |
| `localPass.observationModel.changeType` | Extracts deletion, duplication, or amplification using LOINC component `48019-4`, value maps, and ID fallbacks. |
| `localPass.observationModel.region` | Extracts cytogenetic/genomic region using LOINC component `48013-7` or an ID regex fallback. |
| `localPass.patientMetrics.deletions` | Counts positive deletion observations for `69548-6`. |
| `localPass.patientMetrics.amplifications` | Counts positive amplification observations for `69548-6`. |
| `localPass.patientMetrics.duplications` | Counts positive duplication observations for `69548-6`. |
| `localPass.patientMetrics.total` | Sums deletions, amplifications, and duplications. |
| `localPass.patientMetrics.deletionRegionSet` | Builds the set of positive deletion regions. |
| `localPass.patientMetrics.amplificationRegionSet` | Builds the set of positive amplification regions. |
| `localPass.patientMetrics.variantAssessmentCodes` | Builds the set of observed variant assessment codes. |

Current controls include:

| Control ID | Label | Type | Save target |
| --- | --- | --- | --- |
| `variantAssessmentCode` | Genetic Variant Assessment Type | `select` | `OBSERVATION_DATA.variantAssessmentCode IN value` |
| `deletionRegions` | Deletion Regions | `multi-select-grid` | `OBSERVATION_DATA.deletionRegions IN value` |
| `amplificationRegions` | Amplification Regions | `multi-select-grid` | `OBSERVATION_DATA.amplificationRegions IN value` |
| `minDeletions` | Minimum Number of Deletions | `number` | `OBSERVATION_DATA.minDeletions >= value` |
| `minAmplifications` | Minimum Number of Amplifications | `number` | `OBSERVATION_DATA.minAmplifications >= value` |
| `minTotal` | Minimum Total Mutation Count | `number` | `OBSERVATION_DATA.minTotal >= value` |

### Local Pass Behavior

`FHIRObservationDataEngine.patient_satisfies_filters(observations, conditions)` works by:

1. Normalizing every observation through `localPass.observationModel`.
2. Building patient-level metrics from the normalized observations.
3. Selecting active conditions whose `filter_type` is `OBSERVATION` or `OBSERVATION_DATA`.
4. Matching each condition to a configured control through the control's `save.targets` entry.
5. Comparing the patient metric to the submitted value.
6. Returning `False` on the first failed condition and `True` when all active observation data conditions pass.

Unsupported or unmatched observation conditions are skipped by the data engine rather than treated as failures.

## Main Filter Engine

`filter_engine_config.py` is the runtime module used by analytics code for both filtering and computation-specific data extraction.

### Local Bundle Indexing

For local JSON bundles, `_index_local_bundle_resources()` indexes:

| Indexed object | Source resource type |
| --- | --- |
| `patients` | `Patient` resources by `Patient.id`. |
| `patient_obs` | `Observation` resources grouped by subject patient. |
| `patient_conditions` | `Condition` resources grouped by subject patient. |
| `patient_meds` | Medication tokens and display names from `MedicationStatement`. |
| `patient_med_statements` | Raw `MedicationStatement` resources grouped by subject patient. |
| `ref_to_pid` | `Patient/<id>` and `entry.fullUrl` references mapped back to patient IDs. |
| `groups` | Raw `Group` resources. |

Local bundle and local observation subsets are cached in module-level dictionaries. Cache keys include the project key, source signature, and subject ID signature.

### `apply_filters()` Flow

`apply_filters(filters, bundle, project_id=None)` returns a list of matching patient IDs.

Local JSON flow:

1. Normalize the incoming filters.
2. Build a cache key from project, bundle signature, and filter JSON.
3. Index the local bundle resources.
4. Start with all Patient IDs in the bundle.
5. Apply `PATIENT_QUERY` conditions locally for supported fields: `gender`, `birthDate`, and `medication`.
6. Apply `PATIENT_DATA` conditions locally for supported fields: `deceased_date` and `cancer_type`.
7. If observation conditions are present, retrieve cached local observations for the remaining patients.
8. Apply `OBSERVATION` or `OBSERVATION_DATA` conditions through `patient_satisfies_coded_observation_data_filters()`.
9. If only `OBSERVATION_QUERY` conditions are present, keep patients that have observations.
10. Sort the resulting patient IDs, store them in the apply-filters cache, and return them.

FHIR server flow:

1. Normalize the incoming filters.
2. Build a cache key from project, server URL, and filter JSON.
3. Query Patient resources through `query_patients()` for `PATIENT_QUERY`-style filters.
4. Apply `PATIENT_DATA` conditions locally against fetched Patient and Condition resources when required.
5. If observation conditions are present, query observations through `query_observations_by_patient()` or use cached observations by patient.
6. Apply `OBSERVATION` or `OBSERVATION_DATA` local observation data checks when present.
7. Return and cache the remaining patient IDs.

### Supported Local Patient Filters

| Filter type | Column | Local behavior |
| --- | --- | --- |
| `PATIENT_QUERY` | `gender` | Compares requested value to `Patient.gender`. |
| `PATIENT_QUERY` | `birthDate` | Requires two `values` and checks `Patient.birthDate` between them. |
| `PATIENT_QUERY` | `medication` | Checks medication display names and `system|code` tokens from MedicationStatement resources. |
| `PATIENT_DATA` | `deceased_date` | Requires two `values` and checks `deceasedDateTime` or `deceasedDate` between them. |
| `PATIENT_DATA` | `cancer_type` | Checks Condition code/display values against `patient_query.json` options plus the hardcoded cancer type display/code maps. |

### Cancer Type Mapping

`filter_engine_config.py` includes hardcoded cancer display and code maps used to align UI values, local bundle condition display text, and SNOMED-style codes for several cancer types. Examples include non-small cell lung cancer, breast carcinoma, glioma, colorectal cancer, pancreatic cancer, gastrointestinal stromal tumor, non-Hodgkin lymphoma, bladder cancer, esophagogastric carcinoma, biliary cancer, and melanoma.

`project_2/patient_query.json` is the current project config that exposes the cancer type control. Its save target currently uses the older key names `filter_type` and `column_name` rather than `filter_group` and `field`.

## Analysis Query Engine

`fhir_analysis_query_engine.py` supports FHIR server analysis extraction by building a fetch plan from `analysis_data.json`.

### Core Methods

| Method | Behavior |
| --- | --- |
| `load_analysis_query_schema(project_id)` | Loads `analysis_data.json`, expands query templates for biomarker gene columns, and caches by project key. |
| `build_analysis_fetch_plan(computation_type, workload_args, project_id)` | Determines which Patient, Observation, and MedicationStatement resources are needed for a computation. |
| `fetch_analysis_subject_context(server_url, subject_ids, computation_type, workload_args, project_id)` | Fetches required resources for subject IDs and returns patient, observation, and medication maps. |

The fetch plan avoids pulling every possible resource when the computation only needs a subset. It derives the needed resource types and search parameters from the computation type and selected workload columns.

## Analysis Data Engine

`fhir_analysis_data_engine.py` extracts values from fetched resources according to `analysis_data.json`.

### Core Methods

| Method | Behavior |
| --- | --- |
| `load_analysis_data_schema(project_id)` | Loads `analysis_data.json`, expands data templates for biomarker gene columns, and caches by project key. |
| `get_analysis_resource_requirements(computation_type, workload_args, project_id)` | Returns resource requirements for the selected computation/workload columns. |
| `get_analysis_value_for_property(computation_type, property_key, column_id, patient, observations, medications, project_id)` | Extracts one configured property value from the provided resources. |

### Current Extractors

| Extractor | Source | Behavior |
| --- | --- | --- |
| `patient_gender` | Patient | Returns `Patient.gender`. |
| `observation_value_string_by_code` | Observation | Finds an observation by code and returns a string value. |
| `observation_value_numeric_by_code` | Observation | Finds an observation by code and returns a numeric value. |
| `observation_component_quantity_by_parent_code_and_component_code` | Observation component | Finds a parent observation and component code, then returns a quantity value. |
| `observation_variant_value_by_parent_code_and_gene_code` | Observation component | Finds genetic variant observations by parent code and gene component code, returning allowed values such as `MUT` or `WT`. |
| `medication_names` | MedicationStatement | Returns medication display names. |

## Computation Extraction

`filter_engine_config.extract_data_for_computation_type()` delegates to `extract_data_for_computation()` and returns a pandas DataFrame for the requested computation.

| Computation type | DataFrame builder | Required workload args |
| --- | --- | --- |
| `kaplan-meier` | `extract_survivability_data()` | `group_col`/`group_column_id`, `time_col`/`time_column_id`, `censoring_col`/`censoring_column_id` |
| `kaplan-meier-time-censoring` | `extract_kaplan_meier_time_censoring_data()` | `time_col`/`time_column_id`, `censoring_col`/`censoring_column_id` |
| `biomarker-kaplan-meier` | `build_biomarker_km_dataframe()` | biomarker coefficients, cutoff value, biomarker covariates, group/time/censoring columns, epsilon |
| `biomarker-subjects` | `build_biomarker_subjects_dataframe()` | `biomarker_covariates` |
| `mean` | `extract_mean_data()` | `data_column_id` |
| `stdev` | `extract_stdev_data()` | `data_column_id` |
| `chi2` | `extract_chi2_data()` | `category_column_1_id`, `category_column_2_id` |
| `t-test` | `extract_ttest_data()` | `data_column_id`, `category_column_1_id` |

Unsupported computation types raise `ValueError`.

`utils.py` calls these extraction methods after applying filters. The pre-count path calls `apply_filters()` once to get subject IDs, then builds a computation-specific DataFrame for each workflow to calculate threshold-pass flags. Runtime statistical functions use the same pattern for mean, stdev, chi2, Kaplan-Meier, and t-test computations.

## Biomarker Extraction

`biomarker_gene_columns.py` defines the shared biomarker gene set used for schema expansion. Current genes include:

```text
ARID1A, ATM, BAP1, COL9A3, KDM5C, MTOR, NF2, PBRM1, PCK1, PIK3CA, PTEN, S100B, SETD2, SMARCA4, TCEB1, TP53, TRMT2B, TSC1, USP32, VHL, WNT8A, ZNF800
```

The module provides two expansion helpers:

| Helper | Behavior |
| --- | --- |
| `merge_biomarker_gene_columns_into_analysis_data_schema()` | Adds gene-specific data extraction column rules based on the `pbrm1` template. |
| `merge_biomarker_gene_columns_into_analysis_query_schema()` | Adds gene-specific query planning rules based on the `pbrm1` template. |

`filter_engine_config.py` also defines biomarker-specific extraction for PCA LOINC code `86206-0`, total tumor mutation burden LOINC code `94076-7`, cancer type, treatment windows, sequencing windows, event flags, gene features, and panel versions from Group resources.

`build_biomarker_subjects()` returns `BiomarkerSubject` objects. `build_biomarker_subjects_dataframe()` converts those subjects into covariate columns. `build_biomarker_km_dataframe()` computes risk scores from coefficient rows and a cutoff, then assigns `high_score` or `low_score` groups.

The current risk-score grouping logic computes `diff = risk_score - cutoff_value`; if `abs(diff) <= epsilon`, it sets the cleaned difference to `0.0`. The group is `high_score` only when the cleaned difference is greater than zero; otherwise it is `low_score`.

### Near-cutoff patient count

While assigning groups, the same pass counts patients whose `abs(diff)` is within `NEAR_CUTOFF_MARGIN` (`1e-5`) of the cutoff and stores that count on the returned frame as `df.attrs[NEAR_CUTOFF_ATTR]` (`biomarker_near_cutoff`). An empty result frame carries the attribute too.

A patient inside that band cannot be assigned to an arm reliably: the encrypted comparison resolves it on CKKS noise rather than on the model, so the clear and encrypted paths may legitimately disagree about that patient. Only this clear path can measure the band, because it alone knows the exact `score - cutoff`.

The count is diagnostic only. `attrs` is never serialized, nothing in the analytics chain reads it, and only a caller that deliberately looks for it — the simulator sweep's binning probe — sees it. Only the count is retained; a per-patient margin or score is never stored.

## `/projects/fhir/source`

`POST /projects/fhir/source` is the backend API endpoint that exposes configured datasource metadata to the frontend.

Request model:

```json
{
  "username": "alice",
  "project_id": 1,
  "datasource_group": 2,
  "execute_query": "Patient?_count=1"
}
```

`datasource_group` and `execute_query` are optional.

Response fields include:

| Field | Meaning |
| --- | --- |
| `username` | Request username. |
| `user_id` | Resolved backend user ID. |
| `project_id` | Request project ID. |
| `source` | Configured source path or FHIR server URL. |
| `source_type` | `json` for `.json` sources, otherwise `fhir_server`. |
| `datasource_group` | Datasource group ID from the assignment. |
| `datasource_group_name` | Datasource group display name. |
| `is_default_group` | Whether the assignment is the default datasource group. |
| `datasource_groups_defined` | Whether explicit datasource groups are defined for the project. |
| `datasource_groups` | Available datasource groups for the project. |
| `default_datasource_group` | Default datasource group metadata. |

When `execute_query` is provided for a JSON source, the endpoint skips execution and returns `query_executed: false` plus a message. When `execute_query` is provided for a FHIR server source, the endpoint joins the source base URL and query path, performs a GET with `Accept: application/fhir+json, application/json`, records `query_status_code`, and returns either parsed JSON or raw text.

Error behavior:

| Case | Status | Response |
| --- | --- | --- |
| Username does not resolve | `404` | `{"message": "User not found for username [...]"}` |
| No source assignment exists | `404` | `{"message": "No FHIR source found for username [...] project_id [...] and datasource_group [...]"}` |
| Upstream FHIR query fails at HTTP/request level | Not explicitly caught in this route | The exception propagates to FastAPI's default error handling. |
| Upstream response is not JSON | `200` from backend if request itself succeeds | `query_results` contains response text. |

## Generated NVFlare Runtime Usage

The generated NVFlare job runtime uses this layer from both client and server custom code.

| Runtime file | Use |
| --- | --- |
| `jobs/nvflare_job_template/app_client/custom/analytics_executor.py` | Resolves the client datasource using `FHIRBaseConfigResolver.get_base_for_project(project_id, site_name=client_name, datasource_group_id=...)`, loads filters, and runs local analytics preprocessing. |
| `jobs/nvflare_job_template/app_server/custom/analytics_aggregator.py` | Resolves the server datasource with `site_name=None` when the server is a data owner and can participate in threshold/pre-count processing. |
| `apis/utils.py` | Loads the resolved source, applies filters, builds computation-specific DataFrames, and performs statistical helper operations. |

The selected project and datasource group come from the packaged `filters.json` project metadata generated during job staging. The runtime resolver uses that metadata to select the correct source for the client or server.

## Caching Behavior

| Cache | Scope | Key inputs |
| --- | --- | --- |
| Patient filter schema cache | Module-level | Project key. |
| Observation data schema cache | Module-level | Project key. |
| Analysis data/query schema cache | Module-level | Project key. |
| Local bundle resource cache | Module-level | Project key plus SHA-256 signature of the local bundle payload. |
| Local observation subset cache | Module-level | Project key, bundle key, and subject ID signature. |
| Server observation cache | Module-level in observation query engine | Server URL, project key, and subject IDs. |
| Apply-filters cache | Module-level | Project key, source key, and filter JSON signature. |

These caches are process-local. They do not persist across container restarts or separate NVFlare process executions.

## Error Handling and Edge Cases

| Area | Current behavior |
| --- | --- |
| Missing source value | `resolve_server_url()` raises `ValueError`; `utils._load_stat_data_source()` raises `ValueError` for unsupported paths. |
| Missing local JSON file | `utils._load_stat_data_source()` raises `FileNotFoundError`. |
| Invalid local JSON file | `utils._load_stat_data_source()` raises `IOError` for JSON read failures. |
| Missing project config file | `resolve_project_config_path()` raises `FileNotFoundError` with searched paths. |
| Malformed config root | Config loaders raise `ValueError` when the loaded JSON is not an object. |
| FHIR server HTTP error | `http_get_json()` calls `raise_for_status()`, so the HTTP exception propagates. |
| Non-object FHIR JSON response | `http_get_json()` raises `ValueError`. |
| Unsupported computation type | `extract_data_for_computation()` raises `ValueError`. |
| Missing required Kaplan-Meier columns | Extraction functions raise `ValueError` when group/time/censoring columns are missing. |
| Empty result sets | Extraction functions return empty DataFrames with the expected columns where supported. |
| Unmatched observation controls | The observation data engine skips unmatched conditions. |

## Current Design Boundaries

- `filter_engine_config.py` is the active config-driven filter and extraction implementation used by `utils.py`.
- The same filter engine handles both `.json` bundle paths and HTTP(S) FHIR server URLs.
- Patient query configuration is project-specific through `patient_query.json`.
- Observation local-pass configuration is project-specific through `observation_data.json` where that file exists.
- Analysis extraction configuration is project-specific through `analysis_data.json` where that file exists.
- FHIR server mode still performs local post-filtering for `PATIENT_DATA` and `OBSERVATION_DATA` conditions after fetching the needed FHIR resources.
- Local JSON mode avoids FHIR HTTP queries entirely and filters against indexed bundle resources.
