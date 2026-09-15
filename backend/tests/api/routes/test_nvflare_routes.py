import json
from unittest.mock import Mock, patch

import pytest

from app.api.routes.NVFlareRoutes import fetch_nvflare_results_context


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
@pytest.mark.parametrize("payload", [{}, {"nvflare_job_id": "   "}, []])
async def test_results_context_requires_nvflare_job_id(payload):
    response = await fetch_nvflare_results_context(RequestStub(payload))

    assert response.status_code == 400
    assert body(response) == {
        "status": "FAILURE",
        "error": "nvflare_job_id is required",
    }


@pytest.mark.asyncio
async def test_results_context_returns_job_project_and_filter_and_closes_managers():
    job = {
        "id": 41,
        "project_id": 7,
        "nvflare_assigned_id": "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3",
        "filter_id": 12,
        "datasource_group_id": 3,
        "datasource_group_name": "MSKChord",
        "status": "FINISHED:COMPLETED",
        "functions": ["EXCEPTIONAL_RESPONSE_DISCRIMINATION"],
    }
    project = {
        "id": 7,
        "name": "Biomarker Model Validation for Cancer Prognosis",
    }
    filter_definition = {
        "id": 12,
        "name": "Bladder Cancer",
        "conditions": [],
    }

    jobs_manager = Mock()
    jobs_manager.get_nvflare_job_by_assigned_id.return_value = job
    projects_manager = Mock()
    projects_manager.get_project.return_value = project
    retriever = Mock()
    retriever.get_single_filter.return_value = filter_definition

    with patch(
        "app.api.routes.NVFlareRoutes.NVFlareJobsManager",
        return_value=jobs_manager,
    ) as jobs_manager_cls, patch(
        "app.api.routes.NVFlareRoutes.ProjectsManager",
        return_value=projects_manager,
    ) as projects_manager_cls, patch(
        "app.api.routes.NVFlareRoutes.MySQLRetriever",
        return_value=retriever,
    ) as retriever_cls:
        response = await fetch_nvflare_results_context(
            RequestStub({"nvflare_job_id": f"  {job['nvflare_assigned_id']}  "})
        )

    assert response.status_code == 200
    assert body(response) == {
        "status": "SUCCESS",
        "job": job,
        "project": project,
        "filter": filter_definition,
    }

    jobs_manager_cls.assert_called_once_with(status_writer=None)
    jobs_manager.get_nvflare_job_by_assigned_id.assert_called_once_with(
        job["nvflare_assigned_id"]
    )
    jobs_manager.complete.assert_called_once_with()

    projects_manager_cls.assert_called_once_with()
    projects_manager.get_project.assert_called_once_with(
        7,
        datasource_group_id=3,
    )
    projects_manager.complete.assert_called_once_with()

    retriever_cls.assert_called_once_with()
    retriever.get_single_filter.assert_called_once_with(12)
    retriever.complete.assert_called_once_with()


@pytest.mark.asyncio
async def test_results_context_returns_404_when_job_is_not_found():
    jobs_manager = Mock()
    jobs_manager.get_nvflare_job_by_assigned_id.return_value = None

    with patch(
        "app.api.routes.NVFlareRoutes.NVFlareJobsManager",
        return_value=jobs_manager,
    ), patch("app.api.routes.NVFlareRoutes.ProjectsManager") as projects_manager_cls:
        response = await fetch_nvflare_results_context(
            RequestStub({"nvflare_job_id": "missing-job"})
        )

    assert response.status_code == 404
    assert body(response) == {
        "status": "FAILURE",
        "error": "NVFlare job not found",
    }
    jobs_manager.complete.assert_called_once_with()
    projects_manager_cls.assert_not_called()


@pytest.mark.asyncio
async def test_results_context_skips_filter_lookup_when_job_has_no_filter():
    job = {
        "id": 41,
        "project_id": 7,
        "nvflare_assigned_id": "job-without-filter",
        "filter_id": None,
        "datasource_group_id": None,
        "functions": ["MEAN"],
    }
    project = {"id": 7, "name": "Project"}

    jobs_manager = Mock()
    jobs_manager.get_nvflare_job_by_assigned_id.return_value = job
    projects_manager = Mock()
    projects_manager.get_project.return_value = project

    with patch(
        "app.api.routes.NVFlareRoutes.NVFlareJobsManager",
        return_value=jobs_manager,
    ), patch(
        "app.api.routes.NVFlareRoutes.ProjectsManager",
        return_value=projects_manager,
    ), patch("app.api.routes.NVFlareRoutes.MySQLRetriever") as retriever_cls:
        response = await fetch_nvflare_results_context(
            RequestStub({"nvflare_job_id": "job-without-filter"})
        )

    assert response.status_code == 200
    assert body(response) == {
        "status": "SUCCESS",
        "job": job,
        "project": project,
        "filter": None,
    }
    projects_manager.get_project.assert_called_once_with(
        7,
        datasource_group_id=None,
    )
    retriever_cls.assert_not_called()
