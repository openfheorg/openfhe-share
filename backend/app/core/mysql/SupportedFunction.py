from enum import Enum
from typing import Any, Dict, Optional


#model_type property values:
MODEL_TYPE_OPEN_ACCESS = "Open-access"
MODEL_TYPE_ENCRYPTED = "Encrypted"

class SupportedFunction(str, Enum):
    # Enum of computation functions supported by the system.
    # Used to validate requests and map to back-end logic.
    SURVIVAL_ANALYSIS = "SURVIVAL_ANALYSIS"
    CHI_SQUARE_TEST = "CHI_SQUARE_TEST"
    MEAN = "MEAN"
    STANDARD_DEVIATION = "STANDARD_DEVIATION"
    PARTICIPATION_CONFIRMATION = "PARTICIPATION_CONFIRMATION"
    T_TEST = "T_TEST"
    ENCRYPTED_FILTERING = "ENCRYPTED_FILTERING"
    COUNT = "COUNT"
    EXCEPTIONAL_RESPONSE_DISCRIMINATION = "EXCEPTIONAL_RESPONSE_DISCRIMINATION"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_name(cls, name: str) -> Optional["SupportedFunction"]:
        if not name:
            return None
        text = str(name).strip()
        try:
            return cls(text)
        except ValueError:
            key = text.lower()
            alias_map = {
                "survival_analysis": cls.SURVIVAL_ANALYSIS,
                "chi_square_test": cls.CHI_SQUARE_TEST,
                "mean": cls.MEAN,
                "standard_deviation": cls.STANDARD_DEVIATION,
                "participation_confirmation": cls.PARTICIPATION_CONFIRMATION,
                "t_test": cls.T_TEST,
                "encrypted_filtering": cls.ENCRYPTED_FILTERING,
                "count": cls.COUNT,
                "exceptional_response_discrimination": cls.EXCEPTIONAL_RESPONSE_DISCRIMINATION,
                # Backward compatibility for clients/persisted payloads that still use the legacy token.
                "logistic_calibration_statistics": cls.EXCEPTIONAL_RESPONSE_DISCRIMINATION,
            }
            return alias_map.get(key)

    @classmethod
    def get_property_type(cls, function_name: str, property_name: str) -> Optional[str]:
        fn = cls.from_name(function_name)
        if fn is None or not property_name:
            return None
        properties = FUNCTION_PROPERTY_TYPES.get(fn)
        if not properties:
            return None
        return properties.get(property_name)

    @classmethod
    def get_default_properties(cls, function_name: str) -> Optional[Dict[str, str]]:
        fn = cls.from_name(function_name)
        if fn is None:
            return None
        defaults = FUNCTION_DEFAULT_PROPERTIES.get(fn)
        if not defaults:
            return None
        return dict(defaults)

    @staticmethod
    def coerce_value_for_type(type_name: Optional[str], value: Any) -> Any:
        # Single source of truth for FUNCTION_PROPERTY_TYPES coercion. Returns the value cast
        # into the declared type (int/float/bool), or the original value when the type is
        # "str"/unknown, when the value is None, or when parsing fails (leaving raw input
        # so downstream validation can surface a precise error).
        pt = str(type_name or "").strip().lower()
        if value is None:
            return value

        if pt in ("bool", "boolean"):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("true", "1", "yes", "t", "y"):
                    return True
                if v in ("false", "0", "no", "f", "n", ""):
                    return False
            return value

        if pt in ("int", "integer"):
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                s = value.strip()
                if s:
                    try:
                        return int(s)
                    except ValueError:
                        try:
                            f = float(s)
                            if f.is_integer():
                                return int(f)
                        except ValueError:
                            pass
            return value

        if pt in ("float", "number", "decimal"):
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                s = value.strip()
                if s:
                    try:
                        return float(s)
                    except ValueError:
                        pass
            return value

        # "str" or unknown: don't touch — callers may have already chosen string semantics.
        return value

    @classmethod
    def coerce_properties_for_function(cls, function_name: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        # Return a new dict with each property coerced to the type declared in
        # FUNCTION_PROPERTY_TYPES for this function. Unknown function or unknown property:
        # value passes through unchanged.
        types = FUNCTION_PROPERTY_TYPES.get(cls.from_name(function_name) or "", {}) or {}
        out: Dict[str, Any] = {}
        for k, v in (properties or {}).items():
            key = str(k)
            out[key] = cls.coerce_value_for_type(types.get(key), v)
        return out


FUNCTION_PROPERTY_TYPES: Dict[SupportedFunction, Dict[str, str]] = {
    SupportedFunction.SURVIVAL_ANALYSIS: {
        "group_column_id": "str",
        "time_column_id": "str",
        "censoring_column_id": "str",
        "time_grid_min": "float",
        "time_grid_step": "float",
        "time_grid_max": "float",
        "is_biomarker_discovery": "bool",
        "is_server_contributing_to_aggregation": "bool",
        "model_key": "str",
        "cancer_type": "str",
        "CI_type": "str"
    },
    SupportedFunction.CHI_SQUARE_TEST: {
        "category_column_1_id": "str",
        "category_column_2_id": "str",
    },
    SupportedFunction.MEAN: {
        "data_column_id": "str",
    },
    SupportedFunction.STANDARD_DEVIATION: {
        "data_column_id": "str",
        "std_type": "str",
    },
    SupportedFunction.T_TEST: {
        "data_column_id": "str",
        "category_column_1_id": "str"
    },
    SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION: {
        "cancer_type": "str",
        "model_type": "str",
        "model_key": "str",
    },
}

FUNCTION_DEFAULT_PROPERTIES: Dict[SupportedFunction, Dict[str, str]] = {
    SupportedFunction.SURVIVAL_ANALYSIS: {
        "group_column_id": "PBRM1",
        "time_column_id": "OS",
        "censoring_column_id": "OS_CNSR",
        "time_grid_min": "0",
        "time_grid_step": "0.1",
        "time_grid_max": "62",
        "CI_type": "None"
    },
    SupportedFunction.CHI_SQUARE_TEST: {
        "category_column_1_id": "PBRM1",
        "category_column_2_id": "gender",
    },
    SupportedFunction.MEAN: {
        "data_column_id": "Age",
    },
    SupportedFunction.STANDARD_DEVIATION: {
        "data_column_id": "Age",
        "std_type": "population",
    },
    SupportedFunction.T_TEST: {
        "data_column_id": "Age",
        "category_column_1_id": "PBRM1"
    },
    SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION: {
        # Both paths are wired end-to-end. Default to the encrypted path so the
        # biomarker model weights stay private from the participants and the
        # computing server (encrypt-at-initiator: model_upload[Encrypted] -> HE
        # scoring -> mean-stdev -> meta-analysis). Users can switch to
        # Open-access from the model_type dropdown.
        "model_type": MODEL_TYPE_ENCRYPTED,
    }
}

# Maps our logical function names to the computation_type values used by the analytics workflow
FUNCTION_TO_COMPUTATION_TYPE = {
    "SURVIVAL_ANALYSIS": "kaplan-meier",
    "CHI_SQUARE_TEST": "chi2",
    "MEAN": "mean",
    "STANDARD_DEVIATION": "stdev",
    "T_TEST": "t-test",
    "EXCEPTIONAL_RESPONSE_DISCRIMINATION": "meta-analysis"
}

#Gives us nice display of labels on log
FUNCTION_LABELS = {
    "kaplan-meier": "Survival Analysis",
    "chi2": "Chi-Square Test",
    "mean": "Mean",
    "stdev": "Standard Deviation",
    "t-test": "T-Test",
    "meta-analysis": "Exceptional Response Discrimination",
    "biomarker_enc_risk_group_computation": "Biomarker Discovery (Encrypted)",
    "_PRE_COUNT_SECURE_": "Threshold Count - Secure",
    "_PRE_COUNT_UNSECURE_": "Threshold Count - Unsecure",
}
