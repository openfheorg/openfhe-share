import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChevronDown, ChevronUp } from "react-bootstrap-icons";
import WorkflowErrorPanel, { getWorkflowWarning } from "../../../components/WorkflowErrorPanel";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { Project } from "../../../types/Project";
import KaplanMeierPlot from "../components/KaplanMeierPlot";
import {
  CHI2_1DOF_LABEL,
  formatChi2ForUI,
  formatPValueForUI,
  getWorkflowErrorFromJobData,
  ProfileSummaryWorkflows,
  renderPropertyDisplayLabel,
  formatWorkflowDisplayName,
  WorkflowJobData,
} from "../utils/JobsDataUtils";
import { WorkflowAnalyticsAccordion, buildWorkflowAnalyticsExportBlocks } from "./AnalyticsMetricsAccordion";
import FunctionConfigurationAccordion from "./FunctionConfigurationAccordion";
import { UserRole } from "../../../context/UserRoleContext";
import { ExportSection } from "../utils/ExportDocTypes";
import { useRegisterExportSection } from "./export/useRegisterExportSection";

export type KMAggRow = { t: number; S: number };

export type JobsDataShape = any;

type KMProcessedResults = {
  times?: number[];
  S_output?: Record<string, number[]>;
  p_value?: number | string;
  chi2?: number | string;
};

export interface SurvivabilityComponentHandle {
  exportToPDF: () => Promise<void>;
}

export interface SurvivabilityComponentProps {
  jobsData: JobsDataShape | null;
  workflowId?: string;
  functionName?: string;
  workflows?: WorkflowJobData[];
  activeIndex?: number;
  onActiveIndexChange?: (index: number) => void;
  analyticsWorkflows?: ProfileSummaryWorkflows | null;
  project: Project;
  userRole: UserRole;
}

function fmt(v?: number, isTime: boolean = false) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "-";
  return isTime ? v.toFixed(1) : v.toFixed(3);
}

function formatSurvivalWorkflowDisplayName(
  workflowId?: string,
  runIndex?: number,
): string {
  return formatWorkflowDisplayName(workflowId, "Survival Analysis", runIndex);
}

function rowsFromProcessed(times: number[], S: number[]): KMAggRow[] {
  const m = Math.min(times.length, S.length);
  const out: KMAggRow[] = new Array(m);
  for (let i = 0; i < m; i++) {
    const tVal = Number(times[i]);
    const sVal = Number(S[i]);
    const sClamped = !Number.isFinite(sVal) ? 0 : sVal < 0 ? 0 : sVal > 1 ? 1 : sVal;
    out[i] = { t: tVal, S: sClamped };
  }
  return out;
}

function groupsFromProcessedResults(x: any): Record<string, KMAggRow[]> | null {
  if (!x || typeof x !== "object") return null;

  const timesArr: number[] | null = Array.isArray(x.times)
    ? x.times.map((v: any) => Number(v))
    : null;

  const sOutput: Record<string, any> | null =
    x.S_output && typeof x.S_output === "object"
      ? (x.S_output as Record<string, any>)
      : null;

  if (!timesArr || !sOutput) return null;

  const out: Record<string, KMAggRow[]> = {};
  Object.keys(sOutput)
    .sort()
    .forEach((g) => {
      const Sraw = sOutput[g];
      if (!Array.isArray(Sraw)) return;
      const S = Sraw.map((v: any) => Number(v));
      if (!S.length) return;
      out[g] = rowsFromProcessed(timesArr, S);
    });

  return Object.keys(out).length ? out : null;
}

function getAgentResults(jobData: any, userRole: UserRole) {
  const isClient = userRole === UserRole.CLIENT;

  const agentResults = isClient
    ? jobData?.local_results ?? jobData?.local?.local_results ?? null
    : jobData?.initiator_results ?? null;

  const agentProcessedResults = isClient
    ? jobData?.local_processed_results ??
    jobData?.local?.local_processed_results ??
    jobData?.local_results ??
    jobData?.local?.local_results ??
    null
    : jobData?.initiator_processed_results ?? jobData?.initiator_results ?? null;

  return { agentResults, agentProcessedResults };
}

function renderPager(tableInst: ReturnType<typeof useReactTable<any>>) {
  const pageIndex = tableInst.getState().pagination.pageIndex;
  const pageCount = tableInst.getPageCount();
  const windowSize = 5;
  let start = Math.max(0, pageIndex - Math.floor(windowSize / 2));
  let end = start + windowSize;
  if (end > pageCount) {
    end = pageCount;
    start = Math.max(0, end - windowSize);
  }

  return (
    <div
      className="survivability-component-block-01"
    >
      <button type="button" className="link-button-reset duality-underline"
        onClick={(e) => {
          e.preventDefault();
          if (tableInst.getCanPreviousPage()) tableInst.previousPage();
        }}
        style={{ color: tableInst.getCanPreviousPage() ? "#007BFF" : "#A0A0A0", cursor: tableInst.getCanPreviousPage() ? "pointer" : "not-allowed", pointerEvents: tableInst.getCanPreviousPage() ? "auto" : "none" }}
      >
        Previous
      </button>

      {Array.from({ length: Math.max(0, end - start) }, (_, i) => {
        const pageNum = start + i;
        const isActive = pageNum === pageIndex;
        return (
          <button type="button" className="link-button-reset duality-p-0p25rem-0p5rem-radius-4px-decoration-underline-97edf"
            key={pageNum}
            onClick={(e) => {
              e.preventDefault();
              tableInst.setPageIndex(pageNum);
            }}
            style={{ color: isActive ? "#fff" : "#007BFF", backgroundColor: isActive ? "#007BFF" : "transparent" }}
          >
            {pageNum + 1}
          </button>
        );
      })}

      <button type="button" className="link-button-reset duality-underline"
        onClick={(e) => {
          e.preventDefault();
          if (tableInst.getCanNextPage()) tableInst.nextPage();
        }}
        style={{ color: tableInst.getCanNextPage() ? "#007BFF" : "#A0A0A0", cursor: tableInst.getCanNextPage() ? "pointer" : "not-allowed", pointerEvents: tableInst.getCanNextPage() ? "auto" : "none" }}
      >
        Next
      </button>
    </div>
  );

}


function renderGroupTable(label: string, tableInst: ReturnType<typeof useReactTable<KMAggRow>>) {
  const displayLabel = renderPropertyDisplayLabel(label)


  return (
    <div>
      <h4 className="survivability-component-h4">{displayLabel}</h4>
      <table className="survivability-component-block-02">
        <thead>
          {tableInst.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => (
                <th
                  key={h.id}
                  className="survivability-component-block-03"
                  onClick={h.column.getToggleSortingHandler()}
                >
                  {h.column.getIsSorted() === "asc" && <ChevronUp size={12} />}
                  {h.column.getIsSorted() === "desc" && <ChevronDown size={12} />}{" "}
                  {flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {tableInst.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="survivability-component-block-04">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {renderPager(tableInst)}
    </div>
  );
}

function KMGroupTable({
  label,
  rows,
  columns,
}: {
  label: string;
  rows: KMAggRow[];
  columns: ColumnDef<KMAggRow>[];
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  return renderGroupTable(label, table);
}


function displayLabel(x: any): string | null {
  const sOutput: Record<string, any> | null =
    x && typeof x === "object" && x.S_output && typeof x.S_output === "object"
      ? (x.S_output as Record<string, any>)
      : null;

  if (!sOutput) return null;

  const keys = Object.keys(sOutput).filter((k) => k && typeof k === "string");
  if (!keys.length) return null;

  const sorted = keys.slice().sort();
  if (sorted.length === 1) return renderPropertyDisplayLabel(sorted[0]);
  if (sorted.length === 2) return `${renderPropertyDisplayLabel(sorted[0])} vs ${renderPropertyDisplayLabel(sorted[1])}`;
  return sorted.join(" vs ");
}

const SurvivabilityComponent = React.forwardRef<
  SurvivabilityComponentHandle,
  SurvivabilityComponentProps
>(
  (
    {
      jobsData,
      workflowId,
      workflows,
      activeIndex,
      onActiveIndexChange,
      analyticsWorkflows,
      project,
      userRole,
    },
    ref
  ) => {
    const [jobsDataState, setJobsDataState] = useState<JobsDataShape | null>(null);


    const [plotImagesByWorkflowId, setPlotImagesByWorkflowId] = useState<Record<string, string>>({});

    const [localActiveIndex, setLocalActiveIndex] = useState(0);
    const [selectedWorkflowIds, setSelectedWorkflowIds] = useState<string[]>([]);

    const chartRef = useRef<HTMLDivElement>(null);
    const [chartColumnCount, setChartColumnCount] = useState(1);

    const effectiveIndex =
      workflows && workflows.length > 0
        ? Math.min(
          onActiveIndexChange ? (activeIndex ?? 0) : localActiveIndex,
          workflows.length - 1
        )
        : 0;

    useEffect(() => {
      if (workflows && workflows.length > 0) {
        if (onActiveIndexChange) {
          if (activeIndex == null || activeIndex >= workflows.length) {
            onActiveIndexChange(0);
          }
        } else {
          if (localActiveIndex >= workflows.length) {
            setLocalActiveIndex(0);
          }
        }
      }
    }, [workflows, activeIndex, onActiveIndexChange, localActiveIndex]);

    useEffect(() => {
      if (!workflows || workflows.length === 0) {
        setSelectedWorkflowIds([]);
        return;
      }
      const availableIds = workflows.map((wf, idx) => wf.workflowId || `Config ${idx + 1}`);

      setSelectedWorkflowIds((prev) => {
        const filtered = prev.filter((id) => availableIds.includes(id));
        if (filtered.length > 0) {
          return filtered;
        }
        return availableIds;
      });
    }, [workflows, effectiveIndex]);

    const activeWorkflow: WorkflowJobData | undefined =
      workflows && workflows.length > 0 ? workflows[effectiveIndex] : undefined;

    const activeJobData = activeWorkflow ? activeWorkflow.jobData : jobsData;
    const effectiveWorkflowId = activeWorkflow ? activeWorkflow.workflowId : workflowId;
    const rawWorkflowError =
      (activeWorkflow as any)?.workflowError ?? getWorkflowErrorFromJobData(activeJobData);
    const workflowWarning = getWorkflowWarning(
      rawWorkflowError,
      activeJobData,
      activeJobData?.aggregate_processed_results,
    );
    const workflowError = workflowWarning ? null : rawWorkflowError;

    const handleTabChange = (index: number) => {
      if (workflows && workflows.length > 0) {
        const clamped = Math.min(Math.max(index, 0), workflows.length - 1);
        if (onActiveIndexChange) {
          onActiveIndexChange(clamped);
        } else {
          setLocalActiveIndex(clamped);
        }
      }
    };

    const handleWorkflowCheckboxChange = (workflowKey: string, index: number, checked: boolean) => {
      setSelectedWorkflowIds((prev) => {
        if (!checked && prev.includes(workflowKey) && prev.length <= 1) {
          return prev;
        }

        const next = checked
          ? prev.includes(workflowKey)
            ? prev
            : [...prev, workflowKey]
          : prev.filter((id) => id !== workflowKey);

        const ordered = workflows
          ? workflows
            .map((wf, wfIdx) => wf.workflowId || `Config ${wfIdx + 1}`)
            .filter((id) => next.includes(id))
          : next;

        const nextActiveId = ordered[0];
        if (nextActiveId && workflows) {
          const nextActiveIndex = workflows.findIndex(
            (wf, wfIdx) => (wf.workflowId || `Config ${wfIdx + 1}`) === nextActiveId
          );
          if (nextActiveIndex >= 0) {
            handleTabChange(nextActiveIndex);
          }
        } else if (checked) {
          handleTabChange(index);
        }

        return ordered;
      });
    };


    const handleSelectAllWorkflowIds = () => {
      if (!workflows || workflows.length === 0) return;

      setSelectedWorkflowIds(
        workflows.map((wf, wfIdx) => wf.workflowId || `Config ${wfIdx + 1}`)
      );
    };

    const allWorkflowIdsSelected =
      !!workflows &&
      workflows.length > 0 &&
      workflows.every((wf, wfIdx) =>
        selectedWorkflowIds.includes(wf.workflowId || `Config ${wfIdx + 1}`)
      );

    const columnsPerGroup = useMemo<ColumnDef<KMAggRow>[]>(() => {
      return [
        {
          accessorKey: "t",
          header: "Time (months)",
          cell: (info: any) => fmt(info.getValue() as number | undefined, true),
        },
        {
          accessorKey: "S",
          header: "Survival Probability",
          cell: (info: any) => fmt(info.getValue() as number | undefined),
        },
      ];
    }, []);


    const selectedWorkflowEntries = useMemo(() => {
      if (!workflows || workflows.length === 0) {
        return [] as Array<{
          workflowKey: string;
          workflow: WorkflowJobData;
          index: number;
        }>;
      }

      const selectedSet = new Set(selectedWorkflowIds);
      return workflows
        .map((wf, idx) => ({
          workflowKey: wf.workflowId || `Config ${idx + 1}`,
          workflow: wf,
          index: idx,
        }))
        .filter((entry) => selectedSet.has(entry.workflowKey));
    }, [workflows, selectedWorkflowIds]);

    useEffect(() => {
      const node = chartRef.current;
      if (!node) return;

      const updateColumnCount = () => {
        const width = node.getBoundingClientRect().width;
        const breakpointColumnCount = width >= 1800 ? 3 : width >= 900 ? 2 : 1;
        const selectedPlotCount = Math.max(1, selectedWorkflowEntries.length);
        const nextColumnCount = Math.min(breakpointColumnCount, selectedPlotCount);
        setChartColumnCount((prev) => (prev === nextColumnCount ? prev : nextColumnCount));
      };

      updateColumnCount();

      if (typeof ResizeObserver === "undefined") {
        window.addEventListener("resize", updateColumnCount);
        return () => window.removeEventListener("resize", updateColumnCount);
      }

      const observer = new ResizeObserver(updateColumnCount);
      observer.observe(node);
      return () => observer.disconnect();
    }, [selectedWorkflowEntries.length]);

    useEffect(() => {
      setJobsDataState(activeJobData ?? null);
    }, [activeJobData]);

    const onPlotImageDataUrl = useCallback(
      (workflowKey: string, dataUrl: string | null) => {
        if (!dataUrl) return;

        setPlotImagesByWorkflowId((prev) => {
          if (prev[workflowKey] === dataUrl) return prev;
          return { ...prev, [workflowKey]: dataUrl };
        });
      },
      []
    );

    const formatConfigValue = useCallback((value: any): string => {
      if (value === null || value === undefined) return "";
      if (typeof value === "string") return value;
      if (typeof value === "number" || typeof value === "boolean") return String(value);
      try {
        return JSON.stringify(value);
      } catch {
        return String(value);
      }
    }, []);

    const buildFunctionConfigRows = useCallback((functionConfig: any): (string | number)[][] => {
      if (!functionConfig || typeof functionConfig !== "object") return [];
      return Object.entries(functionConfig)
        .filter(([, value]) => value !== null && value !== undefined && formatConfigValue(value) !== "")
        .map(([key, value]) => [key, formatConfigValue(value)]);
    }, [formatConfigValue]);

    const agentTitle = userRole === UserRole.CLIENT ? "Client" : "Initiator";


    const exportSection = useCallback(async (): Promise<ExportSection | null> => {
      const wfList: Array<{ id: string; displayName: string; jobData: any; functionConfig: any }> = [];

      if (workflows && workflows.length > 0) {
        workflows.forEach((wf, idx) => {
          const id = wf.workflowId || `Config ${idx + 1}`;
          wfList.push({
            id,
            displayName: formatSurvivalWorkflowDisplayName(id, idx + 1),
            jobData: (wf as any).jobData ?? (wf as any).results ?? null,
            functionConfig: (wf as any).function_config || (wf as any).functionConfig || null,
          });
        });
      } else if (jobsData) {
        const id = workflowId || "Workflow";
        wfList.push({
          id,
          displayName: formatSurvivalWorkflowDisplayName(id, 1),
          jobData: jobsData,
          functionConfig: null,
        });
      }

      if (!wfList.length) return null;

      const exportWorkflows = wfList.map((wf) => {
        const blocks: any[] = [];
        const jd = wf.jobData;

        const imgDataUrl = plotImagesByWorkflowId[wf.id];
        if (imgDataUrl) {
          blocks.push({
            kind: "image",
            dataUrl: imgDataUrl,
            caption: `Kaplan-Meier Curve (${wf.displayName})`,
          });
          blocks.push({ kind: "spacer", mm: 4 });
        }

        const functionConfigRows = buildFunctionConfigRows(wf.functionConfig);
        if (functionConfigRows.length) {
          blocks.push({ kind: "paragraph", text: "Function Configuration" });
          blocks.push({
            kind: "table",
            columns: ["Setting", "Value"],
            rows: functionConfigRows,
          });
        }

        if (!jd) {
          blocks.push({ kind: "paragraph", text: "No result data available." });
          blocks.push(...buildWorkflowAnalyticsExportBlocks(wf.id, analyticsWorkflows, userRole));
          return {
            id: wf.id,
            title: wf.displayName,
            blocks,
            options: [
              { id: "analytics_metrics", label: "Include analytics metrics", checkedByDefault: true },
              { id: "tabular_data", label: "Include survival table data", checkedByDefault: false },
            ],
          };
        }

        const aggProcessed: KMProcessedResults | undefined = jd?.aggregate_processed_results;
        const { agentProcessedResults, agentResults } = getAgentResults(jd, userRole);
        const initProcessed: KMProcessedResults | undefined = agentProcessedResults ?? undefined;

        const initGroups = groupsFromProcessedResults(initProcessed) ?? {};
        const aggGroups = groupsFromProcessedResults(aggProcessed) ?? {};

        const rawAggP = aggProcessed?.p_value ?? jd?.aggregate_processed_results?.p_value ?? null;
        const rawLocalP =
          initProcessed?.p_value ??
          (agentResults && typeof agentResults === "object" ? (agentResults as any).p_value : null) ??
          null;
        const rawAggChi2 = aggProcessed?.chi2 ?? jd?.aggregate_processed_results?.chi2 ?? null;
        const rawLocalChi2 =
          initProcessed?.chi2 ??
          (agentResults && typeof agentResults === "object" ? (agentResults as any).chi2 : null) ??
          null;

        const aggDisp = formatPValueForUI(rawAggP);
        const localDisp = formatPValueForUI(rawLocalP);

        const cmp =
          displayLabel(aggProcessed) ??
          displayLabel(initProcessed) ??
          null;

        if (localDisp !== null || aggDisp !== null) {
          blocks.push({ kind: "paragraph", text: `Log-rank test${cmp ? ` (${cmp})` : ""}` });
          blocks.push({
            kind: "table",
            columns: ["Metric", agentTitle, "Aggregated"],
            rows: [
              ["P-value", localDisp ?? "N/A", aggDisp ?? "N/A"],
              [CHI2_1DOF_LABEL, formatChi2ForUI(rawLocalChi2) ?? "N/A", formatChi2ForUI(rawAggChi2) ?? "N/A"],
            ],
          });
        }

        const rawWorkflowError =
          (wf as any).workflowError ?? getWorkflowErrorFromJobData(jd);
        const workflowWarning = getWorkflowWarning(
          rawWorkflowError,
          jd,
          jd?.aggregate_processed_results,
        );
        const workflowError = workflowWarning ? null : rawWorkflowError;
        if (workflowWarning) {
          blocks.push({ kind: "paragraph", text: `Workflow Warning: ${workflowWarning.message}` });
        } else if (workflowError) {
          const errText =
            typeof workflowError === "string"
              ? workflowError
              : JSON.stringify(workflowError);
          blocks.push({ kind: "paragraph", text: `Workflow Error: ${errText}` });
        }

        const groupNames = Array.from(new Set([...Object.keys(initGroups), ...Object.keys(aggGroups)])).sort();

        if (groupNames.length) {
          groupNames.forEach((g) => {
            const initRows = initGroups[g] || [];
            const aggRows = aggGroups[g] || [];

            if (initRows.length) {
              const rowsOut: (string | number)[][] = initRows.map((r) => [r.t, Number(r.S).toFixed(3)]);
              blocks.push({
                kind: "paragraph",
                text: `${agentTitle} ${g}`.replace("MUT", "Mutations records").replace("WT", "Wild Type records"),
                optionId: "tabular_data",
              });
              blocks.push({
                kind: "table",
                columns: ["Time (months)", "Survival Probability"],
                rows: rowsOut,
                optionId: "tabular_data",
              });
            } else {
              blocks.push({
                kind: "paragraph",
                text: `${agentTitle} ${g}`.replace("MUT", "Mutations records").replace("WT", "Wild Type records"),
                optionId: "tabular_data",
              });
              blocks.push({
                kind: "table",
                columns: ["Time (months)", "Survival Probability"],
                rows: [["N/A", "N/A"]],
                optionId: "tabular_data",
              });
            }

            if (aggRows.length) {
              const rowsOut: (string | number)[][] = aggRows.map((r) => [r.t, Number(r.S).toFixed(3)]);
              blocks.push({
                kind: "paragraph",
                text: `Aggregated ${g}`.replace("MUT", "Mutations records").replace("WT", "Wild Type records"),
                optionId: "tabular_data",
              });
              blocks.push({
                kind: "table",
                columns: ["Time (months)", "Survival Probability"],
                rows: rowsOut,
                optionId: "tabular_data",
              });
            } else {
              blocks.push({
                kind: "paragraph",
                text: `Aggregated ${g}`.replace("MUT", "Mutations records").replace("WT", "Wild Type records"),
                optionId: "tabular_data",
              });
              blocks.push({
                kind: "table",
                columns: ["Time (months)", "Survival Probability"],
                rows: [["N/A", "N/A"]],
                optionId: "tabular_data",
              });
            }

            blocks.push({ kind: "spacer", mm: 4, optionId: "tabular_data" });
          });
        } else {
          blocks.push({ kind: "paragraph", text: "No survival table data available.", optionId: "tabular_data" });
          blocks.push({ kind: "spacer", mm: 4, optionId: "tabular_data" });
        }

        blocks.push(...buildWorkflowAnalyticsExportBlocks(wf.id, analyticsWorkflows, userRole));

        return {
          id: wf.id,
          title: wf.displayName,
          blocks,
          options: [
            { id: "analytics_metrics", label: "Include analytics metrics", checkedByDefault: true },
            { id: "tabular_data", label: "Include survival table data", checkedByDefault: false },
          ],
        };
      });

      return {
        title: "Kaplan-Meier Survival Curve",
        workflows: exportWorkflows,
      };
    }, [workflows, jobsData, workflowId, userRole, plotImagesByWorkflowId, analyticsWorkflows, agentTitle, buildFunctionConfigRows]);

    useRegisterExportSection({
      id: "result-function-survival-analysis",
      order: 10,
      title: "Kaplan-Meier Survival Curve",
      exportSection,
    });

    async function exportToPDF(): Promise<void> {
      return;
    }

    useImperativeHandle(ref, () => ({
      exportToPDF,
    }));

    const hasData = !!jobsDataState;
    const shouldRender = hasData || !!workflowError;

    if (!shouldRender) {
      return <></>;
    }

    const hasMultipleWorkflowEntries = !!workflows && workflows.length > 1;

    return (
      <>
        <div
          className="survivability-component-block-05"
        >
          <div
            className="survivability-component-block-06"
          >
            <h3>Kaplan-Meier Survival Curve</h3>

            {/* <button
              type="button"
              disabled
              style={{
                background: "transparent",
                border: 0,
                padding: 0,
                margin: 0,
                textDecoration: "underline",
                font: "inherit",
                cursor: "not-allowed",
                opacity: 0.7,
              }}
            >
              See Results From Other Computations
            </button> */}
          </div>

          {workflows && workflows.length > 0 && (
            <div
              className="duality-pb-0p75rem"
            >
              <div
                className="duality-d-flex-wrap-wrap-gap-0p55rem-1rem"
              >
                Workflows:
                {workflows.map((wf, idx) => {
                  const workflowKey = wf.workflowId || `Config ${idx + 1}`;
                  const workflowDisplayName = formatSurvivalWorkflowDisplayName(workflowKey, idx + 1);
                  const isSelected = selectedWorkflowIds.includes(workflowKey);
                  const isRequiredSelection = isSelected && selectedWorkflowIds.length <= 1;

                  return (
                    <label
                      key={workflowKey}
                      title={isRequiredSelection ? "At least one workflow must remain selected" : undefined}
                      className="survivability-component-block-07"
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        aria-label={`${workflowDisplayName} workflow selection`}
                        aria-describedby="survivability-workflow-selection-rule"
                        onClick={(e) => {
                          if (isRequiredSelection) {
                            e.preventDefault();
                          }
                        }}
                        onChange={(e) =>
                          handleWorkflowCheckboxChange(workflowKey, idx, e.target.checked)
                        }
                      />
                      <span>{workflowDisplayName}</span>
                    </label>
                  );
                })}
                {!allWorkflowIdsSelected && (
                  <button
                    type="button"
                    className="button-href survivability-component-block-08"
                    onClick={handleSelectAllWorkflowIds}
                    
                  >
                    Select All
                  </button>
                )}
              </div>
            </div>
          )}

          {workflowWarning && (
            <WorkflowErrorPanel
              error={workflowWarning}
              variant="warning"
              defaultExpanded={false}
              showTracebackToggle={false}
            />
          )}

          {workflowError && (
            <WorkflowErrorPanel
              error={workflowError}
              variant="error"
              defaultExpanded={false}
              showTracebackToggle={true}
            />
          )}

          {hasData && (
            <div
              ref={chartRef}
              className="survivability-component-chart" style={{ gridTemplateColumns: `repeat(${chartColumnCount * 2}, minmax(0, 1fr))` }}
            >
              {(selectedWorkflowEntries.length > 0
                ? selectedWorkflowEntries
                : workflows && workflows.length > 0 && activeWorkflow
                  ? [{
                    workflowKey: effectiveWorkflowId || "workflow",
                    workflow: activeWorkflow,
                    index: effectiveIndex,
                  }]
                  : jobsData
                    ? [{
                      workflowKey: effectiveWorkflowId || workflowId || "workflow",
                      workflow: { workflowId: effectiveWorkflowId || workflowId || "workflow", jobData: jobsData } as WorkflowJobData,
                      index: 0,
                    }]
                    : [])
                .map((entry, entryIdx, arr) => {
                  const workflowJobData = (entry.workflow as any).jobData ?? null;
                  const { agentResults: entryAgentResults, agentProcessedResults: entryAgentProcessedResults } = getAgentResults(
                    workflowJobData,
                    userRole
                  );
                  const entryAggProcessed = workflowJobData?.aggregate_processed_results;
                  const entryRawAggP = entryAggProcessed?.p_value ?? workflowJobData?.aggregate_processed_results?.p_value ?? null;
                  const entryRawLocalP =
                    entryAgentProcessedResults?.p_value ??
                    (entryAgentResults && typeof entryAgentResults === "object"
                      ? (entryAgentResults as any).p_value
                      : null) ??
                    null;
                  const entryRawAggChi2 = entryAggProcessed?.chi2 ?? workflowJobData?.aggregate_processed_results?.chi2 ?? null;
                  const entryRawLocalChi2 =
                    entryAgentProcessedResults?.chi2 ??
                    (entryAgentResults && typeof entryAgentResults === "object"
                      ? (entryAgentResults as any).chi2
                      : null) ??
                    null;
                  const entryAggPValueDisplay = formatPValueForUI(entryRawAggP);
                  const entryLocalPValueDisplay = formatPValueForUI(entryRawLocalP);
                  const entryAggChi2Value = formatChi2ForUI(entryRawAggChi2);
                  const entryLocalChi2Value = formatChi2ForUI(entryRawLocalChi2);
                  const entryAggChi2Display =
                    entryAggChi2Value !== null ? `${CHI2_1DOF_LABEL} = ${entryAggChi2Value}` : null;
                  const entryLocalChi2Display =
                    entryLocalChi2Value !== null ? `${CHI2_1DOF_LABEL} = ${entryLocalChi2Value}` : null;
                  const entryComparisonLabel =
                    displayLabel(entryAggProcessed) ?? displayLabel(entryAgentProcessedResults) ?? null;
                  const entryComparisonSuffix = entryComparisonLabel ? ` (${entryComparisonLabel})` : "";
                  const entryHasAnyP =
                    entryLocalPValueDisplay !== null || entryAggPValueDisplay !== null;
                  const entryInitRowsByGroup = groupsFromProcessedResults(entryAgentProcessedResults) ?? {};
                  const entryAggRowsByGroup = groupsFromProcessedResults(entryAggProcessed) ?? {};
                  const rowRemainder = arr.length % chartColumnCount;
                  const isLastRowItem = rowRemainder > 0 && entryIdx >= arr.length - rowRemainder;
                  const shouldSpanFull = arr.length === 1 || (rowRemainder === 1 && entryIdx === arr.length - 1);
                  const shouldSpanHalf = chartColumnCount === 3 && rowRemainder === 2 && isLastRowItem;

                  return (
                    <div
                      key={entry.workflowKey}
                      className="survivability-component-block-09" style={{ gridColumn: shouldSpanFull ? "1 / -1" : shouldSpanHalf ? "span 3" : "span 2" }}
                    >
                      {hasMultipleWorkflowEntries && (
                        <div
                          className="survivability-component-block-10"
                        >
                          {formatSurvivalWorkflowDisplayName(entry.workflowKey, entry.index + 1)}
                        </div>
                      )}

                      {(((entry.workflow as any).function_config || (entry.workflow as any).functionConfig)) && (
                        <div
                          className="duality-mb-1"
                        >
                          <FunctionConfigurationAccordion
                            key={`function-config-${entry.workflowKey}`}
                            config={(entry.workflow as any).function_config || (entry.workflow as any).functionConfig}
                            project={project}
                          />
                        </div>
                      )}

                      <KaplanMeierPlot
                        userRole={userRole}
                        seriesMap={
                          workflowJobData
                            ? {
                              agent_results: entryAgentResults,
                              aggregate_results: workflowJobData.aggregate_results,
                              aggregate_processed_results: workflowJobData.aggregate_processed_results,
                            }
                            : {}
                        }
                        onImageDataUrl={(dataUrl) => onPlotImageDataUrl(entry.workflowKey, dataUrl)}
                      />

                      {entryHasAnyP && (
                        <div
                          className="survivability-component-block-11"
                        >
                          <div className="duality-weight-700-mb-0p5rem">
                            Log-rank test{entryComparisonSuffix}
                          </div>

                          <div
                            className="survivability-component-block-12"
                          >
                            <div className="survivability-component-shared-01">
                              <div className="survivability-component-shared-02">{agentTitle}:</div>
                              <div style={{ display: "flex", flexDirection: "column" }}>
                                <div className="survivability-component-block-13">
                                  {entryLocalPValueDisplay ?? "N/A"}
                                </div>
                                {entryLocalChi2Display !== null && (
                                  <div className="survivability-component-block-13">
                                    {entryLocalChi2Display}
                                  </div>
                                )}
                              </div>
                            </div>

                            <div className="survivability-component-shared-01">
                              <div className="survivability-component-shared-02">Aggregated:</div>
                              <div style={{ display: "flex", flexDirection: "column" }}>
                                <div className="survivability-component-block-14">
                                  {entryAggPValueDisplay ?? "N/A"}
                                </div>
                                {entryAggChi2Display !== null && (
                                  <div className="survivability-component-block-14">
                                    {entryAggChi2Display}
                                  </div>
                                )}

                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {(Object.keys(entryInitRowsByGroup).length > 0 || Object.keys(entryAggRowsByGroup).length > 0) && (
                        <div className="duality-mt-1">
                          <AbstractAccordion
                            title="Survival tables"
                            defaultOpen={false}
                            containerStyle={{
                              maxWidth: "100%",
                            }}
                            headerStyle={{
                              width: "100%",
                              textAlign: "left",
                              color: "#373737",
                              fontWeight: 600,
                              padding: 0,
                              marginBottom: "0.75rem",
                            }}
                            bodyStyle={{
                              padding: 0,
                              border: "none",
                              backgroundColor: "transparent",
                              maxWidth: "100%",
                            }}
                          >
                            <div
                              className="survivability-component-block-15"
                            >
                              {Array.from(
                                new Set([
                                  ...Object.keys(entryInitRowsByGroup),
                                  ...Object.keys(entryAggRowsByGroup),
                                ])
                              )
                                .sort()
                                .flatMap((g) => {
                                  const items: React.ReactNode[] = [];

                                  if (entryInitRowsByGroup[g]) {
                                    items.push(
                                      <div
                                        key={`init-cell-${entry.workflowKey}-${g}`}
                                        className="duality-width-full"
                                      >
                                        <KMGroupTable
                                          key={`init-${entry.workflowKey}-${g}`}
                                          label={`${agentTitle} ${g}`}
                                          rows={entryInitRowsByGroup[g]}
                                          columns={columnsPerGroup}
                                        />
                                      </div>
                                    );
                                  }

                                  if (entryAggRowsByGroup[g]) {
                                    items.push(
                                      <div
                                        key={`agg-cell-${entry.workflowKey}-${g}`}
                                        className="duality-width-full"
                                      >
                                        <KMGroupTable
                                          key={`agg-${entry.workflowKey}-${g}`}
                                          label={`Aggregated ${g}`}
                                          rows={entryAggRowsByGroup[g]}
                                          columns={columnsPerGroup}
                                        />
                                      </div>
                                    );
                                  }

                                  return items;
                                })}
                            </div>
                          </AbstractAccordion>
                        </div>
                      )}

                      {analyticsWorkflows && entry.workflowKey && (
                        <div className="duality-mt-0p75rem">
                          <WorkflowAnalyticsAccordion
                            workflowId={entry.workflowKey}
                            workflows={analyticsWorkflows}
                            role={userRole}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      </>
    );
  }
);

SurvivabilityComponent.displayName = "SurvivabilityComponent";

export default SurvivabilityComponent;
