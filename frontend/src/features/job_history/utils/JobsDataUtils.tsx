import {
  API_BASE,
  API_JOB_RESULTS,
  API_JOB_RESULTS_FUNCTION_CONFIG,
  API_JOB_RESULTS_MAPPING,
  API_JOB_RESULTS_CONTEXT,
  API_JOB_TASKFLOW_ARTIFACT,
  API_JOB_TASKFLOW_START,
  API_JOB_TASKFLOW_STATUS,
  getClientApiBase,
} from "../../../constants/Constants";

import { UserRole, UserSession } from "../../../context/UserRoleContext";
import { NVFlareJob } from "../../../types/JobsDataTypes";
import { Project } from "../../../types/Project";
import { Condition } from "../../job_runner/types/FilterSchema";
import { JobsDataShape } from "../components/SurvivabilityComponent";

const API_JOB_INFO = "/jobs/info";

export type FunctionConfig = Record<string, string>;

export type WorkflowErrorJson = {
  timestamp_utc?: string;
  job_id?: string;
  workflow?: string;
  round?: number;
  stage?: string;
  exception_type?: string;
  message?: string;
  traceback?: string;
  error?: string;
  client?: string;
  task?: string;
};

export type WorkflowJobData = {
  workflowId: string;
  functionName: string;
  jobData: JobsDataShape;
  functionConfig?: FunctionConfig | null;
  workflowError?: WorkflowErrorJson | null;
};

export function formatWorkflowDisplayName(
  workflowId?: string,
  functionDisplayName?: string,
  runIndex?: number,
): string {
  const raw = String(workflowId || "").trim();
  if (!raw) return "";

  const match = raw.match(/^workflow_stat_analytics_+(.+)$/i);
  const suffix = (match?.[1] || raw).trim();

  // Result-page workflow labels follow one rule everywhere:
  // <Function> [Cox Lasso | Logistic Reg] Workflow <function-relative run #>.
  // The backend workflow id is never changed; this is display-only.
  if (functionDisplayName) {
    const normalizedSuffix = suffix.toLowerCase().replace(/[^a-z0-9]+/g, "_");
    const variant = normalizedSuffix.includes("cox_lasso")
      ? "Cox Lasso"
      : normalizedSuffix.includes("logistic_reg")
        ? "Logistic Reg"
        : "";

    const fallbackRunNumber = /^\d+$/.test(suffix) ? Number(suffix) : 1;
    const displayRunNumber =
      typeof runIndex === "number" && Number.isFinite(runIndex)
        ? runIndex
        : fallbackRunNumber;

    return `${functionDisplayName}${variant ? ` ${variant}` : ""} Workflow ${displayRunNumber}`;
  }

  if (!match || !suffix) return raw;

  return suffix
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export type ProfileSummaryWorkflowRoundMetrics = {
  server_dispatch_time_sec?: number;
  server_accept_time_sec?: number;
  server_aggregation_time_sec?: number;
  server_compute_time_sec?: number;
  payload_in_bytes?: number;
  payload_out_bytes?: number;
  client_compute_time_sec?: number;
  upstream_rtt_sec?: number;
  downstream_rtt_sec?: number;
  phase_breakdown_sec?: Record<string, number>;
};

export type ProfileSummaryWorkflows = {
  [workflowName: string]: {
    [round: string]: ProfileSummaryWorkflowRoundMetrics;
  };
};

export type ProfileSummarySystemMetrics = {
  wall_time_sec: number;
  cpu_util_pct: number;
  cpu_user_pct: number;
  cpu_system_pct: number;
  cpu_iowait_pct: number;
  cpu_steal_pct: number;
  net_tx_bytes_total: number;
  net_rx_bytes_total: number;
  net_tx_mb_s: number;
  net_rx_mb_s: number;
  rss_max_kb: number;
};

export type CombinedWorkflowMetrics = {
  server_dispatch_time_sec?: number;
  server_accept_time_sec?: number;
  server_aggregation_time_sec?: number;
  server_compute_time_sec?: number;
  payload_in_bytes?: number;
  payload_out_bytes?: number;
  client_compute_time_sec?: number;
  upstream_rtt_sec?: number;
  downstream_rtt_sec?: number;
};

export type ProfileSummary = {
  job_id: string;
  site: string;
  role: string;
  extra: Record<string, unknown>;
  workflows: ProfileSummaryWorkflows;
  system_metrics: ProfileSummarySystemMetrics;
  combined_workflow_metrics?: CombinedWorkflowMetrics | null;
};

type MappingResponse = {
  workflow_dirs?: string[];
  profile_summary?: ProfileSummary;
  error?: string;
};

type JobResultsResponse = {
  job_data?: JobsDataShape;
  function_config?: FunctionConfig;
  error?: string;
};

type FunctionConfigResponse = {
  function_config?: FunctionConfig;
  error?: string;
};

type JobInfoResponse = {
  job?: NVFlareJob | null;
  error?: string;
};

export type TaskflowGenerationState = "idle" | "queued" | "running" | "complete" | "unavailable" | "failed";

export type TaskflowGenerationStatus = {
  state: TaskflowGenerationState;
  progress: number;
  label: string;
  error?: string;
};

export type TaskflowSummary = {
  case_label?: string;
  events?: number;
  lanes?: number;
  spans?: number;
  edges?: number;
  edges_by_id?: number;
  edges_fallback?: number;
  lamport_depth?: number;
  acyclic?: boolean;
  rounds?: number;
  straggler_wait_total_sec?: number;
  straggler_wait_max_sec?: number;
  parties?: string[];
  timeline_note?: string;
  note?: string;
  artifacts?: string[];
};

export type TaskflowRoundMetrics = {
  workflow?: string;
  round?: string | number;
  contributions?: number;
  clients?: string[];
  compute_sec?: { min?: number | null; max?: number | null; mean?: number | null; slowest_client?: string | null };
  wait_sec?: { mean?: number | null; max?: number | null };
  fetch_sec?: { mean?: number | null; max?: number | null };
  send_sec?: { mean?: number | null; max?: number | null };
  submission_spread_sec?: number | null;
  straggler_gap_sec?: number | null;
  straggler_client?: string | null;
  straggler_source?: string | null;
};

export type TaskflowArtifact = {
  filename: string;
  media_type?: string;
  size_bytes?: number;
};

export type TaskflowDiagnosticsResponse = {
  status: TaskflowGenerationStatus;
  summary?: TaskflowSummary | null;
  rounds?: TaskflowRoundMetrics[];
  artifacts?: TaskflowArtifact[];
  error?: string;
};

export type ResultsContextFilter = {
  name?: string | null;
  conditions?: Condition[];
};

export type ResultsContext = {
  job: NVFlareJob;
  project: Project;
  filter: ResultsContextFilter | null;
};

type ResultsContextResponse = {
  status?: string;
  job?: NVFlareJob | null;
  project?: Project | null;
  filter?: ResultsContextFilter | null;
  error?: string;
};

export type WorkflowJobDataResponse = {
  workflows: WorkflowJobData[];
  profileSummary: ProfileSummary | null;
};

export type JobApiSession =
  | UserRole
  | Pick<UserSession, "role" | "client_name">
  | null
  | undefined;

function resolveResultsApiBase(userSession: JobApiSession): string {
  const role = typeof userSession === "string" ? userSession : userSession?.role;

  if (role !== UserRole.CLIENT) {
    return API_BASE;
  }

  const clientName =
    typeof userSession === "string" ? null : userSession?.client_name;

  return getClientApiBase(clientName);
}

async function postJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Request failed ${res.status}: ${text || url}`);
  }
  return res.json() as Promise<T>;
}

function isEmptyFunctionConfig(cfg: FunctionConfig | null | undefined): boolean {
  if (!cfg) return true;
  if (typeof cfg !== "object") return true;
  return Object.keys(cfg).length === 0;
}

function isWorkflowErrorObject(value: unknown): value is WorkflowErrorJson {
  if (!value || typeof value !== "object") return false;

  const obj = value as Record<string, unknown>;

  if (typeof obj.error === "string" && obj.error.trim()) return true;
  if (typeof obj.message === "string" && obj.message.trim()) return true;
  if (typeof obj.traceback === "string" && obj.traceback.trim()) return true;
  if (typeof obj.exception_type === "string" && obj.exception_type.trim()) return true;

  return false;
}

export function getWorkflowErrorFromJobData(jobData: any): WorkflowErrorJson | null {
  if (!jobData || typeof jobData !== "object") return null;

  const explicitRaw =
    jobData.workflow_error ??
    jobData.workflowError ??
    jobData.error_json ??
    jobData.errorJson ??
    jobData.workflow_error_json ??
    jobData.workflowErrorJson ??
    null;

  if (explicitRaw) {
    if (typeof explicitRaw === "string") {
      return { message: explicitRaw };
    }

    if (isWorkflowErrorObject(explicitRaw)) {
      return explicitRaw as WorkflowErrorJson;
    }

    if (typeof explicitRaw === "object" && Object.keys(explicitRaw).length > 0) {
      return explicitRaw as WorkflowErrorJson;
    }
  }

  const candidateSources = [
    jobData.initiator_results,
    jobData.local_results,
    jobData.local?.local_results,
    jobData.initiator_processed_results,
    jobData.local_processed_results,
    jobData.local?.local_processed_results,
  ];

  for (const candidate of candidateSources) {
    if (isWorkflowErrorObject(candidate)) {
      return candidate as WorkflowErrorJson;
    }
  }

  return null;
}

function sortWorkflowIds(workflowIds: string[]): string[] {
  const re = /^workflow_stat_analytics_(\d+)$/;

  return workflowIds
    .map((id, idx) => {
      const m = id.match(re);
      const n = m ? parseInt(m[1], 10) : Number.MAX_SAFE_INTEGER;
      return { id, idx, n };
    })
    .sort((a, b) => (a.n - b.n) || a.idx - b.idx)
    .map((x) => x.id);
}

export async function fetchResultsContext(
  nvflareJobId: string
): Promise<ResultsContext> {
  const data = await postJson<ResultsContextResponse>(
    `${API_BASE}${API_JOB_RESULTS_CONTEXT}`,
    { nvflare_job_id: nvflareJobId }
  );

  if (data.error) {
    throw new Error(data.error);
  }
  if (!data.job) {
    throw new Error("The results context did not include NVFlare job information.");
  }
  if (!data.project) {
    throw new Error("The results context did not include project information.");
  }

  return {
    job: data.job,
    project: data.project,
    filter: data.filter ?? null,
  };
}

export async function fetchNVFlareJobInfo(
  nvflareJobId: string,
  userSession?: JobApiSession
): Promise<NVFlareJob | null> {
  const data = await postJson<JobInfoResponse>(`${API_BASE}${API_JOB_INFO}`, {
    nvflare_job_id: nvflareJobId,
  });

  if (data.error) {
    throw new Error(data.error);
  }

  return data.job ?? null;
}

export async function fetchWorkflowMapping(
  nvflareJobId: string,
  funcName: string,
  userSession?: JobApiSession
): Promise<{ workflowIds: string[]; profileSummary: ProfileSummary | null }> {
  const base = resolveResultsApiBase(userSession);
  const data = await postJson<MappingResponse>(`${base}${API_JOB_RESULTS_MAPPING}`, {
    nvflare_job_id: nvflareJobId,
    function: funcName,
  });

  if (data.error) {
    throw new Error(data.error);
  }

  const dirs = Array.isArray(data.workflow_dirs) ? data.workflow_dirs : [];
  const baseProfile = data.profile_summary ?? null;
  const profileSummary = baseProfile
    ? {
        ...baseProfile,
        combined_workflow_metrics: getCombinedWorkflowMetrics(baseProfile.workflows),
      }
    : null;

  return {
    workflowIds: sortWorkflowIds(dirs),
    profileSummary,
  };
}

async function fetchFunctionConfigForWorkflow(
  nvflareJobId: string,
  funcName: string,
  workflowId: string
): Promise<FunctionConfig | null> {
  const data = await postJson<FunctionConfigResponse>(`${API_BASE}${API_JOB_RESULTS_FUNCTION_CONFIG}`, {
    nvflare_job_id: nvflareJobId,
    function: funcName,
    workflow_id: workflowId,
  });

  if (data.error) {
    throw new Error(data.error);
  }

  const cfg = data.function_config ?? null;
  return isEmptyFunctionConfig(cfg) ? null : cfg;
}

export async function fetchJobResultsForWorkflow(
  nvflareJobId: string,
  funcName: string,
  workflowId: string,
  userSession?: JobApiSession
): Promise<{ jobData: JobsDataShape; functionConfig: FunctionConfig | null; workflowError: WorkflowErrorJson | null }> {
  const base = resolveResultsApiBase(userSession);
  const data = await postJson<JobResultsResponse>(`${base}${API_JOB_RESULTS}`, {
    nvflare_job_id: nvflareJobId,
    function: funcName,
    workflow_id: workflowId,
  });

  if (data.error) {
    throw new Error(data.error);
  }

  const jobData = (data.job_data ?? {}) as JobsDataShape;
  let functionConfig: FunctionConfig | null = data.function_config ?? null;

  if (isEmptyFunctionConfig(functionConfig)) {
    try {
      functionConfig = await fetchFunctionConfigForWorkflow(nvflareJobId, funcName, workflowId);
    } catch {
      functionConfig = null;
    }
  }

  const workflowError = getWorkflowErrorFromJobData(jobData);

  return { jobData, functionConfig, workflowError };
}

export async function startTaskflowDiagnostics(
  nvflareJobId: string
): Promise<TaskflowDiagnosticsResponse> {
  const data = await postJson<TaskflowDiagnosticsResponse>(`${API_BASE}${API_JOB_TASKFLOW_START}`, {
    nvflare_job_id: nvflareJobId,
  });

  if (data.error) {
    throw new Error(data.error);
  }
  return data;
}

export async function fetchTaskflowDiagnostics(
  nvflareJobId: string
): Promise<TaskflowDiagnosticsResponse> {
  const data = await postJson<TaskflowDiagnosticsResponse>(`${API_BASE}${API_JOB_TASKFLOW_STATUS}`, {
    nvflare_job_id: nvflareJobId,
  });

  if (data.error) {
    throw new Error(data.error);
  }
  return data;
}

export function getTaskflowArtifactUrl(
  nvflareJobId: string,
  artifact: string
): string {
  const params = new URLSearchParams({
    nvflare_job_id: nvflareJobId,
    artifact,
  });
  return `${API_BASE}${API_JOB_TASKFLOW_ARTIFACT}?${params.toString()}`;
}

export async function fetchAllWorkflowJobData(
  nvflareJobId: string,
  funcName: string,
  userSession?: JobApiSession
): Promise<WorkflowJobDataResponse> {
  const { workflowIds, profileSummary } = await fetchWorkflowMapping(nvflareJobId, funcName, userSession);
  if (!workflowIds.length) {
    return {
      workflows: [],
      profileSummary,
    };
  }

  const results: WorkflowJobData[] = [];
  for (const wf of workflowIds) {
    const { jobData, functionConfig, workflowError } = await fetchJobResultsForWorkflow(
      nvflareJobId,
      funcName,
      wf,
      userSession
    );
    results.push({
      workflowId: wf,
      functionName: funcName,
      jobData,
      functionConfig,
      workflowError,
    });
  }

  return {
    workflows: results,
    profileSummary,
  };
}

export function getCombinedWorkflowMetrics(
  workflows: ProfileSummaryWorkflows | null | undefined
): CombinedWorkflowMetrics | null {
  if (!workflows) return null;

  const totals: CombinedWorkflowMetrics = {
    server_dispatch_time_sec: 0,
    server_accept_time_sec: 0,
    server_aggregation_time_sec: 0,
    server_compute_time_sec: 0,
    payload_in_bytes: 0,
    payload_out_bytes: 0,
    client_compute_time_sec: 0,
    upstream_rtt_sec: 0,
    downstream_rtt_sec: 0,
  };

  let hasServerMetrics = false;
  let hasClientMetrics = false;

  for (const wf of Object.values(workflows)) {
    if (!wf) continue;
    for (const round of Object.values(wf)) {
      if (!round) continue;

      if (typeof round.server_dispatch_time_sec === "number") {
        totals.server_dispatch_time_sec = (totals.server_dispatch_time_sec || 0) + round.server_dispatch_time_sec;
        hasServerMetrics = true;
      }
      if (typeof round.server_accept_time_sec === "number") {
        totals.server_accept_time_sec = (totals.server_accept_time_sec || 0) + round.server_accept_time_sec;
        hasServerMetrics = true;
      }
      if (typeof round.server_aggregation_time_sec === "number") {
        totals.server_aggregation_time_sec =
          (totals.server_aggregation_time_sec || 0) + round.server_aggregation_time_sec;
        hasServerMetrics = true;
      }
      if (typeof round.server_compute_time_sec === "number") {
        totals.server_compute_time_sec = (totals.server_compute_time_sec || 0) + round.server_compute_time_sec;
        hasServerMetrics = true;
      }
      if (typeof round.payload_in_bytes === "number") {
        totals.payload_in_bytes = (totals.payload_in_bytes || 0) + round.payload_in_bytes;
        hasServerMetrics = true;
      }
      if (typeof round.payload_out_bytes === "number") {
        totals.payload_out_bytes = (totals.payload_out_bytes || 0) + round.payload_out_bytes;
        hasServerMetrics = true;
      }

      if (typeof round.client_compute_time_sec === "number") {
        totals.client_compute_time_sec = (totals.client_compute_time_sec || 0) + round.client_compute_time_sec;
        hasClientMetrics = true;
      }
      if (typeof round.upstream_rtt_sec === "number") {
        totals.upstream_rtt_sec = (totals.upstream_rtt_sec || 0) + round.upstream_rtt_sec;
        hasClientMetrics = true;
      }
      if (typeof round.downstream_rtt_sec === "number") {
        totals.downstream_rtt_sec = (totals.downstream_rtt_sec || 0) + round.downstream_rtt_sec;
        hasClientMetrics = true;
      }
    }
  }

  if (!hasServerMetrics && !hasClientMetrics) {
    return null;
  }

  if (!hasServerMetrics) {
    delete totals.server_dispatch_time_sec;
    delete totals.server_accept_time_sec;
    delete totals.server_aggregation_time_sec;
    delete totals.server_compute_time_sec;
    delete totals.payload_in_bytes;
    delete totals.payload_out_bytes;
  }

  if (!hasClientMetrics) {
    delete totals.client_compute_time_sec;
    delete totals.upstream_rtt_sec;
    delete totals.downstream_rtt_sec;
  }

  return totals;
}

function toFiniteNumber(raw: unknown): number | null {
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  if (typeof raw === "string") {
    const n = Number(raw.trim());
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function truncateToFixed(n: number, digits: number): string {
  const factor = Math.pow(10, digits);
  const truncated = Math.trunc(n * factor) / factor;
  return truncated.toFixed(digits);
}

function negLog10(p: number): number {
  if (p <= 0) return Number.POSITIVE_INFINITY;
  return -Math.log10(p);
}

type FormatPValueOptions = {
  threshold?: number;
  digits?: number;
};

export const CHI2_1DOF_LABEL = "\u03c7\u00b2(1)";

export function formatChi2ForUI(raw: unknown): string | null {
  const chi2 = toFiniteNumber(raw);
  if (chi2 === null || chi2 < 0) return null;
  return chi2.toFixed(1);
}

export function formatPValueForUI(raw: unknown, options?: FormatPValueOptions): string | null {
  const p = toFiniteNumber(raw);
  if (p === null || p < 0 || p > 1) return null;

  const threshold = options?.threshold ?? 0.005;
  const digits = options?.digits ?? 2;

  const op = p < threshold ? "<" : ">";
  const nl10 = negLog10(p);
  const nl10Text = Number.isFinite(nl10) ? truncateToFixed(nl10, digits) : "∞";

  const LOG10_LABEL = "-log\u2081\u2080(p)";

  return `p ${op} ${threshold}, ${LOG10_LABEL} = ${nl10Text}`;
}

export function renderPropertyDisplayLabel(label: string) {
  return label
    .replace("MUT", "Mutations Records")
    .replace("WT", "Wild Type Records")
    .replace("low_score", "Low Risk")
    .replace("high_score", "High Risk");
}

export function renderAgentDisplayLabel(label: string, userRole: UserRole): string {
  if (label === "agent_results") {
    return userRole === UserRole.CLIENT ? "Client" : "Initiator";
  }

  return label
    .replace("initiator_results", "Initiator")
    .replace("local_results", "Client")
    .replace("aggregate_results", "Aggregated")
    .replace("aggregate_processed_results", "Aggregated");
}