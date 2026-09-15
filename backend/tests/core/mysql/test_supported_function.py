import pytest

from app.core.mysql.SupportedFunction import (
    MODEL_TYPE_ENCRYPTED,
    SupportedFunction,
)


def test_from_name_accepts_enum_value_and_lowercase_alias():
    assert SupportedFunction.from_name("MEAN") is SupportedFunction.MEAN
    assert SupportedFunction.from_name(" exceptional_response_discrimination ") is SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION
    # Legacy payloads remain accepted and canonicalize to the renamed function.
    assert SupportedFunction.from_name(" logistic_calibration_statistics ") is SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION
    assert SupportedFunction.from_name("unknown") is None


def test_property_type_and_defaults_are_defensive_copies():
    assert SupportedFunction.get_property_type("SURVIVAL_ANALYSIS", "time_grid_min") == "float"
    defaults = SupportedFunction.get_default_properties("EXCEPTIONAL_RESPONSE_DISCRIMINATION")
    assert defaults == {"model_type": MODEL_TYPE_ENCRYPTED}
    defaults["model_type"] = "changed"
    assert SupportedFunction.get_default_properties("EXCEPTIONAL_RESPONSE_DISCRIMINATION")["model_type"] == MODEL_TYPE_ENCRYPTED


@pytest.mark.parametrize(
    "type_name,value,expected",
    [
        ("bool", "yes", True),
        ("bool", "0", False),
        ("int", "4.0", 4),
        ("int", 4.5, 4.5),
        ("float", "3.25", 3.25),
        ("str", 9, 9),
        (None, "raw", "raw"),
    ],
)
def test_coerce_value_for_type(type_name, value, expected):
    assert SupportedFunction.coerce_value_for_type(type_name, value) == expected


def test_coerce_properties_for_function_only_casts_known_properties():
    result = SupportedFunction.coerce_properties_for_function(
        "SURVIVAL_ANALYSIS",
        {"time_grid_min": "1.5", "is_biomarker_discovery": "true", "unknown": "7"},
    )
    assert result == {
        "time_grid_min": 1.5,
        "is_biomarker_discovery": True,
        "unknown": "7",
    }
