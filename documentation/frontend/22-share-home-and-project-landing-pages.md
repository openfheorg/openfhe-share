# SHARE Home and Project Landing Pages

## Purpose

The frontend no longer uses the former separate project summary screen. The primary authenticated workspace is the SHARE landing-page shell implemented by:

- `src/pages/SHARELandingPage.tsx`
- `src/components/ProjectListComponent.tsx`
- `src/pages/NavigationSelector.tsx`
- `src/components/SHAREHomeDashboard.tsx`
- `src/App.tsx`

The shell provides one persistent left navigation rail and a right-hand content workspace. Home, project overviews, Job History, Job Runner, Results, and NVFlare Manager all render inside this environment.

## Authenticated Navigation Model

The left navigation is organized as:

```text
Home
Projects
  <Project A>
    Job History
    Job Runner        # INITIATOR only
  <Project B>
    Job History
    Job Runner        # INITIATOR only
NVFlare Manager       # INITIATOR only
```

`Projects` is an accordion. Its open/closed state is owned by `App.tsx` so it is not reset when the user moves between Home, project content, or NVFlare Manager.

A project's Job History / Job Runner submenu is shown only while that project is the active project context. The submenu is animated when it opens and closes.

The left rail uses sticky positioning on normal desktop layouts so the workspace content can scroll independently while navigation remains visible.

## Home Landing Page

The global Home view is rendered by `SHAREHomeDashboard.tsx` when:

- `screen === "home"`
- no project is selected

Home is a role-aware global summary rather than a project-specific page. It always displays:

- a welcome/explanation of SHARE
- a refresh action
- total jobs run
- total supported computation functions
- an expanded-by-default Supported Computation Functions accordion

For non-client roles, the backend may additionally supply and the frontend renders:

- total registered users
- a donut chart of job status distribution
- a donut chart of user-role distribution

`CLIENT` users do not receive those system-wide breakdown fields, so those controls are simply absent from Home.

The Home navigation icon is `public/icons/nav_icon_home.png`.

### Home API

Home loads from:

```http
POST /landing/home
Content-Type: application/json

{
  "username": "<current user>"
}
```

The response is typed in `src/types/LandingPage.tsx` as `LandingHomeResponse` / `LandingHomeSummary`.

The backend returns all defined functions. The frontend still uses `FUNCTION_METADATA` from `FunctionSelector.tsx` as the display/availability source of truth for disabled or coming-soon functions. Home counts and lists only functions that are known to the frontend and are not disabled.

### Stale-While-Revalidate Behavior

Home keeps the last successful `LandingHomeSummary` in a module-level cache keyed by username and role. Refreshes leave existing content visible until the new request completes. The cache is role-scoped so a client cannot inherit a stale, more privileged Home payload after a role/session change.

## Project Landing Page

Selecting a project stays inside the landing environment. It sets the active project and keeps `screen === "home"`; `ProjectListComponent` then renders the selected project's landing panel in the right-hand workspace.

Each project landing page includes:

- project icon
- project name and description
- project status and fixed-state indicator
- refresh action
- total jobs run
- registered-user count
- datasource groups when any exist, including `(Default)` on the default group
- supported computation functions
- disabled/coming-soon functions last and visually muted
- `Run New Analysis` for INITIATOR users only
- the five most recent jobs
- expandable recent-job rows
- direct `View Results` actions for completed jobs
- `View Jobs History`

Project function cards reuse the function icon metadata from `FunctionSelector.tsx`, but they use project-landing-specific CSS classes. They must not share the full Job Runner function-card sizing rules.

### Project Landing API

Project landing data loads from:

```http
POST /landing/project
Content-Type: application/json

{
  "project_id": 2
}
```

The response is typed as `LandingProjectResponse` / `LandingProjectSummary` in `src/types/LandingPage.tsx`.

This endpoint replaces the earlier landing-page behavior of fetching the full `/nvflare/jobs/history` payload simply to calculate a job count and show a few recent jobs.

### Project List Still Uses `/projects/list`

`ProjectListComponent` still calls:

```http
POST /projects/list
```

That response is the application's full project-definition source and is still required for:

- left-navigation project entries
- Job Runner project configuration
- filter schema hydration from `public/filters/`
- function restrictions/configuration metadata
- datasource-group metadata used elsewhere in the workflow

`/landing/project` is a purpose-built read model for the project landing view, not a replacement for the complete project configuration endpoint.

## Recent Jobs on Project Landing Pages

The project landing response includes only the five most recent jobs. The frontend presents them in a compact table patterned after the main Job History table.

Each row shows:

- job ID
- included functions
- status
- created time
- View Results when applicable

Expanding a row can show:

- Job Runner ID
- NVFlare assigned job ID
- runtime duration
- datasource group
- submit/update times
- functions and configuration counts

The main Job History page remains the authoritative full-history view and continues to use the existing job-history endpoint.

## Job History, Job Runner, and Results in the Workspace

Job History, Job Runner, and Results no longer render with a separate legacy navigation panel or dummy spacer div. They are loaded directly into the right side of the SHARE landing shell.

The active project remains highlighted in the left navigation while these screens are open.

### Role Rules

- CLIENT: may open project landing pages, Job History, and Results.
- INITIATOR: receives the same access plus Job Runner and NVFlare Manager.

The project landing page also hides `Run New Analysis` unless the role is `INITIATOR`.

## Results Navigation

Results opened from the project recent-jobs table use the same Results page and project workspace as Results opened from main Job History.

`App.tsx` stores the NVFlare job ID in application history state and selects the correct project when `ResultsPage` resolves its results context.

The callback passed into Results context loading must remain stable (`useCallback`) so loading the project context does not restart the Results effect and create a request loop.

## SHARE Logo Behavior

Once logged in, clicking the SHARE logo uses the same application navigation model as returning from feature screens:

- with an active project context, return to that project's landing page
- without a selected project, show global Home

When leaving direct Results, the direct-results job ID state is cleared before returning to the landing environment.

## Back Button Terminology

Project-scoped feature screens use **Back to Project Page** rather than the older **Back to Home** wording. The distinction matters because Home is now a real global screen while the project landing page is the return destination for project-scoped workflows.

## Animation

Project landing panels use the same fade/translate-in visual language used elsewhere in SHARE. The selected project panel is keyed by project ID so the animation can replay when the user changes projects.

The Projects accordion and project Job History / Job Runner submenus also animate their expand/collapse transitions.

## Styling Ownership

Important CSS families in `App.css` include:

- `.projects-home-page`
- `.projects-home-layout`
- `.project-tab-rail`
- `.landing-nav-primary-option`
- `.project-tab-rail-heading*`
- `.project-tab-list-shell`
- `.project-nav-group`
- `.project-nav-submenu*`
- `.project-workspace-panel`
- `.project-overview-*`
- `.project-function-grid`
- `.project-function-tile`
- `.project-recent-jobs-*`
- `.home-dashboard-*`

The Job Runner function selector intentionally uses separate `.job-runner-function-*` classes so project landing-page tile changes do not alter the full function-configuration UI.
