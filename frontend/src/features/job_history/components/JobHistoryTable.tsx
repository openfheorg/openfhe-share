import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimateIn } from "../../../components/AnimateIn";
import CompactBanner from "../../../components/CompactBanner";
import RefreshablePanel from "../../../components/RefreshablePanel";
import { API_BASE, API_JOB_HISTORY, API_JOB_STATUS, WS_API_BASE } from "../../../constants/Constants";
import { UserRole, useUserRole } from "../../../context/UserRoleContext";
import { Project } from "../../../types/Project";
import { JobLogEntry, NVFlareJob } from "../../../types/JobsDataTypes";
import EncryptionParamsSection from "./EncryptionParamsSection";
import FilterSummarySection from "./FilterSummarySection";
import FunctionConfigSection from "./FunctionConfigSection";
import { formatFunctionName } from "../../../components/FunctionSelector";
import LogOutputSection from "./LogOutputSection";
import ThresholdConfigSection from "./ThresholdConfigSection";
import DatasourceSelectionSection from "./DatasourceSelectionSection";
import WorkflowGroupSelectionSection from "./WorkflowGroupSelectionSection";
import ParticipationSection from "./ParticipationSection";
import { Gear } from "react-bootstrap-icons";

const SUCCESS_STATUS = "FINISHED:COMPLETED";
// A run that finished without producing every requested computation. Its partial results are
// still worth opening, so it must not be treated as a plain failure.
const PARTIAL_STATUS = "FINISHED:PARTIAL";
const PAGE_SIZE = 10;
const DEFAULT_SELECTED_COLUMNS = ["cancer_type", "model_type", "time_grid_max"];
const WEB_SOCKET = true;
const POLL_INTERVAL = 500;
const API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws";

interface NVFlareJobHistoryPageProps {
    project: Project;
    onStartNewAnalysis?: () => void;
    onViewResults?: (job: NVFlareJob) => void;
    compact?: boolean;
    extraColumnKeys?: string[];
    onExtraColumnKeysChange?: (keys: string[]) => void;
    onOpenColumnConfig?: () => void;
    onAvailableExtraColumnKeysChange?: (keys: string[]) => void;
}

type FilterMode = "ANY" | "ONLY";
type DateMode = "ON" | "AFTER" | "BEFORE";

function toYMD(date: Date): string {
    const y = date.getUTCFullYear();
    const m = String(date.getUTCMonth() + 1).padStart(2, "0");
    const d = String(date.getUTCDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function normalizeConfigKey(key: string): string {
    return String(key || "").trim().toLowerCase();
}

function normalizeConfigKeys(keys: string[]): string[] {
    return Array.from(
        new Set(
            (keys || [])
                .map((key) => normalizeConfigKey(key))
                .filter(Boolean)
        )
    );
}

function getFixedKeysByFnUpper(project: Project): Record<string, Set<string>> {
    const out: Record<string, Set<string>> = {};
    const fns = (project as any)?.functions;
    if (!Array.isArray(fns)) return out;

    for (const f of fns) {
        const fnName = typeof f?.function === "string" ? f.function.trim() : "";
        if (!fnName) continue;

        const fixed = f?.custom_configuration_fixed;
        if (!fixed || typeof fixed !== "object" || Array.isArray(fixed)) continue;

        const keys = Object.keys(fixed as Record<string, any>).map((k) => normalizeConfigKey(String(k)));
        out[fnName.toUpperCase()] = new Set(keys);
    }

    return out;
}

function isTerminalStatus(status: string | null | undefined): boolean {
    const upper = String(status || "").trim().toUpperCase();
    if (!upper) return false;

    return upper === "DONE" || upper === "FAILURE";
}

function shouldLiveTrackJob(status: string | null | undefined): boolean {
    const upper = String(status || "").trim().toUpperCase();
    if (!upper) return false;

    return !(
        upper === SUCCESS_STATUS ||
        upper === PARTIAL_STATUS ||
        upper.includes("COMPLETED") ||
        upper.includes("FAILED") ||
        upper.includes("CANCELLED") ||
        upper.includes("ABORTED")
    );
}

/** Results are viewable for a fully completed run and for a partial one. */
function canViewResults(status: string | null | undefined): boolean {
    const upper = String(status || "").trim().toUpperCase();
    return upper === SUCCESS_STATUS || upper === PARTIAL_STATUS;
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

function mapLogLinesToEntries(lines: string[]): JobLogEntry[] {
    return (lines || []).map((line: string) => {
        const match = String(line || "").match(/^\[(.*?)\]\s*(.*)$/);
        return match
            ? { timestamp: match[1], message: match[2] }
            : { timestamp: "", message: String(line || "") };
    });
}

const JobHistoryTable: React.FC<NVFlareJobHistoryPageProps> = ({
    project,
    onStartNewAnalysis = () => { },
    onViewResults = () => { },
    compact = false,
    extraColumnKeys: controlledExtraColumnKeys,
    onExtraColumnKeysChange,
    onOpenColumnConfig,
    onAvailableExtraColumnKeysChange
}) => {
    const didApplyDefaultColumnsRef = useRef(false);

    const jobRunnerRole: boolean = useUserRole() === UserRole.INITIATOR ? true : false;

    const [jobs, setJobs] = useState<NVFlareJob[]>([]);
    const [expandedJobId, setExpandedJobId] = useState<string | null>(null);

    const [openFilterSummaryFor, setOpenFilterSummaryFor] = useState<string | null>(null);
    const [openConfigsFor, setOpenConfigsFor] = useState<string | null>(null);
    const [openLogsFor, setOpenLogsFor] = useState<string | null>(null);
    const [openThresholdFor, setOpenThresholdFor] = useState<string | null>(null);
    const [openDatasourceFor, setOpenDatasourceFor] = useState<string | null>(null);
    const [openWorkflowGroupsFor, setOpenWorkflowGroupsFor] = useState<string | null>(null);
    const [openParticipationFor, setOpenParticipationFor] = useState<string | null>(null);
    const [openAuditFor, setOpenAuditFor] = useState<string | null>(null);

    const [jobLogs, setJobLogs] = useState<Record<string, JobLogEntry[]>>({});
    const [loading, setLoading] = useState(false);
    const [refreshingJobId, setRefreshingJobId] = useState<string | null>(null);
    const [page, setPage] = useState(1);
    const [filterText, setFilterText] = useState("");

    const [supportedFunctions, setSupportedFunctions] = useState<string[]>([]);
    const [selectedFunctions, setSelectedFunctions] = useState<Record<string, boolean>>({});
    const [filterMode, setFilterMode] = useState<FilterMode>("ANY");
    const [initializing, setInitializing] = useState<boolean>(true);

    const [createDateMode, setCreateDateMode] = useState<DateMode>("AFTER");
    const [createDate, setCreateDate] = useState<string>(() => {
        const d = new Date();
        d.setUTCDate(d.getUTCDate() - 30);
        return toYMD(d);
    });

    const [openQueryFilters, setOpenQueryFilters] = useState<boolean>(false);

    const fixedKeysByFnUpper = useMemo(() => getFixedKeysByFnUpper(project), [project]);

    const [uncontrolledExtraColumnKeys, setUncontrolledExtraColumnKeys] = useState<string[]>([]);

    const extraColumnKeys = useMemo(
        () => normalizeConfigKeys(controlledExtraColumnKeys ?? uncontrolledExtraColumnKeys).slice(0, 3),
        [controlledExtraColumnKeys, uncontrolledExtraColumnKeys]
    );

    const setExtraColumnKeys = useCallback((keys: string[]) => {
        const cleaned = normalizeConfigKeys(keys || []).slice(0, 3);
        if (onExtraColumnKeysChange) onExtraColumnKeysChange(cleaned);
        if (controlledExtraColumnKeys == null) setUncontrolledExtraColumnKeys(cleaned);
    }, [controlledExtraColumnKeys, onExtraColumnKeysChange]);

    const pollRef = useRef<NodeJS.Timeout | null>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const intentionallyClosingWsRef = useRef(false);
    const websocketConnectedRef = useRef(false);
    const websocketStreamingRef = useRef(false);
    const latestTrackedStatusRef = useRef<string | null>(null);
    const trackedJobKeyRef = useRef<string | null>(null);

    const formatThresholdMethod = (method: string): string => {
        const m = method.toUpperCase();
        if (m === "PROTECTED") return "Protected";
        if (m === "EXPOSED") return "Exposed";
        return method;
    };

    const listFunctions = (job: NVFlareJob): string[] => {
        const fm = job.functions_map || {};
        const fnNames = Object.keys(fm);

        if (fnNames.length > 0) {
            return fnNames.map((fn) => {
                const rawCfg = fm[fn];
                let count = 0;

                if (Array.isArray(rawCfg)) {
                    count = rawCfg.length;
                } else if (rawCfg && typeof rawCfg === "object") {
                    count = 1;
                }

                return count > 1 ? `${fn} (${count})` : fn;
            });
        }

        if (job.functions && job.functions.length) return job.functions;
        return [];
    };

    const parseCsvList = (value: unknown): string[] => {
        if (Array.isArray(value)) {
            return value
                .map((item) => String(item || "").trim())
                .filter(Boolean);
        }

        if (typeof value !== "string") return [];

        return value
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
    };

    const hasParticipationSettings = (job: NVFlareJob): boolean => {
        const nonContributingClients = parseCsvList((job as any).non_contributing_clients);
        const excludeAnalyzingClients = parseCsvList((job as any).exclude_analyzing_clients);
        return nonContributingClients.length > 0 || excludeAnalyzingClients.length > 0;
    };
    const hasThresholdSettings = (job: NVFlareJob): boolean => {
        return !!job.threshold || ((job as any).threshold_config_id !== null && (job as any).threshold_config_id !== undefined);
    };

    const hasEncryptionParams = (job: NVFlareJob): boolean => {
        return !!(job as any).crypto_audit_record;
    };


    const buildJobFunctionConfigSearchText = useCallback((job: NVFlareJob): string => {
        const fm = job.functions_map || {};
        const parts: string[] = [];

        for (const fn of Object.keys(fm)) {
            const rawCfg = fm[fn];
            const upper = String(fn || "").trim().toUpperCase();
            const fixed = fixedKeysByFnUpper[upper];

            const addCfg = (cfg: any) => {
                if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) return;

                for (const k of Object.keys(cfg)) {
                    const key = String(k || "").trim();
                    const normalizedKey = normalizeConfigKey(key);
                    if (!normalizedKey) continue;
                    if (fixed && fixed.has(normalizedKey)) continue;

                    const v = (cfg as any)[k];
                    if (v == null) continue;

                    if (typeof v === "string") {
                        const s = v.trim();
                        if (!s) continue;
                        parts.push(`${normalizedKey}:${s}`);
                        continue;
                    }

                    if (typeof v === "number" || typeof v === "boolean") {
                        parts.push(`${normalizedKey}:${String(v)}`);
                        continue;
                    }

                    try {
                        const js = JSON.stringify(v);
                        if (js && js !== "null") parts.push(`${normalizedKey}:${js}`);
                    } catch {
                        parts.push(`${normalizedKey}:${String(v)}`);
                    }
                }
            };

            if (Array.isArray(rawCfg)) {
                rawCfg.forEach(addCfg);
            } else {
                addCfg(rawCfg);
            }
        }

        return parts.join(" | ");
    }, [fixedKeysByFnUpper]);

    const jobFunctionConfigSearchByKey = useMemo(() => {
        const out: Record<string, string> = {};
        for (const job of jobs) {
            const jobKey = job.job_runner_id || job.id.toString();
            out[jobKey] = buildJobFunctionConfigSearchText(job);
        }
        return out;
    }, [jobs, buildJobFunctionConfigSearchText]);

    const filteredJobs = useMemo(() => {
        const q = filterText.trim().toLowerCase();
        if (!q) return jobs;

        return jobs.filter((job) => {
            const jobKey = job.job_runner_id || job.id.toString();
            const fn = listFunctions(job).join(" ");
            const cfgSearch = jobFunctionConfigSearchByKey[jobKey] || "";

            const haystack = [
                String(job.id || ""),
                job.nvflare_assigned_id || "",
                job.status || "",
                job.job_runner_id || "",
                job.job_path || "",
                job.output_path || "",
                job.create_date || "",
                job.update_date || "",
                job.completed_date || "",
                fn,
                cfgSearch
            ]
                .join(" | ")
                .toLowerCase();

            return haystack.includes(q);
        });
    }, [jobs, filterText, jobFunctionConfigSearchByKey]);

    useEffect(() => {
        const tp = Math.max(1, Math.ceil(filteredJobs.length / PAGE_SIZE));
        if (page > tp) setPage(tp);
    }, [filteredJobs, page]);

    const clearPolling = useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    const closeWebSocket = useCallback(() => {
        intentionallyClosingWsRef.current = true;

        if (wsRef.current) {
            try {
                wsRef.current.close();
            } catch (err) {
            }
            wsRef.current = null;
        }

        websocketConnectedRef.current = false;
        websocketStreamingRef.current = false;
    }, []);

    const stopLiveTracking = useCallback(() => {
        clearPolling();
        closeWebSocket();
        trackedJobKeyRef.current = null;
        latestTrackedStatusRef.current = null;
    }, [clearPolling, closeWebSocket]);

    useEffect(() => {
        setExpandedJobId(null);
        setOpenFilterSummaryFor(null);
        setOpenConfigsFor(null);
        setOpenLogsFor(null);
        setOpenThresholdFor(null);
        setOpenDatasourceFor(null);
        setOpenWorkflowGroupsFor(null);
        setOpenParticipationFor(null);
        setOpenAuditFor(null);
        stopLiveTracking();
    }, [page, stopLiveTracking]);

    useEffect(() => {
        setPage(1);
    }, [filterText]);

    const currentFunctionNames = useMemo(
        () => Object.keys(selectedFunctions).filter((k) => selectedFunctions[k]),
        [selectedFunctions]
    );

    const fetchJobs = async (override?: {
        function_names?: string[];
        filter_mode?: FilterMode;
        date_filter?: { mode: DateMode; create_date: string };
    }) => {
        try {
            setLoading(true);
            const body = {
                project_id: project.id,
                function_names: override?.function_names ?? currentFunctionNames,
                filter_mode: override?.filter_mode ?? filterMode,
                date_filter: override?.date_filter ?? { mode: createDateMode, create_date: createDate }
            };
            const res = await fetch(`${API_BASE}${API_JOB_HISTORY}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            if (!res.ok) throw new Error(String(res.status));
            const data = await res.json();
            setJobs(data.nvflare_jobs || []);
        } catch (err) {
            console.error("Failed to fetch NVFlare jobs:", err);
            setJobs([]);
        } finally {
            setLoading(false);
        }
    };

    const fetchSupportedFunctions = async () => {
        const names: string[] = (project.functions || [])
            .map((f: any) => String(f.function || "").trim().toUpperCase())
            .filter(Boolean);

        const uniq = Array.from(new Set(names)).sort();

        setSupportedFunctions(uniq);

        const allChecked: Record<string, boolean> = {};
        uniq.forEach((n) => (allChecked[n] = true));
        setSelectedFunctions(allChecked);

        await fetchJobs({
            function_names: uniq,
            filter_mode: filterMode,
            date_filter: { mode: createDateMode, create_date: createDate }
        });
    };

    useEffect(() => {
        (async () => {
            try {
                await fetchSupportedFunctions();
            } catch (e) {
                console.error("Failed to load supported functions", e);
                setSupportedFunctions([]);
                setSelectedFunctions({});
            } finally {
                setInitializing(false);
            }
        })();
        // Initialize supported functions once for this mounted history table.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const updateJobInState = (jobKey: string, patch: Partial<NVFlareJob>) => {
        setJobs((prev) =>
            prev.map((job) => {
                const currentKey = job.job_runner_id || job.id.toString();
                if (currentKey !== jobKey) return job;
                return { ...job, ...patch };
            })
        );
    };

    const applyLiveStatusUpdate = (job: NVFlareJob, statusData: any) => {
        const jobKey = job.job_runner_id || job.id.toString();
        const nextStatus = statusData?.status || null;
        const nextLog = mapLogLinesToEntries(statusData?.log || []);

        latestTrackedStatusRef.current = nextStatus;

        setJobLogs((prev) => ({
            ...prev,
            [jobKey]: nextLog
        }));

        updateJobInState(jobKey, {
            run_duration: statusData?.run_duration ?? job.run_duration,
            functions: statusData?.functions || job.functions
        });
    };

    const fetchJobLogs = async (job: NVFlareJob) => {
        const jobKey = job.job_runner_id || job.id.toString();
        try {
            const res = await fetch(`${API_BASE}${API_JOB_STATUS}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ job_id: job.job_runner_id })
            });
            if (!res.ok) throw new Error(String(res.status));
            const data = await res.json();
            const nextLogs = mapLogLinesToEntries(data.log || []);

            setJobLogs((prev) => ({
                ...prev,
                [jobKey]: nextLogs
            }));

            updateJobInState(jobKey, {
                run_duration: data.run_duration ?? job.run_duration,
                functions: data.functions || job.functions
            });
        } catch (err) {
            console.error(`Failed to fetch logs for job ${jobKey}:`, err);
            setJobLogs((prev) => ({
                ...prev,
                [jobKey]: []
            }));
        }
    };

    const startPollingLoop = (job: NVFlareJob) => {
        const jobKey = job.job_runner_id || job.id.toString();
        clearPolling();

        pollRef.current = setInterval(async () => {
            if (trackedJobKeyRef.current !== jobKey) {
                clearPolling();
                return;
            }

            if (websocketStreamingRef.current) {
                clearPolling();
                return;
            }

            try {
                const res = await fetch(`${API_BASE}${API_JOB_STATUS}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ job_id: job.job_runner_id })
                });
                if (!res.ok) throw new Error(String(res.status));

                const statusData = await res.json();
                applyLiveStatusUpdate(job, statusData);

                if (isTerminalStatus(statusData?.status)) {
                    clearPolling();
                    closeWebSocket();
                    refreshJob(job);
                }
            } catch (err) {
                clearPolling();
                console.error(`Failed to poll live status for job ${jobKey}:`, err);
            }
        }, POLL_INTERVAL);
    };

    const startWebSocketStream = (job: NVFlareJob) => {
        if (!WEB_SOCKET) return;

        const jobKey = job.job_runner_id || job.id.toString();

        intentionallyClosingWsRef.current = false;
        websocketConnectedRef.current = false;
        websocketStreamingRef.current = false;

        const socketUrl = buildJobStatusWebSocketUrl(job.job_runner_id || "");

        const ws = new WebSocket(socketUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            websocketConnectedRef.current = true;
        };

        ws.onmessage = (event) => {
            try {

                const statusData = JSON.parse(event.data);

                if (statusData?.requires_ack && statusData?.message_id && ws.readyState === WebSocket.OPEN) {
                    const ackPayload = {
                        type: "ack",
                        message_id: statusData.message_id
                    };

                    ws.send(JSON.stringify(ackPayload));
                }

                if (statusData?.type === "heartbeat") {
                    return;
                }

                if (statusData?.type === "job_status_error") {
                    websocketStreamingRef.current = true;
                    clearPolling();
                    applyLiveStatusUpdate(job, statusData);
                    stopLiveTracking();
                    refreshJob(job);
                    return;
                }

                if (statusData?.type !== "job_status") {
                    return;
                }

                websocketStreamingRef.current = true;
                clearPolling();
                applyLiveStatusUpdate(job, statusData);

                if (isTerminalStatus(statusData?.status)) {

                    stopLiveTracking();
                    refreshJob(job);
                }
            } catch {
                if (!websocketStreamingRef.current && trackedJobKeyRef.current === jobKey) {
                    closeWebSocket();
                    return;
                }

                if (trackedJobKeyRef.current === jobKey && !isTerminalStatus(latestTrackedStatusRef.current)) {
                    startPollingLoop(job);
                }

                closeWebSocket();
            }
        };

        ws.onerror = () => {

            if (intentionallyClosingWsRef.current) return;

            if (trackedJobKeyRef.current === jobKey && websocketStreamingRef.current && !isTerminalStatus(latestTrackedStatusRef.current)) {
                startPollingLoop(job);
            }

            closeWebSocket();
        };

        ws.onclose = () => {

            if (wsRef.current === ws) {
                wsRef.current = null;
            }

            const wasIntentional = intentionallyClosingWsRef.current;
            websocketConnectedRef.current = false;

            if (wasIntentional) {
                return;
            }

            if (trackedJobKeyRef.current === jobKey && websocketStreamingRef.current && !isTerminalStatus(latestTrackedStatusRef.current)) {
                startPollingLoop(job);
            }
        };
    };

    const startLiveTracking = (job: NVFlareJob) => {
        const jobKey = job.job_runner_id || job.id.toString();
        stopLiveTracking();
        trackedJobKeyRef.current = jobKey;
        latestTrackedStatusRef.current = job.status || null;
        websocketConnectedRef.current = false;
        websocketStreamingRef.current = false;
        startPollingLoop(job);
        startWebSocketStream(job);
    };

    const refreshJob = async (job: NVFlareJob) => {
        const jobKey = job.job_runner_id || job.id.toString();
        setRefreshingJobId(jobKey);
        try {
            const res = await fetch(`${API_BASE}${API_JOB_HISTORY}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    project_id: project.id,
                    function_names: currentFunctionNames,
                    filter_mode: filterMode,
                    date_filter: { mode: createDateMode, create_date: createDate }
                })
            });
            if (!res.ok) throw new Error(String(res.status));
            const data = await res.json();
            const freshJobs: NVFlareJob[] = data.nvflare_jobs || [];
            const updated = freshJobs.find((j) => j.id === job.id);
            if (updated) {
                setJobs((prev) => prev.map((j) => (j.id === updated.id ? { ...j, ...updated } : j)));
                if (trackedJobKeyRef.current === jobKey) {
                    latestTrackedStatusRef.current = updated.status || null;
                }
            }
            if (expandedJobId === jobKey) {
                await fetchJobLogs(updated || job);
            }
        } finally {
            setRefreshingJobId(null);
        }
    };

    const toggleJobExpansion = async (job: NVFlareJob) => {
        refreshJob(job);
        const jobKey = job.job_runner_id || job.id.toString();
        if (expandedJobId === jobKey) {
            setExpandedJobId(null);
            setOpenFilterSummaryFor(null);
            setOpenConfigsFor(null);
            setOpenLogsFor(null);
            setOpenThresholdFor(null);
            setOpenDatasourceFor(null);
            setOpenWorkflowGroupsFor(null);
            setOpenParticipationFor(null);
            setOpenAuditFor(null);
            stopLiveTracking();
            return;
        }
        setExpandedJobId(jobKey);
        setOpenFilterSummaryFor(jobKey);
        setOpenConfigsFor(null);
        setOpenLogsFor(null);
        setOpenThresholdFor(null);
        setOpenDatasourceFor(null);
        setOpenWorkflowGroupsFor(null);
        setOpenParticipationFor(null);
        setOpenAuditFor(null);
        stopLiveTracking();
        if (!jobLogs[jobKey]) {
            await fetchJobLogs(job);
        }
    };

    const getExtraColumnValue = (job: NVFlareJob, key: string): string => {
        const normalizedLookupKey = normalizeConfigKey(key);
        if (!normalizedLookupKey) return "--";

        const fm = job.functions_map || {};
        const fnNames = Object.keys(fm);

        for (const fn of fnNames) {
            const rawCfg = fm[fn];
            const upper = String(fn || "").trim().toUpperCase();
            const fixed = fixedKeysByFnUpper[upper];

            const checkOne = (cfg: any): string | null => {
                if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) return null;
                if (fixed && fixed.has(normalizedLookupKey)) return null;

                const matchedKey = Object.keys(cfg).find(
                    (candidate) => normalizeConfigKey(candidate) === normalizedLookupKey
                );
                if (!matchedKey) return null;

                const v = (cfg as any)[matchedKey];
                if (v == null) return null;

                if (typeof v === "string") {
                    const s = v.trim();
                    return s ? s : null;
                }

                if (typeof v === "number" || typeof v === "boolean") {
                    return String(v);
                }

                try {
                    const js = JSON.stringify(v);
                    return js && js !== "null" ? js : null;
                } catch {
                    return String(v);
                }
            };

            if (Array.isArray(rawCfg)) {
                for (const cfg of rawCfg) {
                    const got = checkOne(cfg);
                    if (got != null) return got;
                }
            } else {
                const got = checkOne(rawCfg);
                if (got != null) return got;
            }
        }

        return "--";
    };

    const prettyExtraColLabel = (key: string): string => {
        return formatFunctionName(String(key || "").replace(/-/g, "_"));
    };

    const availableExtraColumnKeys = useMemo(() => {
        const keys = new Set<string>();

        for (const job of jobs) {
            const fm = job.functions_map || {};
            for (const fn of Object.keys(fm)) {
                const upper = String(fn || "").trim().toUpperCase();
                const fixed = fixedKeysByFnUpper[upper];

                const addFromCfg = (cfg: any) => {
                    if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) return;
                    for (const k of Object.keys(cfg)) {
                        const normalizedKey = normalizeConfigKey(String(k));
                        if (!normalizedKey) continue;
                        if (fixed && fixed.has(normalizedKey)) continue;
                        keys.add(normalizedKey);
                    }
                };

                const rawCfg = fm[fn];
                if (Array.isArray(rawCfg)) {
                    rawCfg.forEach(addFromCfg);
                } else {
                    addFromCfg(rawCfg);
                }
            }
        }

        return Array.from(keys).sort((a, b) => a.localeCompare(b));
    }, [jobs, fixedKeysByFnUpper]);

    useEffect(() => {
        if (didApplyDefaultColumnsRef.current) return;
        if (!availableExtraColumnKeys.length) return;

        didApplyDefaultColumnsRef.current = true;

        if (extraColumnKeys.length > 0) return;

        const availableSet = new Set(availableExtraColumnKeys);
        const defaultsThatExist = DEFAULT_SELECTED_COLUMNS
            .map((k) => normalizeConfigKey(k))
            .filter((k) => availableSet.has(k))
            .slice(0, 3);

        if (!defaultsThatExist.length) return;

        setExtraColumnKeys(defaultsThatExist);
    }, [availableExtraColumnKeys, extraColumnKeys.length, setExtraColumnKeys]);

    useEffect(() => {
        if (!onAvailableExtraColumnKeysChange) return;
        onAvailableExtraColumnKeysChange(availableExtraColumnKeys);
    }, [availableExtraColumnKeys, onAvailableExtraColumnKeysChange]);

    useEffect(() => {
        if (!availableExtraColumnKeys.length) return;
        if (!extraColumnKeys.length) return;

        const allowed = new Set(availableExtraColumnKeys);
        const cleaned = normalizeConfigKeys(extraColumnKeys).filter((k) => allowed.has(k)).slice(0, 3);
        if (cleaned.join("|") !== extraColumnKeys.join("|")) {
            setExtraColumnKeys(cleaned);
        }
    }, [availableExtraColumnKeys, extraColumnKeys, setExtraColumnKeys]);

    useEffect(() => {
        if (!openLogsFor || !expandedJobId || openLogsFor !== expandedJobId) {
            stopLiveTracking();
            return;
        }

        const job = jobs.find((j) => (j.job_runner_id || j.id.toString()) === openLogsFor);
        if (!job) {
            stopLiveTracking();
            return;
        }

        if (!shouldLiveTrackJob(job.status)) {
            stopLiveTracking();
            return;
        }

        startLiveTracking(job);

        return () => {
            stopLiveTracking();
        };
        // Live tracking is intentionally keyed only to the expanded logs row; job-state updates
        // are consumed by the active polling/websocket callbacks without restarting the stream.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [openLogsFor, expandedJobId]);

    useEffect(() => {
        return () => {
            stopLiveTracking();
        };
    }, [stopLiveTracking]);

    const tdBase: React.CSSProperties = {
        padding: "4px 8px",
        borderBottom: "1px solid #b4b4b4",
        verticalAlign: "middle",
        fontSize: 14,
        lineHeight: 1.25,
        borderLeft: "none",
        borderRight: "none",
        borderTop: "none"
    };
    const thBase: React.CSSProperties = {
        textAlign: "left",
        fontWeight: 700,
        fontSize: "10pt",
        padding: "6px 8px",
        whiteSpace: "nowrap",
        borderLeft: "none",
        borderRight: "none",
        borderTop: "none",
        borderBottom: "1px solid #b4b4b4",
        background: "#fff",
        position: "sticky",
        top: 0,
        zIndex: 1
    };

    const total = filteredJobs.length;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const startIdx = (page - 1) * PAGE_SIZE;
    const endIdx = Math.min(startIdx + PAGE_SIZE, total);
    const pageJobs = filteredJobs.slice(startIdx, endIdx);

    const latestJob = useMemo<NVFlareJob | undefined>(() => {
        if (!jobs.length) return undefined;
        return jobs.reduce<NVFlareJob | undefined>((acc, job) => {
            if (!acc) return job;
            const accTime = new Date(acc.create_date).getTime();
            const jobTime = new Date(job.create_date).getTime();
            return jobTime > accTime ? job : acc;
        }, undefined);
    }, [jobs]);

    const extraColCount = Math.min(3, extraColumnKeys.length);
    const colSpanCount = 5 + extraColCount;

    const truncate = (s: string, max = 64): string => {
        const str = String(s || "");
        if (str.length <= max) return str;
        return str.slice(0, max - 1) + "…";
    };

    if (compact) {
        if (!latestJob) {
            return <></>;
        }

        const status = latestJob.status || "Not Available";
        const timePhrase = new Date(latestJob.create_date).toLocaleString() + " UTC";

        return (
            <CompactBanner>
                <div>
                    <div>
                        <div className="duality-weight-600-mb-0p25rem">Most Recent Job</div>
                        <hr className="duality-m-0-0-0p4rem-0" />
                        <div className="duality-d-flex-justify-space-between-mb-0p15rem">
                            <span>Created: </span>
                            <span className="duality-text-right">{timePhrase}</span>
                        </div>
                        <div className="duality-flex-between">
                            <span>Status: </span>
                            <span className="duality-weight-600-text-3f5fff-text-right">
                                {status || "UNKNOWN"}
                            </span>
                        </div>
                    </div>
                </div>
            </CompactBanner>
        );
    }

    return (
        <>
            <div className="page-container">
                <div className="job-history-table-surface">
                    <RefreshablePanel
                    header="NVFlare Analysis History"
                    loading={loading || (initializing && jobs.length === 0)}
                    onRefresh={() => fetchJobs()}
                    refreshAriaLabel="Refresh analysis history"
                    refreshTitle="Refresh"
                    right={
                        <div
                            className="job-history-table-block-01"
                        >
                            <h5 className="duality-p-0-m-0-min-w-80px">Quick Filter</h5>
                            <input
                                type="text"
                                value={filterText}
                                onChange={(e) => setFilterText(e.target.value)}
                                placeholder="Filter by ID, Status, Function"
                                className="duality-p-0-8px-border-1px-solid-ccc-radius-4px"
                                aria-label="Filter jobs"
                            />
                        </div>
                    }
                >
                    {jobs.length === 0 ? (
                        <div>No analysis history found.</div>
                    ) : filteredJobs.length === 0 ? (
                        <div>No jobs match your filter.</div>
                    ) : (
                        <div className="duality-w-100pct-overflow-y-hidden-pt-p5rem">
                            <table
                                className="duality-w-100pct-collapse-collapse-border-spa-0"
                            >
                                <thead>
                                    <tr>
                                        <th style={thBase} aria-label="Expand">
                                            Job
                                        </th>
                                        <th style={thBase}>Function(s)</th>
                                        {extraColumnKeys.slice(0, 3).map((k) => (
                                            <th key={k} style={thBase} title={k}>
                                                {prettyExtraColLabel(k)}
                                            </th>
                                        ))}
                                        <th style={thBase}>Status</th>
                                        <th style={thBase}>Created</th>
                                        <th style={{ ...thBase, textAlign: "right" }}>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    if (onOpenColumnConfig) onOpenColumnConfig();
                                                }}
                                                className="job-history-table-configure-columns"
                                                title="Configure columns"
                                                aria-label="Configure columns"
                                                type="button"
                                            >
                                                <Gear size={16} />
                                            </button>
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {pageJobs.map((job) => {
                                        const jobKey = job.job_runner_id || job.id.toString();
                                        const isExpanded = expandedJobId === jobKey;
                                        const fnFull = listFunctions(job).map(formatFunctionName).join(", ");
                                        const hasFilterSummary = !!job.filter_id;
                                        const hasDatasourceSection = !!job.datasource_log;
                                        const hasWorkflowGroupsSection = !!(job.workflow_groups && job.workflow_groups.length);
                                        const hasParticipationSection = hasParticipationSettings(job);
                                        const hasThresholdSection = hasThresholdSettings(job);
                                        const hasEncryptionSection = hasEncryptionParams(job);

                                        const allOpen =
                                            openConfigsFor === jobKey &&
                                            (!hasThresholdSection || openThresholdFor === jobKey) &&
                                            (!hasDatasourceSection || openDatasourceFor === jobKey) &&
                                            (!hasWorkflowGroupsSection || openWorkflowGroupsFor === jobKey) &&
                                            (!hasParticipationSection || openParticipationFor === jobKey) &&
                                            (!hasEncryptionSection || openAuditFor === jobKey) &&
                                            openLogsFor === jobKey &&
                                            (!hasFilterSummary || openFilterSummaryFor === jobKey);

                                        return (
                                            <React.Fragment key={jobKey}>
                                                <tr
                                                    tabIndex={0}
                                                    className="job-history-table-tr" style={{ background: isExpanded ? "#F9F9F9" : "white" }}
                                                    onClick={() => toggleJobExpansion(job)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === "Enter" || e.key === " ") {
                                                            e.preventDefault();
                                                            toggleJobExpansion(job);
                                                        }
                                                    }}
                                                >
                                                    <td style={tdBase}>
                                                        <div className="duality-font-semibold">
                                                            {isExpanded ? "▾" : "▸"}
                                                            {job.id}
                                                        </div>
                                                    </td>
                                                    <td style={tdBase}>
                                                        <div className="job-history-table-shared-01">
                                                            {fnFull || "Not recorded"}
                                                        </div>
                                                    </td>

                                                    {extraColumnKeys.slice(0, 3).map((k) => {
                                                        const raw = getExtraColumnValue(job, k);
                                                        const shown = raw === "--" ? raw : truncate(raw, 64);
                                                        return (
                                                            <td key={k} style={{ ...tdBase, maxWidth: "16vw" }} title={raw !== "--" ? raw : undefined}>
                                                                <div className="job-history-table-shared-01">{shown}</div>
                                                            </td>
                                                        );
                                                    })}

                                                    <td style={tdBase}>
                                                        <div>{job.status || "Not Available"}</div>
                                                    </td>
                                                    <td style={tdBase}>
                                                        <div>{new Date(job.create_date).toLocaleString() + " UTC"}</div>
                                                    </td>
                                                    <td style={{ ...tdBase, maxWidth: "140px", textAlign: "right" }}>
                                                        {isExpanded && (
                                                            <button
                                                                className="secondary-button job-history-table-refresh-this-job"
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    refreshJob(job);
                                                                }}
                                                                disabled={refreshingJobId === jobKey}
                                                                
                                                                title="Refresh this job"
                                                            >
                                                                {refreshingJobId === jobKey ? "…" : "⟳"}
                                                            </button>
                                                        )}
                                                        {canViewResults(job.status) && (
                                                            <button
                                                                type="button"
                                                                className="project-link-button project-view-results-button job-history-table-view-results"
                                                                
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    onViewResults(job);
                                                                }}
                                                                title="View Results"
                                                            >
                                                                <span>View Results</span>
                                                            </button>
                                                        )}
                                                    </td>
                                                </tr>

                                                {isExpanded && (
                                                    <tr
                                                        className="job-history-table-tr-c9e57"
                                                    >
                                                        <td
                                                            style={{
                                                                ...tdBase,
                                                                paddingLeft: "3.5rem",
                                                                background: "white",
                                                                paddingRight: "1.5rem"
                                                            }}
                                                            colSpan={colSpanCount}
                                                        >
                                                            <div className="job-history-table-block-02">
                                                                <AnimateIn delayMs={0}>
                                                                    <div
                                                                        className="job-history-table-block-03"
                                                                    >
                                                                        <div
                                                                            className="job-history-table-block-04"
                                                                        >
                                                                            <div>Total Runtime Duration:</div>
                                                                            <div className="duality-font-semibold">{job.run_duration || "--"}</div>
                                                                        </div>

                                                                        <button
                                                                            className="button-href job-history-table-block-05"
                                                                            onClick={async (e) => {
                                                                                e.stopPropagation();

                                                                                if (allOpen) {
                                                                                    setOpenFilterSummaryFor(null);
                                                                                    setOpenConfigsFor(null);
                                                                                    setOpenThresholdFor(null);
                                                                                    setOpenDatasourceFor(null);
                                                                                    setOpenWorkflowGroupsFor(null);
                                                                                    setOpenParticipationFor(null);
                                                                                    setOpenAuditFor(null);
                                                                                    setOpenLogsFor(null);
                                                                                    stopLiveTracking();
                                                                                    return;
                                                                                }

                                                                                if (hasFilterSummary) setOpenFilterSummaryFor(jobKey);
                                                                                setOpenConfigsFor(jobKey);
                                                                                if (hasThresholdSection) setOpenThresholdFor(jobKey);
                                                                                if (hasDatasourceSection) setOpenDatasourceFor(jobKey);
                                                                                if (hasWorkflowGroupsSection) setOpenWorkflowGroupsFor(jobKey);
                                                                                if (hasParticipationSection) setOpenParticipationFor(jobKey);
                                                                                if (hasEncryptionSection) setOpenAuditFor(jobKey);
                                                                                setOpenLogsFor(jobKey);

                                                                                if (!jobLogs[jobKey]) {
                                                                                    await fetchJobLogs(job);
                                                                                }
                                                                            }}
                                                                            title={allOpen ? "Collapse all sections" : "Expand all sections"}
                                                                            
                                                                        >
                                                                            {allOpen ? "Collapse All" : "Expand All"}
                                                                        </button>
                                                                    </div>
                                                                </AnimateIn>

                                                                {job.filter_id && (
                                                                    <AnimateIn delayMs={25}>
                                                                        <FilterSummarySection
                                                                            filterId={job.filter_id}
                                                                            project={project}
                                                                            jobKey={jobKey}
                                                                            isOpen={openFilterSummaryFor === jobKey}
                                                                            onToggle={() =>
                                                                                setOpenFilterSummaryFor((cur) => (cur === jobKey ? null : jobKey))
                                                                            }
                                                                        />
                                                                    </AnimateIn>
                                                                )}

                                                                <AnimateIn delayMs={50}>
                                                                    <FunctionConfigSection
                                                                        job={job}
                                                                        jobKey={jobKey}
                                                                        isOpen={openConfigsFor === jobKey}
                                                                        onToggle={() => setOpenConfigsFor((cur) => (cur === jobKey ? null : jobKey))}
                                                                        project={project}
                                                                    />
                                                                </AnimateIn>

                                                                {hasThresholdSection && (
                                                                    <AnimateIn delayMs={75}>
                                                                        <ThresholdConfigSection
                                                                            job={job}
                                                                            jobKey={jobKey}
                                                                            isOpen={openThresholdFor === jobKey}
                                                                            onToggle={() =>
                                                                                setOpenThresholdFor((cur) => (cur === jobKey ? null : jobKey))
                                                                            }
                                                                            formatThresholdMethod={formatThresholdMethod}
                                                                        />
                                                                    </AnimateIn>
                                                                )}

                                                                {hasDatasourceSection && (
                                                                    <AnimateIn delayMs={88}>
                                                                        <DatasourceSelectionSection
                                                                            job={job}
                                                                            jobKey={jobKey}
                                                                            isOpen={openDatasourceFor === jobKey}
                                                                            onToggle={() =>
                                                                                setOpenDatasourceFor((cur) => (cur === jobKey ? null : jobKey))
                                                                            }
                                                                        />
                                                                    </AnimateIn>
                                                                )}

                                                                {hasParticipationSection && (
                                                                    <AnimateIn delayMs={94}>
                                                                        <ParticipationSection
                                                                            job={job}
                                                                            jobKey={jobKey}
                                                                            isOpen={openParticipationFor === jobKey}
                                                                            onToggle={() =>
                                                                                setOpenParticipationFor((cur) => (cur === jobKey ? null : jobKey))
                                                                            }
                                                                        />
                                                                    </AnimateIn>
                                                                )}

                                                                {hasWorkflowGroupsSection && (
                                                                    <AnimateIn delayMs={100}>
                                                                        <WorkflowGroupSelectionSection
                                                                            job={job}
                                                                            jobKey={jobKey}
                                                                            isOpen={openWorkflowGroupsFor === jobKey}
                                                                            onToggle={() =>
                                                                                setOpenWorkflowGroupsFor((cur) => (cur === jobKey ? null : jobKey))
                                                                            }
                                                                        />
                                                                    </AnimateIn>
                                                                )}

                                                                {hasEncryptionSection && (
                                                                    <AnimateIn delayMs={106}>
                                                                        <EncryptionParamsSection
                                                                            job={job}
                                                                            jobKey={jobKey}
                                                                            isOpen={openAuditFor === jobKey}
                                                                            onToggle={() => setOpenAuditFor((cur) => (cur === jobKey ? null : jobKey))}
                                                                        />
                                                                    </AnimateIn>
                                                                )}

                                                                <AnimateIn delayMs={125}>
                                                                    <LogOutputSection
                                                                        job={job}
                                                                        jobKey={jobKey}
                                                                        isOpen={openLogsFor === jobKey}
                                                                        logs={jobLogs[jobKey]}
                                                                        onToggle={async () => {
                                                                            const next = openLogsFor === jobKey ? null : jobKey;
                                                                            setOpenLogsFor(next);

                                                                            if (!next) {
                                                                                stopLiveTracking();
                                                                                return;
                                                                            }

                                                                            if (!jobLogs[jobKey]) {
                                                                                await fetchJobLogs(job);
                                                                            }
                                                                        }}
                                                                    />
                                                                </AnimateIn>
                                                            </div>
                                                        </td>
                                                    </tr>
                                                )}
                                            </React.Fragment>
                                        );
                                    })}
                                </tbody>
                            </table>

                            {totalPages > 1 && (
                                <div
                                    className="duality-d-flex-justify-center-align-center"
                                >
                                    <button type="button" className="link-button-reset duality-decoration-underline-text-under-2px-text-decor-1px"
                                        onClick={(e) => {
                                            e.preventDefault();
                                            if (page > 1) setPage((p) => Math.max(1, p - 1));
                                        }}
                                        style={{ color: page > 1 ? "#007BFF" : "#A0A0A0", cursor: page > 1 ? "pointer" : "not-allowed", pointerEvents: page > 1 ? "auto" : "none" }}
                                                                >
                                        Previous
                                    </button>

                                    {(() => {
                                        const current = page;
                                        const pageCount = totalPages;
                                        const windowSize = 5;
                                        let start = Math.max(1, current - Math.floor(windowSize / 2));
                                        let end = start + windowSize - 1;
                                        if (end > pageCount) {
                                            end = pageCount;
                                            start = Math.max(1, end - windowSize + 1);
                                        }
                                        return Array.from({ length: end - start + 1 }, (_, i) => {
                                            const pageNum = start + i;
                                            const isActive = pageNum === current;
                                            return (
                                                <button type="button" className="link-button-reset duality-p-0p25rem-0p5rem-radius-4px-decoration-underline"
                                                    key={pageNum}
                                                    onClick={(e) => {
                                                        e.preventDefault();
                                                        setPage(pageNum);
                                                    }}
                                                    style={{ color: isActive ? "#fff" : "#007BFF", backgroundColor: isActive ? "#007BFF" : "transparent" }}
                                                                                        >
                                                    {pageNum}
                                                </button>
                                            );
                                        });
                                    })()}

                                    <button type="button" className="link-button-reset duality-decoration-underline-text-under-2px-text-decor-1px"
                                        onClick={(e) => {
                                            e.preventDefault();
                                            if (page < totalPages) setPage((p) => Math.min(totalPages, p + 1));
                                        }}
                                        style={{ color: page < totalPages ? "#007BFF" : "#A0A0A0", cursor: page < totalPages ? "pointer" : "not-allowed", pointerEvents: page < totalPages ? "auto" : "none" }}
                                                                >
                                        Next
                                    </button>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="job-history-table-block-06">
                        <button
                            className="button-href job-history-table-show-hide-query-filters"
                            onClick={(e) => {
                                e.stopPropagation();
                                setOpenQueryFilters((v) => !v);
                            }}
                            title="Show/Hide Query Filters"
                            
                        >
                            <span className="job-history-table-block-07">{openQueryFilters ? "▾" : "▸"}</span>
                            Query Configuration
                        </button>

                        {openQueryFilters && (
                            <div
                                className="job-history-table-block-08"
                            >
                                {supportedFunctions.length > 1 && (
                                    <div className="duality-flex-between-center">
                                        <div
                                            className="job-history-table-block-09"
                                        >
                                            <div className="job-history-table-shared-02">
                                                <label className="duality-font-semibold" htmlFor="filterMode">
                                                    Limit Function(s)
                                                </label>
                                                <select
                                                    id="filterMode"
                                                    value={filterMode}
                                                    onChange={(e) => setFilterMode((e.target.value as FilterMode) || "ANY")}
                                                    className="job-history-table-shared-03"
                                                >
                                                    <option value="ANY">to ANY</option>
                                                    <option value="ONLY">to ONLY</option>
                                                </select>
                                            </div>

                                            <div className="job-history-table-block-10">
                                                {supportedFunctions.map((fn) => {
                                                    const id = `fn_${fn}`;
                                                    const checked = !!selectedFunctions[fn];
                                                    return (
                                                        <label
                                                            key={fn}
                                                            htmlFor={id}
                                                            className="job-history-table-block-11"
                                                        >
                                                            <input
                                                                id={id}
                                                                type="checkbox"
                                                                checked={checked}
                                                                onChange={(e) =>
                                                                    setSelectedFunctions((prev) => ({
                                                                        ...prev,
                                                                        [fn]: e.target.checked
                                                                    }))
                                                                }
                                                            />
                                                            {formatFunctionName(fn)}
                                                        </label>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                <div
                                    className="job-history-table-block-12"
                                >
                                    <div
                                        className="job-history-table-block-13"
                                    >
                                        <div className="job-history-table-shared-02">
                                            <label className="duality-font-semibold" htmlFor="createDateMode">
                                                Created
                                            </label>
                                            <select
                                                id="createDateMode"
                                                value={createDateMode}
                                                onChange={(e) => setCreateDateMode((e.target.value as DateMode) || "AFTER")}
                                                className="job-history-table-shared-03"
                                            >
                                                <option value="ON">ON</option>
                                                <option value="AFTER">AFTER</option>
                                                <option value="BEFORE">BEFORE</option>
                                            </select>
                                            <input
                                                type="date"
                                                value={createDate}
                                                onChange={(e) => setCreateDate(e.target.value)}
                                                aria-label="Created date"
                                                className="job-history-table-created-date"
                                            />
                                            NOTE: Default create date is 30 days ago
                                        </div>
                                    </div>
                                    <div className="job-history-table-block-14">
                                        <button
                                            onClick={() =>
                                                fetchJobs({
                                                    date_filter: {
                                                        mode: createDateMode,
                                                        create_date: createDate
                                                    }
                                                })
                                            }
                                            
                                            className="secondary-button job-history-table-apply-date-filter"
                                            title="Apply date filter"
                                        >
                                            Apply
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                    </RefreshablePanel>

                    <div className="footer-button-container surface-action-bar surface-action-bar-right">
                        {jobRunnerRole && (
                            <button onClick={onStartNewAnalysis}>Run New Analysis</button>
                        )}
                    </div>
                </div>
            </div>
        </>
    );
};

export default JobHistoryTable;