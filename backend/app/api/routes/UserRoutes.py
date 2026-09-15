from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.mysql.managers.UsersManager import UsersManager

router = APIRouter(prefix="/user")

class UserLookupRequest(BaseModel):
    username: str

class UserDatasourceUpdate(BaseModel):
    project_id: int
    source: str
    datasource_group_id: int | None = None

class UserDatasourceApplyRequest(BaseModel):
    username: str | None = None
    user_id: int | None = None
    updates: list[UserDatasourceUpdate]

class UserModelFilesRequest(BaseModel):
    username: str | None = None
    user_id: int | None = None
    project_id: int


class UserModelFileAvailabilityRequest(BaseModel):
    username: str | None = None
    user_id: int | None = None
    project_id: int
    datasource_group_id: int | None = None
    model_file_lookup_key: str
    model_file_lookup_value: str
    model_keys: list[str] | None = None
    required_artifact_types: list[str] | None = None

class UserModelFileUpdate(BaseModel):
    project_id: int
    source: str
    datasource_group_id: int | None = None
    model_file_lookup_key: str
    model_file_lookup_value: str
    model_key: str
    artifact_type: str

class UserModelFileApplyRequest(BaseModel):
    username: str | None = None
    user_id: int | None = None
    updates: list[UserModelFileUpdate]


def normalize_datasource_source(source: str):
    value = (source or "").strip()

    if not value:
        raise ValueError("Datasource source is required")

    lower_value = value.lower()

    if lower_value.startswith(("http://", "https://")):
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)

        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("FHIR datasource must be a valid http or https URL")

        if not normalized.lower().endswith("/fhir"):
            raise ValueError("FHIR datasource URL must end with /fhir")

        return normalized

    if not lower_value.endswith(".json"):
        raise ValueError("JSON datasource path must end with .json")

    return value


def normalize_model_file_source(source: str):
    value = (source or "").strip()
    if not value:
        raise ValueError("Model file source is required")
    return value


def _resolve_user_id(manager: UsersManager, user_id: int | None, username: str | None):
    if user_id is not None:
        return user_id
    if username:
        return manager.get_user_id_by_username(username)
    return None


@router.post("/role")
def get_user_role(request: UserLookupRequest):
    manager = UsersManager()
    try:
        role_name = manager.validate_login(request.username)
        if not role_name:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        user_id = manager.get_user_id_by_username(request.username)
        projects = manager.get_user_project_datasources(user_id) if user_id is not None else []

        try:
            client = (
                manager.get_nvflare_client_for_user(user_id)
                if user_id is not None
                else None
            )
        except ValueError as e:
            return JSONResponse(status_code=409, content={"error": str(e)})

        return {
            "username": request.username,
            "role": role_name,
            "user_id": user_id,
            "projects": projects,
            "client_id": client.get("client_id") if client else None,
            "client_name": client.get("client_name") if client else None,
        }
    finally:
        manager.complete()


@router.post("/datasource/apply")
def apply_user_datasource_update(request: UserDatasourceApplyRequest):
    if request.user_id is None and not request.username:
        return JSONResponse(status_code=400, content={"error": "user_id or username is required"})

    if not request.updates:
        return JSONResponse(status_code=400, content={"error": "At least one datasource update is required"})

    manager = UsersManager()
    try:
        user_id = _resolve_user_id(manager, request.user_id, request.username)

        if user_id is None:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        created_datasources = []
        for update in request.updates:
            try:
                source = normalize_datasource_source(update.source)
                created_datasource = manager.create_user_project_datasource(
                    user_id=user_id,
                    project_id=update.project_id,
                    source=source,
                    datasource_group=update.datasource_group_id,
                )
                created_datasources.append(created_datasource)
            except ValueError as e:
                manager.rollback()
                return JSONResponse(status_code=400, content={"error": str(e)})

        manager.commit()
        projects = manager.get_user_project_datasources(user_id)

        return {
            "user_id": user_id,
            "created_datasources": created_datasources,
            "projects": projects,
        }
    finally:
        manager.complete()


@router.post("/model-files/list")
def list_user_model_file_sources(request: UserModelFilesRequest):
    if request.user_id is None and not request.username:
        return JSONResponse(status_code=400, content={"error": "user_id or username is required"})

    manager = UsersManager()
    try:
        user_id = _resolve_user_id(manager, request.user_id, request.username)
        if user_id is None:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        try:
            model_file_sources = manager.get_user_project_model_file_sources(
                user_id=user_id,
                project_id=request.project_id,
            )
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

        return model_file_sources
    finally:
        manager.complete()


@router.post("/model-files/availability")
def get_user_model_file_availability(request: UserModelFileAvailabilityRequest):
    if request.user_id is None and not request.username:
        return JSONResponse(status_code=400, content={"error": "user_id or username is required"})

    manager = UsersManager()
    try:
        user_id = _resolve_user_id(manager, request.user_id, request.username)
        if user_id is None:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        try:
            return manager.get_model_file_availability(
                user_id=user_id,
                project_id=request.project_id,
                datasource_group=request.datasource_group_id,
                model_file_lookup_key=request.model_file_lookup_key,
                model_file_lookup_value=request.model_file_lookup_value,
                model_keys=request.model_keys,
                required_artifact_types=request.required_artifact_types,
            )
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        manager.complete()


@router.post("/model-files/apply")
def apply_user_model_file_sources(request: UserModelFileApplyRequest):
    if request.user_id is None and not request.username:
        return JSONResponse(status_code=400, content={"error": "user_id or username is required"})

    if not request.updates:
        return JSONResponse(status_code=400, content={"error": "At least one model file update is required"})

    manager = UsersManager()
    try:
        user_id = _resolve_user_id(manager, request.user_id, request.username)
        if user_id is None:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        updated_records = []
        affected_project_ids = []

        for update in request.updates:
            try:
                source = normalize_model_file_source(update.source)
                updated_record = manager.upsert_user_project_model_file_source(
                    user_id=user_id,
                    project_id=update.project_id,
                    datasource_group=update.datasource_group_id,
                    model_file_lookup_key=update.model_file_lookup_key,
                    model_file_lookup_value=update.model_file_lookup_value,
                    model_key=update.model_key,
                    artifact_type=update.artifact_type,
                    source=source,
                )
                updated_records.append(updated_record)
                if update.project_id not in affected_project_ids:
                    affected_project_ids.append(update.project_id)
            except ValueError as e:
                manager.rollback()
                return JSONResponse(status_code=400, content={"error": str(e)})

        manager.commit()

        model_file_sources_by_project = {}
        for project_id in affected_project_ids:
            model_file_sources_by_project[str(project_id)] = manager.get_user_project_model_file_sources(
                user_id=user_id,
                project_id=project_id,
            )

        return {
            "user_id": user_id,
            "updated_model_files": updated_records,
            "model_file_sources_by_project": model_file_sources_by_project,
        }
    finally:
        manager.complete()
