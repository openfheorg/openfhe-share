# OpenFHE and Encrypted Workflows

## Files Covered

| File | Role |
| --- | --- |
| `app/core/job_runner/nvflare_jobs/apis/openfhe_manager.py` | OpenFHE CKKS helper used by encrypted job runtime code for crypto-context creation, key generation, serialization/deserialization, encryption, aggregation, partial decryption, and biomarker risk-score masking. |
| `app/core/job_runner/nvflare_jobs/apis/pqc_routing_manager.py` | Post-quantum secure routing helper used when `hide_result_from_server` is enabled. It uses ML-KEM-1024, HKDF-SHA256, and AES-256-GCM to route final plaintext payloads between clients without exposing them to the server. |
| `app/core/job_runner/nvflare_jobs/apis/HEAggregator.py` | Base NVFlare server-side aggregator for encrypted key-generation/decryption workflows. `AnalyticsAggregator` extends this class. |
| `app/core/job_runner/nvflare_jobs/apis/HEExecutor.py` | Base NVFlare client-side executor for encrypted key-generation/decryption workflows. `AnalyticsExecutor` extends this class. |
| `app/core/job_runner/nvflare_jobs/apis/HEPersistor.py` | Base NVFlare server-side persistor for OpenFHE parameter initialization, key-generation bootstrapping, and persistence of the generated crypto context. `AnalyticsPersistor` extends this class. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/custom/analytics_executor.py` | Client runtime executor packaged into generated jobs. It extends `HEExecutor` and handles analytics tasks that can call OpenFHE helpers. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_aggregator.py` | Server runtime aggregator packaged into generated jobs. It extends `HEAggregator` and routes workflow-specific analytics aggregation. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_persistor.py` | Server runtime persistor packaged into generated jobs. It extends `HEPersistor`, validates workload/OpenFHE parameters, injects PQC key packages, and saves runtime outputs. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/config/config_fed_client.json` | NVFlare client config that registers `analytics_executor.AnalyticsExecutor` for key generation, statistical analytics, threshold checks, reference analytics, profile consolidation, and encrypted biomarker discovery tasks. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/config/config_fed_server.json` | NVFlare server config template that registers `AnalyticsPersistor`, `AnalyticsAggregator`, profiler components, progress webhook components, `workflow_KeyGen`, stat-analytics workflow templates, and profile consolidation workflow. |
| `app/core/job_runner/nvflare_jobs/jobs/configs/*.json` | Example and function-specific job configs that include OpenFHE persistor arguments and encrypted workflow definitions. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Backend staging logic that patches server config, injects OpenFHE arguments, adds encrypted biomarker workflow definitions when needed, and writes job metadata/files. |

## Scope

OpenFHE and encrypted workflow support is part of the NVFlare job runtime, not a separate FastAPI endpoint group. The FastAPI backend selects and stages jobs, then the generated NVFlare job executes cryptographic work inside the packaged client/server runtime files.

The encrypted workflow layer currently supports these major runtime responsibilities:

- OpenFHE CKKS crypto context initialization.
- Multi-party key generation using `star` and `cc` architecture paths.
- Serialization and routing of crypto context, public keys, secret keys, eval keys, and ciphertexts.
- Homomorphic/statistical aggregation helpers for analytics workflows.
- Partial decryption and decryption-share fusion.
- Optional hidden-result routing where the server does not receive final plaintext results.
- Encrypted biomarker risk-score computation and masked multi-party decrypt handling.

## Runtime Class Model

| Class | Runtime side | Purpose |
| --- | --- | --- |
| `OpenfheManager` | Shared client/server runtime helper | Owns OpenFHE context, key material, serialization helpers, encrypted operations, aggregation helpers, and decryption helpers. |
| `HEPersistor` | Server | Initializes OpenFHE context/key material at the start of key-generation workflows and saves the final generated crypto context. |
| `HEAggregator` | Server | Aggregates client key shares, routes key-generation rounds, handles server-side decryption workflows, and supports asymmetric per-client shareable payloads. |
| `HEExecutor` | Client | Handles `task_KeyGen`, `task_init_mix`, client-side key-share creation, optional PQC public-key/key-package handling, and client-side decryption helpers. |
| `AnalyticsPersistor` | Server | Extends `HEPersistor`; validates OpenFHE/workload args, injects PQC key packages into the first post-keygen workflow, and persists analytics outputs. |
| `AnalyticsAggregator` | Server | Extends `HEAggregator`; adds workflow-specific aggregation for threshold, reference analytics, stat analytics, and encrypted biomarker discovery. |
| `AnalyticsExecutor` | Client | Extends `HEExecutor`; adds workflow-specific client execution for stat analytics, threshold samples, reference analytics, encrypted biomarker discovery, and profile consolidation. |
| `PQCRoutingManager` | Client-side coordinator/standard client helper | Used only for hidden-result routing; standard clients generate ML-KEM keypairs, the lead client encapsulates AES session keys, and payload vectors are encrypted per recipient. |

## OpenFHE Manager

`OpenfheManager` is the central runtime helper. It is constructed with OpenFHE/CKKS settings and optional key-generation flags:

| Constructor value | Meaning |
| --- | --- |
| `mult_depth` | CKKS multiplicative depth. |
| `cc_batch_size` | Optional CryptoContext batch size. If omitted, the generated context batch size is used. |
| `scale_mod_size` | CKKS scaling modulus size. Defaults to `53`. |
| `scaling_technique` | String name used to resolve `ScalingTechnique`, such as `FLEXIBLEAUTO`. |
| `key_switch_technique` | String name used to resolve `KeySwitchTechnique`, such as `BV` or `HYBRID`. |
| `ckks_data_type` | String name used to resolve `CKKSDataType`, such as `REAL`. |
| `generate_mult_keys` | Enables multiplication/eval-mult key generation. |
| `generate_sum_keys` | Enables eval-sum key generation. |
| `generate_index_keys` | Enables eval-at-index/rotation key generation. |
| `indices` | Rotation indices used when `generate_index_keys` is enabled. |
| `is_MultiParty` | Enables OpenFHE multiparty functionality. |
| `ring_dim` | CKKS ring dimension. Defaults to `0`, the only production value, which lets OpenFHE derive the ring from the security level. A positive value pins the ring and is test/development only. Falls back to the `DUALITY_SIM_CKKS_RING_DIM` environment variable when not passed explicitly. |

### Context Initialization

`initialize_openfhe()` builds a `CCParamsCKKSRNS` object, applies the configured settings, creates the crypto context with `GenCryptoContext`, and enables these OpenFHE capabilities:

- `PKE`
- `KEYSWITCH`
- `LEVELEDSHE`
- `ADVANCEDSHE`
- `MULTIPARTY` when `is_MultiParty` is true

After initialization it records an audit dictionary containing the security level, ring dimension, batch size, scale modulus size, multiplicative depth, scaling technique, key-switch technique, CKKS data type, and configured IND-CPA noise-flooding note. `get_audit_record()` returns that audit dictionary.

#### Security level and ring dimension

Production sets `HEStd_128_classic` explicitly and lets OpenFHE derive the ring dimension from it. A ring dimension can be pinned for tests via `OpenfheManager(ring_dim=…)` or the `DUALITY_SIM_CKKS_RING_DIM` environment variable; OpenFHE only accepts a pinned ring with the security level unset, so the two always move together and an under-sized ring cannot be requested at full security. A pinned ring logs an INSECURE warning and is recorded in the audit dictionary. `cc_batch_size` is unset in every job config, so the batch size follows as `ring / 2` and propagates to the clients in the model metadata. `cov_length` is fixed by the covariate count, not by the batch size, so the configured rotation `indices` are unaffected.

### Key Generation

`keygen()` requires a crypto context to already be initialized. It creates a keypair with `KeyGen()` and conditionally generates:

- key-switch/eval-mult material through `KeySwitchGen()` when `generate_mult_keys` is true
- eval-sum keys through `EvalSumKeyGen()` and `GetEvalSumKeyMap()` when `generate_sum_keys` is true
- rotation/eval-at-index keys through `EvalAtIndexKeyGen()` and `GetEvalAutomorphismKeyMap()` when `generate_index_keys` is true

### Serialization Helpers

`OpenfheManager` serializes and deserializes OpenFHE objects using binary OpenFHE serialization. The helper methods include:

| Method | Use |
| --- | --- |
| `serialize_cc()` / `deserialize_cc()` | CryptoContext bytes in/out. |
| `serialize_public_key()` / `deserialize_public_key()` | Public key bytes in/out. |
| `serialize_secret_key()` / `deserialize_secret_key()` | Secret key bytes in/out. |
| `serialize_dict()` | Packages `CC`, `pk`, `batchSize`, and optional eval keys/indices into a dictionary used by key-generation workflow payloads. |
| `serialize_cipherlist()` / `deserialize_cipherlist()` | Module-level helpers for serialized ciphertext lists. |

### Encrypted Operations

The manager contains client/server helpers for:

- encrypting Python lists and batched lists
- combining ciphertext lists using operations such as encrypted addition/multiplication helpers
- compressing ciphertext lists
- decrypting ciphertext lists in single-key or multiparty paths
- aggregating model weights and stat-analytics results
- executing key-generation rounds on clients and server
- executing encrypted stat analytics
- handling biomarker encrypted risk-score computation, masking, and unmasking

The biomarker helpers include per-model masking state in `biomarker_decrypt_masks`. The encrypted biomarker flow can apply a random mask before partial decryption and later remove the mask to extract the risk scores.

#### Kaplan-Meier time-grid masking

The encrypted Kaplan-Meier path masks its aggregated group numerators/denominators — and, for a two-group log-rank test, the group-A and variance terms — over the time grid, which is packed into `ceil(len_time_grid / cc_batch_size)` ciphertexts. Ciphertext `i` covers grid indices `[i × cc_batch_size, min((i + 1) × cc_batch_size, len_time_grid))`, and every multiplicative and additive mask is built from those same per-ciphertext bounds, so each mask holds exactly the slots its ciphertext occupies. The log-rank additive masks are drawn as shares of zero over the whole grid and then sliced by ciphertext, so the shares still sum to zero across the grid. The time grids produced by the current configs fit in a single ciphertext, so the chunk loop normally runs once; more than one ciphertext becomes reachable with a large grid or a reduced ring dimension.

### Biomarker dot-product parallelism and caching

The biomarker risk-score dot-product is parallelized across processes with a `ProcessPoolExecutor` (`CHUNK_SIZE = 4`) and a worker count (`MAX_WORKERS`) resolved by `resolve_biomarker_max_workers()` as `min(cpu_cores, cap, memory budget)`. The encrypted-aggregation section is core-bound, so the CPU term keeps the count from exceeding the cores that the process can actually be scheduled on (`len(os.sched_getaffinity(0))`, which respects a container cpuset); extra workers past that only consume RAM. `cap` comes from `OPENFHE_BIOMARKER_MAX_WORKERS_CAP`. Setting `OPENFHE_BIOMARKER_MAX_WORKERS` overrides the whole calculation verbatim and is **not** core-capped. To avoid re-encrypting the same cohort, encrypted patient covariates are held in an LRU `_cpatients_cache` keyed by record-cache-key + CKKS level + key tag, so the per-cohort ciphertexts are reused across the discovery (`disc_1`) and scoring (`disc_score`) workflows and across both models. This caching is equivalence-verified against the clear-text reference and does not change results — only timing.

#### Output packing and cohort size

Patient ciphertext `c` writes each patient's score to offset `c % cov_length` inside every `cov_length`-wide patient block, so one output ciphertext holds `cov_length × patients_per_batch == cc_batch_size` patients — one score per slot. Cohorts larger than that span several output ciphertexts, with patient ciphertext `c` contributing to output ciphertext `c // cov_length`. Every biomarker score slice is therefore a **list** of ciphertexts: the decrypt round fuses them position-wise (every party must return one partial share per output ciphertext, or the aggregator raises), each ciphertext of a client's own slice carries an independent hide-from-lead mask keyed `(model_key, cipher_index)`, and `StatAnalyticsManager._re_map_batched_patients_biomarker` converts each `cc_batch_size`-wide slot window back to patient order and concatenates. A single ciphertext (the shape produced before this became a list) is still accepted on read, and mask removal falls back to the bare `model_key` for such a payload.

## Key-Generation Workflows

Encrypted jobs use `workflow_KeyGen` before encrypted analytics workflows. The default job template includes `workflow_KeyGen` in `app_server/config/config_fed_server.json`; generated jobs keep or patch it during staging.

### Star Architecture

The active configs use `arch: "star"` in the persistor args. In this mode:

1. `AnalyticsPersistor.load_model()` calls the base `HEPersistor.load_model()` path for `workflow_KeyGen`.
2. `HEPersistor` initializes the OpenFHE context, calls `keygen()`, and returns a model learnable with serialized context/key material and meta props such as `round`, `arch`, `mult_depth`, `cc_batch_size`, `ckks_data_type`, `hide_result_from_server`, `leader_client_name`, and `exclude_analyzing_clients`.
3. Each client receives `task_KeyGen` through `AnalyticsExecutor`, which delegates the key-generation task to `HEExecutor`.
4. `HEExecutor` stores the architecture and hidden-result metadata on round `0`, then calls the correct OpenFHE manager key-generation round helper.
5. `HEAggregator` receives submitted key shares, aggregates them in `_workflow_KeyGen()`, and returns the next-round shareable.
6. `HEPersistor.save_model()` stores the final serialized `CC` after key generation.

For `star` mode, the aggregator handles two key-generation rounds:

| Round | Server aggregator behavior | Client behavior |
| --- | --- | --- |
| `0` | Aggregates public-key/eval-key shares with `aggregate_keygen_star_round0()`. | Clients run `exec_keygen_star_round0()`. |
| `1` | Aggregates final eval-key shares with `aggregate_keygen_star_round1()`. | Clients run `exec_keygen_star_round1()`. |

### CC Architecture

`HEAggregator` and `HEExecutor` also contain `cc` architecture branches. In this mode:

- round `0` receives initial crypto context/key material from the leader client
- round `1` aggregates key shares from non-leader clients
- round `2` aggregates final eval-key shares

The current packaged example configs are primarily `star` oriented, but the code paths for `cc` are present in the shared encrypted runtime classes.

### Single-Client Behavior

For `init_mix_SAG` and some `cc` paths, the code detects one-client execution and disables multiparty behavior by setting `is_MultiParty` to false.

## Hidden Result Routing

The `hide_result_from_server` option changes how plaintext results are routed after multiparty decryption. It is present in the template server config and in `config_survival_hide_from_server.json`.

When hidden-result routing is enabled:

1. Non-leader clients create ML-KEM keypairs through `PQCRoutingManager` and send their public key during key-generation round `0`.
2. The server aggregator collects those public keys but does not decrypt final plaintext payloads for itself.
3. The leader client receives the other clients' ML-KEM public keys in a per-client/asymmetric payload.
4. The leader client registers public keys and creates key packages with `generate_and_distribute_keys()`.
5. The key packages are returned through key-generation output and saved by `HEPersistor.save_model()` as `pqc_key_packages`.
6. `AnalyticsPersistor._inject_pqc_key_packages()` injects one key package per target client into the first post-keygen workflow only.
7. Non-leader clients receive their own `pqc_key_package`, establish an AES session key, and can later decrypt routed payloads.
8. The leader client can build a per-client encrypted payload vector with `build_payload_vector()`.

The PQC helper uses:

| Item | Current value |
| --- | --- |
| KEM algorithm | `ML-KEM-1024` |
| Key derivation | HKDF-SHA256 |
| Payload/session encryption | AES-256-GCM |
| AES key length | `32` bytes |
| GCM nonce length | `12` bytes |

The server can route encrypted key packages and encrypted payload vectors, but the server does not have the AES session keys for the final hidden plaintext payloads.

### Per-round analytics flow under hidden-result routing

Each hidden-result `stat_analytics` workflow runs a **4-round** exchange (the round dispatch lives in `analytics_aggregator_impl.py` / `analytics_executor_impl.py`):

- **Round 0** — all clients send encrypted ciphertexts; the server aggregates in the ciphertext domain.
- **Round 1** — the server collects partial decryptions and sends the partial-decryption shares only to the **leader** (an asymmetric payload keyed to the leader).
- **Round 2** — the leader fuses the shares, postprocesses locally, writes its own results, and builds a **per-non-leader encrypted payload vector** (`build_payload_vector()`). The server then constructs per-client asymmetric specs (`_PER_CLIENT_PAYLOADS_`) from the leader's submission — one result-bearing payload per analyzing non-leader.
- **Round 3** — each non-leader decrypts its own PQC payload, writes `aggregated/unprocessed_results.json`, and postprocesses locally.

**Asymmetric dispatch + round-2 wait barrier.** When a round carries `_PER_CLIENT_PAYLOADS_`, `customSAG.broadcast_and_wait` bypasses NVFlare's single-Task broadcast and sends one `Task` per client (each with that client's tailored payload), then `_await_asymmetric_completion` blocks until every per-client task has completed before the controller advances to aggregation. This closes a round-2 timing race where the server could otherwise aggregate before the leader's (slow HE) payload submission arrived, leaving non-leaders with a result-less round-3 payload.

**Failure handling.** If the leader's round-2 submission is nonetheless absent at aggregation, the aggregator logs a loud ERROR and raises (failing that one combo) rather than emitting an empty payload. If a non-leader still receives a missing/`None` round-3 payload, it logs an ERROR, skips postprocess, and returns an empty valid shareable so the round completes and the rest of the job proceeds.

## Aggregator, Executor, and Persistor Roles

### `HEPersistor`

`HEPersistor` is the server-side NVFlare persistor base class. It owns an `OpenfheManager` instance and is responsible for:

- loading initial crypto context/key material for `init_mix_SAG`
- loading initial key-generation model data for `workflow_KeyGen`
- setting OpenFHE meta props on the model learnable
- saving the final CryptoContext after key generation
- preserving PQC key packages after hidden-result key generation
- validating that `exclude_analyzing_clients` is a list and does not include the leader client

`get_aggregator_sk()` exposes the server-side secret key to the aggregator after key generation in `star` mode. It raises if the secret key is unavailable.

### `HEAggregator`

`HEAggregator` is the server-side NVFlare aggregator base class. It routes `aggregate()` based on the workflow name. Current base-class handling includes:

| Workflow | Behavior |
| --- | --- |
| `init_mix_SAG` | Returns empty shareable data for initialization. |
| `workflow_KeyGen` | Runs `_workflow_KeyGen()` to aggregate key-generation rounds. |

The class also contains decryption workflow helpers and shareable builders. `get_shareable_data_asymmetric()` is used when different clients need different payloads, such as PQC public-key routing or hidden-result key-package delivery.

### `HEExecutor`

`HEExecutor` is the client-side NVFlare executor base class. It handles:

| Task | Behavior |
| --- | --- |
| `task_init_mix` | Receives/saves crypto context through `exec_init_mix()`. |
| `task_KeyGen` | Performs client-side key-generation round logic for `star` or `cc`. |

For `task_KeyGen` round `0`, the executor reads meta props from the incoming DXO and stores:

- `arch`
- `hide_result_from_server`
- `leader_client_name`
- `exclude_analyzing_clients`

When hidden-result routing is active, non-leader clients create and send ML-KEM public keys, while the leader client receives those keys and returns encrypted key packages.

## Analytics Runtime Integration

The job template does not register `HEExecutor`, `HEAggregator`, or `HEPersistor` directly in NVFlare config. Instead, it registers analytics subclasses:

| Template config | Registered path | Base class |
| --- | --- | --- |
| `app_client/config/config_fed_client.json` | `analytics_executor.AnalyticsExecutor` | `HEExecutor` |
| `app_server/config/config_fed_server.json` component `persistor` | `analytics_persistor.AnalyticsPersistor` | `HEPersistor` |
| `app_server/config/config_fed_server.json` component `aggregator` | `analytics_aggregator.AnalyticsAggregator` | `HEAggregator` |

`AnalyticsExecutor.execute()` first allows `HEExecutor` to handle HE tasks. If the task is not handled by the base class, the analytics executor dispatches to workflow-specific handlers such as:

- `_task_threshold_samples()`
- `_task_reference_stat_analytics()`
- `_task_stat_analytics()`
- `_task_enc_biomarker_disc()`
- `_task_profile_consolidate()`

`AnalyticsAggregator.aggregate()` similarly allows the base HE aggregator to handle `workflow_KeyGen`, then dispatches workflow-specific aggregation for threshold/reference/stat/encrypted-biomarker workflows.

`AnalyticsPersistor` extends the base persistor and adds workload/OpenFHE validation, metadata derivation from schema, broadcast model handling, PQC key-package injection, and result persistence.

## Config Values Required for Encrypted Execution

Encrypted execution is controlled by server config component args and workflow workload args.

### Persistor OpenFHE Args

The persistor component must include OpenFHE-related args. Current examples include:

| Arg | Meaning |
| --- | --- |
| `arch` | Key-generation architecture, usually `star`. |
| `is_server_data_owner` | Whether the server owns source data. The stager currently forces this to `false`. |
| `is_server_contributing_to_aggregation` | Whether the server contributes data to aggregation. The stager currently forces this to `false`. |
| `hide_result_from_server` | Enables hidden-result routing with PQC/AES payload delivery. |
| `leader_client_name` | Lead client for hidden-result and some HE routing behavior. Template value uses `{leader_client}` and configs often default to `site1`. |
| `exclude_analyzing_clients` | Client names that must not receive final stat-analytics result payloads. Injected by the stager from participation selections. |
| `non_contributing_clients` | Client names not contributing data to aggregation. Injected by the stager from participation selections. |
| `mult_depth` | CKKS multiplicative depth. |
| `scale_mod_size` | CKKS scale modulus size. |
| `scaling_technique` | CKKS scaling technique. |
| `key_switch_technique` | CKKS key-switch technique. |
| `ckks_data_type` | CKKS data type. |
| `generate_mult_keys` | Whether multiplication eval keys are required. |
| `generate_sum_keys` | Whether summation eval keys are required. |
| `generate_index_keys` | Whether rotation/eval-at-index keys are required. |
| `indices` | Rotation indices required for the selected workflow. |

### Workflow Args

The generated server config must include `workflow_KeyGen` before encrypted/stat analytics workflows. Analytics workflows use workload args such as:

| Workload arg | Meaning |
| --- | --- |
| `computation_type` | Analytics computation, such as `kaplan-meier` or `biomarker_enc_risk_group_computation`. |
| `global_schema` | Schema file name, usually `global_schema.json`. |
| `is_biomarker_discovery` | Marks biomarker discovery behavior for downstream analytics. |
| `cancer_type` | Cancer type used for biomarker model selection and analysis. |
| `model_key` / `model_keys` | Modeling method selection, such as `cox_lasso` or `logistic_reg`. |
| `group_column_id` | Group/risk-score column used by downstream analysis. |
| `time_column_id` | Survival time column. |
| `censoring_column_id` | Event/censoring column. |
| `time_grid_min`, `time_grid_step`, `time_grid_max` | Kaplan-Meier time-grid settings. |

## Job Staging Behavior

`NVFlareJobStager` prepares encrypted workflow config during job generation.

### Template Copy

The stager copies the selected job template from:

```text
app/core/job_runner/nvflare_jobs/jobs/{job_template_name}/
```

into the local generated job root. It removes any previous generated directory for that template before copying.

### Server Config Patching

The stager patches `app_server/config/config_fed_server.json` when it can parse the file as JSON. Current patching includes:

- `server.heart_beat_timeout = 120`
- `server.task_request_interval = 0.5`
- each workflow `args.min_clients = client_count`
- each workflow `args.wait_time_after_min_received = 0` (moot once `min_clients` = all clients)
- each workflow `args.task_check_period = 0.1`
- encrypted biomarker discovery train timeout when needed
- stat-analytics workflow expansion from submitted function config
- threshold workflow insertion when threshold config is submitted
- encrypted biomarker workflow insertion when an encrypted model is selected
- persistor OpenFHE arg updates

### OpenFHE Arg Calculation

`_update_persistor_openfhe_args()` finds the `persistor` component in server config and updates its `args`.

It always pushes participation-derived values into persistor args:

- `non_contributing_clients`
- `exclude_analyzing_clients`

It also currently forces server data-owner behavior:

- `is_server_data_owner = false`
- `is_server_contributing_to_aggregation = false`

Then it determines required cryptographic settings from submitted threshold/function configuration. Current logic includes:

| Computation | OpenFHE effect |
| --- | --- |
| protected threshold | Requires multiplication keys and depth based on number of data owners. |
| unprotected threshold | Requires at least depth `1`. |
| `mean` | Requires at least depth `2`. |
| `stdev` | Requires depth `3`, multiplication keys, index keys, and indices `[1, 2]`. |
| `chi2` | Requires multiplication keys, sum keys, and depth based on number of data owners. |
| `kaplan-meier` | Requires multiplication keys and depth based on number of data owners and group count from `global_schema.json`. |
| `t-test` | Requires depth `5`, multiplication keys, index keys, and indices `[1, 2, 8]`. |
| encrypted biomarker model | Requires encrypted-biomarker index-key settings from stager constants. |

If encrypted biomarker mode is active, the stager uses the encrypted-biomarker index list rather than the generic function-derived index list.

### Generated Runtime Files

The generated job includes the copied template runtime code plus generated/updated runtime files:

| Generated or patched file | Purpose |
| --- | --- |
| `app_server/config/config_fed_server.json` | Patched workflow/client/OpenFHE configuration. |
| `app_client/custom/filters.json` | Submitted filter/function/project/threshold payload for client runtime. |
| `app_server/custom/filters.json` | Same payload for server runtime. |
| `meta.json` | NVFlare job metadata with `deploy_map`, `min_clients`, and job name. |
| uploaded biomarker model artifacts under `app_server/custom/` | Written at runtime by `workflow_model_upload__<model_key>`. Encrypted workflows write encrypted artifacts plus required non-secret metadata such as LCS `ER_threshold`. |

The client config template already registers `task_enc_biomarker_disc`, so encrypted biomarker workflows can be inserted by server config without changing the client executor registration.

## Encrypted Biomarker Workflow

Encrypted biomarker discovery is represented by workflow IDs such as `workflow_enc_biomarker_disc_1` and task name `task_enc_biomarker_disc`.

The workflow workload args include:

- `computation_type: biomarker_enc_risk_group_computation`
- `global_schema: global_schema.json`
- `cancer_type`
- `model_keys`

The analytics executor handles encrypted biomarker discovery through `_task_enc_biomarker_disc()`. The OpenFHE manager contains helper paths for encrypted model-weight handling, encrypted risk-score computation, masking, partial-decrypt handling, and score extraction.

For model-specific submissions, `NVFlareJobStager` expands selected model keys and stages model-file source metadata for initiator-side runtime upload. Model key examples include:

- `cox_lasso`
- `logistic_reg`

## Result Visibility and Excluded Analyzing Clients

Participation selections flow into encrypted runtime behavior through the stager:

- clients excluded from contribution are written to `non_contributing_clients`
- clients excluded from analysis/result visibility are written to `exclude_analyzing_clients`

`HEExecutor`, `HEPersistor`, `AnalyticsExecutor`, and `AnalyticsPersistor` all carry or use `exclude_analyzing_clients` in hidden-result and result-routing paths. The leader client cannot be listed in `exclude_analyzing_clients`; `HEPersistor` raises a `ValueError` if that condition occurs.

When `hide_result_from_server` is false, excluded analyzing clients can still affect whether final result payloads are sent to a client. When `hide_result_from_server` is true, excluded analyzing clients are also skipped during PQC key registration/package injection.

## Current Example Configs

Current config files under `jobs/configs/` include OpenFHE/key-generation oriented examples:

| File | Notable encrypted/OpenFHE behavior |
| --- | --- |
| `config_template.json` | Baseline OpenFHE-enabled stat analytics template with `workflow_KeyGen`. |
| `config_survival_hide_from_server.json` | Enables `hide_result_from_server: true` and sets `leader_client_name`. |
| `config_mean.json`, `config_standard_deviation.json`, `config_t_test.json`, `config_chi_square_test.json`, `config_survivability_analysis.json`, `config_survival_biomarker_discovery.json` | Include `workflow_KeyGen` and `workflow_stat_analytics` with OpenFHE-compatible persistor configuration. |
| `example_threshold_samples_check.json` | Includes key generation plus threshold sample workflows. |
| `example_all_functions.json` | Shows multiple stat analytics workflows sharing the OpenFHE key-generation setup. |

## Failure Modes

| Failure mode | Where it occurs | Current behavior |
| --- | --- | --- |
| Crypto context used before initialization | `OpenfheManager` serialization/keygen helpers | Raises an exception such as `CryptoContext not initialized`. |
| Keypair required but missing | `serialize_dict()` / key helpers | Raises an exception when context or keypair is missing. |
| Unsupported architecture | `HEAggregator`, `HEExecutor`, `HEPersistor` | Raises for unsupported `arch` values. |
| Invalid key-generation round | `HEAggregator` / `HEExecutor` round handlers | Raises for unexpected rounds. |
| `exclude_analyzing_clients` is not a list/tuple | `HEPersistor.__init__()` | Raises `TypeError`. |
| `leader_client_name` appears in `exclude_analyzing_clients` | `HEPersistor.__init__()` | Raises `ValueError`. |
| PQC helper called from wrong role | `PQCRoutingManager` | Raises `RuntimeError`. |
| AES payload decrypt before session key is established | `PQCRoutingManager.decrypt_payload()` | Raises `ValueError`. |
| Missing key package or malformed key package | `AnalyticsExecutor.execute()` | Logs a warning if key-package processing fails. |
| Missing or unparseable server config JSON | `NVFlareJobStager._update_server_config_text()` | Returns `None`; staging leaves the template config unchanged unless the patching operation itself raises. |
| Missing job template directory | `NVFlareJobStager._build_local_job_dir()` | Raises `FileNotFoundError`. |
| Missing model source on initiator | Runtime `workflow_model_upload__<model_key>` | The upload workflow fails when the initiator/leader site cannot read a saved model path. |

## Security and Current-State Notes

- OpenFHE execution settings are controlled through generated NVFlare server config, not through direct API requests to `openfhe_manager.py`.
- The server config template currently includes `hide_result_from_server: true` and a `{leader_client}` placeholder in persistor args. Function-specific config examples vary and may omit hidden-result mode.
- The stager rewrites selected persistor settings based on job submission, selected functions, thresholds, participation choices, and encrypted biomarker detection.
- PQC routing protects final hidden plaintext payload delivery from server visibility, but the server still orchestrates NVFlare workflow rounds and routes encrypted packages/payloads.
- Crypto audit information is written through the `custom.audit_log` logger from `OpenfheManager.initialize_openfhe()`.
- Encrypted runtime files are copied into each generated job from the template/runtime asset tree, so code changes under `apis/`, `app_client/custom/`, or `app_server/custom/` affect future staged jobs.
