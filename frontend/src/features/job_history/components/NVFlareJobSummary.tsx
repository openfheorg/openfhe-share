import React, { useMemo } from "react";
import { NVFlareJob } from "../../../types/JobsDataTypes";
import { useSelectedProjectDatasources } from "../../../context/UserRoleContext";
import AbstractAccordion from "../../../components/AbstractAccordion";

interface NVFlareJobSummaryProps {
    nvflareJob?: NVFlareJobWithParticipation | null;
    boldBorder?: boolean;
    defaultOpen?: boolean;
    isOpen?: boolean;
    onToggle?: () => void;
    enableFunctionLinks?: boolean;
}

type NVFlareJobWithParticipation = NVFlareJob & {
    non_contributing_clients?: string | null;
    exclude_analyzing_clients?: string | null;
};

function prettifyKey(key: string): string {
    return key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (str) =>
        str.toUpperCase()
    );
}

function getResultFunctionAnchorId(functionName: string): string {
    const normalized = String(functionName || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "");

    return `result-function-${normalized || "unknown"}`;
}

function scrollToResultFunction(functionName: string) {
    if (typeof document === "undefined" || typeof window === "undefined") {
        return;
    }

    const id = getResultFunctionAnchorId(functionName);
    const element = document.getElementById(id);
    window.history.replaceState(window.history.state || {}, "", `#${id}`);

    if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

function hasRenderableValue(value: any): boolean {
    if (value === null || value === undefined) return false;

    if (typeof value === "string") {
        return value.trim() !== "";
    }

    if (typeof value === "number") {
        return Number.isFinite(value);
    }

    if (typeof value === "boolean") {
        return true;
    }

    if (Array.isArray(value)) {
        if (value.length === 0) return false;
        return value.some((item) => hasRenderableValue(item));
    }

    if (typeof value === "object") {
        const entries = Object.entries(value);
        if (entries.length === 0) return false;
        return entries.some(([, v]) => hasRenderableValue(v));
    }

    return false;
}

function formatValue(value: any): string {
    if (Array.isArray(value)) {
        return value
            .filter((item) => hasRenderableValue(item))
            .map((item) => formatValue(item))
            .join(", ");
    }

    if (typeof value === "boolean") {
        return value ? "Yes" : "No";
    }

    if (value && typeof value === "object") {
        return Object.entries(value)
            .filter(([, v]) => hasRenderableValue(v))
            .map(([k, v]) => `${prettifyKey(k)}: ${formatValue(v)}`)
            .join(", ");
    }

    return value?.toString?.() ?? "";
}

export function formatThresholdMethod(method?: string | null): string {
    const normalized = (method || "").trim().toUpperCase();
    if (normalized === "PROTECTED") return "Protected";
    if (normalized === "EXPOSED") return "Exposed";
    return (method || "").trim();
}

function parseCsvList(value?: string | null): string[] {
    if (!value) return [];
    return value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
}

function isDefaultDatasourceGroup(value?: string | null): boolean {
    return (value || "").trim().toUpperCase() === "DEFAULT";
}

function formatDateTime(value?: string | null): string {
    if (!value) return "";

    const parsed = Date.parse(value);
    if (Number.isNaN(parsed)) {
        return value;
    }

    return new Date(parsed).toLocaleString();
}

function formatRunDuration(value?: string | null): string {
    if (!value) return "";

    const trimmed = value.trim();

    const clockMatch = trimmed.match(/^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)(.*)$/);
    if (clockMatch) {
        const hours = Number(clockMatch[1]);
        const minutes = Number(clockMatch[2]);
        const seconds = Number(clockMatch[3]);

        if (Number.isFinite(hours) && Number.isFinite(minutes) && Number.isFinite(seconds)) {
            const totalTenths = Math.round((hours * 3600 + minutes * 60 + seconds) * 10);
            const roundedHours = Math.floor(totalTenths / 36000);
            const remainderAfterHours = totalTenths % 36000;
            const roundedMinutes = Math.floor(remainderAfterHours / 600);
            const roundedSeconds = (remainderAfterHours % 600) / 10;

            return `${roundedHours}:${String(roundedMinutes).padStart(2, "0")}:${roundedSeconds
                .toFixed(1)
                .padStart(4, "0")}${clockMatch[4]}`;
        }
    }

    const numericMatch = trimmed.match(/^(-?\d+(?:\.\d+)?)(.*)$/);
    if (numericMatch) {
        const numericValue = Number(numericMatch[1]);
        if (Number.isFinite(numericValue)) {
            return `${numericValue.toFixed(1)}${numericMatch[2]}`;
        }
    }

    return trimmed;
}

const sectionTitleStyle: React.CSSProperties = {
    fontWeight: 600,
    marginBottom: "0.25rem",
    borderBottom: "1px solid #ccc",
};

const labelStyle: React.CSSProperties = {
    color: "#4b5563",
};

const valueStyle: React.CSSProperties = {
    fontWeight: 600,
    color: "#111827",
};

const emptyValueStyle: React.CSSProperties = {
    color: "#6b7280",
    fontStyle: "italic",
};

function SummaryField({ label, value }: { label: string; value: any }) {
    if (!hasRenderableValue(value)) {
        return null;
    }

    return (
        <div
            className="duality-flex-column-min-0"
        >
            <div style={labelStyle}>{label}</div>
            <div style={valueStyle}>{formatValue(value)}</div>
        </div>
    );
}

function FunctionButtons({ functions }: { functions: string[] }) {
    if (!functions.length) {
        return null;
    }

    return (
        <div
            className="nvflare-job-summary-block-01"
        >
            {functions.map((functionName) => (
                <button
                    key={`function-link-${functionName}`}
                    type="button"
                    className="button-href duality-text-black"
                    
                    onClick={() => scrollToResultFunction(functionName)}
                >
                    {formatValue(functionName)}
                </button>
            ))}
        </div>
    );
}

function SummarySection({
    title,
    children,
}: {
    title: string;
    children: React.ReactNode;
}) {
    return (
        <div className="nvflare-job-summary-block-02">
            <div style={sectionTitleStyle}>{title}</div>
            <div
                className="duality-d-grid-grid-cols-repeat-auto-fit-mi-gap-0p3rem-0p65rem"
            >
                {children}
            </div>
        </div>
    );
}

function PartyList({ title, clients }: { title: string; clients: string[] }) {
    if (!clients.length) {
        return null;
    }

    return (
        <div
            className="duality-flex-column-min-0"
        >
            <div style={labelStyle}>{title}</div>
            <div
                className="nvflare-job-summary-block-03"
            >
                {clients.map((client) => (
                    <span
                        key={`${title}-${client}`}
                        className="nvflare-job-summary-block-04"
                    >
                        {client}
                    </span>
                ))}
            </div>
        </div>
    );
}


function DatasourceSummary({ job }: { job: NVFlareJobWithParticipation }) {
    const selectedProjectDatasources = useSelectedProjectDatasources();
    const datasourceLog = job.datasource_log;
    const datasourceGroupName = datasourceLog?.datasource_group_name || job.datasource_group_name || null;
    const datasourceGroupId = datasourceLog?.datasource_group_id ?? job.datasource_group_id ?? null;

    const datasourceDetails = useMemo(() => {
        if (!selectedProjectDatasources.length) {
            return null;
        }

        if (datasourceGroupId != null) {
            const groupedMatch = selectedProjectDatasources.find((entry) => entry.datasource_group_id === datasourceGroupId);
            if (groupedMatch) {
                const groupName = datasourceGroupName || groupedMatch.datasource_group_name || `Group ${datasourceGroupId}`;

                return {
                    showGroup: !isDefaultDatasourceGroup(groupName),
                    groupName,
                    source: groupedMatch.source,
                    href: groupedMatch.source.toLowerCase().endsWith(".json") ? null : groupedMatch.source,
                };
            }
        }

        const defaultDatasource =
            selectedProjectDatasources.find((entry) => entry.is_default_group) ||
            selectedProjectDatasources.find((entry) => entry.datasource_group_id == null) ||
            selectedProjectDatasources[0];

        if (!defaultDatasource) {
            return null;
        }

        const defaultGroupName =
            datasourceGroupName ||
            defaultDatasource.datasource_group_name ||
            (defaultDatasource.is_default_group ? "DEFAULT" : null);

        return {
            showGroup: !!defaultGroupName && !isDefaultDatasourceGroup(defaultGroupName),
            groupName: defaultGroupName,
            source: defaultDatasource.source,
            href: defaultDatasource.source.toLowerCase().endsWith(".json") ? null : defaultDatasource.source,
        };
    }, [selectedProjectDatasources, datasourceGroupId, datasourceGroupName]);

    if (!datasourceDetails) {
        return <div style={emptyValueStyle}>No data source selection information associated with this job.</div>;
    }

    return (
        <div
            className="nvflare-job-summary-block-05"
        >
            {datasourceDetails.showGroup ? (
                <div className="nvflare-job-summary-block-06">
                    <SummaryField label="Data source group" value={datasourceDetails.groupName || "--"} />
                </div>
            ) : null}

            <div
                className="nvflare-job-summary-block-07"
            >
                <div style={labelStyle}>Data source (You)</div>
                {datasourceDetails.href ? (
                    <a
                        target="_blank"
                        rel="noreferrer"
                        href={datasourceDetails.href}
                        className="nvflare-job-summary-a"
                    >
                        {datasourceDetails.source}
                    </a>
                ) : (
                    <div style={{ ...valueStyle, overflowWrap: "anywhere", wordBreak: "break-word" }}>
                        {datasourceDetails.source}
                    </div>
                )}
            </div>
        </div>
    );
}

const NVFlareJobSummary: React.FC<NVFlareJobSummaryProps> = ({
    nvflareJob,
    boldBorder = false,
    defaultOpen = true,
    isOpen,
    onToggle,
    enableFunctionLinks = false,
}) => {
    if (!nvflareJob) {
        return <></>;
    }

    const nonContributingClients = parseCsvList(nvflareJob.non_contributing_clients);
    const excludedAnalyzingClients = parseCsvList(nvflareJob.exclude_analyzing_clients);
    const hasPartySettings = nonContributingClients.length > 0 || excludedAnalyzingClients.length > 0;
    const threshold = nvflareJob.threshold;

    return (
        <AbstractAccordion
            as="section"
            title="Job Summary"
            titleTooltip="Show/Hide NVFlare Job Overview"
            defaultOpen={defaultOpen}
            isOpen={isOpen}
            onToggle={onToggle}
            containerStyle={{ maxWidth: "100%" }}
            bodyStyle={{
                fontSize: "13px",
                border: boldBorder ? "1px solid black" : "1px solid #ccc",
                borderRadius: boldBorder ? "0" : "4px",
                padding: "0 0.65rem .3rem 0.8rem",
                backgroundColor: "white",
                maxWidth: "100%",
            }}
        >
            <>
                <SummarySection title="Job Details">
                    {/* <SummaryField label="Internal Job ID" value={nvflareJob.id} />
                    <SummaryField label="NVFlare Assigned ID" value={nvflareJob.nvflare_assigned_id} />
                    <SummaryField label="Project ID" value={nvflareJob.project_id} />
                    <SummaryField label="Filter ID" value={nvflareJob.filter_id} /> */}
                    <SummaryField label="Status" value={nvflareJob.status} />
                    <SummaryField label="Run Duration" value={formatRunDuration(nvflareJob.run_duration)} />
                    <SummaryField label="Submit Time" value={formatDateTime(nvflareJob.submit_time)} />
                    <SummaryField label="Created" value={formatDateTime(nvflareJob.create_date)} />
                    <SummaryField label="Updated" value={formatDateTime(nvflareJob.update_date)} />
                </SummarySection>

                <SummarySection title="Data Source">
                    <DatasourceSummary job={nvflareJob} />
                </SummarySection>

                {threshold && (
                    <SummarySection title="Threshold Comparison">
                        <SummaryField label="Method" value={formatThresholdMethod(threshold.method)} />
                        <SummaryField label="Minimum sample count" value={threshold.threshold} />
                    </SummarySection>
                )}

                {hasPartySettings && (
                    <SummarySection title="Party Participation Settings">
                        <PartyList title="Excluded from Contributing" clients={nonContributingClients} />
                        <PartyList title="Excluded from Analyzing" clients={excludedAnalyzingClients} />
                    </SummarySection>
                )}

                <SummarySection title="Functions">
                    {(nvflareJob.functions || []).length ? (
                        enableFunctionLinks ? (
                            <FunctionButtons functions={nvflareJob.functions || []} />
                        ) : (
                            <SummaryField label="Functions" value={nvflareJob.functions} />
                        )
                    ) : (
                        <div style={emptyValueStyle}>No function information was returned.</div>
                    )}
                </SummarySection>
            </>
        </AbstractAccordion>
    );
};

export default NVFlareJobSummary;
