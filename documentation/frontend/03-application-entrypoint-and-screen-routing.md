# Application Entrypoint and Screen Routing

## Files Covered

- `src/index.tsx`
- `src/App.tsx`
- `src/pages/LoginPage.tsx`
- `src/pages/SHARELandingPage.tsx`
- `src/components/ProjectListComponent.tsx`
- `src/pages/NavigationSelector.tsx`
- `src/pages/UserSettingsPage.tsx`
- `src/components/HeaderBar.tsx`
- `src/utils/LaunchPayload.ts`
- `src/context/UserRoleContext.tsx`

## React Entrypoint

`src/index.tsx` renders the application root component inside `React.StrictMode`.

`App.tsx` is the top-level coordinator for authenticated routing, user/session context, selected project context, direct-results state, browser history, header/footer behavior, and the persistent landing/workspace shell.

## Current `AppScreen` Values

`App.tsx` defines:

```ts
type AppScreen =
  | "login"
  | "home"
  | "job_history"
  | "job_runner"
  | "nvflare_manager"
  | "users_manager"
  | "user_settings"
  | "filters_manager"
  | "participation_manager"
  | "job_results";
```

There is no separate project-list or legacy project-summary screen. Project selection is part of the authenticated Home/landing environment.

## URL Route Values

The application writes a compact `s` query parameter for browser history:

| Screen | `s` |
| --- | --- |
| `login` | `0` |
| `home` | `1` |
| `job_history` | `3` |
| `job_runner` | `4` |
| `nvflare_manager` | `5` |
| `users_manager` | `6` |
| `user_settings` | `7` |
| `filters_manager` | `8` |
| `participation_manager` | `9` |
| `job_results` | `10` |

The application also keeps an internal history-state marker and, for Results, an `nvflareJobId` value.

## Initial Screen

The app starts with:

```ts
screen = "login"
```

On ordinary successful login:

1. the returned session base is stored
2. selected project is cleared
3. screen becomes `home`
4. global Home is shown because no project is selected

If the login was initiated from a valid direct Results launch payload containing an NVFlare job ID, the app enters `job_results` instead.

## Authenticated Landing/Workspace Shell

These screens are all rendered through `SHARELandingPage`:

- `home`
- `job_history`
- `job_runner`
- `nvflare_manager`
- `job_results`

`SHARELandingPage` delegates to `ProjectListComponent`, which renders:

- persistent left `NavigationSelector`
- global Home content
- selected project landing content
- Job History in the right workspace
- Job Runner in the right workspace
- Results in the right workspace
- NVFlare Manager content in the right workspace

This is the primary authenticated application environment.

## Project Selection Model

A project is application context, not a separate top-level screen.

Selecting a project performs:

```ts
setProject(selectedProject);
setScreen("home");
```

`ProjectListComponent` receives `initialProjectId` from `App.tsx` and uses it to select/render the corresponding project landing view.

Selecting another project keeps the user in `home` while changing the active project panel.

## Global Home

Global Home is selected by:

```ts
setProject(null);
setScreen("home");
```

`NavigationSelector` treats Home as selected only when:

- `selectedScreen === "home"`
- `selectedProjectId === null`

The global Home content is rendered by `SHAREHomeDashboard.tsx`.

## Project Job History

Selecting Job History performs:

```ts
setProject(selectedProject);
setScreen("job_history");
```

The selected project remains the active project context in the left rail. Job History renders in the right-hand workspace rather than opening a second navigation layout.

## Project Job Runner

Selecting Job Runner performs:

```ts
setProject(selectedProject);
setScreen("job_runner");
```

The Job Runner submenu item is visible only to INITIATOR users.

Job Runner subpages are coordinated internally by `JobRunnerMain.tsx`; they do not become new top-level `AppScreen` values.

## Results Routing

### Results from Project/Job History

`openProjectJobResults(project, nvflareJobId)`:

1. validates/normalizes the NVFlare job ID
2. pushes browser state with `screen: "job_results"`
3. stores the selected project
4. stores the direct Results job ID
5. changes the top-level screen to `job_results`

Results stay inside `SHARELandingPage`.

### Results Context Resolution

A Results link may not initially have a loaded project object. `ResultsPage` resolves its results context and calls a stable `onResultsContextLoaded` callback, allowing `App.tsx`/`ProjectListComponent` to select the correct project in the left navigation.

The callback must remain stable across renders; recreating it on every render can cause the Results loading effect to restart repeatedly.

### Leaving Direct Results

`leaveDirectResults()` clears the direct-results URL/history job ID and returns to `home`.

Project-scoped Results flows should return to the project landing context rather than treating global Home and the project page as the same destination.

## SHARE Client Launch-Link Routing

`LaunchPayload.ts` supports compressed/encoded SHARE launch payloads containing fields such as:

- `username`
- optional `nvflare_job_id`
- optional action metadata

`App.tsx` reads launch data once, decides whether auto-login is valid, then strips launch parameters from the visible URL after initialization.

Direct Results launch links can therefore:

1. identify the user
2. identify the NVFlare job
3. auto-login under the current prototype rules
4. enter Results
5. resolve the project through the backend results-context endpoint

See the client-supervisor documentation for the link generation side.

## User Session Context

`App.tsx` provides `UserRoleContext` with a derived `UserSession`.

The current session includes selected-project datasource state only when a project-oriented screen needs it. The app intentionally hides FHIR-source context on:

- `login`
- global/project `home`
- `nvflare_manager`

The selected project datasource list is derived from `sessionBase.projects` and `project.id`.

## Header Behavior

`HeaderBar` receives:

- current user session
- optional active FHIR server
- User Settings callback
- SHARE-logo callback

Once logged in, the SHARE logo is application navigation rather than a static image. It returns into the landing environment and preserves the relevant project context when appropriate. With no project selected, it opens global Home.

The Home navigation asset is `public/icons/nav_icon_home.png`.

## User Settings

`user_settings` still renders outside the landing shell.

`UserSettingsPage` receives:

- `initialProjectId={project?.id ?? null}`
- `returnScreen="home"`

Its return-button text is context-aware: a selected project means the user is returning to a project page; no selected project means the destination is global Home.

## Other Top-Level Feature Screens

`users_manager`, `filters_manager`, and `participation_manager` remain in the `AppScreen` type. The current source directly renders `users_manager` when a project exists; the others remain available as route/state vocabulary for feature integration.

## Browser Back/Forward

`App.tsx` stores an application-history marker and screen in `window.history.state`.

A `popstate` listener restores the screen and direct Results job ID. When browser history re-enters `job_results`, project state is cleared first so Results context can re-resolve the owning project cleanly.

## Screen Reload Keys

Calling `setScreen(nextScreen)` with the same screen increments `screenReloadKeys[nextScreen]` rather than pushing a duplicate navigation state. Screens that use a reload key can intentionally remount/reload without changing the logical route.

## Animation Behavior

`App.tsx` toggles the outer `animate-in` class when the top-level screen changes.

Project landing panels also have project-specific entry animation so changing projects replays the landing transition.

Projects navigation and project submenus use animated expand/collapse behavior rather than instant visibility changes.

## Scroll-to-Top Behavior

`App.tsx` watches `window.scrollY`. After the user scrolls beyond the configured threshold, a fixed circular scroll-to-top action is displayed near the bottom-right of the viewport.

## Routing Model Summary

The current architecture is intentionally state-driven rather than React Router-driven:

```text
Login
  -> Home (global)
       -> Project landing
            -> Job History
            -> Job Runner
            -> Results
       -> NVFlare Manager
```

All project-oriented paths remain within the same persistent SHARE landing/workspace shell.
