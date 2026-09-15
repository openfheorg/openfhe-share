# Federated Biomarker Logistic Regression Pipeline

Federated workflow that produces a single inverse-variance meta-analysis of the slope of a logistic regression `logit(P(y=1)) = β₀ + β₁ · z(risk_score)`, where the risk score is the dot product of patient covariates with a published biomarker model (e.g. Cox-LASSO) and `y = (time > horizon_threshold)`. The pipeline runs entirely inside the existing NVFlare + OpenFHE + CKKS scaffolding — no new HE primitives.

Companion: [adding_new_workflow.md](./adding_new_workflow.md) — generic recipe for adding any new federated workflow.

---

## 1. Goal

Each client holds a private patient cohort with covariates, an event time, and a censoring indicator. Each client also has access to an open-access biomarker model (e.g. Cox-LASSO weights under `standalone/client_utils/model_files/project_2/datasource_group_1/`). We want a single federated estimate of the relationship between the biomarker risk score and the binary survival outcome `y = (time > horizon)`, **without any per-patient covariate or score leaving the client**.

The federation produces these pooled outputs at the end of the encrypted production path:

```
meta_beta1, meta_se_beta1, z, p_value, ci_lower, ci_upper, total_inv_var
```

`meta_beta1` is the fixed-effects inverse-variance pooled slope of the per-client local logistic fits; the rest are the standard companion statistics. `β₀` is *not* aggregated (only `β₁` is the federation point of interest).

There is a parallel clear-text "reference" path that produces the same outputs from purely clear-text aggregations, for end-to-end validation of the encrypted result.

---

## 2. Architecture

### 2.1 The pipeline workflows (two phases)

**Config layout.** The deployment job template ships a *bare-skeleton* [config_fed_server.json](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/config/config_fed_server.json) (KeyGen + a `workflow_stat_analytics_template` + profile consolidation). The actual LCS chain is assembled at job-submission time by [NVFlareJobStager.py](../app/core/job_runner/nvflare_jobs/NVFlareJobStager.py) from the chain config matching the selected `model_type`:
- **Encrypted:** [jobs/configs/config_meta_analysis_enc.json](../app/core/job_runner/nvflare_jobs/jobs/configs/config_meta_analysis_enc.json)
- **Open-access:** [jobs/configs/config_meta_analysis_open.json](../app/core/job_runner/nvflare_jobs/jobs/configs/config_meta_analysis_open.json)

The simulator sweeps run from self-contained server configs that also carry the clear-text reference twin for end-to-end validation: [tests/sim_config_fed_server_enc.json](../app/core/job_runner/nvflare_jobs/tests/sim_config_fed_server_enc.json) (encrypted) and [tests/sim_config_fed_server.json](../app/core/job_runner/nvflare_jobs/tests/sim_config_fed_server.json) (open-access). The deployment chain configs do **not** include the reference twin (it is test-only).

The **encrypted production path** is **4 workflows** (plus KeyGen): a `workflow_model_upload` that encrypts the model **at the initiator** (see §2.6), then encrypted scoring → mean-stdev → meta-analysis. The clear-text reference path used by the sweep is **4 workflows**, arranged in two phases that **share an on-manager cache**: the entire encrypted production path runs first, then the entire reference path.

The encrypted-path `biomarker_lr_fit` step is **fused** into the meta-analysis preprocess so the production pipeline does not exchange empty `{}` rounds for a local-only computation. The reference path keeps `workflow_biomarker_lr_fit_2` standalone so the per-client status file (`biomarker_lr_fit/.../processed_results.json`) is still written and the sweep tests can detect degenerate fits per client.

Encrypted-path workflows (the reference twin in the sweep config keeps the row layout below shifted by the model_upload step):

| # | Phase | NVFlare workflow id | NVFlare task | computation_type | HE? | Role |
|---|---|---|---|---|---|---|
| 1 | — | `workflow_KeyGen` | `task_KeyGen` | — | yes | Distributed CKKS key generation. Ships multiplication keys and rotation keys for the union of indices needed by the encrypted-scoring HE dot-product and `mean-stdev` (today: `[1, 2, 4, 8, 16, 32, 64, 128, 256, -511]`, `mult_depth = 4`). |
| 2 | **encrypted** | `workflow_model_upload` | `task_model_upload` | — (`model_type: "Encrypted"`, `for_scoring: true`) | yes | **Encrypt-at-initiator.** The leader client encrypts the biomarker model (rsf = 1.0, the raw-score variant — see §2.6) under the multiparty public key and uploads only ciphertext; the server writes the `.ct` artifacts to `app_server/custom`. The plaintext model never reaches the server. |
| 3 | **encrypted** | `workflow_enc_biomarker_disc_score` | `task_enc_biomarker_disc` | `biomarker_enc_score_computation` | yes | **Encrypted-model scoring.** Each contributing client encrypts and sends its patient covariate matrix; the server applies the leader-uploaded encrypted coefficients under HE to produce per-patient encrypted risk scores; each client multi-party-decrypts its own scores (privacy-masked via `_apply_biomarker_mask` / `_remove_biomarker_mask_and_extract_scores` so the server never sees per-client plaintext) and writes them to `cached_risk_scores`. Mirrors the existing `biomarker_enc_risk_group_computation` flow without the cutoff-thresholding step (`SKIP_CUTOFF`). |
| 4 | **encrypted** | `workflow_stat_analytics_scores_mean_stdev` | `task_stat_analytics` | `mean-stdev` (`over_cached_scores: true`) | yes | Aggregates `(sum_sq, sum, count)` of cached scores under HE; the postprocess writes the global `(μ, σ)` of the scores to `cached_scores_mean`/`cached_scores_std`. |
| 5 | **encrypted** | `workflow_stat_analytics_meta_analysis` | `task_stat_analytics` | `meta-analysis` (with **fused** `biomarker_lr_fit`) | yes | Per-client preprocess **first** z-normalizes the cached scores with the encrypted-recovered `(μ, σ)` from step 4 and fits the 2-parameter logit locally (populating `cached_lr_fit`), **then** ships the inverse-variance share. Server runs the fixed-effects meta-analysis under HE and returns `(β̄₁, SE, z, p_value, CI, total_inv_var)`. **End of the encrypted path.** |

The clear-text reference twin in the sweep config (`workflow_biomarker_score_computation` → `workflow_reference_stat_analytics_scores_mean_stdev` → `workflow_biomarker_lr_fit_2` → `workflow_reference_stat_analytics_meta_analysis`, all `task_reference_stat_analytics`) overwrites the shared cache after the encrypted phase and reproduces the same outputs clear-text — see §2.2. `workflow_biomarker_lr_fit_2`'s `_2` suffix is historical and kept so test fixtures and result paths stay stable.

> **Step-number convention.** `workflow_model_upload` (encrypt-at-initiator) is an infrastructure step added to the encrypted path; it is not part of the statistical pipeline. The "**step N**" labels in §3 (the math) count only the computation stages — **step 2 = scoring, step 3 = mean-stdev, step 4 = meta-analysis** on the encrypted side, and steps 5–8 on the reference side — and ignore KeyGen and model_upload. Map by the parenthetical `computation_type`, not by the §2.1 table row.

The encrypted scoring (step 3 above / "step 2" in the §3 math convention) and the clear-text scoring (`workflow_biomarker_score_computation`) are **two parallel implementations** of the same federated computation (per-patient risk score = biomarker model · covariates). The frontend picks one or the other (the `model_type` select) based on whether the user wants to keep the biomarker model itself private. The **deployed open-access chain** (`config_meta_analysis_open.json`) is the unfused KeyGen + `biomarker_score_computation` + mean-stdev + lr_fit + meta-analysis; the **open-access sweep** (`tests/test_simulator_sweep_open.py` via `tests/sim_config_fed_server.json`) computes clear-text scores up front and runs HE mean-stdev + meta-analysis over them — see §2.5.

### 2.2 Two phases (encrypted then reference)

The encrypted and reference twins write to the same on-manager cache fields (`cached_scores_mean`, `cached_scores_std`, `cached_lr_fit`). An interleaved layout — `enc μ,σ` → `ref μ,σ` → `lr_fit` → `enc meta` → `ref meta` — would have the reference workflow overwrite the encrypted cache *before* the encrypted side consumed it, so the entire encrypted side would silently run on reference values. The interleaved layout would also mask an encrypted failure: if the encrypted `mean-stdev` raised, the reference workflow would still seed the cache and the downstream encrypted meta-analysis would produce a wrong-looking-but-right number.

The two-phase layout fixes both issues:

- **Steps 3 and 4** form a fully self-consistent encrypted pipeline. If step 3 fails, `cached_scores_mean/std` stay `None`, the fused `lr_fit` inside step 4 short-circuits (leaving `cached_lr_fit = None`), and the meta-analysis aggregate-side guard emits a `FAIL` result. The encrypted failure surfaces loudly.
- **Steps 5–8** form a fully self-consistent reference pipeline that overwrites the cache *after* the encrypted side is fully done (step 5 reseeds `cached_risk_scores` analogously to step 2 on the encrypted side). The reference outputs at step 8 are produced from clear-text aggregations all the way through.

The two final outputs (4 and 8) can be compared directly — any mismatch is purely the CKKS approximation noise of the encrypted aggregations in steps 3 and 4.

### 2.3 Client-local caches that cross workflow boundaries

`StatAnalyticsManager.reset_computation_props` is called between workflows. The following fields are **intentionally not reset** so they survive the boundary on a single client process:

| Field | Filled by | Then overwritten by | Consumed by |
|---|---|---|---|
| `cached_risk_scores` | step 2 (encrypted scoring) — or the fused score_computation inside step 3 in the open-access path | step 5 (reference clear-text scoring) | step 3 reads it for mean-stdev; step 4's fused `lr_fit` reads it; steps 6, 7 read step 5's value on the reference side |
| `cached_scores_mean`, `cached_scores_std` | step 3 (encrypted `mean-stdev` postprocess) | step 6 (reference `mean-stdev`) | step 4's fused `lr_fit` reads step 3's values; step 7 reads step 6's values |
| `cached_lr_fit = {beta0, beta1, n, se_beta1}` | step 4's **fused** `lr_fit` (inside the meta-analysis preprocess) | step 7 (standalone reference `lr_fit_2`) | step 4's meta-analysis share builder reads the fit it just produced; step 8 reads step 7's fit |

Both encrypted and reference postprocess paths write to the same cache fields. The two-phase ordering guarantees that the production-side workflow always runs before its reference twin overwrites the cache.

### 2.4 Why client-local cache instead of persistor

The existing encrypted biomarker-discovery flow persists encrypted per-client risk scores on the server (still encrypted) between workflows, so the next workflow can consume them. For our open-access path, sending cleartext per-patient scores to the server would defeat federation. Instead, scores, μ/σ, and the LR fit live on each client's `StatAnalyticsManager` instance and survive the workflow boundaries because they're not cleared by `reset_computation_props`.

### 2.5 Open-access path (separate config, not a conversion)

The open-access and encrypted paths are **separate config files**, not a runtime conversion of one into the other:

- **Deployment:** the stager loads [config_meta_analysis_open.json](../app/core/job_runner/nvflare_jobs/jobs/configs/config_meta_analysis_open.json) — KeyGen + `workflow_biomarker_score_computation` (clear-text scoring) + `mean-stdev` (`over_cached_scores`) + `meta-analysis` (fused `lr_fit`). The clear-text scoring caches per-patient scores on each client; the HE mean-stdev and meta-analysis aggregate them exactly as in the encrypted path. No model_upload step (the model is public; clients load coefficients from CSV).
- **Sweep test:** [tests/test_simulator_sweep_open.py](../app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_open.py) stages [tests/sim_config_fed_server.json](../app/core/job_runner/nvflare_jobs/tests/sim_config_fed_server.json) (via the `stage_job` fixture in [tests/conftest.py](../app/core/job_runner/nvflare_jobs/tests/conftest.py)), which carries the open chain plus the clear-text reference twin for the HE-vs-reference agreement assertion.

The persistor recognizes the presence of `model_key` on an `over_cached_scores=true` mean-stdev workload and ships the biomarker covariates + pickled coefficients in `generated_args`; the client's `mean-stdev` preprocess can then run `local_pre_biomarker_score_computation` inline (the fused fallback). On the open path the explicit `workflow_biomarker_score_computation` already populated `cached_risk_scores`, so this fallback only fires for a client that has no cached scores yet.

### 2.6 Encrypt-at-initiator model upload

The encrypted path keeps the **plaintext biomarker model off the server entirely**. The model owner is the *leader client* (the initiator, e.g. `site3`), and a dedicated `workflow_model_upload` runs after KeyGen:

1. The leader loads its plaintext model CSVs (`<model_key>_<cancer_type>_weights.csv` / `_cutoff.csv` from `app_client/custom/`) and encrypts them under the aggregated multiparty public key via `OpenfheManager.encrypt_biomarker_model`.
2. It uploads only the ciphertext (`enc_model_data` + the per-model scale factor). The server's `_workflow_model_upload` writes the `.ct` artifacts to `app_server/custom/`; the plaintext never reaches the server.
3. The downstream encrypted scoring (step 3) loads those pre-encrypted ciphertexts from disk — the server computes the HE dot-product without ever seeing the coefficients.

The stager copies the plaintext model CSVs into `app_client/custom` **only** for encrypted jobs (not `app_server`), so the leader can encrypt but the server has no clear-text copy (`_copy_biomarker_model_files_if_needed`).

**`for_scoring` / `rsf`.** The encryption has two variants, selected by the `for_scoring` flag on the model_upload `workload_args`:
- **Discovery** (`for_scoring: false`, used by encrypted Kaplan-Meier biomarker discovery): coefficients rescaled by `rsf = 1/|cutoff|`. The rescaling amplifies the margin of `score − cutoff` so its sign survives CKKS noise (discovery only needs the risk-group, i.e. the sign).
- **Scoring** (`for_scoring: true`, used by LCS): `rsf = 1.0` — the raw per-patient score, which LCS needs for the logistic fit. The worker skips the cutoff subtraction (`SKIP_CUTOFF`).

Because the two variants of the *same* `model_key` are distinct encryptions, their `.ct` artifacts are named distinctly (`resolve_encrypted_biomarker_model_paths(..., for_scoring=...)` appends a `_score` marker for the scoring variant) so a job that runs *both* validations does not have one overwrite the other — see §2.7.

### 2.7 Co-running with encrypted Kaplan-Meier biomarker discovery

LCS (encrypted scoring) and encrypted KM biomarker discovery are independent validations that a user can select together, on the same or different models. They share runtime machinery (the `task_enc_biomarker_disc` executor, the `aggregate_stat_analytics` HE dot-product, the `workflow_enc_biomarker_disc` persistor/aggregator dispatch), but the stager keeps them **decoupled** so co-staging one does not suppress the other:

- `NVFlareJobStager._workflow_is_enc_biomarker_disc` treats `biomarker_enc_score_computation` (LCS scoring) as **not** a discovery workflow, so the idempotent inserters (`_insert_enc_biomarker_disc_workflow`, `_insert_model_upload_workflow`) still insert KM's discovery enc-disc + discovery model_upload when both are selected.
- `_insert_model_upload_workflow` skips only when a **discovery/open** (`for_scoring != true`) model_upload already exists, so the LCS scoring model_upload and the KM discovery model_upload coexist.
- The discovery (`rsf = 1/|cutoff|`) and scoring (`rsf = 1.0`) encryptions of the same `model_key` write distinct `_score`-marked `.ct` files (§2.6), so they never overwrite each other on disk.

KM's discovery math is **unchanged** by the LCS work. A future optimization will compute the per-patient mat-vec product once and share it across both validations — see §9.

---

## 3. Math

### 3.1 Per-client scoring — two implementations of the same `score_i = Σⱼ coef_j · covariate_ij`

The pipeline ships **both** implementations and the frontend picks one per job. They produce values in the same shape (`self.cached_risk_scores = [score_1, …, score_nₖ]` on each client) so the rest of the pipeline is agnostic to which ran.

**Encrypted scoring (`biomarker_enc_score_computation`)** — chosen when the user wants to keep the biomarker model itself private. The model coefficients are encrypted **at the initiator**: the leader client encrypts them during `workflow_model_upload` (§2.6) and the server only ever holds the ciphertext — it never sees the plaintext coefficients. Each contributing client encrypts and sends its covariate matrix; the server homomorphically computes the per-patient encrypted score `Σⱼ coef_j · covariate_ij` against the leader-uploaded encrypted model (3 mults plus rotation-and-adds); each client multi-party-decrypts only its own scores, with the server seeing only privacy-masked partial shares. Three rounds: encrypt-covariates → partial-decrypt → fuse-and-cache (the fusion step on each client also strips the random privacy mask it injected at the partial-decrypt step). Reuses the existing `biomarker_enc_risk_group_computation` HE machinery minus the cutoff-subtraction step (`SKIP_CUTOFF`); the model-hiding multiplicative mask `rm` is also dropped on the scoring path (it only preserves the *sign* needed by discovery, not the magnitude scoring needs) — see §2.6. The non-contributing leader (initiator) does not upload a covariate share; it scores its own cohort locally from its plaintext model so its Initiator-panel view is still populated, without contributing to the federated aggregate.

**Clear-text scoring (`biomarker_score_computation`)** — used when the user is comfortable with each client loading the model coefficients from a CSV and computing scores locally. Cheaper; no HE. The reference phase keeps this as a standalone workflow (step 5) so its per-client status file is written. The **open-access production path** instead inlines the same `local_pre_biomarker_score_computation` call into the `mean-stdev` preprocess (see §2.5) — the helper function is unchanged; only the wiring differs.

The persistor resolves the biomarker model CSV path in both cases via `resolve_biomarker_model_paths`. In the encrypted-scoring path the coefficients are then encrypted at aggregate-time; in the clear-text-scoring path they're injected into client metadata via `metadata["coeffs"]` — for the standalone reference workflow on the unfused branch of `get_meta_from_schema`, or for the fused open-access mean-stdev on the over_cached_scores branch.

### 3.2 Combined mean + standard deviation under HE (workflows 3 / 7)

A new `computation_type = "mean-stdev"` computes both the mean and the (sample or population) standard deviation of a numeric column — or of the cached per-patient risk scores — in a single HE workload. Built on top of the existing `stdev` workflow infrastructure (same `customSAG` round structure, same persistor / aggregator / executor, same multi-party decryption path), reusing the `(sum_sq, sum, count)` triple that `local_pre_stdev` already returns.

Two operating modes:

- **Column-data mode** (`data_column_id: "<column>"`): mean+std of a FHIR numeric column, with the standard `[-1, 1]` normalization driven by `global_min` / `global_max` / `global_count` from `global_schema.json`. Mirrors `stdev` exactly.
- **Cached-scores mode** (`over_cached_scores: true`): mean+std of the per-patient scores cached by step 2. No FHIR column, no schema-driven normalization. The postprocess writes the result back to `self.cached_scores_mean` and `self.cached_scores_std` on the manager so step 4's fused `lr_fit` can consume it. **Fused-score variant**: when the workload_args also carries `cancer_type` / `model_key` (open-access production path — see §2.5), the preprocess first calls `local_pre_biomarker_score_computation` to populate `cached_risk_scores` before building the `(sum_sq, sum, count)` share.

#### 3.2.1 Per-client share

```
nₖ        = count of (non-null) values
sumₖ      = Σ xᵢ
sum_sqₖ   = Σ xᵢ²
```

In column-data mode the values are normalized to `[-1, 1]` against `(global_min, global_max)` before the sums are taken. In cached-scores mode no normalization is applied.

#### 3.2.2 Slot layout

The per-client ciphertext packs nine non-zero slots:

```
slot:  0        1     2  3     4  5  6     7  8
       x²_sum,  x_sum, n, x_sum, n, 0, x_sum, n, 0
```

The duplicated `(x_sum, n)` at slots 3–4 is consumed by the std math (mirroring the existing `stdev` workflow); the second duplicate at slots 6–7 carries the mean payload through the multiply / rotate / subtract pipeline.

#### 3.2.3 Server-side aggregation under HE

After tree-summing the per-client ciphertexts, the server holds one ciphertext `ctx` with first-9-slot value:

```
ctx = [Σx²_sum, Σx_sum, Σn, Σx_sum, Σn, 0, Σx_sum, Σn, 0, 0, ...]
```

Below, `S = Σx_sum`, `Q = Σx²_sum`, `N = Σn`.

**Step 1 — Build `ctx'` from a rotate-by-2 + add.**

> *Implementation note:* in principle the rotate-by-2 can be expressed as two successive `EvalRotate(1)` calls, avoiding the need for an index-2 rotation key. That was tried first and hit `MultipartyDecryptFusion: approximation error too high` — each rotation adds noise that compounds through the two multiplications that follow (`ctx · ctx'` then the mask multiply), pushing CKKS past its precision budget. So the implementation uses a single `EvalAtIndex(2)` and the keygen ships both index-1 and index-2 rotation keys.

After rotating `ctx` two positions to the left:

```
rot2(ctx) = [N, S, N, 0, S, N, 0, 0, 0, ...]
```

For **sample** std, add `[0, 0, -1, 0, 0, 0, 1, 1, 0, ...]`:

```
ctx' = [N, S, N-1, 0, S, N, 1, 1, 0, ...]
```

For **population** std, add `[0, 0, 0, 0, 0, 0, 1, 1, 0, ...]`:

```
ctx' = [N, S, N, 0, S, N, 1, 1, 0, ...]
```

The `+1`s at slots 6, 7 are the trigger that drives the mean payload through the subsequent multiply.

**Step 2 — Multiply `ctx ← ctx · ctx'`.**

For the **sample** case:

```
ctx · ctx' = [QN, S², N(N-1), 0, SN, 0, S, N, 0, 0, ...]
```

For **population**, slot 2 becomes `N²` and slot 5 stays `0`; slots 6 and 7 are unchanged.

**Step 3 — Rotate `ctx` by one position left to get `ctx'`, then subtract `ctx ← ctx − ctx'` in place.**

For the **sample** case:

```
ctx − rot1(ctx) = [QN − S², S² − N(N-1), N(N-1), −SN, SN, −S, S − N, N, 0, ...]
                     ▲                       ▲              ▲       ▲
              numerator_std          denominator_std    −sum    count
                  (slot 0)               (slot 2)      (slot 5) (slot 7)
```

The numerator of the variance lives at slot 0; the denominator (sample = `N(N-1)`, population = `N²`) lives at slot 2; the sum lives at slot 5 with a flipped sign; the count lives at slot 7.

**Step 4 — Apply the mask plaintext.** Two regimes:

- **Column-data mode** (`global_count is not None`): use `[r1, 0, r1, 0, 0, -r2, 0, r2, 0, …]`. `r1` masks the std payload (slots 0 and 2), `r1` cancels in the `slot0 / slot2` ratio so the recovered variance is exact. `r2` masks the mean payload (slots 5 and 7), `r2` cancels in `slot5 / slot7`. The `-r2` at slot 5 flips the negative sign of `-S` produced in step 3. `r1` and `r2` are *independent* draws — sharing a mask between mean and std would weaken privacy on the variance. To keep the masked ciphertext inside CKKS precision, `r1` is divided by `global_count²` and `r2` by `global_count`.

- **Cached-scores mode** (`global_count is None`, the `over_cached_scores` path): the mask plaintext is `[r1, 0, r1, 0, 0, -r2, 0, r2, 0, …]` with `r1 ~ logN(8.0, 1.5)` and `r2 ~ logN(10.0, 2.0)`, both clipped to `±3σ`. Same structure as column-data mode (`r1` cancels in `slot0/slot2`, `r2` in `slot5/slot7`, `-r2` at slot 5 flips the negative sign of `-S`), but the log-normal parameters are smaller because there is no `global_count` to divide by — the bounds on `n` come from worst-case patient counts (~10⁴) instead. The DP analysis lives in the `multiplicative_mask` docstring; in short, at `δ_mech = 2⁻¹³` and linear sensitivity `K = 1000`, ε ≈ 1.5–2 at `x = 10³` and softens to ~0.2 at `x = 10⁴`. The ±3σ clip puts a ~`10⁻³·Δ_log/σ` floor on the *actual* δ contribution from the truncated tail; the Gaussian-mechanism δ can be driven below `2⁻¹³` by trading ε but the truncation tail is a separate, σ-independent floor.

  Because the mask cancels in both ratios, the decrypted slot7 (= `r2·n`) is **not** a recoverable plaintext: the global cohort size `Σnₖ` is hidden.

**Step 5 — Multi-party decryption** returns the masked plaintext. The postprocess extracts:

```
slot 0 ÷ slot 2  →  variance_normalized           (mask cancels)
sqrt(...)         →  stdev_normalized
× range / 2      →  stdev                         (un-normalize, column-data mode only)

slot 5 ÷ slot 7  →  mean_normalized                (mask cancels)
× range / 2 + global_min  →  mean                 (un-normalize, column-data mode only)
```

In cached-scores mode both un-normalizations are no-ops; the result is `(mean_scores, stdev_scores)` directly (no `total_n` is emitted — the masked count never decodes to a plaintext), and each client also writes them onto `self.cached_scores_mean` and `self.cached_scores_std` for step 4's fused `lr_fit` to read.

Multiplicative-masking recap: slots 0/2 carry `r1·…` and slots 5/7 carry `r2·…`, with `r1`/`r2` cancelling in the std and mean ratios respectively. The mask magnitudes (`R₁ ≤ e¹²·⁵ ≈ 2.7·10⁵`, `R₂ ≤ e¹⁶ ≈ 8.9·10⁶`) stay well under the 10⁹ CKKS-precision cap. The full ε/δ analysis is in step 4 above and the `multiplicative_mask` docstring. The masked `count` slot is not recoverable, so the global cohort size is hidden; the degenerate `n < 2` case is filtered separately via the thresholding check before the lr-fit.

#### 3.2.4 HE budget for `mean-stdev`

| Step | Operation | Mult depth used |
|---|---|---|
| 1 | tree-sum across clients | 0 (additions) |
| 2 | `ctx · ctx'` | 1 |
| 3 | rotate + subtract | 0 |
| 4 | mask multiply | 1 |

Total `depth_required = 3`, identical to plain `stdev`. The persistor's `_validate_openfhe_parameters` enforces this and that rotation indices `[1, 2]` are both present in `openfhe_manager.indices`.

#### 3.2.5 Numerical-robustness guards

`local_post_stdev` clamps `sq_stdev` in `[-1e-8, 0]` to exactly `0` — CKKS round-off can push a near-zero variance slightly below zero (observed: `−1.5·10⁻¹²` for biomarkers whose true variance is at the noise floor). Values more negative than `_NEG_SQ_STDEV_TOL = 1e-8` ([apis/utils.py](../app/core/job_runner/nvflare_jobs/apis/utils.py)) still raise `ValueError`; the threshold is the squared CKKS noise floor under `mult_depth = 4`, `scale_mod_size = 50` and well below any scientifically meaningful variance.

When the score distribution itself sits below the CKKS noise floor (`|mean| < 1e-5` *and* `stdev < 1e-5`), both `postprocess` and `postprocess_reference` flag the result with `status='WARN'` — see [§3.6](#36-status-field-diagnostics-warn-and-fail-triggers) for the full trigger table.

### 3.3 Global z-score normalization and local LR fit (fused into step 4 on the encrypted path; standalone step 7 on the reference path)

`biomarker_lr_fit` runs twice in the pipeline — once on each phase. The computation is identical in both: each client computes per-patient `z = (score − μ) / σ`, builds `y = (time > horizon_threshold)`, fits `sm.Logit(y, [1, z])`, and writes the resulting fit onto `self.cached_lr_fit`:

```
cached_lr_fit = {
  "beta0":    float,           # intercept of the local 2-param logit
  "beta1":    float,           # slope (on the *globally* z-scored score)
  "n":        int,             # local cohort size
  "se_beta1": float,           # fit.bse[1]; the per-client input to meta-analysis weights
}
```

The underlying helper `local_pre_logistic_regression_with_global_zscore` is unchanged and still callable on its own — what differs across the two phases is how it is dispatched:

- **Encrypted phase (fused).** `workflow_stat_analytics_meta_analysis`'s workload_args carry the `biomarker_lr_fit` args (`cancer_type`, `model_key`, `time_column_id`, `censoring_column_id`). The server-side persistor recognizes the presence of these fields, resolves the cutoff CSV to inject `horizon_threshold` (cached per file path; see §4), and ships everything to clients. The client's `meta-analysis` preprocess calls `_run_fused_biomarker_lr_fit` to populate `cached_lr_fit` using the encrypted-recovered `(μ, σ)` from step 3, **then** builds the per-client inverse-variance share. No empty round of communication.
- **Reference phase (standalone).** `workflow_biomarker_lr_fit_2` runs as before — a full clear-text round structure with its own `processed_results.json` per site, so the sweep tests can flag a degenerate fit by client/path.

Because every client's design matrix uses the **same** global `(μ, σ)` (whatever the phase), the per-client `β₁` are in directly comparable units and the inverse-variance pooling at the next step is the meaningful federation point. (Earlier versions of this pipeline used a *local* z-score per client; that produced per-client `β` fit against different x-axes, and the federation point was incoherent.)

Degenerate cohorts (`n < 2`, single class in `y`, or `score_std ≤ 0`) skip the fit and leave `cached_lr_fit = None`. The downstream meta-analysis treats a `None` fit as a zero share so it does not contribute to the aggregate. On the **encrypted (fused) path** the degenerate case is surfaced via a `logging.warning` from `_run_fused_biomarker_lr_fit` (no per-client status file is written — the meta-analysis result carries the propagation downstream); on the **reference (standalone) path** the standalone workflow's postprocess emits `status='WARN'` in its result file, as documented in §3.6.

### 3.4 Inverse-variance meta-analysis of `β₁` (step 4 / step 8)

Each client `k` produces a local fit with slope `β₁,ₖ` and standard error `SEₖ`. The fixed-effects inverse-variance meta-analysis pools these into a single estimate:

```
wₖ      = 1 / SEₖ²                                            (per-client weight)
β̄₁      = (Σₖ wₖ · β₁,ₖ) / (Σₖ wₖ)                            (pooled point estimate)
Var(β̄₁) = 1 / (Σₖ wₖ)
SE(β̄₁)  = 1 / √(Σₖ wₖ)
z       = β̄₁ / SE(β̄₁)
p_value = 2 · (1 − Φ(|z|))                                     (two-sided)
95% CI  = β̄₁ ± 1.96 · SE(β̄₁)
```

Under HE this is a **pure tree-sum** of 2-slot per-client shares `(wₖ · β₁,ₖ, wₖ)` — `depth_required = 1`, no multiplications, no rotations. **No multiplicative mask is applied:** the postprocess explicitly needs `Σwₖ` in the clear to compute `SE(β̄₁) = 1/√(Σwₖ)`, so masking and then having to remove the mask would be a no-op round-trip. (Compare to the `mean` workflow with `cached_lr_field`, which *does* apply a log-normal mask because only the ratio needs to be recoverable.)

**Privacy note.** Without the mask, multi-party decryption reveals `Σwβ` and `Σw` separately. That is no leakier than the four published outputs `(β̄₁, SE, z, p)`: the SE alone determines `Σw`, and combined with `β̄₁` it determines `Σwβ`. So the omitted mask reveals no information beyond the workflow's stated deliverables.

**Degenerate client handling.** A client with `cached_lr_fit is None` (no valid local fit) returns the zero share `{"sum": 0, "count": 0}`. The same zero-share path is taken when `se_beta1 < 1e-10` — a (near-)zero SE would set `wₖ = 1/SEₖ² → ∞`, letting one client dominate the pooled estimate. The threshold lives in `_meta_analysis_share_from_cached_lr_fit` and is logged via `custom_logger.warning(...)` when it triggers.

**Aggregate-side guard.** When `Σwₖ` collapses below `1e-10` (every client contributed a zero share), `local_post_meta_analysis` returns `status='FAIL'` with all four pooled values set to `None`. See [§3.6](#36-status-field-diagnostics-warn-and-fail-triggers) for the full trigger table.

### 3.5 HE budget summary across the pipeline

| Workflow | depth_required | Rotation indices required |
|---|---|---|
| step 2 (`biomarker_enc_score_computation`) | 4 | `[2^i for i ∈ 0..⌈log₂(cov_length)⌉] ∪ {-(cov_length-1)}` (deferred to the aggregate handler — `cov_length` isn't known until the model is resolved) |
| step 3 (`mean-stdev` over scores, encrypted) | 3 | `[1, 2]` |
| step 4 (`meta-analysis`, encrypted; fused `lr_fit` adds no HE cost — it runs on cleartext locally before the share is built) | 1 | none |

The encrypted-scoring step at step 2 dominates: `mult_depth = 4` and `indices = [1, 2, 4, 8, 16, 32, 64, 128, 256, -511]` in the persistor / KeyGen config (the index set covers `cov_length ≤ 512`). `workflow_KeyGen` ships all of these once per job.

### 3.6 Status-field diagnostics: WARN and FAIL triggers

Several postprocess helpers attach a `status` field to their result dict when input data or numerical conditions make the underlying statistic unreliable. Callers (UI, tests, downstream workflows) should treat:

- `status='WARN'` — the statistic was computed, but the result is dominated by noise or partial degeneracy.
- `status='FAIL'` — the statistic could not be computed; the numeric fields are `None`.

**All triggers in one place:**

| Workflow / helper | `status` | Trigger | Source |
|---|---|---|---|
| `mean-stdev` postprocess (encrypted + reference) | `WARN` | `\|mean\| < 1e-5` **and** `stdev < 1e-5` — score distribution below the CKKS noise floor | `_LOW_SNR_THRESHOLD` in [apis/stat_analytics.py](../app/core/job_runner/nvflare_jobs/apis/stat_analytics.py); symmetric on both paths so consumers see the same diagnostic on either output file |
| `mean-stdev` postprocess (encrypted + reference) | `FAIL` | `count <= 0` or `denom <= 0` — empty cohort (no cached scores on this client) | [apis/stat_analytics.py](../app/core/job_runner/nvflare_jobs/apis/stat_analytics.py) `postprocess` / `postprocess_reference` |
| `biomarker_lr_fit` postprocess (**reference path**, standalone `workflow_biomarker_lr_fit_2`) | `WARN` | `cached_lr_fit is None` from `local_pre_logistic_regression_with_global_zscore` (see sub-table below) | [apis/stat_analytics.py](../app/core/job_runner/nvflare_jobs/apis/stat_analytics.py); the per-client share would otherwise carry a silent zero into meta-analysis |
| `meta-analysis` fused `lr_fit` (**encrypted path**, inline) | `WARN` | Same triggers as above. The manager stashes `_fused_lr_fit_status` and the executor writes a per-client file at `biomarker_lr_fit/<meta_workflow_id>/aggregated/processed_results.json` — same shape and stage_dir as the standalone reference workflow, only the workflow_id segment differs. `logging.warning(...)` is also emitted from `_run_fused_biomarker_lr_fit` | [apis/stat_analytics.py](../app/core/job_runner/nvflare_jobs/apis/stat_analytics.py) + [app_client/custom/analytics_executor.py](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/custom/analytics_executor.py) |
| `meta-analysis` postprocess (encrypted + reference) | `FAIL` | `Σwₖ < 1e-10` — every client contributed a zero share | `_META_ANALYSIS_DENOM_TOL` in [apis/utils.py](../app/core/job_runner/nvflare_jobs/apis/utils.py); `local_post_meta_analysis` |

**Sub-triggers that make `local_pre_logistic_regression_with_global_zscore` return `None`** (and therefore fire the `biomarker_lr_fit` WARN):

| Cause | Detection |
|---|---|
| Precondition trip | `n < 2`, single outcome class in `y`, or `score_std ≤ 0` |
| Rank-deficient design matrix | `sm.Logit.fit()` raises, caught by the surrounding `try` |
| Non-convergence | `fit.mle_retvals['converged'] == False` |
| Runaway parameters (perfect separation) | `\|β₁\|` or `SE(β₁)` exceeds `_LR_FIT_MAGNITUDE_LIMIT = 100` |

**Silent numerical clamps (no `status` change):**

- `local_post_stdev` clamps `sq_stdev` in `[-1e-8, 0]` to exactly `0` (`_NEG_SQ_STDEV_TOL` in [apis/utils.py](../app/core/job_runner/nvflare_jobs/apis/utils.py)). Values more negative than the tolerance still raise.
- The per-client meta-analysis share emits zero `(sum, count)` when `cached_lr_fit is None` or `se_beta1 < 1e-10` (see `_meta_analysis_share_from_cached_lr_fit`); a degenerate client cannot dominate the pooled estimate.

**Downstream handling (simulator sweep).** [tests/test_simulator_sweep_enc.py](../app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_enc.py) and [tests/test_simulator_sweep_open.py](../app/core/job_runner/nvflare_jobs/tests/test_simulator_sweep_open.py) bucket cases into PASS / SKIP / FAIL using this status:

| Observation | Outcome | Reason |
|---|---|---|
| Reference `mean-stdev` reports `WARN` | SKIP | Encrypted result is noise-dominated; the comparison is meaningless |
| Any per-site lr_fit status file reports `WARN` (either the standalone `workflow_biomarker_lr_fit_2` or the fused-inside-meta `workflow_stat_analytics_meta_analysis` file under `biomarker_lr_fit/`) | SKIP | At least one client's local logit fit degenerated. The sweep tests list both workflow ids in `LR_FIT_REF_WORKFLOWS`, so the 2-paths × 2-sites = 4-file count from pre-fusion is preserved. If only the encrypted-side file reports `WARN` while the reference does not, the diff in `_diff_results` still catches the resulting `None` vs numeric mismatch (the fused-side zero share usually drives meta-analysis to `FAIL`) |
| Both encrypted and reference `meta-analysis` report `FAIL` | SKIP | No signal to validate — the `None` outputs would "agree" in the diff by coincidence |
| Only one path's `meta-analysis` reports `FAIL` | FAIL | The existing diff catches `None` vs numeric as a real mismatch |
| All status fields clear, diff within `1e-5` | PASS | Encrypted aggregation agrees with the clear-text reference |

---

## 4. Where the logic lives

### Wheel-source (the `apis/` tree; rebuilt and reinstalled via [wheels/APIWheelBuilderCI.py](../app/core/job_runner/nvflare_jobs/wheels/APIWheelBuilderCI.py))

- [apis/stat_analytics.py](../app/core/job_runner/nvflare_jobs/apis/stat_analytics.py)
  - Manager state preserved across workflow boundaries: `cached_risk_scores`, `cached_scores_mean`, `cached_scores_std`, `cached_lr_fit`, `over_cached_scores`. Intentionally **not** cleared by `reset_computation_props`. Transient field `_enc_score_n_patients` is set in the encrypted-scoring preprocess and consumed in the executor's fusion step to trim the decrypted slot vector back to the per-patient list. Transient `_fused_lr_fit_status` is set by `_run_fused_biomarker_lr_fit` to mirror the standalone `biomarker_lr_fit` postprocess shape and is consumed by the executor to emit a per-client status file at `biomarker_lr_fit/<meta_workflow_id>/aggregated/processed_results.json`.
  - Computation-type branches in `set_props_from_init_load`, `preprocess[_reference]`, `aggregate_reference`, `postprocess[_reference]` for: `biomarker_score_computation` (clear-text), `biomarker_enc_score_computation` (encrypted — set_props + encrypted-path preprocess; the round-2 fusion lives in the executor), `mean-stdev` (both column-data and `over_cached_scores`, with optional fused score-computation args), `biomarker_lr_fit` (reference path), `meta-analysis` (with optional fused lr_fit args). (Plus the pre-existing `mean`, `stdev`, `chi2`, `kaplan-meier`, `t-test`, `biomarker_enc_risk_group_computation` branches.)
  - Per-workflow share helpers: `_mean_stdev_share_from_cached_scores()` (steps 3 / 6), `_meta_analysis_share_from_cached_lr_fit()` with the `se < 1e-10` zero-share floor (steps 4 / 8).
  - **Fusion helpers** that compose standalone primitives into the next HE workflow's preprocess (modular — the helper functions they call are unchanged): `_run_fused_biomarker_lr_fit()` invoked from `meta-analysis` preprocess when `horizon_threshold` is set; `_run_fused_biomarker_score_computation()` invoked from `mean-stdev` (`over_cached_scores`) preprocess when `coeffs` is set. Both presence-based so an unfused workflow stays a strict subset of the fused one.

- [apis/utils.py](../app/core/job_runner/nvflare_jobs/apis/utils.py)
  - `local_pre_biomarker_score_computation(...)` — client-side scoring helper. Called by the standalone reference-path `biomarker_score_computation` workflow **and** by the fused open-access mean-stdev preprocess via `_run_fused_biomarker_score_computation`.
  - `local_pre_logistic_regression_with_global_zscore(stat_data_path, filters, time_col, censoring_col, horizon_threshold, risk_scores, score_mean, score_std)` — client-side fit helper. Called by the standalone reference-path `workflow_biomarker_lr_fit_2` **and** by the fused encrypted-path meta-analysis preprocess via `_run_fused_biomarker_lr_fit`. Returns `{"beta0", "beta1", "n", "se_beta1"}` or `None`.
  - `local_post_meta_analysis(total_sum, total_count)` — steps 4 / 8 postprocess; computes the four pooled quantities (β̄₁, SE, z, p) plus CI. Emits `status='FAIL'` on degenerate input ([§3.6](#36-status-field-diagnostics-warn-and-fail-triggers)).
  - `pre_count` accepts `"mean-stdev"` alongside `"mean"` and `"stdev"`.

- [apis/openfhe_manager.py](../app/core/job_runner/nvflare_jobs/apis/openfhe_manager.py)
  - `exec_encrypt_stat_analytics` packs the per-client share: covariate matrix for `biomarker_enc_score_computation` (identical packing to `biomarker_enc_risk_group_computation`), 9-slot for `mean-stdev`, 2-slot for `meta-analysis`.
  - `encrypt_biomarker_model(coeffs_df, cutoff_value, covs, level_val, for_scoring=False)` — packs and encrypts one biomarker model under the multiparty public key. Run by the **leader client** during `workflow_model_upload` (encrypt-at-initiator, §2.6); the server never sees the plaintext. `for_scoring=True` uses `rsf = 1.0` (raw scores, LCS); the default uses `rsf = 1/|cutoff|` (discovery).
  - `aggregate_stat_analytics`:
    - `biomarker_enc_score_computation` shares the discovery-flow branch + parallel worker (`_func_risk_score_multi_model_batch`) and loads the **leader-uploaded** pre-encrypted ciphertext from disk (it never re-encrypts a plaintext CSV). It passes `skip_cutoff=True` so step 7 (cutoff subtraction) is omitted, and drops the log-normal model-hiding mask `rm` from the per-patient masks (that mask only preserves the *sign* of `score − cutoff` for discovery; scoring needs the raw magnitude). Output cipher carries the raw per-patient score per slot.
    - `mean-stdev` runs the rotate-multiply-rotate-subtract pipeline described in §3.2.3. The mask multiply uses the log-normal mask in both modes (column-data and `over_cached_scores`); the over_cached_scores branch uses smaller `(loc, σ)` parameters tuned so the masked slots stay in CKKS precision without a `global_count` divisor — see §3.2.3 step 4 and the DP block in `multiplicative_mask`'s docstring.
    - `meta-analysis` is a pure tree-sum with no mask and a 1-tower compression.
  - `_decrypt_stat_analytics_all_shares` / `_decrypt_stat_analytics_single_shares` carry matching branches for the encrypted-scoring flow (shared with `biomarker_enc_risk_group_computation`), `mean-stdev`, and `meta-analysis`.

### Job folder (ships with `jobs/nvflare_job_template/`, no wheel rebuild)

> The committed `analytics_persistor.py` / `analytics_aggregator.py` / `analytics_executor.py` under `custom/` are thin loader shims; the real classes live in the `*_impl.py` siblings (`analytics_persistor_impl.py`, etc.), loaded at runtime via `duality_wheel_runtime.build_component`. The file references below point at the logical component; the code is in the corresponding `_impl.py`. These take effect directly in the job folder (no wheel rebuild), but for a standalone deploy they ride in the **backend image** (`COPY backend/`), so a backend container rebuild is needed.

- [app_server/custom/analytics_persistor.py](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_persistor.py)
  - `load_model`: workflow_name prefix branches for `workflow_biomarker_score_computation` (reference path), `workflow_biomarker_lr_fit` (reference path — `workflow_biomarker_lr_fit_2` matches the same prefix), `workflow_enc_biomarker_disc` and `workflow_enc_biomarker_score` (encrypted — share the same load path), `workflow_stat_analytics` and `workflow_reference_stat_analytics` (existing).
  - `_validate_workload_args`: accepts the computation_type whitelist `{"mean", "stdev", "mean-stdev", "meta-analysis", "chi2", "kaplan-meier", "t-test", "biomarker_enc_risk_group_computation", "biomarker_enc_score_computation", "biomarker_score_computation", "biomarker_lr_fit"}`; per-type arg validation. `biomarker_enc_score_computation` takes a single `model_key` (parallel to the clear-text `biomarker_score_computation`); the validator wraps it into the `model_keys` list of one and the `biomarker_models_by_key` mapping that the shared HE-dot-product machinery expects. **Fusion validation** is presence-based: a `meta-analysis` workload with `time_column_id` set runs `_validate_and_resolve_lr_fit_args` (same checks as standalone `biomarker_lr_fit`, plus injecting `horizon_threshold`); a `mean-stdev` + `over_cached_scores=true` workload with `model_key` set runs `_validate_and_resolve_score_computation_args` (same checks as standalone `biomarker_score_computation`, resolving `scale_coeff_file_path`).
  - **Per-job invariant caches** on the persistor (`load_model` runs every round; without these the underlying files would be re-read/re-parsed on every round):
    - **`_resolve_horizon_threshold(cutoff_file_path, computation_label)`**: reads the `ER_threshold` column of the cutoff CSV once per file path and caches the parsed float on `self._horizon_threshold_cache`. Used by both the standalone `biomarker_lr_fit` validation and the fused `meta-analysis` validation.
    - **`_global_schema_cache`**: `get_meta_from_schema` opens the global schema JSON exactly once per `schema_path`; subsequent rounds hit the cache.
    - **`_load_pickled_coeffs(scale_coeff_file_path)` + `_pickled_coeffs_cache`**: reads the scale-coeff CSV, normalizes to the three columns clients expect, and pickles once per path. The three coefficient-shipping sites — `kaplan-meier` biomarker discovery, standalone `biomarker_score_computation`, and the fused `mean-stdev` (`over_cached_scores`) — all route through this helper, so the heavy CSV + pandas + pickle path executes once per job instead of once per round.
  - **`_validate_and_resolve_lr_fit_args` / `_validate_and_resolve_score_computation_args`**: extracted shared helpers; each is called from both the standalone-workflow branch and the fused-workflow branch in `_validate_workload_args`, so the two call sites stay in lockstep.
  - `_validate_openfhe_parameters`: `biomarker_enc_score_computation` shares the existing `workflow_enc_biomarker_disc` branch — `depth_required = 4`, mult-keys and index-keys required; the cov-length-dependent rotation-indices check is still deferred to the aggregate handler. `mean-stdev` requires `depth_required = 3` and indices `[1, 2]`. `meta-analysis` requires `depth_required = 1`, no multiplication or rotation keys (the fused `lr_fit` does not add HE cost — it runs on clear-text locally).
  - `get_meta_from_schema`: extended the encrypted-biomarker branch to also handle `biomarker_enc_score_computation` (loads `biomarker_covariates` from the schema, forwards `model_keys` and `biomarker_models_by_key`). Bypasses the schema lookup for `mean-stdev` + `over_cached_scores=true` (forwarding `std_type`) and for `meta-analysis` (no extra metadata). When fusion is active, additionally: for `meta-analysis` with `time_column_id` set, the same numeric-schema check that standalone `biomarker_lr_fit` applies runs here; for `mean-stdev` + `over_cached_scores=true` with `model_key` set, `biomarker_covariates` is read from the schema and the pickled `coeffs` is shipped in `generated_args` (so the client's fused score-computation can use it).

- [app_server/custom/analytics_aggregator.py](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/analytics_aggregator.py)
  - `aggregate` prefix-routes `workflow_enc_biomarker_disc` and `workflow_enc_biomarker_score` through `_workflow_enc_biomarker_disc`. The handler now also accepts `round_idx == 2` (pass-through for the score-computation flow — clients fuse locally, server has nothing to aggregate).
  - `workflow_biomarker_score_computation` and `workflow_biomarker_lr_fit` continue to route through `_workflow_reference_stat_analytics` (clear-text round structure). After fusion, only the reference-path workflows (`workflow_biomarker_score_computation` and `workflow_biomarker_lr_fit_2`) match those prefixes — the encrypted-path lr_fit step has been folded into `workflow_stat_analytics_meta_analysis`.

- [app_client/custom/analytics_executor.py](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/custom/analytics_executor.py)
  - `_task_enc_biomarker_disc` now handles a third round: when `computation_type == "biomarker_enc_score_computation"`, the executor extracts this client's combined-partials ciphertext under its `model_key`, calls `openfhe_manager._remove_biomarker_mask_and_extract_scores` (fuses + strips the privacy mask), re-maps the batched slot vector via `analytics_manager._re_map_batched_patients_biomarker`, trims to `analytics_manager._enc_score_n_patients`, and writes the result onto `analytics_manager.cached_risk_scores`.
  - `_task_stat_analytics` round 0, after `analytics_manager.preprocess()`: if the manager set `_fused_lr_fit_status`, the executor emits a per-client status file via `_write_json(..., stage_dir="biomarker_lr_fit")` so the sweep tests find it at the same path shape as the standalone reference workflow's output.
  - `_write_json`: gained an optional `stage_dir` argument that overrides the default `<computation_type>` segment of the output path. Lets the fused lr_fit status land under `biomarker_lr_fit/` even though the surrounding workflow's `computation_type` is `meta-analysis`.
  - Constructor: new `calc_local_result: bool = True` arg. When False (production deployments), the local-only `aggregate_reference({}, weights)` + postprocess pass is skipped — the per-client `local/local_results.json` is not produced and the executor goes straight to `encrypt`. Saves roughly one postprocess pass per client per round. Default keeps sweep / sim behavior unchanged.

- **Chain configs** (the stager assembles the deployed server config from these — see §2.1):
  - [jobs/configs/config_meta_analysis_enc.json](../app/core/job_runner/nvflare_jobs/jobs/configs/config_meta_analysis_enc.json): encrypted chain `KeyGen → model_upload[Encrypted, for_scoring] → enc_biomarker_disc_score → mean-stdev → meta-analysis (fused lr_fit)`. Persistor `mult_depth: 4`, biomarker indices `[1, 2, 4, 8, 16, 32, 64, 128, 256, -511]`, `hide_result_from_server: true`. Terminal workflow = the encrypted meta-analysis (no reference twin — that is test-only).
  - [jobs/configs/config_meta_analysis_open.json](../app/core/job_runner/nvflare_jobs/jobs/configs/config_meta_analysis_open.json): open chain `KeyGen → biomarker_score_computation → mean-stdev → meta-analysis (fused lr_fit)`.
  - The deployment template [app_server/config/config_fed_server.json](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/config/config_fed_server.json) is a **bare skeleton** (KeyGen + a `workflow_stat_analytics_template` + profile consolidation) plus the persistor/aggregator/`datasource_request_receiver` components; the stager overrides the persistor OpenFHE args per function (`_update_persistor_openfhe_args`) and injects the chain. The stager also requires `num_rounds = 4` on the HE `workflow_stat_analytics*` steps when `hide_result_from_server` (the AES-dispersal round).

- [NVFlareJobStager.py](../app/core/job_runner/nvflare_jobs/NVFlareJobStager.py)
  - `_load_meta_analysis_chain_templates(model_type)` selects the enc vs open chain config; `_build_meta_analysis_chain_for_config` clones it per selected `model_key`, suffixes ids `…__<model_key>`, patches `cancer_type`/`model_key`/`model_keys`, sets the HE `num_rounds`, injects `horizon_threshold` (the non-secret `ER_threshold`) for the encrypted path (the plaintext cutoff CSV is never on the server), and binds the terminal meta-analysis workflow.
  - `_workflow_is_enc_biomarker_disc` excludes `biomarker_enc_score_computation`, and `_insert_model_upload_workflow` skips only on a `for_scoring != true` upload — so LCS scoring and encrypted KM discovery coexist without suppressing each other (§2.7).

- [tests/conftest.py](../app/core/job_runner/nvflare_jobs/tests/conftest.py)
  - `stage_job` / `stage_job_enc`: stage an isolated job under `tmp_path` with the open / encrypted sim config respectively, patching `cancer_type` / `model_key` / `model_keys` into every workflow that declares them. No manual `config_fed_server.json` swap. The encrypted and open sweeps point at `sim_config_fed_server_enc.json` / `sim_config_fed_server.json`; they are separate configs, not a runtime conversion of one into the other.

---

## 5. Workload args

**`workflow_model_upload`** (encrypt-at-initiator — runs after KeyGen on the encrypted path; no `computation_type`):

```jsonc
{
  "model_type":   "Encrypted",
  "for_scoring":  true,                       // LCS: rsf = 1.0 (raw scores). Discovery omits this (rsf = 1/|cutoff|).
  "global_schema": "global_schema.json",
  "cancer_type":  "Non-Small Cell Lung Cancer",
  "model_keys":   ["cox_lasso"]
}
```

The leader client encrypts each `model_keys` entry and uploads ciphertext; the server writes `<model_key>_<cancer_type>[_score]_coeff.ct` / `_cutoff.ct` / `_scale.json` to `app_server/custom` (the `_score` marker is added when `for_scoring`). See §2.6.

**`biomarker_enc_score_computation`** (encrypted scoring — `workflow_enc_biomarker_disc_score`):

```jsonc
{
  "computation_type": "biomarker_enc_score_computation",
  "global_schema":    "global_schema.json",
  "cancer_type":      "Non-Small Cell Lung Cancer",
  "model_key":        "cox_lasso",
  "model_keys":       ["cox_lasso"]
}
```

The persistor resolves `biomarker_models_by_key` to the leader-uploaded `_score` ciphertext artifacts (`for_scoring=True` variant) so the shared HE-dot-product machinery (used by `biomarker_enc_risk_group_computation`) consumes the pre-encrypted model.

**`biomarker_score_computation`** (clear-text scoring — step 5 of the reference phase as a standalone workflow):

```jsonc
{
  "computation_type": "biomarker_score_computation",
  "global_schema":    "global_schema.json",
  "cancer_type":      "Non-Small Cell Lung Cancer",
  "model_key":        "cox_lasso"
}
```

The persistor's `load_model` resolves the biomarker model file paths against the broadcast model dir and pickles the coefficients into `metadata["coeffs"]` (consumed client-side by `local_pre_biomarker_score_computation`). When the user opts for clear-text scoring in **production** (the open-access path), the same `cancer_type` / `model_key` pair instead attaches to the `mean-stdev` workload (see below) and the standalone score-computation workflow is dropped from the staged config — no extra workflow ID is needed.

**`mean-stdev`** — column-data invocation (generic mirror of `stdev`):

```jsonc
{
  "computation_type": "mean-stdev",
  "global_schema":    "global_schema.json",
  "data_column_id":   "<numeric column from global_schema>",
  "std_type":         "sample"             // or "population"
}
```

**`mean-stdev`** — cached-scores invocation (encrypted production step 3 / reference step 6):

```jsonc
{
  "computation_type": "mean-stdev",
  "global_schema":    "global_schema.json",
  "over_cached_scores": true,              // sources from cached_risk_scores
  "std_type":         "sample"
}
```

**`mean-stdev`** — cached-scores invocation with **fused score_computation** (open-access production path, step 3 only):

```jsonc
{
  "computation_type":   "mean-stdev",
  "global_schema":      "global_schema.json",
  "over_cached_scores": true,
  "std_type":           "sample",
  // fused biomarker_score_computation args; presence activates the fused path
  "cancer_type":        "Non-Small Cell Lung Cancer",
  "model_key":          "cox_lasso"
}
```

The presence of `model_key` on an `over_cached_scores=true` workload triggers the fused path: server-side validation runs the same checks as standalone `biomarker_score_computation` and ships `biomarker_covariates` + pickled `coeffs` in `generated_args`; the client's preprocess calls `local_pre_biomarker_score_computation` inline before building the `(sum_sq, sum, count)` share.

`data_column_id` and `over_cached_scores=true` are mutually exclusive. `cached_lr_field` is not supported on `mean-stdev`.

**`biomarker_lr_fit`** (reference-path step 7 standalone workflow):

```jsonc
{
  "computation_type":    "biomarker_lr_fit",
  "global_schema":       "global_schema.json",
  "cancer_type":         "Non-Small Cell Lung Cancer",
  "model_key":           "cox_lasso",
  "time_column_id":      "time",
  "censoring_column_id": "event"
}
```

`horizon_threshold` is not in the YAML — the persistor resolves it from the `<model_key>_<cancer_type>_cutoff.csv` (`ER_threshold` column) via `_resolve_horizon_threshold` and injects it into `workload_args` before the args are broadcast to clients. The resolution is cached per-file-path so repeated rounds don't re-read the CSV.

**`meta-analysis`** — reference-path step 8 (unfused, no extra args):

```jsonc
{
  "computation_type": "meta-analysis",
  "global_schema":    "global_schema.json"
}
```

**`meta-analysis`** — encrypted production step 4 with **fused lr_fit**:

```jsonc
{
  "computation_type":    "meta-analysis",
  "global_schema":       "global_schema.json",
  // fused biomarker_lr_fit args; presence activates the fused path
  "cancer_type":         "Non-Small Cell Lung Cancer",
  "model_key":           "cox_lasso",
  "time_column_id":      "time",
  "censoring_column_id": "event"
}
```

Same pattern as fused mean-stdev: presence of `time_column_id` runs the standalone `biomarker_lr_fit` validation server-side (resolving `horizon_threshold` from the cutoff CSV via the cached helper); the client's `meta-analysis` preprocess calls `local_pre_logistic_regression_with_global_zscore` inline to populate `cached_lr_fit` before building the per-client inverse-variance share. The reference-path meta-analysis workflow does not need these args because the standalone `workflow_biomarker_lr_fit_2` runs immediately before it and populates `cached_lr_fit`.

---

## 6. Return shapes

| Workflow | computation_type | Path | Result dict |
|---|---|---|---|
| step 2 | `biomarker_enc_score_computation` | encrypted | `{"status": "OK"}` (the per-patient scores live in `cached_risk_scores`; no cohort size is shipped) |
| step 5 | `biomarker_score_computation` | reference (clear) | `{"status": "OK"}` |
| steps 3, 6 | `mean-stdev` (cached-scores) | both | `{"mean_scores": float, "stdev_scores": float}` |
| — | `mean-stdev` (column-data) | both | `{"mean": float, "stdev": float}` |
| step 7 | `biomarker_lr_fit` (reference standalone) | reference (clear) | `{"status": "OK"}` (may be `"WARN"` per [§3.6](#36-status-field-diagnostics-warn-and-fail-triggers)) |
| step 4 fused lr_fit | (no aggregation; per-client only) | encrypted | per-client `{"status": "OK"}` or `{"status": "WARN", "msg": ...}` written to `biomarker_lr_fit/<meta_workflow_id>/aggregated/processed_results.json` — same shape as the standalone reference output, only the workflow id segment differs |
| steps 4, 8 | `meta-analysis` | both | `{"meta_beta1": float, "meta_se_beta1": float, "z": float, "p_value": float, "ci_lower": float, "ci_upper": float, "total_inv_var": float}` |

Any of these results may carry an additional `status` field (`'WARN'` or `'FAIL'`) when a numerical or input degeneracy is detected; the canonical list of triggers lives in [§3.6](#36-status-field-diagnostics-warn-and-fail-triggers).

The cached-scores `mean-stdev` postprocess also writes `cached_scores_mean` / `cached_scores_std` on the manager so the next workflow can z-normalize. `biomarker_lr_fit` (standalone, reference path) and the fused `lr_fit` (encrypted path, inside step 4 preprocess) both write `cached_lr_fit` on the manager so the next consumer can build inverse-variance shares.

---

## 7. How to run the tests

The end-to-end validation is the **pytest simulator sweep**, which stages an isolated job under `tmp_path`, runs NVFlare's `SimulatorRunner` (3 clients, `site3` as the non-contributing leader), and asserts the HE meta-analysis agrees with the clear-text reference within `1e-5`. There are two sweeps — encrypted and open-access — sharing fixtures in [tests/conftest.py](../app/core/job_runner/nvflare_jobs/tests/conftest.py).

```sh
cd <repo>/backend/app/core/job_runner/nvflare_jobs

# 1. Rebuild + reinstall the wheel after ANY apis/ change (the simulator imports the
#    installed duality_nvflare_lib; *_impl.py template files take effect directly).
python3 wheels/APIWheelBuilderCI.py
pip install --force-reinstall --no-deps wheels/duality_nvflare_lib-*.whl

# 2. Run a single encrypted case (the runtime only uses the locally installed
#    wheel; it never contacts a package registry). The case id keeps
#    hyphens and replaces spaces with underscores; pick a unique fragment without
#    a hyphen for -k (e.g. "Glioma and cox_lasso").
python3 -m pytest \
  tests/test_simulator_sweep_enc.py -v -k "Glioma and cox_lasso"

# 3. Full sweeps (slow, ~minutes/case):
DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 python3 -m pytest tests/test_simulator_sweep_enc.py -v   # encrypted
DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 python3 -m pytest tests/test_simulator_sweep_open.py -v  # open-access
```

What a passing case verifies:

1. `workflow_KeyGen` builds the CKKS context at `mult_depth = 4` with rotation indices `[1, 2, 4, 8, 16, 32, 64, 128, 256, -511]`.
2. **Encrypted phase** completes in order: `workflow_model_upload` (leader encrypts the model, `for_scoring=true`) → `workflow_enc_biomarker_disc_score` (three rounds: encrypt covariates → partial-decrypt → fuse-and-cache) → `workflow_stat_analytics_scores_mean_stdev` → `workflow_stat_analytics_meta_analysis` (whose preprocess inlines `local_pre_logistic_regression_with_global_zscore` per client before building the share). The per-client lr_fit status file is written to `biomarker_lr_fit/workflow_stat_analytics_meta_analysis/aggregated/processed_results.json`.
3. **Reference phase** completes in order: `workflow_biomarker_score_computation` → `workflow_reference_stat_analytics_scores_mean_stdev` → `workflow_biomarker_lr_fit_2` → `workflow_reference_stat_analytics_meta_analysis`.
4. The two `meta-analysis` outputs (encrypted vs reference) agree within `1e-5` (the sweep's `TOLERANCE`). Cases with no signal auto-SKIP (reference mean-stdev `WARN`, degenerate per-client lr_fit `WARN`, or both paths `FAIL`) — see [§3.6](#36-status-field-diagnostics-warn-and-fail-triggers).
5. **Failure case to watch.** If any encrypted workflow raises (CKKS error logged to its `error.json`), the encrypted meta-analysis should return `status='FAIL'` rather than a plausible-looking number. The reference phase still succeeds; the two outputs are then *not* comparable.

Note: on a fully encrypted path these failures can be silent. Consumers should check the `status` field rather than assume a numeric result is valid.

**Standalone / deployment** runs do **not** go through these sim configs — the backend's `NVFlareJobStager` assembles the chain from `jobs/configs/config_meta_analysis_{enc,open}.json` at submission time (§2.1). Two delivery paths to keep in sync when iterating on a standalone deploy: `apis/` changes ship in the **wheel** (rebuild + redeploy to the nvflare/client containers via the standalone `wheel` command); template (`*_impl.py`, `config_fed_server.json`) and stager changes ship in the **backend image** (`COPY backend/` → rebuild the backend container). A manual `run_simulator.py` on the bare `jobs/nvflare_job_template/` does **not** exercise the LCS chain — the static `config_fed_server.json` is a skeleton; the chain only exists once the stager assembles it.

Server-side aggregated artifacts land under `<workspace>/server/.../simulate_job/<computation_type>/<workflow_id>/aggregated/processed_results.json`; per-client local (Initiator) artifacts under `<workspace>/site-N/.../local/local_results.json`.

---

## 8. Current implementation decisions

1. **`cached_scores_std == 0` is a hard skip.** If every client has identical risk scores (model degeneracy or empty cohort), the global std is zero and every `biomarker_lr_fit` invocation skips the fit. The meta-analysis then FAILs via its aggregate-side guard. Correct behaviour, but worth surfacing in the UI.
2. **Fixed-effects only.** The meta-analysis is fixed-effects (inverse-variance). Random-effects (DerSimonian-Laird with τ²) would need a second federated round to estimate τ² and re-weight; not implemented.
3. **NVFlare does not halt on workflow error.** A failure in any single workflow is logged to that workflow's `error.json` but the next workflow still runs. The two-phase ordering means an encrypted-phase failure surfaces loudly at the encrypted meta-analysis output (FAIL) and the reference phase still produces a usable result.
4. **Production-path lr_fit fusion (presence-based, inline).** The clear-text `biomarker_lr_fit` step is folded into the `meta-analysis` preprocess on the encrypted production path: presence of `time_column_id` on the `meta-analysis` workload triggers the fused local fit before the inverse-variance share is built. Rationale: the standalone step used to ship empty `{}` shares through 2 NVFlare rounds per case — wasted round-trip latency. Modularity is preserved (the helper `local_pre_logistic_regression_with_global_zscore` is unchanged and still callable on its own; the fusion is a wiring-only change), and dispatch is presence-based so an unfused workflow stays a strict subset of the fused one. The open-access chain likewise can fuse `biomarker_score_computation` into the `mean-stdev` preprocess when `model_key` is present on an `over_cached_scores` workload. The **reference twin in the sweep config is intentionally left unfused** so per-client status files (`processed_results.json` per `workflow_biomarker_lr_fit_2` / `workflow_biomarker_score_computation`) keep flowing to the sweep tests' degenerate-fit / failure detection. The encrypted-path fused lr_fit also writes a per-client status file (under the meta-analysis workflow id) so the sweep tests' degenerate-fit count distinguishes "both paths degenerate" from "only one path degenerate".

5. **Production-only `calc_local_result` toggle.** Each round 0 of `_task_stat_analytics` runs a "local-only" pass — `aggregate_reference({}, weights)` plus a postprocess — and writes `local/local_results.json` per client. This is **useful for sweep / simulator debugging** (each client's local view is compared against the aggregated result; per-client divergences surface here before the aggregate is decrypted). It is **wasted work in production**, where only the aggregate matters. The `AnalyticsExecutor` constructor now accepts `calc_local_result: bool` (default True). Set it to `false` in [config_fed_client.json](../app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_client/config/config_fed_client.json) for production deploys to skip the extra postprocess pass.

## 9. Limitations and future work

1. **Share the per-patient mat-vec product across KM + LCS.** When both encrypted KM biomarker discovery and encrypted LCS are selected on the same model, the per-patient score `Σⱼ coef_j · covariate_ij` is currently computed **twice** — once per validation — and the model is encrypted twice (the `rsf = 1/|cutoff|` discovery variant and the `rsf = 1.0` scoring variant, §2.6). The optimization: compute the encrypted mat-vec **once** per `model_key`, cache the resulting per-client scores, and have both consumers read them.
   - The natural unification is on the **raw `rsf = 1.0` score**: LCS uses it directly; KM discovery would derive the risk group from `sign(score − cutoff)` off the same shared score. This collapses the two model_upload variants into one and removes the duplicate dot-product.
   - **Blocker noted during this PR:** moving KM discovery to `rsf = 1.0` is not a free swap. The discovery worker currently subtracts `cutoff · rsf = ±1` (a literal subtract-of-1 enabled by the `1/|cutoff|` rescaling); `rsf = 1.0` means subtracting the actual cutoff and reworking that path, and it loses the noise-margin amplification near the cutoff boundary. There are **no KM tests** today, so this was deliberately deferred to keep the LCS PR from disturbing the shipped KM path. Do this once KM has regression coverage.
2. **The encrypted model path can still reveal the model.** The scores returned to a client are a linear combination of the model weights and that client's covariates. A client with at least as many records as the model has (non-zero) features — or with side-information about which features are non-zero — can solve for the weights. This is inherent to returning per-client scores and is shared with `biomarker_enc_risk_group_computation`.
3. **Encrypt quantities at the minimum CKKS level** to reduce ciphertext size / cost.
4. **Normalization option for cached-scores mean-stdev.** The cached scores aren't schema inputs, so there is no clean `(global_min, global_max)` range to drive the `[-1, 1]` normalization the column-data mode uses.
5. **The mean-stdev multiplicative masking is not fully tested.** Smaller mask magnitudes are currently used on the `over_cached_scores` path; the DP analysis in `multiplicative_mask`'s docstring (§3.2.3) should be validated empirically.
6. **Fixed-effects only.** Random-effects meta-analysis (DerSimonian-Laird with τ²) would need a second federated round to estimate τ² and re-weight; not implemented.
7. **Remaining LCS-specific debug prints** show up even in the General Statistics tasks; gate behind a verbose flag or remove.
8. **Unrelated:** the t-test score card does not show the initiator's results.
9. **General code cleanup** — remove dead code and the remaining debug prints (item 7).
10. **The leader and initiator** are conflated.
