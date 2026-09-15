# Datasource Configuration and Sync

## Configuration-Only `test_data`

`client-supervisor/test_data` contains only the FHIR base configuration JSON files:

```text
test_data/
├── DUALITY_FHIR_BASE_CONFIG_site1.json
├── DUALITY_FHIR_BASE_CONFIG_site2.json
└── DUALITY_FHIR_BASE_CONFIG_initiator.json
```

These files define where datasource files should be placed for each site and project. They are not the datasource corpus.

## Actual Datasource Location

Datasource JSON or ZIP files live under:

```text
share/standalone/nvflare_stage/data
```

The supervisor also loads:

```text
share/standalone/.env.local
```

## `install.ini`

Current mapping:

```ini
[Data]
site1=test_data/DUALITY_FHIR_BASE_CONFIG_site1.json
site2=test_data/DUALITY_FHIR_BASE_CONFIG_site2.json
site3=test_data/DUALITY_FHIR_BASE_CONFIG_initiator.json
```

The server name remains under `[Server]`, but server tar staging is not a supervisor responsibility.

## Datasource Environment Keys

The supervisor honors the same keys used by the standalone client builder.

Ungrouped project example:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_1=/path/to/data.json
```

Grouped project examples:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_2_1=/path/to/group1.json
DUALITY_CLIENT_SITE1_DATASOURCE_2_1=/path/to/mskchord.json
DUALITY_CLIENT_SITE1_DATASOURCE_2_3=/path/to/group3.json
```

A site-wide legacy override may also be recognized:

```text
DUALITY_CLIENT_SITE1_DATASOURCE=/path/to/data.json
```

## Resolution Priority

When a configuration JSON identifies a destination, the supervisor resolves the source in this order:

1. Matching explicit `.env.local` datasource mapping.
2. Matching filename under `standalone/nvflare_stage/data`.
3. Matching ZIP under the same data directory that can produce the required JSON.

An explicit environment mapping wins over filename discovery.

## Sync Command

Sync one site:

```bash
python3 main.py update_data --site site1
```

Sync all configured entries:

```bash
python3 main.py update_data
```

Control replacement behavior:

```bash
python3 main.py update_data --site site1 --overwrite
python3 main.py update_data --site site1 --no-overwrite
```

The client launch flow performs datasource sync before starting NVFlare.

## Runtime Package Model

There is no user-facing wheel staging or install directory in `client-supervisor`. Submitted NVFlare jobs install or update the Duality package when required.
