from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.core.EnvironmentManager import Environment
from app.api.routes.ClientRoutes import (
    _body_bool,
    _canonicalize_functions_map,
    _normalize_client_name_set,
    _parse_optional_int,
    _participation_row_matches_selected_roles,
    _validate_internal_backend_secret,
)


@pytest.mark.parametrize(
    "value,expected",
    [(None, None), ("", None), ("none", None), ("7", 7), (8, 8)],
)
def test_parse_optional_int(value, expected):
    assert _parse_optional_int(value, "field") == expected


def test_parse_optional_int_rejects_invalid_value():
    with pytest.raises(ValueError, match="field must be an integer"):
        _parse_optional_int("abc", "field")


@pytest.mark.parametrize(
    "value,default,expected",
    [
        (None, True, True),
        (True, False, True),
        ("yes", False, True),
        ("off", True, False),
        (1, False, True),
        (0, True, False),
        (object(), True, True),
    ],
)
def test_body_bool(value, default, expected):
    assert _body_bool(value, default) is expected


def test_normalize_client_name_set():
    assert _normalize_client_name_set([" site1 ", "", 2]) == {"site1", "2"}
    assert _normalize_client_name_set("site1") == set()


def test_participation_row_matches_selected_roles_defaults_missing_flags_to_true():
    row = {"client_name": "site1", "contributing_party": None, "analyzing_party": None}
    assert _participation_row_matches_selected_roles(row, set(), set()) is True
    assert _participation_row_matches_selected_roles(row, {"site1"}, set()) is False


def test_canonicalize_functions_map_merges_configs_and_normalizes_names():
    result = _canonicalize_functions_map(
        {
            " mean ": [{" a ": 1}, {"b": None}, "ignored"],
            "": [{"x": 1}],
        }
    )
    assert result == {"MEAN": {"a": "1", "b": ""}}


def test_validate_secret_skips_local():
    with patch(
        "app.api.routes.ClientRoutes.EnvironmentProvider.get_env",
        return_value=Environment.LOCAL,
    ), patch("app.api.routes.ClientRoutes.ResourceConfigProvider.get_mysql_config") as config:
        _validate_internal_backend_secret({})
    config.assert_not_called()


def test_validate_secret_refreshes_then_rejects_bad_password():
    config = Mock()
    config.password = "real"
    with patch(
        "app.api.routes.ClientRoutes.EnvironmentProvider.get_env",
        return_value=Environment.DEV,
    ), patch(
        "app.api.routes.ClientRoutes.ResourceConfigProvider.get_mysql_config",
        return_value=config,
    ) as get_config:
        with pytest.raises(HTTPException) as exc:
            _validate_internal_backend_secret({"$pw": "bad"})
    assert exc.value.status_code == 401
    assert get_config.call_count == 2
