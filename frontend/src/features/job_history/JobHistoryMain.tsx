import React, { useEffect, useMemo, useState } from "react";
import { AppScreen } from "../../App";
import HeaderTitle from "../../components/HeaderTitle";
import { ProjectNameWithDescription } from "../../components/ProjectName";
import { API_BASE, API_FILTERS_FETCH_SINGLE, description_job_history } from "../../constants/Constants";
import { JobLogData, NVFlareJob } from "../../types/JobsDataTypes";
import { Project } from "../../types/Project";
import { buildDefaultFilterCollectionFromConditions, FilterCollection } from "../job_runner/utils/FilterPayloadConfigUtils";
import ColumnConfigModal from "./components/ColumnConfigModal";
import ResultsPage from "./pages/ResultsPage";
import JobHistoryTable from "./components/JobHistoryTable";

type JobHistoryScreen = "jobHistory" | "results";

interface JobHistoryMainProps {
  setMainScreen: (screen: AppScreen) => void;
  project: Project;
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
  run_duration: "",
  functions: []
};

const JobHistoryMain: React.FC<JobHistoryMainProps> = ({ setMainScreen, project }) => {

  const [screen, setScreen] = useState<JobHistoryScreen>("jobHistory");
  const [submittedFilterSet, setSubmittedFilterSet] = useState<FilterCollection>();
  const [submittedFilterSetName, setSubmittedFilterSetName] = useState<string>();

  const [savedJobInfo, setSavedJobInfo] = useState<JobLogData>(BLANK_JOB_DATA);

  const [animate, setAnimate] = useState(true);

  const [viewOnly, setViewOnly] = useState(false);

  const storageKeyForExtraColumns = useMemo(() => {
    const pid = (project as any)?.id != null ? String((project as any).id) : "unknown";
    return `nvflare_job_history_extra_cols_v1:${pid}`;
  }, [project]);

  const [extraColumnKeys, setExtraColumnKeys] = useState<string[]>([]);
  const [availableExtraColumnKeys, setAvailableExtraColumnKeys] = useState<string[]>([]);
  const [openColumnConfig, setOpenColumnConfig] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKeyForExtraColumns);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return;

      const cleaned = parsed
        .map((x) => String(x || ""))
        .filter(Boolean)
        .slice(0, 3);

      setExtraColumnKeys(cleaned);
    } catch {
    }
  }, [storageKeyForExtraColumns]);

  useEffect(() => {
    try {
      const cleaned = (extraColumnKeys || []).slice(0, 3);
      localStorage.setItem(storageKeyForExtraColumns, JSON.stringify(cleaned));
    } catch {
    }
  }, [extraColumnKeys, storageKeyForExtraColumns]);

  useEffect(() => {
    if (!availableExtraColumnKeys.length) return;
    if (!extraColumnKeys.length) return;

    const allowed = new Set(availableExtraColumnKeys);
    const cleaned = extraColumnKeys.filter((k) => allowed.has(k)).slice(0, 3);
    if (cleaned.join("|") !== extraColumnKeys.join("|")) {
      setExtraColumnKeys(cleaned);
    }
  }, [availableExtraColumnKeys, extraColumnKeys]);

  function processAndSetScreen(screenName: JobHistoryScreen) {
    setScreen(screenName);
  }

  useEffect(() => {
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [screen]);

  async function attemptViewResults(job_data: NVFlareJob) {
    const fetchSingleFilter = async (filterId: number) => {
      const res = await fetch(`${API_BASE}${API_FILTERS_FETCH_SINGLE}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filter_id: filterId, project_id: project.id })
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();

      const r = data?.filter;
      return r
        ? {
            name: r.name,
            filter_json: buildDefaultFilterCollectionFromConditions(r.conditions || [], project)
          }
        : null;
    };

    if (job_data.filter_id) {
      const this_filter = await fetchSingleFilter(job_data.filter_id);
      if (this_filter && job_data.nvflare_assigned_id) {
        setViewOnly(true);
        setSavedJobInfo({
          jobId: job_data.job_runner_id,
          jobStatus: job_data.status,
          jobLog: [],
          referencedBy: [job_data.nvflare_assigned_id],
          run_duration: job_data.run_duration,
          functions: job_data.functions
        });
        setSubmittedFilterSetName(this_filter.name);
        setSubmittedFilterSet(this_filter.filter_json);
        setScreen("results");
      }
    }
  }

  function onBackToHistory() {
    setViewOnly(false);
    processAndSetScreen("jobHistory");
  }

  return (
    <>
      {openColumnConfig && (
        <ColumnConfigModal
          isOpen={openColumnConfig}
          onClose={() => setOpenColumnConfig(false)}
          availableKeys={availableExtraColumnKeys}
          selectedKeys={extraColumnKeys}
          onChangeSelectedKeys={(keys) => setExtraColumnKeys((keys || []).slice(0, 3))}
        />
      )}

      <div className={`function-container ${animate ? "animate-in" : ""}`}>
        {screen === "jobHistory" && (
          <>
            <HeaderTitle
              contained
              iconPath="/icons/nav_icon_job_history.png"
              title={
                <>
                  Analysis History: <ProjectNameWithDescription project={project} />
                </>
              }
              description={description_job_history}
            />
            <JobHistoryTable
            project={project}
            onStartNewAnalysis={() => setMainScreen("job_runner")}
            onViewResults={(job_data: NVFlareJob) => attemptViewResults(job_data)}
            extraColumnKeys={extraColumnKeys}
            onExtraColumnKeysChange={(keys) => setExtraColumnKeys((keys || []).slice(0, 3))}
            onOpenColumnConfig={() => setOpenColumnConfig(true)}
            onAvailableExtraColumnKeysChange={(keys) => setAvailableExtraColumnKeys(keys || [])}
            />
          </>
        )}

        {screen === "results" && (
          <ResultsPage
            onBack={() => processAndSetScreen("jobHistory")}
            submittedFilterSetName={submittedFilterSetName ? submittedFilterSetName : ""}
            submittedFilterSet={submittedFilterSet ? submittedFilterSet : BLANK_FILTER_CONFIG}
            onStartOver={() => processAndSetScreen("jobHistory")}
            savedJobInfo={savedJobInfo}
            viewOnly={viewOnly}
            onBackToHistory={onBackToHistory}
            project={project}
          />
        )}
      </div>
    </>
  );
};

export default JobHistoryMain;

 