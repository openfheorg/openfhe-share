# Export System

## Files Covered

| File/Directory | Role |
| --- | --- |
| `src/features/job_history/components/export/` | Export modal, export registry context, and section registration hook. |
| `src/features/job_history/utils/ExportDocTypes.tsx` | Shared export data model used by preview, PDF, DOCX, HTML, and PNG flows. |
| `src/features/job_history/utils/ExportDocumentRenderUtils.tsx` | HTML rendering and shared export CSS used by HTML export and modal preview. |
| `src/features/job_history/utils/ExportPdfUtils.tsx` | PDF export rendering and formatting utilities. |
| `src/features/job_history/utils/ExportDocxUtils.tsx` | Word/DOCX export rendering and formatting utilities. |
| `src/features/job_history/utils/ExportHtmlUtils.tsx` | HTML export rendering and download utilities. |
| `src/features/job_history/utils/ExportPngUtils.tsx` | PNG/screen-capture export utility. |
| `src/features/job_history/pages/ResultsPage.tsx` | Owns export modal state, gathers registered export sections, builds the export document, and dispatches each export format. |
| `src/features/job_history/components/AnalyticsMetricsAccordion.tsx` | Registers the `System Metrics` export section. |
| `src/features/job_history/components/ResultCard.tsx` | Registers scalar result export sections such as T-Test, Mean, Chi-Square Test, and Standard Deviation. |
| `src/features/job_history/components/SurvivabilityComponent.tsx` | Registers the Kaplan-Meier survival curve export section. |
| `src/components/FilterSummary.tsx` | Shared filter display used on the results page; export uses a separate `Filters Overview` section built in `ResultsPage.tsx`. |

## Export Feature Role

The export system allows users to export content from the Results Viewer.

Supported formats are defined by `ExportFormat` in `ExportDocTypes.tsx`:

```ts
export type ExportFormat = "pdf" | "docx" | "html" | "png";
```

PDF, DOCX, and HTML exports use a structured report model. The user chooses an export format, selects report sections, optionally selects workflow-specific content, previews the structured output, and then downloads a generated file.

PNG export is different. It captures the current Results Viewer DOM as an image and does not use the structured section tree for content selection.

## Export Component List

| File | Exports | Role |
| --- | --- | --- |
| `ExportContext.tsx` | `ExportProvider`, `useExportRegistry`, `ExportSectionRegistration` | Maintains the in-memory registry of exportable sections registered by mounted result components. |
| `useRegisterExportSection.tsx` | `useRegisterExportSection` | Registers a section with the export registry and unregisters it when the component unmounts. |
| `ExportFormatModal.tsx` | default `ExportFormatModal` | First export modal. Lets the user choose PDF, Word Document, HTML, or PNG. |
| `ExportSectionSelectionModal.tsx` | default `ExportSectionSelectionModal`, `ExportWorkflowSelectionBySectionId` | Second export modal. Lets the user select sections, workflow IDs, and section/workflow options for structured exports. Also shows the PNG preview/instructions for PNG mode. |

## Export Utility Function List

| File | Exported item | Purpose |
| --- | --- | --- |
| `ExportDocTypes.tsx` | `ExportFormat` | Supported export format union. |
| `ExportDocTypes.tsx` | `ExportKeyValue` | `{ label, value }` structure used by key/value blocks. |
| `ExportDocTypes.tsx` | `ExportBlock` | Union of supported report block types. |
| `ExportDocTypes.tsx` | `ExportSectionOption` | Optional checkbox item attached to a section or workflow. |
| `ExportDocTypes.tsx` | `ExportWorkflow` | Workflow-level export content container. |
| `ExportDocTypes.tsx` | `ExportSection` | Section-level export content container. |
| `ExportDocTypes.tsx` | `ExportSectionSelection` | Selection model for a section and optional workflow selections. This type exists but the active modal passes separate section/option/workflow maps. |
| `ExportDocTypes.tsx` | `ExportDocument` | Full export document model with title, generated timestamp, and selected sections. |
| `ExportDocumentRenderUtils.tsx` | `getExportDocumentCss` | Returns shared CSS for HTML export, modal preview, and offscreen capture markup. |
| `ExportDocumentRenderUtils.tsx` | `renderExportDocumentBodyHtml` | Renders the export document body, optionally including the document header. |
| `ExportDocumentRenderUtils.tsx` | `renderExportDocumentHtml` | Renders a complete standalone HTML document with embedded styles. |
| `ExportDocumentRenderUtils.tsx` | `mountExportDocumentForCapture` | Mounts an offscreen export document wrapper. This helper is present but is not used by the active ResultsPage export dispatch path. |
| `ExportPdfUtils.tsx` | `renderPdf` | Compatibility helper that wraps sections in an `ExportDocument` and calls `downloadPdf`. |
| `ExportPdfUtils.tsx` | `downloadPdf` | Creates a jsPDF document and saves it. |
| `ExportDocxUtils.tsx` | `downloadDocx` | Creates a `docx` document, packs it to a Blob, and downloads it. |
| `ExportHtmlUtils.tsx` | `renderExportHtml` | Returns complete export HTML as a string. |
| `ExportHtmlUtils.tsx` | `downloadHtml` | Creates a `text/html` Blob and downloads it. |
| `ExportPngUtils.tsx` | `downloadElementAsPng` | Uses `html-to-image` to capture an HTMLElement and download a PNG. |

## Shared Export Data Model

The structured export model is defined in `ExportDocTypes.tsx`.

```ts
export type ExportBlock =
  | { kind: "heading"; text: string; level?: 1 | 2 | 3; optionId?: string }
  | { kind: "paragraph"; text: string; optionId?: string }
  | { kind: "keyValues"; items: ExportKeyValue[]; columns?: number; optionId?: string }
  | { kind: "table"; columns: string[]; rows: (string | number)[][]; optionId?: string }
  | { kind: "image"; dataUrl: string; alt?: string; caption?: string; width?: number; height?: number; optionId?: string }
  | { kind: "html"; html: string; optionId?: string }
  | { kind: "spacer"; mm?: number; size?: "sm" | "md" | "lg"; optionId?: string }
  | { kind: "pageBreak"; optionId?: string };
```

```ts
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

The same `ExportDocument` structure is used for PDF, DOCX, HTML, and structured modal preview. PNG uses the current Results Viewer DOM instead.

## Results Page Export State

`ResultsPage.tsx` owns the export flow state inside `ResultsPageInner`.

| State | Type | Purpose |
| --- | --- | --- |
| `exportFormatModalOpen` | `boolean` | Controls the initial format-selection modal. |
| `exportSectionModalOpen` | `boolean` | Controls the section-selection/preview modal. |
| `selectedExportFormat` | `ExportFormat \| null` | Tracks the format selected in the first modal. |
| `exportableSections` | `Array<{ id: string; title: string; section: ExportSection }>` | Holds the section tree generated for the current export attempt. |
| `exporting` | `boolean` | Disables modal actions and changes the export button label while building/exporting content. |

`ResultsPage` wraps `ResultsPageInner` in `ExportProvider`, which makes the export registry available to result components.

## Export Flow From ResultsPage

1. The user clicks `Export As...` in the Results Viewer footer.
2. `handleExportClick` sets `exportFormatModalOpen` to `true`.
3. `ExportFormatModal` displays PDF, Word Document, HTML, and PNG choices.
4. Selecting a format calls `loadExportableSections(format)`.
5. `loadExportableSections` stores the selected format, closes the format modal, and sets `exporting` while sections are gathered.
6. `ResultsPage.tsx` starts the section array with `Job Summary` from `buildJobSummaryExportSection`.
7. `ResultsPage.tsx` calls `getSections()` from the export registry and awaits each registered section's `exportSection()` function.
8. Non-null registered sections are appended in registry order.
9. `ResultsPage.tsx` appends `Filters Overview` from `buildFiltersOverviewExportSection`.
10. `exportableSections` is updated and `ExportSectionSelectionModal` is opened.
11. The user confirms the section selection.
12. `handleExportSections` filters sections, section options, workflow IDs, and workflow options, builds an `ExportDocument`, and dispatches to the selected format utility.
13. When export completes, the section modal closes and `selectedExportFormat` is cleared.

## Registered Export Sections

Registered result sections are dynamic. Only mounted result components with available content can register sections.

| Component | Registry ID | Order | Title | Notes |
| --- | ---: | ---: | --- | --- |
| `ResultsPage.tsx` | `job-summary` | N/A | `Job Summary` | Built directly in `loadExportableSections`; not registered through `useRegisterExportSection`. |
| `SurvivabilityComponent.tsx` | `result-function-survival-analysis` | `10` | `Kaplan-Meier Survival Curve` | Includes one workflow entry per workflow ID. Uses plot images from `plotImagesByWorkflowId` when available. |
| `ResultCard.tsx` | `result-function-t-test` | `20` | `T-Test` | Registered by scalar result card logic. |
| `ResultCard.tsx` | `result-function-mean` | `21` | `Mean` | Registered by scalar result card logic. |
| `ResultCard.tsx` | `result-function-chi-square-test` | `22` | `Chi-Square Test` | Registered by scalar result card logic. |
| `ResultCard.tsx` | `result-function-standard-deviation` | `23` | `Standard Deviation` | Registered by scalar result card logic. |
| `AnalyticsMetricsAccordion.tsx` | `system-metrics` | `30` | `System Metrics` | Registered when system metrics have available data. |
| `ResultsPage.tsx` | `filters-overview` | N/A | `Filters Overview` | Built directly in `loadExportableSections`; appended after registered sections. |

`ExportContext.getSections()` sorts registered sections by numeric `order`. `Job Summary` is always inserted before registered sections. `Filters Overview` is appended after registered sections and is also moved to the end again immediately before export.

## Job Summary Export Section

`buildJobSummaryExportSection` builds a section with ID `job-summary` and title `Job Summary`.

It reads values from `nvflareJobInfo` first and `savedJobInfo` as fallback. The section can include:

| Label | Candidate fields |
| --- | --- |
| `Job ID` | `job_id`, `jobId`, `id`, `nvflare_job_id`, `nvflareJobId`, `savedJobInfo.referencedBy[0]` |
| `Status` | `status`, `job_status`, `jobStatus`, `runner_status`, `runnerStatus` |
| `Project` | `project`, `project_name`, `projectName`, `project_id`, `projectId` |
| `Submitted By` | `submitted_by`, `submittedBy`, `username`, `user`, `created_by`, `createdBy` |
| `Created` | `created_at`, `createdAt`, `create_time`, `createTime`, `submit_time`, `submitTime` |
| `Started` | `started_at`, `startedAt`, `start_time`, `startTime` |
| `Completed` | `completed_at`, `completedAt`, `finished_at`, `finishedAt`, `end_time`, `endTime` |
| `Functions` | `functions`, `function_names`, `functionNames`, `savedJobInfo.functions` |

When at least one row exists, the section contains a `keyValues` block. If no summary details are available, it contains a paragraph stating that no job summary details are currently available.

## Filters Overview Export Section

`buildFiltersOverviewExportSection` builds a section with ID `filters-overview` and title `Filters Overview`.

The first block is a `keyValues` block with:

| Label | Value |
| --- | --- |
| `Filter Set` | `submittedFilterSetName` or `Filters Overview` |

For each top-level entry in `submittedFilterSet`, the export section adds a level-3 heading using the formatted filter field name. It then flattens filter values into a table with columns:

| Column | Meaning |
| --- | --- |
| `Filter` | Flattened filter label/path. |
| `Value` | Flattened filter value. |

If a filter group has no flattened rows, the section adds `No filters applied.` for that group.

## Scalar Result Export Sections

`ResultCard.tsx` handles scalar result sections for Mean, Standard Deviation, Chi-Square Test, and T-Test.

Each scalar export section returns:

```ts
{
  title,
  workflows: exportWorkflows
}
```

Each workflow contains:

- workflow ID/title from `wf.workflowId`, or `Config ${idx + 1}` fallback
- optional `Function Configuration` paragraph and table when function config fields exist
- a table with columns `Source`, `Metric`, and `Value`
- client/initiator metrics depending on `userRole`
- aggregated metrics when available
- workflow error paragraph when `getWorkflowErrorFromJobData` finds an error
- analytics metric blocks from `buildWorkflowAnalyticsExportBlocks`

Each scalar workflow has this option:

```ts
{ id: "analytics_metrics", label: "Include analytics metrics", checkedByDefault: true }
```

This means analytics metrics are included by default, but can be unchecked for each workflow in the export modal.

## Kaplan-Meier Survival Curve Export Section

`SurvivabilityComponent.tsx` registers `Kaplan-Meier Survival Curve` with ID `result-function-survival-analysis` and order `10`.

The section returns workflow entries for available survival workflows. Each workflow can include:

- the workflow plot image when a data URL exists in `plotImagesByWorkflowId`
- tabular survival data for client/initiator and aggregated groups
- fallback `N/A` survival rows when a group is missing
- workflow analytics metric blocks from `buildWorkflowAnalyticsExportBlocks`

Each survival workflow has two options:

```ts
{ id: "analytics_metrics", label: "Include analytics metrics", checkedByDefault: true }
{ id: "tabular_data", label: "Include survival table data", checkedByDefault: false }
```

Survival table data is intentionally unchecked by default. The section modal also has an `Include Survival Tables` convenience toggle for Kaplan-Meier sections that selects or clears survival table options across the visible survival workflows.

## System Metrics Export Section

`AnalyticsMetricsAccordion.tsx` registers `System Metrics` with ID `system-metrics` and order `30`.

The section is registered only when metric data exists. The export section can include key/value blocks for runtime and system metrics, including combined workflow metrics and runtime comparison values when the underlying data is available.

## Section Selection Modal Props

`ExportSectionSelectionModal` receives:

| Prop | Type | Purpose |
| --- | --- | --- |
| `isOpen` | `boolean` | Opens/closes the modal. |
| `format` | `ExportFormat \| null` | Controls title, button label, and PNG-vs-structured behavior. |
| `sections` | `ExportSectionDraft[]` | Section tree built by `ResultsPage.tsx`. |
| `isExporting` | `boolean \| undefined` | Disables modal buttons during export. |
| `onBack` | `() => void` | Returns from section selection to format selection. |
| `onClose` | `() => void` | Closes the section modal. |
| `onExport` | `(sectionIds, optionSelectionsBySectionId, workflowSelectionsBySectionId) => void` | Submits selected content back to `ResultsPage.tsx`. |

`ExportSectionDraft` is internal to the modal:

```ts
type ExportSectionDraft = {
  id: string;
  title: string;
  section: ExportSection;
};
```

## Section Selection Data Structure

The active modal uses three selection structures.

### Selected section IDs

```ts
const [selectedSectionIds, setSelectedSectionIds] = useState<string[]>(defaultSelectedSectionIds);
```

These are the selected top-level section IDs. The default is every available section ID.

### Section option selections

```ts
const [optionSelectionsBySectionId, setOptionSelectionsBySectionId] =
  useState<Record<string, string[]>>({});
```

This maps a section ID to selected option IDs for section-level blocks.

### Workflow selections

```ts
export type ExportWorkflowSelectionBySectionId = Record<
  string,
  {
    workflowIds: string[];
    optionSelectionsByWorkflowId: Record<string, string[]>;
  }
>;
```

This maps a section ID to selected workflow IDs, plus selected option IDs per workflow.

## Default Checked and Unchecked Rules

When the section-selection modal opens:

- all top-level sections are selected by default
- all workflows inside each workflow-based section are selected by default
- section options are selected by default unless `checkedByDefault === false`
- workflow options are selected by default unless `checkedByDefault === false`
- `analytics_metrics` options are checked by default in scalar and survival workflow sections
- survival `tabular_data` options are unchecked by default
- PNG mode does not use customized section/workflow selections for output

The UI prevents unchecking the last selected top-level section. If Select All is unchecked, the modal keeps the first section selected. For workflow-based sections, the UI prevents unchecking the last selected workflow within that section.

## Per-Workflow Selection Behavior

Workflow-based sections render nested checkboxes.

The first level selects the section. The second level selects individual workflows. The third level selects workflow options such as analytics metrics or survival table data.

When a section is unchecked:

- its workflow checkboxes are disabled
- its workflow option checkboxes are disabled
- it is excluded from structured export output

When a workflow is unchecked:

- its workflow options are disabled
- that workflow is excluded from structured export output

`handleExportSections` calls `filterSectionForExport`, which removes unselected workflows and removes blocks whose `optionId` is not selected.

## Export Preview Data Flow

Structured preview is generated in `ExportSectionSelectionModal` before the user downloads the file.

1. The modal computes `previewDocument` from selected section IDs, section options, workflow IDs, and workflow options.
2. Unselected blocks are filtered out by `shouldIncludeBlock`.
3. Unselected workflows are removed from preview.
4. The preview document title is `SHARE Job Results Export`.
5. `generatedAt` is a local `new Date().toLocaleString()` value.
6. `renderExportDocumentBodyHtml(previewDocument, true)` renders preview HTML.
7. `getExportDocumentCss(".duality-export-preview-pane")` scopes the shared export CSS to the preview pane.
8. The preview is rendered through `dangerouslySetInnerHTML` inside the modal.

If no structured sections are available, the modal displays `No exportable sections are currently available.` If no selected content remains in the preview, it displays `Select at least one section to preview the export content.`

## Format Selection Modal

`ExportFormatModal` displays four choices:

| Format | Title | Description |
| --- | --- | --- |
| `pdf` | `PDF` | `Best for read-only sharing, review, and archiving.` |
| `docx` | `Word Document` | `Best for editing, annotation, and client-facing drafts.` |
| `html` | `HTML` | `Best for preserving rich browser-rendered report content.` |
| `png` | `PNG Image` | `Best for a visual snapshot of the visible results page.` |

The modal text explains that PDF, Word, and HTML exports support section/workflow/metric/table selection, while PNG captures the Results Viewer as it appears on screen.

## PDF Export

`downloadPdf` in `ExportPdfUtils.tsx` uses `jsPDF` with portrait letter pages and point units:

```ts
new jsPDF({ orientation: "p", unit: "pt", format: "letter" })
```

Important layout constants:

| Constant | Value |
| --- | ---: |
| `PAGE_MARGIN` | `36` |
| `PAGE_WIDTH` | `612` |
| `PAGE_HEIGHT` | `792` |
| `SECTION_PADDING` | `10` |
| `LINE_HEIGHT` | `13` |

PDF rendering behavior:

- Adds a document header with title and generated timestamp.
- Renders each `ExportSection` in order.
- Renders section titles in blue.
- Renders workflow blocks under a horizontal divider with `Workflow: {title}`.
- Wraps text with `pdf.splitTextToSize`.
- Calls `ensureSpace` before rendering content and adds pages when needed.
- Supports `heading`, `paragraph`, `keyValues`, `table`, `image`, `html`, `spacer`, and `pageBreak` blocks.
- Converts HTML blocks to plain text using a temporary DOM element.
- Supports PNG and JPEG image data URLs.
- Scales images to fit the content width and a max height of `330` points.
- Uses `pdf.save(filename)` for download.

### PDF Text Sanitization

jsPDF's built-in Helvetica only supports WinAnsi/Latin-1. A single out-of-range character garbles the whole string because jsPDF falls back to its two-byte encoding mode for that text run.

`ExportPdfUtils.tsx` therefore sanitizes every string it draws. `normalizeText` passes the value through `toPdfSafe` before collapsing whitespace, so the document title, generated timestamp, section titles, workflow titles, headings, paragraphs, key/value rows, table headers and cells, image captions, and text extracted from `html` blocks by `stripHtml` are all sanitized.

`toPdfSafe` runs two replacement passes:

1. Characters in the scientific Unicode ranges are transliterated through `PDF_CHAR_MAP`. The matched ranges cover subscripts and superscripts, Greek, arrows, and math operators, plus the individual characters `±`, `²`, `³`, `¹`, `×`, `÷`, `–`, `—`, and `…`. Characters matched by the range but absent from the map are removed.
2. A catch-all pass keeps tab, newline, carriage return, printable ASCII, and Latin-1 characters such as `é` and `ñ`, and removes everything else.

`PDF_CHAR_MAP` covers these groups:

| Group | Transliteration |
| --- | --- |
| Subscripts `₀`–`₉` and `₊₋₌₍₎` | ASCII digits and operators. `₁` becomes `1`. |
| Superscripts `⁰`–`⁹`, `¹²³`, and `⁺⁻⁼⁽⁾ⁿ` | ASCII digits, operators, and `n`. `²` becomes `2`. |
| Greek lowercase and uppercase | Spelled-out names. `β` becomes `beta`; `Σ` becomes `Sigma`. |
| Math and misc symbols | ASCII equivalents. `≤` becomes `<=`, `∞` becomes `inf`, `×` becomes `x`, `…` becomes `...`, `→` becomes `->`. |

This sanitization is specific to the PDF path. `ExportDocxUtils.tsx` has its own `normalizeText` that only collapses whitespace, and HTML/preview output escapes text without transliterating it.

PDF table behavior:

- Standard tables use equal-width columns.
- Headers repeat after a page break.
- Cells are wrapped and row heights are calculated from wrapped content.
- Tables with 3 or fewer columns and more than 16 rows use a compact two-column grid.
- Compact grid tables split rows into chunks of 18.

## DOCX Export

`downloadDocx` in `ExportDocxUtils.tsx` uses the `docx` package.

DOCX rendering behavior:

- Creates a `Document` with Arial as the default font.
- Uses 720 twip margins on all sides.
- Adds a title paragraph and generated timestamp.
- Converts sections to Word heading paragraphs and content blocks.
- Supports `heading`, `paragraph`, `keyValues`, `table`, `image`, `html`, `spacer`, and `pageBreak` blocks.
- Converts HTML blocks to plain text using a temporary DOM element.
- Converts data URL images to bytes with `window.atob`.
- Supports `png`, `jpg`, `gif`, and `bmp` image types.
- Packs the document with `Packer.toBlob`, creates an object URL, clicks an anchor, and revokes the object URL.

DOCX table behavior:

- Standard tables use full-width Word tables with equal percentage columns.
- Header rows use shading and `tableHeader: true`.
- Rows use `cantSplit: true`.
- Tables with 3 or fewer columns and more than 16 rows use a compact two-column table grid.
- Compact grid tables split rows into chunks of 18.
- Compact grid cells contain nested tables and use borderless outer cells.

DOCX image behavior:

- Image width defaults to `560` unless the block provides `width`; width is capped at `560`.
- Image height defaults to `315` unless the block provides `height`; height is capped at `360`.
- Image paragraphs are centered.
- Captions are centered and styled with muted text.

## HTML Export

`downloadHtml` in `ExportHtmlUtils.tsx` calls `renderExportHtml`, creates a `text/html;charset=utf-8` Blob, creates an object URL, clicks an anchor, and revokes the object URL.

`renderExportHtml` delegates to `renderExportDocumentHtml` in `ExportDocumentRenderUtils.tsx`.

HTML rendering behavior:

- Generates a complete `<!doctype html>` document.
- Embeds export CSS in a `<style>` tag.
- Uses a centered `.duality-export-page` with `max-width: 1040px` and `padding: 24px`.
- Renders a document header with title and generated timestamp.
- Renders each section in a bordered card-like block.
- Renders workflow content under a divider.
- Escapes text for headings, paragraphs, key/value values, table cells, image alt text, and captions.
- Renders `html` blocks directly inside `.duality-export-html-block`.
- Uses print CSS to reduce document padding and avoid breaking sections where possible.

HTML table behavior:

- Tables are wrapped in `.duality-export-table-wrap`.
- Tables use collapsed borders and small font sizing.
- Empty table headers render as empty header cells.
- Tables with 3 or fewer columns and more than 16 rows use a responsive compact grid.
- Compact grid chunks rows into groups of 18.

## PNG Export

`downloadElementAsPng` in `ExportPngUtils.tsx` uses `html-to-image`:

```ts
toPng(element, {
  cacheBust: true,
  pixelRatio: 2,
  backgroundColor: "#ffffff",
})
```

`ResultsPage.tsx` captures the element with ID:

```ts
"share-results-export-root"
```

PNG behavior:

- Captures the current Results Viewer DOM, not a structured export document.
- Downloads the captured image through a generated anchor.
- Uses the filename pattern `share-results-{stamp}.png`.
- Does not apply section selection filtering.
- Does not apply workflow option filtering inside the export modal.
- Depends on the current visible Results Viewer state before the export modal is opened.

The section-selection modal has special PNG behavior:

- The modal title still says `Select Content to Export`, but the body explains PNG is a screen grab.
- It does not render the structured section checkbox tree.
- It shows a preview image generated from `share-results-export-root`.
- Preview generation uses `html-to-image` with `pixelRatio: 0.35`, `backgroundColor: "#ffffff"`, and `cacheBust: true`.
- If the root element is missing, the preview error is `Unable to find the current Results Viewer.`
- If preview generation throws, the preview error is `Unable to generate the current Results Viewer preview.`

## Filename Behavior

`ResultsPage.tsx` creates a timestamp before dispatching export:

```ts
const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
```

Downloaded filenames are:

| Format | Filename pattern |
| --- | --- |
| PDF | `share-results-{stamp}.pdf` |
| DOCX | `share-results-{stamp}.docx` |
| HTML | `share-results-{stamp}.html` |
| PNG | `share-results-{stamp}.png` |

## Error and Loading Behavior

`ResultsPage.tsx` sets `exporting` to `true` while gathering sections and while generating the selected output. It resets `exporting` in a `finally` block.

When `isExporting` is true in `ExportSectionSelectionModal`:

- the Back button is disabled
- the close button is disabled through `closeButtonDisabled`
- the export button is disabled
- the export button label changes to `Exporting...`

The structured export button is also disabled when there are no sections or no selected sections.

The export dispatch functions do not show a user-facing error message in the current code. If PDF, DOCX, HTML, or PNG generation throws, `exporting` is reset by `finally`, but the modal remains responsible only for the current visual state. PNG preview has its own local loading and error messages inside the modal.

## Layout and Formatting Constraints

Shared layout constraints across preview and HTML export:

- `.duality-export-document` uses white background, Arial/Helvetica, `padding: 18px`, and `line-height: 1.35`.
- `.duality-export-header` and `.duality-export-section` use light borders, rounded corners, white background, and spacing between sections.
- `.duality-export-section` and `.duality-export-workflow` use `break-inside: avoid` and `page-break-inside: avoid`.
- `.duality-export-section-title` is blue and bold.
- Figures use max width `100%`, max height `520px`, and object-fit containment.
- Page break blocks render as dashed separators in HTML/preview and create page breaks for print.

PDF-specific constraints:

- All rendered text is reduced to Latin-1 by `toPdfSafe` because the built-in Helvetica font cannot encode characters outside WinAnsi.
- Uses manual pagination with `ensureSpace`.
- Images are capped at `330` points high.
- Compact tables use two columns and 18-row chunks for small-column, long-row tables.
- Header/section rounded rectangles are present in code but commented out.

DOCX-specific constraints:

- Uses Word heading styles for section and block headings.
- Uses 720 twip page margins.
- Uses compact nested table grids for small-column, long-row tables.
- Uses fixed image defaults/caps rather than measuring original image dimensions.

PNG-specific constraints:

- Captures the browser-rendered Results Viewer.
- Captured output can include only what exists in the DOM at capture time.
- Users must adjust visible workflow/results state before choosing PNG if they want a different image.

## Known Implementation Notes

- The active export system is registry-based; exportable child components register themselves instead of `ResultsPage.tsx` hardcoding every result section.
- `Job Summary` and `Filters Overview` are not registered sections. They are built directly in `ResultsPage.tsx` for every export attempt.
- `Filters Overview` is intentionally forced to the end of structured exports by `moveFiltersOverviewToEnd`.
- PNG mode passes default section IDs back through `onExport`, but the actual PNG path ignores section content and captures `share-results-export-root`.
- `ExportSectionSelection` is defined in `ExportDocTypes.tsx`, but the active section modal uses separate maps for selected sections, section options, and workflow selections.
- `mountExportDocumentForCapture` exists in `ExportDocumentRenderUtils.tsx`, but the active ResultsPage export path does not call it.
- `renderPdf` exists as a wrapper around `downloadPdf`, but `ResultsPage.tsx` calls `downloadPdf` directly.
