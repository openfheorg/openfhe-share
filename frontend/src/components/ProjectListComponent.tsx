import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AppScreen } from "../App";
import {
  API_BASE,
  API_LANDING_PROJECT,
  API_PROJECTS_LIST,
  description_nvflare_manager
} from "../constants/Constants";
import { Project } from "../types/Project";
import { NVFlareJob } from "../types/JobsDataTypes";
import {
  LandingProjectFunctionUsage,
  LandingProjectResponse,
  LandingProjectSummary
} from "../types/LandingPage";
import {
  FUNCTION_ENUM_TO_ID,
  FUNCTION_METADATA
} from "./FunctionSelector";
import CompactBanner from "./CompactBanner";
import {
  FilterSchema,
  FilterType
} from "../features/job_runner/utils/FilterPayloadConfigUtils";
import { UserRole, useUserRole } from "../context/UserRoleContext";
import NVFlareManagerContent from "../features/nvflare_manager/components/NVFlareManagerContent";
import JobHistoryMain, { BLANK_FILTER_CONFIG } from "../features/job_history/JobHistoryMain";
import JobRunnerMain, { JobRunnerMainHandle } from "../features/job_runner/JobRunnerMain";
import ResultsPage from "../features/job_history/pages/ResultsPage";
import NavigationSelector from "../pages/NavigationSelector";
import SHAREHomeDashboard from "./SHAREHomeDashboard";
import UserSettingsPage from "../pages/UserSettingsPage";
import ProjectSettingsPage from "../pages/ProjectSettingsPage";

interface ProjectListComponentProps {
  initialProjectId?: number | null;
  activeScreen?: AppScreen;
  jobHistoryReloadKey?: number;
  userSettingsReloadKey?: number;
  onOpenHome?: () => void;
  onOpenProject?: (project: Project) => void;
  onRunAnalysis?: (project: Project) => void;
  onViewJobHistory?: (project: Project) => void;
  onOpenProjectSettings?: (project: Project) => void;
  onViewJobResults?: (project: Project, nvflareJobId: string) => void;
  resultsJobId?: string | null;
  projectsNavOpen?: boolean;
  onProjectsNavOpenChange?: (open: boolean) => void;
  onResultsContextLoaded?: (project: Project) => void;
  onLeaveResults?: () => void;
  onOpenNVFlareManager?: () => void;
  onOpenUserSettings?: () => void;
  compact?: boolean;
  onStateChange?: (state: { projects: Project[]; loading: boolean; error: string }) => void;
}

interface ProjectLandingState {
  loading: boolean;
  error: string;
  project: LandingProjectSummary | null;
  jobs: NVFlareJob[];
  functionUsageDistribution: LandingProjectFunctionUsage[];
}

interface FunctionUsageSegment {
  label: string;
  count: number;
  color: string;
}

const FUNCTION_USAGE_COLORS = [
  "#3F5FFF",
  "#32ab70",
  "#8d6f82",
  "#8b7655",
  "#637f86",
  "#6b78b8",
  "#9a6a58",
  "#6e7d60"
];

const FILTER_SCHEMA_PATHS: Array<{ filterType: FilterType; path: string }> = [
  { filterType: "PATIENT_QUERY", path: "patient/patient_query.json" },
  { filterType: "PATIENT_DATA", path: "patient/patient_data.json" },
  { filterType: "OBSERVATION", path: "observation/observation_filters.json" },
  { filterType: "OBSERVATION_QUERY", path: "observation/observation_query.json" },
  { filterType: "OBSERVATION_DATA", path: "observation/observation_data.json" }
];

async function hydrateProjectFilterSchemas(project: Omit<Project, "filter_schemas">): Promise<Project> {
  const filterSystem = String(project.filter_system || "DEFAULT").trim().toLowerCase();
  const schemaEntries = await Promise.all(
    FILTER_SCHEMA_PATHS.map(async ({ filterType, path }) => {
      try {
        const response = await fetch(`/filters/${filterSystem}/${path}`);
        if (!response.ok) {
          return [filterType, undefined] as const;
        }
        const schema = (await response.json()) as FilterSchema;
        return [filterType, schema] as const;
      } catch {
        return [filterType, undefined] as const;
      }
    })
  );

  const filter_schemas = schemaEntries.reduce((acc, [filterType, schema]) => {
    if (schema) {
      acc[filterType] = schema;
    }
    return acc;
  }, {} as Partial<Record<FilterType, FilterSchema>>);

  return {
    ...project,
    filter_schemas
  };
}

function getFunctionMetadata(functionName: string) {
  const normalized = String(functionName || "").trim();
  const metadataId =
    FUNCTION_ENUM_TO_ID[normalized.toUpperCase()] || normalized.toLowerCase();

  return FUNCTION_METADATA.find((fn) => fn.id === metadataId);
}

function humanizeFunctionName(functionName: string): string {
  const metadata = getFunctionMetadata(functionName);
  if (metadata) return metadata.title;

  return String(functionName || "")
    .trim()
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}


function statusClassName(status?: string | null): string {
  const upper = String(status || "").toUpperCase();
  // A partial run did not deliver everything it was asked for, so it reads as a failure even
  // though its results are still viewable.
  if (upper.includes("PARTIAL")) return "failure";
  if (upper.includes("COMPLETED") || upper === "DONE") return "success";
  if (upper.includes("FAIL") || upper.includes("ABORT") || upper.includes("CANCEL")) return "failure";
  if (upper.includes("RUN") || upper.includes("SUBMIT") || upper.includes("START")) return "running";
  return "neutral";
}

function canViewResults(job: NVFlareJob): boolean {
  const status = String(job.status || "").toUpperCase();
  return Boolean(
    job.nvflare_assigned_id &&
      // A partial run's results are incomplete but still worth opening.
      (status.includes("COMPLETED") || status.includes("PARTIAL") || status === "DONE")
  );
}


function formatDateTime(value?: string | null): string {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${d.toLocaleString()} UTC`;
}

function getJobFunctionEntries(job: NVFlareJob) {
  const functionsMap = job.functions_map || {};
  const mappedNames = Object.keys(functionsMap);
  const names = mappedNames.length > 0
    ? mappedNames
    : Array.isArray(job.functions)
      ? job.functions
      : [];

  return names.map((functionName) => {
    const rawConfig = functionsMap[functionName];
    const configCount = Array.isArray(rawConfig)
      ? rawConfig.length
      : rawConfig && typeof rawConfig === "object"
        ? 1
        : 0;
    const metadata = getFunctionMetadata(functionName);

    return {
      functionName,
      metadata,
      title: metadata?.title || humanizeFunctionName(functionName),
      configCount
    };
  });
}

function getRecentJobKey(job: NVFlareJob): string {
  return job.job_runner_id || job.nvflare_assigned_id || String(job.id);
}

const FunctionUsageDonut: React.FC<{ segments: FunctionUsageSegment[] }> = ({ segments }) => {
  const total = segments.reduce((sum, segment) => sum + segment.count, 0);
  let cursor = 0;
  const gradientStops = segments.map((segment) => {
    const start = cursor;
    const span = total > 0 ? (segment.count / total) * 100 : 0;
    cursor += span;
    return `${segment.color} ${start}% ${cursor}%`;
  });
  const donutBackground = gradientStops.length > 0
    ? `conic-gradient(${gradientStops.join(", ")})`
    : "#e5e7eb";
  const ariaSummary = segments
    .map((segment) => {
      const percentage = total > 0 ? Math.round((segment.count / total) * 100) : 0;
      return `${segment.label} ${percentage}%`;
    })
    .join(", ");

  return (
    <div className="project-function-usage-content">
      <div
        className="home-donut-chart"
        style={{ background: donutBackground }}
        role="img"
        aria-label={`Analysis Function Distribution: ${ariaSummary || "No data"}`}
      >
        <div className="home-donut-center">
          <strong>{total}</strong>
          <span>jobs</span>
        </div>
      </div>

      <div className="home-chart-legend">
        {segments.length > 0 ? segments.map((segment) => {
          const percentage = total > 0 ? Math.round((segment.count / total) * 100) : 0;
          return (
            <div className="home-chart-legend-row" key={segment.label}>
              <span className="home-chart-legend-label" title={segment.label}>
                <span
                  className="home-chart-legend-swatch"
                  style={{ backgroundColor: segment.color }}
                  aria-hidden="true"
                />
                <span className="project-function-usage-label-text">{segment.label}</span>
              </span>
              <span className="home-chart-legend-value">
                {segment.count} <span>({percentage}%)</span>
              </span>
            </div>
          );
        }) : (
          <div className="project-recent-jobs-message muted">
            No jobs have been run for this project yet.
          </div>
        )}
      </div>
    </div>
  );
};

const ProjectListComponent: React.FC<ProjectListComponentProps> = ({
  initialProjectId,
  activeScreen = "home",
  jobHistoryReloadKey = 0,
  userSettingsReloadKey = 0,
  onOpenHome,
  onOpenProject,
  onRunAnalysis,
  onViewJobHistory,
  onOpenProjectSettings,
  onViewJobResults,
  resultsJobId,
  projectsNavOpen = true,
  onProjectsNavOpenChange,
  onResultsContextLoaded,
  onLeaveResults,
  onOpenNVFlareManager,
  onOpenUserSettings,
  compact = false,
  onStateChange
}) => {
  const role = useUserRole();
  const canRunAnalysis = role === UserRole.INITIATOR;
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [landingByProjectId, setLandingByProjectId] = useState<Record<number, ProjectLandingState>>({});
  const [expandedRecentJobId, setExpandedRecentJobId] = useState<string | null>(null);
  const jobRunnerRef = useRef<JobRunnerMainHandle | null>(null);

  const fetchProjects = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}${API_PROJECTS_LIST}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error || "Failed to load projects");
        return;
      }

      const data = await res.json();
      if (data && Array.isArray(data.projects)) {
        const hydratedProjects = await Promise.all(
          data.projects.map((project: Omit<Project, "filter_schemas">) => hydrateProjectFilterSchemas(project))
        );
        setProjects(hydratedProjects);
      } else {
        setError("Invalid response from server");
      }
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchProjectLanding = useCallback(async (projectId: number): Promise<ProjectLandingState> => {
    try {
      const res = await fetch(`${API_BASE}${API_LANDING_PROJECT}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId })
      });

      const data = (await res.json().catch(() => ({}))) as LandingProjectResponse;
      if (!res.ok || data.status !== "SUCCESS" || !data.project) {
        throw new Error(data.error || `Failed to load project landing data (${res.status})`);
      }

      return {
        loading: false,
        error: "",
        project: data.project,
        jobs: Array.isArray(data.recent_jobs) ? data.recent_jobs : [],
        functionUsageDistribution: Array.isArray(data.function_usage_distribution)
          ? data.function_usage_distribution
          : []
      };
    } catch (caughtError) {
      console.error(`Failed to load project landing data for project ${projectId}:`, caughtError);
      return {
        loading: false,
        error: "Unable to load project landing data",
        project: null,
        jobs: [],
        functionUsageDistribution: []
      };
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    onStateChange?.({ projects, loading, error });
  }, [projects, loading, error, onStateChange]);

  useEffect(() => {
    if (projects.length === 0) {
      setSelectedProjectId(null);
      return;
    }

    setSelectedProjectId((currentProjectId) => {
      if (initialProjectId != null && projects.some((project) => project.id === initialProjectId)) {
        return initialProjectId;
      }
      if (activeScreen === "job_results") {
        return null;
      }
      if (activeScreen === "home" && initialProjectId == null) {
        return null;
      }
      if (currentProjectId && projects.some((project) => project.id === currentProjectId)) {
        return currentProjectId;
      }
      return projects[0].id;
    });
  }, [projects, initialProjectId, activeScreen]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || null,
    [projects, selectedProjectId]
  );

  useEffect(() => {
    setExpandedRecentJobId(null);
  }, [selectedProjectId]);

  useEffect(() => {
    if (compact || activeScreen !== "home" || !selectedProject) return;

    let cancelled = false;
    const projectId = selectedProject.id;

    setLandingByProjectId((prev) => ({
      ...prev,
      [projectId]: {
        loading: true,
        error: "",
        project: prev[projectId]?.project || null,
        jobs: prev[projectId]?.jobs || [],
        functionUsageDistribution: prev[projectId]?.functionUsageDistribution || []
      }
    }));

    void fetchProjectLanding(projectId).then((landingState) => {
      if (cancelled) return;
      setLandingByProjectId((prev) => ({
        ...prev,
        [projectId]: landingState
      }));
    });

    return () => {
      cancelled = true;
    };
  }, [compact, activeScreen, selectedProject, fetchProjectLanding]);

  const refreshAll = useCallback(async () => {
    // Keep the current landing payload visible while project metadata and the
    // selected project's summary are revalidated.
    await fetchProjects();
  }, [fetchProjects]);

  const fixedCount = useMemo(
    () => projects.reduce((acc, p) => acc + (p?.fixed === true ? 1 : 0), 0),
    [projects]
  );

  const handleResultsContextLoaded = useCallback((resolvedProject: Project) => {
    setSelectedProjectId((currentProjectId) =>
      currentProjectId === resolvedProject.id ? currentProjectId : resolvedProject.id
    );
    onResultsContextLoaded?.(resolvedProject);
  }, [onResultsContextLoaded]);

  const handleEmbeddedScreenChange = useCallback((nextScreen: AppScreen) => {
    if (nextScreen === "home") {
      if (selectedProject) onOpenProject?.(selectedProject);
      return;
    }

    if (nextScreen === "job_history") {
      if (selectedProject) onViewJobHistory?.(selectedProject);
      return;
    }

    if (nextScreen === "job_runner") {
      if (selectedProject && canRunAnalysis) onRunAnalysis?.(selectedProject);
      return;
    }

    if (nextScreen === "project_settings") {
      if (selectedProject) onOpenProjectSettings?.(selectedProject);
      return;
    }

    if (nextScreen === "nvflare_manager") {
      onOpenNVFlareManager?.();
      return;
    }

    if (nextScreen === "user_settings") {
      onOpenUserSettings?.();
    }
  }, [selectedProject, onOpenProject, onViewJobHistory, onRunAnalysis, onOpenProjectSettings, onOpenNVFlareManager, onOpenUserSettings, canRunAnalysis]);

  if (compact) {
    return (
      <CompactBanner>
        <div>
          <div className="duality-weight-600-mb-0p25rem">Projects</div>
          <hr className="duality-m-0-0-0p4rem-0" />
          <div className="duality-d-flex-justify-space-between-mb-0p15rem">
            <span>Total Registered:</span>
            <span className="duality-weight-600-text-3f5fff-text-right">{projects.length}</span>
          </div>
          <div className="duality-d-flex-justify-space-between-mb-0p15rem">
            <span>Fixed: </span>
            <span className="project-list-component-block-01">
              {fixedCount}
            </span>
          </div>
        </div>
      </CompactBanner>
    );
  }

  const landingState = selectedProject ? landingByProjectId[selectedProject.id] : undefined;
  const landingProject = landingState?.project || null;
  const recentJobs = landingState?.jobs || [];
  const functionUsageDistribution = landingState?.functionUsageDistribution || [];
  const functionUsageSegments: FunctionUsageSegment[] = functionUsageDistribution.map((entry, index) => ({
    label: entry.functions.map(humanizeFunctionName).join(" + "),
    count: entry.count,
    color: FUNCTION_USAGE_COLORS[index % FUNCTION_USAGE_COLORS.length]
  }));
  const landingFunctions = landingProject?.functions || selectedProject?.functions || [];
  const projectFunctionEntries = landingFunctions
    .map((fn) => ({
      capability: fn,
      metadata: getFunctionMetadata(fn.function)
    }))
    .filter((entry) => Boolean(entry.metadata))
    // Encrypted Filtering stays a backend capability of the project but is not
    // shown as a card until it becomes directly runnable.
    .filter((entry) => entry.metadata?.id !== "encrypted_filtering");
  const supportedFunctions = [
    ...projectFunctionEntries.filter((entry) => !entry.metadata?.disabled),
    ...projectFunctionEntries.filter((entry) => entry.metadata?.disabled)
  ];
  const activeSupportedFunctionCount = supportedFunctions.filter(
    (entry) => !entry.metadata?.disabled
  ).length;
  const registeredUserCount = landingProject && typeof landingProject.registered_user_count === "number"
    ? landingProject.registered_user_count
    : selectedProject && typeof selectedProject.registered_user_count === "number"
      ? selectedProject.registered_user_count
      : null;
  const hasNoProjectJobs = Boolean(
    landingProject &&
    !landingState?.loading &&
    !landingState?.error &&
    landingProject.total_jobs === 0
  );

  const stats = selectedProject
    ? [
        registeredUserCount !== null
          ? { label: "Registered Users", value: registeredUserCount }
          : null,
        {
          label: "Jobs Run",
          value: landingProject?.total_jobs
            ?? (landingState?.error ? "—" : "…")
        },
        { label: "Supported Analyses", value: activeSupportedFunctionCount }
      ].filter(Boolean) as Array<{ label: string; value: React.ReactNode }>
    : [];

  return (
    <>
      {loading && projects.length === 0 && (
        <div className="projects-home-loading">Loading analysis projects...</div>
      )}

      {projects.length === 0 && !loading && error && (
        <div className="projects-home-load-error">{error}</div>
      )}

      {projects.length > 0 && (
        <div className="project-workspace-shell">
          <NavigationSelector
            projects={projects}
            selectedProjectId={selectedProjectId}
            selectedScreen={activeScreen}
            onSelectHome={() => {
              setSelectedProjectId(null);
              onOpenHome?.();
            }}
            onSelectProject={(project) => {
              setSelectedProjectId(project.id);
              onOpenProject?.(project);
            }}
            onSelectJobHistory={(project) => {
              setSelectedProjectId(project.id);
              onViewJobHistory?.(project);
            }}
            onSelectJobRunner={(project) => {
              setSelectedProjectId(project.id);
              if (!canRunAnalysis) return;

              if (activeScreen === "job_runner" && selectedProjectId === project.id) {
                jobRunnerRef.current?.handleRunNewAnalysisNavigation();
                return;
              }

              onRunAnalysis?.(project);
            }}
            onSelectProjectSettings={(project) => {
              setSelectedProjectId(project.id);
              onOpenProjectSettings?.(project);
            }}
            onSelectNVFlareManager={() => onOpenNVFlareManager?.()}
            onSelectUserSettings={() => onOpenUserSettings?.()}
            projectsOpen={projectsNavOpen}
            onProjectsOpenChange={(open) => onProjectsNavOpenChange?.(open)}
          />

          {activeScreen === "home" && !selectedProject ? (
            <SHAREHomeDashboard />
          ) : activeScreen === "nvflare_manager" && role === UserRole.INITIATOR ? (
            <section className="project-workspace-panel landing-manager-panel" aria-labelledby="nvflare-manager-home-title">
              <div className="project-overview-header landing-manager-header">
                <div className="project-overview-title-group">
                  <div className="project-overview-icon-wrap">
                    <img
                      src="/icons/nav_icon_nvflare_manager.png"
                      alt="NVFlare Manager icon"
                      className="project-overview-icon"
                    />
                  </div>
                  <div className="project-overview-heading-copy">
                    <div className="project-overview-heading-line">
                      <h2 id="nvflare-manager-home-title">NVFlare Manager</h2>
                    </div>
                    <p>{description_nvflare_manager}</p>
                  </div>
                </div>
              </div>
              <div className="project-overview-section landing-manager-content">
                <NVFlareManagerContent embedded showBorder={false} />
              </div>
            </section>
          ) : activeScreen === "user_settings" ? (
            <UserSettingsPage
              key={`user-settings:${userSettingsReloadKey}`}
              setMainScreen={handleEmbeddedScreenChange}
              initialProjectId={selectedProject?.id ?? null}
              returnScreen="home"
            />
          ) : activeScreen === "job_results" && resultsJobId ? (
            <section className="project-workspace-tool-panel project-workspace-results-panel" aria-label="Job results">
              <ResultsPage
                key={`landing-results:${resultsJobId}`}
                nvflareJobId={resultsJobId}
                submittedFilterSet={BLANK_FILTER_CONFIG}
                submittedFilterSetName=""
                viewOnly
                directEntry
                onContextLoaded={handleResultsContextLoaded}
                onBack={() => onLeaveResults?.()}
                onStartOver={() => onLeaveResults?.()}
                onBackToHistory={() => onLeaveResults?.()}
              />
            </section>
          ) : activeScreen === "project_settings" && selectedProject ? (
            <section className="project-workspace-tool-panel project-settings-workspace-panel" aria-label={`${selectedProject.name} project configuration`}>
              <ProjectSettingsPage project={selectedProject} />
            </section>
          ) : activeScreen === "job_history" && selectedProject ? (
            <section className="project-workspace-tool-panel" aria-label={`${selectedProject.name} analysis history`}>
              <JobHistoryMain
                key={`job-history:${selectedProject.id}:${jobHistoryReloadKey}`}
                project={selectedProject}
                setMainScreen={handleEmbeddedScreenChange}
              />
            </section>
          ) : activeScreen === "job_runner" && selectedProject && canRunAnalysis ? (
            <section className="project-workspace-tool-panel job-runner-workspace-panel" aria-label={`${selectedProject.name} analysis runner`}>
              <JobRunnerMain
                ref={jobRunnerRef}
                key={`job-runner:${selectedProject.id}`}
                project={selectedProject}
                setMainScreen={handleEmbeddedScreenChange}
              />
            </section>
          ) : selectedProject ? (
          <section
            key={`project-panel-${selectedProject.id}`}
            id={`project-panel-${selectedProject.id}`}
            className="project-workspace-panel project-overview-animate"
            aria-labelledby={`project-tab-${selectedProject.id}`}
          >
            <div className="project-overview-header">
              <div className="project-overview-title-group">
                <div className="project-overview-icon-wrap">
                  <img
                    src={`/icons/projects/${selectedProject.id}/icon.png`}
                    alt={`${selectedProject.name} icon`}
                    className="project-overview-icon"
                  />
                </div>

                <div className="project-overview-heading-copy">
                  <div className="project-overview-heading-line">
                    <h2>{landingProject?.name ?? selectedProject.name}</h2>
                    <div className="project-overview-heading-actions">
                      <span
                        className={`project-status-badge ${String(landingProject?.status ?? selectedProject.status ?? "").toLowerCase() === "active" ? "active" : "inactive"}`}
                      >
                        {landingProject?.status ?? selectedProject.status ?? "UNKNOWN"}
                        {(landingProject?.fixed ?? selectedProject.fixed) ? " · Fixed" : ""}
                      </span>
                      <button
                        type="button"
                        className="projects-home-refresh-button"
                        onClick={refreshAll}
                        disabled={loading}
                        aria-label="Refresh project list"
                        title="Refresh project list"
                      >
                        {loading ? "…" : "⟳"}
                      </button>
                    </div>
                  </div>
                  {(landingProject?.description ?? selectedProject.description) ? (
                    <p>{landingProject?.description ?? selectedProject.description}</p>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="project-overview-stats" aria-label="Project statistics">
              {stats.map((stat) => (
                <div className="project-stat" key={stat.label}>
                  <span className="project-stat-value">{stat.value}</span>
                  <span className="project-stat-label">{stat.label}</span>
                </div>
              ))}
            </div>

            <div className="project-overview-section project-static-section">
              <div className="project-static-section-heading-row">
                <div className="project-static-section-heading">
                  <div>
                    <h3>Supported Analyses</h3>
                    <p>A single job may include one or more of these functions.</p>
                  </div>
                </div>
                {canRunAnalysis && onRunAnalysis ? (
                  <button
                    type="button"
                    className="project-action-button project-action-primary project-section-action"
                    onClick={() => onRunAnalysis(selectedProject)}
                  >
                    <span>Run New Analysis</span>
                  </button>
                ) : null}
              </div>

              <div className="project-function-grid">
                {supportedFunctions.map(({ capability, metadata }) => {
                  if (!metadata) return null;
                  return (
                    <div
                      className={`project-function-tile ${metadata.disabled ? "project-function-tile-disabled" : ""}`}
                      key={capability.function}
                    >
                      {metadata.icon ? (
                        <img src={`/icons${metadata.icon}`} alt="" aria-hidden="true" />
                      ) : null}
                      <div>
                        <div className="project-function-name">{metadata.title}</div>
                        <div className="project-function-description">
                          {metadata.disabled ? `Coming soon. ${metadata.description}` : metadata.description}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {hasNoProjectJobs ? (
              <div className="project-overview-section project-job-activity-empty-section">
                <div className="project-job-activity-empty">
                  <div className="project-job-activity-empty-copy">
                    <img src="/icons/nav_icon_job_history.png" alt="" aria-hidden="true" />
                    <div>
                      <h3>No job activity yet</h3>
                      <p>Analysis function distribution and recent job activity will appear here after this project runs its first job.</p>
                    </div>
                  </div>
                  {canRunAnalysis && onRunAnalysis ? (
                    <button
                      type="button"
                      className="project-action-button project-action-primary project-job-activity-empty-action"
                      onClick={() => onRunAnalysis(selectedProject)}
                    >
                      <span>Run New Analysis</span>
                    </button>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="project-overview-section project-activity-section">
                <div className="project-activity-grid">
                  <div className="project-activity-card project-function-usage-card">
                    <div className="project-static-section-heading">
                      <img src="/icons/nav_icon_job_history.png" alt="" aria-hidden="true" />
                      <div>
                        <h3>Analysis Function Distribution</h3>
                        <p>Exact analysis function or function combination used by each job.</p>
                      </div>
                    </div>

                    {functionUsageSegments.length > 0 ? (
                      <FunctionUsageDonut segments={functionUsageSegments} />
                    ) : landingState?.loading ? (
                      <div className="project-recent-jobs-message muted">Loading function usage…</div>
                    ) : landingState?.error ? (
                      <div className="project-recent-jobs-message muted">
                        Function usage is temporarily unavailable.
                      </div>
                    ) : (landingProject?.total_jobs || 0) === 0 ? (
                      <div className="project-recent-jobs-message muted">
                        No jobs have been run for this project yet.
                      </div>
                    ) : (
                      <div className="project-recent-jobs-message muted">
                        No function usage data is available for these jobs.
                      </div>
                    )}
                  </div>

                  <div className="project-recent-jobs-section">
                    <div className="project-static-section-heading-row project-recent-jobs-heading-row">
                      <div className="project-static-section-heading">
                        <img src="/icons/nav_icon_job_history.png" alt="" aria-hidden="true" />
                        <div>
                          <h3>Recent Jobs</h3>
                          <p>The five most recently created jobs for this project.</p>
                        </div>
                      </div>
                      {onViewJobHistory ? (
                        <button
                          type="button"
                          className="project-action-button secondary-button project-jobs-history-button"
                          onClick={() => onViewJobHistory(selectedProject)}
                        >
                          <span>View Analysis History</span>
                        </button>
                      ) : null}
                    </div>

                    {landingState?.error && recentJobs.length === 0 ? (
                      <div className="project-recent-jobs-message muted">
                        Recent job activity is temporarily unavailable.
                      </div>
                    ) : recentJobs.length === 0 && landingState && !landingState.loading ? (
                      <div className="project-recent-jobs-message muted">
                        No jobs have been run for this project yet.
                      </div>
                    ) : recentJobs.length === 0 ? null : (
                      <div className="project-recent-jobs-table-wrap">
                        <table className="project-recent-jobs-table">
                          <thead>
                            <tr>
                              <th>Function(s)</th>
                              <th>Status</th>
                              <th aria-label="View results" />
                            </tr>
                          </thead>
                          <tbody>
                            {recentJobs.map((job) => {
                              const jobKey = getRecentJobKey(job);
                              const isExpanded = expandedRecentJobId === jobKey;
                              const jobFunctions = getJobFunctionEntries(job);
                              const resultAvailable = canViewResults(job);
                              const functionSummary = jobFunctions.length > 0
                                ? jobFunctions
                                    .map((entry) => entry.configCount > 1 ? `${entry.title} (${entry.configCount})` : entry.title)
                                    .join(", ")
                                : "Functions unavailable";

                              return (
                                <React.Fragment key={`${selectedProject.id}:${jobKey}`}>
                                  <tr
                                    className={`project-recent-job-row ${isExpanded ? "expanded" : ""}`}
                                    tabIndex={0}
                                    aria-expanded={isExpanded}
                                    onClick={() => setExpandedRecentJobId(isExpanded ? null : jobKey)}
                                    onKeyDown={(event) => {
                                      if (event.key === "Enter" || event.key === " ") {
                                        event.preventDefault();
                                        setExpandedRecentJobId(isExpanded ? null : jobKey);
                                      }
                                    }}
                                  >
                                    <td className="project-recent-job-cell project-recent-job-functions-cell" title={functionSummary}>
                                      <span className="project-job-chevron" aria-hidden="true">
                                        {isExpanded ? "▾" : "▸"}
                                      </span>
                                      <span>{functionSummary}</span>
                                    </td>
                                    <td className="project-recent-job-cell">
                                      <span className={`project-job-status ${statusClassName(job.status)}`}>
                                        {job.status || "UNKNOWN"}
                                      </span>
                                    </td>
                                    <td className="project-recent-job-cell project-recent-job-action-cell">
                                      {resultAvailable && onViewJobResults && job.nvflare_assigned_id ? (
                                        <button
                                          type="button"
                                          className="project-results-chevron-button"
                                          aria-label={`View results for job ${job.id}`}
                                          title="View Results"
                                          onClick={(event) => {
                                            event.stopPropagation();
                                            onViewJobResults(selectedProject, job.nvflare_assigned_id as string);
                                          }}
                                        >
                                          ›
                                        </button>
                                      ) : null}
                                    </td>
                                  </tr>

                                  {isExpanded ? (
                                    <tr className="project-recent-job-detail-row">
                                      <td colSpan={3}>
                                        <div className="project-recent-job-detail">
                                          <div className="project-recent-job-detail-grid">
                                            <div>
                                              <span>Job ID</span>
                                              <strong>{job.id}</strong>
                                            </div>
                                            <div>
                                              <span>Total Runtime Duration</span>
                                              <strong>{job.run_duration || "--"}</strong>
                                            </div>
                                            <div>
                                              <span>Created</span>
                                              <strong>{formatDateTime(job.create_date)}</strong>
                                            </div>
                                          </div>

                                          <div className="project-recent-job-detail-functions">
                                            <div className="project-recent-job-detail-label">Functions Included</div>
                                            <div className="project-recent-job-function-meta-list">
                                              {jobFunctions.length > 0 ? (
                                                jobFunctions.map((entry) => (
                                                  <span
                                                    className="project-job-function-meta"
                                                    key={`${job.id}:${entry.functionName}`}
                                                    title={entry.metadata?.description || entry.title}
                                                  >
                                                    {entry.metadata?.icon ? (
                                                      <img src={`/icons${entry.metadata.icon}`} alt="" aria-hidden="true" />
                                                    ) : null}
                                                    <span>
                                                      {entry.title}
                                                      {entry.configCount > 1 ? ` (${entry.configCount})` : ""}
                                                    </span>
                                                  </span>
                                                ))
                                              ) : (
                                                <span className="project-recent-job-no-functions">Functions unavailable</span>
                                              )}
                                            </div>
                                          </div>

                                          {resultAvailable && onViewJobResults && job.nvflare_assigned_id ? (
                                            <div className="project-recent-job-detail-action">
                                              <button
                                                type="button"
                                                className="project-link-button project-view-results-button"
                                                onClick={(event) => {
                                                  event.stopPropagation();
                                                  onViewJobResults(selectedProject, job.nvflare_assigned_id as string);
                                                }}
                                              >
                                                <img
                                                  src="/icons/nav_icon_job_results.png"
                                                  alt=""
                                                  aria-hidden="true"
                                                />
                                                <span>View Results</span>
                                              </button>
                                            </div>
                                          ) : null}
                                        </div>
                                      </td>
                                    </tr>
                                  ) : null}
                                </React.Fragment>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>

            )}
          </section>
          ) : null}
        </div>
      )}

    </>
  );
};

export default ProjectListComponent;
