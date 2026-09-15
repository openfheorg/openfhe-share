import pytest

from app.core.job_runner.nvflare_jobs.apis.fhir.fhir_value_utils import (
    _coerce_float,
    get_fhir_numeric_value,
)


@pytest.mark.parametrize(
    "value,expected",
    [(None, None), ("", None), (" 3.5 ", 3.5), (4, 4.0), ("x", None)],
)
def test_coerce_float(value, expected):
    assert _coerce_float(value) == expected


def test_get_fhir_numeric_value_prefers_quantity_over_primitives():
    resource = {"valueQuantity": {"value": "2.5"}, "valueInteger": 9}
    assert get_fhir_numeric_value(resource) == 2.5


def test_get_fhir_numeric_value_falls_back_to_requested_primitive_keys():
    resource = {"valueQuantity": {"value": "bad"}, "valueDecimal": "1.25"}
    assert get_fhir_numeric_value(resource, primitive_keys=("valueDecimal",)) == 1.25
    assert get_fhir_numeric_value([], primitive_keys=("valueDecimal",)) is None
