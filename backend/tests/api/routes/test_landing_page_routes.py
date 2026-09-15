import json
from unittest.mock import Mock, patch

import pytest

from app.api.routes.LandingPageRoutes import (
    HomeLandingRequest,
    ProjectLandingRequest,
    get_home_landing_data,
    get_project_landing_data,
)


def body(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_get_home_landing_data_returns_summary_and_closes_manager():
    manager = Mock()
    manager.get_home_summary.return_value = {
        "total_jobs": 12,
        "total_users": 5,
        "total_functions": 3,
        "job_statuses": [{"status": "FINISHED:COMPLETED", "count": 12}],
        "user_roles": [{"role": "CLIENT", "count": 5}],
        "functions": [{"id": 1, "name": "MEAN", "description": "Mean"}],
    }

    with patch(
        "app.api.routes.LandingPageRoutes.LandingPageManager",
        return_value=manager,
    ):
        response = await get_home_landing_data(HomeLandingRequest(username="initiator"))

    result = body(response)
    assert response.status_code == 200
    assert result["status"] == "SUCCESS"
    assert result["home"]["total_jobs"] == 12
    manager.get_home_summary.assert_called_once_with("initiator")
    manager.complete.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_home_landing_data_returns_404_for_unknown_user():
    manager = Mock()
    manager.get_home_summary.return_value = None

    with patch(
        "app.api.routes.LandingPageRoutes.LandingPageManager",
        return_value=manager,
    ):
        response = await get_home_landing_data(HomeLandingRequest(username="missing"))

    assert response.status_code == 404
    assert body(response)["error"] == "User not found"
    manager.get_home_summary.assert_called_once_with("missing")
    manager.complete.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_project_landing_data_returns_project_summary_and_closes_manager():
    manager = Mock()
    manager.get_project_landing_summary.return_value = {
        "project": {"id": 2, "name": "General Statistics", "total_jobs": 28},
        "recent_jobs": [{"id": 37}],
        "function_usage_distribution": [
            {"functions": ["CHI_SQUARE_TEST"], "count": 2},
            {"functions": ["MEAN"], "count": 1},
        ],
    }

    with patch(
        "app.api.routes.LandingPageRoutes.LandingPageManager",
        return_value=manager,
    ):
        response = await get_project_landing_data(ProjectLandingRequest(project_id=2))

    result = body(response)
    assert response.status_code == 200
    assert result["status"] == "SUCCESS"
    assert result["project"]["id"] == 2
    assert result["recent_jobs"][0]["id"] == 37
    assert result["function_usage_distribution"][0] == {
        "functions": ["CHI_SQUARE_TEST"],
        "count": 2,
    }
    manager.get_project_landing_summary.assert_called_once_with(2)
    manager.complete.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_project_landing_data_returns_404_for_missing_project():
    manager = Mock()
    manager.get_project_landing_summary.return_value = None

    with patch(
        "app.api.routes.LandingPageRoutes.LandingPageManager",
        return_value=manager,
    ):
        response = await get_project_landing_data(ProjectLandingRequest(project_id=999))

    assert response.status_code == 404
    assert body(response)["error"] == "Project not found"
    manager.complete.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_home_landing_data_returns_500_and_still_closes_manager():
    manager = Mock()
    manager.get_home_summary.side_effect = RuntimeError("boom")

    with patch(
        "app.api.routes.LandingPageRoutes.LandingPageManager",
        return_value=manager,
    ):
        response = await get_home_landing_data(HomeLandingRequest(username="initiator"))

    assert response.status_code == 500
    assert body(response)["status"] == "FAILURE"
    manager.complete.assert_called_once_with()
