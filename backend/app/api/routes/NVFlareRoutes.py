"""
Routes for NVFlare job history and related lookups.
"""

import logging
import traceback
from fastapi import HTTPException, APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.aws.ResourceConfigProvider import ResourceConfigProvider
from app.core.job_runner.JobRunnerService import JobRunnerService
from app.core.mysql.managers.CryptoAuditManager import CryptoAudit, CryptoAuditManager
from app.core.mysql.managers.FunctionsManager import _normalize_functions_map
from app.core.mysql.managers.NVFlareClientEmitManager import NVFlareClientEmitManager
from app.core.mysql.managers.NVFlareJobsManager import NVFlareJobCreateDateDateFilterMode, NVFlareJobFunctionFilterMode, NVFlareJobsManager
from app.core.mysql.managers.ProjectsManager import ProjectsManager
from app.core.mysql.MySQLRetriever import MySQLRetriever
from app.core.mysql.managers.ThresholdManager import Threshold, ThresholdManager, ThresholdMethod

router = APIRouter()



@router.post("/nvflare/client/emit_progress", include_in_schema=False)
async def emit_progress(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = await request.body()

    # Password protection for non-local builds
    env = EnvironmentProvider.get_env()
    if env != Environment.LOCAL:
        pw = body.get("$pw", "")
        mysql_config = ResourceConfigProvider.get_mysql_config()
        password_string = mysql_config.password
        if pw != password_string:
            mysql_config = ResourceConfigProvider.get_mysql_config(check_cached=False)
            if pw != mysql_config.password:
                print(f"Bad password received: {pw}", flush=True)
                raise HTTPException(status_code=401, detail="Unauthorized")

    # build manager from NVFlare job_id sent by the webhook
    nvflare_job_id = body.get("job_id")
    mgr = NVFlareClientEmitManager(nvflare_job_id)

    try:
        # log a human-friendly message mapped from numeric codes
        mgr.log_progress_from_payload(body)

        return JSONResponse(content={"status": "ok"})
    finally:
        mgr.complete()

# Put behind bearer token
@router.post("/nvflare/jobs/history", include_in_schema=False)
async def fetch_nvFlare_job_history(payload: Request):
    print("NVFlareRoutes: /nvflare/job_history called", flush=True)
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

        function_names = body.get("function_names") or []

        raw_mode = str(body.get("filter_mode", "ANY")).strip().upper()
        match_mode = NVFlareJobFunctionFilterMode.ONLY if raw_mode == "ONLY" else NVFlareJobFunctionFilterMode.ANY

        date_filter = body.get("date_filter") or {}
        date_mode_raw = str(date_filter.get("mode", "")).strip().upper()
        date_value = date_filter.get("create_date")

        if date_mode_raw in {"ON", "BEFORE", "AFTER"} and isinstance(date_value, str) and date_value.strip():
            date_filter_mode = NVFlareJobCreateDateDateFilterMode(date_mode_raw)
            resolved_create_date = date_value
        else:
            date_filter_mode = None
            resolved_create_date = body.get("create_date")

        nvflare_jobs_manager = NVFlareJobsManager(status_writer=None, project_id=project_id)
        try:
            nvflare_jobs = nvflare_jobs_manager.get_nvflare_jobs(
                function_names=function_names,
                match_mode=match_mode,
                create_date=resolved_create_date,
                date_filter_mode=date_filter_mode,
            )
            print(f"NVFlareRoutes: /nvflare/job_history retrieved {len(nvflare_jobs)} jobs", flush=True)
        finally:
            nvflare_jobs_manager.complete()

        return JSONResponse(content={"status": "SUCCESS", "nvflare_jobs": nvflare_jobs}, status_code=200)

    except HTTPException:
        raise
    except Exception:
        logging.exception("Error while fetching NVFlare job history")
        print(f"NVFlareRoutes: /nvflare/job_history hit exception {traceback.format_exc().splitlines()}", flush=True)
        return JSONResponse(content={"status": "FAILURE", "error": "Internal error"}, status_code=500)


# Put behind bearer token
@router.post("/nvflare/jobs/results_context", include_in_schema=False)
async def fetch_nvflare_results_context(request: Request):
    """Return the metadata required to open ResultsPage from an NVFlare job ID."""
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if not isinstance(body, dict):
            body = {}

        nvflare_job_id = str(body.get("nvflare_job_id") or "").strip()
        if not nvflare_job_id:
            return JSONResponse(
                content={"status": "FAILURE", "error": "nvflare_job_id is required"},
                status_code=400,
            )

        jobs_manager = NVFlareJobsManager(status_writer=None)
        try:
            job = jobs_manager.get_nvflare_job_by_assigned_id(nvflare_job_id)
        finally:
            jobs_manager.complete()

        if job is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "NVFlare job not found"},
                status_code=404,
            )

        project_id = job.get("project_id")
        if project_id is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "NVFlare job does not reference a project"},
                status_code=500,
            )

        projects_manager = ProjectsManager()
        try:
            project = projects_manager.get_project(
                int(project_id),
                datasource_group_id=job.get("datasource_group_id"),
            )
        finally:
            projects_manager.complete()

        if project is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "Project for NVFlare job not found"},
                status_code=404,
            )

        filter_definition = None
        filter_id = job.get("filter_id")
        if filter_id is not None:
            retriever = MySQLRetriever()
            try:
                filter_definition = retriever.get_single_filter(int(filter_id))
            finally:
                retriever.complete()

        return JSONResponse(
            content=jsonable_encoder(
                {
                    "status": "SUCCESS",
                    "job": job,
                    "project": project,
                    "filter": filter_definition,
                }
            ),
            status_code=200,
        )

    except HTTPException:
        raise
    except Exception:
        logging.exception("Error while fetching NVFlare results context")
        return JSONResponse(
            content={"status": "FAILURE", "error": "Internal error"},
            status_code=500,
        )


# Put behind bearer token
@router.post("/nvflare/jobs/submit", include_in_schema=False)
async def submit_nvflare_job(request: Request):
    body = await request.json()

    print(f"NVFlareRoutes: submit_nvflare_job called with body: {body}", flush=True)

    filters = body.get("filters", "")
    if not filters:
        print("NVFlareRoutes: submit_nvflare_job missing filters in payload", flush=True)
        return JSONResponse(
            content={"status": "Submission must include filters"},
            status_code=400,
        )
    else:
        print(f"NVFlareRoutes: submit_nvflare_job received filters payload: {filters}", flush=True)

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

    raw_datasource_group_id = body.get("datasource_group")
    try:
        datasource_group_id = int(raw_datasource_group_id) if raw_datasource_group_id is not None else None
    except (TypeError, ValueError):
        return JSONResponse(
            content={"status": "FAILURE", "error": "datasource_group must be an integer when provided"},
            status_code=400,
        )

    functions_raw = body.get("functions_map")
    if functions_raw is None:
        return JSONResponse(
            content={"status": "Please provide functions"},
            status_code=400,
        )

    if not isinstance(functions_raw, dict):
        return JSONResponse(
            content={
                "status": "functions must be an object mapping function_id -> { args }"
            },
            status_code=400,
        )

    try:
        functions_map = _normalize_functions_map(functions_raw)
    except Exception:
        logging.exception("Failed to normalize functions map")
        return JSONResponse(
            content={"status": "Invalid functions payload"},
            status_code=400,
        )

    if not any(str(fid).strip() for fid in functions_map.keys()):
        return JSONResponse(
            content={"status": "functions must contain at least one function"},
            status_code=400,
        )

    workflow_group_data = body.get("workflow_group_data")
    if workflow_group_data is not None and not isinstance(workflow_group_data, dict):
        return JSONResponse(
            content={"status": "workflow_group_data must be an object when provided"},
            status_code=400,
        )

    def _normalize_client_name_list(field_name: str):
        raw_value = body.get(field_name)
        if raw_value is None:
            return []
        if not isinstance(raw_value, list):
            return None

        normalized = []
        for item in raw_value:
            if not isinstance(item, str):
                return None
            client_name = item.strip()
            if client_name and client_name not in normalized:
                normalized.append(client_name)
        return normalized

    non_contributing_clients = _normalize_client_name_list("non_contributing_clients")
    if non_contributing_clients is None:
        return JSONResponse(
            content={"status": "non_contributing_clients must be an array of strings when provided"},
            status_code=400,
        )

    exclude_analyzing_clients = _normalize_client_name_list("exclude_analyzing_clients")
    if exclude_analyzing_clients is None:
        return JSONResponse(
            content={"status": "exclude_analyzing_clients must be an array of strings when provided"},
            status_code=400,
        )

    print(
        f"NVFlareRoutes: submit_nvflare_job participation settings: "
        f"non_contributing_clients={non_contributing_clients}, "
        f"exclude_analyzing_clients={exclude_analyzing_clients}",
        flush=True,
    )

    threshold_config_raw = body.get("threshold_config")
    threshold: Threshold | None = None

    if isinstance(threshold_config_raw, dict):
        method_raw = (
            threshold_config_raw.get("thresholdMethod")
            or threshold_config_raw.get("method")
        )
        threshold_raw = threshold_config_raw.get("threshold")

        try:
            method = (
                ThresholdMethod(str(method_raw).upper())
                if method_raw is not None
                else ThresholdMethod.PROTECTED
            )
        except ValueError:
            return JSONResponse(
                content={"status": "Invalid threshold method"},
                status_code=400,
            )

        try:
            threshold_value = int(threshold_raw)
        except (TypeError, ValueError):
            return JSONResponse(
                content={"status": "Invalid threshold value"},
                status_code=400,
            )

        tm = ThresholdManager()
        try:
            threshold = tm.get_or_create(
                Threshold(id=None, method=method, threshold=threshold_value)
            )
        finally:
            tm.complete()

    submit_username = body.get("submitter")
    if not isinstance(submit_username, str) or not submit_username.strip():
        submit_username = None
    else:
        submit_username = submit_username.strip()

    service = JobRunnerService.get_instance()
    job_id = service.request_job_run(
        project_id,
        functions_map,
        filters,
        threshold,
        username=submit_username,
        datasource_group_id=datasource_group_id,
        workflow_group_data=workflow_group_data,
        non_contributing_clients=non_contributing_clients,
        exclude_analyzing_clients=exclude_analyzing_clients,
    )
    print(f"NVFlareRoutes: submit_nvflare_job enqueued job {job_id}", flush=True)

    return JSONResponse(
        content={"job_id": job_id, "status": "QUEUED"},
        status_code=200,
    )

# Put behind bearer token
@router.post("/nvflare/jobs/audit/submit", include_in_schema=False)
async def submit_audit(request: Request):
    print(f"NVFlareRoutes: submit_audit request recieved: {request}", flush=True)

    body = await request.json()

    env = EnvironmentProvider.get_env()
    if env != Environment.LOCAL:
        pw = body.get("$pw", "")
        mysql_config = ResourceConfigProvider.get_mysql_config()
        password_string = mysql_config.password
        if pw != password_string:
            mysql_config = ResourceConfigProvider.get_mysql_config(check_cached=False)
            if pw != mysql_config.password:
                print(f"NVFlareRoutes: submit_audit request recieved a bad password: {pw}", flush=True)
                raise HTTPException(status_code=401, detail="Unauthorized")

    required_fields = [
        "nvflare_job_id",
        "security_level",
        "ring_dimension",
        "batch_size",
        "scale_mod_size",
        "multiplicative_depth",
        "scaling_technique",
        "keyswitch_technique",
        "ckks_data_type",
        "ind_cpa_noise_bits",
    ]

    for field in required_fields:
        if body.get(field) in (None, "", []):
            print(f"NVFlareRoutes: submit_audit recieved missing request data: {field}", flush=True)
            return JSONResponse(content={"status": f"Please provide {field}"}, status_code=400)

    try:
        audit = CryptoAudit(
            nvflare_job_id=str(body["nvflare_job_id"]),
            security_level=str(body["security_level"]),
            ring_dimension=int(body["ring_dimension"]),
            batch_size=int(body["batch_size"]),
            scale_mod_size=int(body["scale_mod_size"]),
            multiplicative_depth=int(body["multiplicative_depth"]),
            scaling_technique=str(body["scaling_technique"]),
            keyswitch_technique=str(body["keyswitch_technique"]),
            ckks_data_type=str(body["ckks_data_type"]),
            ind_cpa_noise_bits=int(body["ind_cpa_noise_bits"]),
        )
    except Exception:
        logging.exception("Failed to parse crypto audit payload")
        return JSONResponse(
            content={"status": "Invalid crypto audit payload"},
            status_code=400,
        )

    ca_manager = CryptoAuditManager()
    try:
        recorded_id = ca_manager.log_audit(audit)

        if not recorded_id:
            print("NVFlareRoutes: Failed to persist crypto audit record.", flush=True)
            return JSONResponse(
                content={"status": "Failed to persist crypto audit record."},
                status_code=500,
            )

        print(
            f"NVFlareRoutes: Crypto audit successfully recorded with id {recorded_id}.",
            flush=True,
        )
        return JSONResponse(
            content={"status": "Crypto audit recorded", "id": recorded_id},
            status_code=200,
        )

    except Exception:
        print(
            f"NVFlareRoutes: submit_audit hit exception {traceback.format_exc().splitlines()}.",
            flush=True,
        )
        return JSONResponse(
            content={
                "status": "Exception occurred while recording crypto audit",
                "log": traceback.format_exc().splitlines(),
            },
            status_code=400,
        )
    finally:
        ca_manager.complete()
