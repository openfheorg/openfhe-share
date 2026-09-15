from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import math
import os
import traceback

from app.NVFlareJobsDataRetriever import NVFlareJobsDataRetriever
from app.SupportedFunction import SupportedFunction

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


app = FastAPI(title="Duality Client Agent", version="0.1.0")

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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "site": (os.getenv("DUALITY_CLIENT_SITE") or "").strip() or None,
    }


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
