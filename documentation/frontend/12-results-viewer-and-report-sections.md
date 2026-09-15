# Results Viewer and Report Sections

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_history/pages/ResultsPage.tsx` | Main results viewer page. Loads NVFlare job info, workflow mappings, workflow result payloads, function configuration, profile/system metrics, and export modal state. |
| `src/features/job_history/components/` | Result/report display components used by the job history table and results page. |
| `src/features/job_history/components/export/` | Export registry and export selection modals used by results sections. |
| `src/features/job_history/utils/JobsDataUtils.tsx` | Job/result API helpers, workflow result normalization, profile summary types, workflow error extraction, and metric formatting helpers. |
| `src/features/job_history/utils/ExportDocTypes.tsx` | Shared export document/section/block/workflow TypeScript types. |
| `src/features/job_history/utils/ExportDocumentRenderUtils.tsx` | Shared export rendering helpers used by PDF/DOCX/HTML utilities. |
| `src/features/job_history/utils/ExportPdfUtils.tsx` | PDF export renderer/downloader. |
| `src/features/job_history/utils/ExportDocxUtils.tsx` | DOCX export renderer/downloader. |
| `src/features/job_history/utils/ExportHtmlUtils.tsx` | HTML export renderer/downloader. |
| `src/features/job_history/utils/ExportPngUtils.tsx` | PNG export helper for screen capture of the rendered results root. |
| `src/components/FilterSummary.tsx` | Shared selected-filter display used at the bottom of the results page. |
| `src/components/AbstractAccordion.tsx` | Shared accordion display component used by summary/config/metrics sections. |
| `src/components/HeaderTitle.tsx` | Results title presentation, including transparent-background support. |
| `src/pages/SHARELandingPage.tsx` / `NavigationSelector.tsx` | Persistent landing/workspace shell that remains visible around top-level Results. |

There is no `src/features/job_history/types/` directory in the current frontend archive, and there is no `src/features/job_history/constants/` directory in the current frontend archive. Job/result-specific types are currently split between `src/types/JobsDataTypes.tsx`, `src/features/job_history/utils/JobsDataUtils.tsx`, and `src/features/job_history/utils/ExportDocTypes.tsx`.

## Results Viewer Role

The results viewer displays the details of a selected job from job history.

It brings together:

- job metadata loaded from `/jobs/info`
- selected project context passed from `JobHistoryMain.tsx`
- datasource metadata from the job info response and `UserRoleContext`
- participation exclusions from the job record
- selected filters reconstructed from the saved filter ID before the page is opened
- workflow IDs loaded per supported function
- per-workflow result payloads
- per-workflow function configuration
- workflow error payloads embedded in result data
- analytics/profile metrics loaded through the workflow mapping response
- exportable report sections registered by the rendered result components

Results can be reached in two ways. `JobHistoryMain.tsx` still has an internal `results` screen for full Job History navigation, while the landing page and SHARE Client direct-entry path use top-level `AppScreen = "job_results"` so Results can remain inside the persistent SHARE workspace with the owning project selected.

## Results Page Props

`ResultsPage.tsx` defines this props interface:

```ts
interface ResultsPageProps {
  onBack: () => void;
  onStartOver: () => void;
  submittedFilterSet: FilterCollection;
  submittedFilterSetName: string;
  savedJobInfo?: JobLogData;
  viewOnly?: boolean;
  onBackToHistory?: () => void;
  directEntry?: boolean;
  nvflareJobId?: string;
  project?: Project;
  onContextLoaded?: (project: Project) => void;
}
```

| Prop | Source | Use |
| --- | --- | --- |
| `onBack` | `JobHistoryMain.tsx` | Returns from results to the job history screen. In non-view-only mode the button label is `Back to Submission Details`, but in the current job-history flow this callback still returns to job history. |
| `onStartOver` | `JobHistoryMain.tsx` | Returns to job history when the user clicks `⟳ Start Over` in non-view-only mode. |
| `submittedFilterSet` | `JobHistoryMain.tsx` | Filter collection reconstructed from the saved job filter before opening results. Falls back to `BLANK_FILTER_CONFIG` if unavailable. |
| `submittedFilterSetName` | `JobHistoryMain.tsx` | Saved filter name displayed by `FilterSummary`. Falls back to an empty string if unavailable. |
| `savedJobInfo` | `JobHistoryMain.tsx` | Carries the NVFlare assigned ID, job status, run duration, and functions from the selected history row. |
| `viewOnly` | `JobHistoryMain.tsx` | Controls the footer buttons. Job-history-opened results use view-only behavior. |
| `onBackToHistory` | `JobHistoryMain.tsx` | Used by the view-only footer button labeled `Back to Job History`. |
| `directEntry` | Landing/direct Results flow | Enables results-context bootstrap when a full Job History state object is not already available. |
| `nvflareJobId` | `App.tsx` / landing workspace | Explicit NVFlare job ID for direct/top-level Results. |
| `project` | Job History or landing workspace | Optional project context; direct entry can resolve it from results context. |
| `onContextLoaded` | Landing workspace | Reports the resolved project so the persistent left navigation can select the correct project. |

`JobHistoryMain.tsx` builds `savedJobInfo` from the selected `NVFlareJob` row when the row has `filter_id` and `nvflare_assigned_id`:

```ts
{
  jobId: job_data.job_runner_id,
  jobStatus: job_data.status,
  jobLog: [],
  referencedBy: [job_data.nvflare_assigned_id],
  run_duration: job_data.run_duration,
  functions: job_data.functions
}
```

The results page uses `savedJobInfo?.referencedBy?.[0]` as the NVFlare job ID for result loading.

## Results Page State

`ResultsPageInner` owns the following state:

| State | Type/initial value | Purpose |
| --- | --- | --- |
| `survivabilityWorkflows` | `WorkflowJobData[]`, `[]` | Loaded survival-analysis workflow results. |
| `tTestWorkflows` | `WorkflowJobData[]`, `[]` | Loaded T-test workflow results. |
| `meanWorkflows` | `WorkflowJobData[]`, `[]` | Loaded mean workflow results. |
| `chi2Workflows` | `WorkflowJobData[]`, `[]` | Loaded chi-square workflow results. |
| `stDevWorkflows` | `WorkflowJobData[]`, `[]` | Loaded standard-deviation workflow results. |
| `activeSurvIndex` | `number`, `0` | Active survival workflow index. |
| `activeMeanIndex` | `number`, `0` | Active mean workflow index. |
| `activeChi2Index` | `number`, `0` | Active chi-square workflow index. |
| `activeStDevIndex` | `number`, `0` | Active standard-deviation workflow index. |
| `activeTTestIndex` | `number`, `0` | Active T-test workflow index. |
| `loading` | `boolean`, `false` | Controls the loading panel and disables export. |
| `loadError` | `string | null`, `null` | Displays a red error panel when result loading fails. |
| `exportFormatModalOpen` | `boolean`, `false` | Controls the first export modal where the user chooses PDF, Word, HTML, or PNG. |
| `exportSectionModalOpen` | `boolean`, `false` | Controls the section-selection export modal. |
| `selectedExportFormat` | `ExportFormat | null`, `null` | Tracks the export format selected in the first modal. |
| `exportableSections` | `Array<{ id: string; title: string; section: ExportSection }>` | Holds all registered/generated export sections for the selection modal. |
| `exporting` | `boolean`, `false` | Disables/marks export work while export sections or files are being generated. |
| `profileSummary` | `ProfileSummary | null`, `null` | Profile/system/workflow metrics returned by workflow mapping. |
| `nvflareJobInfo` | `NVFlareJob | null`, `null` | Full job information returned by `/jobs/info`. |
| `jobInfoProgress` | `ResultLoadProgress` | Progress label/count for loading NVFlare job information. |
| `mappingProgress` | `ResultLoadProgress` | Progress label/count for loading workflow mappings. |
| `resultsProgress` | `ResultLoadProgress` | Progress label/count for loading workflow result payloads. |

Derived values include:

| Derived value | Purpose |
| --- | --- |
| `role` | Read from the user session and combined with `client_name` into `jobApiSession`, which chooses the backend API base versus the client results agent base. |
| `getSections` | Read from `useExportRegistry()` for export section collection. |
| `nvflareJobId` | `savedJobInfo?.referencedBy?.[0]`; primary result-loading ID. |
| `savedAvailableFunctions` | Normalized from `savedJobInfo?.functions`. |
| `runDurationTime` | `nvflareJobInfo?.run_duration || savedJobInfo?.run_duration`. |
| `hasSurvResults` | True when survival workflow results were loaded. |
| `hasMeanResults` | True when mean workflow results were loaded. |
| `hasChi2Results` | True when chi-square workflow results were loaded. |
| `hasStDevResults` | True when standard-deviation workflow results were loaded. |
| `hasTTestResults` | True when T-test workflow results were loaded. |
| `hasAnyScalarResults` | True when one or more scalar metric result sections are rendered. |
| `jobInfoProgressPercent` | Progress percentage for the job info loading bar. |
| `mappingProgressPercent` | Progress percentage for the workflow mapping loading bar. |
| `resultsProgressPercent` | Progress percentage for the workflow results loading bar. |

## Result Loading Flow

`ResultsPage.tsx` loads result data in a `useEffect` keyed by:

```ts
[
  directEntry,
  jobApiSession,
  nvflareJobId,
  onContextLoaded,
  projectProp,
  savedAvailableFunctions,
  submittedFilterSet,
  submittedFilterSetName,
]
```

`jobApiSession` is a memoized `{ role, client_name }` object built from the user session. It is what the result helpers use to resolve their API base.

The load sequence is:

1. Clear old error/result/profile/job-info state.
2. Stop immediately if `nvflareJobId` is missing.
3. Set `loading` to `true`.
4. Call `fetchNVFlareJobInfo(nvflareJobId, jobApiSession)`.
5. If `/jobs/info` fails, log a warning and continue with `savedAvailableFunctions`.
6. Determine functions to load by comparing the job's functions to `RESULT_FUNCTION_LOAD_ORDER`.
7. For each function, call `fetchWorkflowMapping(nvflareJobId, functionName, jobApiSession)`.
8. Use the returned `workflow_dirs` as workflow IDs, sorted by `JobsDataUtils.sortWorkflowIds`.
9. For each workflow ID, call `fetchJobResultsForWorkflow(nvflareJobId, functionName, workflowId, jobApiSession)`.
10. Store returned `jobData`, `functionConfig`, and `workflowError` in a `WorkflowJobData` object.
11. Attach workflow title suffixes parsed from workflow IDs containing `__`.
12. Store results into the function-specific workflow state arrays.
13. Reset all active workflow indexes to `0`.
14. Set `loading` to `false` in `finally` unless the effect was cancelled.

`RESULT_FUNCTION_LOAD_ORDER` is:

```ts
[
  SupportedFunction.SURVIVAL_ANALYSIS,
  SupportedFunction.MEAN,
  SupportedFunction.STANDARD_DEVIATION,
  SupportedFunction.CHI_SQUARE_TEST,
  SupportedFunction.T_TEST,
]
```

Only functions present in the loaded job info or saved job info are requested. The page does not attempt to load result types for functions absent from the selected job.

## Backend Calls Used by Results Loading

`JobsDataUtils.tsx` resolves the base URL for the per-workflow helpers with `resolveResultsApiBase(userSession)`:

```ts
role !== UserRole.CLIENT ? API_BASE : getClientApiBase(client_name)
```

For a `CLIENT` session, `getClientApiBase` returns the per-site results agent base, so `base` is `http://127.0.0.1:8089` for `site1` in local development and standalone builds. The remaining helpers always use `API_BASE`.

| Helper | Endpoint | Request body | Response shape used |
| --- | --- | --- | --- |
| `fetchNVFlareJobInfo` | `POST ${API_BASE}/jobs/info` | `{ nvflare_job_id }` | `{ job?: NVFlareJob | null, error?: string }` |
| `fetchWorkflowMapping` | `POST ${base}${API_JOB_RESULTS_MAPPING}` | `{ nvflare_job_id, function }` | `{ workflow_dirs?: string[], profile_summary?: ProfileSummary, error?: string }` |
| `fetchJobResultsForWorkflow` | `POST ${base}${API_JOB_RESULTS}` | `{ nvflare_job_id, function, workflow_id }` | `{ job_data?: JobsDataShape, function_config?: FunctionConfig, error?: string }` |
| `fetchFunctionConfigForWorkflow` | `POST ${API_BASE}${API_JOB_RESULTS_FUNCTION_CONFIG}` | `{ nvflare_job_id, function, workflow_id }` | `{ function_config?: FunctionConfig, error?: string }` |

`fetchJobResultsForWorkflow` calls the function-config endpoint only if the result payload does not include a usable `function_config`.

`postJson` throws `Request failed ${status}: ${text || url}` when the HTTP response is not OK. If a response JSON contains `error`, the helper throws that error string.

## Core Result Types

`src/types/JobsDataTypes.tsx` defines the current job metadata type used by results:

```ts
export interface NVFlareJob {
  id: number;
  nvflare_assigned_id?: string;
  filter_id?: number;
  status?: string;
  job_path?: string;
  output_path?: string;
  job_runner_id?: string;
  non_contributing_clients?: string | null;
  exclude_analyzing_clients?: string | null;
  submit_time?: string;
  run_duration?: string;
  create_date: string;
  update_date: string;
  completed_date?: string;
  functions?: string[];
  functions_map?: Record<string, Record<string, string> | Record<string, string>[]>;
  threshold?: ThresholdPayload;
  crypto_audit_record?: CryptoAuditRecord;
  datasource_group_id?: number | null;
  datasource_group_name?: string | null;
  datasource_log?: DatasourceLogPayload;
  workflow_group_data?: Record<string, string[]>;
  workflow_groups?: WorkflowGroupSelection[];
}
```

`JobsDataUtils.tsx` defines the loaded workflow result shape:

```ts
export type WorkflowJobData = {
  workflowId: string;
  functionName: string;
  jobData: JobsDataShape;
  functionConfig?: FunctionConfig | null;
  workflowError?: WorkflowErrorJson | null;
};
```

`FunctionConfig` is currently:

```ts
export type FunctionConfig = Record<string, string>;
```

`JobsDataShape` is currently `any` from `SurvivabilityComponent.tsx`.

## Report Section Component Map

| Section/component | File | Rendered where | Data source |
| --- | --- | --- | --- |
| Job Summary | `NVFlareJobSummary.tsx` | Top of `ResultsPage.tsx` when `nvflareJobInfo` is available | `/jobs/info` response plus selected datasource context from `UserRoleContext` |
| Survival/Kaplan-Meier results | `SurvivabilityComponent.tsx` | `ResultsPage.tsx` when `survivabilityWorkflows.length > 0` | `/jobs/results/mapping`, `/jobs/results`, optional `/jobs/function/config`, `profileSummary.workflows` |
| Kaplan-Meier plot | `KaplanMeierPlot.tsx` | Inside `SurvivabilityComponent` | Survival `jobData` processed/aggregated results |
| Scalar result cards | `ResultCard.tsx` | `ResultsPage.tsx` metric grid | Function-specific workflow arrays for T-test, mean, chi-square, and standard deviation |
| System metrics | `AnalyticsMetricsAccordion.tsx` default export `SystemMetricsAccordion` | Below result cards when `profileSummary` exists | `profileSummary.system_metrics`, `profileSummary.combined_workflow_metrics`, run duration |
| Per-workflow analytics metrics | `AnalyticsMetricsAccordion.tsx` named export `WorkflowAnalyticsAccordion` | Inside scalar result cards and survival result sections | `profileSummary.workflows` keyed by workflow ID |
| Function configuration accordion | `FunctionConfigurationAccordion.tsx` | Inside scalar cards and survival cards when workflow config exists | `WorkflowJobData.functionConfig` |
| Filter summary / Filters Overview | `FilterSummary.tsx` | Bottom of `ResultsPage.tsx` | `submittedFilterSet` and `submittedFilterSetName` from `JobHistoryMain.tsx` |
| Workflow error display | `WorkflowErrorPanel.tsx` | Inside scalar and survival workflow cards when result data contains a workflow error | `getWorkflowErrorFromJobData(jobData)` |
| Export format modal | `ExportFormatModal.tsx` | Results page footer flow | Local export state |
| Export section selection modal | `ExportSectionSelectionModal.tsx` | Results page export flow | Registered export sections plus generated Job Summary and Filters Overview sections |

The following job-history components exist in `src/features/job_history/components/` but are primarily used by `JobHistoryTable.tsx` rows or older/detail accordions rather than directly in `ResultsPage.tsx`:

| Component | Purpose |
| --- | --- |
| `ColumnConfigModal.tsx` | Lets the user choose up to three additional function configuration columns in job history. |
| `DatasourceSelectionSection.tsx` | Accordion for saved job datasource details. |
| `EncryptionParamsSection.tsx` | Accordion for crypto audit/security parameters. |
| `FilterSummarySection.tsx` | Loads a saved filter by ID and displays it using `FilterSummary`. |
| `FunctionConfigSection.tsx` | Accordion/table for function configurations attached to a job history row. |
| `LogOutputSection.tsx` | Accordion for job log output. |
| `ParticipationSection.tsx` | Accordion for non-contributing and excluded-analyzing client lists. |
| `ThresholdConfigSection.tsx` | Accordion for threshold method/value display. |
| `WorkflowGroupSelectionSection.tsx` | Accordion for workflow group selections attached to a job history row. |

## Job Summary Section

`NVFlareJobSummary.tsx` renders the top results-page summary accordion when `nvflareJobInfo` is not null.

Props:

```ts
interface NVFlareJobSummaryProps {
  nvflareJob?: NVFlareJobWithParticipation | null;
  boldBorder?: boolean;
  defaultOpen?: boolean;
  isOpen?: boolean;
  onToggle?: () => void;
  enableFunctionLinks?: boolean;
}
```

`ResultsPage.tsx` passes:

```tsx
<NVFlareJobSummary nvflareJob={nvflareJobInfo} enableFunctionLinks />
```

The rendered summary sections are:

| Summary subsection | Fields/behavior |
| --- | --- |
| `Job Details` | `Status`, `Run Duration`, `Submit Time`, `Created`, `Updated`. Internal job ID, NVFlare assigned ID, project ID, and filter ID are present in comments but not rendered in the current component. |
| `Data Source` | Uses `DatasourceSummary` to show `Data source (You)` and, when non-default, `Data source group`. The source is rendered as a blue link when it does not end in `.json`; JSON sources render as plain text. |
| `Party Participation Settings` | Rendered only when `non_contributing_clients` or `exclude_analyzing_clients` has values. Labels are `Excluded from Contributing` and `Excluded from Analyzing`. |
| `Functions` | Shows function buttons when `enableFunctionLinks` is true. Buttons use class `button-href` and scroll to the matching result section anchor. If no functions are returned, displays `No function information was returned.` |
| `Workflow Settings` | Rendered when `workflow_groups` or `workflow_group_data` exists. Uses `group_label`, `group_key`, and selected option labels/values/keys when structured workflow groups exist. |
| `Threshold Settings` | Rendered when `threshold` or `threshold_config_id` has a value. |
| `Security Settings` | Rendered when `crypto_audit_record` has a value. |

Datasource behavior in this summary is intentionally user-specific: the label is `Data source (You)`. `DEFAULT` datasource groups are suppressed, so the group line only appears for non-default groups.

Function summary buttons compute anchors with the same function-name normalization as `ResultsPage.tsx`:

```ts
result-function-${normalizedFunctionName}
```

Examples:

| Function | Anchor ID |
| --- | --- |
| `SURVIVAL_ANALYSIS` | `result-function-survival-analysis` |
| `STANDARD_DEVIATION` | `result-function-standard-deviation` |
| `CHI_SQUARE_TEST` | `result-function-chi-square-test` |
| `T_TEST` | `result-function-t-test` |
| `MEAN` | `result-function-mean` |

`ResultsPage.tsx` gives each top-level function section `scrollMarginTop: "6rem"` to avoid overscrolling under the header/navigation area.

## Workflow-Specific Results

Workflow IDs come from the backend result mapping response field `workflow_dirs`.

For each supported function, the results page stores loaded workflows as:

```ts
{
  workflowId,
  functionName,
  jobData,
  functionConfig,
  workflowError,
  workflowTitleSuffix
}
```

`workflowTitleSuffix` is added locally by parsing workflow IDs that contain `__`. For example, a workflow ID such as:

```text
workflow_stat_analytics__cox_lasso
```

gets the display suffix:

```text
Cox Lasso
```

The suffix is used by result cards to make selected workflow variants clearer in the title.

## Survival Results Section

`ResultsPage.tsx` renders `SurvivabilityComponent` when `survivabilityWorkflows.length > 0`.

Props passed by `ResultsPage.tsx`:

```tsx
<SurvivabilityComponent
  jobsData={null}
  workflowId={undefined}
  functionName="SURVIVAL_ANALYSIS"
  workflows={survivabilityWorkflows}
  activeIndex={activeSurvIndex}
  onActiveIndexChange={setActiveSurvIndex}
  analyticsWorkflows={profileSummary?.workflows ?? null}
  project={project}
  userRole={role}
/>
```

`SurvivabilityComponentProps` are:

```ts
export interface SurvivabilityComponentProps {
  jobsData: JobsDataShape;
  workflowId?: string;
  functionName?: string;
  workflows?: WorkflowJobData[];
  activeIndex?: number;
  onActiveIndexChange?: (index: number) => void;
  analyticsWorkflows?: ProfileSummaryWorkflows | null;
  project: Project;
  userRole: UserRole;
}
```

Important survival rendering behavior:

- Supports one or more `WorkflowJobData` entries.
- Displays workflow-specific function configuration when present.
- Displays workflow errors via `WorkflowErrorPanel` when error data is detected.
- Uses `KaplanMeierPlotUnified` for Kaplan-Meier curves.
- Extracts agent/client versus aggregated results based on user role and available result payload shape.
- Supports survival tables for processed KM series.
- Registers an export section for the survival/Kaplan-Meier content through the export registry.
- For multiple workflows, workflow selection checkboxes control which workflow plots/tables are visible.
- The last selected workflow cannot be unchecked; at least one workflow remains selected.
- When not all workflows are selected, a `Select All` action can restore all workflow selections.

`KaplanMeierPlotUnified` accepts:

```ts
interface Props {
  data?: any;
  seriesMap?: Record<string, KMAggRow[]>;
  plotHeight?: number;
  userRole: UserRole;
  onImageDataUrl?: (dataUrl: string) => void;
}
```

It can extract KM data from several result shapes, including direct `KM_results`, `aggregate_processed_results`, raw grouped `N`/`d` arrays, and legacy aggregate/client payloads.

## Scalar Result Sections

Scalar result cards are implemented by `ResultCard.tsx`.

The exported card components are:

| Component | Title | Function constant used by `ResultsPage.tsx` | Displayed properties |
| --- | --- | --- | --- |
| `TTestResultCard` | `T-Test` | `SupportedFunction.T_TEST` | `T-Score`, `Degrees of Freedom`, `T-Test` |
| `MeanResultCard` | `Mean` | `SupportedFunction.MEAN` | `Mean` |
| `Chi2ResultCard` | `Chi Square Test` | `SupportedFunction.CHI_SQUARE_TEST` | `Chi-Square Value`, `Chi-Square Test` |
| `StDevResultCard` | `Standard Deviation` | `SupportedFunction.STANDARD_DEVIATION` | `Standard Deviation` |

The p-value row of a scalar card is labeled with the test that produced it: `T-Test` on `TTestResultCard` and `Chi-Square Test` on `Chi2ResultCard`. `MeanResultCard` displays the mean only; a mean has no chi-squared statistic and no p-value. `Log-rank test` is not a scalar card label; it is used only by `SurvivabilityComponent.tsx` for the Kaplan-Meier log-rank p-value panel.

Shared scalar props:

```ts
export interface ScalarResultWorkflowProps {
  workflows: WorkflowJobData[];
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  analyticsWorkflows?: ProfileSummaryWorkflows | null;
  project: Project;
  userRole: UserRole;
}
```

Scalar card behavior:

- Returns `null` when no workflows exist.
- Maintains local `selectedWorkflowIds` state.
- Defaults to all available workflows selected.
- Filters out selections that no longer exist when workflow data changes.
- Prevents unchecking the last selected workflow.
- Updates the active workflow index when selected workflows change.
- Shows workflow checkboxes when more than one workflow exists.
- Shows `Select All` when not all workflows are selected.
- Uses a responsive card grid: one card per row by default, two columns at container width `640px`, and three columns at `960px` for three selected workflow cards.
- Displays per-workflow function configuration with `FunctionConfigurationAccordion` when config exists.
- Displays workflow errors with `WorkflowErrorPanel` when detected.
- Displays user-role-specific agent label: `Client` for client role, `Initiator` otherwise.
- Displays aggregated result values when `aggregate_processed_results` exists.
- Builds one row per configured property, using the first key in that property's `keys` list whose value in the result payload is neither `undefined` nor `null`.
- Omits a property row entirely when none of its keys has a value. A `null` `p_value`, such as the chi-square p-value returned for a degenerate contingency table, removes only that row; the remaining rows, for example `Chi-Square Value`, still render.
- Formats p-value rows, meaning any property whose `keys` include `p_value`, with `formatPValueForUI`. That helper renders `p < 0.005` or `p > 0.005` together with `-log₁₀(p)` instead of a raw decimal, and the card falls back to the raw value as a string when the helper cannot format it.
- Formats other numeric rows to the property `precision`, or `defaultPrecision` when the property has none, unless the property sets `exact`, which keeps the raw value. `exact` has no effect on p-value rows.
- Displays `N/A` when no agent or aggregate value rows can be built.
- Displays `WorkflowAnalyticsAccordion` when analytics metrics exist for the workflow.

The scalar result grid on `ResultsPage.tsx` sorts sections by descending workflow count first, then title. It renders one column if there is only one scalar result section and two columns when there are multiple scalar sections:

```ts
gridTemplateColumns:
  metricColumns.length === 1
    ? "minmax(260px, 1fr)"
    : "repeat(2, minmax(260px, 1fr))"
```

## System Metrics and Workflow Analytics

`AnalyticsMetricsAccordion.tsx` exports two components/utility groups:

| Export | Use |
| --- | --- |
| default `SystemMetricsAccordion` | Results-page system-level metrics section. |
| `WorkflowAnalyticsAccordion` | Per-workflow analytics metrics rendered inside result cards. |
| `buildWorkflowAnalyticsExportBlocks` | Adds workflow analytics metrics to export sections. |

`SystemMetricsAccordion` props:

```ts
type SystemMetricsPanelProps = {
  metrics?: Record<string, any> | null;
  combinedMetrics?: Record<string, any> | null;
  runDurationTime?: string;
  role?: UserRole | null;
};
```

`ResultsPage.tsx` renders it only when `profileSummary` exists:

```tsx
<SystemMetricsAccordion
  metrics={profileSummary.system_metrics}
  combinedMetrics={profileSummary.combined_workflow_metrics}
  runDurationTime={runDurationTime}
  role={role}
/>
```

`ProfileSummary` is defined in `JobsDataUtils.tsx`:

```ts
export type ProfileSummary = {
  job_id: string;
  site: string;
  role: string;
  extra: Record<string, unknown>;
  workflows: ProfileSummaryWorkflows;
  system_metrics: ProfileSummarySystemMetrics;
  combined_workflow_metrics?: CombinedWorkflowMetrics | null;
};
```

`fetchWorkflowMapping` computes `combined_workflow_metrics` locally by calling `getCombinedWorkflowMetrics(baseProfile.workflows)` when a profile summary is returned.

System metrics are shown after survival/scalar results and before the filters overview.

## Filters Overview Section

The on-screen filters overview is rendered at the bottom of the results content root:

```tsx
<FilterSummary
  submittedFilterSet={submittedFilterSet}
  submittedFilterSetName={submittedFilterSetName}
/>
```

The filter values come from `JobHistoryMain.tsx`, not from `ResultsPage.tsx` result loading. Before opening results, `JobHistoryMain.tsx` calls `POST ${API_BASE}${API_FILTERS_FETCH_SINGLE}` with:

```ts
{ filter_id: filterId, project_id: project.id }
```

It then transforms `data?.filter?.conditions || []` with `buildDefaultFilterCollectionFromConditions(r.conditions || [], project)` and passes the resulting `FilterCollection` into `ResultsPage`.

The export filters overview is generated separately by `buildFiltersOverviewExportSection(submittedFilterSet, submittedFilterSetName)`. It parses/stringifies nested filter values and flattens display rows into exportable table blocks. It is always pushed after registered component sections during export setup and is moved to the end again before final export output.

## Loading and Error States

When `loading` is true, the results page shows a `Loading Results Data` panel with three progress bars:

| Progress area | Initial label | Later labels |
| --- | --- | --- |
| `NVFlare Job Information` | `Preparing NVFlare job information` | `Loading NVFlare job information`, `Loaded NVFlare job information` |
| `Workflow Mapping` | `Waiting for NVFlare job information` | `Preparing workflow mapping lookup`, `Loading <Function> workflow list`, `Loaded <Function> workflow list`, `Loaded workflow mappings`, `No workflow mappings to load` |
| `Workflow Results Data` | `Waiting for workflow mappings` | `Loading workflow results data`, `Loading <Function> results X of Y`, `Loaded <Function> results X of Y`, `Loaded all results data`, `No workflow results to load` |

The page applies a small artificial result-load delay of `175ms` before clearing `loading`, through `waitForArtificialResultLoadDelay()`.

When `loadError` is set, a red error panel displays the error text above the result sections.

If no survival results, no scalar results, no loading state, and no load error exist, the page renders an empty fragment for the results area. It still renders job summary if job info exists, system metrics if profile summary exists, and filters overview.

The `/jobs/info` call is handled specially: if it fails, the page logs `ResultsPage: Failed to load NVFlare job information` and continues with `savedAvailableFunctions`. Failures in workflow mapping or workflow result loading set `loadError` and stop the normal load sequence.

## Workflow Error Handling

`JobsDataUtils.tsx` defines `WorkflowErrorJson` and `getWorkflowErrorFromJobData(jobData)`.

A result payload is treated as a workflow error when error-like values are found, including:

- `error`
- `message`
- `traceback`
- `exception_type`

`fetchJobResultsForWorkflow` returns:

```ts
{
  jobData,
  functionConfig,
  workflowError
}
```

Result components render `WorkflowErrorPanel` when `workflowError` or an error extracted from `jobData` exists.

## Export Integration

`ResultsPage.tsx` wraps `ResultsPageInner` in `ExportProvider`.

Rendered result components register export sections by calling `useRegisterExportSection`. The registry is used only when the user starts an export.

Export flow:

1. User clicks `Export As...`.
2. `ExportFormatModal` opens.
3. User selects `pdf`, `docx`, `html`, or `png`.
4. `loadExportableSections(format)` stores the selected format and closes the format modal.
5. Results page starts `exporting`.
6. Results page creates a generated `Job Summary` export section first.
7. Results page reads registered sections with `getSections()` and awaits each `exportSection()` callback.
8. Results page appends generated `Filters Overview` export section last.
9. `ExportSectionSelectionModal` opens with the assembled sections.
10. User selects sections/options/workflows.
11. `handleExportSections` filters blocks/workflows/options and exports the selected document.

Generated sections:

| Section | Source | Default position in export selector/output |
| --- | --- | --- |
| `Job Summary` | `buildJobSummaryExportSection(nvflareJobInfo, savedJobInfo)` | First. |
| Component-registered result sections | `useRegisterExportSection` from result components | Between Job Summary and Filters Overview, ordered by registry order. |
| `Filters Overview` | `buildFiltersOverviewExportSection(submittedFilterSet, submittedFilterSetName)` | Last. |

`handleExportSections` creates:

```ts
const document: ExportDocument = {
  title: "SHARE Job Results Export",
  generatedAt: new Date().toLocaleString(),
  sections: selectedSections,
};
```

Export filenames use:

```text
share-results-${YYYY-MM-DD-HH-MM-SS}.pdf
share-results-${YYYY-MM-DD-HH-MM-SS}.docx
share-results-${YYYY-MM-DD-HH-MM-SS}.html
share-results-${YYYY-MM-DD-HH-MM-SS}.png
```

Export dispatch:

| Format | Function |
| --- | --- |
| `pdf` | `downloadPdf(document, filename)` |
| `docx` | `downloadDocx(document, filename)` |
| `html` | `downloadHtml(document, filename)` |
| `png` | `downloadElementAsPng(root, filename)` where `root` is `#share-results-export-root` |

PNG export is different from PDF/DOCX/HTML: it captures the rendered results DOM root instead of rendering the structured `ExportDocument` blocks.

## Export Types

`ExportDocTypes.tsx` defines:

```ts
export type ExportFormat = "pdf" | "docx" | "html" | "png";

export type ExportKeyValue = { label: string; value: string };

export type ExportBlock =
  | { kind: "heading"; text: string; level?: 1 | 2 | 3; optionId?: string }
  | { kind: "paragraph"; text: string; optionId?: string }
  | { kind: "keyValues"; items: ExportKeyValue[]; columns?: number; optionId?: string }
  | { kind: "table"; columns: string[]; rows: (string | number)[][]; optionId?: string }
  | { kind: "image"; dataUrl: string; alt?: string; caption?: string; width?: number; height?: number; optionId?: string }
  | { kind: "html"; html: string; optionId?: string }
  | { kind: "spacer"; mm?: number; size?: "sm" | "md" | "lg"; optionId?: string }
  | { kind: "pageBreak"; optionId?: string };

export type ExportSectionOption = {
  id: string;
  label: string;
  checkedByDefault?: boolean;
};

export type ExportWorkflow = {
  id: string;
  title?: string;
  blocks: ExportBlock[];
  options?: ExportSectionOption[];
};

export type ExportSection = {
  id?: string;
  title: string;
  blocks?: ExportBlock[];
  workflows?: ExportWorkflow[];
  options?: ExportSectionOption[];
};

export type ExportDocument = {
  title: string;
  generatedAt: string;
  sections: ExportSection[];
};
```

`ExportSectionSelectionModal` supports section-level option filtering and workflow-level option filtering. For sections with workflows, the modal can select specific workflow IDs and specific per-workflow option IDs.

## Viewer Ordering Versus Export Ordering

On-screen order in `ResultsPage.tsx`:

1. Job Summary
2. Loading/error panel, if applicable
3. Survival Analysis results, if available
4. Scalar metric result grid, if available
5. System Metrics, if `profileSummary` exists
6. Filters Overview
7. Footer buttons and export modals

Export setup order:

1. Job Summary
2. Registered result sections from rendered components
3. Filters Overview

Final export output also runs `moveFiltersOverviewToEnd`, so Filters Overview remains last even after section filtering.

System metrics are registered/exported through result components and `SystemMetricsAccordion`/analytics helpers where those components provide export blocks. On-screen System Metrics appears before Filters Overview.

## Footer and Navigation Behavior

`ResultsPage.tsx` renders footer buttons outside `#share-results-export-root`, so the buttons are not part of PNG export capture.

When `viewOnly` is true:

| Button | Behavior |
| --- | --- |
| `Back to Job History` | Calls `onBackToHistory`; disabled if callback is missing. |
| `Export As...` | Opens export format modal; disabled while `loading` is true. |

When `viewOnly` is false:

| Button | Behavior |
| --- | --- |
| `Back to Submission Details` | Calls `onBack`. |
| `Export As...` | Opens export format modal; disabled while `loading` is true. |
| `⟳ Start Over` | Calls `onStartOver`. |

In the current job-history flow, `JobHistoryMain.tsx` sets `viewOnly` to `true` before opening results from a history row.

## Empty and Missing Data Behavior

| Missing data | Behavior |
| --- | --- |
| Missing `nvflareJobId` | Result load effect returns without setting `loading`; no result API calls are made. |
| Failed `/jobs/info` | Warning is logged and loading continues with saved job functions when available. Job Summary may be absent because `nvflareJobInfo` remains null. |
| Missing functions | No workflow mappings are loaded. |
| Mapping response with no `workflow_dirs` | Function stores no workflow results; no section for that function renders. |
| Result response with no `job_data` | Uses `{}` as `jobData`. Components may show empty/N/A states. |
| Empty/missing function config | Treated as `null`; `fetchJobResultsForWorkflow` attempts separate function-config lookup. |
| Failed separate function-config lookup | Function config remains `null`; result rendering continues. |
| Missing profile summary | System Metrics is not rendered; per-workflow analytics sections are not shown. |
| Empty scalar values | Scalar card shows `Value` / `N/A`. |
| `null` value for one scalar property, such as `p_value: null` for a degenerate chi-square contingency table | That property row is omitted from the agent and aggregated tables; the card's other property rows still render. |
| Empty datasource context | Job Summary shows `No data source selection information associated with this job.` |
| Missing function list in Job Summary | Shows `No function information was returned.` |
| Missing selected filter data | `JobHistoryMain.tsx` passes `BLANK_FILTER_CONFIG`; FilterSummary renders from the blank collection. |
