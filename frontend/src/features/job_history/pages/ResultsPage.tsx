import React, { JSX, useEffect, useMemo, useRef, useState } from "react";
import FilterSummary from "../../../components/FilterSummary";
import HeaderTitle from "../../../components/HeaderTitle";
import { FUNCTION_METADATA, formatFunctionName } from "../../../components/FunctionSelector";
import { ProjectNameWithDescription } from "../../../components/ProjectName";
import { IS_LOCAL_APP, IS_STANDALONE_APP, SupportedFunction } from "../../../constants/Constants";
import { Project } from "../../../types/Project";
import {
  buildDefaultFilterCollectionFromConditions,
  FilterCollection,
} from "../../job_runner/utils/FilterPayloadConfigUtils";
import SystemMetricsAccordion from "../components/AnalyticsMetricsAccordion";
import {
  fetchJobResultsForWorkflow,
  fetchNVFlareJobInfo,
  fetchResultsContext,
  fetchTaskflowDiagnostics,
  fetchWorkflowMapping,
  startTaskflowDiagnostics,
  ProfileSummary,
  TaskflowDiagnosticsResponse,
  WorkflowJobData,
  formatWorkflowDisplayName,
} from "../utils/JobsDataUtils";
import { UserRole, useUserSession } from "../../../context/UserRoleContext";
import { ExportProvider, useExportRegistry } from "../components/export/ExportContext";
import { ExportDocument, ExportFormat, ExportSection } from "../utils/ExportDocTypes";
import { downloadPdf } from "../utils/ExportPdfUtils";
import { downloadHtml } from "../utils/ExportHtmlUtils";
import { downloadDocx } from "../utils/ExportDocxUtils";
import { downloadElementAsPng } from "../utils/ExportPngUtils";
import ExportFormatModal from "../components/export/ExportFormatModal";
import ExportSectionSelectionModal, { ExportWorkflowSelectionBySectionId } from "../components/export/ExportSectionSelectionModal";
import { JobLogData, NVFlareJob } from "../../../types/JobsDataTypes";
import {
  Chi2ResultCard,
  MeanResultCard,
  StDevResultCard,
  TTestResultCard,
  LogisticCalibrationResultCard,
} from "../components/ResultCard";
import SurvivabilityComponent from "../components/SurvivabilityComponent";
import NVFlareJobSummary, { formatThresholdMethod } from "../components/NVFlareJobSummary";
import WorkflowErrorPanel from "../../../components/WorkflowErrorPanel";
import TaskflowDiagnosticsPanel from "../components/TaskflowDiagnosticsPanel";

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

function normalizeFunctionName(name: string): string {
  return String(name || "").trim().toUpperCase();
}

function getResultFunctionAnchorId(functionName: string): string {
  const normalized = String(functionName || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return `result-function-${normalized || "unknown"}`;
}

const TASKFLOW_DIAGNOSTICS_ENABLED = IS_LOCAL_APP || IS_STANDALONE_APP;

const RESULTS_SECTION_IDS = {
  JOB_SUMMARY: "results-section-job-summary",
  SYSTEM_METRICS: "results-section-system-metrics",
  TASKFLOW_DIAGNOSTICS: "results-section-taskflow-diagnostics",
  FILTERS_OVERVIEW: "results-section-filters-overview",
} as const;

function scrollToResultsSection(sectionId: string) {
  if (typeof document === "undefined" || typeof window === "undefined") {
    return;
  }

  const element = document.getElementById(sectionId);
  window.history.replaceState(window.history.state || {}, "", `#${sectionId}`);

  if (element) {
    element.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function getFunctionNavMetadata(functionName: string) {
  const functionId = String(functionName || "").trim().toLowerCase();
  return FUNCTION_METADATA.find((option) => option.id === functionId);
}

function getJobFunctionNames(savedJobInfo?: JobLogData): string[] {
  return savedJobInfo?.functions ? savedJobInfo?.functions : [];
}

function toWorkflowTitleSuffix(workflowId?: string): string | undefined {
  const raw = String(workflowId || "").trim();
  if (!raw) return undefined;

  const displayName = formatWorkflowDisplayName(raw);
  return displayName !== raw ? displayName : undefined;
}

function attachWorkflowTitleSuffix(workflows: WorkflowJobData[]): WorkflowJobData[] {
  return (workflows || []).map((workflow) => ({
    ...workflow,
    workflowTitleSuffix: toWorkflowTitleSuffix(workflow.workflowId),
  }));
}

const RESULT_FUNCTION_LOAD_ORDER = [
  SupportedFunction.SURVIVAL_ANALYSIS,
  SupportedFunction.MEAN,
  SupportedFunction.STANDARD_DEVIATION,
  SupportedFunction.CHI_SQUARE_TEST,
  SupportedFunction.T_TEST,
  SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION,
];

interface ResultLoadProgress {
  completed: number;
  total: number;
  label: string;
}


const RESULT_LOAD_ARTIFICIAL_DELAY_MS = 175;

function waitForArtificialResultLoadDelay(): Promise<void> {
  if (RESULT_LOAD_ARTIFICIAL_DELAY_MS <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    window.setTimeout(resolve, RESULT_LOAD_ARTIFICIAL_DELAY_MS);
  });
}

function getResultFunctionDisplayName(fn: string): string {
  return formatFunctionName(normalizeFunctionName(fn));
}

/** True once the NVFlare run has stopped (any FINISHED:* state, or a job-runner terminal state). */
function isTerminalJobStatus(status: string | null | undefined): boolean {
  const upper = String(status || "").trim().toUpperCase();
  if (!upper) return false;
  return (
    upper.startsWith("FINISHED:") ||
    upper === "DONE" ||
    upper === "FAILURE" ||
    upper.includes("ABORT") ||
    upper.includes("CANCEL")
  );
}

function formatFilterFieldName(key: string): string {
  return String(key || "")
    .replace(/Filters$/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function parseFilterValue(value: unknown): unknown {
  if (typeof value !== "string") {
    return value;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function stringifyFilterValue(value: unknown): string {
  if (value == null || value === "") {
    return "Any";
  }

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value.length ? value.map((entry) => stringifyFilterValue(entry)).join(", ") : "Any";
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function flattenFilterRows(value: unknown, prefix = ""): Array<[string, string]> {
  const parsed = parseFilterValue(value);

  if (parsed == null || parsed === "" || (typeof parsed === "object" && !Array.isArray(parsed) && Object.keys(parsed as Record<string, unknown>).length === 0)) {
    return [];
  }

  if (Array.isArray(parsed)) {
    if (!parsed.length) {
      return [];
    }

    const rows: Array<[string, string]> = [];

    parsed.forEach((entry, index) => {
      const rowPrefix = prefix ? `${prefix} ${index + 1}` : `Filter ${index + 1}`;

      if (entry && typeof entry === "object" && !Array.isArray(entry)) {
        const record = entry as Record<string, unknown>;
        const label =
          stringifyFilterValue(record.label ?? record.name ?? record.id ?? record.field ?? record.code ?? rowPrefix);
        const value =
          record.value ?? record.selectedValue ?? record.selectedValues ?? record.operator ?? record.condition ?? record;

        rows.push([label, stringifyFilterValue(value)]);
      } else {
        rows.push([rowPrefix, stringifyFilterValue(entry)]);
      }
    });

    return rows;
  }

  if (typeof parsed === "object") {
    const rows: Array<[string, string]> = [];

    Object.entries(parsed as Record<string, unknown>).forEach(([key, entry]) => {
      const label = prefix ? `${prefix} ${formatFilterFieldName(key)}` : formatFilterFieldName(key);
      const nested = parseFilterValue(entry);

      if (nested && typeof nested === "object" && !Array.isArray(nested)) {
        const record = nested as Record<string, unknown>;
        const hasDisplayValue =
          "value" in record ||
          "selectedValue" in record ||
          "selectedValues" in record ||
          "label" in record ||
          "operator" in record ||
          "condition" in record;

        if (hasDisplayValue) {
          const rowLabel = stringifyFilterValue(record.label ?? record.name ?? label);
          const rowValue = record.value ?? record.selectedValue ?? record.selectedValues ?? record.condition ?? record.operator ?? nested;
          rows.push([rowLabel, stringifyFilterValue(rowValue)]);
        } else {
          const childRows = flattenFilterRows(nested, label);
          rows.push(...childRows);
        }
      } else {
        rows.push([label, stringifyFilterValue(nested)]);
      }
    });

    return rows;
  }

  return [[prefix || "Filter", stringifyFilterValue(parsed)]];
}

function formatJobSummaryValue(value: unknown): string {
  if (value == null || value === "") {
    return "";
  }

  if (Array.isArray(value)) {
    return value.length ? value.map((entry) => formatJobSummaryValue(entry)).filter(Boolean).join(", ") : "";
  }

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function getJobSummaryValue(...sources: unknown[]): string {
  for (const source of sources) {
    const value = formatJobSummaryValue(source);
    if (value) {
      return value;
    }
  }

  return "";
}

function readJobSummaryField(source: unknown, fieldNames: string[]): unknown {
  if (!source || typeof source !== "object") {
    return undefined;
  }

  const record = source as Record<string, unknown>;

  for (const fieldName of fieldNames) {
    if (Object.prototype.hasOwnProperty.call(record, fieldName)) {
      return record[fieldName];
    }
  }

  return undefined;
}

function buildJobSummaryExportSection(nvflareJobInfo: NVFlareJob | null, savedJobInfo?: JobLogData): ExportSection {
  const summaryRows = [
    [
      "Job ID",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["job_id", "jobId", "id", "nvflare_job_id", "nvflareJobId"]),
        savedJobInfo?.referencedBy?.[0],
        readJobSummaryField(savedJobInfo, ["job_id", "jobId", "id", "nvflare_job_id", "nvflareJobId"])
      ),
    ],
    [
      "Status",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["status", "job_status", "jobStatus", "runner_status", "runnerStatus"]),
        readJobSummaryField(savedJobInfo, ["status", "job_status", "jobStatus", "runner_status", "runnerStatus"])
      ),
    ],
    [
      "Project",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["project", "project_name", "projectName", "project_id", "projectId"]),
        readJobSummaryField(savedJobInfo, ["project", "project_name", "projectName", "project_id", "projectId"])
      ),
    ],
    [
      "Submitted By",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["submitted_by", "submittedBy", "username", "user", "created_by", "createdBy"]),
        readJobSummaryField(savedJobInfo, ["submitted_by", "submittedBy", "username", "user", "created_by", "createdBy"])
      ),
    ],
    [
      "Created",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["created_at", "createdAt", "create_time", "createTime", "submit_time", "submitTime"]),
        readJobSummaryField(savedJobInfo, ["created_at", "createdAt", "create_time", "createTime", "submit_time", "submitTime"])
      ),
    ],
    [
      "Started",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["started_at", "startedAt", "start_time", "startTime"]),
        readJobSummaryField(savedJobInfo, ["started_at", "startedAt", "start_time", "startTime"])
      ),
    ],
    [
      "Completed",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["completed_at", "completedAt", "finished_at", "finishedAt", "end_time", "endTime"]),
        readJobSummaryField(savedJobInfo, ["completed_at", "completedAt", "finished_at", "finishedAt", "end_time", "endTime"])
      ),
    ],
    [
      "Functions",
      getJobSummaryValue(
        readJobSummaryField(nvflareJobInfo, ["functions", "function_names", "functionNames"]),
        savedJobInfo?.functions,
        readJobSummaryField(savedJobInfo, ["functions", "function_names", "functionNames"])
      ),
    ],
    [
      "Threshold Comparison",
      nvflareJobInfo?.threshold
        ? `${formatThresholdMethod(nvflareJobInfo.threshold.method)}, minimum sample count ${nvflareJobInfo.threshold.threshold}`
        : "",
    ],
  ].filter((row): row is [string, string] => Boolean(row[1]));

  const blocks: ExportSection["blocks"] = summaryRows.length > 0
    ? [
      {
        kind: "keyValues",
        items: summaryRows.map(([label, value]) => ({ label, value })),
      },
    ]
    : [
      {
        kind: "paragraph",
        text: "No job summary details are currently available.",
      },
    ];

  return {
    id: "job-summary",
    title: "Job Summary",
    blocks,
  };
}

function buildFiltersOverviewExportSection(
  submittedFilterSet: FilterCollection,
  submittedFilterSetName: string
): ExportSection {
  const blocks: ExportSection["blocks"] = [
    {
      kind: "keyValues",
      items: [
        { label: "Filter Set", value: submittedFilterSetName || "Filters Overview" },
      ],
    },
  ];

  Object.entries(submittedFilterSet || {}).forEach(([key, value]) => {
    const rows = flattenFilterRows(value);

    blocks.push({
      kind: "heading",
      text: formatFilterFieldName(key),
      level: 3,
    });

    if (rows.length > 0) {
      blocks.push({
        kind: "table",
        columns: ["Filter", "Value"],
        rows,
      });
    } else {
      blocks.push({
        kind: "paragraph",
        text: "No filters applied.",
      });
    }
  });

  return {
    id: "filters-overview",
    title: "Filters Overview",
    blocks,
  };
}

const ResultsPageInner: React.FC<ResultsPageProps> = ({
  onBack,
  onStartOver,
  submittedFilterSet,
  submittedFilterSetName,
  savedJobInfo,
  viewOnly,
  onBackToHistory,
  directEntry = false,
  nvflareJobId: nvflareJobIdProp,
  project: projectProp,
  onContextLoaded,
}) => {
  const userSession = useUserSession();
  const role = userSession.role;
  const jobApiSession = useMemo(
    () => ({ role: userSession.role, client_name: userSession.client_name ?? null }),
    [userSession.role, userSession.client_name]
  );
  const { getSections } = useExportRegistry();
  const onContextLoadedRef = useRef(onContextLoaded);

  useEffect(() => {
    onContextLoadedRef.current = onContextLoaded;
  }, [onContextLoaded]);

  const nvflareJobId = nvflareJobIdProp || savedJobInfo?.referencedBy?.[0];
  const savedAvailableFunctions = useMemo(() => getJobFunctionNames(savedJobInfo), [savedJobInfo]);

  const [survivabilityWorkflows, setSurvivabilityWorkflows] = useState<WorkflowJobData[]>([]);
  const [tTestWorkflows, setTTestWorkflows] = useState<WorkflowJobData[]>([]);
  const [meanWorkflows, setMeanWorkflows] = useState<WorkflowJobData[]>([]);
  const [chi2Workflows, setChi2Workflows] = useState<WorkflowJobData[]>([]);
  const [stDevWorkflows, setStDevWorkflows] = useState<WorkflowJobData[]>([]);
  const [logCalibrationWorkflows, setLogCalibrationWorkflows] = useState<WorkflowJobData[]>([]);
  // Functions this job requested that produced no result directory at all. Without this the
  // section is simply absent from the page, which is indistinguishable from "never requested".
  const [functionsWithoutResults, setFunctionsWithoutResults] = useState<string[]>([]);

  const [activeSurvIndex, setActiveSurvIndex] = useState(0);
  const [activeMeanIndex, setActiveMeanIndex] = useState(0);
  const [activeChi2Index, setActiveChi2Index] = useState(0);
  const [activeStDevIndex, setActiveStDevIndex] = useState(0);
  const [activeTTestIndex, setActiveTTestIndex] = useState(0);
  const [activeLogCalibrationIndex, setActiveLogCalibrationIndex] = useState(0);

  const [loading, setLoading] = useState(Boolean(nvflareJobId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [exportFormatModalOpen, setExportFormatModalOpen] = useState(false);
  const [exportSectionModalOpen, setExportSectionModalOpen] = useState(false);
  const [selectedExportFormat, setSelectedExportFormat] = useState<ExportFormat | null>(null);
  const [exportableSections, setExportableSections] = useState<Array<{ id: string; title: string; section: ExportSection }>>([]);
  const [exporting, setExporting] = useState(false);
  const [profileSummary, setProfileSummary] = useState<ProfileSummary | null>(null);
  const [taskflowDiagnostics, setTaskflowDiagnostics] = useState<TaskflowDiagnosticsResponse | null>(null);
  const [nvflareJobInfo, setNVFlareJobInfo] = useState<NVFlareJob | null>(null);
  const [resultsProject, setResultsProject] = useState<Project | null>(projectProp ?? null);
  const [resolvedFilterSet, setResolvedFilterSet] = useState<FilterCollection>(submittedFilterSet);
  const [resolvedFilterSetName, setResolvedFilterSetName] = useState(submittedFilterSetName);
  const [jobInfoProgress, setJobInfoProgress] = useState<ResultLoadProgress>({
    completed: 0,
    total: 1,
    label: "Preparing NVFlare job information",
  });
  const [mappingProgress, setMappingProgress] = useState<ResultLoadProgress>({
    completed: 0,
    total: 1,
    label: "Waiting for NVFlare job information",
  });
  const [resultsProgress, setResultsProgress] = useState<ResultLoadProgress>({
    completed: 0,
    total: 1,
    label: "Waiting for workflow mappings",
  });

  const runDurationTime = nvflareJobInfo?.run_duration || savedJobInfo?.run_duration;

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoadError(null);
        setSurvivabilityWorkflows([]);
        setMeanWorkflows([]);
        setStDevWorkflows([]);
        setChi2Workflows([]);
        setTTestWorkflows([]);
        setLogCalibrationWorkflows([]);
        setProfileSummary(null);
        setTaskflowDiagnostics(null);
        setNVFlareJobInfo(null);
        setResultsProject(projectProp ?? null);
        setResolvedFilterSet(submittedFilterSet);
        setResolvedFilterSetName(submittedFilterSetName);
        setJobInfoProgress({ completed: 0, total: 1, label: "Preparing NVFlare job information" });
        setMappingProgress({ completed: 0, total: 1, label: "Waiting for NVFlare job information" });
        setResultsProgress({ completed: 0, total: 1, label: "Waiting for workflow mappings" });

        if (!nvflareJobId) {
          return;
        }

        setLoading(true);

        let completedJobInfoSteps = 0;
        const totalJobInfoSteps = 1;
        let completedMappingSteps = 0;
        let totalMappingSteps = 1;
        let completedResultSteps = 0;
        let totalResultSteps = 1;

        const updateJobInfoProgress = (label: string) => {
          if (cancelled) return;
          setJobInfoProgress({
            completed: Math.min(completedJobInfoSteps, totalJobInfoSteps),
            total: totalJobInfoSteps,
            label,
          });
        };

        const updateMappingProgress = (label: string) => {
          if (cancelled) return;
          setMappingProgress({
            completed: Math.min(completedMappingSteps, Math.max(totalMappingSteps, 1)),
            total: Math.max(totalMappingSteps, 1),
            label,
          });
        };

        const updateResultsProgress = (label: string) => {
          if (cancelled) return;
          setResultsProgress({
            completed: Math.min(completedResultSteps, Math.max(totalResultSteps, 1)),
            total: Math.max(totalResultSteps, 1),
            label,
          });
        };

        updateJobInfoProgress("Loading NVFlare job information");

        let loadedJobInfo: NVFlareJob | null = null;

        if (directEntry) {
          const resultsContext = await fetchResultsContext(nvflareJobId);
          loadedJobInfo = resultsContext.job;

          if (!cancelled) {
            setResultsProject(resultsContext.project);

            const loadedFilter = resultsContext.filter;
            if (loadedFilter) {
              setResolvedFilterSet(
                buildDefaultFilterCollectionFromConditions(
                  loadedFilter.conditions || [],
                  resultsContext.project
                )
              );
              setResolvedFilterSetName(loadedFilter.name || "");
            }

            onContextLoadedRef.current?.(resultsContext.project);
          }
        } else {
          try {
            loadedJobInfo = await fetchNVFlareJobInfo(nvflareJobId, jobApiSession);
          } catch (error) {
            console.warn("ResultsPage: Failed to load NVFlare job information", error);
          }
        }

        completedJobInfoSteps += 1;
        if (!cancelled) {
          setNVFlareJobInfo(loadedJobInfo);
        }

        const jobFunctions = loadedJobInfo?.functions?.length
          ? loadedJobInfo.functions
          : savedAvailableFunctions;
        const normalizedJobFunctions = new Set(jobFunctions.map((fn) => normalizeFunctionName(fn)));
        const functionsToLoad = RESULT_FUNCTION_LOAD_ORDER.filter((fn) => normalizedJobFunctions.has(normalizeFunctionName(fn)));
        totalMappingSteps = Math.max(functionsToLoad.length, 1);
        totalResultSteps = 1;
        updateJobInfoProgress("Loaded NVFlare job information");
        updateMappingProgress(functionsToLoad.length ? "Preparing workflow mapping lookup" : "No workflow mappings to load");
        updateResultsProgress("Waiting for workflow mappings");
        const workflowMappings: Array<{
          functionName: string;
          workflowIds: string[];
          profileSummary: ProfileSummary | null;
        }> = [];

        for (const functionName of functionsToLoad) {
          const displayName = getResultFunctionDisplayName(functionName);
          updateMappingProgress(`Loading ${displayName} workflow list`);
          const { workflowIds, profileSummary: functionProfileSummary } = await fetchWorkflowMapping(
            nvflareJobId,
            functionName,
            jobApiSession
          );

          workflowMappings.push({
            functionName,
            workflowIds,
            profileSummary: functionProfileSummary,
          });

          completedMappingSteps += 1;
          updateMappingProgress(`Loaded ${displayName} workflow list`);
        }

        completedMappingSteps = totalMappingSteps;
        updateMappingProgress("Loaded workflow mappings");

        // A requested function with no workflow directory produced nothing at all. Record it
        // so the page can say so instead of dropping the section.
        if (!cancelled) {
          setFunctionsWithoutResults(
            workflowMappings
              .filter((mapping) => mapping.workflowIds.length === 0)
              .map((mapping) => mapping.functionName)
          );
        }

        const totalWorkflowResultSteps = workflowMappings.reduce((sum, mapping) => sum + mapping.workflowIds.length, 0);
        totalResultSteps = Math.max(totalWorkflowResultSteps, 1);
        updateResultsProgress(totalWorkflowResultSteps ? "Loading workflow results data" : "No workflow results to load");
        const responses: Array<{
          functionName: string;
          workflows: WorkflowJobData[];
          profileSummary: ProfileSummary | null;
        }> = [];

        for (const mapping of workflowMappings) {
          const functionName = mapping.functionName;
          const workflowIds = mapping.workflowIds;
          const displayName = getResultFunctionDisplayName(functionName);
          const workflows: WorkflowJobData[] = [];

          for (let i = 0; i < workflowIds.length; i += 1) {
            const workflowId = workflowIds[i];
            updateResultsProgress(`Loading ${displayName} results ${i + 1} of ${workflowIds.length}`);
            const { jobData, functionConfig, workflowError } = await fetchJobResultsForWorkflow(
              nvflareJobId,
              functionName,
              workflowId,
              jobApiSession
            );

            workflows.push({
              workflowId,
              functionName,
              jobData,
              functionConfig,
              workflowError,
            });

            completedResultSteps += 1;
            updateResultsProgress(`Loaded ${displayName} results ${i + 1} of ${workflowIds.length}`);
          }

          responses.push({
            functionName,
            workflows,
            profileSummary: mapping.profileSummary,
          });
        }

        completedResultSteps = totalResultSteps;
        updateResultsProgress("Loaded all results data");
        await waitForArtificialResultLoadDelay();
        if (cancelled) {
          return;
        }

        let localProfileSummary: ProfileSummary | null = null;

        for (const response of responses) {
          if (!localProfileSummary && response.profileSummary) {
            localProfileSummary = response.profileSummary;
          }
        }

        if (localProfileSummary) {
          setProfileSummary(localProfileSummary);
        }

        const findByFunction = (fn: string): WorkflowJobData[] => {
          const upper = normalizeFunctionName(fn);
          return responses.find((response) => normalizeFunctionName(response.functionName || "") === upper)?.workflows || [];
        };

        setSurvivabilityWorkflows(attachWorkflowTitleSuffix(findByFunction(SupportedFunction.SURVIVAL_ANALYSIS)));
        setMeanWorkflows(attachWorkflowTitleSuffix(findByFunction(SupportedFunction.MEAN)));
        setStDevWorkflows(attachWorkflowTitleSuffix(findByFunction(SupportedFunction.STANDARD_DEVIATION)));
        setChi2Workflows(attachWorkflowTitleSuffix(findByFunction(SupportedFunction.CHI_SQUARE_TEST)));
        setTTestWorkflows(attachWorkflowTitleSuffix(findByFunction(SupportedFunction.T_TEST)));
        setLogCalibrationWorkflows(attachWorkflowTitleSuffix(findByFunction(SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION)));

        setActiveSurvIndex(0);
        setActiveMeanIndex(0);
        setActiveStDevIndex(0);
        setActiveChi2Index(0);
        setActiveTTestIndex(0);
        setActiveLogCalibrationIndex(0);
      } catch (err: any) {
        console.error(err);
        setLoadError(err?.message || "Failed to load workflow results.");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [
    directEntry,
    jobApiSession,
    nvflareJobId,
    projectProp,
    savedAvailableFunctions,
    submittedFilterSet,
    submittedFilterSetName,
  ]);

  useEffect(() => {
    if (!TASKFLOW_DIAGNOSTICS_ENABLED || role !== UserRole.INITIATOR || !nvflareJobId || loading || loadError) {
      return;
    }

    let cancelled = false;
    let pollTimer: number | undefined;

    const schedulePoll = () => {
      pollTimer = window.setTimeout(async () => {
        try {
          const diagnostics = await fetchTaskflowDiagnostics(nvflareJobId);
          if (cancelled) return;

          setTaskflowDiagnostics(diagnostics);
          if (["idle", "queued", "running"].includes(diagnostics.status.state)) {
            schedulePoll();
          }
        } catch (error: any) {
          if (cancelled) return;
          setTaskflowDiagnostics({
            status: {
              state: "failed",
              progress: 100,
              label: "Unable to load taskflow diagnostics",
              error: error?.message || "Unable to load taskflow diagnostics",
            },
            summary: null,
            rounds: [],
            artifacts: [],
          });
        }
      }, 750);
    };

    const start = async () => {
      try {
        const diagnostics = await startTaskflowDiagnostics(nvflareJobId);
        if (cancelled) return;

        setTaskflowDiagnostics(diagnostics);
        if (["idle", "queued", "running"].includes(diagnostics.status.state)) {
          schedulePoll();
        }
      } catch (error: any) {
        if (cancelled) return;
        setTaskflowDiagnostics({
          status: {
            state: "failed",
            progress: 100,
            label: "Unable to start taskflow diagnostics",
            error: error?.message || "Unable to start taskflow diagnostics",
          },
          summary: null,
          rounds: [],
          artifacts: [],
        });
      }
    };

    start();

    return () => {
      cancelled = true;
      if (pollTimer !== undefined) {
        window.clearTimeout(pollTimer);
      }
    };
  }, [jobApiSession, loadError, loading, nvflareJobId, role]);

  const hasSurvResults = useMemo(() => survivabilityWorkflows.length > 0, [survivabilityWorkflows]);
  const hasMeanResults = useMemo(() => meanWorkflows.length > 0, [meanWorkflows]);
  const hasChi2Results = useMemo(() => chi2Workflows.length > 0, [chi2Workflows]);
  const hasStDevResults = useMemo(() => stDevWorkflows.length > 0, [stDevWorkflows]);
  const hasTTestResults = useMemo(() => tTestWorkflows.length > 0, [tTestWorkflows]);
  const hasLogCalibrationResults = useMemo(() => logCalibrationWorkflows.length > 0, [logCalibrationWorkflows]);

  const handleExportClick = () => {
    setExportFormatModalOpen(true);
  };

  const loadExportableSections = async (format: ExportFormat) => {
    setSelectedExportFormat(format);
    setExportFormatModalOpen(false);
    setExporting(true);

    try {
      const regs = getSections();
      const sections: Array<{ id: string; title: string; section: ExportSection }> = [
        {
          id: "job-summary",
          title: "Job Summary",
          section: buildJobSummaryExportSection(nvflareJobInfo, savedJobInfo),
        },
      ];

      for (const r of regs) {
        const section = await r.exportSection();
        if (section) {
          sections.push({
            id: r.id,
            title: r.title || section.title,
            section: { ...section, id: section.id || r.id },
          });
        }
      }

      sections.push({
        id: "filters-overview",
        title: "Filters Overview",
        section: buildFiltersOverviewExportSection(resolvedFilterSet, resolvedFilterSetName),
      });

      setExportableSections(sections);
      setExportSectionModalOpen(true);
    } finally {
      setExporting(false);
    }
  };

  const filterBlocksForOptions = (blocks: ExportSection["blocks"], selectedOptionIds: string[]) => {
    return (blocks || []).filter((block) => !block.optionId || selectedOptionIds.includes(block.optionId));
  };

  const isFiltersOverviewExportSection = (section: ExportSection): boolean => {
    const id = String(section.id || "").trim().toLowerCase();
    const title = String(section.title || "").trim().toLowerCase();
    return id === "filters-overview" || title === "filters overview";
  };

  const moveFiltersOverviewToEnd = (sections: ExportSection[]): ExportSection[] => {
    const filtersOverviewSections = sections.filter(isFiltersOverviewExportSection);
    if (filtersOverviewSections.length === 0) {
      return sections;
    }

    return [
      ...sections.filter((section) => !isFiltersOverviewExportSection(section)),
      ...filtersOverviewSections,
    ];
  };

  const filterSectionForExport = (
    section: ExportSection,
    selectedSectionOptionIds: string[],
    workflowSelection?: ExportWorkflowSelectionBySectionId[string]
  ): ExportSection => {
    if (!section.workflows || section.workflows.length === 0) {
      return {
        ...section,
        blocks: filterBlocksForOptions(section.blocks, selectedSectionOptionIds),
      };
    }

    const selectedWorkflowIds = workflowSelection?.workflowIds || section.workflows.map((workflow) => workflow.id);
    const selectedWorkflowIdSet = new Set(selectedWorkflowIds);
    const optionSelectionsByWorkflowId = workflowSelection?.optionSelectionsByWorkflowId || {};

    return {
      ...section,
      blocks: filterBlocksForOptions(section.blocks, selectedSectionOptionIds),
      workflows: section.workflows
        .filter((workflow) => selectedWorkflowIdSet.has(workflow.id))
        .map((workflow) => ({
          ...workflow,
          blocks: filterBlocksForOptions(
            workflow.blocks,
            optionSelectionsByWorkflowId[workflow.id] || (workflow.options || []).filter((option) => option.checkedByDefault !== false).map((option) => option.id)
          ),
        })),
    };
  };

  const handleExportSections = async (
    sectionIds: string[],
    optionSelectionsBySectionId: Record<string, string[]>,
    workflowSelectionsBySectionId: ExportWorkflowSelectionBySectionId
  ) => {
    if (!selectedExportFormat) return;

    setExporting(true);

    try {
      const selectedSections = moveFiltersOverviewToEnd(
        exportableSections
          .filter((entry) => sectionIds.includes(entry.id))
          .map((entry) =>
            filterSectionForExport(
              entry.section,
              optionSelectionsBySectionId[entry.id] || [],
              workflowSelectionsBySectionId[entry.id]
            )
          )
      );

      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const document: ExportDocument = {
        title: "SHARE Job Results Export",
        generatedAt: new Date().toLocaleString(),
        sections: selectedSections,
      };

      if (selectedExportFormat === "pdf") {
        await downloadPdf(document, `share-results-${stamp}.pdf`);
      } else if (selectedExportFormat === "docx") {
        await downloadDocx(document, `share-results-${stamp}.docx`);
      } else if (selectedExportFormat === "html") {
        downloadHtml(document, `share-results-${stamp}.html`);
      } else if (selectedExportFormat === "png") {
        const root = window.document.getElementById("share-results-export-root");
        if (root) {
          await downloadElementAsPng(root, `share-results-${stamp}.png`);
        }
      }

      setExportSectionModalOpen(false);
      setSelectedExportFormat(null);
    } finally {
      setExporting(false);
    }
  };

  if (!resultsProject && !projectProp && !loading) {
    return (
      <div className="page-container">
        <div className="child-container-results-page">
          {loadError || "Unable to load the project associated with this NVFlare job."}
        </div>
      </div>
    );
  }

  const resolvedProject = resultsProject ?? projectProp!;

  const metricSections: Array<{ title: string; functionName: string; workflowCount: number; element: JSX.Element }> = [];

  if (hasTTestResults) {
    metricSections.push({
      title: "T-Test",
      functionName: SupportedFunction.T_TEST,
      workflowCount: tTestWorkflows.length,
      element: (
        <TTestResultCard
          key="t-test"
          workflows={tTestWorkflows}
          activeIndex={activeTTestIndex}
          onActiveIndexChange={setActiveTTestIndex}
          analyticsWorkflows={profileSummary?.workflows ?? null}
          project={resolvedProject}
          userRole={role}
        />
      ),
    });
  }

  if (hasLogCalibrationResults) {
    metricSections.push({
      title: "Exceptional Response Discrimination",
      functionName: SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION,
      workflowCount: logCalibrationWorkflows.length,
      element: (
        <LogisticCalibrationResultCard
          key="logistic-calibration"
          workflows={logCalibrationWorkflows}
          activeIndex={activeLogCalibrationIndex}
          onActiveIndexChange={setActiveLogCalibrationIndex}
          analyticsWorkflows={profileSummary?.workflows ?? null}
          project={resolvedProject}
          userRole={role}
        />
      ),
    });
  }

  if (hasMeanResults) {
    metricSections.push({
      title: "Mean",
      functionName: SupportedFunction.MEAN,
      workflowCount: meanWorkflows.length,
      element: (
        <MeanResultCard
          key="mean"
          workflows={meanWorkflows}
          activeIndex={activeMeanIndex}
          onActiveIndexChange={setActiveMeanIndex}
          analyticsWorkflows={profileSummary?.workflows ?? null}
          project={resolvedProject}
          userRole={role}
        />
      ),
    });
  }

  if (hasChi2Results) {
    metricSections.push({
      title: "Chi Square Test",
      functionName: SupportedFunction.CHI_SQUARE_TEST,
      workflowCount: chi2Workflows.length,
      element: (
        <Chi2ResultCard
          key="chi2"
          workflows={chi2Workflows}
          activeIndex={activeChi2Index}
          onActiveIndexChange={setActiveChi2Index}
          analyticsWorkflows={profileSummary?.workflows ?? null}
          project={resolvedProject}
          userRole={role}
        />
      ),
    });
  }

  if (hasStDevResults) {
    metricSections.push({
      title: "Standard Deviation",
      functionName: SupportedFunction.STANDARD_DEVIATION,
      workflowCount: stDevWorkflows.length,
      element: (
        <StDevResultCard
          key="stdev"
          workflows={stDevWorkflows}
          activeIndex={activeStDevIndex}
          onActiveIndexChange={setActiveStDevIndex}
          analyticsWorkflows={profileSummary?.workflows ?? null}
          project={resolvedProject}
          userRole={role}
        />
      ),
    });
  }

  // Requested computations that produced nothing get a section of their own rather than being
  // omitted: an absent section reads as "not requested", which is how an incomplete run came to
  // look like a successful one. Only shown once the job has stopped, so a still-loading run
  // does not flash the notice.
  if (isTerminalJobStatus(nvflareJobInfo?.status)) {
    for (const functionName of functionsWithoutResults) {
      const title = getResultFunctionDisplayName(functionName);
      metricSections.push({
        title,
        functionName,
        workflowCount: 0,
        element: (
          <div key={`missing-${functionName}`} className="result-card-block-01">
            <div className="result-card-block-04">{title}</div>
            <WorkflowErrorPanel
              error={{
                workflow: functionName,
                code: "NO_RESULTS_PRODUCED",
                message:
                  "This computation was requested but produced no results, so the run did not " +
                  "deliver everything that was asked for. The job log records where it stopped.",
              }}
              variant="warning"
              title="No results produced"
              defaultExpanded
              showTracebackToggle={false}
            />
          </div>
        ),
      });
    }
  }

  const sortedMetricSections = metricSections.sort((a, b) => {
    if (a.workflowCount !== b.workflowCount) {
      return b.workflowCount - a.workflowCount;
    }

    return a.title.localeCompare(b.title);
  });

  const metricColumns = sortedMetricSections.map((section) => (
    <div key={section.functionName} id={getResultFunctionAnchorId(section.functionName)} className="results-page-shared-01">
      {section.element}
    </div>
  ));

  const resultFunctionNavItems = [
    ...(hasSurvResults
      ? [{ title: "Survival Analysis", functionName: SupportedFunction.SURVIVAL_ANALYSIS }]
      : []),
    ...sortedMetricSections.map((section) => ({
      title: section.title,
      functionName: section.functionName,
    })),
  ];

  const hasAnyScalarResults = metricColumns.length > 0;
  const jobInfoProgressPercent = Math.max(
    0,
    Math.min(100, Math.round((jobInfoProgress.completed / Math.max(jobInfoProgress.total, 1)) * 100))
  );
  const mappingProgressPercent = Math.max(
    0,
    Math.min(100, Math.round((mappingProgress.completed / Math.max(mappingProgress.total, 1)) * 100))
  );
  const resultsProgressPercent = Math.max(
    0,
    Math.min(100, Math.round((resultsProgress.completed / Math.max(resultsProgress.total, 1)) * 100))
  );

  return (
    <>
      <HeaderTitle
        transparentBackground
        iconPath="/icons/nav_icon_job_results.png"
        title={
          <>
            Analysis Results: <ProjectNameWithDescription project={resolvedProject} />
          </>
        }
        description={
          <nav className="results-section-nav" aria-label="Results sections">
            <span className="results-section-nav-label">Jump to:</span>
            <button
              type="button"
              className="results-section-link"
              onClick={() => scrollToResultsSection(RESULTS_SECTION_IDS.FILTERS_OVERVIEW)}
            >
              Filters Overview
            </button>

            {resultFunctionNavItems.map((item) => {
              const metadata = getFunctionNavMetadata(item.functionName);
              return (
                <button
                  key={`results-nav-${item.functionName}`}
                  type="button"
                  className="results-section-link results-section-function-link"
                  onClick={() => scrollToResultsSection(getResultFunctionAnchorId(item.functionName))}
                >
                  {metadata?.icon && (
                    <img src={`/icons${metadata.icon}`} alt="" aria-hidden="true" />
                  )}
                  <span>{metadata?.title || item.title}</span>
                </button>
              );
            })}

            {profileSummary && (
              <button
                type="button"
                className="results-section-link"
                onClick={() => scrollToResultsSection(RESULTS_SECTION_IDS.SYSTEM_METRICS)}
              >
                System Metrics
              </button>
            )}

            {TASKFLOW_DIAGNOSTICS_ENABLED && role === UserRole.INITIATOR && !loading && taskflowDiagnostics && nvflareJobId && (
              <button
                type="button"
                className="results-section-link"
                onClick={() => scrollToResultsSection(RESULTS_SECTION_IDS.TASKFLOW_DIAGNOSTICS)}
              >
                Taskflow Diagnostics
              </button>
            )}
          </nav>
        }
      />
      <div className="page-container">
        <div id="share-results-export-root" className="child-container-results-page">
          <div
            id={RESULTS_SECTION_IDS.JOB_SUMMARY}
            className="results-page-block-01"
          >
            <NVFlareJobSummary nvflareJob={nvflareJobInfo} enableFunctionLinks />
          </div>

          <div
            id={RESULTS_SECTION_IDS.FILTERS_OVERVIEW}
            className="results-page-shared-02"
          >
            <FilterSummary submittedFilterSet={resolvedFilterSet} submittedFilterSetName={resolvedFilterSetName} />
          </div>

          {loadError && (
            <div
              className="results-page-block-02"
            >
              {loadError}
            </div>
          )}

          {loading && (
            <div
              className="results-page-block-03"
            >
              <div className="results-page-block-04">Loading Results Data</div>

              <div className="duality-mb-075">
                <div
                  className="duality-d-flex-justify-space-between-align-center"
                >
                  <span>NVFlare Job Information</span>
                  <span>{jobInfoProgressPercent}%</span>
                </div>
                <div
                  className="duality-h-0p75rem-w-100pct-bg-e5e7eb"
                >
                  <div
                    className="duality-h-100pct-bg-2563eb-transition-width-160ms-ease-i" style={{ width: `${jobInfoProgressPercent}%` }}
                  />
                </div>
                <div className="duality-mt-0p35rem-fs-10pt-text-4b5563">{jobInfoProgress.label}</div>
              </div>

              <div className="duality-mb-075">
                <div
                  className="duality-d-flex-justify-space-between-align-center"
                >
                  <span>Workflow Mapping</span>
                  <span>{mappingProgressPercent}%</span>
                </div>
                <div
                  className="duality-h-0p75rem-w-100pct-bg-e5e7eb"
                >
                  <div
                    className="duality-h-100pct-bg-2563eb-transition-width-160ms-ease-i" style={{ width: `${mappingProgressPercent}%` }}
                  />
                </div>
                <div className="duality-mt-0p35rem-fs-10pt-text-4b5563">{mappingProgress.label}</div>
              </div>

              <div>
                <div
                  className="duality-d-flex-justify-space-between-align-center"
                >
                  <span>Workflow Results Data</span>
                  <span>{resultsProgressPercent}%</span>
                </div>
                <div
                  className="duality-h-0p75rem-w-100pct-bg-e5e7eb"
                >
                  <div
                    className="duality-h-100pct-bg-2563eb-transition-width-160ms-ease-i" style={{ width: `${resultsProgressPercent}%` }}
                  />
                </div>
                <div className="duality-mt-0p35rem-fs-10pt-text-4b5563">{resultsProgress.label}</div>
              </div>
            </div>
          )}

          {hasSurvResults && (
            <div id={getResultFunctionAnchorId(SupportedFunction.SURVIVAL_ANALYSIS)} className="results-page-shared-01">
              <SurvivabilityComponent
                jobsData={null}
                workflowId={undefined}
                functionName="SURVIVAL_ANALYSIS"
                workflows={survivabilityWorkflows}
                activeIndex={activeSurvIndex}
                onActiveIndexChange={setActiveSurvIndex}
                analyticsWorkflows={profileSummary?.workflows ?? null}
                project={resolvedProject}
                userRole={role}
              />
            </div>
          )}

          {hasAnyScalarResults && (
            <div
              className="results-page-block-05" style={{ gridTemplateColumns:
                  metricColumns.length === 1 ? "minmax(260px, 1fr)" : "repeat(2, minmax(260px, 1fr))" }}
            >
              {metricColumns}
            </div>
          )}

          {!loading && !loadError && !hasSurvResults && !hasAnyScalarResults && <></>}

          {profileSummary && (
            <div
              id={RESULTS_SECTION_IDS.SYSTEM_METRICS}
              className="results-page-shared-02"
            >
              <SystemMetricsAccordion
                metrics={profileSummary.system_metrics}
                combinedMetrics={profileSummary.combined_workflow_metrics}
                runDurationTime={runDurationTime}
                role={role}
              />
            </div>
          )}

          {TASKFLOW_DIAGNOSTICS_ENABLED && role === UserRole.INITIATOR && !loading && taskflowDiagnostics && nvflareJobId && (
            <div
              id={RESULTS_SECTION_IDS.TASKFLOW_DIAGNOSTICS}
              className="results-page-shared-02"
            >
              <TaskflowDiagnosticsPanel
                diagnostics={taskflowDiagnostics}
                nvflareJobId={nvflareJobId}
              />
            </div>
          )}

        </div>
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          {viewOnly ? (
            <>
              <button className="secondary-button" onClick={onBackToHistory} disabled={!onBackToHistory}>
                {directEntry ? "Back to Project Page" : "Back to Analysis History"}
              </button>
              <button onClick={handleExportClick} disabled={loading}>
                Export As...
              </button>
            </>
          ) : (
            <>
              <button className="secondary-button" onClick={onBack}>
                Back to Submission Details
              </button>
              <button onClick={handleExportClick} disabled={loading}>
                Export As...
              </button>
              <button onClick={onStartOver}>⟳ Start Over</button>
            </>
          )}
        </div>
      </div>

      <ExportFormatModal
        isOpen={exportFormatModalOpen}
        onClose={() => setExportFormatModalOpen(false)}
        onSelectFormat={loadExportableSections}
      />

      <ExportSectionSelectionModal
        isOpen={exportSectionModalOpen}
        format={selectedExportFormat}
        sections={exportableSections}
        isExporting={exporting}
        onBack={() => {
          setExportSectionModalOpen(false);
          setExportFormatModalOpen(true);
        }}
        onClose={() => setExportSectionModalOpen(false)}
        onExport={handleExportSections}
      />
    </>
  );
};

const ResultsPage: React.FC<ResultsPageProps> = (props) => {
  return (
    <ExportProvider>
      <ResultsPageInner {...props} />
    </ExportProvider>
  );
};

export default ResultsPage;
