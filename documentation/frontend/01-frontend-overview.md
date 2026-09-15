# Frontend Overview

## Frontend Documentation Map

The frontend documentation is organized around the major code areas in the React/TypeScript application.

| Area | Primary files/directories | Detailed file |
| --- | --- | --- |
| Repository and runtime layout | `package.json`, `tsconfig.json`, `public/`, `src/` | `02-repository-and-runtime-layout.md` |
| Application entrypoint and screen routing | `src/index.tsx`, `src/App.tsx` | `03-application-entrypoint-and-screen-routing.md` |
| API configuration and backend contracts | `src/constants/Constants.tsx`, frontend `fetch` callers | `04-api-configuration-and-backend-contracts.md` |
| User session, roles, and project context | `src/context/UserRoleContext.tsx`, `src/pages/LoginPage.tsx`, `src/App.tsx` | `05-user-session-roles-and-project-selection.md` |
| Navigation, layout, and shared UI components | `src/pages/SHARELandingPage.tsx`, `src/pages/NavigationSelector.tsx`, `src/components/`, `src/App.css` | `06-navigation-layout-and-shared-components.md` |
| Job runner flow | `src/features/job_runner/JobRunnerMain.tsx`, job runner pages/components/utils | `07-job-runner-flow.md` |
| Filter screens and payload building | `src/features/job_runner/pages/filters/`, `FilterPayloadConfigUtils.tsx`, `public/filters/` | `08-filter-screens-and-payload-building.md` |
| Workflow group selection | `WorkflowGroupSelectionPage.tsx`, workflow group state in `JobRunnerMain.tsx` | `09-workflow-group-selection.md` |
| Job submission, status, and websocket handling | `JobSubmissionPage.tsx`, `JobHistoryTable.tsx`, job status constants | `10-job-submission-status-and-websocket-handling.md` |
| Job history and results flow | `JobHistoryMain.tsx`, `JobHistoryTable.tsx`, `ResultsPage.tsx`, `JobsDataUtils.tsx` | `11-job-history-and-results-flow.md` |
| Results viewer and report sections | `src/features/job_history/components/`, `src/features/job_history/pages/ResultsPage.tsx` | `12-results-viewer-and-report-sections.md` |
| Export system | `src/features/job_history/components/export/`, `src/features/job_history/utils/Export*.tsx` | `13-export-system.md` |
| NVFlare manager and client snapshot | `NVFlareManagerContent.tsx`, `NVFlareClientSnapshot.tsx` | `14-nvflare-manager-and-client-snapshot.md` |
| User manager configuration screens | `UserManagerMain.tsx`, `FilterManagerPage.tsx`, `AnalysisManager.tsx` | `15-user-manager-filter-and-analysis-config.md` |
| Static assets and public configuration | `public/icons/`, `public/logos/`, `public/status-images/`, `public/filters/`, `public/analysis_config/` | `16-public-assets-static-config-and-test-data.md` |
| TypeScript data models | `src/types/`, `src/constants/global_schema.json` | `17-types-and-data-models.md` |
| Styling and UI patterns | `src/App.css`, `src/index.css`, shared components | `18-styling-css-and-ui-patterns.md` |
| Testing, build, and runtime configuration | `package.json`, `package-lock.json`, `App.test.tsx`, `setupTests.ts`, `.env.production.local` | `19-testing-build-and-runtime-config.md` |
| User settings and datasource management | `src/pages/UserSettingsPage.tsx`, datasource session types and endpoints | `21-user-settings-and-datasource-management.md` |
| SHARE Home and project landing pages | `SHARELandingPage.tsx`, `ProjectListComponent.tsx`, `SHAREHomeDashboard.tsx`, `NavigationSelector.tsx` | `22-share-home-and-project-landing-pages.md` |
| Frontend code map | End-to-end file index and starting points by task | `20-frontend-code-map.md` |

## Application Structure at a Glance

The frontend is a React application built with TypeScript and `react-scripts`.

`src/index.tsx` renders `App` inside `React.StrictMode`.

`src/App.tsx` owns top-level application state, including:

- login/session state
- active screen
- selected project context
- direct Results job ID
- browser-history state
- left Projects accordion state
- selected-project datasource metadata
- FHIR source display behavior
- scroll-to-top behavior

The authenticated screens are centered around one persistent landing/workspace shell rather than the former separate project screen.

## Main Screen Flow

The current top-level flow is:

1. `LoginPage` authenticates the username through `/user/role`.
2. A successful login stores role, username, user ID, project access, and datasource metadata in session state.
3. Normal login enters the global **Home** landing page with no project selected.
4. `SHARELandingPage` renders the persistent left navigation plus right-hand workspace.
5. Users can select a project to open that project's landing page.
6. The active project's submenu exposes **Job History** and, for INITIATOR users, **Job Runner**.
7. INITIATOR users can also open **NVFlare Manager** from the global navigation.
8. Results remain inside the same landing/workspace environment with the correct project selected.

The authenticated shell covers these `AppScreen` values:

- `home`
- `job_history`
- `job_runner`
- `nvflare_manager`
- `job_results`

Other feature screens such as `user_settings` and `users_manager` are still routed separately by `App.tsx`.

## Home and Project Landing Pages

There is no separate legacy project summary screen.

The global Home view provides system statistics and guidance. A project landing page provides project-specific capabilities, summary counts, datasource groups, supported functions, and five recent jobs.

The landing pages use dedicated backend summary endpoints:

- `POST /landing/home`
- `POST /landing/project`

See `22-share-home-and-project-landing-pages.md` for the full frontend behavior.

## Session and Role Context

User/session state is defined in `src/context/UserRoleContext.tsx`.

The session model includes:

- user role
- username
- optional user ID
- current FHIR source
- project access list
- selected project ID
- selected project datasource list

Role-specific navigation currently includes:

- CLIENT: Home, Projects, project Job History, Results
- INITIATOR: CLIENT capabilities plus project Job Runner and NVFlare Manager

The project landing page also hides `Run New Analysis` for non-initiators.

## Backend API Integration

Backend API constants are centralized in `src/constants/Constants.tsx`.

The frontend calls backend endpoints for:

- login/user role lookup
- Home landing summary
- project landing summary
- full project definitions
- project FHIR source lookup
- supported functions
- filters
- client connection status
- client participation status
- NVFlare job submission
- NVFlare job history
- job status
- job info
- job results
- job result mapping
- job function config

The landing summary endpoints are intentionally separate from full Job History and full project configuration APIs.

## Main Feature Areas

### Job Runner

The job runner feature lives under `src/features/job_runner/`.

It coordinates filter selection/creation, workflow-group selection, computation-function selection and configuration, submission review, client participation, submission, and submitted-job/results flow.

The full Job Runner function cards use their own `job-runner-function-*` CSS classes. They are intentionally separate from the compact function tiles used on project landing pages.

### Job History and Results

The job history feature lives under `src/features/job_history/`.

It includes full-history querying, live job status tracking, result loading, result/report cards, function configuration display, participation details, datasource details, analytics metrics, Kaplan-Meier plots, and export behavior.

Job History and Results render inside the right-hand SHARE workspace while the left project navigation remains available.

### NVFlare Manager

The NVFlare manager content is embedded directly into the landing workspace. The shared `NVFlareClientSnapshot` supports page-specific border/layout options because it is also reused by Job Runner submission screens.

### User Manager and Settings

User/settings-related screens remain separate top-level features. User Settings can return either to a selected project page or global Home depending on the context from which it was opened.

### Shared Components

Important shared components include:

- `HeaderBar`
- `FooterBar`
- `HeaderTitle`
- `ProjectListComponent`
- `SHAREHomeDashboard`
- `FunctionSelector`
- `NVFlareClientSnapshot`
- `FilterSummary`
- `AbstractAccordion`
- `AbstractModal`
- `RefreshablePanel`
- `HelpToggle`
- `WorkflowErrorPanel`

`NavigationSelector` is implemented under `src/pages/` and owns the persistent Home / Projects / project submenu / NVFlare Manager rail.

## Static Assets and Configuration

The frontend uses `public/` for static assets and JSON configuration.

Important public directories include:

- `public/icons/`
- `public/icons/projects/{project_id}/`
- `public/logos/`
- `public/status-images/`
- `public/filters/`
- `public/analysis_config/`
- `public/SO/`

The global Home navigation icon is `public/icons/nav_icon_home.png`.

## Documentation Build-Out Rule

Each frontend document should connect:

- file or directory covered
- component responsibility
- props and state owned by the component
- backend endpoints called
- public JSON/assets loaded
- shared components used
- type definitions involved
- user workflow supported
- role-gated behavior
- loading/cache behavior
- known disabled or placeholder behavior
- common failure modes
