import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExclamationCircle } from "react-bootstrap-icons";
import NVFlareClientSnapshot, {
  ClientParticipationSelection,
  ClientStatus,
} from "../../../components/NVFlareClientSnapshot";
import {
  API_BASE,
  API_JOB_STATUS,
  API_SUBMIT_JOB,
  WS_API_BASE,
} from "../../../constants/Constants";
import {
  FunctionConfigs,
  ThresholdConfig,
} from "../../../types/FunctionConfigs";
import SubmissionOverview from "../components/SubmissionOverview";
import {
  buildFiltersPayload,
  FilterCollection,
} from "../utils/FilterPayloadConfigUtils";
import { Project, WorkflowGroupData } from "../../../types/Project";
import AccordionSection from "../../../components/AccordionSection";
import { useUserSession } from "../../../context/UserRoleContext";
import { JobLogData } from "../../../types/JobsDataTypes";

interface JobSubmissionProps {
  project: Project;
  submittedFilter: FilterCollection;
  submittedFilterName: string;
  onBack: () => void;
  viewAnalysisResultsPage: () => void;
  onCancel?: () => void;
  savedJobInfo: JobLogData;
  setSavedJobInfo: (jobData: JobLogData) => void;
  selectedFunctions: FunctionConfigs;
  selectedThresholdConfig: ThresholdConfig | undefined;
  selectedDatasourceGroupId: number | null;
  selectedDatasourceGroupName: string | null;
  workflowGroupData?: WorkflowGroupData;
}

const WEB_SOCKET = true;
const POLL_INTERVAL = 500;
const STATUS_ICON_BASE = "/status-images/icons";
const API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws";

type StatusVisual = {
  key: string;
  label: string;
  filename: string;
};

const PRIMARY_STATUS_FLOW: StatusVisual[] = [
  // { key: "queued", label: "Queued", filename: "queued.png" },
  // { key: "filters-processing", label: "Filters Processing", filename: "filters-processing.png" },

  // { key: "broadcasting-participation-job", label: "Broadcasting Participation Job", filename: "broadcasting-participation-job.png" },
  {
    key: "checking-client-participation",
    label: "Checking Client Participation",
    filename: "checking-client-participation.png",
  },
  // { key: "client-participation-established", label: "Client Participation Established", filename: "client-participation-established.png" },
  // { key: "ssh-connecting", label: "SSH Connecting", filename: "ssh-connecting.png" },
  // { key: "ssh-connected", label: "SSH Connected", filename: "ssh-connected.png" },
  { key: "job-defining", label: "Job Defining", filename: "job-defining.png" },
  {
    key: "job-broadcast",
    label: "Job Broadcast",
    filename: "job-broadcast.png",
  },
  { key: "job-received", label: "Job Received", filename: "job-received.png" },
  // { key: "client-preparing", label: "Client Preparing", filename: "client-preparing.png" },
  // { key: "server-preparing", label: "Server Preparing", filename: "server-preparing.png" },
  {
    key: "interactive-key-generation",
    label: "Interactive Key Generation",
    filename: "interactive-key-generation.png",
  },

  {
    key: "client-compute",
    label: "Client Compute",
    filename: "client-compute.png",
  },
  {
    key: "server-compute",
    label: "Server Compute",
    filename: "server-compute.png",
  },
  // { key: "client-analysis", label: "Client Analysis", filename: "client-analysis.png" },
  // { key: "server-analysis", label: "Server Analysis", filename: "server-analysis.png" },
  {
    key: "collaborative-decryption",
    label: "Collaborative Decryption",
    filename: "collaborative-decryption.png",
  },
  {
    key: "client-results",
    label: "Client Results",
    filename: "client-results.png",
  },
  {
    key: "server-results",
    label: "Server Results",
    filename: "server-results.png",
  },
  { key: "done", label: "Done", filename: "done.png" },
];

const SECONDARY_STATUS_VISUALS: StatusVisual[] = [
  {
    key: "participation-failed",
    label: "Participation Failed",
    filename: "participation-failed.png",
  },
  {
    key: "participation-empty",
    label: "Participation Empty",
    filename: "participation-empty.png",
  },
  {
    key: "analysis-failure",
    label: "Analysis Failure",
    filename: "analysis-failure.png",
  },
  {
    key: "threshold-not-met",
    label: "Threshold Not Met",
    filename: "threshold-not-met.png",
  },
  { key: "failure", label: "Failure", filename: "failure.png" },
  { key: "warning", label: "Warning", filename: "warning.png" },
  { key: "error", label: "Error", filename: "error.png" },
];

function normalizeStatusKey(value: string | null | undefined): string {
  if (!value) return "";

  const raw = value.toString().trim().toLowerCase();

  const normalized = raw
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const aliasMap: Record<string, string> = {
    queued: "queued",
    processing: "processing",

    "checking client participation": "checking-client-participation",
    "broadcasting participation job": "checking-client-participation",
    "monitoring participation responses": "checking-client-participation",
    "client participation established": "client-participation-established",
    "participation failed": "participation-failed",
    "no clients accepted participation": "participation-empty",

    "processing filters": "job-defining",
    "ssh connecting": "job-defining",
    "ssh connected": "job-defining",
    "uploading nvflare job": "job-defining",
    "defining nvflare job": "job-defining",

    "broadcasting nvflare job": "job-broadcast",
    "job broadcast received": "job-received",

    "client compute": "client-compute",
    "server compute": "server-compute",

    "interactive key generation": "interactive-key-generation",
    "executing keygen workflow": "interactive-key-generation",

    // The sample-count pre-pass has no step of its own in the flow; it reports as compute,
    // and the log line carries the workflow name and round.
    "executing threshold comparison workflow": "client-compute",

    "collaborative decryption": "collaborative-decryption",

    "client encryption processing": "client-compute",
    "server encryption processing": "server-compute",

    "client performing analysis": "client-compute",
    "server performing analysis": "server-compute",

    "client processing results": "client-results",
    "server processing results": "server-results",

    "performing analysis": "job-analysis",
    "aggregating job results": "job-results",

    "threshold not met": "threshold-not-met",
    "analysis failure": "analysis-failure",
    failure: "failure",
    warning: "warning",
    error: "error",
    done: "done",

    "parameters loaded": "server-compute",
    "preprocessing (reference)": "server-analysis",
    "preprocessing (encrypted)": "client-compute",
    "encrypting local statistics": "client-compute",
    "post-processing": "client-results",
    "results written to json": "client-results",
    "aggregating results from all sources": "server-results",
    "aggregation complete; running analysis": "server-analysis",
    "writing aggregated results to json": "server-results",
    "threshold limit not met": "threshold-not-met",
    "exception encountered": "error",
    "workflow started": "client-analysis",
    "received encrypted ciphertexts": "server-compute",
    "loading filters / resolving data paths": "server-compute",
    "preprocessing local data": "client-analysis",
    "validating model artifacts": "server-compute",
    "aggregating encrypted results": "server-compute",
    "aggregation complete; sending ciphertext": "server-compute",

    "receiving partial decryptions": "collaborative-decryption",
    "decrypting aggregated results": "collaborative-decryption",

    "risk scores ready; sending to persistor": "server-results",
    "validating workflow arguments": "server-compute",
    "loading schema metadata": "server-compute",
    "validating openfhe parameters": "server-compute",
    "saved risk scores": "server-results",
  };

  return aliasMap[normalized] || normalized.replace(/\s+/g, "-");
}

function getFixedConfigByFunction(
  project: Project,
): Record<string, Record<string, any>> {
  const out: Record<string, Record<string, any>> = {};
  const fns = (project as any)?.functions;

  if (!Array.isArray(fns)) return out;

  for (const f of fns) {
    const fnName = typeof f?.function === "string" ? f.function.trim() : "";
    if (!fnName) continue;

    const fixed = f?.custom_configuration_fixed;
    if (fixed && typeof fixed === "object" && !Array.isArray(fixed)) {
      out[fnName.toUpperCase()] = { ...(fixed as Record<string, any>) };
    }
  }

  return out;
}

function mergeFixedIntoSelectedFunctions(
  selected: FunctionConfigs,
  fixedByFnUpper: Record<string, Record<string, any>>,
): FunctionConfigs {
  const out: any = {};

  for (const [fnNameRaw, cfgVal] of Object.entries(selected || {})) {
    const fnKey = String(fnNameRaw || "");
    const fixed = fixedByFnUpper[fnKey.toUpperCase()] || {};

    if (Array.isArray(cfgVal)) {
      out[fnKey] = cfgVal.map((cfg: any) => {
        const base =
          cfg && typeof cfg === "object" && !Array.isArray(cfg) ? cfg : {};
        return { ...base, ...fixed };
      });
      continue;
    }

    if (cfgVal && typeof cfgVal === "object" && !Array.isArray(cfgVal)) {
      out[fnKey] = [{ ...(cfgVal as any), ...fixed }];
      continue;
    }

    out[fnKey] = cfgVal;
  }

  return out as FunctionConfigs;
}

function detectSecondaryStatuses(
  jobStatus: string | null,
  jobLog: string[],
): string[] {
  const detected = new Set<string>();
  const normalizedStatus = normalizeStatusKey(jobStatus);

  if (SECONDARY_STATUS_VISUALS.some((item) => item.key === normalizedStatus)) {
    detected.add(normalizedStatus);
  }

  for (const line of jobLog) {
    const normalizedLine = normalizeStatusKey(line);

    for (const item of SECONDARY_STATUS_VISUALS) {
      if (
        normalizedLine === item.key ||
        normalizedLine.includes(item.key) ||
        normalizedLine.includes(item.label.toLowerCase().replace(/\s+/g, "-"))
      ) {
        detected.add(item.key);
      }
    }

    const lowered = line.toLowerCase();
    if (lowered.includes("exception encountered")) detected.add("error");
    if (lowered.includes("threshold limit not met"))
      detected.add("threshold-not-met");
    if (lowered.includes("participation failed"))
      detected.add("participation-failed");
    if (lowered.includes("no clients accepted participation"))
      detected.add("participation-empty");
    if (lowered.includes("analysis failure")) detected.add("analysis-failure");
    if (lowered.includes(" warning")) detected.add("warning");
    if (lowered.includes(" failure")) detected.add("failure");
    if (lowered.includes(" error")) detected.add("error");
  }

  return SECONDARY_STATUS_VISUALS.map((item) => item.key).filter((key) =>
    detected.has(key),
  );
}

function isTerminalStatus(status: string | null | undefined): boolean {
  const upper = (status || "").toUpperCase();
  return upper === "DONE" || upper === "FAILURE";
}

function buildJobStatusWebSocketUrl(jobId: string): string {
  const localBase = `${API_BASE || ""}`.replace(/\/$/, "");
  const wsBase = `${WS_API_BASE || ""}`.replace(/\/$/, "");

  const isLocal =
    localBase.includes("localhost") ||
    localBase.includes("127.0.0.1") ||
    wsBase.includes("localhost") ||
    wsBase.includes("127.0.0.1");

  if (isLocal) {
    const path = `${localBase}${API_JOB_STATUS_WEBSOCKET}/local/${encodeURIComponent(jobId)}`;

    if (path.startsWith("https://")) {
      return path.replace(/^https:\/\//, "wss://");
    }

    if (path.startsWith("http://")) {
      return path.replace(/^http:\/\//, "ws://");
    }

    const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    return `${protocol}${window.location.host}${normalizedPath}`;
  }

  return `${wsBase}?job_id=${encodeURIComponent(jobId)}`;
}

function JobStatusFlow({
  jobStatus,
  persistentSecondaryKeys,
}: {
  jobStatus: string | null;
  persistentSecondaryKeys: string[];
}) {
  const normalizedStatus = normalizeStatusKey(jobStatus);
  const activePrimaryIndex = PRIMARY_STATUS_FLOW.findIndex(
    (item) => item.key === normalizedStatus,
  );

  const visibleSecondaryVisuals = SECONDARY_STATUS_VISUALS.filter((item) =>
    persistentSecondaryKeys.includes(item.key),
  );

  return (
    <div
      className="job-submission-page-block-01"
    >
      <div
        className="job-submission-page-block-02"
      >
        {PRIMARY_STATUS_FLOW.map((item, index) => {
          const isActive = normalizedStatus === item.key;
          const isCompleted =
            activePrimaryIndex >= 0 && index < activePrimaryIndex;
          const opacity = isActive ? 1 : 0.3;

          return (
            <React.Fragment key={item.key}>
              <div
                style={{
                  minWidth: "58px",
                  maxWidth: "58px",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  textAlign: "center",
                  opacity,
                  transition: "opacity 0.2s ease",
                }}
              >
                <img
                  src={`${STATUS_ICON_BASE}/${item.filename}`}
                  alt={item.label}
                  title={item.label}
                  className="job-submission-page-img"
                />
              </div>

              {index < PRIMARY_STATUS_FLOW.length - 1 && (
                <div
                  className="job-submission-page-block-03"
                >
                  <div
                    className="job-submission-page-block-04" style={{ backgroundColor: isCompleted ? "#d9e2ec" : "#d9e2ec" }}
                  />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {visibleSecondaryVisuals.length > 0 && (
        <div
          className="job-submission-page-block-05"
        >
          {visibleSecondaryVisuals.map((item) => (
            <div
              key={item.key}
              className="job-submission-page-block-06"
            >
              <img
                src={`${STATUS_ICON_BASE}/${item.filename}`}
                alt={item.label}
                title={item.label}
                className="job-submission-page-img-1a9d6"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const JobSubmissionPage: React.FC<JobSubmissionProps> = ({
  project,
  submittedFilter,
  submittedFilterName,
  onBack,
  viewAnalysisResultsPage,
  savedJobInfo,
  setSavedJobInfo,
  selectedFunctions,
  selectedThresholdConfig,
  selectedDatasourceGroupId,
  selectedDatasourceGroupName,
  workflowGroupData,
}) => {
  const { username } = useUserSession();

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectionNotice, setConnectionNotice] = useState<string | null>(null);
  const consecutivePollingFailuresRef = useRef(0);
  const [, setResult] = useState<any>(null);
  const [jobStatus, setJobStatus] = useState<string | null>("QUEUED");
  const [jobLog, setJobLog] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [persistentSecondaryKeys, setPersistentSecondaryKeys] = useState<
    string[]
  >([]);

  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [snapshotClients, setSnapshotClients] = useState<ClientStatus[]>([]);
  const [clientParticipationSelection, setClientParticipationSelection] =
    useState<ClientParticipationSelection>({
      non_contributing_clients: [],
      exclude_analyzing_clients: [],
    });

  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const wsReconnectRef = useRef<NodeJS.Timeout | null>(null);
  const intentionallyClosingWsRef = useRef(false);
  const websocketConnectedRef = useRef(false);
  const websocketStreamingRef = useRef(false);
  const latestJobStatusRef = useRef<string | null>("QUEUED");

  const logTextAreaRef = useRef<HTMLTextAreaElement | null>(null);
  const shouldAutoScrollRef = useRef(true);

  const filtersPayload = useMemo(
    () =>
      buildFiltersPayload(
        submittedFilterName || "Filter Set",
        submittedFilter,
        project,
      ),
    [submittedFilterName, submittedFilter, project],
  );

  const fixedByFnUpper = useMemo(
    () => getFixedConfigByFunction(project),
    [project],
  );

  const resolvedFunctionsMap = useMemo(
    () => mergeFixedIntoSelectedFunctions(selectedFunctions, fixedByFnUpper),
    [selectedFunctions, fixedByFnUpper],
  );

  const scrollLogToBottom = () => {
    const el = logTextAreaRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  };

  const handleLogTextAreaRef = useCallback(
    (element: HTMLTextAreaElement | null) => {
      const becameVisible = element !== null && logTextAreaRef.current === null;
      logTextAreaRef.current = element;

      if (!becameVisible) return;

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({
            top: document.documentElement.scrollHeight,
            behavior: "smooth",
          });
        });
      });
    },
    [],
  );

  const handleLogScroll = () => {
    const el = logTextAreaRef.current;
    if (!el) return;
    const thresholdPx = 8;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom <= thresholdPx;
  };

  const applyJobStatusUpdate = (
    id: string,
    nextStatus: string | null,
    nextLog: string[],
    statusData: any,
    fallbackFunctions: any[] = [],
  ) => {
    latestJobStatusRef.current = nextStatus;
    setJobStatus(nextStatus);
    setJobLog(nextLog);
    setPersistentSecondaryKeys((prev) => {
      const nextDetected = detectSecondaryStatuses(nextStatus, nextLog);
      const merged = new Set([...prev, ...nextDetected]);
      return SECONDARY_STATUS_VISUALS.map((item) => item.key).filter((key) =>
        merged.has(key),
      );
    });

    setSavedJobInfo({
      jobId: id,
      jobStatus: nextStatus || "",
      jobLog: nextLog,
      referencedBy: statusData?.referenced_by || undefined,
      run_duration: statusData?.run_duration || undefined,
      functions: statusData?.functions || fallbackFunctions,
    });
  };

  const clearPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const clearWebSocketReconnect = () => {
    if (wsReconnectRef.current) {
      clearTimeout(wsReconnectRef.current);
      wsReconnectRef.current = null;
    }
  };

  const closeWebSocket = () => {
    intentionallyClosingWsRef.current = true;

    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch { }
      wsRef.current = null;
    }

    websocketConnectedRef.current = false;
    websocketStreamingRef.current = false;
  };

  const stopTracking = () => {
    clearPolling();
    clearWebSocketReconnect();
    closeWebSocket();
    consecutivePollingFailuresRef.current = 0;
  };

  const startPollingLoop = (id: string) => {
    clearPolling();

    pollRef.current = setInterval(async () => {
      if (websocketStreamingRef.current) {
        clearPolling();
        return;
      }

      try {
        const pw = process.env.REACT_APP_MYSQL_SECRET_PW ?? "";
        const res = await fetch(`${API_BASE}${API_JOB_STATUS}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: id, $pw: pw }),
        });

        if (!res.ok) {
          const retryable =
            res.status === 408 ||
            res.status === 429 ||
            res.status >= 500;

          if (retryable) {
            consecutivePollingFailuresRef.current += 1;

            if (consecutivePollingFailuresRef.current >= 3) {
              setConnectionNotice(
                "Connection temporarily interrupted. Reconnecting...",
              );
            }

            return;
          }

          stopTracking();
          setSubmitting(false);
          consecutivePollingFailuresRef.current = 0;
          setConnectionNotice(null);
          setError(`Unable to retrieve job status (Status API ${res.status}).`);
          return;
        }

        const statusData = await res.json();
        const nextStatus = statusData.status || null;
        const nextLog = statusData.log || [];

        consecutivePollingFailuresRef.current = 0;
        setConnectionNotice(null);
        applyJobStatusUpdate(id, nextStatus, nextLog, statusData);

        if (isTerminalStatus(nextStatus)) {
          stopTracking();
          setSubmitting(false);
        }
      } catch {
        if (!isTerminalStatus(latestJobStatusRef.current)) {
          consecutivePollingFailuresRef.current += 1;

          if (consecutivePollingFailuresRef.current >= 3) {
            setConnectionNotice(
              "Connection temporarily interrupted. Reconnecting...",
            );
          }
        }
      }
    }, POLL_INTERVAL);
  };

  const scheduleWebSocketReconnect = (id: string) => {
    if (
      !WEB_SOCKET ||
      isTerminalStatus(latestJobStatusRef.current) ||
      wsReconnectRef.current
    ) {
      return;
    }

    wsReconnectRef.current = setTimeout(() => {
      wsReconnectRef.current = null;

      if (!isTerminalStatus(latestJobStatusRef.current)) {
        startWebSocketStream(id);
      }
    }, 2000);
  };

  const startWebSocketStream = (id: string) => {
    if (!WEB_SOCKET) return;

    clearWebSocketReconnect();
    intentionallyClosingWsRef.current = false;
    websocketConnectedRef.current = false;
    websocketStreamingRef.current = false;

    const socketUrl = buildJobStatusWebSocketUrl(id);

    const ws = new WebSocket(socketUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      websocketConnectedRef.current = true;
    };

    ws.onmessage = (event) => {
      try {

        const statusData = JSON.parse(event.data);

        if (
          statusData?.requires_ack &&
          statusData?.message_id &&
          ws.readyState === WebSocket.OPEN
        ) {
          const ackPayload = {
            type: "ack",
            message_id: statusData.message_id,
          };
          ws.send(JSON.stringify(ackPayload));
        }

        if (statusData?.type === "heartbeat") {
          return;
        }

        if (statusData?.type === "job_status_error") {

          websocketStreamingRef.current = false;

          if (!isTerminalStatus(latestJobStatusRef.current)) {
            startPollingLoop(id);
            scheduleWebSocketReconnect(id);
          }

          closeWebSocket();
          return;
        }

        if (statusData?.type !== "job_status") {
          return;
        }

        const nextStatus = statusData.status || null;
        const nextLog = statusData.log || [];

        websocketStreamingRef.current = true;
        clearPolling();
        setConnectionNotice(null);
        applyJobStatusUpdate(id, nextStatus, nextLog, statusData);

        if (isTerminalStatus(nextStatus)) {
          setSubmitting(false);
          stopTracking();
        }
      } catch {
        if (!isTerminalStatus(latestJobStatusRef.current)) {
          startPollingLoop(id);
          scheduleWebSocketReconnect(id);
        }

        closeWebSocket();
      }
    };

    ws.onerror = () => {

      if (intentionallyClosingWsRef.current) return;

      if (!isTerminalStatus(latestJobStatusRef.current)) {
        startPollingLoop(id);
        scheduleWebSocketReconnect(id);
      }

      closeWebSocket();
    };

    ws.onclose = () => {

      if (wsRef.current === ws) {
        wsRef.current = null;
      }

      const wasIntentional = intentionallyClosingWsRef.current;

      websocketConnectedRef.current = false;
      websocketStreamingRef.current = false;

      if (wasIntentional) {
        return;
      }

      if (!isTerminalStatus(latestJobStatusRef.current)) {
        startPollingLoop(id);
        scheduleWebSocketReconnect(id);
      }
    };
  };

  const startTracking = (id: string) => {
    stopTracking();
    websocketConnectedRef.current = false;
    websocketStreamingRef.current = false;
    startPollingLoop(id);
    startWebSocketStream(id);
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    setConnectionNotice(null);
    setPersistentSecondaryKeys([]);

    const payload: any = {
      project_id: project.id,
      filters: filtersPayload,
      functions_map: resolvedFunctionsMap,
      submitter: username,
      non_contributing_clients:
        clientParticipationSelection.non_contributing_clients,
      exclude_analyzing_clients:
        clientParticipationSelection.exclude_analyzing_clients,
    };

    if (selectedDatasourceGroupId !== null) {
      payload.datasource_group = selectedDatasourceGroupId;
    }

    if (workflowGroupData && Object.keys(workflowGroupData).length > 0) {
      payload.workflow_group_data = workflowGroupData;
    }

    if (
      selectedThresholdConfig &&
      selectedThresholdConfig.enabled &&
      selectedThresholdConfig.thresholdMethod &&
      selectedThresholdConfig.threshold != null
    ) {
      payload.threshold_config = {
        method: selectedThresholdConfig.thresholdMethod,
        threshold: selectedThresholdConfig.threshold,
      };
    }

    try {
      const res = await fetch(`${API_BASE}${API_SUBMIT_JOB}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setResult(data);
      if (data?.job_id) {
        setJobId(data.job_id);
        startTracking(data.job_id);
      }
    } catch (e: any) {
      setError(
        (e?.message ? e.message + ": " : "") + (String(e) || "Submit failed"),
      );
      setSubmitting(false);
    }
  };

  useEffect(() => {
    if (savedJobInfo?.jobId) {
      const restoredStatus = savedJobInfo.jobStatus || null;
      const restoredLog = savedJobInfo.jobLog || [];

      setJobId(savedJobInfo.jobId);
      latestJobStatusRef.current = restoredStatus;
      setJobStatus(restoredStatus);
      setJobLog(restoredLog);
      setPersistentSecondaryKeys(
        detectSecondaryStatuses(restoredStatus, restoredLog),
      );

      if (
        savedJobInfo.jobStatus &&
        savedJobInfo.jobStatus.toUpperCase() !== "DONE" &&
        savedJobInfo.jobStatus.toUpperCase() !== "FAILURE"
      ) {
        startTracking(savedJobInfo.jobId);
      }
    }

    return () => {
      stopTracking();
    };
    // Restore the saved submission snapshot once when this page mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    latestJobStatusRef.current = jobStatus;
  }, [jobStatus]);

  useEffect(() => {
    if (!jobId) return;
    if (!shouldAutoScrollRef.current) return;
    requestAnimationFrame(() => scrollLogToBottom());
  }, [jobId, jobLog]);

  const isFailure = (jobStatus || "").toUpperCase().includes("FAILURE");
  const isDone = (jobStatus || "").toUpperCase() === "DONE";
  const hasSelectedFunctions =
    Object.keys(resolvedFunctionsMap || {}).length > 0;
  const serverClient = snapshotClients.find(
    (c) => c.isServer || c.name.trim().toLowerCase() === "server",
  );
  const serverOnline = serverClient ? serverClient.connected : true;
  const jobEligibleClients = snapshotClients.filter(
    (c) => !c.isServer && c.name.trim().toLowerCase() !== "server",
  );
  const registeredJobEligibleClients = jobEligibleClients.filter(
    (c) => c.registered !== false,
  );
  const connectedRegisteredJobEligibleClients = registeredJobEligibleClients.filter(
    (c) => c.connected,
  );

  const canSubmit =
    !submitting &&
    !isDone &&
    !isFailure &&
    hasSelectedFunctions &&
    serverOnline &&
    registeredJobEligibleClients.length > 0 &&
    connectedRegisteredJobEligibleClients.length > 0;

  return (
    <>
      <NVFlareClientSnapshot
        projectId={project.id}
        filtersPayload={filtersPayload}
        functionsMap={resolvedFunctionsMap}
        thresholdConfig={selectedThresholdConfig}
        heartbeatWindowMs={60000}
        onState={({ loading, clients }) => {
          setSnapshotLoading(loading);
          setSnapshotClients(clients);
        }}
        onParticipationSelectionChange={setClientParticipationSelection}
        onError={(msg) => setError(msg)}
        canSubmit={canSubmit}
      />

      <div className="page-container">
        <div
          className="child-container job-submission-page-block-07"
          style={{ marginBottom: jobId || error ? "0" : "0.75rem" }}
        >
          <SubmissionOverview
            submittedFilterName={submittedFilterName}
            submittedFilter={submittedFilter}
            selectedFunctions={resolvedFunctionsMap}
            hasSelectedFunctions={hasSelectedFunctions}
            selectedThresholdConfig={selectedThresholdConfig}
            selectedDatasourceGroupName={selectedDatasourceGroupName}
            workflowGroupData={workflowGroupData}
            project={project}
          />
        </div>
      </div>

      {jobId && (
        <div className="page-container">
          <div className="child-container">
            <div className="job-submission-page-block-08">
              <AccordionSection title={`Status: ${jobStatus}`} defaultExpanded>
                <JobStatusFlow
                  jobStatus={jobStatus}
                  persistentSecondaryKeys={persistentSecondaryKeys}
                />
                {jobLog.length > 0 && (
                  <textarea
                    ref={handleLogTextAreaRef}
                    onScroll={handleLogScroll}
                    readOnly
                    value={jobLog.join("\n")}
                    className="job-submission-page-log-text-area"
                  />
                )}
              </AccordionSection>
            </div>
          </div>
        </div>
      )}

      {connectionNotice && (
        <div className="page-container">
          <div
            className="job-submission-page-connection-notice"
            role="status"
            aria-live="polite"
          >
            <ExclamationCircle
              className="job-submission-page-connection-notice-icon"
              aria-hidden="true"
            />
            <span>{connectionNotice}</span>
          </div>
        </div>
      )}

      {error && (
        <div className="page-container">
          <div
            className="job-submission-page-block-09"
          >
            {error}
          </div>
        </div>
      )}

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>
            Back to Analysis Function Selection
          </button>

          {snapshotLoading && <button className="wizard-next-button" disabled>Loading clients...</button>}

          {!snapshotLoading && !isDone && !isFailure && (
            <button className="wizard-next-button" onClick={handleSubmit} disabled={!canSubmit}>
              {submitting
                ? "Submitting..."
                : !hasSelectedFunctions
                  ? "Select at least one function"
                  : registeredJobEligibleClients.length === 0
                    ? "No Registered Clients"
                    : !serverOnline
                      ? "Server is Offline"
                      : connectedRegisteredJobEligibleClients.length === 0
                        ? "No Site Online"
                        : "Submit for Analysis"}
            </button>
          )}

          {isDone && (
            <button onClick={viewAnalysisResultsPage}>
              View Analysis Results
            </button>
          )}

          {isFailure && <button disabled>Failure Occurred</button>}
        </div>
      </div>
    </>
  );
};

export default JobSubmissionPage;
