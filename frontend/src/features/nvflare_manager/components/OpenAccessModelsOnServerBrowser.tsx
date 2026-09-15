import React, { ChangeEvent, useEffect, useMemo, useState } from "react";
import { Project } from "../../../types/Project";
import { API_BASE, API_PROJECTS_LIST } from "../../../constants/Constants";

type ArtifactType = "weights" | "cutoff";
type ModelKey = "cox_lasso" | "logistic_reg";

interface OpenAccessModelsOnServerBrowserProps {
  currentProject?: Project | null;
}

interface PublicModelGroup {
  folder: string;
  label: string;
  models: Partial<Record<ModelKey, string[]>>;
}

const FOUR_SCENARIOS_CANCER_TYPES = [
  "Breast Carcinoma",
  "Colorectal Cancer",
  "Non-Small Cell Lung Cancer",
  "Pancreatic Cancer",
  "Prostate Cancer"
];

const OPEN_ACCESS_MODELS_BY_PROJECT: Record<string, PublicModelGroup[]> = {
  "2": [
    {
      folder: "datasource_group_1",
      label: "MSKChord",
      models: {
        cox_lasso: FOUR_SCENARIOS_CANCER_TYPES,
        logistic_reg: FOUR_SCENARIOS_CANCER_TYPES
      }
    }
  ]
};

// Matches the seeded default datasource group for the biomarker project.
const DEFAULT_GROUP_FOLDER = "datasource_group_1";

const MODEL_LABELS: Record<ModelKey, string> = {
  cox_lasso: "Lasso Cox Regression",
  logistic_reg: "Lasso Logistic Regression"
};

function isModelFileSettingsEnabled(project: Project): boolean {
  return project.model_file_settings_enabled === true;
}

function getProjectModels(projectId: string): PublicModelGroup[] {
  return OPEN_ACCESS_MODELS_BY_PROJECT[projectId] || [];
}

function getAvailableModelKeys(group: PublicModelGroup | null): ModelKey[] {
  if (!group) {
    return [];
  }

  return (Object.keys(group.models) as ModelKey[]).filter((modelKey) => {
    const cancerTypes = group.models[modelKey];
    return Array.isArray(cancerTypes) && cancerTypes.length > 0;
  });
}

function buildModelFileName(modelKey: ModelKey, cancerType: string, artifactType: ArtifactType): string {
  return `${modelKey}_${cancerType}_${artifactType}.csv`;
}

function buildModelFileUrl(projectId: string, groupFolder: string, fileName: string): string {
  return `/models/project_${encodeURIComponent(projectId)}/${encodeURIComponent(groupFolder)}/${encodeURIComponent(fileName)}`;
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    const next = line[i + 1];

    if (ch === '"') {
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (ch === "," && !inQuotes) {
      cells.push(current);
      current = "";
      continue;
    }

    current += ch;
  }

  cells.push(current);
  return cells;
}

function parseCsv(text: string): string[][] {
  return text
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0)
    .map(parseCsvLine);
}

const OpenAccessModelsOnServerBrowser: React.FC<OpenAccessModelsOnServerBrowserProps> = ({ currentProject }) => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedGroupFolder, setSelectedGroupFolder] = useState("");
  const [selectedModelKey, setSelectedModelKey] = useState<ModelKey>("cox_lasso");
  const [selectedCancerType, setSelectedCancerType] = useState("");
  const [selectedArtifactType, setSelectedArtifactType] = useState<ArtifactType>("weights");
  const [csvText, setCsvText] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingCsv, setLoadingCsv] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;

    async function fetchProjects() {
      setLoadingProjects(true);
      setError("");

      try {
        const res = await fetch(`${API_BASE}${API_PROJECTS_LIST}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
          throw new Error(data.error || "Failed to load projects.");
        }

        if (!ignore) {
          setProjects(Array.isArray(data.projects) ? data.projects : []);
        }
      } catch (e) {
        if (!ignore) {
          setError(e instanceof Error ? e.message : "Failed to load projects.");
        }
      } finally {
        if (!ignore) {
          setLoadingProjects(false);
        }
      }
    }

    fetchProjects();

    return () => {
      ignore = true;
    };
  }, []);

  const modelEnabledProjects = useMemo(() => {
    return projects.filter(isModelFileSettingsEnabled);
  }, [projects]);

  useEffect(() => {
    if (selectedProjectId) {
      return;
    }

    const currentProjectIsEnabled = currentProject
      ? modelEnabledProjects.find((project) => String(project.id) === String(currentProject.id))
      : null;

    if (currentProjectIsEnabled) {
      setSelectedProjectId(String(currentProjectIsEnabled.id));
      return;
    }

    if (modelEnabledProjects.length > 0) {
      setSelectedProjectId(String(modelEnabledProjects[0].id));
    }
  }, [currentProject, modelEnabledProjects, selectedProjectId]);

  const selectedProject = useMemo(() => {
    return modelEnabledProjects.find((project) => String(project.id) === selectedProjectId) || null;
  }, [modelEnabledProjects, selectedProjectId]);

  const projectModelGroups = useMemo(() => {
    return selectedProject ? getProjectModels(String(selectedProject.id)) : [];
  }, [selectedProject]);

  useEffect(() => {
    if (!projectModelGroups.length) {
      setSelectedGroupFolder("");
      return;
    }

    if (!projectModelGroups.some((group) => group.folder === selectedGroupFolder)) {
      const defaultGroup =
        projectModelGroups.find((group) => group.folder === DEFAULT_GROUP_FOLDER) || projectModelGroups[0];
      setSelectedGroupFolder(defaultGroup.folder);
    }
  }, [projectModelGroups, selectedGroupFolder]);

  const selectedGroup = useMemo(() => {
    return projectModelGroups.find((group) => group.folder === selectedGroupFolder) || null;
  }, [projectModelGroups, selectedGroupFolder]);

  const availableModelKeys = useMemo(() => getAvailableModelKeys(selectedGroup), [selectedGroup]);

  useEffect(() => {
    if (!availableModelKeys.length) {
      return;
    }

    if (!availableModelKeys.includes(selectedModelKey)) {
      setSelectedModelKey(availableModelKeys[0]);
    }
  }, [availableModelKeys, selectedModelKey]);

  const availableCancerTypes = useMemo(() => {
    if (!selectedGroup) {
      return [];
    }

    return selectedGroup.models[selectedModelKey] || [];
  }, [selectedGroup, selectedModelKey]);

  useEffect(() => {
    if (!availableCancerTypes.length) {
      setSelectedCancerType("");
      return;
    }

    if (!availableCancerTypes.includes(selectedCancerType)) {
      const defaultCancerType = availableCancerTypes.includes("Non-Small Cell Lung Cancer")
        ? "Non-Small Cell Lung Cancer"
        : availableCancerTypes[0];
      setSelectedCancerType(defaultCancerType);
    }
  }, [availableCancerTypes, selectedCancerType]);

  const selectedFileName = useMemo(() => {
    if (!selectedProject || !selectedGroup || !selectedCancerType) {
      return "";
    }

    return buildModelFileName(selectedModelKey, selectedCancerType, selectedArtifactType);
  }, [selectedArtifactType, selectedCancerType, selectedGroup, selectedModelKey, selectedProject]);

  const selectedFileUrl = useMemo(() => {
    if (!selectedProject || !selectedGroup || !selectedFileName) {
      return "";
    }

    return buildModelFileUrl(String(selectedProject.id), selectedGroup.folder, selectedFileName);
  }, [selectedFileName, selectedGroup, selectedProject]);

  useEffect(() => {
    let ignore = false;

    async function fetchCsv() {
      if (!selectedFileUrl) {
        setCsvText("");
        return;
      }

      setLoadingCsv(true);
      setError("");

      try {
        const res = await fetch(selectedFileUrl);

        if (!res.ok) {
          throw new Error(`Could not load ${selectedFileName}.`);
        }

        const text = await res.text();

        if (!ignore) {
          setCsvText(text);
        }
      } catch (e) {
        if (!ignore) {
          setCsvText("");
          setError(e instanceof Error ? e.message : "Could not load model file.");
        }
      } finally {
        if (!ignore) {
          setLoadingCsv(false);
        }
      }
    }

    fetchCsv();

    return () => {
      ignore = true;
    };
  }, [selectedFileName, selectedFileUrl]);

  const csvRows = useMemo(() => parseCsv(csvText), [csvText]);
  const headerRow = csvRows[0] || [];
  const bodyRows = csvRows.slice(1);
  const hasHeader = headerRow.length > 0;

  const handleProjectChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setSelectedProjectId(event.target.value);
  };

  return (
    <div className="page-container">
      <div
        className="open-access-models-on-server-browser-block-01"
      >
      <div className="open-access-models-on-server-browser-block-02">
        <h3 className="open-access-models-on-server-browser-h3">Open Access Models on Server</h3>
        <div className="open-access-models-on-server-browser-block-03">
          Browse server-bundled open-access model CSVs used by biomarker workflows.
        </div>
      </div>

      {loadingProjects ? <div>Loading model-enabled projects...</div> : null}

      {!loadingProjects && modelEnabledProjects.length === 0 ? (
        <div className="duality-text-muted">No model-enabled projects are available.</div>
      ) : null}

      {!loadingProjects && modelEnabledProjects.length > 0 ? (
        <>
          <div
            className="open-access-models-on-server-browser-block-04"
          >
            <label className="open-access-models-on-server-browser-shared-01">
              Project
              <select
                value={selectedProjectId}
                onChange={handleProjectChange}
                className="open-access-models-on-server-browser-shared-02"
              >
                {modelEnabledProjects.map((project) => (
                  <option key={project.id} value={String(project.id)}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="open-access-models-on-server-browser-shared-01">
              Datasource Group
              <select
                value={selectedGroupFolder}
                onChange={(event) => setSelectedGroupFolder(event.target.value)}
                disabled={!projectModelGroups.length}
                className="open-access-models-on-server-browser-shared-02"
              >
                {projectModelGroups.map((group) => (
                  <option key={group.folder} value={group.folder}>
                    {group.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="open-access-models-on-server-browser-shared-01">
              Model
              <select
                value={selectedModelKey}
                onChange={(event) => setSelectedModelKey(event.target.value as ModelKey)}
                disabled={!availableModelKeys.length}
                className="open-access-models-on-server-browser-shared-02"
              >
                {availableModelKeys.map((modelKey) => (
                  <option key={modelKey} value={modelKey}>
                    {MODEL_LABELS[modelKey]}
                  </option>
                ))}
              </select>
            </label>

            <label className="open-access-models-on-server-browser-shared-01">
              Cancer Type
              <select
                value={selectedCancerType}
                onChange={(event) => setSelectedCancerType(event.target.value)}
                disabled={!availableCancerTypes.length}
                className="open-access-models-on-server-browser-shared-02"
              >
                {availableCancerTypes.map((cancerType) => (
                  <option key={cancerType} value={cancerType}>
                    {cancerType}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {projectModelGroups.length === 0 ? (
            <div className="duality-text-muted">
              No public model manifest is configured for /models/project_{selectedProjectId}.
            </div>
          ) : (
            <>
              <div className="open-access-models-on-server-browser-block-05">
                <button
                  type="button"
                  onClick={() => setSelectedArtifactType("weights")}
                  className={selectedArtifactType === "weights" ? "primary-button" : "secondary-button"}
                >
                  View weights
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedArtifactType("cutoff")}
                  className={selectedArtifactType === "cutoff" ? "primary-button" : "secondary-button"}
                >
                  View cutoff
                </button>
                {selectedFileUrl ? (
                  <a
                    href={selectedFileUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="open-access-models-on-server-browser-a"
                  >
                    Open raw CSV
                  </a>
                ) : null}
              </div>

              <div className="open-access-models-on-server-browser-block-06">
                {selectedFileName}
              </div>

              {error ? <div className="open-access-models-on-server-browser-block-07">{error}</div> : null}
              {loadingCsv ? <div>Loading CSV...</div> : null}

              {!loadingCsv && hasHeader ? (
                <div className="open-access-models-on-server-browser-block-08">
                  <table className="open-access-models-on-server-browser-block-09">
                    <thead>
                      <tr>
                        {headerRow.map((cell, index) => (
                          <th
                            key={`${cell}-${index}`}
                            className="open-access-models-on-server-browser-block-10"
                          >
                            {cell || `Column ${index + 1}`}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {bodyRows.map((row, rowIndex) => (
                        <tr key={rowIndex}>
                          {headerRow.map((_, cellIndex) => (
                            <td
                              key={cellIndex}
                              className="open-access-models-on-server-browser-block-11"
                            >
                              {row[cellIndex] ?? ""}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </>
          )}
        </>
      ) : null}
      </div>
    </div>
  );
};

export default OpenAccessModelsOnServerBrowser;
