# Biomarker and Analytics Workflows

## Files Covered

| File/Directory | Role |
| --- | --- |
| `app/core/job_runner/nvflare_jobs/apis/stat_analytics.py` | Main statistical analytics manager used by packaged NVFlare jobs. Handles workload metadata, local preprocessing, aggregation reference logic, encrypted postprocessing, Kaplan-Meier processing, and biomarker-specific risk group computation. |
| `app/core/job_runner/nvflare_jobs/apis/stat_analytics_event_type.py` | Application-defined profiling/event constants for statistical analytics, encrypted analytics, PQC payload handling, and profile-summary consolidation. |
| `app/core/job_runner/nvflare_jobs/apis/profiler.py` | Runtime profiling/event capture utilities used by the NVFlare job runtime. |
| `app/core/job_runner/nvflare_jobs/apis/observation_snapshot.py` | Utility for building a merged Observation snapshot from FHIR JSON files or directories. |
| `app/core/job_runner/nvflare_jobs/apis/utils.py` | Shared local preprocessing/postprocessing utilities for mean, standard deviation, chi-square, Kaplan-Meier, t-test, and biomarker records. |
| `app/core/job_runner/nvflare_jobs/apis/fhir/` | FHIR and local-data query/filter engines used by analytics workflows. |
| `app/core/job_runner/nvflare_jobs/apis/FHIRBaseConfigResolver.py` | Resolves the FHIR/local data source base path passed into the packaged analytics runtime. |
| `app/core/job_runner/nvflare_jobs/apis/HEExecutor.py` | Base encrypted executor used by `AnalyticsExecutor`. |
| `app/core/job_runner/nvflare_jobs/apis/HEAggregator.py` | Base encrypted aggregation behavior used by the server-side analytics aggregator. |
| `app/core/job_runner/nvflare_jobs/apis/HEPersistor.py` | Base encrypted persistor behavior used by the server-side analytics persistor. |
| `app/core/job_runner/nvflare_jobs/apis/openfhe_manager.py` | OpenFHE encryption, aggregation, masking, and decryption helper used by encrypted analytics. |
| `app/core/job_runner/nvflare_jobs/apis/pqc_routing_manager.py` | PQC payload routing helper used when final results must be hidden from the server. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/custom/analytics_executor.py` | Client-side NVFlare executor for reference analytics, encrypted analytics, threshold checks, encrypted biomarker discovery, and profile consolidation. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_aggregator.py` | Server-side aggregator for analytics workflows. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_persistor.py` | Server-side persistor that validates workload args, loads schema metadata, initializes workflow metadata, emits progress, records crypto audit data, and stores encrypted biomarker risk scores between workflows. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/global_schema.json` | Global schema copied into generated jobs and used for workflow argument validation and metadata generation. |
| `app/core/job_runner/nvflare_jobs/jobs/configs/` | Source workflow/config JSON files used by job staging and analytics runtime configuration. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Backend staging logic that expands selected functions/model methods into NVFlare workflows, stages model-file source metadata, and inserts model-upload workflows. |

## Runtime Boundary

The analytics workflow code has two layers:

| Layer | Location | Responsibility |
| --- | --- | --- |
| Backend staging layer | `NVFlareJobStager.py` and route/service/task code | Converts selected backend functions, datasource group, participation choices, thresholds, and workflow group selections into a generated NVFlare job directory. |
| Packaged NVFlare runtime layer | `jobs/nvflare_job_template/`, `apis/`, `workflows/`, and copied CSV assets | Runs inside the NVFlare job as client/server custom code. Performs local filtering, local preprocessing, encrypted aggregation, result postprocessing, result writing, progress emission, profiling, and optional PQC result routing. |

The backend does not execute the statistical calculations directly. It stages the NVFlare job with the correct templates and workload arguments. The packaged job runtime performs the calculation once NVFlare runs the staged job.

## Supported Analytics Computation Types

The active analytics runtime supports these computation types:

| Computation type | Primary runtime path | Purpose |
| --- | --- | --- |
| `mean` | `StatAnalyticsManager.preprocess`, `postprocess`, `utils.local_pre_mean`, `utils.local_post_mean` | Computes an aggregate mean for a numeric column. |
| `stdev` | `StatAnalyticsManager.preprocess`, `postprocess`, `utils.local_pre_stdev`, `utils.local_post_stdev` | Computes standard deviation for a numeric column. |
| `chi2` | `StatAnalyticsManager.preprocess`, `postprocess`, `utils.local_pre_chi2`, `utils.local_post_chi2` | Computes chi-square and p-value for categorical variables. The p-value is `null` when the aggregated contingency table is degenerate. |
| `kaplan-meier` | `StatAnalyticsManager.preprocess`, `postprocess`, `utils.local_pre_kaplan_meier`, `utils.local_post_kaplan_meier` | Computes Kaplan-Meier survival output and optional log-rank statistics. |
| `t-test` | `StatAnalyticsManager.preprocess`, `postprocess`, `utils.local_pre_t_test`, `utils.local_post_t_test` | Computes t-test values for a numeric column grouped by a two-category field. |
| `biomarker_enc_risk_group_computation` | `AnalyticsExecutor._task_enc_biomarker_disc`, `StatAnalyticsManager.preprocess`, `utils.local_pre_get_biomarker_records` | Computes encrypted biomarker risk score inputs before the Kaplan-Meier biomarker survival workflow. |

## Job Config Files

Current analytics config files under `app/core/job_runner/nvflare_jobs/jobs/configs/` include:

| Config file | Primary workflow behavior |
| --- | --- |
| `config_mean.json` | Key generation plus encrypted stat analytics for `mean`. |
| `config_standard_deviation.json` | Key generation plus encrypted stat analytics for `stdev`. |
| `config_chi_square_test.json` | Key generation plus encrypted stat analytics for `chi2`. |
| `config_t_test.json` | Key generation plus encrypted stat analytics for `t-test`. |
| `config_survivability_analysis.json` | Key generation plus encrypted stat analytics for standard Kaplan-Meier survival analysis. |
| `config_survival_biomarker_discovery.json` | Key generation plus Kaplan-Meier biomarker discovery using model coefficients/cutoffs. |
| `config_survival_hide_from_server.json` | Kaplan-Meier workflow variant configured for result hiding from the server. |
| `config_template.json` | Generic analytics template with placeholder/default workload argument keys. |
| `example_all_functions.json` | Example configuration containing multiple function selections. |
| `example_threshold_samples_check.json` | Example threshold-sample-check configuration. |
| `example_validate_data.json` | Example validation-style configuration. |

## Workflow IDs and Task Names

Analytics jobs are built around NVFlare workflow IDs and task names.

| Workflow/task | Location | Use |
| --- | --- | --- |
| `workflow_KeyGen` / `task_KeyGen` | Config JSON and OpenFHE runtime | Initializes OpenFHE context and keys before encrypted analytics workflows. |
| `workflow_stat_analytics` / `task_stat_analytics` | Config JSON, `AnalyticsExecutor`, `AnalyticsPersistor` | Main encrypted statistical analytics workflow. |
| `workflow_reference_stat_analytics` / `task_reference_stat_analytics` | Runtime code path | Clear/reference analytics path used when a reference analytics workflow is present. |
| `workflow_enc_biomarker_disc_1` / `task_enc_biomarker_disc` | Config JSON and stager-inserted workflow template | Encrypted biomarker risk group precomputation workflow. |
| `workflow_threshold_samples_unsecure` / `task_threshold_samples_unsecure` | Stager templates and executor | Unsecure threshold sample check. |
| `workflow_threshold_samples_secure` / `task_threshold_samples_secure` | Stager templates and executor | Secure threshold sample check. |
| `workflow_consolidate_profile_summaries` / `task_profile_consolidate` | `stat_analytics_event_type.py`, executor runtime | Merges per-client profile summaries. |

When selected workflow group values include predictive modeling methods, `NVFlareJobStager` expands biomarker Kaplan-Meier workflow IDs into model-specific IDs such as:

- `workflow_stat_analytics__cox_lasso`
- `workflow_stat_analytics__logistic_reg`

The double underscore form is intentional and is used to bind each selected model method to a distinct workflow/result stream.

## Function Config to Workload Args

The stager receives a normalized `functions_map` from job submission. Each selected function maps to one or more configuration dictionaries. During staging, `NVFlareJobStager._build_stat_analytics_workflows()`:

1. Locates the base workflow whose `train_task_name` is `task_stat_analytics`.
2. Removes the original stat analytics template from the non-analytics workflow list.
3. Iterates over selected function configs.
4. Determines `computation_type` from the config or from `FUNCTION_TO_COMPUTATION_TYPE`.
5. Ensures `global_schema` is present, defaulting to `global_schema.json`.
6. Applies type coercion and config-variable-to-filter handling.
7. Creates a workflow copy with a concrete workflow ID.
8. Sets `min_clients` to the participating client count.
9. Writes the concrete `workload_args` into the workflow.
10. Records the function-config-to-workflow mapping through `NVFlareJobsManager.ensure_and_set_workflow_for_function_config()` when a manager is available.

For biomarker discovery configs with selected predictive modeling methods, the stager creates one workflow per selected model key and sets `workload_args.model_key` for each workflow.

## Workload Argument Schema by Computation Type

The runtime validates workload arguments in `AnalyticsPersistor._validate_workload_args()` and generates execution metadata in `AnalyticsPersistor.get_meta_from_schema()`.

| Computation type | Required workload fields | Global schema expectations |
| --- | --- | --- |
| `mean` | `data_column_id`, `global_schema` | `data_column_id` must exist in `columns` and be numeric. `global_min`, `global_max`, and `global_count` must exist. |
| `stdev` | `data_column_id`, `std_type`, `global_schema` | Same numeric-column metadata as `mean`; encrypted validation also requires OpenFHE multiplication/index keys for the stdev workflow. |
| `chi2` | `category_column_1_id`, `category_column_2_id`, `global_schema` | Both category columns must exist and be categorical. Categories and `metadata.global_count_contingency_table.value` are used. |
| `kaplan-meier` | `group_column_id`, `time_column_id`, `censoring_column_id`, `time_grid_min`, `time_grid_step`, `time_grid_max`, `global_schema` | Group column must be categorical, time column numeric, censoring column boolean, group categories present, and `metadata.max_samples_per_time_step` present. |
| `kaplan-meier` biomarker mode | Standard Kaplan-Meier fields plus `is_biomarker_discovery`, `cancer_type`, `model_key` | `metadata.biomarker_covariates` must be present. Coefficients/cutoff are loaded unless encrypted risk scores are injected from the prior encrypted biomarker workflow. |
| `t-test` | `data_column_id`, `category_column_1_id`, `global_schema` | Data column must be numeric. Category column must be categorical and have exactly two categories. |
| `biomarker_enc_risk_group_computation` | `cancer_type`, `model_keys`, `global_schema` | `metadata.biomarker_covariates` must be present. Runtime model artifact metadata is added after model upload. |

## Client-Side Runtime

`AnalyticsExecutor` is the client-side NVFlare executor. It extends `HEExecutor` and owns a `StatAnalyticsManager` instance.

### Client setup

During `START_RUN`, the executor:

1. Resolves filters from the staged filters file when present.
2. Stores filter conditions on `analytics_manager.filters`.
3. Resolves the FHIR/local data source through `FHIRBaseConfigResolver`.
4. Stores the resolved source path or endpoint as `analytics_manager.stat_data_path`.
5. Rejects execution if the data source cannot be resolved to either a URL or a local file.

### Reference analytics task

`AnalyticsExecutor._task_reference_stat_analytics()` is a two-round clear/reference path:

| Round | Behavior |
| --- | --- |
| `0` | Reads workload/generated metadata, configures `StatAnalyticsManager`, preprocesses local data in clear form, and returns local weights/statistics. |
| `1` | Receives aggregated clear/reference data, postprocesses the result, and writes `aggregated/processed_results.json`. |

### Encrypted analytics task

`AnalyticsExecutor._task_stat_analytics()` is the main encrypted analytics path:

| Round | Behavior |
| --- | --- |
| `0` | Reads workload/generated metadata, optionally remaps persisted biomarker risk scores for the client, preprocesses local data, optionally writes `local/local_results.json`, skips contribution for non-contributing clients, encrypts local weights, and returns encrypted weights. |
| `1` | Produces the client's decryption share for the aggregated encrypted result. When server-hidden results are enabled, the leader keeps its local partial decrypt share. |
| `2` | Postprocesses the final decrypted aggregate. In normal mode, clients receive the server-provided result. In hide-result-from-server mode, the leader fuses client shares locally, postprocesses the result, writes `aggregated/processed_results.json`, and builds PQC payloads for eligible analyzing clients. |
| `3` | Used only when `hide_result_from_server` is enabled. Non-leader analyzing clients decrypt the PQC payload and write `aggregated/unprocessed_results.json`. |

Clients listed in `non_contributing_clients` do not contribute encrypted local weights. Clients listed in `exclude_analyzing_clients` are prevented from receiving or writing final analytics results where that runtime path enforces the exclusion.

### Encrypted biomarker discovery task

`AnalyticsExecutor._task_enc_biomarker_disc()` supports encrypted biomarker risk score precomputation:

| Round | Behavior |
| --- | --- |
| `0` | Loads biomarker workflow metadata, builds local biomarker records, encrypts the local biomarker data, and returns encrypted weights. |
| `1` | Produces decryption shares for the encrypted biomarker computation. |

The server persistor stores the resulting encrypted biomarker risk scores so the following model-specific Kaplan-Meier workflows can consume them.

## Server-Side Runtime

### Analytics persistor

`AnalyticsPersistor` extends `HEPersistor` and provides the server-side initialization and persistence behavior for analytics workflows.

During `load_model()` it:

1. Delegates to the HE base persistor for HE-specific workflows when applicable.
2. Logs crypto audit metadata after `workflow_KeyGen`.
3. Builds common metadata such as round, server data-owner flags, leader client name, excluded analyzing clients, and non-contributing clients.
4. Validates workload arguments for analytics workflows.
5. Loads `global_schema.json` from the generated job's server custom directory.
6. Generates computation-specific metadata from the global schema.
7. Validates OpenFHE parameters and computes required multiplicative depth for encrypted workflows.
8. Injects PQC key packages when server-hidden result routing requires them.
9. Returns a `ModelLearnable` with `weights={}` and metadata in `meta_props`.

During `save_model()` it delegates to the HE base persistor and then stores `w_biomarker_risk_scores` plus `risk_scores_scale_factor` when the completed workflow starts with `workflow_enc_biomarker_disc`.

### Analytics aggregator

`analytics_aggregator.py` provides the server-side aggregation component used by the NVFlare workflow configuration. It builds on the encrypted aggregation behavior in `HEAggregator` and participates in the same OpenFHE workflow family as the executor and persistor.

## Biomarker Model File Resolution

Biomarker model files are resolved from initiator-side User Settings instead of backend-bundled CSV directories. The backend never needs the model files on its own filesystem.

The User Settings model-file records identify:

| Field | Meaning |
| --- | --- |
| `project_id` | Project that owns the model file setting. |
| `datasource_group_id` | Datasource group; this distribution provides `MSKChord`. |
| `model_file_lookup_key` | Lookup dimension, currently cancer type for biomarker models. |
| `model_file_lookup_value` | Lookup value, such as `Non-Small Cell Lung Cancer`. |
| `model_key` | Model family, such as `cox_lasso` or `logistic_reg`. |
| `artifact_type` | Artifact role, such as `weights` or `cutoff`. |
| `source` | Initiator-local filesystem path. |

Default filenames use this convention when pattern mode is used in User Settings:

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

At staging time, `NVFlareJobStager` writes `app_client/custom/model_file_sources.json` containing only the selected initiator-local paths. At runtime, `workflow_model_upload__<model_key>` runs on the initiator/leader site, reads those paths, and uploads the artifacts required by later workflows.

Open-access model workflows can upload plaintext model artifacts. Encrypted workflows upload encrypted model artifacts. For encrypted Exceptional Response Discrimination, the model-upload workflow also sends the `ER_threshold` from the cutoff CSV so the later meta-analysis workflow can resolve `horizon_threshold` without requiring the backend or server to read the original model file.

## Predictive Modeling Method Expansion

The workflow group payload controls biomarker model expansion through:

```json
{
  "predictive_modeling_method_ids": {
    "selected_values": ["cox_lasso", "logistic_reg"]
  }
}
```

`NVFlareJobStager._get_selected_model_keys()` reads this payload, trims string values, removes empty values, and preserves unique model keys in selection order.

When a selected function config has `is_biomarker_discovery` set to a truthy value and selected model keys are present, the stager duplicates the biomarker config once per selected model key. Each duplicated config receives its own `model_key`.

The same expansion is applied to project function metadata through `_expand_project_functions_for_selected_models()` so job history/config lookup can reflect the model-specific function configuration.

## Biomarker Kaplan-Meier Modes

The code supports two biomarker Kaplan-Meier execution modes.

### Direct model-file mode

For non-precomputed biomarker Kaplan-Meier execution, `AnalyticsPersistor.get_meta_from_schema()` resolves model paths and loads:

- coefficients from the selected `{model_key}_{cancer_type}_weights.csv`
- cutoff value from the selected `{model_key}_{cancer_type}_cutoff.csv`

The coefficients are serialized into generated metadata and passed to clients. `utils.local_pre_kaplan_meier()` then builds a biomarker Kaplan-Meier dataframe using the filter engine and assigns risk groups based on model-derived risk scores.

### Encrypted precomputed risk-score mode

For encrypted biomarker discovery, the stager inserts `workflow_enc_biomarker_disc_1` before the Kaplan-Meier workflow when the selected function is encrypted model-based biomarker discovery and the config does not already include an encrypted biomarker discovery workflow.

That inserted workflow uses:

| Field | Value |
| --- | --- |
| `id` | `workflow_enc_biomarker_disc_1` |
| `train_task_name` | `task_enc_biomarker_disc` |
| `computation_type` | `biomarker_enc_risk_group_computation` |
| `train_timeout` | `600` seconds |
| `model_keys` | Selected predictive model keys when present. |

After that workflow finishes, `AnalyticsPersistor.save_model()` stores encrypted biomarker risk scores. During the following `workflow_stat_analytics__{model_key}` workflow, `AnalyticsPersistor.load_model()` injects the matching model's risk scores into generated metadata and removes that model key from the persisted score cache.

## Risk Group Assignment

For biomarker Kaplan-Meier workflows, risk grouping is handled in `utils.local_pre_kaplan_meier()`.

When direct model coefficients are available, the filter engine builds the biomarker Kaplan-Meier dataframe using the model coefficients and cutoff.

When precomputed encrypted risk scores are supplied, the code:

1. Extracts time and censoring data through the filter engine.
2. Slices the risk score vector to the dataframe length.
3. Converts nested list/array score values to floats.
4. Applies an epsilon cleanup threshold.
5. Assigns `high_score` where the cleaned risk score is greater than `0.0`; otherwise assigns `low_score`.

The epsilon differs by model key in the precomputed-score branch:

| Model key | Epsilon behavior |
| --- | --- |
| `cox_lasso` | Uses `1e-15` unless scaled by `risk_scores_scale_factor`. |
| `logistic_reg` | Uses `1e-5` unless scaled by `risk_scores_scale_factor`. |
| `risk_scores_scale_factor == 1` | Uses `1e-6`. |

In `StatAnalyticsManager.postprocess()` and `postprocess_reference()`, the result swaps `high_score` and `low_score` survival output for `logistic_reg`. The code comment states this is because high score means low risk for the logistic regression model and the swap helps display the result correctly in the UI.

## Chi-Square Contingency Table and Degrees of Freedom

`utils.local_pre_chi2()` builds a per-client contingency table over `column_1_categories` by `column_2_categories`, together with row/column marginals, the table total `N_sum`, and two zero-marginal indicator vectors, `zeros_row` and `zeros_col`. Every vector is flattened to `N_rows * N_cols` entries so it lines up with the row-marginal by column-marginal outer product: each row flag is repeated `N_cols` times and each column flag is tiled `N_rows` times.

Aggregation (`OpenfheManager.aggregate_stat_analytics()` for the encrypted path, `StatAnalyticsManager.aggregate_reference()` for the clear path) derives the same terms on both paths:

| Aggregated value | Behavior |
| --- | --- |
| `cont_table`, `row_marg`, `col_marg`, `N_sum` | Summed across contributing clients. |
| `zeros_row`, `zeros_col` | Multiplied across contributing clients, so a category counts as empty only when it is empty for every client. |
| Numerator | `(observed - expected)^2` per cell, where `expected = row_marg * col_marg` and `observed = cont_table * N_sum`. |
| Denominator | `expected * N_sum` per cell. |
| Empty row/column counts | The indicator totals still carry the broadcast factor, so an empty row would otherwise be counted once per column. The clear path divides it out directly (`sum(zeros_row) // num_cols`, `sum(zeros_col) // num_rows`); the encrypted path folds the same factor into the constants it subtracts, divides `len_category1 * len_category2` back out after decryption, and rounds the result to an integer. |
| Degrees of freedom | `(num_rows - 1 - empty_rows) * (num_cols - 1 - empty_cols)`, which can be `0` or negative when a dimension is left with a single non-empty category. |

Two behaviors follow from the fact that a category can be empty across all clients — most commonly because a submitted filter pins that variable to a single value:

- **Zero-expected-value cells.** A cell's expected value is `row_marg * col_marg`, so it is zero when either marginal is empty. `OpenfheManager.zero_expected_value_mask()` combines the two indicator vectors with OR (`zeros_row + zeros_col - zeros_row * zeros_col`) rather than AND, so the mask also fires for an empty column against populated rows. Masked cells are given a dummy denominator instead of dividing by zero, which keeps the additive shares-of-zero used by the encrypted masking cancelling correctly. `utils.local_post_chi2()` independently skips any cell whose denominator is zero when it sums the statistic.
- **Degrees of freedom over surviving categories.** Empty rows and columns are excluded from the count on both paths, and `OpenfheManager._decrypt_stat_analytics_all_shares()` removes the broadcast factor before `dof` is handed to postprocessing.

### Degenerate and invalid chi-square results

`utils.local_post_chi2(numerator, denominator, dof)` returns `(chi2, None)` when `dof <= 0`. `scipy.stats.chi2.sf` returns `NaN` for a non-positive `dof`, which is also not valid JSON.

The module-level `_chi2_result()` helper in `stat_analytics.py` assembles the final payload for both `StatAnalyticsManager.postprocess()` (encrypted) and `postprocess_reference()` (clear), so both paths surface the same result shape:

| Condition | `p_value` | Warning |
| --- | --- | --- |
| `dof <= 0` | `null` | `DEGENERATE_CHI2_NO_TEST` |
| `dof > 0` and `chi2 < 0` | `null` | `INVALID_CHI2_NEGATIVE` |
| Otherwise | Computed p-value | None |

Degeneracy is checked first. A `dof <= 0` table has `observed == expected` in every non-empty cell, so its statistic is exactly zero in the clear and CKKS noise routinely makes the encrypted value come back slightly negative; checking `chi2 < 0` first would report the wrong reason.

Both conditions are non-fatal. `_chi2_result()` sets `p_value` to `null`, builds a `WarnException` (`apis/warn_exception.py`) without raising it, logs it at warning level, and merges its payload into the result through `_attach_warning()`, which adds:

| Field | Value |
| --- | --- |
| `status` | `WARN` |
| `msg` | The warning message string. |
| `warning` | `{"exception_type": "WarnException", "code": ..., "message": ..., "details": ...}` |

`DEGENERATE_CHI2_NO_TEST` carries `details.dof`; `INVALID_CHI2_NEGATIVE` carries `details.chi2`. The `chi2` key is still present in both cases. Letting a `WarnException` escape an NVFlare task would turn the warning into a failed workflow, so the runtime never propagates it.

## FHIR and Local Data Integration

The analytics runtime receives one `stat_data_path` value from `FHIRBaseConfigResolver`. The value can be a local JSON file path or a FHIR endpoint URL.

The shared utility path loads and filters data through the FHIR/local filter engine:

- `utils.local_pre_mean()` extracts numeric data for mean.
- `utils.local_pre_stdev()` extracts numeric data for standard deviation.
- `utils.local_pre_chi2()` extracts categorical data for chi-square.
- `utils.local_pre_t_test()` extracts numeric/category data for t-test.
- `utils.local_pre_kaplan_meier()` extracts survival data and, in biomarker mode, builds risk-score survival groups.
- `utils.local_pre_get_biomarker_records()` builds biomarker subject records for encrypted biomarker risk group computation.

Filters staged by the backend are loaded by the executor and passed through `StatAnalyticsManager.filters` into the utility functions.

## Observation Snapshot Utility

`observation_snapshot.py` is a standalone helper for building a single merged Observation snapshot from FHIR JSON. It can read:

- a single JSON object,
- a JSON array,
- NDJSON,
- or a directory of JSON files.

It collects `Observation` resources, strips top-level IDs and subject references, recursively merges object/list/primitive values, and writes a final JSON snapshot. This utility is not the main analytics execution path; it supports inspection/schema-style handling of Observation structures.

## Result File Layout

Client-side results are written under:

```text
job-results/{job_id}/{computation_type}/{workflow_name}/
```

Known result files include:

| File | Written by | Meaning |
| --- | --- | --- |
| `aggregated/processed_results.json` | `AnalyticsExecutor._task_reference_stat_analytics()` and `_task_stat_analytics()` | Final postprocessed aggregate analytics result. |
| `aggregated/unprocessed_results.json` | `AnalyticsExecutor._task_stat_analytics()` round 3 for server-hidden result mode | The decrypted **unprocessed** aggregate the leader broadcast (the leader sends the pre-postprocess aggregate, not its final result). The non-leader postprocesses it locally and also writes its own `aggregated/processed_results.json`. |
| `local/local_results.json` | `AnalyticsExecutor._task_stat_analytics()` when local-result calculation is enabled | Local-only result for the client before federated aggregate result handling. |
| `profile_summary.json` | Profiler/runtime code | Per-client profile summary consumed by profile consolidation. |

The processed aggregate result shape depends on computation type:

| Computation type | Result keys |
| --- | --- |
| `mean` | `mean` |
| `stdev` | `stdev` |
| `chi2` | `chi2`, `p_value` (`null` when `dof <= 0` or the aggregated statistic is negative), optional `status`, optional `msg`, optional `warning` |
| `kaplan-meier` | `S_output`, `times`, optional `CI`, optional `chi2`, optional `p_value`, optional `status`, optional `msg`, optional `warning` |
| `t-test` | `t_score`, `dof`, `p_value` |

The optional `status`, `msg`, and `warning` keys are added by `_attach_warning()` whenever the runtime records a non-fatal analytics warning. `chi2` results carry `DEGENERATE_CHI2_NO_TEST` or `INVALID_CHI2_NEGATIVE` on both the encrypted and clear paths. `kaplan-meier` results carry `SINGLE_RISK_GROUP_NO_LOGRANK` on the clear reference path when only one risk group is populated; in that case `chi2` and `p_value` are absent from the result rather than `null`.

## Profiling and Events

`stat_analytics_event_type.py` defines analytics phase events used by the runtime profiler and related listeners.

| Event phase | Meaning |
| --- | --- |
| `setup` | Workload/generated metadata is loaded and manager state is configured. |
| `preprocess` | Local data extraction/filtering/statistic preparation runs. |
| `compute` | Reserved for key generation, init mix, and non-stat-analytics crypto lifecycle work. |
| `aggregate` | Server encrypted aggregation runs. |
| `aggregate_reference` | Clear/local aggregate-reference computation runs. |
| `postprocess` | Final result conversion/postprocessing runs. |
| `encrypt` | Client encrypts local analytics weights. |
| `decrypt` | Client/server decryption-share or final decryption behavior runs. |
| `encrypt_pqc` | Leader wraps final result payload for PQC routing. |
| `decrypt_pqc` | Client decrypts a PQC result payload. |

`PROFILE_CONSOLIDATE_WORKFLOW_ID` is `workflow_consolidate_profile_summaries`. `PROFILE_SNAPSHOT_EVENT` is `duality_profile_snapshot`.

## Progress and Audit Emission

`AnalyticsExecutor` emits job progress from the client runtime. `AnalyticsPersistor` emits server-side progress around workload validation, schema metadata loading, OpenFHE validation, and intermediate artifact persistence.

The persistor also calls `log_audit()` after `workflow_KeyGen`, sending OpenFHE audit fields such as security level, ring dimension, batch size, scale modulus size, multiplicative depth, scaling technique, key-switch technique, CKKS data type, noise bits, and related crypto settings to the backend audit endpoint when progress/audit HTTP emission is enabled.

## OpenFHE Validation Rules

Encrypted analytics workflows depend on OpenFHE context and keys initialized by `workflow_KeyGen`.

`AnalyticsPersistor._validate_openfhe_parameters()` validates that the required crypto context and evaluation keys exist for the requested workflow. Current examples include:

| Workflow/computation | Validation behavior |
| --- | --- |
| `workflow_stat_analytics` with `mean` | Requires OpenFHE CryptoContext and sets depth for mean. |
| `workflow_stat_analytics` with `stdev` | Requires multiplication keys and rotation/index keys including `[1, 2]`. |
| `workflow_stat_analytics` with `chi2` | Requires multiplication keys and calculates depth based on number of contributing data owners. |
| `workflow_stat_analytics` with `kaplan-meier` | Uses Kaplan-Meier metadata such as time-grid length and encrypted aggregation/decryption metadata. |
| `workflow_threshold_samples_secure` | Requires multiplication keys and supports only the coded threshold/data-owner configurations. |
| `workflow_enc_biomarker_disc` | Validates encrypted biomarker risk group computation parameters and model metadata. |

## Error Handling

Current runtime behavior is fail-fast for invalid analytics configuration.

Examples of hard failures include:

- Missing generated job template files.
- Missing `global_schema.json` in the generated server custom directory.
- Unsupported workflow names in `AnalyticsPersistor.load_model()`.
- Unsupported computation types in `StatAnalyticsManager`.
- Missing or invalid workload arguments.
- Missing schema metadata for selected columns.
- Categorical fields without categories.
- Kaplan-Meier schema missing `max_samples_per_time_step`.
- Biomarker workflows missing `biomarker_covariates`.
- Missing biomarker weight/cutoff CSV files.
- Invalid biomarker model key when risk scores are used.
- Attempting `workflow_stat_analytics` without required OpenFHE context after key generation.
- Encrypted result-hiding workflow configured with an invalid round count.
- Non-hidden encrypted analytics workflow configured with an invalid round count.

The client executor writes exception JSON through its exception helper when task execution fails in paths that catch and record execution exceptions.

Two hidden-result PQC round cases are handled specially rather than as generic fail-fast:

- **Round 2, leader submission absent (server):** if the leader's per-non-leader payload submission is not present when the server aggregates round 2, the aggregator logs a loud ERROR and raises (failing that one combo) instead of silently emitting an empty payload. The round-2 wait barrier in `customSAG` normally prevents this by blocking until every per-client task completes before aggregation; the guard is the server-side backstop.
- **Round 3, per-client payload missing (non-leader client):** if a non-leader receives a `None` / non-`(nonce, ciphertext)` round-3 payload, it logs an ERROR, skips postprocess, and returns an empty (valid) shareable so the round completes and the rest of the job proceeds — that one (analysis × model) combo's result is absent for the run rather than crashing the contribution.

Result conditions that are not configuration errors are reported as non-fatal warnings instead. `WarnException` (`apis/warn_exception.py`) is never allowed to escape an NVFlare task; the runtime attaches its payload to the result through `_attach_warning()` and the workflow still completes. A chi-square job whose contingency table is degenerate (`DEGENERATE_CHI2_NO_TEST`) or whose aggregated statistic is negative (`INVALID_CHI2_NEGATIVE`) therefore returns a `WARN` result with a `null` `p_value`, not a failure.

## Frontend Result Expectations

The backend stages one or more workflow IDs for each submitted analytics job. The frontend should treat results as workflow-scoped, not only function-scoped.

For biomarker discovery with multiple predictive modeling methods, the frontend should expect separate workflow IDs and result sections for each model method, such as:

- `workflow_stat_analytics__cox_lasso`
- `workflow_stat_analytics__logistic_reg`

For Kaplan-Meier-style results, the frontend should expect survival output under `S_output` and time points under `times`, with optional confidence interval and p-value/log-rank statistics depending on the workflow and available data.

For chi-square results, the frontend should expect `chi2` to always be present and `p_value` to be nullable. A `null` `p_value` means the test was not applicable, not that the job failed; the accompanying `status`, `msg`, and `warning` fields carry the reason.

For logistic regression biomarker results, the backend runtime swaps high-score and low-score survival output during postprocessing so the displayed risk grouping matches the intended UI interpretation.
