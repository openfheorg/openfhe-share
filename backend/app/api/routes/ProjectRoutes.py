"""
Routes for listing NVFlare projects and related functions
"""

from urllib.parse import urljoin

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.mysql.managers.ProjectsManager import ProjectsManager
from app.core.mysql.managers.UsersManager import UsersManager


#convert object into dict:
from fastapi.encoders import jsonable_encoder

router = APIRouter()


class ProjectFHIRSourceRequest(BaseModel):
    username: str
    project_id: int
    datasource_group: int | None = None
    execute_query: str | None = None


@router.post("/projects/list", include_in_schema=False)
async def get_projects_list():
    manager = ProjectsManager()
    users_manager = UsersManager()
    try:
        projects = jsonable_encoder(manager.get_project_list())
        model_file_settings_by_project_id = users_manager.get_project_model_file_settings_enabled_map()

        for project in projects:
            project_id = project.get("id") or project.get("project_id")
            try:
                project_id_int = int(project_id)
            except (TypeError, ValueError):
                project_id_int = None

            project["model_file_settings_enabled"] = bool(
                model_file_settings_by_project_id.get(
                    project_id_int,
                    project.get("model_file_settings_enabled", False),
                )
            )

        return JSONResponse(content={"projects": projects})
    finally:
        users_manager.complete()
        manager.complete()


@router.post("/projects/fhir/source", include_in_schema=False)
async def get_project_fhir_source(request: ProjectFHIRSourceRequest):
    users_manager = UsersManager()
    project_manager = ProjectsManager()
    try:
        user_id = users_manager.get_user_id_by_username(request.username)
        if user_id is None:
            return JSONResponse(
                status_code=404,
                content={"message": f"User not found for username [{request.username}]"}
            )

        source_record = users_manager.get_fhir_source_record(
            user_id=user_id,
            project_id=request.project_id,
            datasource_group=request.datasource_group
        )
        if not source_record:
            return JSONResponse(
                status_code=404,
                content={
                    "message": (
                        f"No FHIR source found for username [{request.username}] "
                        f"project_id [{request.project_id}] "
                        f"and datasource_group [{request.datasource_group}]"
                    )
                }
            )

        source = source_record["source"]

        datasource_group_details = project_manager.get_project_datasource_group_summary(request.project_id)

        response_payload = {
            "username": request.username,
            "user_id": user_id,
            "project_id": request.project_id,
            "source": source,
            "source_type": "json" if source.lower().endswith(".json") else "fhir_server",
            "datasource_group": source_record["datasource_group"],
            "datasource_group_name": source_record["datasource_group_name"],
            "is_default_group": source_record["is_default_group"],
            "datasource_groups_defined": datasource_group_details["datasource_groups_defined"],
            "datasource_groups": datasource_group_details["datasource_groups"],
            "default_datasource_group": datasource_group_details["default_datasource_group"],
        }

        if request.execute_query:
            if source.lower().endswith(".json"):
                response_payload["query_executed"] = False
                response_payload["query_execution_message"] = "Query execution skipped because source is a json file."
            else:
                query_path = request.execute_query.strip()
                if not query_path.startswith("/"):
                    query_path = f"/{query_path}"

                base_source = source.rstrip("/") + "/"
                full_url = urljoin(base_source, query_path.lstrip("/"))

                upstream_response = requests.get(
                    full_url,
                    headers={"Accept": "application/fhir+json, application/json"},
                    timeout=60
                )

                response_payload["query_executed"] = True
                response_payload["executed_url"] = full_url
                response_payload["query_status_code"] = upstream_response.status_code

                try:
                    response_payload["query_results"] = upstream_response.json()
                except ValueError:
                    response_payload["query_results"] = upstream_response.text

        return JSONResponse(content=jsonable_encoder(response_payload))
    finally:
        project_manager.complete()
        users_manager.complete()


#Add project/ Remove project endpoints going to be needed here