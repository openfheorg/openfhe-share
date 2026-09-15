# Global-schema selection

Place this `global_schema/` directory beside `NVFlareJobStager.py` in the backend source tree.

## Runtime selection

`NVFlareJobStager` stages exactly one file into each generated job at:

```text
app_server/custom/global_schema.json
```

The source is selected as follows:

| Project | Datasource group | Source schema |
|---|---:|---|
| 1 | none | `global_schema/project_1/global_schema.json` |
| 2 | 1 | `global_schema/project_2/datasource_group_1/global_schema.json` |

Project 2 intentionally fails staging when no datasource group is supplied or the requested group has no schema. It must not silently fall back to a different group's schema.

## How Project 2 schemas were built

Each Project 2 schema begins with the supplied baseline `global_schema.json`. Only this model-derived field is replaced:

```text
metadata.biomarker_covariates
```

It is the sorted, de-duplicated union of `covariate` values from every `*_weights.csv` in that datasource group.

Other `metadata` and `columns` values are preserved because the model weight files do not contain enough information to derive them safely.

| Datasource group | Weight files scanned | Unique biomarker covariates |
|---:|---:|---:|
| 1 | 45 | 428 |

The public biomarker pipeline includes only the MSKChord datasource group.

## Refreshing schemas after model changes

Use `build_global_schemas.py` to regenerate the directory from the baseline schema plus the current model-file archives or directories. Commit the generated `global_schema.json` files together with the matching model artifacts.
