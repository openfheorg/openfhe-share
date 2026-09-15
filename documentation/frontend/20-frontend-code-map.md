# Frontend Code Map

## Top-Level Frontend

| Path | Area |
| --- | --- |
| `package.json` | NPM scripts, dependencies, and React build/test commands. |
| `tsconfig.json` | TypeScript compiler configuration. |
| `.env.production.local` | Production-local environment values. |
| `public/` | Static assets and runtime JSON configuration. |
| `src/index.tsx` | React render entrypoint. |
| `src/App.tsx` | Top-level session, screen, project context, browser history, and landing-workspace routing. |
| `src/App.css` | Application-level styling and landing/workspace layout. |
| `src/index.css` | Global styling. |

## Source Code Map

| Path | Area |
| --- | --- |
| `src/components/` | Shared reusable UI components, including landing-page content components. |
| `src/constants/` | API constants, global schema, execution step constants, and test constants. |
| `src/context/` | User/session/role/project datasource context. |
| `src/features/job_runner/` | Job setup, filters, workflow groups, function selection, participation, submission, and submitted job flow. |
| `src/features/job_history/` | Job history table, Results page, report sections, utilities, types, and export system. |
| `src/features/nvflare_manager/` | NVFlare manager content/wrappers. |
| `src/features/user_manager/` | Filter and analysis configuration manager screens. |
| `src/images/` | Source-bundled image assets. |
| `src/models/` | Frontend model definitions. |
| `src/pages/` | Login, SHARE landing shell, persistent navigation, and user settings pages. |
| `src/types/` | Shared TypeScript data models and interfaces. |

## Top-Level Pages

| File | Area |
| --- | --- |
| `src/pages/LoginPage.tsx` | Username login and user role lookup. |
| `src/pages/SHARELandingPage.tsx` | Authenticated SHARE workspace shell. |
| `src/pages/NavigationSelector.tsx` | Persistent Home / Projects / project submenu / NVFlare Manager navigation rail. |
| `src/pages/UserSettingsPage.tsx` | Current-user datasource settings for project and datasource groups. |

## Landing Page Components

| File | Area |
| --- | --- |
| `src/components/ProjectListComponent.tsx` | Loads full project definitions, owns selected project state, loads per-project landing summaries, and renders the right-hand workspace content. |
| `src/components/SHAREHomeDashboard.tsx` | Global Home landing content and `/landing/home` consumer. The filename retains `Dashboard`, but the product concept is the Home landing page. |
| `src/types/LandingPage.tsx` | Home/project landing endpoint response types. |
| `src/pages/NavigationSelector.tsx` | Global left rail and role-gated project submenu. |

## Shared Components

| File | Area |
| --- | --- |
| `AbstractAccordion.tsx` | Reusable accordion, including Home supported-function list. |
| `AbstractModal.tsx` | Reusable modal. |
| `AnimateIn.tsx` | Reusable animated-entry wrapper/pattern. |
| `FilterSummary.tsx` | Filter summary display. |
| `FooterBar.tsx` | Shared footer. |
| `FunctionSelector.tsx` | Function metadata plus full Job Runner function selection/configuration. |
| `HeaderBar.tsx` | Shared header, user context, logo navigation, user settings entry. |
| `HeaderTitle.tsx` | Shared feature title with optional icon and transparent/contained background treatment. |
| `HelpToggle.tsx` | Contextual help toggle. |
| `NVFlareClientSnapshot.tsx` | Shared client/server connection/participation snapshot. |
| `ProjectName.tsx` | Project-name display helper. |
| `RefreshablePanel.tsx` | Refreshable content wrapper. |
| `WorkflowErrorPanel.tsx` | Workflow error display. |

## Job Runner Map

| Path | Area |
| --- | --- |
| `src/features/job_runner/JobRunnerMain.tsx` | Job runner workflow coordinator. |
| `src/features/job_runner/pages/filters/` | Filter creation, listing, and selection. |
| `src/features/job_runner/pages/workflow_group_selection/` | Workflow group option selection. |
| `src/features/job_runner/pages/functions/` | Function selection. |
| `src/features/job_runner/pages/job_submission/` | Final job review, client state, and submission. |
| `src/features/job_runner/pages/submitted_jobs/` | Submitted job display/confirmation/results path. |
| `src/features/job_runner/components/` | Job runner-specific reusable components. |
| `src/features/job_runner/utils/` | Job runner helper utilities. |

## Job History and Results Map

| Path | Area |
| --- | --- |
| `src/features/job_history/JobHistoryMain.tsx` | Full Job History feature entrypoint embedded in the SHARE workspace. |
| `src/features/job_history/components/JobHistoryTable.tsx` | Full history table and row actions. |
| `src/features/job_history/pages/ResultsPage.tsx` | Main Results viewer, also embedded in the SHARE workspace. |
| `src/features/job_history/components/` | Results/report/export UI components. |
| `src/features/job_history/utils/JobsDataUtils.tsx` | Job/result loading and parsing utilities. |
| `src/features/job_history/utils/ExportPdfUtils.tsx` | PDF export utilities. |
| `src/features/job_history/utils/ExportDocxUtils.tsx` | DOCX export utilities. |
| `src/features/job_history/utils/ExportHtmlUtils.tsx` | HTML export utilities. |
| `src/features/job_history/utils/ExportPngUtils.tsx` | PNG export utilities. |
| `src/features/job_history/types/` | Job history/result/export types. |
| `src/features/job_history/constants/` | Job history/result constants. |

## NVFlare Manager Map

| Path | Area |
| --- | --- |
| `src/features/nvflare_manager/` | NVFlare manager content/wrappers. |
| `src/components/NVFlareClientSnapshot.tsx` | Shared client/server snapshot table and submission-page participation view. |

## User Manager Map

| Path | Area |
| --- | --- |
| `src/features/user_manager/UserManagerMain.tsx` | User manager screen wrapper. |
| `src/features/user_manager/pages/FilterManagerPage.tsx` | Filter configuration manager page. |
| `src/features/user_manager/pages/AnalysisManager.tsx` | Analysis configuration manager page. |
| `src/features/user_manager/utils/` | User manager utilities. |

## Public Asset and Config Map

| Path | Area |
| --- | --- |
| `public/icons/nav_icon_home.png` | Home navigation icon. |
| `public/icons/nav_icon_projects_list.png` | Projects accordion icon. |
| `public/icons/nav_icon_job_history.png` | Job History title/landing icon. |
| `public/icons/nav_icon_job_runner.png` | Job Runner title/landing icon. |
| `public/icons/nav_icon_nvflare_manager.png` | NVFlare Manager icon. |
| `public/icons/function_icon_*.png` | Computation-function icon vocabulary. |
| `public/icons/projects/{id}/icon.png` | Per-project icons. |
| `public/logos/` | Logo assets. |
| `public/status-images/` | Status and illustration assets. |
| `public/filters/` | Static filter configuration JSON. |
| `public/analysis_config/` | Static analysis configuration JSON. |
| `public/SO/` | Static survival/analysis output assets. |

## Starting Points by Task

| Task | Start with |
| --- | --- |
| Change login behavior | `src/pages/LoginPage.tsx`, `src/context/UserRoleContext.tsx`, `Constants.tsx` |
| Change global Home | `src/components/SHAREHomeDashboard.tsx`, `src/pages/NavigationSelector.tsx`, `src/types/LandingPage.tsx` |
| Change project landing content | `src/components/ProjectListComponent.tsx`, `src/types/LandingPage.tsx`, `App.css` |
| Change left navigation / project submenu | `src/pages/NavigationSelector.tsx`, `src/App.tsx`, `App.css` |
| Change landing API URLs | `src/constants/Constants.tsx`, `src/types/LandingPage.tsx` |
| Change project loading/configuration | `ProjectListComponent.tsx`, `/projects/list`, public filter schemas |
| Change user datasource settings | `src/pages/UserSettingsPage.tsx`, `src/context/UserRoleContext.tsx`, `21-user-settings-and-datasource-management.md` |
| Change shared header/logo behavior | `src/components/HeaderBar.tsx`, `src/App.tsx`, `UserRoleContext.tsx` |
| Change Job Runner flow | `src/features/job_runner/JobRunnerMain.tsx` |
| Change filter screens | `src/features/job_runner/pages/filters/`, `FilterPayloadConfigUtils.tsx`, `public/filters/` |
| Change workflow group behavior | `src/features/job_runner/pages/workflow_group_selection/`, `JobRunnerMain.tsx` |
| Change full function selection/configuration | `src/features/job_runner/pages/functions/`, `FunctionSelector.tsx`, `.job-runner-function-*` CSS |
| Change Job History table | `src/features/job_history/components/JobHistoryTable.tsx` |
| Change Results loading | `src/features/job_history/pages/ResultsPage.tsx`, `JobsDataUtils.tsx`, `App.tsx` |
| Change report/result sections | `src/features/job_history/components/`, `ResultsPage.tsx` |
| Change export behavior | `src/features/job_history/components/export/`, `Export*Utils.tsx` |
| Change NVFlare client status UI | `src/components/NVFlareClientSnapshot.tsx`, `src/features/nvflare_manager/` |
| Change static filter config | `public/filters/` |
| Change static analysis config | `public/analysis_config/` |
| Change global styling | `src/App.css`, `src/index.css` |
| Change TypeScript data models | `src/types/`, feature-specific `types/` directories |
