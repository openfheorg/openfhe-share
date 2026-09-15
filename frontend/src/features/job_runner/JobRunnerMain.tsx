import React, { useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { AppScreen } from "../../App";
import HeaderTitle from "../../components/HeaderTitle";
import { description_job_runner } from "../../constants/Constants";
import { FunctionConfigs, ThresholdConfig } from "../../types/FunctionConfigs";
import { Medication } from "../../types/Medication";
import { Observation } from "../../types/Observation";
import { Patient } from "../../types/Patient";
import { Project } from "../../types/Project";
import ResultsPage from "../job_history/pages/ResultsPage";
import FilterScreenObservations from "./pages/filters/FilterScreenObservationsFHIR";
import FilterScreenPatients from "./pages/filters/FilterScreenPatients";
import FilterScreenPatientsJSON from "./pages/filters/default/FilterScreenPatientsJSON";
import FilterHistoryTable from "./pages/filters/FilterHistoryTable";
import FunctionSelectionPage from "./pages/FunctionSelectionPage";
import JobSubmissionPage from "./pages/JobSubmissionPage";
import { ProjectNameWithDescription } from "../../components/ProjectName";
import { FilterCollection } from "./utils/FilterPayloadConfigUtils";
import { JobLogData } from "../../types/JobsDataTypes";
import { useUserSession } from "../../context/UserRoleContext";
import WorkflowGroupSelectionPage from "./pages/WorkflowGroupSelectionPage";
import { loadGeneralStatisticsPreviewData } from "./utils/LocalBundlePreview";

type JobRunnerScreen =
  | "filterHistory"
  | "patientFilters"
  | "variantTable"
  | "workflow_groups"
  | "functionSelection"
  | "submit_function"
  | "results";

interface JobRunnerBrowserHistoryState {
  screen?: AppScreen;
  projectId?: number;
  jobRunnerStep?: JobRunnerScreen;
  jobRunnerTrail?: JobRunnerScreen[];
  jobRunnerProjectId?: number;
  jobRunnerDepth?: number;
}

const JOB_RUNNER_SCREENS: readonly JobRunnerScreen[] = [
  "filterHistory",
  "patientFilters",
  "variantTable",
  "workflow_groups",
  "functionSelection",
  "submit_function",
  "results"
] as const;

function isJobRunnerScreen(value: unknown): value is JobRunnerScreen {
  return typeof value === "string" && JOB_RUNNER_SCREENS.includes(value as JobRunnerScreen);
}

function readJobRunnerHistory(projectId: number): { screen: JobRunnerScreen; trail: JobRunnerScreen[]; depth: number } | null {
  if (typeof window === "undefined") return null;

  const state = (window.history.state || {}) as JobRunnerBrowserHistoryState;
  if (state.screen !== "job_runner" || state.projectId !== projectId || state.jobRunnerProjectId !== projectId) {
    return null;
  }

  const step = isJobRunnerScreen(state.jobRunnerStep) ? state.jobRunnerStep : null;
  const trail = Array.isArray(state.jobRunnerTrail)
    ? state.jobRunnerTrail.filter(isJobRunnerScreen)
    : [];

  if (!step) return null;
  const normalizedTrail = trail.length && trail[trail.length - 1] === step ? trail : [...trail, step];
  const depth = typeof state.jobRunnerDepth === "number" && Number.isFinite(state.jobRunnerDepth)
    ? Math.max(0, Math.floor(state.jobRunnerDepth))
    : Math.max(0, normalizedTrail.length - 1);
  return { screen: step, trail: normalizedTrail.length ? normalizedTrail : [step], depth };
}

interface ProjectWorkflowGroupOption {
  id?: number;
  option_key?: string;
  option_label?: string;
  option_value: string;
  option_order?: number;
}

interface ProjectWorkflowGroup {
  id?: number;
  group_key: string;
  group_label: string;
  group_description?: string | null;
  min_selected?: number | null;
  max_selected?: number | null;
  is_required?: boolean;
  page_order?: number;
  options: ProjectWorkflowGroupOption[];
}

interface WorkflowGroupSelection {
  group_key: string;
  selected_values: string[];
}

type WorkflowGroupData = Record<string, WorkflowGroupSelection>;

interface JobRunnerMainProps {
  setMainScreen: (screen: AppScreen) => void;
  project: Project;
}

export interface JobRunnerMainHandle {
  handleRunNewAnalysisNavigation: () => void;
}

export const BLANK_FILTER_CONFIG: FilterCollection = {
  patientQueryFilters: "{}",
  patientDataFilters: "{}",
  observationQueryFilters: "{}",
  observationDataFilters: "{}"
};

export const BLANK_JOB_DATA: JobLogData = {
  jobId: undefined,
  jobStatus: undefined,
  jobLog: [],
  referencedBy: [],
  run_duration: undefined
};

const CLEAR_JOB_STATES: readonly JobRunnerScreen[] = ["patientFilters", "variantTable", "functionSelection"] as const;

const DEFAULT_THRESHOLD_CONFIG: ThresholdConfig = {
  enabled: false,
  threshold: 10,
  thresholdMethod: "PROTECTED"
};

function safeParseJson<T = any>(s: string | null | undefined): T | null {
  if (!s) return null;
  const trimmed = String(s).trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed) as T;
  } catch {
    return null;
  }
}

function isMeaningfulJsonString(s: string | null | undefined): boolean {
  if (!s) return false;
  const trimmed = String(s).trim();
  if (!trimmed || trimmed === "{}" || trimmed === "null") return false;

  const parsed = safeParseJson<any>(trimmed);
  if (parsed == null) return false;

  if (Array.isArray(parsed)) return parsed.length > 0;
  if (typeof parsed === "object") return Object.keys(parsed).length > 0;
  if (typeof parsed === "string") return parsed.trim() !== "";
  return true;
}

function getCancerTypeFromFilterCollection(filter: FilterCollection | null | undefined): string {
  const parsed = safeParseJson<any>(filter?.patientDataFilters);
  if (!parsed || typeof parsed !== "object") return "";

  const raw =
    (typeof parsed.cancer_type === "string" && parsed.cancer_type) ||
    (typeof parsed.cancerType === "string" && parsed.cancerType) ||
    "";

  return String(raw || "").trim();
}

function normalizeFilterCollection(fc: FilterCollection | null | undefined): FilterCollection {
  return {
    patientQueryFilters: fc?.patientQueryFilters ?? "{}",
    patientDataFilters: fc?.patientDataFilters ?? "{}",
    observationQueryFilters: fc?.observationQueryFilters ?? "{}",
    observationDataFilters: fc?.observationDataFilters ?? "{}"
  };
}

function supportsAny(project: Project, wanted: string[]): boolean {
  const allowed = (project as any)?.filter_system_allowed_filter_types as string[] | null | undefined;
  if (!allowed || !Array.isArray(allowed) || allowed.length === 0) return true;
  const set = new Set(allowed.map((s) => String(s).toUpperCase()));
  return wanted.some((w) => set.has(String(w).toUpperCase()));
}


function getOrderedWorkflowGroups(project: Project): ProjectWorkflowGroup[] {
  const raw = (project as any)?.workflow_groups;
  if (!Array.isArray(raw)) return [];

  return [...raw]
    .filter((group) => group && typeof group.group_key === "string" && Array.isArray(group.options))
    .sort((a, b) => {
      const aOrder = typeof a?.page_order === "number" ? a.page_order : Number.MAX_SAFE_INTEGER;
      const bOrder = typeof b?.page_order === "number" ? b.page_order : Number.MAX_SAFE_INTEGER;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return String(a?.group_label || a?.group_key || "").localeCompare(String(b?.group_label || b?.group_key || ""));
    });
}

function getPostPatientScreen(supportsObservationScreen: boolean, supportsWorkflowGroups: boolean): JobRunnerScreen {
  if (supportsObservationScreen) return "variantTable";
  if (supportsWorkflowGroups) return "workflow_groups";
  return "functionSelection";
}
 

const JobRunnerMain = React.forwardRef<JobRunnerMainHandle, JobRunnerMainProps>(({ setMainScreen, project }, ref) => {
  const userSession = useUserSession();
  const initialBrowserHistoryRef = useRef<{ screen: JobRunnerScreen; trail: JobRunnerScreen[]; depth: number } | null | undefined>(undefined);
  if (initialBrowserHistoryRef.current === undefined) {
    initialBrowserHistoryRef.current = readJobRunnerHistory(project.id);
  }
  const initialBrowserHistory = initialBrowserHistoryRef.current;

  const [screen, setScreen] = useState<JobRunnerScreen>(initialBrowserHistory?.screen ?? "filterHistory");
  const screenHistoryRef = useRef<JobRunnerScreen[]>(initialBrowserHistory?.trail ?? ["filterHistory"]);
  const historyDepthRef = useRef<number>(initialBrowserHistory?.depth ?? 0);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [medications, setMedications] = useState<Medication[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [localBundleLoading, setLocalBundleLoading] = useState(false);
  const [localBundleError, setLocalBundleError] = useState("");

  const [variantPatients, setVariantPatients] = useState<Patient[]>([]);
  const [geneticObsForVariantPage, setGeneticObsForVariantPage] = useState<Observation[]>([]);

  const [, setSelectedFinalPatients] = useState<Patient[]>([]);

  const [newFilterSet, setNewFilterSet] = useState<FilterCollection>(BLANK_FILTER_CONFIG);
  const [selectedPreviouslySavedFilterSet, setSelectedPreviouslySavedFilterSet] = useState<FilterCollection>(BLANK_FILTER_CONFIG);

  const [submittedFilterSet, setSubmittedFilterSet] = useState<FilterCollection>(BLANK_FILTER_CONFIG);
  const [submittedFilterSetName, setSubmittedFilterSetName] = useState<string>("");

  const [selectedFilterName, setSelectedFilterName] = useState("");

  const [savedJobInfo, setSavedJobInfo] = useState<JobLogData>(BLANK_JOB_DATA);

  const [animate, setAnimate] = useState(true);

  const [viewOnly, setViewOnly] = useState(false);

  const [selectedFunctions, setSelectedFunctions] = useState<FunctionConfigs>({});

  const [selectedThresholdConfig, setSelectedThresholdConfig] = useState<ThresholdConfig>();
  const [selectedDatasourceGroupId, setSelectedDatasourceGroupId] = useState<number | null>(null);
  const [workflowGroupData, setWorkflowGroupData] = useState<WorkflowGroupData>({});

  const supportsPatientScreens = useMemo(
    () => supportsAny(project, ["PATIENT_QUERY", "PATIENT_DATA"]),
    [project]
  );

  const supportsObservationScreen = useMemo(
    () => supportsAny(project, ["OBSERVATION", "OBSERVATION_QUERY", "OBSERVATION_DATA"]),
    [project]
  );

  const supportsWorkflowGroups = useMemo(
    () => getOrderedWorkflowGroups(project).length > 0,
    [project]
  );

  const generalStatisticsFhirSource = useMemo(
    () => String(userSession.fhir_source || "").trim(),
    [userSession.fhir_source]
  );

  const usesLocalGeneralStatisticsBundle = useMemo(
    () => project.name === "General Statistics" && generalStatisticsFhirSource.toLowerCase().endsWith(".json"),
    [generalStatisticsFhirSource, project.name]
  );

  useEffect(() => {
    let cancelled = false;

    console.log("[GeneralStatisticsPreview][JobRunnerMain] datasource effect", {
      projectName: project.name,
      fhirSource: generalStatisticsFhirSource,
      usesLocalGeneralStatisticsBundle
    });

    if (!usesLocalGeneralStatisticsBundle) {
      setPatients([]);
      setMedications([]);
      setObservations([]);
      setLocalBundleLoading(false);
      setLocalBundleError("");
      return () => {
        cancelled = true;
      };
    }

    setLocalBundleLoading(true);
    setLocalBundleError("");
    loadGeneralStatisticsPreviewData(generalStatisticsFhirSource)
      .then((data) => {
        if (cancelled) return;
        console.log("[GeneralStatisticsPreview][JobRunnerMain] load complete", {
          patients: data.patients.length,
          medications: data.medications.length,
          observations: data.observations.length
        });
        setPatients(data.patients);
        setMedications(data.medications);
        setObservations(data.observations);
      })
      .catch((error: any) => {
        if (cancelled) return;
        console.error("[GeneralStatisticsPreview][JobRunnerMain] load failed", error);
        setPatients([]);
        setMedications([]);
        setObservations([]);
        setLocalBundleError(error?.message || "Unable to load the local General Statistics bundle.");
      })
      .finally(() => {
        if (!cancelled) setLocalBundleLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [generalStatisticsFhirSource, usesLocalGeneralStatisticsBundle]);

  const orderedScreens = useMemo<JobRunnerScreen[]>(() => {
    const s: JobRunnerScreen[] = ["filterHistory"];
    if (supportsPatientScreens) s.push("patientFilters");
    if (supportsObservationScreen) s.push("variantTable");
    if (supportsWorkflowGroups) s.push("workflow_groups");
    s.push("functionSelection", "submit_function", "results");
    return s;
  }, [supportsPatientScreens, supportsObservationScreen, supportsWorkflowGroups]);

  useEffect(() => {
    const projectEntry = userSession.projects.find((entry) => entry.project_id === project.id);
    if (!projectEntry) {
      setSelectedDatasourceGroupId(null);
      return;
    }

    const grouped = (projectEntry.datasources || []).filter((item) => item.datasource_group_id != null);
    if (!grouped.length) {
      setSelectedDatasourceGroupId(null);
      return;
    }

    const defaultDatasource = grouped.find((item) => item.is_default_group) || grouped[0];
    setSelectedDatasourceGroupId(defaultDatasource.datasource_group_id ?? null);
  }, [userSession.projects, project.id]);

  function getNextScreen(from: JobRunnerScreen): JobRunnerScreen {
    const idx = orderedScreens.indexOf(from);
    if (idx < 0) return "filterHistory";
    return orderedScreens[Math.min(orderedScreens.length - 1, idx + 1)];
  }

  function getPrevScreen(from: JobRunnerScreen): JobRunnerScreen {
    const idx = orderedScreens.indexOf(from);
    if (idx <= 0) return "filterHistory";
    return orderedScreens[Math.max(0, idx - 1)];
  }

  function getBackToScreenLabel(screenName: JobRunnerScreen): string {
    switch (screenName) {
      case "filterHistory":
        return "Back to Filter History";
      case "patientFilters":
        return "Back to Patient Filters";
      case "variantTable":
        return "Back to Observation Filters";
      case "workflow_groups":
        return "Back to Workflow Selection";
      case "functionSelection":
        return "Back to Analysis Function Selection";
      case "submit_function":
        return "Back to Submission Details";
      default:
        return "Back";
    }
  }

  function applyScreenTransition(screenName: JobRunnerScreen) {
    if (CLEAR_JOB_STATES.includes(screenName)) {
      setSavedJobInfo(BLANK_JOB_DATA);
    }
    setScreen(screenName);
  }

  function writeBrowserHistory(
    historyMode: "push" | "replace",
    screenName: JobRunnerScreen,
    trail: JobRunnerScreen[]
  ) {
    if (typeof window === "undefined") return;

    const nextState: JobRunnerBrowserHistoryState = {
      ...((window.history.state || {}) as JobRunnerBrowserHistoryState),
      screen: "job_runner",
      projectId: project.id,
      jobRunnerStep: screenName,
      jobRunnerTrail: trail,
      jobRunnerProjectId: project.id,
      jobRunnerDepth: historyDepthRef.current
    };

    window.history[historyMode === "push" ? "pushState" : "replaceState"](
      nextState,
      "",
      window.location.href
    );
  }

  function processAndSetScreen(screenName: JobRunnerScreen) {
    const trail = screenHistoryRef.current;
    if (trail[trail.length - 1] === screenName) {
      applyScreenTransition(screenName);
      return;
    }

    const nextTrail = [...trail, screenName];
    screenHistoryRef.current = nextTrail;
    historyDepthRef.current += 1;
    writeBrowserHistory("push", screenName, nextTrail);
    applyScreenTransition(screenName);
  }

  function resetFlowToScreen(screenName: JobRunnerScreen) {
    if (screenName === "filterHistory" && historyDepthRef.current > 0 && typeof window !== "undefined") {
      window.history.go(-historyDepthRef.current);
      return;
    }

    const nextTrail = [screenName];
    screenHistoryRef.current = nextTrail;
    historyDepthRef.current = 0;
    writeBrowserHistory("replace", screenName, nextTrail);
    applyScreenTransition(screenName);
  }

  function getPreviousVisitedScreen(fallbackFrom: JobRunnerScreen): JobRunnerScreen {
    const trail = screenHistoryRef.current;
    return trail.length > 1 ? trail[trail.length - 2] : getPrevScreen(fallbackFrom);
  }

  function goBackInFlow(fallbackFrom: JobRunnerScreen) {
    const trail = screenHistoryRef.current;
    if (trail.length > 1 && typeof window !== "undefined") {
      window.history.back();
      return;
    }

    // Defensive fallback for legacy/direct runner state. Never navigate out of the
    // runner from an in-wizard Back control.
    applyScreenTransition(getPrevScreen(fallbackFrom));
  }

  useEffect(() => {
    const currentTrail = screenHistoryRef.current;
    writeBrowserHistory("replace", currentTrail[currentTrail.length - 1] ?? screen, currentTrail);

    const onPopState = (event: PopStateEvent) => {
      const state = (event.state || {}) as JobRunnerBrowserHistoryState;
      if (state.screen !== "job_runner" || state.projectId !== project.id || state.jobRunnerProjectId !== project.id) {
        return;
      }

      const restored = readJobRunnerHistory(project.id);
      if (!restored) return;

      screenHistoryRef.current = restored.trail;
      historyDepthRef.current = restored.depth;
      applyScreenTransition(restored.screen);
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
    // This listener is scoped to the mounted runner/project. Screen changes are
    // restored from history state rather than re-registering the listener.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  const updateNewFilterCollection = <K extends keyof FilterCollection>(key: K, jsonString: string): void => {
    setNewFilterSet((prev) => ({ ...prev, [key]: jsonString }));
  };

  useEffect(() => {
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [screen]);

  function resetAnalysisRunnerState() {
    setVariantPatients([]);
    setGeneticObsForVariantPage([]);
    setSelectedFinalPatients([]);

    setNewFilterSet(BLANK_FILTER_CONFIG);
    setSelectedPreviouslySavedFilterSet(BLANK_FILTER_CONFIG);
    setSubmittedFilterSet(BLANK_FILTER_CONFIG);
    setSubmittedFilterSetName("");
    setSelectedFilterName("");

    setSelectedFunctions({});
    setSelectedThresholdConfig(undefined);
    setSelectedDatasourceGroupId(null);
    setWorkflowGroupData({});

    setSavedJobInfo(BLANK_JOB_DATA);
    setViewOnly(false);
  }

  function startOver() {
    resetAnalysisRunnerState();
    resetFlowToScreen("filterHistory");
  }

  useImperativeHandle(ref, () => ({
    handleRunNewAnalysisNavigation: () => {
      // Run New Analysis should not interrupt a runner already in progress.
      // From Results, use the exact same reset path as the Start Over button.
      if (screen === "results") {
        startOver();
      }
    }
  }), [screen]);

  function onBackToHistory() {
    setViewOnly(false);
    setSavedJobInfo(BLANK_JOB_DATA);
    setSubmittedFilterSetName("");
    setSubmittedFilterSet(BLANK_FILTER_CONFIG);
    resetFlowToScreen("filterHistory");
  }

  const handleAfterHistory = () => {
    const next = getNextScreen("filterHistory");
    processAndSetScreen(next);
  };

  const handleAfterPatients = (selectedPatients: Patient[]) => {
    setVariantPatients(selectedPatients);
    const acceptableRefs = new Set<string>([
      ...selectedPatients.map((p) => p.fullUrl),
      ...selectedPatients.map((p) => `Patient/${p.id}`)
    ]);
    const obsForSelected = observations.filter((o) => acceptableRefs.has(o.subjectReference));
    setGeneticObsForVariantPage(obsForSelected);

    const next = getPostPatientScreen(supportsObservationScreen, supportsWorkflowGroups);
    processAndSetScreen(next);
  };

  const activeCandidateFilterSet = useMemo(() => {
    const candidate = selectedFilterName ? selectedPreviouslySavedFilterSet : newFilterSet;
    return normalizeFilterCollection(candidate);
  }, [selectedFilterName, selectedPreviouslySavedFilterSet, newFilterSet]);

  const generateFilterSetNameDynamic = (filter: FilterCollection): string => {
    const parts: string[] = [];

    const query = safeParseJson<any>(filter.patientQueryFilters);
    const data = safeParseJson<any>(filter.patientDataFilters);
    const observationQuery = safeParseJson<any>(filter.observationQueryFilters);
    const observationData = safeParseJson<any>(filter.observationDataFilters);

    if (isMeaningfulJsonString(filter.patientQueryFilters) && query) {
      const gender = query.gender || "any";
      const medication = query.medication || "any";
      const ar = Array.isArray(query.ageRange) ? query.ageRange : null;
      const ageMin = ar?.[0] ?? 0;
      const ageMax = ar?.[1] ?? 120;
      parts.push(`G:${gender}`);
      parts.push(`A:${ageMin}-${ageMax}`);
      parts.push(`MD:${medication}`);
    }

    if (isMeaningfulJsonString(filter.patientDataFilters) && data) {
      const ct =
        typeof data.cancer_type === "string"
          ? data.cancer_type
          : typeof data.cancerType === "string"
            ? data.cancerType
            : "";
      if (ct.trim() !== "") parts.push(`CT:${ct}`);
      if (Array.isArray(data.deceasedDateRange) && data.deceasedDateRange.length >= 2) {
        const a = data.deceasedDateRange[0] ?? "";
        const b = data.deceasedDateRange[1] ?? "";
        if (a || b) parts.push(`DD:${a}-${b}`);
      }
    }

    if (isMeaningfulJsonString(filter.observationQueryFilters) || isMeaningfulJsonString(filter.observationDataFilters)) {
      const del = observationData?.minDeletions ?? 0;
      const amp = observationData?.minAmplifications ?? observationData?.minDuplications ?? 0;
      const tot = observationData?.minTotal ?? 0;
      const regionCount =
        (Array.isArray(observationQuery?.deletionRegions) ? observationQuery.deletionRegions.length : 0) +
        (Array.isArray(observationQuery?.amplificationRegions) ? observationQuery.amplificationRegions.length : 0);
      parts.push(`D:${del}`);
      parts.push(`A:${amp}`);
      parts.push(`T:${tot}`);
      parts.push(`R:${regionCount}`);
    }

    return parts.length ? parts.join(",") : "Default";
  };

  useEffect(() => {
    const next = activeCandidateFilterSet;
    setSubmittedFilterSet(next);
    setSubmittedFilterSetName(selectedFilterName ? selectedFilterName : generateFilterSetNameDynamic(next));
  }, [activeCandidateFilterSet, selectedFilterName]);

  const effectiveFilterSet = useMemo(() => {
    return submittedFilterSetName ? submittedFilterSet : activeCandidateFilterSet;
  }, [submittedFilterSetName, submittedFilterSet, activeCandidateFilterSet]);

  const selectedDatasourceGroupName = useMemo(() => {
    const projectEntry = userSession.projects.find((entry) => entry.project_id === project.id);
    if (!projectEntry || selectedDatasourceGroupId == null) {
      return null;
    }

    const selectedDatasource = (projectEntry.datasources || []).find(
      (entry) => entry.datasource_group_id === selectedDatasourceGroupId
    );

    return selectedDatasource?.datasource_group_name || null;
  }, [userSession.projects, project.id, selectedDatasourceGroupId]);

  const workflowValidationLookupValues = useMemo(() => {
    const cancerType = getCancerTypeFromFilterCollection(activeCandidateFilterSet);
    return cancerType ? { cancer_type: cancerType, cancerType } : {};
  }, [activeCandidateFilterSet]);
  return (
    <>
      <div className={`function-container job-runner-flow ${screen === "results" ? "job-runner-flow-results" : ""} ${animate ? "animate-in" : ""}`}>
        {screen !== "results" ? (
          <HeaderTitle
            contained
            iconPath="/icons/nav_icon_job_runner.png"
            title={
              <>
                Analysis Runner: <ProjectNameWithDescription project={project} />
              </>
            }
            description={description_job_runner}
          />
        ) : null}
        {screen === "filterHistory" && (
          <FilterHistoryTable
            project={project}
            onUseFilter={(config, name) => {
              setSelectedPreviouslySavedFilterSet(config);
              setSelectedFilterName(name);
              handleAfterHistory();
            }}
            onCreateNewFilterSet={() => {
              setSelectedPreviouslySavedFilterSet(BLANK_FILTER_CONFIG);
              setSelectedFilterName("");
              setNewFilterSet(BLANK_FILTER_CONFIG);
              handleAfterHistory();
            }}
          />
        )}

        {screen === "patientFilters" && supportsPatientScreens && usesLocalGeneralStatisticsBundle && (
          <FilterScreenPatientsJSON
            project={project}
            patients={patients}
            medications={medications}
            loading={localBundleLoading}
            loadError={localBundleError}
            onBack={() => goBackInFlow("patientFilters")}
            onProceedToVariants={handleAfterPatients}
            setFilterCollection={updateNewFilterCollection}
            existingQueryFilter={
              selectedFilterName && selectedPreviouslySavedFilterSet?.patientQueryFilters !== "{}"
                ? selectedPreviouslySavedFilterSet?.patientQueryFilters
                : newFilterSet?.patientQueryFilters
            }
            existingPatientFilter={
              selectedFilterName && selectedPreviouslySavedFilterSet?.patientDataFilters !== "{}"
                ? selectedPreviouslySavedFilterSet?.patientDataFilters
                : newFilterSet?.patientDataFilters
            }
            lockFilterConfig={!!selectedFilterName}
            selectedDatasourceGroupId={selectedDatasourceGroupId}
            onSelectedDatasourceGroupIdChange={setSelectedDatasourceGroupId}
          />
        )}

        {screen === "patientFilters" && supportsPatientScreens && !usesLocalGeneralStatisticsBundle && (
          <FilterScreenPatients
            project={project}
            filterSystem={project.filter_system || "DEFAULT"}
            patients={patients}
            medications={medications}
            onBack={() => goBackInFlow("patientFilters")}
            onProceedToVariants={handleAfterPatients}
            setFilterCollection={updateNewFilterCollection}
            existingQueryFilter={
              selectedFilterName && selectedPreviouslySavedFilterSet?.patientQueryFilters !== "{}"
                ? selectedPreviouslySavedFilterSet?.patientQueryFilters
                : newFilterSet?.patientQueryFilters
            }
            existingPatientFilter={
              selectedFilterName && selectedPreviouslySavedFilterSet?.patientDataFilters !== "{}"
                ? selectedPreviouslySavedFilterSet?.patientDataFilters
                : newFilterSet?.patientDataFilters
            }
            lockFilterConfig={!!selectedFilterName}
            selectedDatasourceGroupId={selectedDatasourceGroupId}
            onSelectedDatasourceGroupIdChange={setSelectedDatasourceGroupId}
          />
        )}

        {screen === "variantTable" && supportsObservationScreen && (
          <FilterScreenObservations
            filterSystem={project.filter_system || "DEFAULT"}
            patients={variantPatients}
            project={project}
            rawObservations={geneticObsForVariantPage}
            reviewSubmission={(selectedFinal) => {
              setSelectedFinalPatients(selectedFinal);
              processAndSetScreen(supportsWorkflowGroups ? "workflow_groups" : "functionSelection");
            }}
            onBack={() => goBackInFlow("variantTable")}
            backToButtonText={getBackToScreenLabel(getPreviousVisitedScreen("variantTable"))}
            setFilterCollection={updateNewFilterCollection}
            existingQueryFilter={
              selectedFilterName && selectedPreviouslySavedFilterSet?.observationQueryFilters !== "{}"
                ? selectedPreviouslySavedFilterSet?.observationQueryFilters
                : newFilterSet?.observationQueryFilters
            }
            existingDataFilter={
              selectedFilterName && selectedPreviouslySavedFilterSet?.observationDataFilters !== "{}"
                ? selectedPreviouslySavedFilterSet?.observationDataFilters
                : newFilterSet?.observationDataFilters
            }
            lockFilterConfig={!!selectedFilterName}
            selectedDatasourceGroupId={selectedDatasourceGroupId}
          />
        )}


        {screen === "workflow_groups" && supportsWorkflowGroups && (
          <WorkflowGroupSelectionPage
            project={project}
            workflowGroupData={workflowGroupData}
            setWorkflowGroupData={setWorkflowGroupData}
            onBack={() => goBackInFlow("workflow_groups")}
            backToButtonText={getBackToScreenLabel(getPreviousVisitedScreen("workflow_groups"))}
            onNext={() => processAndSetScreen(getNextScreen("workflow_groups"))}
            username={userSession.username}
            datasourceGroupId={selectedDatasourceGroupId}
            validationLookupValues={workflowValidationLookupValues}
          />
        )}

        {screen === "functionSelection" && (
          <FunctionSelectionPage
            project={project}
            onBack={() => goBackInFlow("functionSelection")}
            onNext={() => processAndSetScreen("submit_function")}
            setSelectedFunctions={setSelectedFunctions}
            existingFunctions={selectedFunctions}
            setSelectedThresholdConfig={setSelectedThresholdConfig}
            existingThresholdConfig={selectedThresholdConfig || DEFAULT_THRESHOLD_CONFIG}
            filterSet={effectiveFilterSet}
            backToButtonText={getBackToScreenLabel(getPreviousVisitedScreen("functionSelection"))}
          />
        )}

        {screen === "submit_function" && (
          <JobSubmissionPage
            project={project}
            onBack={() => goBackInFlow("submit_function")}
            submittedFilterName={submittedFilterSetName || ""}
            submittedFilter={effectiveFilterSet}
            onCancel={() => resetFlowToScreen("filterHistory")}
            viewAnalysisResultsPage={() => {
              processAndSetScreen("results");
            }}
            savedJobInfo={savedJobInfo}
            setSavedJobInfo={setSavedJobInfo}
            selectedFunctions={selectedFunctions}
            selectedThresholdConfig={selectedThresholdConfig}
            selectedDatasourceGroupId={selectedDatasourceGroupId}
            selectedDatasourceGroupName={selectedDatasourceGroupName}
            workflowGroupData={workflowGroupData}
          />
        )}

        {screen === "results" && (
          <ResultsPage
            onBack={() => goBackInFlow("results")}
            submittedFilterSetName={submittedFilterSetName ? submittedFilterSetName : ""}
            submittedFilterSet={effectiveFilterSet}
            onStartOver={startOver}
            savedJobInfo={savedJobInfo}
            viewOnly={viewOnly}
            onBackToHistory={onBackToHistory}
            project={project}
          />
        )}
      </div>
    </>
  );
});

JobRunnerMain.displayName = "JobRunnerMain";

export default JobRunnerMain;
