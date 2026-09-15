"""
Shared list of somatic biomarker gene column IDs (lowercase keys, uppercase FHIR codes).

Used by filter_engine, analysis_data / analysis_query schema expansion, and global_schema.json
should stay aligned with this set.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

# Keys are lowercase column ids (API / workload args); FHIR Observation.code uses .upper().
BIOMARKER_GENE_COLUMNS = frozenset(
    g.lower()
    for g in (
        "ARID1A",
        "ATM",
        "BAP1",
        "COL9A3",
        "KDM5C",
        "MTOR",
        "NF2",
        "PBRM1",
        "PCK1",
        "PIK3CA",
        "PTEN",
        "S100B",
        "SETD2",
        "SMARCA4",
        "TCEB1",
        "TP53",
        "TRMT2B",
        "TSC1",
        "USP32",
        "VHL",
        "WNT8A",
        "ZNF800",
    )
)


def merge_biomarker_gene_columns_into_analysis_data_schema(schema: Dict[str, Any]) -> None:
    """
    For each computation property that defines `pbrm1` with observation_value_string_by_code,
    add one column entry per gene in BIOMARKER_GENE_COLUMNS (same extractor/allowedValues, code set per gene).
    """
    computations = schema.get("computations") or {}
    for comp_block in computations.values():
        if not isinstance(comp_block, dict):
            continue
        for prop_block in (comp_block.get("properties") or {}).values():
            if not isinstance(prop_block, dict):
                continue
            columns = prop_block.get("columns")
            if not isinstance(columns, dict):
                continue
            tmpl = columns.get("pbrm1")
            if not isinstance(tmpl, dict):
                continue
            if _normalize(tmpl.get("extractor")) != "observation_value_string_by_code":
                continue
            for gene_lower in sorted(BIOMARKER_GENE_COLUMNS):
                gene_upper = gene_lower.upper()
                rule = copy.deepcopy(tmpl)
                args = dict(rule.get("args") or {})
                args["code"] = gene_upper
                rule["args"] = args
                columns[gene_lower] = rule


def merge_biomarker_gene_columns_into_analysis_query_schema(schema: Dict[str, Any]) -> None:
    """
    For each computation property that defines `pbrm1` with Observation?code=PBRM1,
    add matching resource rules for every gene in BIOMARKER_GENE_COLUMNS.
    """
    computations = schema.get("computations") or {}
    for comp_block in computations.values():
        if not isinstance(comp_block, dict):
            continue
        for prop_block in (comp_block.get("properties") or {}).values():
            if not isinstance(prop_block, dict):
                continue
            columns = prop_block.get("columns")
            if not isinstance(columns, dict):
                continue
            tmpl = columns.get("pbrm1")
            if not isinstance(tmpl, dict):
                continue
            if not _is_pbrm1_observation_code_query_template(tmpl):
                continue
            for gene_lower in sorted(BIOMARKER_GENE_COLUMNS):
                gene_upper = gene_lower.upper()
                rule = copy.deepcopy(tmpl)
                for res in rule.get("resources") or []:
                    if _normalize(res.get("resourceType")) != "observation":
                        continue
                    for param in res.get("params") or []:
                        if _normalize(param.get("name")) != "code":
                            continue
                        if param.get("value") is not None:
                            param["value"] = gene_upper
                columns[gene_lower] = rule


def _normalize(v: Any) -> str:
    return str(v or "").strip().lower()


def _is_pbrm1_observation_code_query_template(column_block: Dict[str, Any]) -> bool:
    for res in column_block.get("resources") or []:
        if _normalize(res.get("resourceType")) != "observation":
            continue
        for param in res.get("params") or []:
            if _normalize(param.get("name")) == "code" and param.get("value") is not None:
                return True
    return False
