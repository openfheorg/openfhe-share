import json
from unittest.mock import Mock, patch

import pytest

from app.api.routes.FilterRoutes import fetch_filters, fetch_single_filter


class RequestStub:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    async def json(self):
        if self.error:
            raise self.error
        return self.payload


def body(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_fetch_single_filter_requires_integer_id():
    response = await fetch_single_filter(RequestStub({}))
    assert response.status_code == 400
    response = await fetch_single_filter(RequestStub({"filter_id": "x"}))
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_fetch_single_filter_returns_manager_result_and_closes():
    retriever = Mock()
    retriever.get_single_filter.return_value = {"id": 4}
    with patch("app.api.routes.FilterRoutes.MySQLRetriever", return_value=retriever):
        response = await fetch_single_filter(RequestStub({"filter_id": "4"}))
    assert response.status_code == 200
    assert body(response) == {"status": "SUCCESS", "filter": {"id": 4}}
    retriever.get_single_filter.assert_called_once_with(4)
    retriever.complete.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_filters_requires_project_id():
    response = await fetch_filters(RequestStub({}))
    assert response.status_code == 400
    assert body(response)["error"] == "project_id is required"


@pytest.mark.asyncio
async def test_fetch_filters_passes_project_id_and_closes():
    retriever = Mock()
    retriever.get_all_filters.return_value = [{"id": 1}]
    with patch("app.api.routes.FilterRoutes.MySQLRetriever", return_value=retriever):
        response = await fetch_filters(RequestStub({"project_id": "2"}))
    assert body(response)["filters"] == [{"id": 1}]
    retriever.get_all_filters.assert_called_once_with(project_id=2)
    retriever.complete.assert_called_once()
