from app.core.mysql.managers.FunctionsManager import FunctionsManager, _normalize_functions_map


def test_normalize_map_accepts_single_and_multiple_config_shapes():
    result = FunctionsManager.normalize_map(
        {
            " mean ": {" data_column_id ": "Age", "blank": None},
            "t_test": [{"category": 1}, "ignored", {"value": True}],
            "": {"x": "y"},
        }
    )
    assert result == {
        "MEAN": [{"data_column_id": "Age", "blank": ""}],
        "T_TEST": [{"category": "1"}, {"value": "True"}],
    }


def test_normalize_props_ignores_blank_keys():
    assert FunctionsManager._normalize_props({" ": "x", " a ": None}) == {"a": ""}


def test_compatibility_normalize_function_applies_defaults_and_typed_values():
    result = _normalize_functions_map({"mean": {"x": 1}})
    assert result == {"MEAN": [{"x": 1, "data_column_id": "Age"}]}

def test_legacy_exceptional_response_name_canonicalizes():
    result = FunctionsManager.normalize_map(
        {"logistic_calibration_statistics": {"model_type": "Encrypted"}}
    )
    assert list(result) == ["EXCEPTIONAL_RESPONSE_DISCRIMINATION"]

    normalized = _normalize_functions_map(
        {"LOGISTIC_CALIBRATION_STATISTICS": {"model_type": "Encrypted"}}
    )
    assert list(normalized) == ["EXCEPTIONAL_RESPONSE_DISCRIMINATION"]

