"""Routes that provide the aggregate data used by the SHARE landing pages."""

import logging

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.mysql.managers.LandingPageManager import LandingPageManager


router = APIRouter(prefix="/landing")


class HomeLandingRequest(BaseModel):
    username: str


class ProjectLandingRequest(BaseModel):
    project_id: int


@router.post("/home", include_in_schema=False)
async def get_home_landing_data(request: HomeLandingRequest):
    """Return role-appropriate SHARE statistics for the Home landing page."""
    manager = LandingPageManager()
    try:
        data = manager.get_home_summary(request.username)
        if data is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "User not found"},
                status_code=404,
            )

        return JSONResponse(
            content=jsonable_encoder({"status": "SUCCESS", "home": data}),
            status_code=200,
        )
    except Exception:
        logging.exception(
            "Error while fetching SHARE Home landing data for username=%s",
            request.username,
        )
        return JSONResponse(
            content={"status": "FAILURE", "error": "Internal error"},
            status_code=500,
        )
    finally:
        manager.complete()


@router.post("/project", include_in_schema=False)
async def get_project_landing_data(request: ProjectLandingRequest):
    """Return one project's summary, function usage, and five most recent jobs."""
    manager = LandingPageManager()
    try:
        data = manager.get_project_landing_summary(request.project_id)
        if data is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "Project not found"},
                status_code=404,
            )

        return JSONResponse(
            content=jsonable_encoder({"status": "SUCCESS", **data}),
            status_code=200,
        )
    except Exception:
        logging.exception(
            "Error while fetching project landing data for project_id=%s",
            request.project_id,
        )
        return JSONResponse(
            content={"status": "FAILURE", "error": "Internal error"},
            status_code=500,
        )
    finally:
        manager.complete()
