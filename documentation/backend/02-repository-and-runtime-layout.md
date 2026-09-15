# Repository and Runtime Layout

## Backend Root

The backend lives under `backend/`.

| Path | Role |
| --- | --- |
| `.env` | Local/runtime environment values used by the backend container or local execution. |
| `.gitignore` | Backend-specific ignored files. |
| `Dockerfile` | Backend container build definition. |
| `Dockerfile_alpine` | Alternate backend container build definition. |
| `README.md` | Existing backend readme. Some endpoint references appear stale; use route files as the current API source of truth. |
| `pytest.ini` | Pytest configuration for the backend unit suite. |
| `requirements.txt` | Python dependencies for the backend runtime. |
| `requirements-dev.txt` | Development/test dependencies. Includes `requirements.txt`, `pytest`, and `pytest-asyncio`. |
| `documents/` | Backend-adjacent reference documents and NVFlare YAML examples. |
| `scripts/` | Operator helper scripts for container build/push and MySQL tunnel access. |
| `tests/` | Backend unit test suite mirroring the `app/` package layout. |
| `app/` | Main Python application package. |

## Application Package

| Path | Role |
| --- | --- |
| `app/main.py` | FastAPI application entrypoint. |
| `app/api/` | API router registration, route modules, and request models. |
| `app/core/` | Backend service logic, environment handling, AWS helpers, MySQL access, job runner code, NVFlare helpers, and SSH helpers. |

## API Layout

| Path | Role |
| --- | --- |
| `app/api/AppRoutes.py` | Creates the grouped API router and includes route modules. |
| `app/api/models/FunctionBasedRequest.py` | Request model for endpoints that operate on a selected function. |
| `app/api/routes/ClientRoutes.py` | Client connection status, participation status, and participation submission. |
| `app/api/routes/FilterRoutes.py` | Filter lookup endpoints. |
| `app/api/routes/FunctionRoutes.py` | Supported function lookup endpoints. |
| `app/api/routes/JobRunnerRoutes.py` | Job status, websocket status, job info, results, function config, and result mapping. |
| `app/api/routes/NVFlareRoutes.py` | NVFlare progress emission, job history, job submission, and crypto audit submission. |
| `app/api/routes/ProjectRoutes.py` | Project listing and project datasource lookup. |

## Core Layout

| Path | Role |
| --- | --- |
| `app/core/EnvironmentManager.py` | Runtime environment handling. |
| `app/core/aws/ResourceConfigProvider.py` | AWS resource configuration provider. |
| `app/core/aws/SecretsManager.py` | AWS Secrets Manager helper. |
| `app/core/mysql/` | MySQL connection, schema/default-data initialization, retrievers, managers, and job tracking. |
| `app/core/job_runner/` | Job runner service, task classes, and NVFlare job orchestration/assets. |
| `app/core/nvflare/` | NVFlare admin kit, server, and client snapshot helpers. |
| `app/core/ssh/` | SSH connection provider. |

## MySQL Layout

| Path | Role |
| --- | --- |
| `MySQLConnectionProvider.py` | MySQL connection/provider behavior plus database creation, table creation, table alteration, and default data initialization. |
| `MySQLRetriever.py` | Shared retrieval/query helper. |
| `MySQLTable.py` | Table helper used by schema/manager logic. |
| `SupportedFilterSystem.py` | Supported filter system definitions. |
| `SupportedFunction.py` | Supported function definitions. |
| `UserRole.py` | User role definitions. |
| `managers/` | Application-specific database manager classes. |
| `job_tracking/` | Job status/history/data retrieval and writing. |

## Manager Layout

| Manager file | Area |
| --- | --- |
| `CryptoAuditManager.py` | Crypto audit persistence. |
| `FiltersManager.py` | Filter metadata and lookup. |
| `FunctionsManager.py` | Supported function metadata and lookup. |
| `NVFlareClientEmitManager.py` | NVFlare client progress/status emission persistence. |
| `NVFlareJobsManager.py` | NVFlare job records, history, workflow group logging, datasource logging, and result-related retrieval. |
| `ParticipationManager.py` | Client participation status and participation updates. |
| `ProjectsManager.py` | Project lookup and project datasource lookup. |
| `RolesManager.py` | Role lookup and role-related database behavior. |
| `ThresholdManager.py` | Threshold metadata and lookup. |
| `UsersManager.py` | User lookup and user role behavior. |

## Job Runner Layout

| Path | Role |
| --- | --- |
| `JobRunnerService.py` | Main service entrypoint for requesting job execution. |
| `job_tasks/NVFlareJobTask.py` | Task object for standard NVFlare job submission/execution. |
| `job_tasks/NVFlareParticipationJobTask.py` | Task object for participation confirmation flow. |
| `nvflare_jobs/NVFlareJobStager.py` | Builds/stages job directories and job artifacts. |
| `nvflare_jobs/NVFlareJobRunner.py` | Runs/submits staged NVFlare jobs. |
| `nvflare_jobs/NVFlareJobUploader.py` | Uploads job artifacts to the NVFlare server/admin context. |
| `nvflare_jobs/NVFlareJobMonitor.py` | Monitors NVFlare job status. |
| `nvflare_jobs/taskflow_report.py` | Host-side taskflow/causal-trace renderer for a finished job's collected `trace.jsonl` streams. |

## NVFlare Job Asset Layout

| Path | Role |
| --- | --- |
| `nvflare_jobs/apis/` | Python modules used by NVFlare job runtime code. |
| `nvflare_jobs/apis/fhir/` | FHIR query, filtering, configuration, and analysis engines. |
| `nvflare_jobs/jobs/nvflare_job_template/` | NVFlare runtime template. Model files are no longer stored in the backend job tree; model locations are resolved from initiator user settings at runtime. |
| `nvflare_jobs/docs/` | NVFlare/job sequence diagrams and supporting documentation. |
| `nvflare_jobs/jobs/configs/` | Function/job config JSON files and examples. |
| `nvflare_jobs/jobs/nvflare_job_template/` | Main generated job template. |
| `nvflare_jobs/jobs/participation_confirmation/` | Participation confirmation job template. |
| `nvflare_jobs/scripts/` | Simulator, result parsing, profiling, and helper scripts. |
| `nvflare_jobs/wheels/` | Wheel builder for `duality_nvflare_lib`. The public standalone/simulator runtime consumes the committed local snapshot wheel; job-template wrappers do not update it from a package registry. |
| `nvflare_jobs/workflows/` | Custom workflow implementation files. |

## Test Layout

| Path | Role |
| --- | --- |
| `pytest.ini` | Sets `testpaths = tests`, `python_files = test_*.py`, `addopts = -ra`, and declares the `integration` marker for tests requiring external services or a full NVFlare runtime. |
| `requirements-dev.txt` | Installs `requirements.txt` plus `pytest` and `pytest-asyncio`. |
| `tests/conftest.py` | Shared fixtures for the unit suite. |
| `tests/api/` | Tests for API models, route helpers, and route behavior with mocked managers. |
| `tests/core/` | Tests for configuration, archive handling, NVFlare helpers, FHIR utilities, and database-manager behavior with fake connections/cursors. |

The suite is run from the backend root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The unit suite intentionally avoids live AWS, EC2, MySQL, Docker, and NVFlare-server calls. The simulator/integration tests under `app/core/job_runner/nvflare_jobs/tests/` remain separate and are not collected by `pytest.ini`.

## Runtime Assembly

1. Container/runtime files define the Python environment and startup context.
2. `app/main.py` creates the FastAPI app.
3. `app/api/AppRoutes.py` registers route modules.
4. Route handlers call manager classes and services.
5. Manager classes read/write MySQL-backed application state.
6. Job submission routes call the job runner service.
7. Job runner task classes call NVFlare staging/running/upload/monitoring code.
8. NVFlare job templates and runtime API files are used to build or execute jobs.
9. Status/history/result routes read from job tracking and NVFlare job records.
