# Navigation, Layout, and Shared UI Components

## Files Covered

- `src/pages/SHARELandingPage.tsx`
- `src/pages/NavigationSelector.tsx`
- `src/components/ProjectListComponent.tsx`
- `src/components/SHAREHomeDashboard.tsx`
- `src/components/HeaderBar.tsx`
- `src/components/HeaderTitle.tsx`
- `src/components/FooterBar.tsx`
- `src/components/FunctionSelector.tsx`
- `src/components/NVFlareClientSnapshot.tsx`
- `src/components/AbstractAccordion.tsx`
- `src/components/AbstractModal.tsx`
- `src/components/RefreshablePanel.tsx`
- `src/components/HelpToggle.tsx`
- `src/components/WorkflowErrorPanel.tsx`
- `src/App.css`

## Layout Model

The authenticated application uses a persistent two-column workspace:

```text
+----------------------+--------------------------------------+
| left navigation      | right workspace                      |
|                      |                                      |
| Home                 | Home / project / Job History /       |
| Projects             | Job Runner / Results / NVFlare       |
|   Project A          | Manager content                      |
|     Job History      |                                      |
|     Job Runner       |                                      |
|   Project B          |                                      |
| NVFlare Manager      |                                      |
+----------------------+--------------------------------------+
```

The left rail is sticky on normal desktop layouts. The right side scrolls with the document while the navigation remains anchored below the application header.

Responsive CSS collapses/reflows the layout on narrow screens rather than forcing the desktop rail model.

## `SHARELandingPage`

`src/pages/SHARELandingPage.tsx` is intentionally thin. It receives the active top-level screen and navigation callbacks from `App.tsx`, then renders `ProjectListComponent`.

It is the authenticated workspace entrypoint for:

- Home
- project landing pages
- Job History
- Job Runner
- Results
- NVFlare Manager

## `NavigationSelector`

`src/pages/NavigationSelector.tsx` is the persistent left navigation rail.

### Global Items

The current global items are:

- Home
- Projects accordion
- NVFlare Manager for INITIATOR users

Home uses `public/icons/nav_icon_home.png`.

### Projects Accordion

The Projects row contains:

- chevron positioned in the far-left indicator lane
- Projects icon aligned with Home's icon
- `Projects` label aligned with Home text
- project-count indicator

Its open state is controlled by `App.tsx`, not by local component state. This prevents Home or NVFlare Manager selection from unexpectedly reopening a user-collapsed Projects list.

### Project Entries

Each project entry shows:

- project-specific icon
- project name
- supported-function count
- datasource-group count when nonzero

The selected project uses a green vertical indicator matching the secondary-button green.

### Project Submenu

Only the selected project reveals its submenu.

The submenu contains:

- Job History
- Job Runner for INITIATOR users

The submenu animates open/closed using the same transition language as the Projects accordion.

## `ProjectListComponent`

Despite the historical name, `ProjectListComponent` now owns much more than a list. It coordinates the landing/workspace content.

Responsibilities include:

- fetch `/projects/list`
- hydrate public filter schemas
- maintain selected project ID
- render `NavigationSelector`
- fetch/cache `/landing/project` summaries
- render project landing content
- render `SHAREHomeDashboard` for global Home
- embed Job History
- embed Job Runner
- embed Results
- embed NVFlare Manager content
- maintain recent-job expanded row state

The component keeps existing landing payloads visible while refreshing so users do not see a full-page loading flash when navigating back to previously loaded content.

## `SHAREHomeDashboard`

This component renders the global Home landing view.

It calls `/landing/home` with the current username, caches the last successful response by username + role, and keeps stale data on screen during refresh. The backend response is role-aware; optional Home fields are rendered only when present.

The Home view includes:

- welcome copy
- refresh action
- job/function counts for all users
- registered-user count when supplied by the backend
- job-status donut visualization when supplied by the backend
- user-role donut visualization when supplied by the backend
- supported-functions accordion expanded by default

## Shared Header

`HeaderBar.tsx` renders the SHARE logo and user/session context.

After login, the logo is clickable and routes back into the landing environment. The destination depends on whether the application has an active project context.

User Settings is also opened through HeaderBar.

## Shared Page Title

`HeaderTitle.tsx` supports:

- text title
- optional icon via `iconPath`
- description/help content
- contained white-background presentation
- transparent background presentation through `transparentBackground`

Job History and Job Runner use their respective navigation icons in the title.

The contained workspace title and first child content panel are styled as visually related surfaces. A light grey separator line can be owned by the title surface while the child panel removes its top border.

Results uses its title with the appropriate transparent/non-contained treatment so it does not appear to reserve space for a phantom icon.

## Function Selector

`FunctionSelector.tsx` serves two related purposes:

1. defines `FUNCTION_METADATA`, including IDs, display titles, icons, descriptions, and disabled state
2. renders the full Job Runner computation-function selection/configuration UI

### Separate Landing and Job Runner Card Styles

The compact project/Home function tiles use:

- `.project-function-grid`
- `.project-function-tile`

The full Job Runner cards use dedicated classes such as:

- `.job-runner-function-grid`
- `.job-runner-function-card`

These must remain separate. The Job Runner cards need configuration expansion, controls, and larger content areas; project landing tiles are compact capability summaries.

Current project landing grid uses responsive tracks similar to:

```css
grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
```

## Function Icons

Function icons live under `public/icons/` and are shared across:

- Job Runner
- project supported-function tiles
- Home supported-function list
- recent-job detail pills

The icon filename mapping remains centralized through function metadata rather than duplicated by page.

## `NVFlareClientSnapshot`

The client snapshot is reused in multiple contexts.

It supports page-specific layout options because:

- the standalone/landing NVFlare Manager should not reserve a legacy navigation placeholder
- the landing NVFlare Manager can omit the outer panel border
- Job Runner submission still needs the bordered embedded client/participation panel

The component therefore accepts explicit behavior props rather than relying on one fixed visual wrapper.

## `AbstractAccordion`

`AbstractAccordion` is the shared accordion implementation used by areas such as the Home supported-function list.

The Home supported-function accordion is controlled by the parent and starts open by default. Parent-controlled state is preferred when the page needs guaranteed default/open behavior.

The project landing Supported Functions and Recent Jobs areas are intentionally always visible rather than accordions.

## Animation

The UI uses a consistent fade/translate entry language.

Important animated areas include:

- top-level feature swaps
- selected project landing pages
- Projects accordion
- selected-project submenu

The project landing panel is keyed by project ID so selecting a different project replays the entry animation.

## Buttons and Hover Conventions

The left navigation follows the existing SHARE navigation hover language:

- no dramatic background fill on hover
- potential selection text becomes bold/blue
- selected project uses the green vertical indicator

Secondary actions use the shared `secondary-button` class.

## Loading Convention

Home/project/NVFlare landing content uses stale-while-revalidate behavior when practical:

- do not blank previously loaded content
- keep stale data visible
- refresh in place
- update when the new response arrives

A true loading placeholder should be reserved for first-load cases where no usable prior content exists.

## CSS Class Families

Important landing/workspace class families in `App.css` include:

- `.projects-home-*`
- `.project-tab-*`
- `.landing-nav-*`
- `.project-nav-*`
- `.project-workspace-*`
- `.project-overview-*`
- `.project-function-*`
- `.project-recent-job-*`
- `.home-dashboard-*`
- `.job-runner-function-*`

Keep exact duplicate selectors consolidated within the same CSS scope. Breakpoint-specific overrides may remain separate inside their media-query scope.
