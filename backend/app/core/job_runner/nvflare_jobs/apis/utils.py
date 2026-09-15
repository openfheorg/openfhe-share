import logging
import os
import re
import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

import pandas as pd
import numpy as np
import scipy.stats as stats
import math
import json
from pandas.api.types import is_numeric_dtype, is_categorical_dtype

from .fhir import filter_engine_config
from .FHIRBaseConfigResolver import FHIRBaseConfigResolver
from .warn_exception import WarnException


# Slice key for the SERVER's own patients in the encrypted biomarker risk-score result map
# ({model_key: {site: ct}}). Chosen so it cannot collide with any client/site name. When the
# server is a data owner, its covariates are scored homomorphically alongside the clients and
# its scores are recovered via the standard multiparty decryption under this key.
biomarker_server_risk_key = "__server_local__"


# ── Encrypted-biomarker computation-type taxonomy ─────────────────────────────
# Single source of truth for the biomarker HE ``computation_type`` string sets.
# These were previously re-expressed as ~12 inline tuples across openfhe_manager,
# stat_analytics, and the aggregator/persistor/executor job-template modules; the
# parallel ``elif`` chains there now read by ROLE. Membership here is authoritative
# -- changing a role set updates every consumer (e.g. retiring a computation type
# is a single edit here, not a hunt across four files).
ENC_BIOMARKER_RISK_GROUP_COMPUTATION = "biomarker_enc_risk_group_computation"   # fused KM discovery: dot product + KM tail in one workflow
ENC_BIOMARKER_SCORE_CACHE            = "biomarker_enc_score_cache"              # split producer: dot product + neutral pack, cache, no decrypt
ENC_BIOMARKER_SCORE_POSTPROCESS      = "biomarker_enc_score_postprocess"        # split LCS consumer: x 1/rsf tail from the cache
ENC_BIOMARKER_RISK_GROUP_POSTPROCESS = "biomarker_enc_risk_group_postprocess"   # split KM consumer: -cutoff then x rm tail from the cache

# Every encrypted-biomarker computation type.
ENC_BIOMARKER_ALL = (
    ENC_BIOMARKER_RISK_GROUP_COMPUTATION,
    ENC_BIOMARKER_SCORE_CACHE,
    ENC_BIOMARKER_SCORE_POSTPROCESS,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
)

# Types whose workflow runs the homomorphic dot product (client encrypt + server
# aggregate): the fused KM discovery and the split score-cache producer.
ENC_BIOMARKER_DOT_PRODUCT_TYPES = (
    ENC_BIOMARKER_RISK_GROUP_COMPUTATION,
    ENC_BIOMARKER_SCORE_CACHE,
)

# Types with a server partial-decrypt round -- everything except the no-decrypt cache producer.
ENC_BIOMARKER_DECRYPT_TYPES = (
    ENC_BIOMARKER_RISK_GROUP_COMPUTATION,
    ENC_BIOMARKER_SCORE_POSTPROCESS,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
)

# Types that consume the "_score" (for_scoring) model upload -- everything except the
# fused KM discovery, which reads the discovery upload variant.
ENC_BIOMARKER_SCORE_VARIANT = (
    ENC_BIOMARKER_SCORE_CACHE,
    ENC_BIOMARKER_SCORE_POSTPROCESS,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
)

# Types whose dot product packs the score with NO cutoff subtraction (the score-cache
# producer; the risk-group/discovery type subtracts the cutoff during the pack).
ENC_BIOMARKER_SKIP_CUTOFF_TYPES = (
    ENC_BIOMARKER_SCORE_CACHE,
)

# Split-architecture from-cache consumers (no dot product; apply a per-slot tail).
ENC_BIOMARKER_POSTPROCESS_TYPES = (
    ENC_BIOMARKER_SCORE_POSTPROCESS,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
)

# Types whose workflow has a terminal round-2 fuse/ack (num_rounds=3): the split LCS
# postprocess. (The KM variants are num_rounds <= 2.)
ENC_BIOMARKER_ROUND2_ACK_TYPES = (
    ENC_BIOMARKER_SCORE_POSTPROCESS,
)

# stat_analytics props/preprocess lineages:
#   SCORE      = the score-packing lineage (the score-cache producer + LCS postprocess)
#   RISK_GROUP = the KM lineage (fused discovery + KM postprocess)
ENC_BIOMARKER_SCORE_FAMILY = (
    ENC_BIOMARKER_SCORE_CACHE,
    ENC_BIOMARKER_SCORE_POSTPROCESS,
)
ENC_BIOMARKER_RISK_GROUP_FAMILY = (
    ENC_BIOMARKER_RISK_GROUP_COMPUTATION,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
)


def _is_json_data_source(stat_data_path: str) -> bool:
    return isinstance(stat_data_path, str) and stat_data_path.strip().lower().endswith(".json")


def _is_url_data_source(stat_data_path: str) -> bool:
    if not isinstance(stat_data_path, str):
        return False
    s = stat_data_path.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


# parsed-FHIR-bundle cache
_BUNDLE_CACHE = OrderedDict()          # abspath -> parsed bundle (LRU)
_BUNDLE_CACHE_LOCK = threading.Lock()
_BUNDLE_CACHE_MAX = 2                   # bound resident bundles (each can be hundreds of MB)

# extract_time_event_arrays() re-derives the cohort's (time, event) arrays from the FHIR
# bundle: load -> apply filters -> build the kaplan-meier dataframe. The result depends
# only on (dataset, filters, columns, cancer_type), but it is called once per model per
# round from BOTH the mean/stdev share and the LR fit, so the same extraction was being
# rebuilt many times per job. The bundle and subject caches underneath it already hit;
# what is uncached -- and what this memo saves -- is the dataframe assembly over the
# whole cohort, which is O(patients) every time.
_TIME_EVENT_CACHE = OrderedDict()       # key -> (time_arr, event_arr)
_TIME_EVENT_CACHE_LOCK = threading.Lock()
_TIME_EVENT_CACHE_MAX = 4               # a few (dataset, filter set) pairs in play at once


def _load_stat_data_source(stat_data_path: str):
    if _is_json_data_source(stat_data_path):
        key = os.path.abspath(stat_data_path)
        with _BUNDLE_CACHE_LOCK:
            if key in _BUNDLE_CACHE:
                _BUNDLE_CACHE.move_to_end(key)
                return _BUNDLE_CACHE[key], filter_engine_config
        # Parse outside the lock; a rare concurrent double-parse of the same file is harmless.
        try:
            with open(stat_data_path, "r") as f:
                bundle = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Dataset not found at: {stat_data_path}")
        except Exception as e:
            raise IOError(f"Error reading JSON file: {e}")
        with _BUNDLE_CACHE_LOCK:
            _BUNDLE_CACHE[key] = bundle
            _BUNDLE_CACHE.move_to_end(key)
            while len(_BUNDLE_CACHE) > _BUNDLE_CACHE_MAX:
                _BUNDLE_CACHE.popitem(last=False)
        return bundle, filter_engine_config

    if _is_url_data_source(stat_data_path):
        return stat_data_path, filter_engine_config

    raise ValueError(
        f"Unsupported stat_data_path '{stat_data_path}'. Expected a .json file path or an http(s) FHIR server URL."
    )


def _get_fhir_context_for_stat_data_path(stat_data_path: str):
    """Resolve project and datasource-group context for FHIR configuration lookup."""
    if not isinstance(stat_data_path, str) or not stat_data_path.strip():
        return None, None

    source = stat_data_path.strip()
    project_id = FHIRBaseConfigResolver.get_project_for_base(source)
    datasource_group_id = FHIRBaseConfigResolver.get_datasource_group_for_base(source)

    if FHIRBaseConfigResolver._is_simulator_mode():
        suffix = os.getenv("DUALITY_SIM_DATASOURCE_VERSION", "").strip()
        match = re.match(r"^(\d+)(?:_(\d+))?$", suffix)
        if match:
            if project_id is None:
                project_id = match.group(1)
            if datasource_group_id is None and match.group(2) is not None:
                datasource_group_id = match.group(2)

    return project_id, datasource_group_id


def _get_project_id_for_stat_data_path(stat_data_path: str):
    return _get_fhir_context_for_stat_data_path(stat_data_path)[0]


def _apply_filters_with_optional_project_id(
    active_filter_engine,
    filters,
    bundle,
    project_id=None,
    datasource_group_id=None,
):
    if project_id is not None or datasource_group_id is not None:
        return active_filter_engine.apply_filters(
            filters,
            bundle,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        )
    return active_filter_engine.apply_filters(filters, bundle)


def multiplicative_mask(loc=19.42, sigma=5.22, min_band=-3, max_band=3):
    """
    Returns a multiplicative mask R with magnitude clipped to prevent underflow
    and to limit its maximum magnitude based on a max_band-sigma band of Z.

    Args:
        loc (float): Mean (“centre”) of the distribution.
        sigma (float): The standard deviation for the Gaussian noise Z.
        min_band (float): The min absolute value for the mask R to prevent numerical
                                    underflow is calculated as min_band * sigma
        max_band (float): The max absolute value for the mask R to prevent numerical
                                    overflow is calculated as max_band * sigma
    Returns:
        float: The clipped multiplicative mask R.
    """
    Z = np.clip(np.random.normal(loc, sigma), loc + min_band * sigma, loc + max_band * sigma)
    R = np.exp(Z)

    # COMPLEX: Mean, stdev, t-test: R=e^[0, 38.84] -> (loc, sigma) = (19.42, 5.22)
    # COMPLEX: KM: R=e^[0, 29]  (10 bits of AdditiveMask). KM can tolerate higher but logRank test cannot. (loc, sigma) = (14.5, 3.89)
    # COMPLEX: chi2: R=e^[0, 19]  (20 bits of AdditiveMask). 2 decimal points. p_value - 5 decimal points. (loc, sigma) = (9.5, 2.55)
    # REAL: Mean, stdev: R=e^[-4, 34.84]. Only 2 decimal digit precision at [-4, 0]. (loc, sigma) = (15.42, 6.47)
    # REAL: T-Test: R=e^[-2, 28]. Only 3 decimal digit precision at extremes. p_value has 4 digits. (loc, sigma) = (13.00, 5.00)
    # REAL: KM: R=e^[0, 11]  (10 bits of AdditiveMask). Only 3 decimal digit precision. p_value has 5 digits. Can do -1 but p_value has 3 digits. (loc, sigma) = (5.50, 1.83)
    # REAL: chi2: R=e^[0, 19] (20 bits of AdditiveMask). (loc, sigma) = (9.50, 3.17)
    # R = np.exp(loc + max_band * sigma)    # Test max values
    # R = np.exp(loc + min_band * sigma)    # Test min values

    return abs(R)

def additive_mask(length, lambda_val=1048576.0):
    """
    Generates a list of 'length' random values that sum to zero.

    This function creates a vector of random numbers from a normal distribution,
    where the last element is specifically calculated to ensure the sum of all
    elements is exactly zero. The magnitude of the generated numbers is controlled
    by 'lambda_val', which acts as a scaling factor for the standard deviation.

    Args:
        length (int): The desired length of the additive mask vector.
        lambda_val (float): A parameter that controls the magnitude of the
                            generated random values.

    Returns:
        list: A list of 'length' floats whose sum is zero.
    """
    if length <= 0:
        return []

    # Generate length-1 random numbers from a normal distribution
    # Using lambda_val/3.0 to ensure most values fall within +/- lambda_val
    random_values = np.random.normal(0.0, lambda_val / 3.0, length - 1).tolist()

    # The last element ensures the sum is zero
    random_values.append(-sum(random_values))

    return random_values

def log_tree_op(op, list_party_data, is_encrypted=True, op_fn=None):
    """
    Recursively performs pairwise operations (log-tree op) over a list of client data.

    Args:
        list_party_data: List of client data (either encrypted lists or model dicts).
        op (str): The operation to perform ('add', 'mult', etc.).
        is_encrypted (bool): Whether the data is encrypted.
        op_fn: Function to apply the operation (required if is_encrypted).

    Returns:
        Aggregated result (list of ciphertexts or model dict).
    """
    if op not in ["add", "sub", "mult"]:
        raise ValueError(f"Invalid operation {op}.")
    if is_encrypted and len(list_party_data) > 1 and op_fn is None:
        raise ValueError("op_fn must be provided for encrypted data aggregation.")

    if len(list_party_data) == 1:
        return list_party_data[0]
    elif len(list_party_data) == 2:
        if is_encrypted:
            return op_fn(op, list_party_data[0], list_party_data[1])
        return op_two_models_dict(op, list_party_data[0], list_party_data[1])
    else:
        mid = len(list_party_data) // 2
        left_sum = log_tree_op(op, list_party_data[:mid], is_encrypted, op_fn)
        right_sum = log_tree_op(op, list_party_data[mid:], is_encrypted, op_fn)
        if is_encrypted:
            return op_fn(op, left_sum, right_sum)
        return op_two_models_dict(op, left_sum, right_sum)

def op_two_models_dict(op, dict_model1, dict_model2):
    """
    Element-wise operation of two model dictionaries (plaintext weights).

    Args:
        dict_model1: First model dictionary.
        dict_model2: Second model dictionary.

    Returns:
        New model dictionary with values defined by function=op.
    """
    result = {}
    if op == "add":
        for layer in dict_model1:
            result[layer] = dict_model1[layer] + dict_model2[layer]
    elif op == "sub":
        for layer in dict_model1:
            result[layer] = dict_model1[layer] - dict_model2[layer]
    elif op == "mult":
        for layer in dict_model1:
            result[layer] = dict_model1[layer] * dict_model2[layer]
    return result

def average_model_dict(model_dict, num_models):
    """
    Averages the weights in a model dictionary by dividing by the number of models.

    Args:
        model_dict: Model dictionary to average.
        num_models: Number of models aggregated.

    Returns:
        Averaged model dictionary.
    """
    for k in model_dict:
        model_dict[k] = model_dict[k] / num_models
    return model_dict


def pre_count(stat_data_path: str, workload_args: dict, threshold: int, filters):
    """
    Computes the local pre-count for different computation types based on workload arguments.

    Now operates on a JSON FHIR bundle and uses filter_engine to:
      - Apply FHIR filters once to get the cohort (subject IDs).
      - For each workflow, build the appropriate DataFrame via extract_data_for_computation_type.
      - Count the number of valid rows used for that computation.

    Args:
        stat_data_path (str): Path to JSON FHIR bundle.
        workload_args (dict): { workflow_name: { "computation_type": ..., ... } }
        threshold (int): The minimum required sample count threshold.
        filters: FHIR filter spec (whatever filter_engine.apply_filters expects).

    Returns:
        list: A list of local pre-counts in the order of workload_args keys.

    Note: The function does not validate the presence of category values in the global categories.
        This means that the threshold flag can pass even when it shouldn't, if the data contains unexpected categories.
        However, the actual workflow computations will fail later if unexpected categories are present; so, there isn't
        a security issue as long as data isn't manipulated between workflows.
    """
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

    # Get subject IDs after applying FHIR filters once
    subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)

    threshold_pass_flag = []

    for w_name, w_args in workload_args.items():
        computation_type = w_args.get("computation_type", None)
        if computation_type is None:
            raise ValueError(
                f"Computation type not specified in workload args for workflow: {w_name}."
            )

        is_biomarker_discovery = w_args.get("is_biomarker_discovery", None)
        over_cached_scores = bool(w_args.get("over_cached_scores", False))

        # Build the computation-specific DataFrame via filter_engine (biomarker )
        if not over_cached_scores and (is_biomarker_discovery is None or is_biomarker_discovery == False):
            df = active_filter_engine.extract_data_for_computation_type(
                computation_type=computation_type,
                bundle=bundle,
                subject_ids=subject_ids,
                workload_args=w_args,
                project_id=project_id,
                datasource_group_id=datasource_group_id,
            )

        if computation_type in ("mean", "stdev", "mean-stdev"):
            if over_cached_scores:
                count = active_filter_engine.build_biomarker_subjects_dataframe(
                    bundle,
                    subject_ids,
                    [],
                    project_id=project_id,
                    datasource_group_id=datasource_group_id,
                    cancer_type=_resolve_biomarker_cancer_type(w_args.get("cancer_type"), filters),
                ).shape[0]
            else:
                data_column_id = w_args.get("data_column_id", None)
                if data_column_id not in df.columns:
                    raise ValueError(
                        f"Column '{data_column_id}' not found in extracted data for workflow '{w_name}'."
                    )
                dtype = df[data_column_id].dtype
                if not (np.issubdtype(dtype, np.number) or dtype == object):
                    raise ValueError(
                        f"Column '{data_column_id}' must be numeric or object, got {dtype}."
                    )
                if dtype == object:
                    count = len(pd.to_numeric(df[data_column_id], errors='coerce').dropna().values)
                else:
                    count = len(df[data_column_id].dropna().values)

        elif computation_type == "chi2":
            # Note: Didn't check that category values belong to global categories.
            category_column_1_id = w_args.get("category_column_1_id", None)
            category_column_2_id = w_args.get("category_column_2_id", None)

            if (
                category_column_1_id not in df.columns
                or category_column_2_id not in df.columns
            ):
                raise ValueError(
                    f"Columns '{category_column_1_id}' or '{category_column_2_id}' not found in extracted data."
                )
            count = df[[category_column_1_id, category_column_2_id]].dropna().shape[0]

        elif computation_type == "kaplan-meier":
            # Note: Didn't check that group values belong to group_categories.
            is_biomarker_discovery = w_args.get("is_biomarker_discovery", None)
            if is_biomarker_discovery is not None and is_biomarker_discovery == True:
                # cancer_type = w_args.get("cancer_type")
                # df = df[df["CANCER_TYPE"] == cancer_type].dropna()
                count = len(subject_ids)
            else:
                count = df.dropna().shape[0]

        elif computation_type == "t-test":
            data_column_id = w_args.get("data_column_id")
            category_column_1_id = w_args.get("category_column_1_id")

            if data_column_id not in df.columns or category_column_1_id not in df.columns:
                raise ValueError(
                    f"Columns '{data_column_id}' or '{category_column_1_id}' not found in extracted data."
                )
            count = df[[data_column_id, category_column_1_id]].dropna().shape[0]

        elif computation_type == "meta-analysis":
            time_column_id = w_args.get("time_column_id")
            censoring_column_id = w_args.get("censoring_column_id")
            if time_column_id not in df.columns or censoring_column_id not in df.columns:
                raise ValueError(
                    f"Columns '{time_column_id}' or '{censoring_column_id}' not found in extracted data for workflow '{w_name}'."
                )
            count = df[[time_column_id, censoring_column_id]].dropna().shape[0]

        else:
            raise ValueError(f"Unsupported computation type '{computation_type}' in pre_count.")

        # Clipping count to threshold
        if count > threshold:
            count = threshold
        threshold_pass_flag.append(count)
    return threshold_pass_flag


def local_pre_mean(
    data_column_id,
    stat_data_path,
    global_min=None,
    global_max=None,
    global_count=None,
    filters=None,
):
    """
        Performs sum computation on the specified data column using FHIR + filter_engine.

        Returns sum value and count within the specified column.
        If range_val and global_min are provided, uses
            2*(sum(data/range_val) - count*global_min/range_val) - count
          scaled by global_count.
        If neither of those are provided, it returns un-scaled reference sum and count.

        Ignores NaN/null values and non-numeric data.
    """
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

    # Apply FHIR filters -> subject IDs
    subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)

    workload_args = {
        "computation_type": "mean",
        "data_column_id": data_column_id,
    }
    df = active_filter_engine.extract_data_for_computation_type("mean", bundle, subject_ids, workload_args, project_id=project_id, datasource_group_id=datasource_group_id)

    if data_column_id not in df.columns:
        raise ValueError(f"Column '{data_column_id}' not found in the data.")
    dtype = df[data_column_id].dtype
    if not (np.issubdtype(dtype, np.number) or dtype == object):
        raise ValueError(
            f"Column '{data_column_id}' must be numeric or object, got {dtype}."
        )
    if dtype == object:
        data = pd.to_numeric(df[data_column_id], errors="coerce").dropna().values
    else:
        data = df[data_column_id].dropna().values

    count = len(data)
    if count == 0:
        return {"sum": 0, "count": 0}
    if global_max is not None and global_min is not None and global_count is not None:
        if global_max < global_min:
            raise ValueError("global_max must be larger than global_min")
        range_val = global_max - global_min
        data_scaled = 2 * (data - global_min) / range_val - 1   # Normalizes each data point to [-1, 1]
        sum_val = np.sum(data_scaled)
    else:
        sum_val = np.sum(data)
    return {"sum": sum_val, "count": count}


def local_post_mean(total_sum, total_count, global_min=None, global_max=None, global_count=None):
    """
        Calculates mean result using the results of local_pre_mean().
    """
    mean = (total_sum / total_count)
    if global_max is not None and global_min is not None and global_count is not None:
        if global_max < global_min:
            raise ValueError("global_max must be larger than global_min")
        range_val = global_max - global_min
        mean = (mean + 1) * range_val / 2 + global_min
    return mean


def local_pre_stdev(
    data_column_id,
    stat_data_path,
    global_min=None,
    global_max=None,
    filters=None,
):
    """
        Returns sum value, sum of squares value, and count within the specified column.

        Uses FHIR + filter_engine to build the data column.

        If range_val and global_min are provided, normalizes data points to [-1,1].
        If neither of those are provided, it returns un-scaled reference sum,
        sum of squares, and count.

        Ignores NaN/null values and non-numeric data.
    """
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

    # Apply FHIR filters -> subject IDs
    subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)

    workload_args = {
        "computation_type": "stdev",
        "data_column_id": data_column_id,
    }
    df = active_filter_engine.extract_data_for_computation_type("stdev", bundle, subject_ids, workload_args, project_id=project_id, datasource_group_id=datasource_group_id)

    if data_column_id not in df.columns:
        raise ValueError(f"Column '{data_column_id}' not found in the data.")
    dtype = df[data_column_id].dtype
    if not (np.issubdtype(dtype, np.number) or dtype == object):
        raise ValueError(
            f"Column '{data_column_id}' must be numeric or object, got {dtype}."
        )
    if dtype == object:
        data = pd.to_numeric(df[data_column_id], errors="coerce").dropna().values
    else:
        data = df[data_column_id].dropna().values

    count = len(data)
    if count == 0:
        return {"sum_sq": 0, "sum": 0, "count": 0}
    if global_max is not None and global_min is not None:
        if global_max < global_min:
            raise ValueError("global_max must be larger than global_min")
        range_val = global_max - global_min
        data_scaled = 2 * (data - global_min) / range_val - 1  # Normalizes each data point to [-1, 1]
        sum_val = np.sum(data_scaled)
        sum_sq_val = np.sum(data_scaled ** 2)
    else:
        sum_val = np.sum(data)
        sum_sq_val = np.sum(data ** 2)
    return {"sum_sq": sum_sq_val, "sum": sum_val, "count": count}


# CKKS round-off can push a near-zero squared stdev slightly below zero.
# Values inside ``[-_NEG_SQ_STDEV_TOL, 0]`` are treated as exactly zero; anything
# more negative is a real bug and still raises.
_NEG_SQ_STDEV_TOL = 1e-8


def local_post_stdev(numerator, denominator, global_min=None, global_max=None):
    if denominator < 1e-10:
        raise ValueError(f"Denominator {denominator} is <= 0, cannot compute stdev.")
    sq_stdev = numerator / denominator
    if sq_stdev < -_NEG_SQ_STDEV_TOL:
        raise ValueError(f"Calculated squared stdev {sq_stdev} is negative.")
    sq_stdev = max(sq_stdev, 0.0)
    stdev = math.sqrt(sq_stdev)
    if global_max is not None and global_min is not None:
        range_val = global_max - global_min
        stdev = stdev * range_val / 2
    return stdev


def local_pre_chi2(
    stat_data_path: str,
    column_1: str,
    column_1_categories: list,
    column_2: str,
    column_2_categories: list,
    scaling_factor=None,
    filters=None,
):
    """
    Computes the Chi-squared statistics components for two categorical columns in a dataset.

    Now operates on a JSON FHIR bundle + filter_engine to build the [column_1, column_2] DataFrame.

    Args:
        stat_data_path (str): Path to JSON FHIR bundle.
        column_1 (str): The name of the first categorical column.
        column_1_categories (list): List of categories for the first categorical column.
        column_2 (str): The name of the second categorical column.
        column_2_categories (list): List of categories for the second categorical column.
        scaling_factor (float, optional): A factor to normalize the contingency table
                                          and marginal sums for numerical precision.
        filters: FHIR filter spec.

    Returns:
        dict: With encoded contingency table and marginals, suitable for DXO.

    Raises:
        ValueError: If specified columns are not found in the DataFrame or scaling_factor is zero.
        TypeError: If columns are not categorical and cannot be converted from 'object' dtype.
    """
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

    # Apply filters
    subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)

    workload_args = {
        "computation_type": "chi2",
        "category_column_1_id": column_1,
        "category_column_2_id": column_2,
    }
    df = active_filter_engine.extract_data_for_computation_type("chi2", bundle, subject_ids, workload_args, project_id=project_id, datasource_group_id=datasource_group_id)

    # Validate column existence and enforce categorical types
    if column_1 not in df.columns or column_2 not in df.columns:
        raise ValueError(
            f"Columns '{column_1}' or '{column_2}' not found in the data."
        )

    for col_name, categories_list in [
        (column_1, column_1_categories),
        (column_2, column_2_categories),
    ]:
        if not is_categorical_dtype(df[col_name].dtype):
            if df[col_name].dtype == "object":
                df[col_name] = df[col_name].astype("category")
            else:
                raise TypeError(
                    f"Column '{col_name}' must be categorical or convertible from object dtype. "
                    f"Current dtype is {df[col_name].dtype}."
                )

        # Check for categories in the data that are not in the specified list
        actual_data_categories = set(df[col_name].dropna().unique())
        specified_categories_set = set(categories_list)
        unexpected_categories = actual_data_categories - specified_categories_set
        if unexpected_categories:
            raise ValueError(
                f"Column '{col_name}' contains categories not specified in '{col_name}_categories': "
                f"{list(unexpected_categories)}. "
                f"Please ensure all categories present in the data are listed in the '{col_name}_categories' argument."
            )

    # Set categories for both columns
    df[column_1] = pd.Categorical(df[column_1], categories=column_1_categories)
    df[column_2] = pd.Categorical(df[column_2], categories=column_2_categories)
    # TODO: before normalization, all values are int in everything. use .astype(int) for efficiency?

    # 1. Build contingency table. Get the number of rows and columns from the contingency table.
    cont_table = pd.crosstab(df[column_1], df[column_2], dropna=False)
    N_rows = cont_table.shape[0]
    N_cols = cont_table.shape[1]

    # 2. Compute the marginal row sums and the marginal column sums. Output is a pd.Series type containing the sum for each row.
    row_marg = cont_table.sum(axis=1)
    col_marg = cont_table.sum(axis=0)

    if scaling_factor == 0:
        raise ValueError("Scaling factor cannot be zero.")

    # 4. Compute the sum over the contingency table.
    N_sum = cont_table.sum().sum()

    # Check if the scaling factor is large enough to normalize values to [0, 1]. If this is not the case, the security of the multiplicative mask is compromised.
    if scaling_factor is not None:
        if N_sum / scaling_factor > 1:
            raise ValueError(
                f"Scaling factor {scaling_factor} is not large enough to normalize pre-random_masking inputs to [0,1]."
            )

    # 5. Create zero positions for rows and columns. Bitmap representing 1 as an indicator of zero marginal sums at the corresponding index.
    zeros_row = (row_marg == 0).astype(int)
    zeros_col = (col_marg == 0).astype(int)

    # 6. Encoding:
    #    1) Prepare the marginal sums vectors and zeroes vectors for an outer product between them
    #    2) Convert all Pandas objects to lists (each of length = N_rows x N_cols) for DXO compatibility
    cont_table = cont_table.values.flatten().tolist()
    row_marg = np.repeat(row_marg, N_cols).tolist()
    col_marg = (col_marg.tolist()) * N_rows
    zeros_row = np.repeat(zeros_row, N_cols).tolist()
    zeros_col = (zeros_col.tolist()) * N_rows
    N_sum = [int(N_sum)] * (N_rows * N_cols)

    return {
        "cont_table": cont_table,
        "row_marg": row_marg,
        "col_marg": col_marg,
        "N_sum": N_sum,
        "zeros_row": zeros_row,
        "zeros_col": zeros_col,
    }


def local_post_chi2(numerator, denominator, dof):
    """
    Calculates chi2 and p_value using aggregated values.

    ``p_value`` is None when dof <= 0: one of the dimensions has fewer than two non-empty
    categories (e.g. a filter pinned that variable to a single value), so there is nothing to
    test. stats.chi2.sf returns NaN for a non-positive dof, which is also not valid JSON.
    """
    chi2 = sum([(n / d) for n, d in zip(numerator, denominator) if d != 0])
    if dof <= 0:
        return chi2, None
    p_value = stats.chi2.sf(chi2, dof)
    return chi2, p_value


def _time_to_index(event_time_val, current_times):
    """
    Helper to map event times to the defined time grid indices.
    Finds the index of the closest time point in the grid where event_time_val <= t.
    """
    if not current_times:
        return 0  # Or handle error appropriately
    for i, t in enumerate(current_times):
        if event_time_val <= t:
            return i
    return (
        len(current_times) - 1
    )  # If event_time is beyond the last time point, map to last index

# cohort/feature-matrix cache
_RECORDS_CACHE = OrderedDict()
_RECORDS_CACHE_LOCK = threading.Lock()
_RECORDS_CACHE_MAX = 4
_RECORDS_INFLIGHT = {}


def _resolve_biomarker_cancer_type(cancer_type, filters):
    """Prefer an explicit cancer_type, otherwise recover it from PATIENT_DATA filters.

    Biomarker workflows already carry the cancer filter in ``filters``. This
    fallback keeps wrapper call sites robust while explicit propagation remains
    the primary path.
    """
    explicit = str(cancer_type or "").strip()
    if explicit:
        return explicit

    candidates = filters
    if isinstance(candidates, dict):
        candidates = candidates.get("filters", candidates.get("conditions", []))
    if not isinstance(candidates, (list, tuple)):
        return None

    for item in candidates:
        if not isinstance(item, dict):
            continue
        if str(item.get("column_name") or "").strip() != "cancer_type":
            continue
        value = item.get("value")
        if isinstance(value, list):
            value = value[0] if value else None
        resolved = str(value or "").strip()
        if resolved:
            return resolved
    return None


def _records_cache_key(stat_data_path, cancer_type, biomarker_covariates, filters):
    src = os.path.abspath(stat_data_path) if _is_json_data_source(stat_data_path) else str(stat_data_path)
    filters_hash = hashlib.md5(json.dumps(filters, sort_keys=True, default=str).encode()).hexdigest()
    return (src, str(cancer_type), tuple(biomarker_covariates or ()), filters_hash)


def local_pre_get_biomarker_records(stat_data_path, cancer_type=None, biomarker_covariates=None, filters=None):
    cancer_type = _resolve_biomarker_cancer_type(cancer_type, filters)
    ck = _records_cache_key(stat_data_path, cancer_type, biomarker_covariates, filters)
    while True:
        with _RECORDS_CACHE_LOCK:
            if ck in _RECORDS_CACHE:
                _RECORDS_CACHE.move_to_end(ck)
                return _RECORDS_CACHE[ck]
            ev = _RECORDS_INFLIGHT.get(ck)
            if ev is None:
                ev = threading.Event()
                _RECORDS_INFLIGHT[ck] = ev
                break  # we own the build
        ev.wait()  # another caller is building this exact key; wait, then re-check

    try:
        bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
        project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

        subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)

        df = active_filter_engine.build_biomarker_subjects_dataframe(
            bundle,
            subject_ids,
            biomarker_covariates,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            cancer_type=cancer_type,
        ).astype(float)

        result = {'all_records': df.values.tolist(), 'record_len': len(df.columns), '_records_cache_key': ck}
        with _RECORDS_CACHE_LOCK:
            _RECORDS_CACHE[ck] = result
            _RECORDS_CACHE.move_to_end(ck)
            while len(_RECORDS_CACHE) > _RECORDS_CACHE_MAX:
                _RECORDS_CACHE.popitem(last=False)
        return result
    finally:
        # Release waiters (on success they read the cache; on failure one of them rebuilds).
        with _RECORDS_CACHE_LOCK:
            _RECORDS_INFLIGHT.pop(ck, None)
        ev.set()

def local_pre_kaplan_meier(
    stat_data_path,
    filters,
    group_col,
    time_col,
    censoring_col,
    group_categories,
    time_grid_min,
    time_grid_step,
    time_grid_max,
    is_biomarker_discovery=None,
    cancer_type=None,
    biomarker_covariates=None,
    coeffs=None,
    cutoff_value=None,
    risk_scores=None,
    risk_scores_scale_factor=None,
    model_key=None,
    from_cached_score=False,
    cached_scores=None,
):
    """
    Computes local Kaplan-Meier statistics (N, d, zeros_N, ones_N) for each group
    at specified time grid points.

    Now uses the FHIR-based filter_engine to:
      - Apply FHIR filters to get the cohort.
      - Extract [group_col, time_col, censoring_col] via computation_type="kaplan-meier".

    Args:
        stat_data_path (str): Path to JSON FHIR bundle.
        filters (list): A list of filter conditions to apply.
        group_col (str): Name of the group column.
        time_col (str): Name of the event time column.
        censoring_col (str): Name of the censoring column (True for event, False for censored).
        group_categories (list): List of all possible groups in group_col.
        time_grid_min (int): Minimum value for the time grid.
        time_grid_step (int): Step size for the time grid.
        time_grid_max (int): Maximum value for the time grid.
        model_key (str, optional): Biomarker model id from workload (e.g. cox_lasso, logistic_reg); used for epsilon when precomputed risk_scores are used.

    Returns:
        dict: A dictionary containing the time grid and local N, d, zeros_N, ones_N
              for each group.
    """
    cancer_type = _resolve_biomarker_cancer_type(cancer_type, filters)
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

    subject_ids = []
    if bundle:
        if isinstance(bundle, dict):
            print("[KM DEBUG] Bundle entries:", len(bundle.get("entry", [])))
        else:
            print("[KM DEBUG] Data source:", bundle)
        subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)
        print("[KM DEBUG] Subject IDs after filters:", len(subject_ids))

    if is_biomarker_discovery is not None and is_biomarker_discovery == True:
        if from_cached_score:
            # Open-access reuse path: group on the per-patient RAW scores (score = coeff.x)
            # already computed and cached by a preceding ``biomarker_score_computation``
            # workflow, instead of re-deriving them from the on-disk model here. This is the
            # clear-text analogue of the encrypted ``risk_scores``/``w_biomarker_risk_scores``
            # branch below, but far simpler: there is no CKKS noise, so no rsf/scaling and no
            # noise-tuned epsilon -- we replicate ``biomarker_subjects_to_km_dataframe``'s exact
            # grouping (``diff = score - cutoff``; dead-band ``epsilon = 1e-15``; ``> 0`` -> high)
            # so the reused groups are identical to the recompute path bit-for-bit.
            #
            # ``cached_scores`` are the RAW scores (not ``score - cutoff``), aligned positionally
            # to this cohort's kaplan-meier-time-censoring extraction (the same order the
            # producer scored). The caller (stat_analytics) guarantees the cache is present and
            # belongs to this model_key; a missing cache is a wiring bug and must NOT silently
            # fall back to recompute (that would hide a broken reuse chain), so we fail loud.
            if cached_scores is None:
                raise ValueError(
                    "local_pre_kaplan_meier: from_cached_score set but no cached_scores provided"
                )
            print(f"[KM DEBUG] biomarker discovery: REUSING {len(cached_scores)} cached clear scores (no recompute)")
            epsilon = 1e-15  # match biomarker_subjects_to_km_dataframe's dead-band exactly
            cutoff = _coerce_float_scalar(cutoff_value, "biomarker model cutoff")
            workload_args = {
                "computation_type": "kaplan-meier-time-censoring",
                "time_column_id": time_col,
                "censoring_column_id": censoring_col,
                "cancer_type": cancer_type,
            }
            df = active_filter_engine.extract_data_for_computation_type(
                "kaplan-meier-time-censoring", bundle, subject_ids, workload_args,
                project_id=project_id, datasource_group_id=datasource_group_id,
            )
            len_df = len(df)
            risk_series = pd.Series(cached_scores)
            sliced_raw = risk_series.iloc[:len_df]

            def extract_float(x):
                while isinstance(x, (list, np.ndarray)):
                    x = x[0]
                return float(x)

            diff_arr = [extract_float(i) - cutoff for i in sliced_raw]
            cleaned_diff = np.where(np.abs(diff_arr) <= epsilon, 0.0, diff_arr)
            df[group_col] = np.where(np.array(cleaned_diff) > 0.0, "high_score", "low_score")
        elif risk_scores is None: # Risk scores are generated online (access to model required)
            epsilon = 1e-15  # Threshold for treating very small values as zero
            df = active_filter_engine.build_biomarker_km_dataframe(
                bundle=bundle,
                subject_ids=subject_ids,
                coeffs=coeffs,
                cutoff_value=cutoff_value,
                target_biomarker_covariates=biomarker_covariates,
                group_col=group_col,
                time_col=time_col,
                censoring_col=censoring_col,
                epsilon=epsilon,
                project_id=project_id,
                datasource_group_id=datasource_group_id,
                cancer_type=cancer_type,
            )
        else:   # Pre-computed Risk scores are provided.
            if risk_scores_scale_factor is not None and risk_scores_scale_factor == 1:
                epsilon = 1e-6
            else:
                if model_key == "cox_lasso":
                    epsilon = 1e-15
                elif model_key == "logistic_reg":
                    epsilon = 1e-5  # try e-5? for Colorectal.
                else:
                    raise ValueError(f"Invalid model key: {model_key}")
            eff_epsilon = epsilon * abs(float(risk_scores_scale_factor)) if risk_scores_scale_factor is not None else epsilon
            workload_args = {
                    "computation_type": "kaplan-meier-time-censoring",
                    "time_column_id": time_col,
                    "censoring_column_id": censoring_col,
                    "cancer_type": cancer_type,
                }
            df = active_filter_engine.extract_data_for_computation_type("kaplan-meier-time-censoring", bundle, subject_ids, workload_args, project_id=project_id, datasource_group_id=datasource_group_id)

            len_df = len(df)
            risk_series = pd.Series(risk_scores)
            sliced_raw = risk_series.iloc[:len_df]

            def extract_float(x):
                while isinstance(x, (list, np.ndarray)):
                    x = x[0]
                return float(x)

            diff_arr = [extract_float(i) for i in sliced_raw]
            cleaned_diff = np.where(np.abs(diff_arr) <= eff_epsilon, 0.0, diff_arr)
            df[group_col] = np.where(np.array(cleaned_diff) > 0.0, "high_score", "low_score")
    else:
        workload_args = {
            "computation_type": "kaplan-meier",
            "group_column_id": group_col,
            "time_column_id": time_col,
            "censoring_column_id": censoring_col,
        }
        df = active_filter_engine.extract_data_for_computation_type(
            "kaplan-meier", bundle, subject_ids, workload_args, project_id=project_id,
            datasource_group_id=datasource_group_id
        )

    print("[KM DEBUG] Raw KM DataFrame shape:", df.shape)
    print("[KM DEBUG] Raw KM DataFrame columns:", list(df.columns))

    df = df[[group_col, time_col, censoring_col]].dropna()
    print("[KM DEBUG] KM DataFrame after dropna shape:", df.shape)

    if df.empty:
        print("[KM DEBUG] KM DataFrame is empty after dropna. No groups to process.")
        return {}

    print("[KM DEBUG] dtypes after column selection:")
    for col_name, dtype in df.dtypes.items():
        print(f"    {col_name}: {dtype}")

    try:
        t_min = float(df[time_col].min())
        t_max = float(df[time_col].max())
        t_nunique = int(df[time_col].nunique())
        print(
            f"[KM DEBUG] Time column '{time_col}' min={t_min}, max={t_max}, nunique={t_nunique}"
        )
    except Exception as e:
        print(f"[KM DEBUG] Error computing time stats for '{time_col}': {e}")

    print(
        f"[KM DEBUG] Group column '{group_col}' sample:",
        df[group_col].head(10).tolist(),
    )
    print(
        f"[KM DEBUG] Censoring column '{censoring_col}' value counts (raw):",
        df[censoring_col].value_counts(dropna=False).to_dict(),
    )

    if not pd.api.types.is_bool_dtype(df[censoring_col]):
        df[censoring_col] = df[censoring_col].astype(bool)

    print(
        f"[KM DEBUG] Censoring column '{censoring_col}' value counts (bool):",
        df[censoring_col].value_counts(dropna=False).to_dict(),
    )

    print("[KM DEBUG] Declared group_categories:", group_categories)

    unique_groups = set(df[group_col].unique())
    unexpected_groups = unique_groups - set(group_categories)
    print("[KM DEBUG] Observed groups in data:", unique_groups)
    if unexpected_groups:
        print("[KM DEBUG] Unexpected groups encountered:", unexpected_groups)
        raise ValueError(
            f"Unexpected groups found in {group_col}: {unexpected_groups}"
        )

    M_steps = math.ceil((time_grid_max - time_grid_min) / time_grid_step)
    time_grid_points = [
        time_grid_min + ind * time_grid_step for ind in range(int(M_steps))
    ]
    if time_grid_points and time_grid_points[-1] < time_grid_max:
        time_grid_points.append(time_grid_max)
    time_grid_points = sorted(list(set(time_grid_points)))

    print(
        "[KM DEBUG] Time grid points count:",
        len(time_grid_points),
        "sample:",
        time_grid_points[:10],
    )

    groups_data = {}

    n_beyond_grid = int((df[time_col] > time_grid_points[-1]).sum())
    if n_beyond_grid:
        # Deliberate tail aggregation: times beyond the schema's grid max are
        # clamped into the last cell. Late-tail cells would otherwise hold very
        # few patients, and thin per-cell tallies are a disclosure risk; pooling
        # the tail keeps the last cell well occupied. The reference computation
        # must apply the same clamp for the log-rank to match.
        logging.getLogger(__name__).info(
            "Kaplan-Meier: %d patient time(s) beyond grid max %s aggregated "
            "into the last grid cell (deliberate tail clamping).",
            n_beyond_grid,
            time_grid_points[-1],
        )
    mapped_event_times = df[time_col].apply(
        lambda x: _time_to_index(x, time_grid_points)
    )
    censoring_values = df[censoring_col]

    for group_name in sorted(df[group_col].unique()):
        group_indices = df[df[group_col] == group_name].index
        print(
            f"[KM DEBUG] Processing group '{group_name}' with {len(group_indices)} rows"
        )

        N_group = np.zeros(len(time_grid_points))
        d_group = np.zeros(len(time_grid_points))

        for i in range(len(time_grid_points)):
            N_group[i] = sum(
                1 for idx in group_indices if mapped_event_times[idx] >= i
            )

            d_group[i] = sum(
                1
                for idx in group_indices
                if mapped_event_times[idx] == i and censoring_values[idx]
            )

        print(
            f"[KM DEBUG] Group '{group_name}': total_at_risk={N_group.sum()}, total_events={d_group.sum()}"
        )

        zeros_N_group = (N_group == 0).astype(int).tolist()
        ones_N_group = (N_group == 1).astype(int).tolist()

        groups_data[str(group_name)] = {
            "N": N_group.tolist(),
            "d": d_group.tolist(),
            "zeros_N": zeros_N_group,
            "ones_N": ones_N_group,
        }

    return groups_data


def local_post_kaplan_meier(
    time_grid_min,
    time_grid_max,
    time_grid_step,
    aggregated_N_groups,
    aggregated_d_groups,
    numerator_A_val=None,
    denominator_A_val=None,
    numerator_var_A_val=None,
    denominator_var_A_val=None,
    masked=False
):
    """
        Post-process calculation of kaplan meier and logrank test.
        If masked = False, we operate over N or d values for each group.
        If masked = True, we operate over 'numerator' and 'denominator' of each group.
        In this case, argument 'aggregated_N_groups'='numerator' and
        argument 'aggregated_d_groups'='denominator'.
    """
    M_steps = math.ceil((time_grid_max - time_grid_min) / time_grid_step)
    time_grid = [time_grid_min + ind * time_grid_step for ind in range(int(M_steps))]
    if time_grid and time_grid[-1] < time_grid_max:
        time_grid.append(time_grid_max)
    time_grid = sorted(list(set(time_grid)))

    zero_threshold_d = 1e-5

    S_output = {}
    for group_name, N_values in aggregated_N_groups.items():
        d_values = aggregated_d_groups[group_name]
        survival_func = []
        current_survival = 1.0
        for i in range(len(time_grid)):
            n = N_values[i]
            d = d_values[i]
            if masked:
                if abs(d) >= zero_threshold_d:
                    current_survival *= n / d
            else:
                if abs(n) >= zero_threshold_d:  # Reference also checks for zero_threshold_d here.
                    current_survival *= (n - d) / n
            if current_survival < zero_threshold_d:
                current_survival = 0.0
            survival_func.append(current_survival)
        S_output[group_name] = survival_func

    if numerator_A_val is not None: # Log-rank test results are present
        oe_terms = [] # Store (O - E) terms
        v_terms = []  # Store Var(O - E) terms

        for i in range(len(time_grid)): # Don't need zero indicator checks here since we use zero markers in preprocess to set large number if den = 0.
            if denominator_A_val[i] != 0:
                oe_terms.append(numerator_A_val[i] / denominator_A_val[i])
            if denominator_var_A_val[i] != 0:
                v_terms.append(numerator_var_A_val[i] / denominator_var_A_val[i])

        # Calculation for log-rank numerator: sum (O-E) then square
        sum_oe = sum(oe_terms)
        e_A = sum_oe ** 2

        # Sum of variances
        v_A = sum(v_terms)

        chi2_stat = (e_A / v_A) if v_A != 0 else 0.0
        p_value = stats.chi2.sf(chi2_stat, df=1)  # Log-rank test has 1 degree of freedom for 2 groups

        return S_output, time_grid, chi2_stat, p_value
    else:
        return S_output, time_grid

def logrank_terms_from_aggregated_N_d(aggregated_N_groups, aggregated_d_groups):
    '''
    Compute log-rank test terms (numerator_A, denominator_A, numerator_var_A, denominator_var_A)
    from aggregated N and d per group. Used when CI_type is set and we only have N and d (no indicators).
    Returns a tuple (numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val)
    when there are exactly 2 groups; otherwise returns None.
    '''
    group_names = sorted(aggregated_N_groups.keys())
    if len(group_names) != 2:
        return None
    group_A_name, group_B_name = group_names[0], group_names[1]
    co_N_A = aggregated_N_groups[group_A_name]
    co_d_A = aggregated_d_groups[group_A_name]
    co_N_B = aggregated_N_groups[group_B_name]
    co_d_B = aggregated_d_groups[group_B_name]
    n_bins = len(co_N_A)
    co_N = [a + b for a, b in zip(co_N_A, co_N_B)]
    co_d = [a + b for a, b in zip(co_d_A, co_d_B)]
    numerator_A_val = [(co_N[i] * co_d_A[i]) - (co_d[i] * co_N_A[i]) for i in range(n_bins)]
    denominator_A_val = co_N
    numerator_var_A_val = [co_N_A[i] * (co_N[i] - co_N_A[i]) * co_d[i] * (co_N[i] - co_d[i]) for i in range(n_bins)]
    denominator_var_A_val = [co_N[i] * co_N[i] * (co_N[i] - 1) for i in range(n_bins)]
    return (numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val)

def kaplan_meier_confidence_interval(S_output, aggregated_N_groups, aggregated_d_groups, time_grid, ci_type, alpha=0.05):
    '''
    Compute confidence intervals for Kaplan-Meier survival estimates.
    V_t = sum_{t_j <= t} d_j / (n_j * (n_j - d_j)).
    log-log: SE(theta_t) = (1/ln(S(t))) * sqrt(V_t), LB = S(t)^exp(-Z*SE), UB = S(t)^exp(Z*SE).
    linear:  SE(t) = S(t) * sqrt(V_t), LB = S(t) - Z*SE(t), UB = S(t) + Z*SE(t).
    Z = Z_{1-alpha/2} (e.g. 1.96 for alpha=0.05).
    '''
    if ci_type not in ["log-log", "linear"]:
        return {}
    zero_threshold = 1e-5
    Z = stats.norm.ppf(1 - alpha / 2)
    ci_result = {}
    for group_name in S_output:
        N_vals = aggregated_N_groups[group_name]
        d_vals = aggregated_d_groups[group_name]
        S_vals = S_output[group_name]
        n_bins = len(time_grid)
        V_t = []
        cum = 0.0
        for i in range(n_bins):
            n_i = N_vals[i]
            d_i = d_vals[i]
            if n_i < zero_threshold or (n_i - d_i) < zero_threshold:
                pass
            else:
                cum += d_i / (n_i * (n_i - d_i))
            V_t.append(cum)
        lb = [1.0] * n_bins
        ub = [1.0] * n_bins
        for i in range(n_bins):
            S_t = S_vals[i]
            V_i = V_t[i]
            if V_i < zero_threshold or S_t < zero_threshold:
                lb[i] = S_t
                ub[i] = S_t
                continue
            if ci_type == "log-log":
                ln_S = math.log(S_t)
                if ln_S >= 0 or abs(ln_S) < zero_threshold:
                    lb[i] = S_t
                    ub[i] = S_t
                    continue
                se_theta = (1.0 / ln_S) * math.sqrt(V_i)
                lb[i] = (S_t ** math.exp(-Z * se_theta)) if S_t >= zero_threshold else 0.0
                ub[i] = (S_t ** math.exp(Z * se_theta)) if S_t >= zero_threshold else 0.0
            else:  # linear
                se_t = S_t * math.sqrt(V_i)
                lb[i] = float(max(0.0, S_t - Z * se_t))
                ub[i] = float(min(1.0, S_t + Z * se_t))
        ci_result[group_name] = {"lower": lb, "upper": ub}
    return ci_result


def local_pre_t_test(
    stat_data_path: str,
    data_column_id: str,
    column_1: str,
    column_1_categories: list,
    global_min: int = None,
    global_max: int = None,
    global_count: int = None,
    filters=None,
):
    """
    Local pre-computation for t-test.

    Now operates on JSON FHIR bundle and uses filter_engine to build a DataFrame with:
      - numeric data_column_id
      - categorical column_1

    Returns per-category sum, sum_sq, and count.
    """
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)

    # Apply filters
    subject_ids = _apply_filters_with_optional_project_id(active_filter_engine, filters, bundle, project_id, datasource_group_id)

    workload_args = {
        "computation_type": "t-test",
        "data_column_id": data_column_id,
        "category_column_1_id": column_1,
    }
    df = active_filter_engine.extract_data_for_computation_type("t-test", bundle, subject_ids, workload_args, project_id=project_id, datasource_group_id=datasource_group_id)

    if data_column_id not in df.columns or column_1 not in df.columns:
        raise ValueError(
            f"Column '{data_column_id}' or '{column_1}' not found in the data."
        )

    df[data_column_id] = pd.to_numeric(df[data_column_id], errors="coerce")
    if not is_categorical_dtype(df[column_1].dtype):
        df[column_1] = df[column_1].astype("category")
    df = df.dropna(subset=[data_column_id, column_1]).copy()

    data_col = df[data_column_id]
    cat_col = df[column_1]
    column_1_categories.sort()
    return_val = {}
    for cat in column_1_categories:
        x = data_col.iloc[np.where(cat_col == cat)[0]]
        n = x.shape[0]
        if global_max is not None and global_min is not None and global_count is not None:
            if global_max < global_min:
                raise ValueError("global_max must be larger than global_min")
            range_val = global_max - global_min
            data_scaled = 2 * (x - global_min) / range_val - 1   # Normalizes each data point to [-1, 1]
            # Version 1
            # sum_val = np.sum(data_scaled)
            # sum_sq_val = np.sum(data_scaled**2)

            # Version 2 (more robust)
            sum_val = np.sum(data_scaled)/global_count
            sum_sq_val = np.sum(data_scaled**2)/global_count
            n = n/global_count
        else:
            sum_val = np.sum(x)
            sum_sq_val = np.sum(x ** 2)
        return_val[cat] = {'sum_sq': sum_sq_val, 'sum': sum_val, 'count': n}

    return return_val


def local_post_t_test(num_d, num_den_d, den_den_d, num_t, den_t, global_count = None):
    if abs(num_den_d[0]) < 1e-7 or abs(num_den_d[1]) < 1e-7:
        raise ValueError(f"num_den_d = 0. Make sure that total number of samples in each category is > 1.")
    if den_t < 1e-7:
        raise ValueError(f"den_t = 0. Make sure at least one of the samples has non-zero variance (numbers are not identical).")
    if num_d < 0:
        raise ValueError(f"num_d < 0. This should never happen.")

    if global_count is not None:
        # # Version 1
        # # g_n0 and g_n1 are the global counts for each category. Get it from global_schema
        # t_num = num_t * (g_n0*g_n1)**2
        # t_den = den_t * (g_n0*g_n1)
        # d_num = num_d * (g_n0*g_n1)**2
        # d_num_den = [num_den_d[0] * g_n0 * g_n1**2, num_den_d[1] * g_n0**2 * g_n1]
        # d_den_den = [den_den_d[0]/(g_n0 * g_n1**2), den_den_d[1]/(g_n0**2 * g_n1)]
        # t_score = math.sqrt(t_num/t_den)
        # dof = d_num**2/((d_num_den[0]**2/d_den_den[0]) + (d_num_den[1]**2/d_den_den[1]))

        # Version 2 (more robust)
        d_num = num_d * (global_count)**5
        d_num_den = [num_den_d[0] * global_count**5, num_den_d[1] * global_count**5]
        d_den_den = [den_den_d[0] * global_count, den_den_d[1] * global_count]
        t_score = math.sqrt(num_t*global_count/den_t)
        dof = d_num**2/((d_num_den[0]**2/d_den_den[0]) + (d_num_den[1]**2/d_den_den[1]))
    else:
        t_score = math.sqrt(num_t/den_t)
        dof = num_d**2/((num_den_d[0]**2/den_den_d[0]) + (num_den_d[1]**2/den_den_d[1]))
    p_value = 2 * stats.t.sf(np.abs(t_score), dof)
    return t_score, dof, p_value


def local_pre_biomarker_score_computation(stat_data_path, filters, cancer_type=None, biomarker_covariates=None, coeffs=None):
    """Apply the open-access biomarker model to local covariates and return per-patient scores.

    Open-access analogue of ``biomarker_enc_risk_group_computation`` *without* the
    high/low thresholding step: each client computes ``score_i = sum_j coef_j * x_ij``
    for its own patients and returns the resulting list. The caller is expected to
    cache this list locally for the next workflow (no scores leave the client).

    Returns ``list[float]`` of per-patient scores, or ``[]`` if the cohort is empty.
    """
    import pickle as _pickle

    cancer_type = _resolve_biomarker_cancer_type(cancer_type, filters)
    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)
    subject_ids = _apply_filters_with_optional_project_id(
        active_filter_engine,
        filters,
        bundle,
        project_id,
        datasource_group_id,
    )

    if coeffs is None or biomarker_covariates is None:
        raise ValueError(
            "local_pre_biomarker_score_computation: coeffs and biomarker_covariates are required"
        )
    coeffs_df = _pickle.loads(coeffs) if isinstance(coeffs, (bytes, bytearray)) else coeffs
    coeffs_df = _normalize_weights_dataframe_columns(
        coeffs_df, source_label="coefficients dataframe"
    )

    df = active_filter_engine.build_biomarker_subjects_dataframe(
        bundle,
        subject_ids,
        biomarker_covariates,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        cancer_type=cancer_type,
    )
    df = df.astype(float)
    if df.shape[0] == 0:
        return []

    coef_map = {row["covariate"]: float(row["coef"]) for _, row in coeffs_df.iterrows()}
    aligned_coefs, _, _ = filter_engine_config.align_model_coefficients(
        coef_map, biomarker_covariates, context_label="biomarker_score_computation"
    )
    coef_vec = np.array(aligned_coefs, dtype=float)
    score = df[biomarker_covariates].to_numpy(dtype=float) @ coef_vec
    return [float(s) for s in score]


# Upper bound on plausible |β₁| / SE(β₁) for a 2-parameter logit on z-normalized
# covariates. Real converged fits sit comfortably under 10; perfect-separation /
# non-converged fits land at 10⁴+.
_LR_FIT_MAGNITUDE_LIMIT = 100.0


def censor_aware_er_labels(time_arr, event_arr, horizon_threshold):
    """Censor-aware early-responder labels over aligned time/event arrays.

    ER = 1 when time > threshold; ER = 0 when the event occurred at or before
    it; a patient censored at/before the threshold cannot be labeled and is
    excluded. Returns ``(labeled_mask, y)``: a boolean mask over the input rows
    and the 0/1 labels for the masked positions. Shared by the LR fit and the
    mean-stdev share so both operate on the identical row set.
    """
    t = np.asarray(time_arr, dtype=float)
    e = np.asarray(event_arr).astype(bool)
    is_er = t > float(horizon_threshold)
    labeled_mask = is_er | e  # non-ER requires an observed event at/<= threshold
    return labeled_mask, is_er[labeled_mask].astype(int)


def extract_time_event_arrays(stat_data_path, filters, time_col, censoring_col, cancer_type=None):
    """Extract the (time, event) arrays for the filtered cohort, in cohort order.

    This is the same "kaplan-meier-time-censoring" extraction every biomarker
    consumer uses, so the returned rows align positionally with the cached
    per-patient scores produced under the same filters.
    """
    cancer_type = _resolve_biomarker_cancer_type(cancer_type, filters)
    cache_key = (
        os.path.abspath(stat_data_path) if _is_json_data_source(stat_data_path) else str(stat_data_path),
        hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
        str(time_col),
        str(censoring_col),
        str(cancer_type or ""),
    )
    with _TIME_EVENT_CACHE_LOCK:
        cached = _TIME_EVENT_CACHE.get(cache_key)
        if cached is not None:
            _TIME_EVENT_CACHE.move_to_end(cache_key)
            # Copies, so a caller cannot mutate the cached arrays and the caller-side
            # cohort-alignment check keeps seeing exactly what a fresh extraction gives.
            return cached[0].copy(), cached[1].copy()

    bundle, active_filter_engine = _load_stat_data_source(stat_data_path)
    project_id, datasource_group_id = _get_fhir_context_for_stat_data_path(stat_data_path)
    subject_ids = _apply_filters_with_optional_project_id(
        active_filter_engine,
        filters,
        bundle,
        project_id,
        datasource_group_id,
    )
    time_df = active_filter_engine.extract_data_for_computation_type(
        "kaplan-meier-time-censoring",
        bundle,
        subject_ids,
        {
            "computation_type": "kaplan-meier-time-censoring",
            "time_column_id": time_col,
            "censoring_column_id": censoring_col,
            "cancer_type": cancer_type,
        },
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    time_arr = np.asarray(time_df[time_col].values, dtype=float)
    event_arr = np.asarray(time_df[censoring_col].values).astype(bool)

    with _TIME_EVENT_CACHE_LOCK:
        _TIME_EVENT_CACHE[cache_key] = (time_arr, event_arr)
        _TIME_EVENT_CACHE.move_to_end(cache_key)
        while len(_TIME_EVENT_CACHE) > _TIME_EVENT_CACHE_MAX:
            _TIME_EVENT_CACHE.popitem(last=False)

    return time_arr.copy(), event_arr.copy()


def _lr_fit_fail(reason, n=0, n_er=0, n_non_er=0):
    return {
        "status": "FAIL",
        "fail_reason": str(reason),
        "n": int(n),
        "n_ER": int(n_er),
        "n_nonER": int(n_non_er),
    }


def local_pre_logistic_regression_with_global_zscore(stat_data_path, filters, time_col, censoring_col, horizon_threshold, risk_scores, score_mean, score_std, model_key=None, cancer_type=None):
    """Fit a 2-parameter logistic regression locally using a *global* z-score.

    Uses pre-computed per-patient ``risk_scores`` (cached from the preceding
    score-computation workflow) and the global ``(score_mean, score_std)``
    recovered from the federated ``mean-stdev`` workflow that ran over those
    same scores. Builds the censor-aware ER label from the time/event columns
    (``censor_aware_er_labels``), applies the *global* z-score
    ``z = (score - score_mean) / score_std`` to the labeled rows, and fits
    ``sm.Logit(y, [1, z])``.

    ``se_beta1`` (``fit.bse[1]``) is the per-client input to the inverse-variance
    meta-analysis (weights ``wₖ = 1 / SEₖ²``). Using the *global* ``(μ, σ)`` makes
    each client's design matrix comparable across clients, so the downstream
    pooling of ``β₁`` is meaningful.

    ``model_key == "cox_lasso"`` negates the returned ``β₁`` so its sign matches
    the "higher score → higher event odds" convention (Cox scores are oriented the
    opposite way); ``logistic_reg`` and unspecified models are left as fit.

    Returns ``{"status": "OK", "beta0", "beta1", "n", "n_ER", "n_nonER",
    "se_beta1"}`` on success. Degenerate cohorts/fits return
    ``{"status": "FAIL", "fail_reason", "n", "n_ER", "n_nonER"}`` using the
    reference's per-site gate names (n >= 5, n_ER >= 2, n_nonER >= 2,
    non-constant z).
    """
    import statsmodels.api as sm

    cancer_type = _resolve_biomarker_cancer_type(cancer_type, filters)
    if score_std is None or float(score_std) <= 0.0:
        return _lr_fit_fail("invalid_score_std")
    if horizon_threshold is None or not np.isfinite(float(horizon_threshold)):
        return _lr_fit_fail("invalid_ER_threshold")

    time_arr, event_arr = extract_time_event_arrays(
        stat_data_path, filters, time_col, censoring_col, cancer_type=cancer_type
    )
    score = np.asarray(risk_scores, dtype=float)

    if score.shape[0] != time_arr.shape[0]:
        return _lr_fit_fail("score_time_length_mismatch")

    labeled_mask, y = censor_aware_er_labels(time_arr, event_arr, horizon_threshold)
    score_labeled = score[labeled_mask]

    n = int(y.shape[0])
    n_er = int(y.sum())
    n_non_er = n - n_er

    # Per-site fit gates, matching the reference exactly (handoff section E).
    if n < 5:
        return _lr_fit_fail("too_few_labeled_samples", n, n_er, n_non_er)
    if n_er < 2:
        return _lr_fit_fail("too_few_ER_cases", n, n_er, n_non_er)
    if n_non_er < 2:
        return _lr_fit_fail("too_few_nonER_cases", n, n_er, n_non_er)

    score_zscored = (score_labeled - float(score_mean)) / float(score_std)
    if np.unique(score_zscored).shape[0] <= 1:
        return _lr_fit_fail("constant_score", n, n_er, n_non_er)

    X = sm.add_constant(score_zscored, has_constant="add")
    try:
        fit = sm.Logit(y, X).fit(disp=0)
    except Exception as error:
        return _lr_fit_fail(f"logit_failed: {error}", n, n_er, n_non_er)

    # statsmodels emits a ConvergenceWarning (rather than raising) when MLE fails
    # to converge, reporting ``mle_retvals['converged'] == False`` with whatever
    # runaway params the optimizer last produced. Perfect-separation cases
    # sometimes claim convergence but still produce infeasible parameters. Either way
    # the per-client share would carry a tiny ``wₖ = 1/SEₖ²`` into meta-analysis
    # and silently shrink the effective cohort, so signal degeneracy instead.
    mle_retvals = getattr(fit, "mle_retvals", None) or {}
    if not mle_retvals.get("converged", True):
        return _lr_fit_fail("logit_failed: did not converge", n, n_er, n_non_er)

    beta0 = float(fit.params[0])
    beta1 = float(fit.params[1])
    se_beta1 = float(fit.bse[1])

    if abs(beta1) > _LR_FIT_MAGNITUDE_LIMIT or se_beta1 > _LR_FIT_MAGNITUDE_LIMIT:
        return _lr_fit_fail("logit_failed: runaway parameters", n, n_er, n_non_er)

    # Cox-LASSO scores are oriented opposite to logistic_reg (higher = worse
    # prognosis), so flip β₁ to the shared "higher score → higher event odds"
    # convention. Equivalent to fitting on −z, so β₀/se/n are unaffected.
    if model_key == "cox_lasso":
        beta1 = -beta1

    return {
        "status": "OK",
        "beta0": beta0,
        "beta1": beta1,
        "n": n,
        "n_ER": n_er,
        "n_nonER": n_non_er,
        "se_beta1": se_beta1,
    }


_META_ANALYSIS_DENOM_TOL = 1e-10  # matches the per-client SE threshold in stat_analytics


def _attach_meta_analysis_warning(result: dict, warning: WarnException) -> dict:
    """Attach a UI-visible warning payload to a meta-analysis FAIL result.

    Deliberately does not touch ``status`` (which stays ``FAIL``, since the pooled values are
    genuinely undefined): only a structured payload is added, because an undefined aggregate
    with every numeric field ``None`` otherwise renders as an empty panel with no explanation.
    Unlike the per-client degenerate-fit warning, these conditions are properties of the
    aggregate, so every party's copy of the result carries the same reason.
    """
    payload = warning.to_payload()
    result["warning"] = payload
    result["warnings"] = [payload]
    return result


def local_post_meta_analysis(total_sum, total_count, usable_sites=None):
    """Recover the fixed-effects inverse-variance meta-analysis outputs from the
    aggregated ``(Σ wₖ·β₁,ₖ, Σ wₖ)`` where ``wₖ = 1/SEₖ²``.

      β̄₁      = A / B
      SE(β̄₁)  = 1 / √B
      z       = β̄₁ / SE(β̄₁)
      p_value = 2 · (1 − Φ(|z|))   (two-sided)
      95% CI  = β̄₁ ± 1.96 · SE(β̄₁)

    ``usable_sites`` is the aggregated count of sites whose fit passed the
    per-site gates (each usable site contributes 1; rounded because the count
    arrives with CKKS noise on the encrypted path). The reference combines only
    when at least two sites are usable — one site is not a cross-site
    meta-analysis. ``None`` (legacy share without the count) skips that gate.

    Returns ``{"status": "FAIL", ...}`` (numeric fields ``None``) if fewer than
    two sites are usable, or if ``B`` is effectively zero — i.e. every client
    either had a degenerate fit or sent a zero share because ``SEₖ < 1e-10``.
    """
    B = float(total_count)
    A = float(total_sum)
    n_sites = int(round(float(usable_sites))) if usable_sites is not None else None
    if n_sites is not None and n_sites < 2:
        logging.getLogger(__name__).warning(
            "local_post_meta_analysis: only %d usable site(s); a fixed-effects "
            "combine needs at least two. Reporting FAIL.",
            n_sites,
        )
        return _attach_meta_analysis_warning(
            {
                "status": "FAIL",
                "msg": (
                    f"Only {n_sites} site(s) passed the per-site fit gates; "
                    "a cross-site meta-analysis needs at least two usable sites."
                ),
                "fail_reason": "fewer_than_two_usable_sites",
                "n_sites_combined": n_sites,
                "meta_beta1": None,
                "meta_se_beta1": None,
                "z": None,
                "p_value": None,
                "ci_lower": None,
                "ci_upper": None,
                "total_inv_var": B,
            },
            WarnException(
                (
                    f"Pooled result not computed: only {n_sites} site(s) passed the per-site "
                    "fit gates, and a cross-site meta-analysis needs at least two. The most "
                    "common cause is a degenerate local logistic fit (too few usable records, "
                    "one outcome class, a singular design matrix, or a zero score standard "
                    "deviation) at the other site(s)."
                ),
                code="FEWER_THAN_TWO_USABLE_SITES",
                details={"n_sites_combined": n_sites},
            ),
        )
    if B < _META_ANALYSIS_DENOM_TOL:
        logging.getLogger(__name__).warning(
            "local_post_meta_analysis: aggregated denominator Σ wₖ = %.3e is below "
            "the tolerance %.0e; skipping division and reporting FAIL. All clients "
            "either had a degenerate local fit or saw SEₖ < 1e-10 (treated as zero).",
            B, _META_ANALYSIS_DENOM_TOL,
        )
        return _attach_meta_analysis_warning(
            {
                "status": "FAIL",
                "msg": (
                    f"Aggregated denominator Σ wₖ = {B:.3e} is below tolerance "
                    f"{_META_ANALYSIS_DENOM_TOL:.0e}; meta-analysis division would be "
                    "undefined. Every client either had a degenerate local fit or saw "
                    "SEₖ < 1e-10 (treated as zero)."
                ),
                "meta_beta1": None,
                "meta_se_beta1": None,
                "z": None,
                "p_value": None,
                "ci_lower": None,
                "ci_upper": None,
                "total_inv_var": B,
            },
            WarnException(
                (
                    "Pooled result not computed: the aggregated inverse-variance weight "
                    f"Σ wₖ = {B:.3e} is effectively zero, so the pooled estimate is undefined. "
                    "Every site either had a degenerate local fit or reported a near-zero "
                    "standard error (treated as a zero-weight share)."
                ),
                code="META_ANALYSIS_DENOMINATOR_ZERO",
                details={"total_inv_var": B, "tolerance": _META_ANALYSIS_DENOM_TOL},
            ),
        )
    beta_pooled = A / B
    se_pooled = 1.0 / math.sqrt(B)
    z = beta_pooled / se_pooled
    p_value = 2.0 * stats.norm.sf(abs(z))
    result = {
        "meta_beta1": beta_pooled,
        "meta_se_beta1": se_pooled,
        "z": z,
        "p_value": float(p_value),
        "ci_lower": beta_pooled - 1.96 * se_pooled,
        "ci_upper": beta_pooled + 1.96 * se_pooled,
        "total_inv_var": B,
    }
    if n_sites is not None:
        result["n_sites_combined"] = n_sites
    return result


def _simulator_biomarker_group_dir(group_idx: str):
    """Return ``.../biomarker_models/datasource_group_<n>`` for simulator runs.

    When ``duality_nvflare_apis`` is installed in site-packages, ``__file__`` does not
    sit next to the repo ``biomarker_models`` tree; we then search upward from ``cwd``
    (NVFlare server cwd is typically under ``.../nvflare_jobs/outputs/...``).

    Optional: set ``DUALITY_SIM_BIOMARKER_MODELS_ROOT`` to the ``biomarker_models``
    directory (parent of ``datasource_group_*``).
    """
    name = f"datasource_group_{group_idx}"
    root = os.getenv("DUALITY_SIM_BIOMARKER_MODELS_ROOT", "").strip()
    if root:
        p = Path(root).expanduser().resolve() / name
        if p.is_dir():
            return p

    here = Path(__file__).resolve()
    cand = here.parent.parent / "biomarker_models" / name
    if cand.is_dir():
        return cand

    cwd = Path.cwd().resolve()
    for base in [cwd, *list(cwd.parents)[:96]]:
        for rel in (
            ("biomarker_models", name),
            ("nvflare_jobs", "biomarker_models", name),
        ):
            p = base.joinpath(*rel)
            if p.is_dir():
                return p
    return None


def _model_file_sources_config_candidates(config_name: str, model_dir: str = None):
    raw_name = str(config_name or "model_file_sources.json").strip() or "model_file_sources.json"
    candidate = Path(raw_name).expanduser()
    if candidate.is_absolute():
        yield candidate

    if model_dir is not None and str(model_dir).strip():
        yield Path(model_dir).expanduser().resolve() / raw_name

    cwd = Path.cwd().resolve()
    for base in [cwd, *list(cwd.parents)[:64]]:
        yield base / raw_name
        yield base / "custom" / raw_name
        yield base / "app_client" / "custom" / raw_name


def _load_model_file_sources_config(config_name: str, model_dir: str = None):
    seen = set()
    for candidate in _model_file_sources_config_candidates(config_name, model_dir):
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            continue
        with candidate.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError(f"Model file sources config {candidate} must be a JSON object")
        return payload, candidate
    return None, None


def _resolve_biomarker_model_paths_from_sources_config(workload_args: dict, model_dir: str = None) -> bool:
    config_name = (
        workload_args.get("model_file_sources_config")
        or workload_args.get("model_sources_config")
        or "model_file_sources.json"
    )
    payload, config_path = _load_model_file_sources_config(str(config_name), model_dir=model_dir)
    if not payload:
        return False

    mk = str(workload_args["model_key"]).strip()
    models = payload.get("models")
    if not isinstance(models, dict):
        raise ValueError(f"Model file sources config {config_path} is missing a 'models' object")

    sources = models.get(mk)
    if not isinstance(sources, dict):
        raise FileNotFoundError(f"Model file sources config {config_path} has no model entry for {mk!r}")

    weights_path = sources.get("weights")
    cutoff_path = sources.get("cutoff")
    if not isinstance(weights_path, str) or not weights_path.strip():
        raise FileNotFoundError(f"Model file sources config {config_path} is missing weights path for {mk!r}")
    if not isinstance(cutoff_path, str) or not cutoff_path.strip():
        raise FileNotFoundError(f"Model file sources config {config_path} is missing cutoff path for {mk!r}")

    weights_path = os.path.abspath(os.path.expanduser(weights_path.strip()))
    cutoff_path = os.path.abspath(os.path.expanduser(cutoff_path.strip()))

    if not os.path.isfile(weights_path):
        raise FileNotFoundError(f"Biomarker model weights file does not exist: {weights_path!r}")
    if not os.path.isfile(cutoff_path):
        raise FileNotFoundError(f"Biomarker model cutoff file does not exist: {cutoff_path!r}")

    workload_args["scale_coeff_file_path"] = weights_path
    workload_args["cutoff_file_path"] = cutoff_path
    return True


def resolve_biomarker_model_paths(workload_args: dict, model_dir: str = None) -> None:
    """Set absolute ``scale_coeff_file_path`` and ``cutoff_file_path`` on ``workload_args``.

    In the NVFlare simulator, ``--datasource-version 2_i`` resolves to
    ``biomarker_models/datasource_group_i`` under the ``nvflare_jobs`` tree (discovered
    via ``__file__``, ``cwd`` ancestors, or ``DUALITY_SIM_BIOMARKER_MODELS_ROOT``), overriding
    ``model_dir`` (the job ``custom`` staging folder used in deployment).

    Otherwise: if ``model_dir`` is provided, use it; if not, use ``MODEL_DIR_<suffix>``.
    Filenames are ``{model_key}_{cancer_type}_weights.csv`` and ``_cutoff.csv``.
    """
    if _resolve_biomarker_model_paths_from_sources_config(workload_args, model_dir=model_dir):
        return

    mk = str(workload_args["model_key"]).strip()
    cancer_type = str(workload_args["cancer_type"]).strip()

    suffix = (os.getenv("DUALITY_SIM_DATASOURCE_VERSION", "2_1") or "2_1").strip() or "2_1"
    sim = os.getenv("FL_IS_SIMULATOR", "").strip().lower() in ("1", "true", "yes", "on")

    resolved_model_dir = None
    if sim:
        m = re.match(r"^2_(\d+)$", suffix)
        if m:
            found = _simulator_biomarker_group_dir(m.group(1))
            if found is None:
                raise FileNotFoundError(
                    f"Simulator biomarker model directory not found for datasource_group_{m.group(1)} "
                    f"(DUALITY_SIM_DATASOURCE_VERSION={suffix!r}). "
                    f"Set DUALITY_SIM_BIOMARKER_MODELS_ROOT to the biomarker_models directory, "
                    f"or run with cwd under nvflare_jobs (e.g. outputs/.../server)."
                )
            resolved_model_dir = str(found)

    if resolved_model_dir is None:
        if model_dir is not None and str(model_dir).strip():
            resolved_model_dir = os.path.abspath(str(model_dir).strip())
        else:
            versioned_key = f"MODEL_DIR_{suffix}"
            raw = os.environ.get(versioned_key, "").strip()
            if not raw:
                raise RuntimeError(
                    f"No explicit model_dir was provided and {versioned_key} is not set."
                )

            p = Path(raw)
            if p.is_absolute():
                resolved_model_dir = str(p.resolve())
            else:
                hint = os.getenv("DUALITY_SIM_DATASOURCE_BASE")
                if hint:
                    cand = (Path(hint).expanduser().resolve() / raw).resolve()
                    if cand.is_dir() or cand.is_file():
                        resolved_model_dir = str(cand)
                    else:
                        resolved_model_dir = None
                else:
                    resolved_model_dir = None

                if resolved_model_dir is None:
                    cwd = Path.cwd().resolve()
                    for base in [cwd, *list(cwd.parents)[:64]]:
                        cand = (base / raw).resolve()
                        if cand.is_dir() or cand.is_file():
                            resolved_model_dir = str(cand)
                            break
                    else:
                        resolved_model_dir = str((cwd / raw).resolve())

    if not os.path.isdir(resolved_model_dir):
        raise FileNotFoundError(
            f"Biomarker model directory does not exist: {resolved_model_dir!r}"
        )

    workload_args["scale_coeff_file_path"] = os.path.abspath(
        os.path.join(resolved_model_dir, f"{mk}_{cancer_type}_weights.csv")
    )
    workload_args["cutoff_file_path"] = os.path.abspath(
        os.path.join(resolved_model_dir, f"{mk}_{cancer_type}_cutoff.csv")
    )


def resolve_encrypted_biomarker_model_paths(workload_args: dict, model_dir: str, for_scoring: bool = False) -> None:
    """Set the encrypted-model artifact paths on ``workload_args``.

    Unlike :func:`resolve_biomarker_model_paths` (which *discovers* the plaintext source
    CSVs in the simulator/datasource tree), the encrypted artifacts are produced by the
    leader client during ``workflow_model_upload`` and written by the server into the job's
    ``app_server/custom`` directory. They are job-workspace artifacts, so this is a plain
    ``model_dir`` + filename join with no discovery -- which keeps the write location
    (``_workflow_model_upload``) and the read location (persistor / openfhe aggregation)
    identical in both simulator and deployment.

    Sets three keys, named by ``{model_key}_{cancer_type}`` (plus a ``_score`` marker for
    the LCS scoring variant):
      - ``coeff_ct_file_path``:   serialized OpenFHE ciphertext of the (scaled) coefficients
      - ``cutoff_ct_file_path``:  serialized OpenFHE ciphertext of the (scaled) cutoff
      - ``scale_factor_file_path``: JSON sidecar holding ``{"rsf": <float>}``

    ``for_scoring`` selects the variant: discovery encrypts at ``rsf = 1/|cutoff|``,
    LCS scoring at ``rsf = 1.0``. These are two distinct encryptions of the same
    model_key, so the scoring variant carries a ``_score`` marker so a job running both
    validations does not overwrite the discovery artifacts on disk.
    """
    mk = str(workload_args["model_key"]).strip()
    cancer_type = str(workload_args["cancer_type"]).strip()
    base = os.path.abspath(str(model_dir))
    variant = "_score" if for_scoring else ""
    workload_args["coeff_ct_file_path"] = os.path.join(base, f"{mk}_{cancer_type}{variant}_coeff.ct")
    workload_args["cutoff_ct_file_path"] = os.path.join(base, f"{mk}_{cancer_type}{variant}_cutoff.ct")
    workload_args["inv_rsf_ct_file_path"] = os.path.join(base, f"{mk}_{cancer_type}{variant}_inv_rsf.ct")
    workload_args["scale_factor_file_path"] = os.path.join(base, f"{mk}_{cancer_type}{variant}_scale.json")


def _canonical_weights_column_label(column) -> str:
    """Return a forgiving normalized header label for biomarker weights files."""
    return str(column).replace("\ufeff", "").strip().lower()


def _normalize_weights_dataframe_columns(
    df: pd.DataFrame, source_label: str = "weights file"
) -> pd.DataFrame:
    """Normalize biomarker weights to the internal ``covariate``/``coef`` shape.

    Older model files use ``covariate`` for the feature name. Newer model files may
    use ``feature`` instead. CSV headers are normalized for whitespace, case, and
    UTF-8 BOM artifacts before validation, so columns like `` feature`` or
    ``Coef`` are accepted. Some logistic-regression model files provide both
    ``coef_scaled`` and ``coef_raw`` instead of ``coef``; this engine multiplies
    coefficients directly by the raw FHIR feature values, so ``coef_scaled`` is
    the compatible coefficient column and is normalized to ``coef`` when a plain
    ``coef`` column is absent. Downstream scoring/encryption code still expects
    ``covariate`` and ``coef``, so normalize aliases once at the boundary.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"{source_label} must be loaded as a pandas DataFrame")

    rename_map = {}
    normalized_seen = {}
    for column in df.columns:
        normalized = _canonical_weights_column_label(column)
        canonical = None
        if normalized in (
            "covariate",
            "feature",
            "coef",
            "coef_scaled",
            "coef_raw",
            "scaler_mean",
            "scaler_scale",
            "penalized",
        ):
            canonical = normalized

        if canonical is None:
            continue

        existing = normalized_seen.get(canonical)
        if existing is not None and existing != column:
            raise ValueError(
                f"{source_label} has duplicate columns that normalize to {canonical!r}: "
                f"{existing!r} and {column!r}"
            )

        normalized_seen[canonical] = column
        if column != canonical:
            rename_map[column] = canonical

    if rename_map:
        df = df.rename(columns=rename_map).copy()

    if "coef" not in df.columns and "coef_scaled" in df.columns:
        df = df.rename(columns={"coef_scaled": "coef"}).copy()

    if "coef" not in df.columns:
        raise ValueError(
            f"{source_label} must contain 'coef' or 'coef_scaled'. "
            f"Found columns: {list(df.columns)!r}"
        )

    if "covariate" not in df.columns:
        if "feature" not in df.columns:
            raise ValueError(
                f"{source_label} must contain either 'covariate' or 'feature' columns. "
                f"Found columns: {list(df.columns)!r}"
            )
        df = df.rename(columns={"feature": "covariate"}).copy()

    return df


def load_weights_dataframe(path: str) -> pd.DataFrame:
    """Load weights CSV with ``covariate``/``feature`` and ``coef``/``coef_scaled``.

    If a ``penalized`` column exists, keep only truthy rows; otherwise keep all rows.
    The returned DataFrame always exposes the normalized internal columns
    ``covariate`` and ``coef``.
    """
    df = _normalize_weights_dataframe_columns(pd.read_csv(path), source_label=f"weights file {path!r}")
    if "penalized" in df.columns:
        pen = df["penalized"]
        if pen.dtype == bool:
            mask = pen
        else:
            mask = pen.astype(str).str.strip().str.lower().isin(
                ("true", "1", "yes", "t")
            )
        df = df.loc[mask].copy()
    return df[["covariate", "coef"]].reset_index(drop=True)


def _coerce_float_scalar(value, label: str = "value") -> float:
    """Coerce a scalar-like value into a float with a useful error message."""
    if hasattr(value, "to_numpy"):
        arr = value.to_numpy().reshape(-1)
        arr = [v for v in arr if not pd.isna(v)]
        if len(arr) != 1:
            raise ValueError(
                f"{label} must contain exactly one numeric value; found {len(arr)} values"
            )
        value = arr[0]

    while isinstance(value, (list, tuple, np.ndarray)):
        if len(value) != 1:
            raise ValueError(
                f"{label} must contain exactly one numeric value; found {len(value)} values"
            )
        value = value[0]

    if isinstance(value, str):
        value = value.replace("\ufeff", "").strip()
        if not value:
            raise ValueError(f"{label} cannot be blank")

    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be numeric, got {value!r}") from e


def load_cutoff_value(path: str, model_type: str = None) -> float:
    """Load a biomarker cutoff CSV by column name, not by positional cell.

    Legacy cutoff files start with ``cutoff`` as the first column. Newer logistic
    regression cutoff files start with metadata like ``model_type`` and keep the
    numeric threshold in a named ``cutoff`` column. This helper always selects the
    cutoff/threshold column by normalized header name so metadata columns such as
    ``model_type=logistic`` are never mistaken for the numeric cutoff.

    Args:
        path: CSV path for the model cutoff file.
        model_type: Optional model type/key used only when the CSV contains
            multiple rows and a ``model_type`` column.

    Returns:
        float: The single numeric cutoff value.
    """
    df = pd.read_csv(path)
    source_label = f"cutoff file {path!r}"
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError(f"{source_label} is empty")

    rename_map = {}
    normalized_seen = {}
    for column in df.columns:
        normalized = _canonical_weights_column_label(column)
        canonical = None
        if normalized in (
            "model_type",
            "model_key",
            "cutoff",
            "cutoff_value",
            "threshold",
        ):
            canonical = normalized

        if canonical is None:
            continue

        existing = normalized_seen.get(canonical)
        if existing is not None and existing != column:
            raise ValueError(
                f"{source_label} has duplicate columns that normalize to {canonical!r}: "
                f"{existing!r} and {column!r}"
            )

        normalized_seen[canonical] = column
        if column != canonical:
            rename_map[column] = canonical

    if rename_map:
        df = df.rename(columns=rename_map).copy()

    cutoff_column = None
    for candidate in ("cutoff", "cutoff_value", "threshold"):
        if candidate in df.columns:
            cutoff_column = candidate
            break

    if cutoff_column is None:
        raise ValueError(
            f"{source_label} must contain a named cutoff column "
            f"('cutoff', 'cutoff_value', or 'threshold'). Found columns: {list(df.columns)!r}"
        )

    rows = df
    if model_type is not None and "model_type" in rows.columns:
        target = str(model_type).replace("_reg", "").replace("_", "").strip().lower()

        def _norm_model_type(v):
            return str(v).replace("_reg", "").replace("_", "").strip().lower()

        matched = rows[rows["model_type"].map(_norm_model_type) == target]
        if not matched.empty:
            rows = matched

    numeric_values = pd.to_numeric(rows[cutoff_column], errors="coerce").dropna().tolist()
    if len(numeric_values) != 1:
        raise ValueError(
            f"{source_label} column {cutoff_column!r} must contain exactly one numeric cutoff "
            f"value after filtering; found {len(numeric_values)}. Found columns: {list(df.columns)!r}"
        )

    return _coerce_float_scalar(numeric_values[0], "biomarker model cutoff")
