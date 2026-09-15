# Styling, CSS, and UI Patterns

## Files Covered

- `src/App.css`
- `src/index.css`
- `src/components/HeaderBar.tsx`
- `src/components/HeaderTitle.tsx`
- `src/pages/NavigationSelector.tsx`
- `src/pages/SHARELandingPage.tsx`
- `src/components/ProjectListComponent.tsx`
- `src/components/SHAREHomeDashboard.tsx`
- shared Job Runner / Job History / Results components

## Styling Model

The frontend uses a combination of:

- global element styles in `App.css` / `index.css`
- named layout and feature classes
- small inline style objects where components need runtime values
- shared button/status classes

The current authenticated UI is built around a compact persistent left navigation rail and a right-hand workspace.

## Core Surface Classes

| Class family | Purpose |
| --- | --- |
| `.page-container` | Generic horizontal/section wrapper used across feature pages. |
| `.child-container`, `.child-container-top`, `.child-container-error` | Main white content surfaces. |
| `.child-container-results-page` | Results-specific content surface. |
| `.footer-button-container` | Bottom action row. |
| `.secondary-button` | Shared green secondary/navigation action. |
| `.function-container` | Feature-level animated content wrapper. |

The old dummy left-navigation spacer pattern is no longer used by Job Runner, Job History, Results, or NVFlare Manager in the primary authenticated path. Those features are embedded directly into the right side of the landing workspace.

## Persistent Landing Workspace

Important classes include:

- `.projects-home-page`
- `.project-workspace-shell`
- `.project-tab-rail`
- `.landing-nav-primary-option`
- `.project-tab-rail-heading*`
- `.project-tab-list-shell`
- `.project-tab-button`
- `.project-nav-group`
- `.project-nav-submenu-*`
- `.project-workspace-panel`
- `.project-workspace-tool-panel`

### Left Rail

The left rail is sticky on desktop layouts. It contains:

- Home
- Projects accordion
- project entries
- animated Job History / Job Runner submenu for the selected project
- NVFlare Manager for INITIATOR users

Navigation hover behavior follows the existing SHARE language: text becomes bold/blue without introducing a strong filled hover background.

The selected project is marked with a green vertical line using the same green family as `secondary-button`.

### Projects Accordion Alignment

The Projects row is aligned so:

- Projects icon aligns with Home icon
- Projects text aligns with Home text
- the chevron sits further left in the indicator lane

The chevron is positioned so it does not push the Projects label/icon to the right.

## Home Landing Page Styling

Home classes use the `.home-dashboard-*` implementation prefix even though the product concept is the Home landing page.

The Home page includes:

- welcome header
- compact system-stat row
- two donut/chart panels
- Supported Computation Functions accordion

The supported-functions accordion is expanded by default and uses the shared accordion component.

## Project Landing Page Styling

Project overview class families include:

- `.project-overview-*`
- `.project-function-*`
- `.project-recent-job-*`

The project header contains title/description, status, refresh, and compact summary statistics.

Project status is displayed as text rather than a heavy pill/badge surface.

Datasource groups are plain comma-separated content rather than individual rounded chips. The default group is labeled `(Default)`. Projects with zero datasource groups omit the datasource-group stat entirely.

## Project Function Tiles

Project landing function tiles are compact capability cards.

The responsive grid currently follows the pattern:

```css
.project-function-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.5rem;
}
```

Disabled/coming-soon function tiles are ordered after active functions and use muted/greyed styling.

The project landing cards do not use hover tooltips; coming-soon state is visible in the card description itself.

## Job Runner Function Cards

The full Job Runner function selector uses a separate class family:

- `.job-runner-function-grid`
- `.job-runner-function-card`

This separation is intentional. The full cards must support selection, expansion, multiple configurations, configuration inputs, internal scrolling, and disabled states.

Important width behavior:

```css
.job-runner-function-card {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
```

`box-sizing: border-box` ensures card padding is included in the assigned grid track and prevents one card from visually overlapping the next.

The function-selector wrapper adds modest left/right padding while keeping inter-card gaps tighter than the original layout.

## Header Title Pattern

`HeaderTitle.tsx` supports contained and transparent presentation.

### Contained Workspace Title

Job History and Job Runner use `contained` titles with their navigation icons.

Within `.project-workspace-tool-panel`:

- the title surface is white
- it has compact internal padding
- the title can show an icon via `iconPath`
- the bottom edge uses a very light grey separator line
- the following child content panel removes its top border so the two surfaces read as one composed page

Spacing is implemented as padding inside the title surface so the border grows with the title/description spacing.

### Transparent Title

`HeaderTitle` exposes `transparentBackground`.

When true, the title has:

- transparent background
- no border
- no shadow

This is used where the screen should not look like a separate white title card.

## Workspace Density

The newer landing page established a denser visual language, and the main project tools were tightened to match it.

Within `.project-workspace-tool-panel` the CSS reduces:

- normal paragraph text size slightly
- content panel padding
- inter-panel vertical gaps
- table cell padding
- control/button sizing
- spacing above bottom action rows

Heading sizes are intentionally left alone so page hierarchy remains strong.

Bottom action rows should sit reasonably close to the content they act on instead of floating far below the last panel.

## Recent Jobs / Job History Styling

The project landing page's Recent Jobs area uses a compact table modeled after the full Job History table.

Recent rows can expand to reveal detail. The full Job History feature remains more feature-rich and uses its own query/filter/column controls.

## Results Styling

Results remains in the same persistent workspace environment as Job History and Job Runner.

Results-specific content uses `.child-container-results-page` plus compact workspace overrides. The Results title uses the shared `HeaderTitle` treatment and should align with the content without phantom icon spacing.

## NVFlare Manager Styling

`NVFlareClientSnapshot` accepts `embedded` and `showBorder` props.

The landing NVFlare Manager uses an embedded/borderless snapshot so it does not create a redundant box inside the right-hand workspace.

The Job Runner submission page can use the same component with the border enabled.

## Animation

The application uses short fade/translate animations for:

- top-level content entry
- project landing page changes
- Projects accordion open/close
- selected-project Job History / Job Runner submenu open/close

Project landing content is keyed by project ID so switching projects can replay the entry animation.

## Responsive Behavior

Desktop behavior prioritizes the sticky left rail and wide right workspace.

At narrower breakpoints, the landing layout reflows so navigation/content do not require a fixed desktop-width two-column surface. Feature grids use responsive `auto-fit`/`minmax` layouts where appropriate.

## CSS Maintenance Rules

- Consolidate duplicate exact selectors in the same CSS scope.
- Keep media-query overrides separate when they intentionally differ by breakpoint.
- Do not reintroduce dummy left-nav spacer divs into project feature pages.
- Keep project landing function cards separate from Job Runner function cards.
- Prefer shared `secondary-button` styling over one-off secondary button definitions.
- Preserve navigation hover behavior: no dramatic filled hover backgrounds.
- Keep stale content visible during background refresh instead of creating loading-state layout flashes when possible.
