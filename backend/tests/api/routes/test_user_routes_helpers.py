from unittest.mock import Mock

import pytest

from app.api.routes.UserRoutes import (
    _resolve_user_id,
    normalize_datasource_source,
    normalize_model_file_source,
)


@pytest.mark.parametrize(
    "source,expected",
    [
        (" https://example.org/fhir/ ", "https://example.org/fhir"),
        ("/data/site1.json", "/data/site1.json"),
        ("DATA.JSON", "DATA.JSON"),
    ],
)
def test_normalize_datasource_source_accepts_supported_sources(source, expected):
    assert normalize_datasource_source(source) == expected


@pytest.mark.parametrize(
    "source,message",
    [
        ("", "required"),
        ("https://example.org/api", "end with /fhir"),
        ("not-json.csv", "end with .json"),
    ],
)
def test_normalize_datasource_source_rejects_invalid_values(source, message):
    with pytest.raises(ValueError, match=message):
        normalize_datasource_source(source)


def test_normalize_model_file_source_requires_nonblank_value():
    assert normalize_model_file_source(" /models/a.csv ") == "/models/a.csv"
    with pytest.raises(ValueError):
        normalize_model_file_source(" ")


def test_resolve_user_id_prefers_explicit_id_then_username():
    manager = Mock()
    manager.get_user_id_by_username.return_value = 8
    assert _resolve_user_id(manager, 3, "name") == 3
    manager.get_user_id_by_username.assert_not_called()
    assert _resolve_user_id(manager, None, "name") == 8
    assert _resolve_user_id(manager, None, None) is None
