# Repository and Runtime Layout

## Frontend Root

The frontend root contains the React application configuration, public static assets, and source code.

| Path | Role |
| --- | --- |
| `.env.production.local` | Production-local environment values for the React build/runtime configuration. |
| `.gitignore` | Frontend-specific ignored files. |
| `package.json` | NPM package definition, scripts, and dependency list. |
| `package-lock.json` | Locked dependency versions. |
| `README.md` | Existing Create React App readme. |
| `tsconfig.json` | TypeScript compiler configuration. |
| `public/` | Static files, icons, logos, status images, filter JSON, analysis config JSON, and other public runtime assets. |
| `src/` | Main React/TypeScript source code. |

`node_modules/` and large test data files are intentionally excluded from the reviewed frontend package.

## Package and Build Configuration

The frontend is a React application using `react-scripts`.

The main package/runtime files are:

| File | Role |
| --- | --- |
| `package.json` | Defines scripts, dependencies, dev dependencies, and browser support settings. |
| `package-lock.json` | Pins dependency versions. |
| `tsconfig.json` | Configures TypeScript compilation. |
| `.env.production.local` | Supplies production-local environment values. |

The build/test/runtime documentation should cover this in `19-testing-build-and-runtime-config.md`.

## Public Directory

The `public/` directory contains static assets and JSON configuration files loaded by the frontend at runtime.

Important public paths include:

| Path | Role |
| --- | --- |
| `public/index.html` | Browser HTML entrypoint used by the React build. |
| `public/favicon.ico` | Browser favicon. |
| `public/manifest.json` | Web app manifest. |
| `public/robots.txt` | Robots metadata. |
| `public/icons/` | UI icons used by job runner, result, role, and workflow screens. |
| `public/logos/` | Application/logo assets. |
| `public/status-images/` | Status/illustration images used by the UI. |
| `public/filters/` | Public filter configuration JSON. |
| `public/analysis_config/` | Public analysis configuration JSON. |
| `public/SO/` | Static survival/analysis output assets. |

The public assets and configuration behavior should be documented in `16-public-assets-static-config-and-test-data.md`.

## Source Directory

The application source lives under `src/`.

Top-level source paths include:

| Path | Role |
| --- | --- |
| `src/index.tsx` | React render entrypoint. |
| `src/App.tsx` | Top-level application screen state and screen rendering. |
| `src/App.css` | Application-level CSS. |
| `src/index.css` | Global CSS. |
| `src/App.test.tsx` | Default/placeholder app test file. |
| `src/setupTests.ts` | Test setup file. |
| `src/react-app-env.d.ts` | Create React App TypeScript environment declarations. |
| `src/components/` | Shared reusable UI components. |
| `src/constants/` | Frontend constants, API URLs, schemas, and test constants. |
| `src/context/` | React context for user/session/role state. |
| `src/features/` | Main feature modules. |
| `src/images/` | Source-bundled image assets. |
| `src/models/` | Frontend model files. |
| `src/pages/` | Top-level pages used by `App.tsx`. |
| `src/types/` | TypeScript interfaces/types. |

## Application Entrypoint

The render entrypoint is:

| File | Role |
| --- | --- |
| `src/index.tsx` | Imports React, ReactDOM, CSS, and `App`; renders `<App />` inside `React.StrictMode`. |

The application screen/root component is:

| File | Role |
| --- | --- |
| `src/App.tsx` | Owns the top-level app screen state, selected project state, user session state, selected datasource state, scroll-to-top behavior, and top-level screen rendering. |

This flow is documented in `03-application-entrypoint-and-screen-routing.md`.

## Top-Level Pages

Top-level page components live under `src/pages/`.

| File | Role |
| --- | --- |
| `LoginPage.tsx` | Username login flow and `/user/role` backend call. |
| `SHARELandingPage.tsx` | Authenticated SHARE landing/workspace shell. |
| `NavigationSelector.tsx` | Persistent Home / Projects / project submenu / NVFlare Manager left navigation. |

These pages participate in the initial login/project/navigation flow documented in `05-user-session-roles-and-project-selection.md`.

## Context Directory

The context layer currently includes:

| File | Role |
| --- | --- |
| `src/context/UserRoleContext.tsx` | User/session/role/FHIR source/project access context, provider, and helper hooks. |

This file is documented in `05-user-session-roles-and-project-selection.md`.

## Constants Directory

The constants directory contains backend URL constants, shared constants, schemas, and test constants.

| File | Role |
| --- | --- |
| `src/constants/Constants.tsx` | Backend API URL constants and shared frontend constants. |
| `src/constants/ExecutionStep.ts` | Execution step constants/types used by job/status flows. |
| `src/constants/global_schema.json` | Global schema JSON used by frontend data/config flows. |
| `src/constants/testConstants.ts` | Test/local constants. |

API constants and backend contracts are documented in `04-api-configuration-and-backend-contracts.md`.

## Shared Components Directory

Reusable UI components live under `src/components/`.

Important shared components include:

| File | Role |
| --- | --- |
| `AbstractAccordion.tsx` | Reusable accordion component. |
| `AbstractModal.tsx` | Reusable modal component. |
| `FilterSummary.tsx` | Shared filter summary display. |
| `FooterBar.tsx` | Shared footer. |
| `FunctionSelector.tsx` | Reusable function selection/grid/navigation component. |
| `HeaderBar.tsx` | Shared header bar. |
| `HeaderTitle.tsx` | Shared header title component. |
| `HelpToggle.tsx` | Reusable contextual help toggle. |
| `SHAREHomeDashboard.tsx` | Global Home landing content. |
| `ProjectListComponent.tsx` | Landing/workspace coordinator and project landing content. |
| `NVFlareClientSnapshot.tsx` | Shared NVFlare client snapshot display. |
| `RefreshablePanel.tsx` | Refreshable panel wrapper. |
| `WorkflowErrorPanel.tsx` | Workflow error display component. |

Shared components and layout behavior are documented in `06-navigation-layout-and-shared-components.md`.

## Features Directory

The main application modules live under `src/features/`.

| Directory | Role |
| --- | --- |
| `src/features/job_runner/` | Job setup, filter selection, workflow group selection, function selection, submission, and submitted job flow. |
| `src/features/job_history/` | Job history, status, results viewer, report sections, and export system. |
| `src/features/nvflare_manager/` | NVFlare manager screen and client snapshot view. |
| `src/features/user_manager/` | User/config management screens for filters and analysis configuration. |

## Job Runner Feature Layout

The job runner feature is organized under `src/features/job_runner/`.

| Path | Role |
| --- | --- |
| `JobRunnerMain.tsx` | Main job runner state machine and page coordinator. |
| `components/` | Job runner-specific UI components. |
| `pages/` | Job runner screens. |
| `utils/` | Job runner helper utilities. |

Important job runner page areas include:

| Path | Role |
| --- | --- |
| `pages/filters/` | Filter selection/create/list pages. |
| `pages/functions/` | Function selection page. |
| `pages/job_submission/` | Job submission page. |
| `pages/submitted_jobs/` | Submitted job display. |
| `pages/workflow_group_selection/` | Workflow group selection page. |

The job runner flow is documented in `07-job-runner-flow.md`.

## Job History Feature Layout

The job history feature is organized under `src/features/job_history/`.

| Path | Role |
| --- | --- |
| `JobHistoryMain.tsx` | Job history feature entrypoint. |
| `pages/` | Job history pages, including results page. |
| `components/` | Result viewer/report UI components. |
| `types/` | Job history/result-specific types. |
| `utils/` | Job history/result/export utility functions. |
| `constants/` | Job history constants. |

The job history and results flow is documented in `11-job-history-and-results-flow.md`.

The export system is documented in `13-export-system.md`.

## NVFlare Manager Feature Layout

The NVFlare manager feature is organized under `src/features/nvflare_manager/`.

| File | Role |
| --- | --- |
| `NVFlareManagerMain.tsx` | NVFlare manager screen wrapper using shared header/navigation and `NVFlareClientSnapshot`. |

This feature is documented in `14-nvflare-manager-and-client-snapshot.md`.

## User Manager Feature Layout

The user manager feature is organized under `src/features/user_manager/`.

| Path | Role |
| --- | --- |
| `UserManagerMain.tsx` | User manager feature wrapper. |
| `pages/` | Filter/analysis manager pages. |
| `utils/` | User manager helper utilities. |

Known user manager page files include:

| File | Role |
| --- | --- |
| `FilterManagerPage.tsx` | Filter configuration manager screen. |
| `AnalysisManager.tsx` | Analysis configuration manager screen. |

This feature is documented in `15-user-manager-filter-and-analysis-config.md`.

## Types and Models

Type definitions live primarily under `src/types/`, with additional feature-specific types under feature directories.

Important type areas include:

| Path | Role |
| --- | --- |
| `src/types/` | Shared TypeScript interfaces and domain models. |
| `src/features/job_history/types/` | Job history/result-specific types. |
| `src/models/` | Additional frontend model files. |

Types and frontend data models are documented in `17-types-and-data-models.md`.

## Runtime Assembly

At runtime, the frontend is assembled as follows:

1. `public/index.html` hosts the React bundle.
2. `src/index.tsx` renders `App`.
3. `App.tsx` initializes top-level screen/session/project state.
4. `LoginPage` resolves user role/session information.
5. `SHARELandingPage` opens the persistent authenticated workspace.
6. `NavigationSelector` selects global Home, projects, project Job History/Job Runner, or NVFlare Manager.
7. `ProjectListComponent` swaps the right-hand workspace content while preserving project context.
8. Feature modules call backend APIs using constants from `Constants.tsx`.
9. Shared components render common layout, navigation, status, filter summaries, and reusable controls.
10. Public JSON/assets provide static filter/analysis configuration and images used by feature screens.