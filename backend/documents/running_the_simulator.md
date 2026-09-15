# Running the NVFlare job in simulator mode

This describes how to run the biomarker NVFlare job template locally with the NVFlare
**simulator** (`scripts/run_simulator.py`), and the items that differ from a standalone /
deployed run.

## TL;DR

```bash
cd backend/app/core/job_runner/nvflare_jobs
python scripts/run_simulator.py \
  -w outputs/stat_analytics -n 3 -t 3 \
  jobs/nvflare_job_template --datasource-version 2_1
```

A clean run ends with `status: 0` (the script exits non-zero on an aborted run). The template's own
`config_fed_server.json` carries no `computation_type`, because the backend stager fills it per
submitted function and would inherit any default placed there, so `run_simulator.py` stages a copy
of the template under `<workspace>_staged_job` with `tests/sim_config_fed_server_km_open.json`:
`workflow_KeyGen → workflow_stat_analytics (open-access Kaplan-Meier, HE) → workflow_reference_stat_analytics (clear-text reference)`.
Pass `--server-config tests/sim_config_fed_server_<km|lcs|combined>_<open|enc>.json` for the other
chains; the encrypted ones run `workflow_model_upload → workflow_enc_biomarker_disc → …`.
The datasource paths come from `standalone/.env.local`; copy `standalone/default.env.local` there on a
fresh checkout (the standalone launcher does this for you).

## Why the simulator differs from standalone

The simulator runs the **static** job template under
`backend/app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/` directly. It does **not**
go through `NVFlareJobStager`, which is what generates the deployed job config. So anything the
stager produces dynamically must already be correct in the static template, or the simulator
silently diverges from standalone. Things the stager normally injects:

- the `workflow_model_upload` stage in `config_fed_server.json`
- `deploy_map.app_client` (the client list)
- `filters.json` (project / datasource group, only needed in deployment)
- `leader_client_name` substitution

## The library wheel (`duality_nvflare_lib`)

The public branch is local-wheel-only. `duality_nvflare_apis` and
`duality_nvflare_workflows` come from the snapshot wheel committed under
`standalone/wheels/`; the job runtime never checks GitLab for a newer copy.

Before a direct venv/pytest simulator run, install that bundled wheel explicitly:

```bash
python -m pip install --force-reinstall --no-index --no-deps \
  standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
```

When invoked from `backend/app/core/job_runner/nvflare_jobs`, use the checkout-relative
path to the same file. The simulator fixtures verify that the installed wheel version
matches the bundled snapshot and fail rather than silently replacing it.

Editing `apis/` or `workflows/` requires rebuilding the snapshot wheel before testing.
Files under `jobs/nvflare_job_template/.../custom/` are **not** in the wheel and take
effect directly.

## Client naming (`siteN` vs `site-N`)

NVFlare's simulator hardcodes `-n N` to **hyphenated** `site-1 .. site-N`, which will not match
the non-hyphenated leader client (`site3`) used in standalone. `scripts/run_simulator.py`
therefore normalizes `-n` into explicit non-hyphenated `siteN` names (passed as `-c`), so NVFlare
never takes its `site-`+i branch. You can also pass names explicitly with `-c site1,site2,site3`.

The names must appear in `meta.json`'s `deploy_map.app_client`. That is a **static,
simulator-only** list (it carries both `siteN` and `site-N` forms). It is *not* synced at runtime
and `meta.json` is never mutated — deployment regenerates `deploy_map` from the real client list
in `NVFlareJobStager`, so the template's list only affects the simulator.

The leader client is `site3`. In `config_fed_server.json` it is expressed as the top-level
`leader_client` key, substituted into `leader_client_name: "{leader_client}"` by NVFlare's config
variable resolution.

## Datasource resolution

- Pass `--datasource-version` in the **`2_<GROUP_ID>`** form (e.g. `2_1`). Plain `2` does **not**
  match the biomarker-model discovery regex and silently falls back to the (empty) client custom
  dir, producing a missing-`weights.csv` error.
- Per-site datasource paths come from `DUALITY_CLIENT_SITE*_DATASOURCE_<suffix>` env vars in
  `standalone/.env.local` (loaded automatically by `run_simulator.py`; seed it from `standalone/default.env.local`).
- Patient-data tasks resolve `stat_data_path` locally in the simulator (gated by
  `FL_IS_SIMULATOR`) via `FHIRBaseConfigResolver._resolve_simulator_datasource_path`, bypassing the
  backend HTTP lookup used in deployment. `task_model_upload` needs no datasource (it only encrypts
  the model CSVs); `task_enc_biomarker_disc` and `task_stat_analytics` do.

## `num_rounds` vs `hide_result_from_server`

`workflow_stat_analytics` round count depends on the persistor's `hide_result_from_server`:

| `hide_result_from_server` | required `num_rounds` |
| --- | --- |
| `true`  | `4` (extra round to disperse the AES-decrypted payload to clients) |
| `false` | `3` |

Keep `persist_every_n_rounds` equal to `num_rounds` (persist on the final round), matching the
other workflows.

## Direct pytest defaults on the public branch

Direct simulator tests resolve biomarker models from
`standalone/client_utils/model_files/project_2/datasource_group_1` through the shared
`tests/conftest.py` default. A raw Linux `pytest` run therefore does not require
`DUALITY_SIM_BIOMARKER_MODELS_ROOT` to be exported. The same fixture requires the
installed `duality_nvflare_lib` version to match the bundled snapshot.
