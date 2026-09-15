# Local Datasource Staging and Runtime Lookup

## Purpose

Standalone no longer builds or injects a client-side FHIR base config file. It still stages local JSON datasource files into client containers, but the datasource value used by analytics code is resolved at job runtime through the NVFlare server and backend user settings lookup.

## Current Local Flow

```text
.env.local
  -> contains host-side datasource file locations used by client_utils

client_utils/create_client.py
  -> reads DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT>_<GROUP>
  -> resolves each local JSON path relative to the standalone repository
  -> copies JSON files into client_utils/injected_datasources/

client.Dockerfile
  -> copies injected datasource JSONs into the client image
  -> files are available at /data/client/<filename>.json

backend MySQL
  -> stores the runtime datasource value for each user/project/group
  -> local General Statistics and biomarker values use /data/client/<filename>.json

NVFlare job runtime
  -> client asks the server for its datasource
  -> server asks backend /clients/datasource/source
  -> client receives and uses /data/client/<filename>.json or a FHIR /fhir URL
```

## Retired Client Config Artifacts

The standalone client build does not need these runtime artifacts:

```text
client_utils/DUALITY_FHIR_BASE_CONFIG.json
/opt/nvflare/DUALITY_FHIR_BASE_CONFIG.json
DUALITY_NVFLARE_FHIR_BASE_CONFIG
```

Datasource config is backend state. Local JSON files are still copied into the container as data files.

## Environment Values

Datasource staging variables use this pattern:

```text
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>_<DATASOURCE_GROUP_ID>=<host-side source path>
```

Current local staging values (General Statistics, project `1`, no datasource group):

```text
DUALITY_CLIENT_SITE3_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part1.json
DUALITY_CLIENT_SITE1_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part2.json
DUALITY_CLIENT_SITE2_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part3.json
```

Current biomarker local staging values (project `2`, datasource group `1`):

```text
DUALITY_CLIENT_SITE3_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_training_bundle.json

DUALITY_CLIENT_SITE1_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json

DUALITY_CLIENT_SITE2_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json
```

These values are source paths for build-time staging. They are not the values that should be returned to a running client by the backend.

## Runtime Values Stored in Backend for Local

For local standalone, backend-seeded datasource values use the client container path:

| Site | Group | Runtime datasource value |
| --- | --- | --- |
| `site1` | General Statistics, no group (`DEFAULT`) | `/data/client/Survivability_FHIR_Data_part2.json` |
| `site2` | General Statistics, no group (`DEFAULT`) | `/data/client/Survivability_FHIR_Data_part3.json` |
| `site3` | General Statistics, no group (`DEFAULT`) | `/data/client/Survivability_FHIR_Data_part1.json` |
| `site1` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json` |
| `site2` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json` |
| `site3` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_training_bundle.json` |

`site3` maps to the backend `initiator` user.

## Client Utility Responsibilities

`client_utils/create_client.py` is responsible for:

1. Loading `.env.local` or an explicit `--env-file`.
2. Collecting `DUALITY_CLIENT_<SITE>_DATASOURCE...` entries.
3. Resolving local JSON source files.
4. Extracting matching `.zip` files when a `.json` target is missing but a same-name `.zip` exists.
5. Copying local JSON files into `client_utils/injected_datasources/`.
6. Building the client image so those files land in `/data/client/`.
7. Registering the NVFlare client/site mapping in MySQL.

The helper cleans up `client_utils/injected_datasources/` and the temporary per-site compose file after the Docker compose command completes.

## Failure Modes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Client rejects datasource as invalid local path | Backend returned a host path such as `nvflare_stage/data/...` or `/home/client1/...` during local container execution. | Store/return `/data/client/<filename>.json` for local runtime. |
| JSON file missing inside client container | Env staging value points to a missing host-side file or duplicate basename. | Verify `nvflare_stage/data/...` exists before building the client. |
| Server returns no datasource | `nvflare_clients` does not map the site to the expected user, or `users_fhir_source_by_project` has no row for user/project/group. | Re-run backend initialization/client registration and verify datasource rows. |
| FHIR URL rejected in UserSettings | URL does not normalize to a valid `http(s)://.../fhir` value. | Save a URL ending in `/fhir`. |
