from enum import Enum
from typing import Dict, Optional


class SupportedFunction(str, Enum):
    # Enum of computation functions supported by the system.
    # Used to validate requests and map to back-end logic.    
    SURVIVAL_ANALYSIS = "SURVIVAL_ANALYSIS"
    CHI_SQUARE_TEST = "CHI_SQUARE_TEST"
    MEAN = "MEAN"
    STANDARD_DEVIATION = "STANDARD_DEVIATION"
    PARTICIPATION_CONFIRMATION = "PARTICIPATION_CONFIRMATION"
    T_TEST = "T_TEST"
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
        "cutoff_file_path": "str",
        "scale_coeff_file_path": "str",
        "cancer_type": "str",
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
    }
}

FUNCTION_DEFAULT_PROPERTIES: Dict[SupportedFunction, Dict[str, str]] = {
    SupportedFunction.SURVIVAL_ANALYSIS: {
        "group_column_id": "PBRM1",
        "time_column_id": "OS",
        "censoring_column_id": "OS_CNSR",
        "time_grid_min": "0",
        "time_grid_step": "0.1",
        "time_grid_max": "62",
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
    "kaplan-meier": "Survivability Analysis",
    "chi2": "Chi-Square Test",
    "mean": "Mean",
    "stdev": "Standard Deviation",
    "_PRE_COUNT_SECURE_": "Threshold Count - Secure",
    "_PRE_COUNT_UNSECURE_": "Threshold Count - Unsecure",
    "t-test": "T-Test",
    "meta-analysis": "Exceptional Response Discrimination"

}
