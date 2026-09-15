# NVFlare Manager and Client Snapshot

## Files Covered

- `src/features/nvflare_manager/components/NVFlareManagerContent.tsx`
- `src/features/nvflare_manager/NVFlareManagerMain.tsx`
- `src/components/NVFlareClientSnapshot.tsx`
- `src/components/RefreshablePanel.tsx`
- `src/components/CompactBanner.tsx`
- `src/pages/NavigationSelector.tsx`
- `src/components/ProjectListComponent.tsx`
- `src/App.tsx`

## Feature Role

NVFlare Manager provides a global view of NVFlare client/server connection state. In the current application it is primarily embedded in the persistent SHARE landing/workspace shell rather than opened through a separate project-specific navigation page.

The same `NVFlareClientSnapshot` component is reused by Job Runner submission screens, where it can also display participation state and allow contributing/analyzing selections.

## Global NVFlare Manager Navigation

`NavigationSelector.tsx` exposes **NVFlare Manager** as a global left-navigation item for INITIATOR users.

Selecting it changes the top-level screen to:

```ts
"nvflare_manager"
```

and `ProjectListComponent` renders NVFlare manager content in the right-hand workspace. Project selection is not required to open the global manager.

The left navigation remains pinned while the right-side client connection content scrolls.

## `NVFlareManagerContent`

`NVFlareManagerContent.tsx` is a thin wrapper around `NVFlareClientSnapshot`.

Props:

| Prop | Type | Default | Purpose |
| --- | --- | --- | --- |
| `embedded` | `boolean` | `false` | Enables landing-workspace layout behavior. |
| `showBorder` | `boolean` | `true` | Controls whether the snapshot's outer panel border/shadow treatment is rendered. |

The landing page uses the embedded/borderless combination so Client Connections sits naturally against the workspace without preserving an obsolete internal navigation offset.

The Job Runner reuse keeps the bordered panel behavior.

## `NVFlareClientSnapshot`

### Main Props

| Prop | Type | Purpose |
| --- | --- | --- |
| `projectId` | `number?` | Project context for participation/status requests. |
| `filtersPayload` | `any` | Selected filter payload used when requesting participation state. |
| `functionsMap` | `FunctionConfigs?` | Selected computation functions/configurations. Presence enables participation mode. |
| `thresholdConfig` | `ThresholdConfig?` | Optional threshold configuration. |
| `header` | `string?` | Panel heading; defaults to `Participants Status`. |
| `heartbeatWindowMs` | `number?` | Client heartbeat freshness window. |
| `onState` | callback | Reports loading/client state to parent. |
| `onParticipationSelectionChange` | callback | Reports non-contributing/analyzing exclusions. |
| `onError` | callback | Reports errors. |
| `compact` | `boolean?` | Optional compact summary rendering retained for reuse. |
| `canSubmit` | `boolean?` | Enables submission-related selection behavior. |
| `embedded` | `boolean?` | Removes layout assumptions meant for standalone feature pages. |
| `showBorder` | `boolean?` | Toggles outer border/shadow treatment. |

## Connection-Only Versus Participation Mode

The component computes participation mode from the presence of both:

- a non-empty `functionsMap`
- a defined `filtersPayload`

When those are absent, the global NVFlare Manager acts as a connection-status view.

When they are present, as in Job Runner submission, the component also requests participation details and exposes contributing/analyzing selection state.

## Backend Endpoints Used

The component uses:

```http
POST /clients/connection/status
POST /clients/participation/status
```

Connection status is the primary global Manager endpoint. Participation status is used when the Job Runner supplies project/filter/function context.

## Global Manager Cache / Loading Behavior

The landing-page NVFlare Manager is designed for repeated navigation. `NVFlareClientSnapshot.tsx` keeps the last successful global manager client list in module-level cache.

When the user leaves NVFlare Manager and later returns:

- previous client rows remain visible
- a new request starts in the background
- the table updates when the new response arrives

This avoids the visible full-panel `Loading...` flash that occurred when the component discarded all prior state on navigation.

The cache behavior is scoped to the landing manager scenario:

```ts
embedded && projectId == null && !functionsMap
```

Job Runner participation state is not treated as global reusable connection cache.

## Connection Status Model

`ClientStatus` includes fields such as:

- `id`
- `name`
- `connected`
- optional participation state
- last connect/check-in timestamp
- server/initiator/submitted-user flags
- registered flag
- contributing/analyzing flags

The component normalizes display labels and presents client/server rows according to the mode in which it is rendered.

## Participation Selection

When participation controls are active, the component reports:

```ts
interface ClientParticipationSelection {
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
}
```

Server rows cannot be selected as participants. Initiator/server analyzing state can also be locked according to the existing rules.

## Relationship to Job Submission

The Job Runner submission page reuses `NVFlareClientSnapshot` to:

1. verify client connectivity
2. load participation responses
3. allow supported contribution/analyzing overrides
4. pass the resulting exclusion arrays into the submission payload

This is why the component's border/layout behavior is controlled by props rather than hardcoded specifically for the global Manager page.

## Standalone Wrapper

`NVFlareManagerMain.tsx` still exists as a separately routable wrapper and can render `NVFlareManagerContent` with a `HeaderTitle` and return action. The main authenticated navigation path, however, uses the embedded landing/workspace rendering through `ProjectListComponent`.

## Styling Notes

Landing-specific styling should avoid:

- legacy left-navigation spacer/dummy divs
- forced `100vw` widths inside the right workspace
- a duplicate outer border when the parent landing panel already owns the visual surface

Use the `embedded` and `showBorder` props instead of adding page-specific DOM placeholders.
