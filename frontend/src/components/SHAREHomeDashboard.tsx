import React, { useCallback, useEffect, useMemo, useState } from "react";
import AbstractAccordion from "./AbstractAccordion";
import { HelpToggle, HelpPanel } from "./HelpToggle";
import { FUNCTION_ENUM_TO_ID, FUNCTION_METADATA } from "./FunctionSelector";
import { useUserSession } from "../context/UserRoleContext";
import {
  API_BASE,
  API_LANDING_HOME
} from "../constants/Constants";
import {
  LandingHomeResponse,
  LandingHomeSummary
} from "../types/LandingPage";

interface DashboardSegment {
  label: string;
  count: number;
  color: string;
  description?: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  "FINISHED:COMPLETED": "#32ab70",
  // Finished, but some requested computations produced no results: amber, not green.
  "FINISHED:PARTIAL": "#d9902b",
  PARTIAL: "#d9902b",
  COMPLETED: "#32ab70",
  DONE: "#32ab70",
  RUNNING: "#3F5FFF",
  SUBMITTED: "#3F5FFF",
  STARTED: "#3F5FFF",
  FAILED: "#c84b4b",
  FAILURE: "#c84b4b",
  ABORTED: "#8a909b",
  CANCELLED: "#8a909b",
  CANCELED: "#8a909b",
  UNKNOWN: "#1F2851"
};

const ROLE_COLORS: Record<string, string> = {
  CLIENT: "#32ab70",
  INITIATOR: "#3F5FFF",
  OBSERVER: "#8a909b",
  ADMIN: "#1F2851"
};

const FALLBACK_SEGMENT_COLORS = [
  "#6b78b8",
  "#7c8a65",
  "#8d6f82",
  "#8b7655",
  "#637f86"
];

// Functions surfaced on the Home page that are not yet directly callable from
// the rest of the platform, so the backend never reports them.
const HOME_ONLY_FUNCTIONS = [
  {
    id: "predict_risk_scores",
    title: "Predict and Classify Risk Scores",
    description: "Predict patient risk scores from pre-trained models and classify patients into risk groups.",
    icon: "/function_icon_RiskScore.png"
  }
];

// Keep the last successful Home payload per username so returning to Home never
// flashes an empty/loading state while the latest values are revalidated.  The
// cache must be user-scoped because the backend intentionally returns different
// Home fields for different roles.
const cachedHomeSummaries = new Map<string, LandingHomeSummary>();

function getFunctionMetadata(functionName: string) {
  const normalized = String(functionName || "").trim();
  const metadataId =
    FUNCTION_ENUM_TO_ID[normalized.toUpperCase()] || normalized.toLowerCase();

  return FUNCTION_METADATA.find((fn) => fn.id === metadataId);
}

function resolveSegmentColor(
  label: string,
  colorMap: Record<string, string>,
  index: number
): string {
  const upper = String(label || "UNKNOWN").trim().toUpperCase();
  if (colorMap[upper]) return colorMap[upper];

  if (upper.includes("COMPLETED")) return STATUS_COLORS.COMPLETED;
  if (upper.includes("RUN") || upper.includes("SUBMIT") || upper.includes("START")) {
    return STATUS_COLORS.RUNNING;
  }
  if (upper.includes("FAIL")) return STATUS_COLORS.FAILED;
  if (upper.includes("ABORT") || upper.includes("CANCEL")) return STATUS_COLORS.ABORTED;

  return FALLBACK_SEGMENT_COLORS[index % FALLBACK_SEGMENT_COLORS.length];
}

interface DonutChartProps {
  title: string;
  totalLabel: string;
  segments: DashboardSegment[];
  iconPath?: string;
}

const DonutChart: React.FC<DonutChartProps> = ({ title, totalLabel, segments, iconPath }) => {
  const [expandedInfoLabel, setExpandedInfoLabel] = useState<string | null>(null);
  const total = segments.reduce((sum, segment) => sum + segment.count, 0);
  let cursor = 0;
  const gradientStops = segments.map((segment) => {
    const start = cursor;
    const span = total > 0 ? (segment.count / total) * 100 : 0;
    cursor += span;
    return `${segment.color} ${start}% ${cursor}%`;
  });

  const ariaSummary = segments
    .map((segment) => {
      const percentage = total > 0 ? Math.round((segment.count / total) * 100) : 0;
      return `${segment.label} ${percentage}%`;
    })
    .join(", ");

  const donutBackground = gradientStops.length > 0
    ? `conic-gradient(${gradientStops.join(", ")})`
    : "#e5e7eb";

  return (
    <div className="home-chart-panel">
      <h3 className="home-chart-title">
        {iconPath ? <img src={iconPath} alt="" aria-hidden="true" /> : null}
        <span>{title}</span>
      </h3>
      <div className="home-chart-content">
        <div
          className="home-donut-chart"
          style={{ background: donutBackground }}
          role="img"
          aria-label={`${title}: ${ariaSummary || "No data"}`}
        >
          <div className="home-donut-center">
            <strong>{total}</strong>
            <span>{totalLabel}</span>
          </div>
        </div>

        <div className="home-chart-legend">
          {segments.length > 0 ? segments.map((segment) => {
            const percentage = total > 0 ? Math.round((segment.count / total) * 100) : 0;
            const infoExpanded = expandedInfoLabel === segment.label;
            return (
              <React.Fragment key={segment.label}>
                <div className="home-chart-legend-row">
                  <span className="home-chart-legend-label">
                    <span
                      className="home-chart-legend-swatch"
                      style={{ backgroundColor: segment.color }}
                      aria-hidden="true"
                    />
                    {segment.label}
                    {segment.description ? (
                      <HelpToggle
                        open={infoExpanded}
                        onToggle={() =>
                          setExpandedInfoLabel((current) =>
                            current === segment.label ? null : segment.label
                          )
                        }
                        ariaLabel={`Show help for ${segment.label}`}
                        title={`Show help for ${segment.label}`}
                      />
                    ) : null}
                  </span>
                  <span className="home-chart-legend-value">
                    {segment.count} <span>({percentage}%)</span>
                  </span>
                </div>
                {segment.description ? (
                  <HelpPanel open={infoExpanded} text={segment.description} />
                ) : null}
              </React.Fragment>
            );
          }) : (
            <div className="project-recent-jobs-message muted">No data available.</div>
          )}
        </div>
      </div>
    </div>
  );
};

const SHAREHomeDashboard: React.FC = () => {
  const { username, role } = useUserSession();
  const cacheKey = `${username}:${role}`;
  const cachedSummary = cachedHomeSummaries.get(cacheKey) || null;
  const [data, setData] = useState<LandingHomeSummary | null>(() => cachedSummary);
  const [loading, setLoading] = useState(() => cachedSummary === null);
  const [error, setError] = useState("");
  const [functionsOpen, setFunctionsOpen] = useState(true);

  const fetchHomeSummary = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_BASE}${API_LANDING_HOME}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username })
      });
      const payload = (await response.json().catch(() => ({}))) as LandingHomeResponse;

      if (!response.ok || payload.status !== "SUCCESS" || !payload.home) {
        throw new Error(payload.error || `Failed to load Home summary (${response.status})`);
      }

      cachedHomeSummaries.set(cacheKey, payload.home);
      setData(payload.home);
    } catch (caughtError) {
      console.error("Failed to load SHARE Home summary:", caughtError);
      setError("Unable to load SHARE system statistics.");
    } finally {
      setLoading(false);
    }
  }, [cacheKey, username]);

  useEffect(() => {
    const cached = cachedHomeSummaries.get(cacheKey) || null;
    setData(cached);
    setLoading(cached === null);
    void fetchHomeSummary();
  }, [cacheKey, fetchHomeSummary]);

  const supportedFunctions = useMemo(() => {
    if (!data) return [];

    return data.functions
      .map((backendFunction) => ({
        backendFunction,
        metadata: getFunctionMetadata(backendFunction.name)
      }))
      .filter((entry) => Boolean(entry.metadata) && !entry.metadata?.disabled);
  }, [data]);

  const jobStatusSegments = useMemo<DashboardSegment[]>(() => {
    return (data?.job_statuses || []).map((entry, index) => ({
      label: entry.status,
      count: entry.count,
      color: resolveSegmentColor(entry.status, STATUS_COLORS, index)
    }));
  }, [data]);

  const userRoleSegments = useMemo<DashboardSegment[]>(() => {
    return (data?.user_roles || []).map((entry, index) => ({
      label: entry.role,
      count: entry.count,
      color: resolveSegmentColor(entry.role, ROLE_COLORS, index),
      description: entry.description
    }));
  }, [data]);

  const showJobStatusChart = data?.job_statuses !== undefined;
  const showUserRoleChart = data?.user_roles !== undefined;
  const visibleChartCount = Number(showJobStatusChart) + Number(showUserRoleChart);

  return (
    <section className="project-workspace-panel home-dashboard-panel project-overview-animate" aria-labelledby="share-home-title">
      <div className="project-overview-header home-dashboard-header">
        <div className="project-overview-title-group">
          <div className="project-overview-icon-wrap">
            <img
              src="/icons/nav_icon_home.png"
              alt=""
              aria-hidden="true"
              className="project-overview-icon"
            />
          </div>

          <div className="project-overview-heading-copy">
            <div className="project-overview-heading-line">
              <h2 id="share-home-title">Welcome to SHARE</h2>
              <div className="project-overview-heading-actions">
                <button
                  type="button"
                  className="projects-home-refresh-button"
                  onClick={() => void fetchHomeSummary()}
                  disabled={loading}
                  aria-label="Refresh SHARE home statistics"
                  title="Refresh SHARE home statistics"
                >
                  {loading ? "…" : "⟳"}
                </button>
              </div>
            </div>
            <p>
              SHARE is a secure healthcare data collaboration platform for running federated analyses across encrypted data from participating organizations without revealing intermediate results. SHARE is built using the open-source fully homomorphic encryption library OpenFHE and the open-source federated learning framework NVIDIA Flare (NVFlare).
            </p>
            <p>
              Select a project from the left to review its capabilities and activity, open Analysis History, or launch a new analysis when your role permits. Global NVFlare operations are available from NVFlare Manager.
            </p>
          </div>
        </div>
      </div>

      <div className="project-overview-stats home-dashboard-stats" aria-label="SHARE system statistics">
        <div className="project-stat">
          <span className="project-stat-value">{loading && !data ? "…" : data?.total_jobs ?? "—"}</span>
          <span className="project-stat-label">Jobs Run</span>
        </div>
        <div className="project-stat">
          <span className="project-stat-value">
            {loading && !data ? "…" : supportedFunctions.length + HOME_ONLY_FUNCTIONS.length}
          </span>
          <span className="project-stat-label">Supported Functions</span>
        </div>
        {data?.total_users !== undefined ? (
          <div className="project-stat">
            <span className="project-stat-value">{data.total_users}</span>
            <span className="project-stat-label">Registered Users</span>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="project-recent-jobs-message muted">{error}</div>
      ) : null}

      {visibleChartCount > 0 ? (
        <div className="project-overview-section home-dashboard-chart-section">
          <div className={`home-dashboard-charts-grid ${visibleChartCount === 1 ? "single" : ""}`}>
            {showJobStatusChart ? (
              <DonutChart
                title="Job Status Distribution"
                totalLabel="jobs"
                segments={jobStatusSegments}
                iconPath="/icons/nav_icon_job_history.png"
              />
            ) : null}
            {showUserRoleChart ? (
              <DonutChart
                title="User Role Distribution"
                totalLabel="users"
                segments={userRoleSegments}
                iconPath="/icons/nav_icon_users_manager.png"
              />
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="project-overview-section home-functions-section">
        <AbstractAccordion
          isOpen={functionsOpen}
          onToggle={() => setFunctionsOpen((open) => !open)}
          headerClassName="home-functions-accordion-button"
          chevronMarginRight={8}
          title={
            <span className="home-functions-accordion-title">
              <img src="/icons/nav_icon_job_runner.png" alt="" aria-hidden="true" />
              <span>
                <strong>Supported Functions</strong>
                <small>Types of functions currently available across SHARE</small>
              </span>
            </span>
          }
          bodyClassName="home-functions-accordion-body"
        >
          <div className="project-function-grid home-function-grid">
            {supportedFunctions.map(({ backendFunction, metadata }) => {
              if (!metadata) return null;
              return (
                <div className="project-function-tile home-function-tile" key={backendFunction.id}>
                  {metadata.icon ? <img src={`/icons${metadata.icon}`} alt="" aria-hidden="true" /> : null}
                  <div>
                    <div className="project-function-name">{metadata.title}</div>
                    <div className="project-function-description">
                      {backendFunction.description || metadata.description}
                    </div>
                  </div>
                </div>
              );
            })}
            {HOME_ONLY_FUNCTIONS.map((fn) => (
              <div className="project-function-tile home-function-tile" key={fn.id}>
                <img src={`/icons${fn.icon}`} alt="" aria-hidden="true" />
                <div>
                  <div className="project-function-name">{fn.title}</div>
                  <div className="project-function-description">{fn.description}</div>
                </div>
              </div>
            ))}
          </div>
        </AbstractAccordion>
      </div>
    </section>
  );
};

export default SHAREHomeDashboard;
