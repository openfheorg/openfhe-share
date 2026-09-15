# User Session, Roles, and Project Selection

## Files Covered

- `src/context/UserRoleContext.tsx`
- `src/pages/LoginPage.tsx`
- `src/App.tsx`
- `src/pages/SHARELandingPage.tsx`
- `src/pages/NavigationSelector.tsx`
- `src/components/ProjectListComponent.tsx`
- `src/components/HeaderBar.tsx`
- `src/pages/UserSettingsPage.tsx`
- `src/types/Project.tsx`
- `src/types/LandingPage.tsx`

## Session Context

`UserRoleContext.tsx` defines the authenticated session model used throughout SHARE.

The session includes:

- role
- username
- user ID
- project access entries
- current selected project ID
- selected project datasource assignments
- effective FHIR source when applicable

The top-level session base returned from login is stored in `App.tsx`; selected-project fields are derived from the current `project` state rather than persisted as an independent authoritative object.

## Login Flow

`LoginPage` calls the backend user-role/session endpoint. On success, `App.tsx` stores the returned session base.

Normal login then:

```ts
setProject(null);
setScreen("home");
```

This opens global Home. There is no separate project picker screen before entering the application.

A valid direct Results launch can enter `job_results` after login instead.

## Role Handling

The active role is read through `useUserRole()`.

Current landing/workspace role behavior:

| Capability | CLIENT | INITIATOR |
| --- | --- | --- |
| Global Home | Yes | Yes |
| View/select projects | Yes | Yes |
| Project landing page | Yes | Yes |
| Job History | Yes | Yes |
| Results | Yes | Yes |
| Job Runner submenu | No | Yes |
| `Run New Analysis` on project page | No | Yes |
| NVFlare Manager global navigation item | No | Yes |

Role checks are presentation/navigation controls in the current frontend. Backend route-level bearer-token authorization is not yet the enforcement mechanism for these capabilities.

## Project Definitions

`ProjectListComponent` continues to load full project definitions from:

```http
POST /projects/list
```

Those full project objects are needed beyond the landing page itself. They include the configuration used by Job Runner and other project-scoped features.

After the backend project list is returned, the frontend hydrates relevant public filter schemas under `public/filters/{filter_system}/` and stores them on the project objects.

## Project Selection

Project selection now happens in the persistent left navigation.

The `Projects` navigation item is an accordion containing all available projects. The accordion open/closed state lives in `App.tsx` so it persists across Home, project, Job History, Job Runner, Results, and NVFlare Manager navigation.

Selecting a project:

1. stores the full `Project` object in `App.tsx`
2. sets the screen to `home`
3. renders that project's landing page
4. expands the active project's Job History / Job Runner submenu

Only the active project shows the submenu.

## Project Navigation Metadata

Each project entry displays:

- project icon from `public/icons/projects/{project.id}/icon.png`
- project name
- count of active/supported functions
- datasource-group count when the project has datasource groups

Disabled/coming-soon computation functions are not included in the navigation's supported-function count.

## Project Landing Summary

After a project is active, `ProjectListComponent` fetches:

```http
POST /landing/project

{
  "project_id": <selected project id>
}
```

This response supplies landing-specific data such as:

- project status/description/fixed state
- total jobs
- registered-user count
- datasource groups/default group
- project function capabilities
- five recent jobs

The full project object from `/projects/list` remains the source for workflow configuration. `/landing/project` is a compact read model for the project landing view.

## Datasource Resolution

`App.tsx` derives `selectedProjectDatasources` by locating the selected project in the authenticated user's project-access list.

The effective FHIR source is chosen from:

1. the default datasource assignment when available
2. otherwise the first datasource assignment

FHIR source context is hidden on screens that do not need project-local data display, including Home and NVFlare Manager.

The app validates non-JSON FHIR URLs and expects the path to end in `/fhir`.

## Project Datasource Groups

Projects may define zero or more datasource groups.

On project landing pages:

- if the project has no datasource groups, the datasource-group stat is omitted
- if groups exist, they are shown as a simple comma-separated list
- the default group is marked with `(Default)`

The project landing API also returns `default_datasource_group` explicitly.

## Project Function Availability

The backend project capability list is mapped through `FUNCTION_METADATA` in the frontend.

The frontend metadata controls presentation state such as:

- icon
- display title
- description
- disabled/coming-soon status

On the project landing page, active functions are displayed first. Disabled functions appear after active functions, are greyed out, and include `Coming soon.` in their description.

## Project Job History and Job Runner Submenu

The active project's submenu is animated.

- `Job History` is available to CLIENT and INITIATOR.
- `Job Runner` is rendered only for INITIATOR.

Selecting either item retains the active project and swaps the right-hand workspace content.

## Recent Jobs and Results

The project landing page shows only five recent jobs from `/landing/project`.

A completed recent job can open Results directly. `App.tsx` records the selected project and NVFlare assigned job ID before entering `job_results`.

The Results page resolves/maintains project context so the left navigation stays associated with the correct project.

## SHARE Logo and Return Navigation

The SHARE logo is clickable after login.

Conceptually:

- if there is no project context, it returns to global Home
- if there is active project context, it returns to that project's landing page
- leaving direct Results also clears direct-results URL/history state

Project-scoped feature screens use **Back to Project Page** terminology. Global Home is reserved for the system-level landing page.

## User Settings

`UserSettingsPage` receives the current `initialProjectId` when one exists.

Its return target is `home`, but the label reflects the user's context:

- selected project: **Back to Project Page**
- no selected project: **Back to Home**

## Session Persistence

The current session is React state, not a durable browser session store. Refreshing/reloading the application does not reconstruct the full authenticated session from cookies or a token-based session provider.

Browser history preserves screen/direct-results navigation state during the active page session, but it is not an authentication persistence mechanism.

## Summary Flow

```text
Login
  -> Home
       -> select Project A
            -> Project A landing
                 -> Job History
                 -> Job Runner (INITIATOR)
                 -> Results
       -> select Project B
            -> Project B landing
       -> NVFlare Manager (INITIATOR)
```

The selected project is a shared application context; project selection is no longer a dedicated standalone page.
