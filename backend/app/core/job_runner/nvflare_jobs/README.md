# NVFlare jobs (`nvflare_jobs`)

Federated analytics jobs (Kaplan–Meier, encrypted biomarker discovery, etc.) for the Duality NVFlare stack. This folder contains **APIs**, **workflows**, the **job template**, the **simulator driver**, and CI wheel build support.

For this public OpenFHE snapshot, **standalone and simulator runs use a local `duality_nvflare_lib` wheel only**. The bundled standalone wheel is staged into the NVFlare/client containers, and simulator tooling builds/installs the wheel from this checkout. These supported public modes do not select a newer `duality_nvflare_lib` from the GitLab package registry.

---

## The runtime wheel

The job template's custom code imports the runtime as `duality_nvflare_apis` and
`duality_nvflare_workflows`, and `duality_wheel_runtime.py` checks with `importlib.metadata` that a
distribution named `duality_nvflare_lib` is installed before it builds any component. The source
directories here are named `apis/` and `workflows/`; the wheel builder renames them on packaging.
Putting this directory on `PYTHONPATH` therefore does **not** make those imports resolve. The wheel
has to be pip-installed into the active environment, either the prebuilt copy under
`standalone/wheels/` (see the root README's Simulation section) or one rebuilt from this checkout
as below.

After changing anything under **`apis/`** or **`workflows/`**, rebuild the local snapshot wheel before running standalone/simulator tests. Deployment packaging outside these supported public modes is the deployer's responsibility.

```sh
python3 wheels/APIWheelBuilderCI.py --root . --out-dir wheels
python3 -m pip install --force-reinstall --no-index --no-deps wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
```

Server/client **custom** Python under `jobs/nvflare_job_template/.../custom/` ships with the job folder; copy a fresh template (or re-stage your job) so the simulator picks up edits there.

### Biomarker somatic gene columns (multi-gene)

Kaplan–Meier, χ², and *t*-test style workloads can use **`group_column_id`** / category columns for **any gene** listed in **`apis/fhir/biomarker_gene_columns.py`** as **`BIOMARKER_GENE_COLUMNS`**, not only PBRM1. **`filter_engine`** and the FHIR analysis engines use that set; FHIR **`config/project_*/analysis_data.json`** and **`analysis_query.json`** keep a single **`pbrm1`** template row per property, and the loaders **expand** it to all listed genes at load time (so e.g. **`group_column_id: tp53`** works without duplicating JSON per gene).

The job template **`jobs/nvflare_job_template/.../custom/global_schema.json`** defines matching **MUT** / **WT** categorical columns for federated analytics—**keep that list aligned** with **`BIOMARKER_GENE_COLUMNS`** when you add or remove genes.

Implementation detail: `apis/fhir/filter_engine.py` and the analysis engines under `apis/fhir/`; see `documentation/backend/14-fhir-filtering-and-analysis-engines.md`.

---

## Local simulation (multi-site, one machine)

Use the **NVFlare simulator** to run a workflow graph locally for fast iteration—**no UI** required. By default it runs KeyGen → open-access biomarker Kaplan–Meier (HE) → clear-text reference Kaplan–Meier; `--server-config tests/sim_config_fed_server_<chain>.json` selects any of the sweep chains (`km`, `lcs`, `combined`, each `_open` or `_enc`).

### Host environment

Bare-host simulator runs and the pytest sweep need a virtual environment whose Python matches an `openfhe` build. PyPI ships each release twice as `py3-none-any` wheels that each embed one CPython extension: `.22.4` (CPython 3.10 extension, built on Ubuntu 22.04, `Requires-Python >=3.10`) and `.24.4` (CPython 3.12 extension, built on Ubuntu 24.04, needs glibc 2.38 and GCC 13's libstdc++, `Requires-Python >=3.12`). Use the OS default interpreter: **Python 3.10 on Ubuntu 22.04** or **Python 3.12 on Ubuntu 24.04**. `requirements-simulator.txt` pins both builds behind `python_version` environment markers, so the same file installs `openfhe==1.5.1.0.22.4` under 3.10 and `openfhe==1.5.1.0.24.4` under 3.12 with no editing. The markers exist because the `.22.4` wheel's `Requires-Python >=3.10` would otherwise let pip install it on 3.12, where its extension cannot load. There is no build for Python 3.11 or 3.13. The Docker images run Python 3.12 and get the `.24.4` build; the backend and its tests use Python 3.12 (see the root README).

```sh
python3 -m venv .venv && . .venv/bin/activate              # from the repo root; python3 is 3.10 on 22.04, 3.12 on 24.04
cd backend/app/core/job_runner/nvflare_jobs
pip install -r requirements-simulator.txt                  # pinned runtime deps; openfhe build chosen by interpreter
pip install --no-deps ../../../../../standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
pip install -r tests/requirements-test.txt                 # pytest sweep only
python -c "import openfhe"                                 # sanity check: the compiled extension loads
```

Use `pip install --force-reinstall --no-index --no-deps wheels/duality_nvflare_lib-*.whl` instead of the bundled-wheel line when testing a locally rebuilt wheel. `liboqs-python` needs the native liboqs library: on first import it clones and builds it into `~/_oqs` (needs `cmake`, `ninja-build` or `make`, a C compiler, `libssl-dev`, `git`); `standalone/docker_stage/nvflare.Dockerfile` shows the equivalent prebuilt install.

### Quick start

```sh
# from the repository root, in a virtualenv that has the bundled wheel installed
pip install standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
cp standalone/default.env.local standalone/.env.local   # per-site datasource paths, loaded by run_simulator.py
cd backend/app/core/job_runner/nvflare_jobs
python3 scripts/run_simulator.py -w outputs/stat_analytics -n 3 -t 3 jobs/nvflare_job_template --datasource-version 2_1
```

Use `-n 3` (or `-c site1,site2,site3`): the leader client is `site3`. Use `--datasource-version 2_1` for the biomarker project (the public snapshot ships datasource group `1`, MSKChord, only). For General Statistics use `--datasource-version 1`, which reads the ungrouped `DUALITY_*_DATASOURCE_1` bundles (`standalone/nvflare_stage/data/Survivability_FHIR_Data_part{1,2,3}.json`, extracted from the committed zips); because the template ships the project 2 `app_server/custom/global_schema.json`, copy the job template, replace that file with `global_schema/project_1/global_schema.json`, and give the stat workflow General Statistics `workload_args` (for example `computation_type: kaplan-meier`, `group_column_id: PBRM1`, `time_column_id: OS`, `censoring_column_id: OS_CNSR`, plus `time_grid_min/step/max`). The template's `config_fed_server.json` intentionally has no `computation_type` (the backend stager fills it per submitted function and would inherit any default placed there), so `run_simulator.py` stages a copy of the template under `<workspace>_staged_job` with the selected server config and exits non-zero if the run aborts.

| Flag | Meaning |
|------|--------|
| **`-w`** | Simulator workspace / output root (e.g. `outputs/stat_analytics`). |
| **`-n`** | Number of simulated clients (sites). |
| **`-t`** | Thread count for parallel client execution. |
| **`job_folder`** | Path to the job definition (often `jobs/nvflare_job_template`). |
| **`--datasource-version N`** | Selects the suffix on datasource env vars (`..._DATASOURCE_N`). Overrides the in-script default when passed. |
| **`--server-config JSON`** | Server config to run instead of the job folder's own (see `tests/sim_config_fed_server_*.json`). Defaults to the open-access KM config when the job's stat workflow has no `computation_type`. |

Edit **`jobs/nvflare_job_template/app_server/config/config_fed_server.json`** (and related configs) to set **`workload_args`** (e.g. **`computation_type`**, **`cancer_type`**).

**Biomarker Cox/LASSO (Kaplan–Meier with `is_biomarker_discovery`, or encrypted biomarker discovery):** do **not** embed **`scale_coeff_file_path`** / **`cutoff_file_path`** in JSON. Weights and cutoffs are resolved from **`MODEL_DIR_<N>`** (same **`N`** as **`--datasource-version`**) or legacy **`MODEL_DIR`**, with files named **`{model_key}_{cancer_type}_weights.csv`** and **`_cutoff.csv`**.

| Workflow | Parameter | Meaning |
|----------|-----------|--------|
| **`workflow_enc_biomarker_disc`** (`biomarker_enc_risk_group_computation`) | **`model_keys`** | Non-empty **list**, e.g. **`["cox_lasso"]`** or **`["cox_lasso", "logistic_reg"]`**. One run encrypts patient gene data once and computes masked risk scores for **every** listed model. |
| **`workflow_stat_analytics`** / **`workflow_reference_stat_analytics`** (Kaplan–Meier + **`is_biomarker_discovery`**) | **`model_key`** | Single model id (e.g. **`logistic_reg`**) for that analysis—must match an enc job **`model_keys`** entry when using persisted encrypted scores. |

See `documentation/backend/15-biomarker-and-analytics-workflows.md` for the encrypted multi-model flow and `apis/utils.py` (`resolve_biomarker_model_paths`) for the file-naming rules.

**Batch script:** **`scripts/run_bio_all_cancers.sh`** sweeps **`cancer_type`** only; set **`model_keys`** in **`config_fed_server.json`** before running (no per-model outer loop).

### Environment and data

**`run_simulator.py`** sets **`FL_IS_SIMULATOR=true`** and loads **`.env.local`** when present. Search order: `DUALITY_SIM_ENV_FILE`, then `./.env.local` in the current directory, then the first `.env.local` or `standalone/.env.local` found walking up from the script directory. Variables already set in the shell are never overwritten.

**Per-site FHIR JSON** in simulation (unset **`DUALITY_NVFLARE_FHIR_BASE`** if you want different files per site):

| Role | Variable pattern |
|------|------------------|
| Server / initiator | `DUALITY_SERVER_DATASOURCE_<N>` |
| Client `site-1`, `site1`, … | `DUALITY_CLIENT_SITE1_DATASOURCE_<N>` |
| More sites | `DUALITY_CLIENT_SITE2_DATASOURCE_<N>`, … |

**`<N>`** defaults to **`2_1`** (or **`DEFAULT_SIM_DATASOURCE_VERSION`** / **`DUALITY_SIM_DATASOURCE_VERSION`** / **`--datasource-version`**).

Paths may be relative; resolution uses **`DUALITY_SIM_DATASOURCE_BASE`** or walks upward from the process **cwd** until the file exists.

**Biomarker models:** **`MODEL_DIR_<N>`** (e.g. **`MODEL_DIR_2`**, **`MODEL_DIR_3`**) uses the same **`<N>`** as **`DUALITY_*_DATASOURCE_<N>`**, so **`--datasource-version`** switches both FHIR JSON and model weights/cutoffs. If **`MODEL_DIR_<N>`** is unset, **`MODEL_DIR`** is used as a fallback.

**Standalone (Docker):** model files are not read from `MODEL_DIR_*`. `create_client.py` copies `standalone/client_utils/model_files/` into the initiator container at `/data/model_files`, and the backend seeds the initiator's User Settings with those paths; `workflow_model_upload` stages them into the job workspace at job time (see `documentation/standalone/09-local-datasource-staging-and-runtime-lookup.md`).

**Optional:** **`DUALITY_SIM_ENV_FILE`** — explicit path to an env file to load.

**Cohort / filters:** If there is no UI-generated **`custom/filters.json`**, simulation still applies **`cancer_type`** from **`workload_args`** as a **`PATIENT_DATA`** filter when **`FL_IS_SIMULATOR`** is set (see changelog).

**Backend HTTP:** Simulator runs normally skip POSTs to **`DUALITY_BACKEND_URL`** (avoids noise to a dummy URL). To exercise a real backend API from the simulator:

```sh
export DUALITY_SIM_ENABLE_BACKEND_HTTP=1
export DUALITY_BACKEND_URL=https://your-backend/...
```

### Rebuild the wheel from source and simulate

```sh
python3 wheels/APIWheelBuilderCI.py --root . --out-dir wheels \
  && python3 -m pip install --force-reinstall --no-index --no-deps wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl \
  && python3 scripts/run_simulator.py -w outputs/stat_analytics -n 3 -t 3 jobs/nvflare_job_template --datasource-version 2_1
```

The job runtime never installs or upgrades `duality_nvflare_lib` from a package index; whatever is installed in the active environment is what runs.

---

## Deployment vs simulation

| Aspect | Deployment (sites / UI) | Local simulation |
|--------|-------------------------|------------------|
| **`FL_IS_SIMULATOR`** | Unset | Set by `run_simulator.py` |
| FHIR path | Often **`DUALITY_NVFLARE_FHIR_BASE`** per party | **`DUALITY_*_DATASOURCE_<N>`** + path resolution |
| Filters | From **`filters.json`** / UI | **`cancer_type`** from **`workload_args`** when filters file missing |
| Progress webhooks | POST to real **`DUALITY_BACKEND_URL`** | Skipped unless **`DUALITY_SIM_ENABLE_BACKEND_HTTP=1`** |

### Model upload (`workflow_model_upload`)

Biomarker workflows need the Cox-LASSO / logistic model (**`coef`** + cutoff) on the **server side**. **`workflow_model_upload`** stages it there exactly once: it runs **after `workflow_KeyGen`** and **before the first biomarker consumer** (encrypted discovery, or **`workflow_stat_analytics`** with **`is_biomarker_discovery`**). The **leader client** supplies the model and the server writes it into **`{job_id}/app_server/custom/`**, so the **write** location and the consumer's **read** location are identical in both simulator and deployment.

Two modes, chosen by **`model_type`**:

| Mode (`model_type`) | Leader sends | Server writes to `app_server/custom/` | Consumer |
|---------------------|--------------|----------------------------------------|----------|
| **`Open-access`** | raw **`weights_csv`** / **`cutoff_csv`** bytes | **`{model_key}_{cancer_type}_weights.csv`** + **`_cutoff.csv`** | clear-text Kaplan–Meier (**`is_biomarker_discovery`**) |
| **`Encrypted`** | OpenFHE ciphertexts of the (scaled) coeffs/cutoff + per-model **`rsf`** | **`{model_key}_{cancer_type}_coeff.ct`** + **`_cutoff.ct`** + **`_scale.json`** (`{"rsf": …}`) | **`workflow_enc_biomarker_disc`** |

Key points:

- **Encrypted mode never exposes the plaintext model to the server.** The leader encrypts each model under the **multiparty public key** (after KeyGen) at the **same CKKS level** the discovery round uses, via **`OpenfheManager.encrypt_biomarker_model`** — the packing/encryption that previously ran server-side now runs on the leader. The server only persists opaque ciphertext bytes.
- **`leader_client_name`** is the only client that uploads (non-leaders return an empty payload); it must match the persistor / executor leader name. Set it in **`config_fed_client.json`** executor args.
- **Filenames preserve spaces** in **`cancer_type`** on both write and read — do not substitute underscores.
- **Source models** still come from **`MODEL_DIR_<N>`** / discovery (see *Local simulation* above): the leader reads those CSVs to build the upload. Model upload only changes **where the consumer reads from** (the staged job-workspace artifacts), resolved by **`resolve_biomarker_model_paths`** (CSV) and **`resolve_encrypted_biomarker_model_paths`** (`.ct`).
- If **`workflow_enc_biomarker_disc`** runs without a prior Encrypted upload, the persistor raises a clear **`FileNotFoundError`**.

| Where | What to set |
|-------|-------------|
| **Simulator / hand-edited jobs** | The stager auto-inserts the workflow for backend-staged jobs; for hand-edited simulator jobs, add a **`workflow_model_upload`** block (1-round **`customSAG`**, **`task_model_upload`**) before the consumer, with **`workload_args.model_keys`** / **`cancer_type`** / **`model_type`**. |
| **Backend-staged jobs (UI / API)** | Automatic: **`NVFlareJobStager._insert_model_upload_workflow`** inserts it after KeyGen and before the consumer, deriving **`model_keys`** / **`cancer_type`** / **`model_type`** from the function config. Idempotent and skipped when no biomarker consumer is present. |

Details: `documentation/backend/15-biomarker-and-analytics-workflows.md` and `documentation/backend/18-openfhe-and-encrypted-workflows.md`.

### Non-contributing clients (`non_contributing_clients`)

Some sites may **observe** a federated HE result without mixing their ciphertext into the round-0 aggregate.

| Where | What to set |
|-------|-------------|
| **Simulator / hand-edited jobs** | Persistor **`args`** in **`jobs/nvflare_job_template/app_server/config/config_fed_server.json`**: **`"non_contributing_clients": ["site3"]`**. Use **`[]`** (or omit) so every site contributes ciphertext. |
| **Backend-staged jobs (UI / API)** | Same key inside submit payload **`workflow_group_data`**; **`NVFlareJobStager`** copies it into the staged persistor **`args`** when the key is present. |

Names must match each site’s NVFlare **client name** exactly. Affected tasks: **`task_stat_analytics`** (skip encrypt after preprocess) and **`task_threshold_samples_unsecure` / `task_threshold_samples_secure`** (skip round 0 encrypt path). Decrypt / later rounds still run on those sites.

Details and threshold caveats: `documentation/backend/13-participation-and-client-state.md`.

### Excluding clients from the final result (`exclude_analyzing_clients`)

Some sites may **take part** in homomorphic aggregation and distributed decrypt **without receiving** the final federated cleartext (or PQC-routed payload when **`hide_result_from_server`** is true). Think of it as the **client-side analogue of `is_server_contributing_to_aggregation` on the server**: the server can own data yet opt out of **mixing** into the aggregate; here a client can run the protocol yet opt out of **receiving** the combined analytic outcome. The **leader** cannot be listed (the leader fuses partial decrypts and, when applicable, builds per-client PQC payloads).

| Where | What to set |
|-------|-------------|
| **Simulator / hand-edited jobs** | Persistor **`args`** in **`jobs/nvflare_job_template/app_server/config/config_fed_server.json`**: **`"exclude_analyzing_clients": ["site-1"]`**. Use **`[]`** (or omit) so every site receives the final result. |
| **Backend-staged jobs (UI / API)** | Same key inside submit payload **`workflow_group_data`** when your staging layer merges it into the persistor **`args`** in **`config_fed_server.json`** (parallel to **`non_contributing_clients`**). |

Applies to **`workflow_stat_analytics`** only. **`non_contributing_clients`** and **`exclude_analyzing_clients`** address different axes (contribute ciphertext vs receive final result); see `documentation/backend/13-participation-and-client-state.md`.

### Profile summaries at the leader (initiator)

Each site’s backend normally only ingests that site’s artifacts. **`profile_summary.json`** (from **`duality_nvflare_apis.profiler.Profiler`**) is written per party at job end and, for consolidation, flushed **before** the tail workflow so it exists on disk when clients read it.

| Piece | Role |
|-------|------|
| **`workflow_consolidate_profile_summaries`** | Optional last workflow in **`config_fed_server.json`**: a **2-round** **`customSAG`** with **`task_profile_consolidate`**. |
| **Round 0** | Every client reads **`job-results/<job_id>/profile_summary.json`** and returns it to the server. **`ProfileSummaryAggregator`** merges client payloads and the server’s own file into **`by_site`**. |
| **Round 1** | Server sends the merged object **only to `leader_client_name`** (same initiator/leader as persistor HE routing). The leader client writes **`job-results/<job_id>/profile_summaries_all_sites.json`**. |
| **`ProfileSummaryPersistor`** | Stub global model so this workflow does not broadcast the full HE **`AnalyticsPersistor`** state. |
| **`PROFILE_SNAPSHOT_EVENT`** | NVFlare fires **`START_WORKFLOW` on the server only**; clients fire this event from **`task_profile_consolidate`** round 0 so **`Profiler`** flushes to disk before the read. |

**Client template:** register **`task_profile_consolidate`** on **`AnalyticsExecutor`** and keep **`Profiler`** on the client app. **`ProfileSummaryAggregator` / `ProfileSummaryPersistor`** live in **`apis/profiler.py`** (same wheel as **`Profiler`**).

Details: `documentation/backend/21-observability-logging-and-troubleshooting.md`.

**Backend-staged jobs:** **`NVFlareJobStager._build_stat_analytics_workflows`** rewrites the workflow list from **`functions_map`**. It **appends** **`workflow_consolidate_profile_summaries` after every generated `workflow_stat_analytics_*`** so consolidation still runs **last** (simulator jobs that skip staging keep template order as authored).

---

## Encrypted biomarker risk groups: parallel worker throttling (server)

For **`computation_type: biomarker_enc_risk_group_computation`**, the server runs patient-batch work in a **`ProcessPoolExecutor`**. **`max_workers`** is chosen automatically on **Linux** from **`MemAvailable`** (`/proc/meminfo`) using **fixed MiB budgets** (not runtime profiling). Defaults are **conservative**; adjust env vars if a host runs out of memory or leaves too much RAM unused.

**Default static budgets (MiB):**

| Role | Default | Env override |
|------|---------|----------------|
| Base (parent + main OpenFHE + SHM overhead) | **1536** | `OPENFHE_BIOMARKER_BASE_RAM_MB` |
| Per worker (after `worker_init`) | **1024** | `OPENFHE_BIOMARKER_PER_WORKER_RAM_MB` |
| OS / NVFlare reserve | **512** | `OPENFHE_BIOMARKER_OS_RESERVE_MB` |
| Max workers (auto cap) | **32** | `OPENFHE_BIOMARKER_MAX_WORKERS_CAP` |
| Workers if `MemAvailable` unavailable | **10** | `OPENFHE_BIOMARKER_MAX_WORKERS_MEM_FALLBACK` |

**Auto formula:**  
`MAX_WORKERS = min(cap, max(1, (MemAvailable − base − reserve) // per_worker))`. If the budget is non-positive, **`MAX_WORKERS = 1`**.

_A CPU core-cap is also applied: **`MAX_WORKERS = min(cores, cap, mem-budget)`**, where **`cores`** is the process's schedulable CPU set (**`len(os.sched_getaffinity(0))`**, so container cpuset / cgroup CPU limits are respected), and the memory budget prefers a cgroup memory limit over `MemAvailable` when one is set._

**Fixed override:** set **`OPENFHE_BIOMARKER_MAX_WORKERS`** to skip auto.

**Assumptions:** `MemAvailable` is an estimate of reclaimable memory, not a hard guarantee. Non-Linux environments use the **fallback** worker count. Tune **`OPENFHE_BIOMARKER_*`** from measured RSS on your target hosts if needed.

**Reference profiling (serialized sizes, one development run):** temporary helpers once logged shared-memory component sizes and per-task patient ciphertext bytes. They are **not** in current **`openfhe_manager.py`** (v1.2.6+ ships throttling only). Example numbers from that session:

| Item | Observed |
|------|----------|
| Serialized **cc** / **coeff** / **cutoff** / **multkey** / **indexkeys** | ~1 KiB / ~2.5 MiB / ~2.5 MiB / ~22.5 MiB / ~225 MiB |
| **Total** shared serialized blobs | **~252.5 MiB** |
| **Per pool task** (patient ciphertext bytes, chunk of 2) | **~5 MiB** total (~2.5 MiB per patient ciphertext) |

Use this as **scale context** (indexkeys dominate SHM; per-task payload grows with **`CHUNK_SIZE`**). **Auto `MAX_WORKERS`** still uses the **static MiB** table above, not these figures. For **RSS**, measure **`VmRSS`** on the server process and workers on each host.

Implementation: **`apis/openfhe_manager.py`** (`resolve_biomarker_max_workers`). External biomarker model paths and **`model_key`** resolution: `apis/utils.py` (`resolve_biomarker_model_paths`).

---

## Further reading

- **`documentation/backend/`** — 11 (job lifecycle), 12 (job packaging and templates), 13 (participation and client state), 15 (biomarker and analytics workflows), 18 (OpenFHE and encrypted workflows), 21 (observability).
- **`docs/`** — sequence diagrams for key generation, encrypted biomarker discovery, stat analytics, the threshold gate, and PQC result routing.
- **`run_simulator.py`** — comments on env defaults and datasource CLI.
