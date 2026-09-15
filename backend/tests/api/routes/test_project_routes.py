import json
from unittest.mock import Mock, patch

import pytest

from app.api.routes.ProjectRoutes import (
    ProjectFHIRSourceRequest,
    get_project_fhir_source,
    get_projects_list,
)


def body(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_get_projects_list_applies_model_file_feature_map_and_closes():
    projects = Mock()
    projects.get_project_list.return_value = [
        {"id": 1, "model_file_settings_enabled": False},
        {"project_id": "2", "model_file_settings_enabled": True},
    ]
    users = Mock()
    users.get_project_model_file_settings_enabled_map.return_value = {1: True, 2: False}
    with patch("app.api.routes.ProjectRoutes.ProjectsManager", return_value=projects), patch(
        "app.api.routes.ProjectRoutes.UsersManager", return_value=users
    ):
        response = await get_projects_list()
    result = body(response)["projects"]
    assert result[0]["model_file_settings_enabled"] is True
    assert result[1]["model_file_settings_enabled"] is False
    users.complete.assert_called_once()
    projects.complete.assert_called_once()


@pytest.mark.asyncio
async def test_get_project_fhir_source_returns_404_for_unknown_user():
    users = Mock()
    users.get_user_id_by_username.return_value = None
    projects = Mock()
    with patch("app.api.routes.ProjectRoutes.UsersManager", return_value=users), patch(
        "app.api.routes.ProjectRoutes.ProjectsManager", return_value=projects
    ):
        response = await get_project_fhir_source(
            ProjectFHIRSourceRequest(username="missing", project_id=1)
        )
    assert response.status_code == 404
    users.complete.assert_called_once()
    projects.complete.assert_called_once()


@pytest.mark.asyncio
async def test_get_project_fhir_source_skips_query_for_json_source():
    users = Mock()
    users.get_user_id_by_username.return_value = 5
    users.get_fhir_source_record.return_value = {
        "source": "/data/site.json",
        "datasource_group": 2,
        "datasource_group_name": "Group 2",
        "is_default_group": False,
    }
    projects = Mock()
    projects.get_project_datasource_group_summary.return_value = {
        "datasource_groups_defined": True,
        "datasource_groups": [{"id": 2}],
        "default_datasource_group": 1,
    }
    with patch("app.api.routes.ProjectRoutes.UsersManager", return_value=users), patch(
        "app.api.routes.ProjectRoutes.ProjectsManager", return_value=projects
    ), patch("app.api.routes.ProjectRoutes.requests.get") as request_get:
        response = await get_project_fhir_source(
            ProjectFHIRSourceRequest(
                username="user", project_id=1, datasource_group=2, execute_query="Patient"
            )
        )
    result = body(response)
    assert result["source_type"] == "json"
    assert result["query_executed"] is False
    request_get.assert_not_called()


@pytest.mark.asyncio
async def test_get_project_fhir_source_executes_remote_query():
    users = Mock()
    users.get_user_id_by_username.return_value = 5
    users.get_fhir_source_record.return_value = {
        "source": "https://fhir.example/base/fhir",
        "datasource_group": 1,
        "datasource_group_name": "Default",
        "is_default_group": True,
    }
    projects = Mock()
    projects.get_project_datasource_group_summary.return_value = {
        "datasource_groups_defined": False,
        "datasource_groups": [],
        "default_datasource_group": 1,
    }
    upstream = Mock(status_code=200)
    upstream.json.return_value = {"resourceType": "Bundle"}
    with patch("app.api.routes.ProjectRoutes.UsersManager", return_value=users), patch(
        "app.api.routes.ProjectRoutes.ProjectsManager", return_value=projects
    ), patch("app.api.routes.ProjectRoutes.requests.get", return_value=upstream) as request_get:
        response = await get_project_fhir_source(
            ProjectFHIRSourceRequest(username="user", project_id=1, execute_query="Patient?_count=1")
        )
    result = body(response)
    assert result["query_executed"] is True
    assert result["executed_url"] == "https://fhir.example/base/fhir/Patient?_count=1"
    request_get.assert_called_once()
