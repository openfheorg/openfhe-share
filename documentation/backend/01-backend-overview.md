# Backend Overview

## Backend Documentation Map

The backend documentation is organized around the major code areas in the FastAPI backend.

| Area | Primary files/directories | Detailed file |
| --- | --- | --- |
| Repository and runtime layout | `backend/`, `backend/app/`, Docker/runtime files | `02-repository-and-runtime-layout.md` |
| Application startup and routing | `app/main.py`, `app/api/AppRoutes.py` | `03-application-entrypoint-and-routing.md` |
| API endpoints | `app/api/routes/`, `app/api/models/` | `04-api-endpoints.md` |
| Environment configuration and secrets | `app/core/EnvironmentManager.py`, `app/core/aws/` | `05-environment-configuration-and-secrets.md` |
| Database initialization and schema | `app/core/mysql/MySQLConnectionProvider.py`, schema/default-data methods | `06-database-initialization-and-schema.md` |
| MySQL access and managers | `app/core/mysql/`, `app/core/mysql/managers/` | `07-mysql-access-layer-and-managers.md` |
| Users, roles, projects, and datasources | `UsersManager.py`, `RolesManager.py`, `ProjectsManager.py` | `08-users-roles-projects-and-datasources.md` |
| Functions, filters, thresholds, and workflow groups | `FunctionsManager.py`, `FiltersManager.py`, `ThresholdManager.py`, workflow group schema/manager logic | `09-functions-filters-thresholds-and-workflow-groups.md` |
| Job runner service | `app/core/job_runner/JobRunnerService.py` | `10-job-runner-service.md` |
| NVFlare job lifecycle | `NVFlareJobTask.py`, `NVFlareJobStager.py`, `NVFlareJobRunner.py`, `NVFlareJobUploader.py`, `NVFlareJobMonitor.py` | `11-nvflare-job-lifecycle.md` |
| NVFlare job packaging and templates | `app/core/job_runner/nvflare_jobs/jobs/`, `templates/`, `workflows/`, `scripts/`, `wheels/` | `12-nvflare-job-packaging-and-templates.md` |
| Participation and client state | `ClientRoutes.py`, `ParticipationManager.py`, `NVFlareClientSnapshot.py`, `NVFlareParticipationJobTask.py` | `13-participation-and-client-state.md` |
| FHIR filtering and analysis engines | `app/core/job_runner/nvflare_jobs/apis/fhir/` | `14-fhir-filtering-and-analysis-engines.md` |
| Biomarker and analytics workflows | `stat_analytics.py`, biomarker model CSVs, analysis runtime files | `15-biomarker-and-analytics-workflows.md` |
| Job status, history, and results | `JobRunnerRoutes.py`, `NVFlareRoutes.py`, `NVFlareJobsManager.py`, `job_tracking/` | `16-job-status-history-and-results.md` |
| NVFlare admin, server, and SSH integration | `app/core/nvflare/`, `app/core/ssh/` | `17-nvflare-admin-server-and-ssh-integration.md` |
| OpenFHE and encrypted workflows | `openfhe_manager.py`, `HEAggregator.py`, `HEExecutor.py`, `HEPersistor.py`, `pqc_routing_manager.py` | `18-openfhe-and-encrypted-workflows.md` |
| Local standalone and containerization | `Dockerfile`, `Dockerfile_alpine`, `requirements.txt`, `.env`, build scripts | `19-local-standalone-and-containerization.md` |
| Security, auth, CORS, and access control | `app/main.py`, `/user/role`, environment/secrets helpers, route auth TODOs | `20-security-auth-cors-and-access-control.md` |
| Observability, logging, and troubleshooting | route logging, job status writers/retrievers, monitor classes, websocket status paths | `21-observability-logging-and-troubleshooting.md` |
| Backend code map | End-to-end file index and subsystem ownership | `22-backend-code-map.md` |
| Landing page summary endpoints | `LandingPageRoutes.py`, `LandingPageManager.py`, landing-page indexes | `24-landing-page-summary-endpoints.md` |

## Backend Areas at a Glance

The backend starts in `app/main.py`, registers route modules through `app/api/AppRoutes.py`, and exposes endpoint groups from `app/api/routes/`.

The backend uses MySQL through `app/core/mysql/`. Lower-level connection and table helpers sit beside manager classes that implement application-specific behavior for users, roles, projects, functions, filters, thresholds, participation, NVFlare jobs, landing-page summary reads, client progress emission, and crypto audit records.

Job execution flows through `app/core/job_runner/`. The main service delegates to task classes, and NVFlare-specific work is handled under `app/core/job_runner/nvflare_jobs/`.

The NVFlare job directory contains both backend orchestration code and job runtime assets. The documentation should keep those separated: files like `NVFlareJobStager.py` are backend orchestration code, while files under `jobs/`, `apis/`, `workflows/`, `scripts/`, and `wheels/` define NVFlare job templates, wheel contents, simulator helpers, and local snapshot-wheel packaging.

## How to Use These Docs

Start here for the file map, then move to the document that matches the subsystem being changed.

When documenting or modifying a backend area, always connect:

- route file
- request model or request body
- manager/service class
- database tables touched
- NVFlare job assets touched
- frontend screen or workflow that calls it
- runtime configuration needed
- common failure modes