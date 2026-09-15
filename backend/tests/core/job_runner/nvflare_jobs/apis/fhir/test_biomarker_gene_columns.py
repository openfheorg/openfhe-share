from app.core.job_runner.nvflare_jobs.apis.fhir.biomarker_gene_columns import (
    BIOMARKER_GENE_COLUMNS,
    _is_pbrm1_observation_code_query_template,
    merge_biomarker_gene_columns_into_analysis_data_schema,
    merge_biomarker_gene_columns_into_analysis_query_schema,
)


def test_analysis_data_schema_expansion_clones_pbrm1_rule():
    schema = {
        "computations": {
            "meta-analysis": {
                "properties": {
                    "gene": {
                        "columns": {
                            "pbrm1": {
                                "extractor": "observation_value_string_by_code",
                                "args": {"code": "PBRM1", "allowedValues": ["MUT", "WT"]},
                            }
                        }
                    }
                }
            }
        }
    }

    merge_biomarker_gene_columns_into_analysis_data_schema(schema)
    columns = schema["computations"]["meta-analysis"]["properties"]["gene"]["columns"]

    assert set(BIOMARKER_GENE_COLUMNS).issubset(columns)
    assert columns["tp53"]["args"]["code"] == "TP53"
    assert columns["pbrm1"]["args"]["code"] == "PBRM1"
    assert columns["tp53"] is not columns["pbrm1"]


def test_analysis_query_schema_expansion_updates_observation_code():
    schema = {
        "computations": {
            "meta-analysis": {
                "properties": {
                    "gene": {
                        "columns": {
                            "pbrm1": {
                                "resources": [
                                    {
                                        "resourceType": "Observation",
                                        "params": [{"name": "code", "value": "PBRM1"}],
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
    }

    merge_biomarker_gene_columns_into_analysis_query_schema(schema)
    columns = schema["computations"]["meta-analysis"]["properties"]["gene"]["columns"]
    assert columns["vhl"]["resources"][0]["params"][0]["value"] == "VHL"


def test_query_template_detection_requires_observation_code_parameter():
    assert _is_pbrm1_observation_code_query_template(
        {"resources": [{"resourceType": "Observation", "params": [{"name": "code", "value": "PBRM1"}]}]}
    )
    assert not _is_pbrm1_observation_code_query_template(
        {"resources": [{"resourceType": "Patient", "params": [{"name": "code", "value": "PBRM1"}]}]}
    )
