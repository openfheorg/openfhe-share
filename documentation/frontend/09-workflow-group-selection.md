# Workflow Group Selection

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_runner/pages/WorkflowGroupSelectionPage.tsx` | Current workflow group selection page. The uploaded frontend does not contain a `pages/workflow_group_selection/` subdirectory; the implementation is a single page file directly under `pages/`. |
| `src/features/job_runner/JobRunnerMain.tsx` | Detects whether the selected project has workflow groups, owns selected workflow group state, inserts the workflow step into the job runner screen sequence, and passes selections into job submission. |
| `src/features/job_runner/pages/JobSubmissionPage.tsx` | Adds workflow group selections to the `/nvflare/jobs/submit` payload as `workflow_group_data` when selections exist. |
| `src/features/job_runner/components/SubmissionOverview.tsx` | Displays selected workflow group options in the final submission overview. |
| `src/types/Project.tsx` | Defines the project, workflow group, workflow group option, and selected workflow group TypeScript shapes. |

## Workflow Group Feature Role

Workflow groups represent project-level grouped execution choices that can modify how a job is staged and run.

In the current frontend, workflow group data is not loaded by a separate workflow-group-specific API call. It is expected to be present on the selected `Project` object as `project.workflow_groups`. That `Project` object is passed into `JobRunnerMain.tsx` from the top-level project selection/session flow.

The workflow group step is only inserted into the job runner flow when the selected project has at least one valid workflow group.

Workflow group selections can affect backend job staging by changing:

- which workflow variants are generated
- which model or method options are selected
- which workflow IDs are submitted
- which function configuration is duplicated or expanded
- which workflow group selections are logged into job history

The frontend itself does not expand workflow IDs. It collects the selected option values and submits them to the backend as `workflow_group_data`.

## Current File Layout

The current uploaded frontend contains this workflow group file:

```text
src/features/job_runner/pages/WorkflowGroupSelectionPage.tsx
```

There is no current `src/features/job_runner/pages/workflow_group_selection/` directory in the uploaded source.

Related files:

```text
src/features/job_runner/JobRunnerMain.tsx
src/features/job_runner/pages/JobSubmissionPage.tsx
src/features/job_runner/components/SubmissionOverview.tsx
src/types/Project.tsx
```

`src/components/FunctionSelector.tsx` is part of the broader job runner function-selection flow, but the current workflow group selection page does not import or render `FunctionSelector`. Workflow group selection is rendered with checkbox inputs directly inside `WorkflowGroupSelectionPage.tsx`.

## TypeScript Shapes

Workflow group project metadata is defined in `src/types/Project.tsx`.

### `ProjectWorkflowGroupOption`

```ts
export interface ProjectWorkflowGroupOption {
  id?: number;
  option_key?: string;
  option_label?: string;
  option_value: string;
  option_order?: number;
}
```

`option_value` is required and is the value submitted in selected workflow group payloads. `option_label` is used for display when available. `option_key` is used as part of the rendered option DOM key/help-state key when available. `option_order` controls option ordering.

The workflow page also checks optional runtime fields that are not currently declared on the interface:

```ts
option_description
```

or:

```ts
description
```

Those fields are used as help text when present.

### `ProjectWorkflowGroup`

```ts
export interface ProjectWorkflowGroup {
  id?: number;
  group_key: string;
  group_label: string;
  group_description?: string | null;
  min_selected?: number | null;
  max_selected?: number | null;
  is_required?: boolean;
  page_order?: number;
  options: ProjectWorkflowGroupOption[];
}
```

`group_key` is the stable key used in selected workflow group state and in the submitted payload. `group_label` is the user-facing title. `group_description` is displayed under the group heading when present. `min_selected` and `max_selected` drive validation in the workflow group page. `page_order` controls group ordering.

### `WorkflowGroupSelection`

```ts
export interface WorkflowGroupSelection {
  group_key: string;
  selected_values: string[];
}
```

Each selected group stores its own `group_key` and an array of selected option values.

### `WorkflowGroupData`

```ts
export type WorkflowGroupData = Record<string, WorkflowGroupSelection>;
```

The record key is the workflow group key. A typical selected value looks like this:

```json
{
  "modeling_method": {
    "group_key": "modeling_method",
    "selected_values": ["cox_lasso", "logistic_reg"]
  }
}
```

The exact group key and selected values come from `project.workflow_groups`.

## State Ownership in `JobRunnerMain.tsx`

`JobRunnerMain.tsx` owns the workflow group state:

```ts
const [workflowGroupData, setWorkflowGroupData] = useState<WorkflowGroupData>({});
```

Initial state is an empty object. The current implementation does not preselect default workflow group options. A required workflow group must be selected by the user before the page allows advancement.

The selected data is passed into:

- `WorkflowGroupSelectionPage.tsx` for editing
- `JobSubmissionPage.tsx` for payload submission
- `SubmissionOverview.tsx` through `JobSubmissionPage.tsx` for final review display

The current `onBackToHistory()` reset path clears saved job/result/filter display state, but it does not explicitly reset `workflowGroupData`. Starting a new filter set resets filter-related state and moves forward through the flow, but workflow group selections remain in `JobRunnerMain.tsx` unless changed by the user or the component is remounted.

## Detecting Whether Workflow Groups Are Supported

`JobRunnerMain.tsx` determines whether the selected project supports workflow groups by reading `project.workflow_groups`.

The helper logic:

```ts
function getOrderedWorkflowGroups(project: Project): ProjectWorkflowGroup[] {
  const raw = (project as any)?.workflow_groups;
  if (!Array.isArray(raw)) return [];

  return [...raw]
    .filter((group) => group && typeof group.group_key === "string" && Array.isArray(group.options))
    .sort((a, b) => {
      const aOrder = typeof a?.page_order === "number" ? a.page_order : Number.MAX_SAFE_INTEGER;
      const bOrder = typeof b?.page_order === "number" ? b.page_order : Number.MAX_SAFE_INTEGER;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return String(a?.group_label || a?.group_key || "").localeCompare(String(b?.group_label || b?.group_key || ""));
    });
}
```

The support flag is computed as:

```ts
const supportsWorkflowGroups = useMemo(
  () => getOrderedWorkflowGroups(project).length > 0,
  [project]
);
```

A project is treated as workflow-group-capable only when `workflow_groups` is an array with at least one object that has a string `group_key` and an `options` array.

## Job Runner Screen Flow

`JobRunnerMain.tsx` includes workflow groups in the internal job runner screen union:

```ts
type JobRunnerScreen =
  | "filterHistory"
  | "patientFilters"
  | "variantTable"
  | "workflow_groups"
  | "functionSelection"
  | "submit_function"
  | "results";
```

The screen sequence is built dynamically:

```ts
const orderedScreens = useMemo<JobRunnerScreen[]>(() => {
  const s: JobRunnerScreen[] = ["filterHistory"];
  if (supportsPatientScreens) s.push("patientFilters");
  if (supportsObservationScreen) s.push("variantTable");
  if (supportsWorkflowGroups) s.push("workflow_groups");
  s.push("functionSelection", "submit_function", "results");
  return s;
}, [supportsPatientScreens, supportsObservationScreen, supportsWorkflowGroups]);
```

This means workflow group selection appears after filter screens and before function selection, but only for projects with workflow groups.

The patient-filter branch uses this helper to skip directly to workflow groups when observation filters are not enabled but workflow groups are enabled:

```ts
function getPostPatientScreen(supportsObservationScreen: boolean, supportsWorkflowGroups: boolean): JobRunnerScreen {
  if (supportsObservationScreen) return "variantTable";
  if (supportsWorkflowGroups) return "workflow_groups";
  return "functionSelection";
}
```

The observation filter branch goes to workflow groups when supported:

```ts
processAndSetScreen(supportsWorkflowGroups ? "workflow_groups" : "functionSelection");
```

The workflow group page is rendered by this branch:

```tsx
{screen === "workflow_groups" && supportsWorkflowGroups && (
  <WorkflowGroupSelectionPage
    project={project}
    workflowGroupData={workflowGroupData}
    setWorkflowGroupData={setWorkflowGroupData}
    onBack={() => processAndSetScreen(getPrevScreen("workflow_groups"))}
    onNext={() => processAndSetScreen(getNextScreen("workflow_groups"))}
  />
)}
```

The function selection page adjusts its back button label when the previous screen is workflow group selection:

```ts
getPrevScreen("functionSelection") === "workflow_groups"
  ? "Back to Workflow Selection"
```

## Props Passed to `WorkflowGroupSelectionPage`

`WorkflowGroupSelectionPage.tsx` receives:

| Prop | Type | Purpose |
| --- | --- | --- |
| `project` | `Project` | Supplies `workflow_groups` metadata, labels, descriptions, validation limits, and options. |
| `workflowGroupData` | `WorkflowGroupData` | Current selected workflow group values. |
| `setWorkflowGroupData` | `React.Dispatch<React.SetStateAction<WorkflowGroupData>>` | Parent-owned setter used to update selected values. |
| `onBack` | `() => void` | Moves to the previous job runner screen using `getPrevScreen("workflow_groups")`. |
| `onNext` | `() => void` | Moves to the next job runner screen using `getNextScreen("workflow_groups")`. |

## Workflow Group Page Rendering

`WorkflowGroupSelectionPage.tsx` sorts groups by:

1. numeric `page_order`, when present
2. `group_label` or `group_key` alphabetically as fallback

For each group, it renders:

- a section using `patient-filter-section`
- a header using `patient-filter-section-header`
- the group label in an `h3`
- the group description when `group_description` is present
- one checkbox card per option

Each option is sorted by:

1. numeric `option_order`, when present
2. `option_label` or `option_value` alphabetically as fallback

Each option displays:

- a checkbox
- `option_label` when present, otherwise `option_value`
- a `HelpToggle` when `option_description` or `description` exists
- a `HelpPanel` containing the help text

The option help open/closed state is local to `WorkflowGroupSelectionPage.tsx`:

```ts
const [openHelpByOption, setOpenHelpByOption] = useState<Record<string, boolean>>({});
```

The help-state key is built from:

```ts
`${group.group_key}_${option.option_key || option.option_value}`
```

## Selection Behavior

Checkbox changes call `toggleOption(group.group_key, String(option.option_value))`.

The state update reads the existing selected values for that group, removes the clicked value if already selected, or appends the clicked value if not selected:

```ts
const existing = prev[groupKey]?.selected_values || [];
const nextValues = existing.includes(optionValue)
  ? existing.filter((value) => value !== optionValue)
  : [...existing, optionValue];

return {
  ...prev,
  [groupKey]: {
    group_key: groupKey,
    selected_values: nextValues
  }
};
```

The page does not disable individual checkboxes when `max_selected` has already been reached. Instead, it allows the state to exceed the maximum and disables the next-step button until validation passes.

## Validation Rules

Validation is performed in `WorkflowGroupSelectionPage.tsx` using `min_selected` and `max_selected`.

The page-level validation helper uses:

```ts
const minSelected = typeof group?.min_selected === "number" ? group.min_selected : 0;
const maxSelected = typeof group?.max_selected === "number" ? group.max_selected : null;
```

Current page validation behavior:

| Condition | Result |
| --- | --- |
| `selected_values.length < min_selected` and `min_selected === 1` | Error: `Select at least one {group_label}.` |
| `selected_values.length < min_selected` and `min_selected > 1` | Error: `Select at least {min_selected} options for {group_label}.` |
| `selected_values.length > max_selected` and `max_selected === 1` | Error: `Select no more than one {group_label}.` |
| `selected_values.length > max_selected` and `max_selected > 1` | Error: `Select no more than {max_selected} options for {group_label}.` |

All validation errors are displayed below the group list in red text. The `Set Function Configuration` button is disabled while any group has a validation error.

The `is_required` field exists on `ProjectWorkflowGroup`, but the current `WorkflowGroupSelectionPage.tsx` validation does not use it directly. Required behavior is enforced only when `min_selected` is set above `0` in the project workflow group metadata.

`JobRunnerMain.tsx` also has a separate helper named `getWorkflowGroupValidationError()` that treats `is_required` as implying a minimum of `1`, but that helper is not used by the rendered workflow group page. The active rendered validation is the logic inside `WorkflowGroupSelectionPage.tsx`.

## Job Submission Integration

`JobRunnerMain.tsx` passes the selected workflow group data into `JobSubmissionPage.tsx`:

```tsx
<JobSubmissionPage
  ...
  workflowGroupData={workflowGroupData}
/>
```

`JobSubmissionPage.tsx` includes workflow group data in the submit payload only when the object exists and has at least one key:

```ts
if (workflowGroupData && Object.keys(workflowGroupData).length > 0) {
  payload.workflow_group_data = workflowGroupData;
}
```

The final backend payload field is:

```json
"workflow_group_data"
```

Example submit payload fragment:

```json
{
  "project_id": 1,
  "filters": {
    "patient_query": {},
    "patient_data": {},
    "observation_query": {},
    "observation_data": {}
  },
  "functions_map": {
    "survivability": {
      "name": "survivability"
    }
  },
  "submitter": "example.user",
  "datasource_group": 2,
  "workflow_group_data": {
    "modeling_method": {
      "group_key": "modeling_method",
      "selected_values": ["cox_lasso", "logistic_reg"]
    }
  },
  "non_contributing_clients": [],
  "exclude_analyzing_clients": []
}
```

The exact `filters` and `functions_map` contents depend on selected filters and selected function configuration. Workflow group selections are submitted alongside those fields rather than embedded inside either one.

## Final Submission Overview Display

`SubmissionOverview.tsx` receives:

```ts
workflowGroupData?: WorkflowGroupData | null;
project: Project;
```

It builds display rows by matching each selected value back to the selected project metadata:

```ts
const selectedValues = workflowGroupData?.[group.group_key]?.selected_values || [];
const matchedOption = options.find(
  (option) => String(option?.option_value) === String(selectedValue)
);
```

The overview displays workflow group selections under:

```text
Custom Workflow Options
```

The display table has two columns:

- `Group`
- `Selected Option`

For each selected option, it displays the project workflow group label and the matching option label. If no option label matches, it displays the raw selected value.

## Relationship to Function Selection

Workflow group selection and function selection are related but separate.

Workflow group selection identifies project-level grouped execution options. Function selection identifies the computation/function configuration to submit.

The frontend sequence is:

1. collect filters
2. collect workflow group selections, if the project defines workflow groups
3. collect function configuration
4. review final submission
5. submit one payload containing both `functions_map` and `workflow_group_data`

`FunctionSelectionPage.tsx` does not receive `workflowGroupData`. The two selections meet in `JobSubmissionPage.tsx`, where both are included in the final payload.

## Backend Fields That Receive Workflow Group Data

The frontend sends selected workflow group data to the backend submit endpoint as:

```json
"workflow_group_data": {
  "<group_key>": {
    "group_key": "<group_key>",
    "selected_values": ["<option_value>"]
  }
}
```

The backend endpoint is the job submission endpoint represented by the frontend constants imported in `JobSubmissionPage.tsx`:

```ts
API_BASE
API_SUBMIT_JOB
```

The frontend request is:

```ts
fetch(`${API_BASE}${API_SUBMIT_JOB}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
```

The frontend documentation can verify that the submitted field name is `workflow_group_data`. The uploaded frontend zip does not include the backend route implementation, so backend persistence/staging behavior must be verified against the backend source separately.

## Error and Loading Behavior

Workflow group selection itself does not make a backend request and has no loading state.

Error behavior is validation-driven:

- validation errors are computed from the current selected values and project workflow group metadata
- errors are displayed as red text below the workflow group sections
- the next button is disabled until all validation errors clear

Submission-time errors are handled in `JobSubmissionPage.tsx`. If the submit request fails, the page displays an error panel and stops submitting. If the submit succeeds and the response includes `job_id`, the page starts job status tracking for that job.

## Known Implementation Notes

- The source contains workflow group type definitions in both `src/types/Project.tsx` and `JobRunnerMain.tsx`. `WorkflowGroupSelectionPage.tsx` and `JobSubmissionPage.tsx` import the shared types from `src/types/Project.tsx`; `JobRunnerMain.tsx` also declares local workflow group interfaces with the same shape.
- `is_required` is present in the project type and in `JobRunnerMain.tsx` helper logic, but the active workflow group page uses `min_selected` and `max_selected` only.
- The workflow group page allows users to temporarily select more than `max_selected`; it blocks advancement rather than preventing the checkbox action.
- The current implementation does not explicitly clear `workflowGroupData` when starting a new filter set from `FilterHistoryTable`.
- Workflow group option descriptions are supported at runtime through `option_description` or `description`, even though those fields are not currently part of the declared `ProjectWorkflowGroupOption` interface.
