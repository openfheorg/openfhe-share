# SHARE — Secure Healthcare Data Collaboration Platform

SHARE lets multiple healthcare institutions run joint statistical and biomarker analyses over
their patient data **without any site ever exposing its records**, and, in encrypted mode,
without the aggregating server ever seeing the intermediate values or the analytic model.

Each participating site keeps its data behind its own firewall, either in a live FHIR server or
in a local FHIR bundle. An initiating site composes an analysis in the web UI — a cohort filter,
one or more statistical functions, a set of participating sites — and submits it. The platform
compiles that request into an [NVFlare](https://github.com/NVIDIA/NVFlare) federated job, ships it
to the sites, and each site computes locally on its own patients. Only encrypted partial results
travel over the wire; the final aggregate is reconstructed through multi-party decryption and
delivered to the sites entitled to see it. The security of those computations rests (among other
tools) on homomorphic encryption from
[OpenFHE](https://github.com/openfheorg/openfhe-development), the public open-source FHE library.

---

## Contents

- [What the platform can do](#what-the-platform-can-do)
- [Disclaimer](#disclaimer-research-prototype-not-for-production-use)
- [Supported data](#supported-data)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Running SHARE](#running-share)
  - [Simulation](#1-simulation-fastest-loop-no-ui)
  - [Standalone](#2-standalone-full-local-stack-in-docker)
  - [Production deployment (not supported)](#3-production-deployment-not-supported-in-this-version)
- [Documentation](#documentation)
- [Contributors](#contributors)
- [Use of AI assistance](#use-of-ai-assistance)
- [License](#license)

---

## What the platform can do

### Federated analyses

| Analysis | Computation type | What it produces |
| --- | --- | --- |
| Mean | `mean` | Federated mean of a numeric column. |
| Standard deviation | `stdev` | Population or sample standard deviation. |
| Chi-square test | `chi2` | χ² statistic and p-value over a federated contingency table, with degenerate-table handling. |
| T-test | `t-test` | `t_score`, degrees of freedom, and p-value for a numeric column split by a two-category field. |
| Survival curve | `kaplan-meier` | Kaplan-Meier survival curves (`S_output` over `times`), optional confidence intervals, and a two-group log-rank test. |
| Biomarker risk-group discovery | `biomarker_enc_risk_group_computation` | Encrypted per-patient risk scores from a prognostic model, consumed by a downstream Kaplan-Meier workflow. |
| Exceptional response discrimination | `meta-analysis` | Federated odds ratio per standard deviation of predictive model score for exceptional response, pooled across sites. |

The flagship pipeline is **biomarker model validation for cancer prognosis**: an initiating site
trains a penalized model on its own cohort — Lasso Cox regression on mutation burden gene features
with unpenalized clinical covariates, or Lasso logistic regression for exceptional responders —
and then validates it across the federation. Participating sites score their own patients against
the model, split into high-risk and low-risk arms, and contribute to a federated survival curve
and log-rank test that tests whether the initiator's hypothesis generalizes. Any generalized 
linear model can be supported in this pipeline.

### Privacy technology

Four layers protect a run, in the order data moves through it: the computation is encrypted, the
values that must be decrypted are masked first, the final result is routed only to its intended
recipients, and disclosure controls decide who may take part and what may be released at all.

#### Encrypted computation

- **Homomorphic encryption (OpenFHE / CKKS scheme).**
  Sites encrypt local statistics before they leave the machine. The server aggregates in
  the ciphertext domain and never holds a key that can open a single site's contribution.
- **Multi-party key generation.** No single party holds the decryption key. The final aggregate is
  recovered only by fusing partial decryption shares from every participant, so no one, server
  included, can decrypt unilaterally.
- **Encrypted models.** A biomarker model can be uploaded to the federation *encrypted* under the
  multi-party public key. The server computes risk scores homomorphically against it. Open-access
  mode, where the model is shared in the clear, is also supported.

#### Masking the values that get decrypted

CKKS evaluates additions and multiplications natively, but **divisions and comparisons are
expensive and imprecise under encryption**: they must be approximated by high-degree polynomials
that burn multiplicative depth and precision. The approximation is weakest near zero or near a 
decision boundary. Nearly every statistic here ends in one or the other, e.g., a ratio of aggregated 
sums, or a risk score tested against a cutoff.

Rather than evaluating those operations homomorphically, we decrypt the *factors* — the
aggregated numerator and denominator, or the score-minus-cutoff difference — and finish the
division or comparison in the clear. That is only safe if the decrypted factors themselves reveal
nothing, which is what masking provides. Masks are applied under encryption, before any partial
decryption, so what is decrypted is never the true intermediate value. Both families below cancel
exactly in postprocessing and leave the reported result unchanged.

- **Multiplicative masks** hide *magnitude* and *sign*. Random log-normal factors scale the aggregated
  numerator and denominator of a statistic. Because the statistic is a ratio and both terms carry
  the same factor, it divides out on the way to the answer, while the absolute size of the sums,
  and, through separately masked slots, the global cohort size, stays hidden from whoever fuses
  the shares.
- **Additive shares of zero** hide *individual terms*. Random offsets drawn so they sum to zero
  across the grid or table are added to each cell or time point. Any single decrypted term is
  therefore blinded, but the aggregate is unaffected because the shares cancel. Kaplan-Meier
  log-rank terms and chi-square contingency cells both use these. The mask magnitude is a
  deliberate trade: larger masks blind more but consume CKKS precision.
- **Per-slot biomarker score masks** hide *the model and the scores*. Encrypted risk scores carry
  a per-slot multiplicative mask calibrated so the score magnitudes reveal nothing about the
  encrypted model, plus an independent mask on each site's own slice so the lead client cannot
  read another site's per-patient scores while fusing.

#### Result delivery

- **Post-quantum result routing.** With `hide_result_from_server` enabled (the default), final
  plaintext results never pass through the server at all. A lead client fuses the decryption
  shares and routes a separate sealed payload to each entitled recipient. The channel uses
  ML-KEM-1024 key encapsulation via [liboqs](https://github.com/open-quantum-safe/liboqs-python)
  (Open Quantum Safe), with HKDF-SHA256 key derivation and AES-256-GCM payload encryption from
  [pyca/cryptography](https://github.com/pyca/cryptography). The server routes opaque ciphertext
  and never holds a session key.

#### Disclosure controls

- **Minimum-cohort thresholds.** A job can require a minimum global sample count before any result
  is released. The check itself runs either in the clear at the server (`EXPOSED`) or under encryption
  (`PROTECTED`), so the per-site counts stay hidden even while the gate is evaluated.
- **Participation controls.** Per job, a site can be marked *non-contributing* — it takes part in
  the protocol but mixes no data into the aggregate — or *excluded from analysis* — it helps compute
  and decrypt but never receives the final result. The two axes are independent. (Note that for the 
  model validation workflows, the initiating site should not contribute its data to the aggregation, 
  if the models were trained on that data.)
- **Crypto audit trail.** Every encrypted run records its security level, ring dimension, batch
  size, scaling and key-switch techniques, and multiplicative depth to an audit log.

### Governance and operations

- Role-based access: `INITIATOR`, `CLIENT`, `OBSERVER`, `ADMIN` is scoped per project.
- Reusable, hashed, project-scoped cohort filters, deduplicated across submissions.
- Live job status over websockets, full job history, and per-workflow result reports and exports.
- Per-site startup-kit delivery, workspace management, and a local Results API so each site keeps
  its own copy of its results.
- Built-in runtime profiling, consolidated across sites into a single per-job summary.

---

## Disclaimer: research prototype, not for production use

**SHARE is a research and demonstration prototype. It is not a product, it has not been
security-audited or independently reviewed, and it must not be deployed against real patient data
or in any setting where a privacy failure would cause harm.**

In particular:

- **Authentication is a placeholder.** Login is a username lookup with no password validation, and
  most API routes perform no authorization checks. Site startup kits, which carry site
  credentials, are served over an endpoint that does not yet derive the authorized site from
  authenticated credentials. Treat every deployment as trusted-network-only.
- **Repeated queries against the same cohort leak information.** The privacy guarantees here cover
  a *single* computation. Running many analyses over the same underlying data, e.g., varying a filter,
  re-running with one site added or removed, sweeping a parameter, lets an observer difference
  the results and recover information about individual records that no single result would have
  revealed. There is no query budget, no composition accounting, and no protection against this.
  Limit the number of analyses run against any one cohort, and treat a series of related jobs as
  disclosing substantially more than any one of them.
- **The masking schemes trade privacy against numerical precision** and are tuned empirically for
  the workloads exercised here. Their parameters are not backed by a formal end-to-end privacy
  proof.
- **Not a medical device.** Nothing here is validated for clinical use, diagnosis, or treatment
  decisions. Results are for research and methodological evaluation only.
- **No warranty.** The software is provided as-is, without warranty of any kind, express or
  implied.

---

## Supported data

### Source modes

Every site resolves to exactly one **patient data source** per project and datasource group:

| Mode | Input | Behavior |
| --- | --- | --- |
| **FHIR server** | An `http(s)://` FHIR base URL | The runtime issues FHIR REST searches, follows pagination, and fetches related resources by subject ID in batches. |
| **Local FHIR bundle** | A path to a `.json` Bundle | The bundle is indexed in memory by patient and filtered entirely locally, with no outbound HTTP. |

Sources are resolved per user, project, and datasource group from backend settings, so different
sites (and different cohorts at the same site) can point at different data without changing code.

Biomarker runs need as a second input the **prognostic model** being validated. It is a pair of
CSVs per model and cancer type, held only by the initiating site:

| Artifact | Default filename | Contents |
| --- | --- | --- |
| Weights | `{model_key}_{cancer_type}_weights.csv` | Model coefficients over the biomarker covariates. |
| Cutoff | `{model_key}_{cancer_type}_cutoff.csv` | Risk-score threshold splitting high- from low-risk, plus `ER_threshold` for Exceptional Response Discrimination. |

Model files are **never stored on the backend or the aggregating server**. Their locations are
registered in the initiator's User Settings, keyed by project, datasource group, cancer type,
model key (`cox_lasso`, `logistic_reg`), and artifact type — so the paths stay on the initiator's
own filesystem. At job time a dedicated model-upload workflow runs on the initiating site and
stages the artifacts into the job workspace: in **open-access** mode as the raw CSVs, in
**encrypted** mode as OpenFHE ciphertexts encrypted under the multi-party public key, so the
server only ever persists opaque bytes. In simulation the same files are read from `MODEL_DIR_<N>`
instead of User Settings.

### FHIR resources consumed

`Patient`, `Condition`, `Observation` (including components), `MedicationStatement`, and `Group`.

Filtering is config-driven per project through JSON schemas
([`apis/fhir/config/`](backend/app/core/job_runner/nvflare_jobs/apis/fhir/config/)) rather than
hardcoded, covering:

- **Patient query**: gender, birth-date range, deceased-date range, medication (via reverse chaining).
- **Patient data**: cancer type, matched against SNOMED codes and display text.
- **Observation data**: genetic variant assessment type, deletion and amplification regions,
  minimum deletion/amplification/total mutation counts (this is available for the `General Statistics` 
  project).

Supported operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `IN`, `NOT_IN`, `BETWEEN`, `IN_ALL`.

### Clinical and genomic coverage

- **Cancer types** (SNOMED-coded): non-small cell lung, breast carcinoma, glioma, colorectal,
  pancreatic, gastrointestinal stromal tumor, gastrointestinal neuroendocrine tumor,
  non-Hodgkin lymphoma, bladder, esophagogastric, biliary, and melanoma.
- **Somatic gene panel**: `ARID1A`, `ATM`, `BAP1`, `COL9A3`, `KDM5C`, `MTOR`, `NF2`, `PBRM1`,
  `PCK1`, `PIK3CA`, `PTEN`, `S100B`, `SETD2`, `SMARCA4`, `TCEB1`, `TP53`, `TRMT2B`, `TSC1`,
  `USP32`, `VHL`, `WNT8A`, `ZNF800`. Any of these can serve as a grouping or category column.
  The list lives in
  [`biomarker_gene_columns.py`](backend/app/core/job_runner/nvflare_jobs/apis/fhir/biomarker_gene_columns.py)
  and is expanded into the analysis schemas at load time.
- **Other extracted signals**: principal components (LOINC `86206-0`), total tumor mutation burden
  (LOINC `94076-7`), treatment and sequencing windows, event and censoring flags, and panel
  versions from `Group` resources.

### Projects

Two projects ship seeded by default, each with its own filter system and permitted functions:

| Project | Filter system | Functions |
| --- | --- | --- |
| **General Statistics** | `DEFAULT` broad patient/observation filtering | Survival analysis, chi-square, mean, standard deviation, t-test, count, encrypted filtering, participation confirmation |
| **Biomarker Model Validation for Cancer Prognosis** | `CANCER_TYPE` | Survival analysis (biomarker discovery mode), exceptional response discrimination |

The public biomarker project includes the `MSKChord` datasource group, which selects
the bundled cohort split and matching trained model artifacts.

### Demo data provenance

The data shipped or referenced for the two seeded projects derive from public studies. They are
FHIR re-encodings prepared for this prototype, not the original distributions; consult the
sources below for licensing and the authoritative data.

| Project | Datasource | Origin |
| --- | --- | --- |
| General Statistics | Local FHIR bundles under `standalone/nvflare_stage/data/` (`Survivability_FHIR_Data_part1.zip` for the initiating site, `part2` and `part3` for sites 1 and 2; paths in `standalone/default.env.local`). `general_statistics_pipeline_backup/Survivability_FHIR_Data.zip` holds the same three bundles in one archive. | Braun DA, Hou Y, Bakouny Z, et al. *Interplay of somatic alterations and immune infiltration modulates response to PD-1 blockade in advanced clear cell renal cell carcinoma.* Nat Med 26, 909–918 (2020). [doi:10.1038/s41591-020-0839-y](https://doi.org/10.1038/s41591-020-0839-y) |
| Biomarker Model Validation, `MSKChord` (datasource group 1) | Local FHIR bundles under `standalone/nvflare_stage/data/` (training bundle for the initiating site, testing bundles for sites 1 and 2) and the model files under `standalone/client_utils/model_files/project_2/datasource_group_1/` | MSK-CHORD, cBioPortal study [`msk_chord_2024`](https://www.cbioportal.org/study/summary?id=msk_chord_2024). Jee J, Fong C, Pichotta K, et al. *Automated real-world data integration improves cancer outcome prediction.* Nature 636, 728–736 (2024). [doi:10.1038/s41586-024-08167-5](https://doi.org/10.1038/s41586-024-08167-5) |

---

## Architecture

```text
┌─────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  Frontend   │────>│  Backend         │────>│  NVFlare server      │
│  React/TS   │<────│  FastAPI + MySQL │<────│  (job orchestration) │
└─────────────┘     └──────────────────┘     └───────────┬──────────┘
                                                         │ encrypted rounds
                             ┌───────────────────────────┼───────────────────────────┐
                             v                           v                           v
                    ┌────────────────┐          ┌────────────────┐          ┌────────────────┐
                    │ Site 1 client  │          │ Site 2 client  │          │ Site N client  │
                    │ FHIR / bundle  │          │ FHIR / bundle  │          │ FHIR / bundle  │
                    └────────────────┘          └────────────────┘          └────────────────┘
```

The backend does not run the statistics itself, but **stages** a job. It converts the submitted
filters, functions, thresholds, participation choices, and model selections into a concrete
NVFlare job directory with a workflow graph — key generation, optional model upload, optional
threshold gate, one analytics workflow per function-and-model combination, and a profile
consolidation tail — then uploads it to the NVFlare server. The packaged runtime inside that job
does the local extraction, encryption, aggregation, decryption, and result writing.

---

## Repository layout

| Directory | What it is |
| --- | --- |
| [backend/](backend/) | FastAPI backend, MySQL access layer, job runner, NVFlare job staging, and the packaged federated-analytics runtime (`nvflare_jobs/apis`, `workflows`, job templates). |
| [frontend/](frontend/) | React + TypeScript web application: job runner, filter builder, job history, results viewer, exports, NVFlare manager. |
| [standalone/](standalone/) | Local orchestration CLI that brings up the whole stack in Docker: MySQL, backend, frontend, NVFlare server, per-site clients. |
| [client-supervisor/](client-supervisor/) | Site-operator tooling: a PySide6 desktop app and a terminal supervisor that provision a site's startup kit, run its NVFlare client, and host its local Results API. |
| [documentation/](documentation/) | The detailed specifications: 66 documents across backend, frontend, standalone, and client-supervisor. |

---

## Running SHARE

There are three ways to run the platform, in increasing order of fidelity and setup cost.

### 1. Simulation: fastest loop, no UI

Runs a workflow graph (multi-party key generation → open-access biomarker Kaplan-Meier under
encryption → clear-text reference Kaplan-Meier) for three simulated sites in a single process on
one machine. This is the right target for iterating on analytics, crypto, or FHIR-extraction code.
Everything below is self-contained: it takes a fresh clone to a finished simulator run and a
passing pytest sweep, and needs neither Docker nor the standalone stack.

**Prerequisites.** An Ubuntu 22.04 or Ubuntu 24.04 host (WSL2 running either is fine), using
the Python that ships with it: 3.10 on 22.04, 3.12 on 24.04. The same commands below work on both
releases; nothing has to be edited per host.

| Host | Python (`python3`) | `openfhe` build that gets installed |
| --- | --- | --- |
| Ubuntu 22.04 | 3.10 | `1.5.1.0.22.4` |
| Ubuntu 24.04 | 3.12 | `1.5.1.0.24.4` |

The pairing matters because the `openfhe` package on PyPI ships one wheel per interpreter, each
embedding a CPython extension compiled against that Ubuntu release's system libraries.
`requirements-simulator.txt` pins both builds behind environment markers, so pip installs the one
that matches the interpreter in your virtual environment. Stick to the OS default interpreter: there
is no `openfhe` build for Python 3.11 or 3.13.

The post-quantum routing layer (`liboqs-python`) compiles the native liboqs library into `~/_oqs`
the first time it is imported, which needs a C toolchain:

```bash
sudo apt-get install -y build-essential cmake ninja-build git libssl-dev python3-venv unzip
```

**Step 1: clone and create a virtual environment.** `python3` is the OS default interpreter, so
this yields Python 3.10 on Ubuntu 22.04 and Python 3.12 on Ubuntu 24.04.

```bash
git clone https://github.com/openfheorg/openfhe-share.git
cd openfhe-share
python3 -m venv .venv && . .venv/bin/activate
python --version    # 3.10.x on Ubuntu 22.04, 3.12.x on Ubuntu 24.04
```

**Step 2: install the runtime and the bundled analytics wheel.** The pinned requirements go in
first; the wheel is then installed with `--no-deps` so pip cannot swap the pinned `openfhe` build
for the wheel's looser `openfhe>=1.5`. The wheel is `duality_nvflare_lib`, the packaged form of
`nvflare_jobs/apis` and `nvflare_jobs/workflows`. The last line loads the compiled `openfhe`
extension and is the quickest way to confirm the build matches your interpreter.

```bash
pip install -r backend/app/core/job_runner/nvflare_jobs/requirements-simulator.txt
pip install --no-deps standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
pip install -r backend/app/core/job_runner/nvflare_jobs/tests/requirements-test.txt   # pytest, for step 6
python -c "import openfhe; print(openfhe.__file__)"                                   # sanity check
```

`pip show openfhe` reports `1.5.1.0.22.4` on 22.04 and `1.5.1.0.24.4` on 24.04. If the import fails
with a missing `openfhe.openfhe` module, the virtual environment was created from a Python other
than the OS default; recreate it with `python3 -m venv`.

**Step 3: unpack the demo data and seed the environment file.** The FHIR bundles are committed as
zips; `default.env.local` names the extracted `.json` files, so extract them first. The env file
holds the per-site datasource paths and is read by the simulator (variables already set in your
shell take precedence over it).

```bash
# extract the six demo bundles; -n leaves already-extracted files alone, so this is safe to rerun
cd standalone/nvflare_stage/data
for z in *.zip; do unzip -n "$z"; done
cd ../../..                                              # back to the repository root

# per-site datasource paths (the extracted .json files above), read by the simulator
cp standalone/default.env.local standalone/.env.local
```

**Step 4: run a simulation.**

```bash
cd backend/app/core/job_runner/nvflare_jobs
python3 scripts/run_simulator.py -w outputs/stat_analytics -n 3 -t 3 \
    jobs/nvflare_job_template --datasource-version 2_1
```

`-n 3` matches the template's leader site (`site3`), `-t` is the thread count, and
`--datasource-version 2_1` selects project 2 / datasource group 1 (MSKChord): the
`DUALITY_*_DATASOURCE_2_1` entries in `standalone/.env.local` supply the per-site FHIR bundles and
the model files are read from `standalone/client_utils/model_files/project_2/datasource_group_1`.
The job template's own server config carries no analysis (the backend fills it per submitted
function), so the script stages a copy of the template under `outputs/stat_analytics_staged_job`
with `tests/sim_config_fed_server_km_open.json` and prints the staged path. Pass `--server-config`
to run another chain, for example `tests/sim_config_fed_server_combined_enc.json` for the encrypted
model-upload → HE scoring → Kaplan-Meier and exceptional-response path. The simulator never
contacts a package registry; whatever wheel is installed in the virtualenv is what runs.

A successful run ends with `status: 0` and exits zero. Anything else, or a
`FATAL_SYSTEM_ERROR in server log` suffix, exits non-zero. Per-party logs and result files are
under `outputs/stat_analytics/` (`server/` and `site1/`, `site2/`, `site3/`), with the workflow
outputs in the server's `simulate_job/` tree.

**Step 5 (optional): rebuild the wheel from source.** After editing anything under `apis/` or
`workflows/`, rebuild and reinstall before running again. The builder writes into
`nvflare_jobs/wheels/`, which is gitignored; the committed copy under `standalone/wheels/` is what
the standalone Docker stack ships.

```bash
python3 wheels/APIWheelBuilderCI.py --root . --out-dir wheels
pip install --force-reinstall --no-index --no-deps wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
```

`scripts/run_simulator.sh` chains this rebuild with a two-site simulator run.

**Step 6: run the pytest sweep.** The suite under
[nvflare_jobs/tests/](backend/app/core/job_runner/nvflare_jobs/tests/) runs the simulator across
the open and encrypted paths for Kaplan-Meier (`km`), exceptional response discrimination (`lcs`),
combined jobs, and the secure sample-count threshold, and checks each against a clear-text
reference. It extracts the zipped bundles itself if step 3 was skipped, and refuses to start unless
the installed wheel matches the bundled one. Every case is marked `slow` and runs at full CKKS
security.

```bash
pytest tests/test_simulator_sweep_km_open.py -m slow -v --datasource-version 2_1   # one chain
pytest tests -m slow -v --datasource-version 2_1                                    # everything
```

**→ Full reference:** [nvflare_jobs/README.md](backend/app/core/job_runner/nvflare_jobs/README.md)
(every simulator flag, datasource and model environment variables, General Statistics runs with
`--datasource-version 1`, model upload, participation flags, worker throttling) and
[nvflare_jobs/tests/docker_simulator_runner/](backend/app/core/job_runner/nvflare_jobs/tests/docker_simulator_runner/README.md)
for a containerized version of the sweep that builds liboqs and the wheel inside the image.

### 2. Standalone: full local stack in Docker

Brings up the real application — MySQL, backend, frontend, NVFlare server, and three per-site
client containers — on one machine, driven through the actual web UI. From a fresh clone it is
two menu choices in an interactive dashboard.

**Prerequisites.** Docker Engine with Compose v2, running and reachable by your user (`docker ps`
must work; on Linux the launcher tells you to rerun with `sudo` if the socket is permission-denied).
Python 3.10 or newer on the host. On Windows, Docker Desktop with the WSL2 backend; NVFlare
provisioning runs inside WSL. The dashboard bootstraps what it needs itself: it seeds the env file,
installs `nvflare` on the host for provisioning if it is missing, and fetches a MySQL driver into
`standalone/.deps/`. Installing `standalone/requirements.txt` into a virtualenv first is optional
and only matters for host-mode MySQL or the wheel command.

**Step 1: clone and start the launcher.**

```bash
git clone https://github.com/openfheorg/openfhe-share.git
cd openfhe-share/standalone

./LAUNCH_ME_LINUX.sh          # Linux
./LAUNCH_ME_MAC.command       # macOS (or double-click in Finder)
LAUNCH_ME_WIN.bat             # Windows (or double-click in Explorer)
```

The launcher finds Python, checks Docker, and opens the dashboard. The top of the screen is a
status banner (MySQL reachability and registered clients, NVFlare workspace state, running
containers); below it is a numbered menu. `Enter` or `r` refreshes the banner, `q` quits and leaves
any containers running.

**Step 2: press `1`, then `Enter`.** On a fresh clone the first entry reads *Provision workspace &
build all*. It runs the whole pipeline without further questions:

1. Copies `default.env.local` to `.env.local` and fills `DUALITY_NVFLARE_HOST` with your machine's
   LAN address.
2. Provisions the NVFlare workspace from `project.yml` (server, `site1` through `site10`, and the
   `admin@share.local` admin) into `standalone/nvflare_workspace/`, and packs the admin startup kit
   into `standalone/dist/`.
3. Builds and starts the `mysql`, `backend`, `frontend`, and `nvflare` containers with Docker
   Compose. The first build compiles liboqs and installs the runtime wheel into the NVFlare image,
   so expect it to take several minutes.
4. Pokes the backend so it initializes the database and registers `site1`, `site2`, and `site3`.

It ends with `Full pipeline completed with status 0. Press Enter to continue...`. Press `Enter`. The
refreshed banner should show NVFlare as `PROVISIONED` and the clients line as `site1, site2, site3`.

**Step 3: press `6`, then `Enter`, then `Enter` again.** Entry 6 is *Create/Rebuild USER SPECIFIED
client container*. It asks for a site name; leaving it empty and pressing `Enter` creates a
container for every client registered in MySQL, so all three demo sites come up in one go. For
each site it builds the client image (the first one is slow for the same liboqs reason), extracts
the zipped demo FHIR bundle that `.env.local` assigns to that site into the container's data
mount, copies the biomarker model files into the initiator's container, and starts the NVFlare
client. It ends with `Launched 3 registered client(s): site1, site2, site3. Press Enter to
continue...`. Press `Enter`, then `q` to leave the dashboard.

**Step 4: use the web UI.** Open [http://localhost:3000](http://localhost:3000) and log in as
`initiator`, the seeded `INITIATOR` user mapped to `site3`. The prototype performs no password
check. Two complete walkthroughs with expected results, one per seeded project plus an
encrypted-model variant, are in [documentation/ui-examples/](documentation/ui-examples/README.md).
The backend API is on port 8000 and each site's local Results API on 8089, 8090, and 8091.

**Coming back later.** Rerun the launcher. Entry 1 now reads *Reset & rebuild all* and will ask
whether to wipe the MySQL volume; you only need it after changing backend, frontend, or NVFlare
image inputs. Entries 2 to 5 rebuild one service, 8 rebuilds the running client containers, and 9
rebuilds the runtime wheel from `nvflare_jobs/apis` and `workflows` and hot-redeploys it into the
running NVFlare server and clients.

**→ Full reference:** [standalone/README.md](standalone/README.md) (every command, the complete
`default.env.local` variable table, folder layout, troubleshooting) and
[documentation/standalone/](documentation/standalone/) for provisioning, Compose, MySQL modes,
datasource staging, and operations.

#### Python versions

Python versions differ per component. PyPI publishes each `openfhe` release as two `py3-none-any`
wheels that each embed one CPython extension: the `.22.4` build for Python 3.10 on Ubuntu 22.04 and
the `.24.4` build for Python 3.12 on Ubuntu 24.04 (it needs glibc 2.38 and GCC 13's libstdc++).
Only the `.24.4` wheel declares `Requires-Python >=3.12`; the `.22.4` wheel declares `>=3.10`, so a
bare `openfhe==1.5.1.0.22.4` pin would install on Python 3.12 and fail at import time.
[nvflare_jobs/requirements-simulator.txt](backend/app/core/job_runner/nvflare_jobs/requirements-simulator.txt)
therefore pins each build behind a `python_version` environment marker, and the bare-host simulator
and its pytest sweep run in a virtual environment created from the host's default `python3` (3.10 on
22.04, 3.12 on 24.04), as laid out in the [Simulation](#1-simulation-fastest-loop-no-ui)
prerequisites and detailed in the
[nvflare_jobs README](backend/app/core/job_runner/nvflare_jobs/README.md#host-environment). The
Docker images run Python 3.12 (Ubuntu 24.04 or `python:3.12` bases) and install `openfhe>=1.5`,
which resolves to the `.24.4` build. The backend and its test suite need Python 3.12
(`backend/requirements-dev.txt`).

### 3. Production deployment: not supported in this version

This public release supports the simulator and the standalone Docker stack only. There is no
supported production or multi-institution deployment path, and the code has not been hardened
for one. See the [disclaimer](#disclaimer-research-prototype-not-for-production-use).

The codebase does keep the *shape* of a deployed configuration so that adopters can wire up
their own infrastructure if they choose to. `SHARE_ENV` accepts `dev`, `test`, and `prod` in
addition to `local`, and the non-local branches reach for externally managed database
credentials, SSH access to a remote NVFlare workspace, remote startup-kit packaging, and an
externally hosted websocket relay. Every hostname, secret name, and bucket in those branches is a
placeholder (`*.example.org`, `example-database-secret`) that must be replaced, and only the `dev`
branch is wired at all: `test` and `prod` return no configuration and fail downstream. The
client supervisor under [client-supervisor/](client-supervisor/) likewise ships with a placeholder
backend URL and an `aws` environment label that point at nothing.

If you take this on, treat the following as blocking before any real data is involved:

- **Authentication.** Login is a username lookup with no password validation, and most routes
  perform no authorization checks. Startup kits carry site credentials, and the delivery endpoint
  does not derive the authorized site from an authenticated caller. See
  [backend/20](documentation/backend/20-security-auth-cors-and-access-control.md) and
  [client-supervisor/11](documentation/client-supervisor/11-share-launch-links-and-direct-results.md).
- **Internal callbacks.** The NVFlare server posts job status back to the backend gated only by a
  shared database password carried in the request body.
- **Everything listed in the disclaimer above.**

The environment switch and the non-local code paths are described in
[documentation/backend/05](documentation/backend/05-environment-configuration-and-secrets.md),
[backend/17](documentation/backend/17-nvflare-admin-server-and-ssh-integration.md), and
[backend/19](documentation/backend/19-local-standalone-and-containerization.md).

---

## Documentation

Start from the overview for the area you're working in:

| Area | Overview | Code map |
| --- | --- | --- |
| Backend | [01-backend-overview](documentation/backend/01-backend-overview.md) | [22-backend-code-map](documentation/backend/22-backend-code-map.md) |
| Frontend | [01-frontend-overview](documentation/frontend/01-frontend-overview.md) | [20-frontend-code-map](documentation/frontend/20-frontend-code-map.md) |
| Standalone | [01-standalone-overview](documentation/standalone/01-standalone-overview.md) | [02-repository-and-runtime-layout](documentation/standalone/02-repository-and-runtime-layout.md) |
| Client supervisor | [01-client-supervisor-overview](documentation/client-supervisor/01-client-supervisor-overview.md) | [10-client-supervisor-code-map](documentation/client-supervisor/10-client-supervisor-code-map.md) |

Frequently needed deep dives:

- [Running jobs from the web UI: worked examples with expected results](documentation/ui-examples/README.md)
- [Functions, filters, thresholds, and workflow groups](documentation/backend/09-functions-filters-thresholds-and-workflow-groups.md)
- [FHIR filtering and analysis engines](documentation/backend/14-fhir-filtering-and-analysis-engines.md)
- [Biomarker and analytics workflows](documentation/backend/15-biomarker-and-analytics-workflows.md)
- [OpenFHE and encrypted workflows](documentation/backend/18-openfhe-and-encrypted-workflows.md)
- [NVFlare job lifecycle](documentation/backend/11-nvflare-job-lifecycle.md) and
  [job packaging and templates](documentation/backend/12-nvflare-job-packaging-and-templates.md)
- [Job runner flow](documentation/frontend/07-job-runner-flow.md) and
  [results viewer](documentation/frontend/12-results-viewer-and-report-sections.md)

Sequence diagrams for the key-generation, encrypted biomarker, stat-analytics, threshold, and PQC
routing flows live in [nvflare_jobs/docs/](backend/app/core/job_runner/nvflare_jobs/docs/).

---

## Contributors

- **Andreea Alexandru**, Duality Technologies and OpenFHE.org
- **Evan Chicoine**, ICF International
- **Sadegh Faramarzi Ganj Abad**, ICF International
- **Carlo Pascoe**, Duality Technologies and OpenFHE.org
- **Yuriy Polyakov**, Duality Technologies and OpenFHE.org
- **Abdullah Rafiqi**, ICF International
- **Sarabjeet Singh**, Duality Technologies
- **Dmitriy Suponitsky**, Duality Technologies and OpenFHE.org
- **Lida Wang**, Dana-Farber Cancer Institute

Affiliations are given as of the time of contribution.

## Use of AI assistance

Parts of this repository, code, tests, and documentation, were written or revised with the assistance 
of large language models. Every AI-assisted contribution was human-reviewed, tested, and accepted by 
the contributors above.

## License

SHARE is released under the [BSD 2-Clause License](LICENSE), the same license as OpenFHE.
