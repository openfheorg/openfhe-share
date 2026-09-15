import React, { useMemo, useState } from "react";
import { AnimateIn } from "./AnimateIn";

export const WARN_EXCEPTION_MARKER = "WarnException";

export type WorkflowErrorJson = {
    timestamp_utc?: string;
    job_id?: string;
    workflow?: string;
    round?: number;
    stage?: string;
    exception_type?: string;
    message?: string;
    traceback?: string;
    code?: string;
    details?: Record<string, unknown>;
    status?: string;
};

export type WorkflowPanelVariant = "error" | "warning";

export type WorkflowWarning = WorkflowErrorJson & {
    exception_type: typeof WARN_EXCEPTION_MARKER;
};

type UnknownRecord = Record<string, unknown>;

function safeString(v: unknown): string {
    if (v == null) return "";
    if (typeof v === "string") return v;
    return String(v);
}

function asRecord(value: unknown): UnknownRecord | null {
    return value && typeof value === "object" && !Array.isArray(value)
        ? (value as UnknownRecord)
        : null;
}

function formatLabel(value: string): string {
    const normalized = value.replace(/_/g, " ").trim();
    return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : value;
}

export function getWorkflowErrorFromJobData(jobData: any): WorkflowErrorJson | null {
    if (!jobData || typeof jobData !== "object") return null;

    const raw =
        jobData.workflow_error ??
        jobData.workflowError ??
        jobData.error_json ??
        jobData.errorJson ??
        jobData.workflow_error_json ??
        jobData.workflowErrorJson ??
        null;

    if (!raw) return null;

    const looksLikeMissing = (msg: string) => {
        const s = msg.toLowerCase();
        return s.includes("unreadable file:") && (s.includes("not found") || s.includes("no such file"));
    };

    if (typeof raw === "string") {
        if (looksLikeMissing(raw)) return null;
        return { message: raw };
    }

    if (typeof raw === "object" && raw) {
        const msg = typeof (raw as any).message === "string" ? (raw as any).message : "";
        const err = typeof (raw as any).error === "string" ? (raw as any).error : "";
        if ((msg && looksLikeMissing(msg)) || (err && looksLikeMissing(err))) return null;

        const keys = Object.keys(raw);
        if (keys.length === 0) return null;

        return raw as WorkflowErrorJson;
    }

    return null;
}

function findWorkflowWarning(
    value: unknown,
    seen: WeakSet<object> = new WeakSet<object>(),
): WorkflowWarning | null {
    if (!value) {
        return null;
    }

    if (typeof value === "string") {
        const marker = `${WARN_EXCEPTION_MARKER}:`;
        const markerIndex = value.indexOf(marker);
        if (markerIndex >= 0) {
            const message = value.slice(markerIndex + marker.length).trim();
            return {
                exception_type: WARN_EXCEPTION_MARKER,
                message: message || "This workflow completed with a warning.",
            };
        }

        try {
            return findWorkflowWarning(JSON.parse(value), seen);
        } catch {
            return null;
        }
    }

    const record = asRecord(value);
    if (!record) {
        return null;
    }

    if (seen.has(record)) {
        return null;
    }
    seen.add(record);

    const message =
        typeof record.message === "string"
            ? record.message
            : typeof record.msg === "string"
                ? record.msg
                : null;
    const exceptionType =
        typeof record.exception_type === "string"
            ? record.exception_type
            : typeof record.type === "string"
                ? record.type
                : typeof record.name === "string"
                    ? record.name
                    : null;
    const isWarning =
        exceptionType === WARN_EXCEPTION_MARKER ||
        String(record.status ?? "").toUpperCase() === "WARN";

    if (isWarning && message) {
        return {
            timestamp_utc: typeof record.timestamp_utc === "string" ? record.timestamp_utc : undefined,
            job_id: typeof record.job_id === "string" ? record.job_id : undefined,
            workflow: typeof record.workflow === "string" ? record.workflow : undefined,
            round: typeof record.round === "number" ? record.round : undefined,
            stage: typeof record.stage === "string" ? record.stage : undefined,
            exception_type: WARN_EXCEPTION_MARKER,
            message,
            code: typeof record.code === "string" ? record.code : undefined,
            details: asRecord(record.details) ?? undefined,
            status: "WARN",
        };
    }

    for (const key of [
        "warning",
        "warnings",
        "workflow_warning",
        "workflow_warnings",
        "exception",
        "error",
        "aggregate_processed_results",
        "processed_results",
        "result",
        "results",
        "jobData",
    ]) {
        const nested = record[key];

        if (Array.isArray(nested)) {
            for (const item of nested) {
                const warning = findWorkflowWarning(item, seen);
                if (warning) {
                    return warning;
                }
            }
        } else {
            const warning = findWorkflowWarning(nested, seen);
            if (warning) {
                return warning;
            }
        }
    }

    return null;
}

/**
 * Finds a serialized WarnException or legacy status="WARN" result payload.
 * This keeps existing jobs readable while new backend jobs use the explicit
 * WarnException marker.
 */
export function getWorkflowWarning(...values: unknown[]): WorkflowWarning | null {
    for (const value of values) {
        const warning = findWorkflowWarning(value);
        if (warning) {
            return warning;
        }
    }

    return null;
}

export type WorkflowErrorPanelProps = {
    error: WorkflowErrorJson;
    /** Controls the visual treatment while retaining one shared panel layout. */
    variant?: WorkflowPanelVariant;
    title?: string;
    defaultExpanded?: boolean;
    showTracebackToggle?: boolean;
};

const WorkflowErrorPanel: React.FC<WorkflowErrorPanelProps> = ({
    error,
    variant = "error",
    title,
    defaultExpanded = false,
    showTracebackToggle = variant === "error",
}) => {
    const [expanded, setExpanded] = useState(defaultExpanded || !showTracebackToggle);
    const [copied, setCopied] = useState(false);

    const traceback = useMemo(() => safeString(error?.traceback).trim(), [error]);
    const hasTraceback = traceback.length > 0;
    const canToggle = variant === "error" && showTracebackToggle && hasTraceback;
    const showTraceback = variant === "error" && hasTraceback;

    const timestamp = safeString(error?.timestamp_utc);
    const workflow = safeString(error?.workflow);
    const stage = safeString(error?.stage);
    const exceptionType = safeString(error?.exception_type);
    const message = safeString(error?.message);
    const code = safeString(error?.code);
    const details = useMemo(
        () => Object.entries(error?.details ?? {}).filter(([, value]) => value !== undefined && value !== null && value !== ""),
        [error],
    );
    const round =
        typeof error?.round === "number" && Number.isFinite(error.round) ? error.round : null;

    const palette =
        variant === "warning"
            ? {
                border: "#d6a426",
                background: "#fff8db",
                heading: "#8a5a00",
                tracebackBorder: "#ead48b",
            }
            : {
                border: "#ccc",
                background: "#fff5f5",
                heading: "#b7150fff",
                tracebackBorder: "#f0c2c0",
            };

    const resolvedTitle = title ?? (variant === "warning" ? "Workflow Warning" : "Exception Encountered");

    const copyTraceback = async () => {
        if (!hasTraceback) return;
        try {
            await navigator.clipboard.writeText(traceback);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
        } catch {
            setCopied(false);
        }
    };

    return (
        <div
            role={variant === "warning" ? "status" : "alert"}
            className="workflow-error-panel-block-01" style={{ border: `1px solid ${palette.border}`, backgroundColor: palette.background }}
        >
            <div className="workflow-error-panel-block-02">
                <h4 className="workflow-error-panel-h4" style={{ color: palette.heading }}>{resolvedTitle}</h4>
            </div>

            <div className="workflow-error-panel-block-03">
                <div
                    className="workflow-error-panel-block-04"
                >
                    {message ? (
                        <>
                            <div className="duality-font-semibold">Message</div>
                            <div>{message}</div>
                        </>
                    ) : null}

                    {variant === "warning" && code ? (
                        <>
                            <div className="duality-font-semibold">Warning Code</div>
                            <div>{formatLabel(code)}</div>
                        </>
                    ) : null}

                    {variant === "error" && exceptionType ? (
                        <>
                            <div className="duality-font-semibold">Exception Type</div>
                            <div>{exceptionType}</div>
                        </>
                    ) : null}

                    {stage ? (
                        <>
                            <div className="duality-font-semibold">Stage</div>
                            <div>{stage}</div>
                        </>
                    ) : null}

                    {workflow ? (
                        <>
                            <div className="duality-font-semibold">Workflow</div>
                            <div>{workflow}</div>
                        </>
                    ) : null}

                    {round !== null ? (
                        <>
                            <div className="duality-font-semibold">Round</div>
                            <div>{round}</div>
                        </>
                    ) : null}

                    {timestamp ? (
                        <>
                            <div className="duality-font-semibold">Timestamp (UTC)</div>
                            <div>{timestamp}</div>
                        </>
                    ) : null}

                    {details.map(([key, value]) => (
                        <React.Fragment key={key}>
                            <div className="duality-font-semibold">{formatLabel(key)}</div>
                            <div>{safeString(value)}</div>
                        </React.Fragment>
                    ))}
                </div>

                {showTraceback && (
                    <div className="workflow-error-panel-block-05">
                        <div
                            className="workflow-error-panel-block-06"
                        >
                            {canToggle ? (
                                <button
                                    type="button"
                                    className="button-href workflow-error-panel-shared-01"
                                    onClick={() => setExpanded((v) => !v)}
                                    
                                >
                                    Stack Trace
                                </button>
                            ) : (
                                <div className="duality-font-semibold">Stack Trace</div>
                            )}
                            {expanded && (
                                <div className="workflow-error-panel-block-07">
                                    <button
                                        
                                        type="button"
                                        className="button-href workflow-error-panel-shared-01"
                                        onClick={copyTraceback}
                                    >
                                        {copied ? "Copied" : "Copy"}
                                    </button>
                                </div>
                            )}
                        </div>

                        {(expanded || !canToggle) && (
                            <AnimateIn>
                                <pre
                                    className="workflow-error-panel-pre" style={{ border: `1px solid ${palette.tracebackBorder}` }}
                                >
                                    {traceback}
                                </pre>
                            </AnimateIn>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default WorkflowErrorPanel;
