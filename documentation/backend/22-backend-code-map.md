# Backend Code Map

## Top-Level Backend

| Path | Area |
| --- | --- |
| `backend/app/main.py` | FastAPI app startup and top-level routes. |
| `backend/app/api/` | API route registration, request models, and endpoint modules. |
| `backend/app/core/` | Core backend services and integrations. |
| `backend/documents/` | Reference documents. |
| `backend/tests/` | Unit test suite mirroring `app/`; `tests/api/` and `tests/core/` use mocked managers and fake connections/cursors. |
| `backend/Dockerfile` | Container build. |
| `backend/pytest.ini` | Pytest config: `testpaths = tests`, `python_files = test_*.py`, `addopts = -ra`, and the `integration` marker for tests requiring external services or a full NVFlare runtime. |
| `backend/requirements.txt` | Python dependencies. |
| `backend/requirements-dev.txt` | Test dependencies: `requirements.txt` plus `pytest` and `pytest-asyncio`. |

Run the unit suite from the backend root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The simulator/integration tests under `app/core/job_runner/nvflare_jobs/tests/` are separate and are not collected by `pytest.ini`.

## API Code Map

| Path | Area |
| --- | --- |
| `app/api/AppRoutes.py` | Registers route modules. |
| `app/api/models/FunctionBasedRequest.py` | Function-based request model. |
| `app/api/routes/ClientRoutes.py` | Client connection, participation, and trusted NVFlare server datasource lookup endpoints. |
| `app/api/routes/FilterRoutes.py` | Filter endpoints. |
| `app/api/routes/FunctionRoutes.py` | Function endpoints. |
| `app/api/routes/JobRunnerRoutes.py` | Job status/result endpoints. |
| `app/api/routes/NVFlareRoutes.py` | NVFlare job/progress/history/audit endpoints. |
| `app/api/routes/ProjectRoutes.py` | Full project and datasource endpoints. |
| `app/api/routes/LandingPageRoutes.py` | Optimized global Home and project landing summary endpoints. |
| `app/api/routes/UserRoutes.py` | User role/session and user datasource settings endpoints. |

## Core Code Map

| Path | Area |
| --- | --- |
| `app/core/EnvironmentManager.py` | Environment handling. |
| `app/core/aws/` | AWS config/secrets helpers. |
| `app/core/mysql/` | MySQL connection, schema, managers, and job tracking. |
| `app/core/job_runner/` | Job service, tasks, and NVFlare job orchestration. |
| `app/core/nvflare/` | NVFlare admin/server/client helper layer. |
| `app/core/ssh/` | SSH helper layer. |

## MySQL Manager Map

| File | Area |
| --- | --- |
| `CryptoAuditManager.py` | Crypto audit. |
| `FiltersManager.py` | Filters. |
| `FunctionsManager.py` | Functions. |
| `NVFlareClientEmitManager.py` | Client progress emission. |
| `NVFlareJobsManager.py` | NVFlare job records/history/results. |
| `ParticipationManager.py` | Participation. |
| `ProjectsManager.py` | Full project definitions/datasources. |
| `LandingPageManager.py` | Read-only Home/project landing aggregates and five-job summaries. |
| `RolesManager.py` | Roles. |
| `ThresholdManager.py` | Thresholds. |
| `UsersManager.py` | Users, role lookup, NVFlare client-to-user lookup, current datasource lookup, and datasource update persistence. |

## NVFlare Job Code Map

| Path | Area |
| --- | --- |
| `NVFlareJobStager.py` | Job staging/artifact creation. |
| `NVFlareJobUploader.py` | Job upload. |
| `NVFlareJobRunner.py` | Job run/submit behavior. |
| `NVFlareJobMonitor.py` | Job monitoring. |
| `taskflow_report.py` | Host-side, post-run renderer that merges the per-party `trace.jsonl` streams for one job into a causal graph and writes Perfetto/Mermaid/Graphviz/round/timeline/index artifacts. Best-effort and idempotent; never raises. |
| `apis/` | Runtime modules packaged into jobs. |
| `apis/trace_filter.py` | `TraceCorrelationFilter`, registered in the server's `task_data_filters`. Stamps a correlation id onto each outbound task header and appends a matching `dispatch_msg` record to `trace_filter.jsonl` so server dispatch and client receipt pair exactly. Pure pass-through; swallows all errors. |
| `apis/fhir/` | FHIR/local data filtering and analysis engines. |
| `jobs/configs/` | Job config examples. |
| `jobs/nvflare_job_template/` | Main job template. |
| `jobs/participation_confirmation/` | Participation confirmation template. |
| `scripts/` | Simulation, parsing, profiling, helpers. |
| `wheels/` | CI wheel builder for the published `duality_nvflare_lib` package. |
| `workflows/` | Custom NVFlare workflows. |

## Starting Points by Task

| Task | Start with |
| --- | --- |
| Add or change an endpoint | `app/api/routes/`, then `04-api-endpoints.md` |
| Change user/role behavior | `UsersManager.py`, `RolesManager.py`, `08-users-roles-projects-and-datasources.md` |
| Change project datasource behavior | `ProjectRoutes.py`, `ProjectsManager.py`, `UsersManager.py` |
| Change Home/project landing summary data | `LandingPageRoutes.py`, `LandingPageManager.py`, `MySQLConnectionProvider.py`, `24-landing-page-summary-endpoints.md` |
| Change runtime datasource lookup | `ClientRoutes.py`, `UserRoutes.py`, `UsersManager.py`, `FHIRBaseConfigResolver.py`, `jobs/nvflare_job_template/app_server/custom/datasource_request_receiver.py`, `23-runtime-datasource-resolution-and-user-settings.md` |
| Change supported functions | `FunctionsManager.py`, `SupportedFunction.py`, initialization code |
| Change filters | `FilterRoutes.py`, `FiltersManager.py`, `SupportedFilterSystem.py` |
| Change job submission behavior | `NVFlareRoutes.py`, `JobRunnerService.py`, `NVFlareJobTask.py` |
| Change job staging | `NVFlareJobStager.py`, job templates/configs |
| Change participation | `ClientRoutes.py`, `ParticipationManager.py`, `NVFlareParticipationJobTask.py` |
| Change status/results | `JobRunnerRoutes.py`, job tracking classes, `NVFlareJobsManager.py` |
| Change FHIR filtering | `apis/fhir/`, project config JSON files |
| Change encrypted workflow behavior | `openfhe_manager.py`, `pqc_routing_manager.py`, `HE*.py`, job configs/templates |
| Debug local startup | Dockerfile, `.env`, `app/main.py`, `MySQLConnectionProvider.py` |

## Client Content Delivery

| File | Role |
| --- | --- |
| `app/api/models/ClientContentRequest.py` | Validates the startup-kit request body. |
| `app/api/routes/ClientContentRoutes.py` | Maps delivery errors to HTTP status codes and returns the tar as `FileResponse`. |
| `app/core/content_delivery/ClientStartupKitDeliveryService.py` | Local/remote archive creation, path validation, permission handling, checksum, and cleanup. |
| `app/core/ssh/SSHConnectionProvider.py` | Pooled remote command execution plus SFTP upload and download. |
