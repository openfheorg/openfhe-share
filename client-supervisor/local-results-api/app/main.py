from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import math
import os
import traceback

from app.NVFlareJobsDataRetriever import NVFlareJobsDataRetriever
from app.SupportedFunction import SupportedFunction

LOGGER = logging.getLogger("uvicorn.error")

def _parse_origins(val: str):
    val = (val or "").strip()
    if not val:
        return []
    parts = [p.strip() for p in val.split(",")]
    return [p for p in parts if p]

def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _job_save_location() -> str:
    explicit = (os.getenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION") or "").strip()
    if explicit:
        return explicit
    workspace = (os.getenv("DUALITY_NVFLARE_WORKSPACE") or "/nvflare").strip() or "/nvflare"
    return os.path.join(workspace, "job-results")


def _job_save_location_status() -> dict:
    path = _job_save_location()
    exists = os.path.isdir(path)
    try:
        entries = sorted(os.listdir(path))[:25] if exists else []
    except Exception as exc:
        entries = [f"<unreadable: {exc}>"]
    return {
        "workspace": (os.getenv("DUALITY_NVFLARE_WORKSPACE") or "/nvflare").strip() or "/nvflare",
        "job_save_location": path,
        "job_save_location_exists": exists,
        "job_save_location_entries": entries,
    }

app = FastAPI(title="SHARE Client Results API", version="0.2.0")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://api.example.org",
    "https://app.example.org",
    "https://dev-app.example.org",
    "https://api.example.org",
]
for origin in _parse_origins(os.getenv("DUALITY_UI_ORIGINS", "")):
    if origin not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
    max_age=86400,
)


@app.on_event("startup")
def log_startup_config():
    cfg = _job_save_location_status()
    LOGGER.info("startup config")
    LOGGER.info("DUALITY_NVFLARE_WORKSPACE=%s", cfg["workspace"])
    LOGGER.info("DUALITY_NVFLARE_JOB_SAVE_LOCATION=%s", cfg["job_save_location"])
    LOGGER.info("job_save_location_exists=%s", cfg["job_save_location_exists"])


@app.get("/health")
def health():
    payload = {
        "status": "ok",
        "site": (os.getenv("DUALITY_CLIENT_SITE") or "").strip() or None,
    }
    payload.update(_job_save_location_status())
    return payload


@app.post("/jobs/results", include_in_schema=False)
async def get_job_results_by_nvflare_id(request: Request):
    body = await request.json()
    nvflare_job_id = body.get("nvflare_job_id")
    function_name = body.get("function")
    workflow_id = body.get("workflow_id")

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    if not function_name:
        return JSONResponse({"error": "function is required."}, status_code=400)
    if not workflow_id:
        return JSONResponse({"error": "workflow_id is required."}, status_code=400)

    function_enum = SupportedFunction.from_name(function_name)
    if function_enum is None:
        return JSONResponse({"error": f"Unsupported function '{function_name}'"}, status_code=400)

    try:
        cfg = _job_save_location_status()
        LOGGER.info(
            "/jobs/results nvflare_job_id=%s function=%s workflow_id=%s job_save_location=%s exists=%s",
            nvflare_job_id,
            function_name,
            workflow_id,
            cfg["job_save_location"],
            cfg["job_save_location_exists"],
        )
        retriever = NVFlareJobsDataRetriever(nvflare_job_id, function_enum)
        job_data, function_config = retriever.retrieve_workflow_data_with_config(workflow_id)
        payload = _json_safe({"job_data": job_data, "function_config": function_config})
        return JSONResponse(payload)
    except Exception:
        return JSONResponse(
            content={"error": f"Failed to fetch workflow data: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )


@app.post("/jobs/results/mapping", include_in_schema=False)
async def get_job_results_mapping(request: Request):
    body = await request.json()
    nvflare_job_id = body.get("nvflare_job_id")
    function_name = body.get("function")

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    if not function_name:
        return JSONResponse({"error": "function is required."}, status_code=400)

    function_enum = SupportedFunction.from_name(function_name)
    if function_enum is None:
        return JSONResponse({"error": f"Unsupported function '{function_name}'"}, status_code=400)

    try:
        cfg = _job_save_location_status()
        LOGGER.info(
            "/jobs/results/mapping nvflare_job_id=%s function=%s job_save_location=%s exists=%s",
            nvflare_job_id,
            function_name,
            cfg["job_save_location"],
            cfg["job_save_location_exists"],
        )
        retriever = NVFlareJobsDataRetriever(nvflare_job_id=nvflare_job_id, function=function_enum)
        workflow_dirs = retriever.list_workflow_dirs()
        profile_summary = retriever.get_profile_summary()

        payload = {"workflow_dirs": workflow_dirs}
        if profile_summary:
            payload["profile_summary"] = _json_safe(profile_summary)

        return JSONResponse(payload)
    except Exception:
        return JSONResponse(
            {"error": f"Failed to fetch mapping: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )
