"""
Routes for managing filter retrieval.
"""

import logging
import traceback
from fastapi import HTTPException, Request, APIRouter
from fastapi.responses import JSONResponse

from app.api.models.FunctionBasedRequest import FunctionBasedRequest
from app.core.mysql.MySQLRetriever import MySQLRetriever
from app.core.mysql.managers.FunctionsManager import FunctionsManager


router = APIRouter()

# Put behind bearer token
@router.post("/filters/fetch_single_filter", include_in_schema=False)
async def fetch_single_filter(request: Request):
    print("NVFlareRoutes: fetch_single_filter called", flush=True)
    # Submits a survivability analysis job. Expects a filters object in the body.
    body = await request.json()
    filter_id = body.get("filter_id", "")

    if not filter_id:
        print("NVFlareRoutes: fetch_single_filter missing filter_id in body", flush=True)
        return JSONResponse(content={"status": "Submission must include filter_id"}, status_code=400)

    try:
        filter_id = int(filter_id)   # ensure it's an int
    except (TypeError, ValueError):
        return JSONResponse(content={"status": "filter_id must be an integer"}, status_code=400)

    print(f"NVFlareRoutes: fetch_single_filter called with payload={body}", flush=True)
    try:
        retriever = MySQLRetriever()
        try:
            single_filter = retriever.get_single_filter(filter_id)
            print(f"NVFlareRoutes: fetch_single_filter retrieved {single_filter}", flush=True)
        finally:
            retriever.complete()

        return JSONResponse(content={"status": "SUCCESS", "filter": single_filter}, status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error while fetching single filter for {filter_id}")
        print(f"NVFlareRoutes: fetch_single_filter hit exception {traceback.format_exc().splitlines()}", flush=True)
        return JSONResponse(content={"status": "FAILURE", "error": str(e)}, status_code=500)

# Put behind bearer token
@router.post("/filters/fetch_filters", include_in_schema=False)
async def fetch_filters(payload: Request):
    print(f"NVFlareRoutes: fetch_filters called", flush=True)
    try:
        try:
            body = await payload.json()
        except Exception:
            body = {}

        raw_project_id = body.get("project_id")
        try:
            project_id = int(raw_project_id) if raw_project_id is not None else None
        except (TypeError, ValueError):
            project_id = None

        if project_id is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "project_id is required"},
                status_code=400,
            )

        retriever = MySQLRetriever()
        try:
            filters = retriever.get_all_filters(project_id=project_id)
            print(f"NVFlareRoutes: fetch_filters retrieved {len(filters)} filters", flush=True)
        finally:
            retriever.complete()

        return JSONResponse(content={"status": "SUCCESS", "filters": filters}, status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error while fetching filters")
        print(f"NVFlareRoutes: fetch_filters hit exception {traceback.format_exc().splitlines()}", flush=True)
        return JSONResponse(content={"status": "FAILURE", "error": str(e)}, status_code=500)
