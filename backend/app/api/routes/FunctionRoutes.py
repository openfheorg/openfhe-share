"""
Routes for supported functions and function submissions.
"""

import logging
import traceback
from fastapi import HTTPException, Request, APIRouter
from fastapi.responses import JSONResponse

from app.core.mysql.managers.FunctionsManager import FunctionsManager

router = APIRouter()

# Function arg spec for server-side defaulting / light validation.
# Values remain strings; missing/blank inputs fall back to defaults.


@router.post("/functions/supported_functions", include_in_schema=False)
async def fetch_supported_functions(_request: Request):
    print("NVFlareRoutes: fetch_supported_functions called", flush=True)
    # Returns the list of functions the system currently supports.
    try:
        functions_manager = FunctionsManager()
        try:
            functions = functions_manager.get_supported_functions()
            print(f"NVFlareRoutes: fetch_supported_functions found {len(functions)} functions", flush=True)
        finally:
            functions_manager.complete()

        return JSONResponse(content={"status": "SUCCESS", "functions": functions}, status_code=200)
    except HTTPException:
        raise
    except Exception:
        logging.exception("Error while fetching supported functions")
        print(f"NVFlareRoutes: fetch_supported_functions hit exception {traceback.format_exc().splitlines()}", flush=True)
        return JSONResponse(content={"status": "FAILURE", "error": "Internal error"}, status_code=500)

