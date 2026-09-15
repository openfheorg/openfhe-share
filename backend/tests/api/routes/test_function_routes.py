import json
from unittest.mock import Mock, patch

import pytest

from app.api.routes.FunctionRoutes import fetch_supported_functions


def body(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_fetch_supported_functions_returns_rows_and_closes():
    manager = Mock()
    manager.get_supported_functions.return_value = [{"name": "MEAN"}]
    with patch("app.api.routes.FunctionRoutes.FunctionsManager", return_value=manager):
        response = await fetch_supported_functions(None)
    assert response.status_code == 200
    assert body(response) == {"status": "SUCCESS", "functions": [{"name": "MEAN"}]}
    manager.complete.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_supported_functions_hides_internal_error():
    manager = Mock()
    manager.get_supported_functions.side_effect = RuntimeError("secret")
    with patch("app.api.routes.FunctionRoutes.FunctionsManager", return_value=manager):
        response = await fetch_supported_functions(None)
    assert response.status_code == 500
    assert body(response) == {"status": "FAILURE", "error": "Internal error"}
    manager.complete.assert_called_once()
