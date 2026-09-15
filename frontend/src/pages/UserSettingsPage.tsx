import React, { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AppScreen } from "../App";
import { API_BASE, API_PROJECTS_LIST } from "../constants/Constants";
import { useUserSession } from "../context/UserRoleContext";
import type { UserProjectDatasource, UserProjectAccess } from "../context/UserRoleContext";
import { Project } from "../types/Project";
import HeaderTitle from "../components/HeaderTitle";

const API_USER_DATASOURCE_APPLY = "/user/datasource/apply";
const API_USER_MODEL_FILES_LIST = "/user/model-files/list";
const API_USER_MODEL_FILES_APPLY = "/user/model-files/apply";

type DataSourceMode = "json_file" | "fhir_server";

type ProjectDatasourceGroup = NonNullable<Project["datasource_groups"]>[number];

interface UserSettingsPageProps {
  setMainScreen: (screen: AppScreen) => void;
  initialProjectId?: number | string | null;
  returnScreen: AppScreen;
}

interface DataSourceField {
  key: string;
  label: string;
  datasource_group_id: number | string | null;
  datasource_group_name: string | null;
  is_default_group: boolean;
}

interface DataSourceModeValues {
  json_file: string;
  fhir_server: string;
}

interface DataSourceSetting {
  mode: DataSourceMode;
  value: string;
  valuesByMode: DataSourceModeValues;
}

interface UserModelFileRecord {
  id?: number | string | null;
  user_id?: number | string | null;
  project_id: number | string;
  datasource_group?: number | string | null;
  datasource_group_id?: number | string | null;
  datasource_group_name?: string | null;
  is_default_group?: boolean | null;
  model_file_lookup_key: string;
  model_file_lookup_value: string;
  model_key: string;
  artifact_type: string;
  source: string;
}

type ModelFileLocationMode = "manual" | "pattern";

interface ModelFilePatternSettings {
  basePath: string;
  projectFolderPattern: string;
  datasourceGroupFolderPattern: string;
  filenamePatternsByArtifact: Record<string, string>;
}


function getGroupId(group: ProjectDatasourceGroup): number | string | null {
  return (group as { id?: number | string; datasource_group_id?: number | string }).id ??
    (group as { datasource_group_id?: number | string }).datasource_group_id ??
    null;
}

function getGroupName(group: ProjectDatasourceGroup): string {
  return (group as { group_name?: string }).group_name || "DEFAULT";
}

function getGroupDefaultFlag(group: ProjectDatasourceGroup): boolean {
  return Boolean((group as { is_default?: boolean }).is_default);
}

function buildDataSourceFields(project: Project | null): DataSourceField[] {
  if (!project) {
    return [];
  }

  const datasourceGroups = Array.isArray(project.datasource_groups) ? project.datasource_groups : [];
  const hasDatasourceGroups = Boolean(project.datasource_groups_defined && datasourceGroups.length > 0);

  if (!hasDatasourceGroups) {
    return [
      {
        key: "single-datasource",
        label: "Project Datasource",
        datasource_group_id: null,
        datasource_group_name: null,
        is_default_group: true
      }
    ];
  }

  return datasourceGroups.map((group, index) => {
    const groupId = getGroupId(group);
    const groupName = getGroupName(group);
    const isDefault = getGroupDefaultFlag(group);

    return {
      key: `group-${groupId ?? groupName}-${index}`,
      label: `${groupName}${isDefault ? " (Default)" : ""}`,
      datasource_group_id: groupId,
      datasource_group_name: groupName,
      is_default_group: isDefault
    };
  });
}

function createEmptyDataSourceSetting(): DataSourceSetting {
  return {
    mode: "json_file",
    value: "",
    valuesByMode: {
      json_file: "",
      fhir_server: ""
    }
  };
}

function createDataSourceSetting(mode: DataSourceMode, value: string): DataSourceSetting {
  return {
    mode,
    value,
    valuesByMode: {
      json_file: mode === "json_file" ? value : "",
      fhir_server: mode === "fhir_server" ? value : ""
    }
  };
}

function createInitialSettings(fields: DataSourceField[]): Record<string, DataSourceSetting> {
  return fields.reduce((acc, field) => {
    acc[field.key] = createEmptyDataSourceSetting();
    return acc;
  }, {} as Record<string, DataSourceSetting>);
}

function isValidJsonPath(value: string): boolean {
  return value.trim().toLowerCase().endsWith(".json");
}

function normalizeFhirUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function isValidFhirUrl(value: string): boolean {
  const normalizedValue = normalizeFhirUrl(value);

  if (!normalizedValue.toLowerCase().endsWith("/fhir")) {
    return false;
  }

  try {
    const url = new URL(normalizedValue);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function inferDataSourceMode(source: string): DataSourceMode {
  return source.trim().toLowerCase().endsWith(".json") ? "json_file" : "fhir_server";
}

function datasourceGroupIdsMatch(left: number | string | null, right: number | string | null): boolean {
  if (left == null && right == null) {
    return true;
  }

  if (left == null || right == null) {
    return false;
  }

  return String(left) === String(right);
}

function getModelFileRecordDatasourceGroupId(record: UserModelFileRecord): number | string | null {
  return record.datasource_group_id ?? record.datasource_group ?? null;
}

function modelFileRecordMatchesDatasourceField(record: UserModelFileRecord, field: DataSourceField): boolean {
  const recordDatasourceGroupId = getModelFileRecordDatasourceGroupId(record);

  if (datasourceGroupIdsMatch(recordDatasourceGroupId, field.datasource_group_id)) {
    return true;
  }

  if (!record.datasource_group_name || !field.datasource_group_name) {
    return false;
  }

  return record.datasource_group_name === field.datasource_group_name;
}

function getDatasourceForField(field: DataSourceField, datasources: UserProjectDatasource[]): UserProjectDatasource | null {
  if (!datasources.length) {
    return null;
  }

  const matchingGroup = datasources.find((datasource) => (
    datasourceGroupIdsMatch(datasource.datasource_group_id, field.datasource_group_id)
  ));

  if (matchingGroup) {
    return matchingGroup;
  }

  if (field.datasource_group_id == null) {
    return datasources.find((datasource) => datasource.datasource_group_id == null) ||
      datasources.find((datasource) => datasource.is_default_group) ||
      datasources[0];
  }

  return null;
}

function createSettingsFromUserDatasources(
  fields: DataSourceField[],
  datasources: UserProjectDatasource[]
): Record<string, DataSourceSetting> {
  const initialSettings = createInitialSettings(fields);

  fields.forEach((field) => {
    const datasource = getDatasourceForField(field, datasources);
    const source = datasource?.source?.trim() || "";

    if (!source) {
      return;
    }

    initialSettings[field.key] = createDataSourceSetting(inferDataSourceMode(source), source);
  });

  return initialSettings;
}

function normalizeDatasourceSettingForComparison(setting?: DataSourceSetting): Pick<DataSourceSetting, "mode" | "value"> {
  const mode = setting?.mode ?? "json_file";
  const value = setting?.value ?? "";

  return {
    mode,
    value: mode === "fhir_server" ? normalizeFhirUrl(value) : value.trim()
  };
}

function getCompleteDataSourceSetting(setting?: DataSourceSetting): DataSourceSetting {
  if (!setting) {
    return createEmptyDataSourceSetting();
  }

  const jsonValue = setting.valuesByMode?.json_file ?? (setting.mode === "json_file" ? setting.value : "");
  const fhirValue = setting.valuesByMode?.fhir_server ?? (setting.mode === "fhir_server" ? setting.value : "");

  return {
    mode: setting.mode,
    value: setting.value,
    valuesByMode: {
      json_file: jsonValue,
      fhir_server: fhirValue
    }
  };
}

function datasourceSettingHasChanged(
  field: DataSourceField,
  currentSettings: Record<string, DataSourceSetting>,
  initialSettings: Record<string, DataSourceSetting>
): boolean {
  const current = normalizeDatasourceSettingForComparison(currentSettings[field.key]);
  const initial = normalizeDatasourceSettingForComparison(initialSettings[field.key]);

  return current.mode !== initial.mode || current.value !== initial.value;
}

function datasourceSettingsHaveChanges(
  fields: DataSourceField[],
  currentSettings: Record<string, DataSourceSetting>,
  initialSettings: Record<string, DataSourceSetting>
): boolean {
  return fields.some((field) => datasourceSettingHasChanged(field, currentSettings, initialSettings));
}

function trimDataSourceSettings(
  fields: DataSourceField[],
  settings: Record<string, DataSourceSetting>
): Record<string, DataSourceSetting> {
  const trimmedSettings = { ...settings };

  fields.forEach((field) => {
    const setting = getCompleteDataSourceSetting(settings[field.key]);
    const trimmedValue = setting.value.trim();

    trimmedSettings[field.key] = {
      ...setting,
      value: trimmedValue,
      valuesByMode: {
        ...setting.valuesByMode,
        [setting.mode]: trimmedValue
      }
    };
  });

  return trimmedSettings;
}

function datasourceSettingsHavePendingTrim(
  fields: DataSourceField[],
  settings: Record<string, DataSourceSetting>
): boolean {
  return fields.some((field) => {
    const setting = getCompleteDataSourceSetting(settings[field.key]);
    return setting.value !== setting.value.trim();
  });
}

function waitForNextPaint(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
      setTimeout(resolve, 0);
      return;
    }

    window.requestAnimationFrame(() => resolve());
  });
}

function toNullableNumber(value: number | string | null): number | null {
  if (value == null || value === "") {
    return null;
  }

  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function getModelFileRecordKey(record: UserModelFileRecord): string {
  const datasourceGroupId = getModelFileRecordDatasourceGroupId(record) ?? "DEFAULT";
  return [
    record.project_id,
    datasourceGroupId,
    record.model_file_lookup_key,
    record.model_file_lookup_value,
    record.model_key,
    record.artifact_type
  ].map((value) => String(value ?? "")).join("::");
}

function createModelFileSettings(records: UserModelFileRecord[]): Record<string, string> {
  return records.reduce((acc, record) => {
    acc[getModelFileRecordKey(record)] = record.source || "";
    return acc;
  }, {} as Record<string, string>);
}

function trimModelFileSettings(
  records: UserModelFileRecord[],
  settings: Record<string, string>
): Record<string, string> {
  const trimmed = { ...settings };
  records.forEach((record) => {
    const key = getModelFileRecordKey(record);
    trimmed[key] = (settings[key] || "").trim();
  });
  return trimmed;
}

function modelFileSettingHasChanged(
  record: UserModelFileRecord,
  currentSettings: Record<string, string>,
  initialSettings: Record<string, string>
): boolean {
  const key = getModelFileRecordKey(record);
  return (currentSettings[key] || "").trim() !== (initialSettings[key] || "").trim();
}

function modelFileSettingsHaveChanges(
  records: UserModelFileRecord[],
  currentSettings: Record<string, string>,
  initialSettings: Record<string, string>
): boolean {
  return records.some((record) => modelFileSettingHasChanged(record, currentSettings, initialSettings));
}

function modelFileSettingsHavePendingTrim(
  records: UserModelFileRecord[],
  settings: Record<string, string>
): boolean {
  return records.some((record) => {
    const key = getModelFileRecordKey(record);
    const value = settings[key] || "";
    return value !== value.trim();
  });
}

function projectHasModelTypeSelector(project: Project | null): boolean {
  if (!project || !Array.isArray(project.functions)) {
    return false;
  }

  return project.functions.some((projectFunction) => {
    const variableConfig = projectFunction.custom_configuration_variable;
    if (!variableConfig || typeof variableConfig !== "object") {
      return false;
    }

    const modelTypeConfig = (variableConfig as Record<string, unknown>).model_type;
    if (!modelTypeConfig || typeof modelTypeConfig !== "object") {
      return false;
    }

    const modelType = (modelTypeConfig as { type?: unknown }).type;
    return typeof modelType === "string" && modelType.toLowerCase() === "select";
  });
}

function projectSupportsModelFileSettings(project: Project | null): boolean {
  return Boolean(project?.model_file_settings_enabled) || projectHasModelTypeSelector(project);
}

function formatModelKey(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatArtifactType(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function buildTemplateMarker(name: string): string {
  return ["$", "{", name, "}"].join("");
}

const PROJECT_ID_MARKER = buildTemplateMarker("project_id");
const DATASOURCE_GROUP_ID_MARKER = buildTemplateMarker("datasource_group_id");
const DATASOURCE_GROUP_NAME_MARKER = buildTemplateMarker("datasource_group_name");
const MODEL_KEY_MARKER = buildTemplateMarker("model_key");
const LOOKUP_KEY_MARKER = buildTemplateMarker("lookup_key");
const LOOKUP_VALUE_MARKER = buildTemplateMarker("lookup_value");
const ARTIFACT_TYPE_MARKER = buildTemplateMarker("artifact_type");

function createDefaultModelFilePatternSettings(): ModelFilePatternSettings {
  return {
    basePath: "/data/model_files/",
    projectFolderPattern: `project_${PROJECT_ID_MARKER}/`,
    datasourceGroupFolderPattern: `datasource_group_${DATASOURCE_GROUP_ID_MARKER}/`,
    filenamePatternsByArtifact: {
      weights: `${MODEL_KEY_MARKER}_${LOOKUP_VALUE_MARKER}_weights.csv`,
      cutoff: `${MODEL_KEY_MARKER}_${LOOKUP_VALUE_MARKER}_cutoff.csv`
    }
  };
}

function ensureModelFilePatternSettings(settings?: ModelFilePatternSettings): ModelFilePatternSettings {
  const defaults = createDefaultModelFilePatternSettings();

  return {
    basePath: settings?.basePath ?? defaults.basePath,
    projectFolderPattern: settings?.projectFolderPattern ?? defaults.projectFolderPattern,
    datasourceGroupFolderPattern: settings?.datasourceGroupFolderPattern ?? defaults.datasourceGroupFolderPattern,
    filenamePatternsByArtifact: {
      ...defaults.filenamePatternsByArtifact,
      ...(settings?.filenamePatternsByArtifact || {})
    }
  };
}

function getDefaultFilenamePatternForArtifact(artifactType: string): string {
  return `${MODEL_KEY_MARKER}_${LOOKUP_VALUE_MARKER}_${ARTIFACT_TYPE_MARKER}.csv`.replace(ARTIFACT_TYPE_MARKER, artifactType);
}

function getModelFileArtifactTypes(records: UserModelFileRecord[]): string[] {
  const artifactTypes = Array.from(new Set(records.map((record) => record.artifact_type).filter(Boolean)));
  const priority = ["weights", "cutoff"];

  return artifactTypes.sort((left, right) => {
    const leftIndex = priority.indexOf(left);
    const rightIndex = priority.indexOf(right);

    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? priority.length : leftIndex) - (rightIndex === -1 ? priority.length : rightIndex);
    }

    return left.localeCompare(right);
  });
}

function getDefaultModelFileName(record: UserModelFileRecord): string {
  return `${record.model_key}_${record.model_file_lookup_value}_${record.artifact_type}.csv`;
}

function expandModelFilePattern(
  pattern: string,
  project: Project,
  datasourceField: DataSourceField,
  record: UserModelFileRecord
): string {
  const tokenValues: Record<string, string> = {
    project_id: String(project.id),
    datasource_group_id: String(datasourceField.datasource_group_id ?? "default"),
    datasource_group_name: datasourceField.datasource_group_name || "DEFAULT",
    lookup_key: record.model_file_lookup_key,
    lookup_value: record.model_file_lookup_value,
    model_key: record.model_key,
    artifact_type: record.artifact_type
  };

  return pattern.replace(/\$\{([a-zA-Z0-9_]+)\}/g, (_match, token: string) => tokenValues[token] ?? "");
}

function withTrailingSlash(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  return `${trimmed.replace(/\/+$/, "")}/`;
}

function relativeFolderWithTrailingSlash(value: string): string {
  const trimmed = value.trim().replace(/^\/+/, "").replace(/\/+$/, "");
  return trimmed ? `${trimmed}/` : "";
}

function relativeFilename(value: string): string {
  return value.trim().replace(/^\/+/, "");
}

function buildDerivedModelFileSource(
  project: Project,
  datasourceField: DataSourceField,
  record: UserModelFileRecord,
  patternSettings: ModelFilePatternSettings
): string {
  const completePatternSettings = ensureModelFilePatternSettings(patternSettings);
  const filenamePattern = completePatternSettings.filenamePatternsByArtifact[record.artifact_type] ||
    getDefaultFilenamePatternForArtifact(record.artifact_type);

  return [
    withTrailingSlash(expandModelFilePattern(completePatternSettings.basePath, project, datasourceField, record)),
    relativeFolderWithTrailingSlash(expandModelFilePattern(completePatternSettings.projectFolderPattern, project, datasourceField, record)),
    relativeFolderWithTrailingSlash(expandModelFilePattern(completePatternSettings.datasourceGroupFolderPattern, project, datasourceField, record)),
    relativeFilename(expandModelFilePattern(filenamePattern, project, datasourceField, record))
  ].join("");
}

function splitModelFileSourcePath(source: string, fileName: string): {
  basePath: string;
  projectFolder: string;
  datasourceGroupFolder: string;
} | null {
  const normalizedSource = String(source || "").trim().replace(/\\/g, "/");
  const normalizedFileName = String(fileName || "").trim().replace(/\\/g, "/").split("/").pop() || "";

  if (!normalizedSource || !normalizedFileName || !normalizedSource.endsWith(`/${normalizedFileName}`)) {
    return null;
  }

  const directory = normalizedSource.slice(0, normalizedSource.length - normalizedFileName.length).replace(/\/+$/, "");
  const rawParts = directory.split("/");
  const parts = rawParts.filter(Boolean);

  if (parts.length < 2) {
    return null;
  }

  const projectFolder = parts[parts.length - 2];
  const datasourceGroupFolder = parts[parts.length - 1];
  const baseParts = parts.slice(0, -2);
  const startsWithSlash = directory.startsWith("/");
  const basePath = `${startsWithSlash ? "/" : ""}${baseParts.join("/")}`;

  return {
    basePath: withTrailingSlash(basePath),
    projectFolder,
    datasourceGroupFolder
  };
}

function getProjectFolderPatternFromActual(project: Project, projectFolder: string): string {
  const expected = `project_${project.id}`;
  return projectFolder === expected ? `project_${PROJECT_ID_MARKER}/` : `${projectFolder}/`;
}

function getDatasourceGroupFolderPatternFromActual(datasourceField: DataSourceField, datasourceGroupFolder: string): string {
  const groupId = datasourceField.datasource_group_id;
  const expected = groupId === null || groupId === undefined ? "datasource_group_default" : `datasource_group_${groupId}`;
  return datasourceGroupFolder === expected ? `datasource_group_${DATASOURCE_GROUP_ID_MARKER}/` : `${datasourceGroupFolder}/`;
}

function inferModelFilePatternSettings(
  project: Project,
  datasourceField: DataSourceField,
  records: UserModelFileRecord[],
  currentSettings: Record<string, string>
): ModelFilePatternSettings {
  const defaults = createDefaultModelFilePatternSettings();
  const parsedPaths = records
    .map((record) => {
      const key = getModelFileRecordKey(record);
      const source = currentSettings[key] ?? record.source ?? "";
      return splitModelFileSourcePath(source, getDefaultModelFileName(record));
    })
    .filter((value): value is NonNullable<typeof value> => value !== null);

  if (!parsedPaths.length || parsedPaths.length !== records.length) {
    return defaults;
  }

  const firstPath = parsedPaths[0];
  const hasCommonBase = parsedPaths.every((path) => path.basePath === firstPath.basePath);
  const hasCommonProjectFolder = parsedPaths.every((path) => path.projectFolder === firstPath.projectFolder);
  const hasCommonDatasourceGroupFolder = parsedPaths.every((path) => path.datasourceGroupFolder === firstPath.datasourceGroupFolder);

  if (!hasCommonBase || !hasCommonProjectFolder || !hasCommonDatasourceGroupFolder) {
    return defaults;
  }

  return {
    basePath: firstPath.basePath || defaults.basePath,
    projectFolderPattern: getProjectFolderPatternFromActual(project, firstPath.projectFolder),
    datasourceGroupFolderPattern: getDatasourceGroupFolderPatternFromActual(datasourceField, firstPath.datasourceGroupFolder),
    filenamePatternsByArtifact: defaults.filenamePatternsByArtifact
  };
}

const UserSettingsPage: React.FC<UserSettingsPageProps> = () => {
  const userSession = useUserSession();
  const [animate, setAnimate] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedDatasourceGroupKey, setSelectedDatasourceGroupKey] = useState("");
  const [datasourceSettings, setDatasourceSettings] = useState<Record<string, DataSourceSetting>>({});
  const [initialDatasourceSettings, setInitialDatasourceSettings] = useState<Record<string, DataSourceSetting>>({});
  const [modelFileRecords, setModelFileRecords] = useState<UserModelFileRecord[]>([]);
  const [modelFileSettings, setModelFileSettings] = useState<Record<string, string>>({});
  const [initialModelFileSettings, setInitialModelFileSettings] = useState<Record<string, string>>({});
  const [modelFileLocationModes, setModelFileLocationModes] = useState<Record<string, ModelFileLocationMode>>({});
  const [initialModelFileLocationModes, setInitialModelFileLocationModes] = useState<Record<string, ModelFileLocationMode>>({});
  const [modelFilePatternSettingsByGroup, setModelFilePatternSettingsByGroup] = useState<Record<string, ModelFilePatternSettings>>({});
  const [initialModelFilePatternSettingsByGroup, setInitialModelFilePatternSettingsByGroup] = useState<Record<string, ModelFilePatternSettings>>({});
  const [modelFilesLoading, setModelFilesLoading] = useState(false);
  const [modelFilesError, setModelFilesError] = useState("");
  const [sessionProjects, setSessionProjects] = useState<UserProjectAccess[]>(userSession.projects);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [applyError, setApplyError] = useState("");
  const [applySaving, setApplySaving] = useState(false);
  const [settingsUpdateNoticeState, setSettingsUpdateNoticeState] = useState<"hidden" | "visible" | "fading">("hidden");
  const [settingsUpdateNoticeMessage, setSettingsUpdateNoticeMessage] = useState("User settings updated");
  const settingsUpdateNoticeTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearSettingsUpdateNoticeTimers = useCallback(() => {
    settingsUpdateNoticeTimersRef.current.forEach((timerId) => clearTimeout(timerId));
    settingsUpdateNoticeTimersRef.current = [];
  }, []);

  const hideSettingsUpdateNotice = useCallback(() => {
    clearSettingsUpdateNoticeTimers();
    setSettingsUpdateNoticeState("hidden");
  }, [clearSettingsUpdateNoticeTimers]);

  const showSettingsUpdateNotice = useCallback((message: string) => {
    clearSettingsUpdateNoticeTimers();
    setSettingsUpdateNoticeMessage(message);
    setSettingsUpdateNoticeState("visible");
    settingsUpdateNoticeTimersRef.current = [
      setTimeout(() => setSettingsUpdateNoticeState("fading"), 4000),
      setTimeout(() => setSettingsUpdateNoticeState("hidden"), 4600)
    ];
  }, [clearSettingsUpdateNoticeTimers]);

  useEffect(() => {
    setAnimate(false);
    const timerId = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(timerId);
  }, []);

  useEffect(() => {
    return () => clearSettingsUpdateNoticeTimers();
  }, [clearSettingsUpdateNoticeTimers]);

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
        setLoading(false);
        return;
      }

      const data = await res.json();
      if (data && Array.isArray(data.projects)) {
        setProjects(data.projects.map((project: Project) => ({
          ...project,
          filter_schemas: project.filter_schemas || {}
        })));
      } else {
        setError("Invalid response from server");
      }
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    setSessionProjects(userSession.projects);
  }, [userSession.projects]);

  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(String(projects[0].id));
    }
  }, [projects, selectedProjectId]);

  const selectedProject = useMemo(() => {
    return projects.find((project) => String(project.id) === selectedProjectId) || null;
  }, [projects, selectedProjectId]);

  const datasourceFields = useMemo(() => buildDataSourceFields(selectedProject), [selectedProject]);

  useEffect(() => {
    if (!datasourceFields.length) {
      setSelectedDatasourceGroupKey("");
      return;
    }

    setSelectedDatasourceGroupKey((currentGroupKey) => {
      if (currentGroupKey && datasourceFields.some((field) => field.key === currentGroupKey)) {
        return currentGroupKey;
      }

      return datasourceFields[0].key;
    });
  }, [datasourceFields]);

  const selectedDatasourceField = useMemo(() => {
    return datasourceFields.find((field) => field.key === selectedDatasourceGroupKey) || null;
  }, [datasourceFields, selectedDatasourceGroupKey]);

  const selectedProjectDatasources = useMemo(() => {
    if (!selectedProject) {
      return [];
    }

    const projectEntry = sessionProjects.find((entry) => String(entry.project_id) === String(selectedProject.id));

    if (projectEntry) {
      return projectEntry.datasources || [];
    }

    if (userSession.selected_project_id != null && String(userSession.selected_project_id) === String(selectedProject.id)) {
      return userSession.selected_project_datasources || [];
    }

    return [];
  }, [selectedProject, sessionProjects, userSession.selected_project_datasources, userSession.selected_project_id]);

  useEffect(() => {
    const nextSettings = createSettingsFromUserDatasources(datasourceFields, selectedProjectDatasources);

    setDatasourceSettings(nextSettings);
    setInitialDatasourceSettings(nextSettings);
    setApplyError("");
  }, [datasourceFields, selectedProjectDatasources]);

  const isInitiator = String(userSession.role || "").toUpperCase() === "INITIATOR";

  const selectedProjectSupportsModelFileSettings = useMemo(() => (
    projectSupportsModelFileSettings(selectedProject)
  ), [selectedProject]);

  const shouldShowModelFileSettings = Boolean(
    isInitiator && selectedProject && selectedProjectSupportsModelFileSettings
  );

  const selectedDatasourceGroupModelFileRecords = useMemo(() => {
    if (!selectedDatasourceField) {
      return [];
    }

    return modelFileRecords.filter((record) => modelFileRecordMatchesDatasourceField(record, selectedDatasourceField));
  }, [modelFileRecords, selectedDatasourceField]);

  const selectedModelFileLocationMode = selectedDatasourceField
    ? modelFileLocationModes[selectedDatasourceField.key] || "manual"
    : "manual";

  const selectedModelFilePatternSettings = selectedDatasourceField
    ? ensureModelFilePatternSettings(modelFilePatternSettingsByGroup[selectedDatasourceField.key])
    : createDefaultModelFilePatternSettings();

  const selectedModelFileArtifactTypes = useMemo(() => (
    getModelFileArtifactTypes(selectedDatasourceGroupModelFileRecords)
  ), [selectedDatasourceGroupModelFileRecords]);

  useEffect(() => {
    if (!selectedProject || !shouldShowModelFileSettings) {
      setModelFileRecords([]);
      setModelFileSettings({});
      setInitialModelFileSettings({});
      setModelFileLocationModes({});
      setInitialModelFileLocationModes({});
      setModelFilePatternSettingsByGroup({});
      setInitialModelFilePatternSettingsByGroup({});
      setModelFilesLoading(false);
      setModelFilesError("");
      return;
    }

    const projectId = toNullableNumber(selectedProject.id);
    if (projectId == null) {
      setModelFilesError("Selected project is missing a valid project id.");
      return;
    }

    let cancelled = false;
    setModelFilesLoading(true);
    setModelFilesError("");

    const payload = {
      ...(userSession.user_id != null ? { user_id: userSession.user_id } : { username: userSession.username }),
      project_id: projectId
    };

    fetch(`${API_BASE}${API_USER_MODEL_FILES_LIST}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
          throw new Error(data.error || "Failed to load model file settings.");
        }

        return data;
      })
      .then((data) => {
        if (cancelled) {
          return;
        }

        const records = Array.isArray(data.records) ? data.records : [];
        const nextSettings = createModelFileSettings(records);
        setModelFileRecords(records);
        setModelFileSettings(nextSettings);
        setInitialModelFileSettings(nextSettings);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setModelFileRecords([]);
          setModelFileSettings({});
          setInitialModelFileSettings({});
          setModelFilesError(err.message || "Failed to load model file settings.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setModelFilesLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedProject, shouldShowModelFileSettings, userSession.user_id, userSession.username]);

  useEffect(() => {
    if (!selectedProject || !shouldShowModelFileSettings || !modelFileRecords.length) {
      return;
    }

    setModelFileSettings((previousSettings) => {
      let nextSettings = previousSettings;

      datasourceFields.forEach((field) => {
        if ((modelFileLocationModes[field.key] || "manual") !== "pattern") {
          return;
        }

        const patternSettings = ensureModelFilePatternSettings(modelFilePatternSettingsByGroup[field.key]);
        const recordsForField = modelFileRecords.filter((record) => modelFileRecordMatchesDatasourceField(record, field));

        recordsForField.forEach((record) => {
          const key = getModelFileRecordKey(record);
          const derivedSource = buildDerivedModelFileSource(selectedProject, field, record, patternSettings);

          if ((nextSettings[key] || "") !== derivedSource) {
            if (nextSettings === previousSettings) {
              nextSettings = { ...previousSettings };
            }
            nextSettings[key] = derivedSource;
          }
        });
      });

      return nextSettings;
    });
  }, [
    datasourceFields,
    modelFileLocationModes,
    modelFilePatternSettingsByGroup,
    modelFileRecords,
    selectedProject,
    shouldShowModelFileSettings
  ]);

  const hasDatasourceChanges = useMemo(() => (
    datasourceSettingsHaveChanges(datasourceFields, datasourceSettings, initialDatasourceSettings)
  ), [datasourceFields, datasourceSettings, initialDatasourceSettings]);

  const hasPendingDatasourceTrim = useMemo(() => (
    datasourceSettingsHavePendingTrim(datasourceFields, datasourceSettings)
  ), [datasourceFields, datasourceSettings]);

  const hasModelFileChanges = useMemo(() => (
    shouldShowModelFileSettings && modelFileSettingsHaveChanges(modelFileRecords, modelFileSettings, initialModelFileSettings)
  ), [shouldShowModelFileSettings, modelFileRecords, modelFileSettings, initialModelFileSettings]);

  const hasPendingModelFileTrim = useMemo(() => (
    shouldShowModelFileSettings && modelFileSettingsHavePendingTrim(modelFileRecords, modelFileSettings)
  ), [shouldShowModelFileSettings, modelFileRecords, modelFileSettings]);

  const isApplyDisabled = applySaving || modelFilesLoading || !selectedProject || (
    !hasDatasourceChanges &&
    !hasPendingDatasourceTrim &&
    !hasModelFileChanges &&
    !hasPendingModelFileTrim
  );

  const handleCancel = () => {
    hideSettingsUpdateNotice();
    setApplyError("");
    setDatasourceSettings({ ...initialDatasourceSettings });
    setModelFileSettings({ ...initialModelFileSettings });
    setModelFileLocationModes({ ...initialModelFileLocationModes });
    setModelFilePatternSettingsByGroup({ ...initialModelFilePatternSettingsByGroup });
  };

  const updateDatasourceValue = (fieldKey: string, value: string) => {
    setDatasourceSettings((prev) => {
      const current = getCompleteDataSourceSetting(prev[fieldKey]);

      return {
        ...prev,
        [fieldKey]: {
          ...current,
          value,
          valuesByMode: {
            ...current.valuesByMode,
            [current.mode]: value
          }
        }
      };
    });
  };

  const updateModelFileValue = (record: UserModelFileRecord, value: string) => {
    const key = getModelFileRecordKey(record);
    setModelFileSettings((prev) => ({
      ...prev,
      [key]: value
    }));
  };

  const updateSelectedModelFilePattern = (updates: Partial<Omit<ModelFilePatternSettings, "filenamePatternsByArtifact">>) => {
    if (!selectedDatasourceField) {
      return;
    }

    hideSettingsUpdateNotice();
    setModelFilePatternSettingsByGroup((prev) => {
      const current = ensureModelFilePatternSettings(prev[selectedDatasourceField.key]);
      return {
        ...prev,
        [selectedDatasourceField.key]: {
          ...current,
          ...updates
        }
      };
    });
  };

  const updateSelectedModelFileFilenamePattern = (artifactType: string, value: string) => {
    if (!selectedDatasourceField) {
      return;
    }

    hideSettingsUpdateNotice();
    setModelFilePatternSettingsByGroup((prev) => {
      const current = ensureModelFilePatternSettings(prev[selectedDatasourceField.key]);
      return {
        ...prev,
        [selectedDatasourceField.key]: {
          ...current,
          filenamePatternsByArtifact: {
            ...current.filenamePatternsByArtifact,
            [artifactType]: value
          }
        }
      };
    });
  };

  const handleModelFileLocationModeChange = (mode: ModelFileLocationMode) => {
    if (!selectedDatasourceField || !selectedProject) {
      return;
    }

    hideSettingsUpdateNotice();
    setModelFileLocationModes((prev) => ({
      ...prev,
      [selectedDatasourceField.key]: mode
    }));

    if (mode === "pattern") {
      setModelFilePatternSettingsByGroup((prev) => ({
        ...prev,
        [selectedDatasourceField.key]: prev[selectedDatasourceField.key]
          ? ensureModelFilePatternSettings(prev[selectedDatasourceField.key])
          : inferModelFilePatternSettings(
            selectedProject,
            selectedDatasourceField,
            selectedDatasourceGroupModelFileRecords,
            modelFileSettings,
          )
      }));
    }
  };

  const handleProjectChange = (event: ChangeEvent<HTMLSelectElement>) => {
    hideSettingsUpdateNotice();
    setSelectedProjectId(event.target.value);
    setModelFileLocationModes({});
    setInitialModelFileLocationModes({});
    setModelFilePatternSettingsByGroup({});
    setInitialModelFilePatternSettingsByGroup({});
  };

  const handleDatasourceGroupChange = (event: ChangeEvent<HTMLSelectElement>) => {
    hideSettingsUpdateNotice();
    setSelectedDatasourceGroupKey(event.target.value);
  };

  const handleModeChange = (fieldKey: string, mode: DataSourceMode) => {
    setDatasourceSettings((prev) => {
      const current = getCompleteDataSourceSetting(prev[fieldKey]);
      const valuesByMode = {
        ...current.valuesByMode,
        [current.mode]: current.value
      };

      return {
        ...prev,
        [fieldKey]: {
          mode,
          value: valuesByMode[mode],
          valuesByMode
        }
      };
    });
  };

  const handleApply = async () => {
    setApplyError("");
    hideSettingsUpdateNotice();

    if (!selectedProject) {
      setApplyError("Select a project before applying settings.");
      return;
    }

    const projectId = toNullableNumber(selectedProject.id);

    if (projectId == null) {
      setApplyError("Selected project is missing a valid project id.");
      return;
    }

    const trimmedDatasourceSettings = trimDataSourceSettings(datasourceFields, datasourceSettings);
    const settingsWereTrimmed = datasourceSettingsHavePendingTrim(datasourceFields, datasourceSettings);
    const trimmedModelFileSettings = trimModelFileSettings(modelFileRecords, modelFileSettings);
    const modelFilesWereTrimmed = modelFileSettingsHavePendingTrim(modelFileRecords, modelFileSettings);

    if (settingsWereTrimmed) {
      setDatasourceSettings(trimmedDatasourceSettings);
    }

    if (modelFilesWereTrimmed) {
      setModelFileSettings(trimmedModelFileSettings);
    }

    if (settingsWereTrimmed || modelFilesWereTrimmed) {
      await waitForNextPaint();
    }

    const changedFields = datasourceFields.filter((field) => (
      datasourceSettingHasChanged(field, trimmedDatasourceSettings, initialDatasourceSettings)
    ));

    const changedModelFileRecords = shouldShowModelFileSettings
      ? modelFileRecords.filter((record) => (
        modelFileSettingHasChanged(record, trimmedModelFileSettings, initialModelFileSettings)
      ))
      : [];

    if (!changedFields.length && !changedModelFileRecords.length) {
      showSettingsUpdateNotice("No changes detected");
      return;
    }

    const invalidField = changedFields.find((field) => {
      const setting = getCompleteDataSourceSetting(trimmedDatasourceSettings[field.key]);
      return setting.mode === "json_file" ? !isValidJsonPath(setting.value) : !isValidFhirUrl(setting.value);
    });

    if (invalidField) {
      const setting = getCompleteDataSourceSetting(trimmedDatasourceSettings[invalidField.key]);
      setApplyError(
        setting.mode === "json_file"
          ? `Enter a JSON file path ending in .json for ${invalidField.label}.`
          : `Enter a valid FHIR server URL ending in /fhir for ${invalidField.label}.`
      );
      return;
    }

    const invalidModelFileRecord = changedModelFileRecords.find((record) => {
      const key = getModelFileRecordKey(record);
      return !(trimmedModelFileSettings[key] || "").trim();
    });

    if (invalidModelFileRecord) {
      setApplyError(
        `Enter a model file location for ${invalidModelFileRecord.model_file_lookup_value} ` +
        `${formatModelKey(invalidModelFileRecord.model_key)} ${formatArtifactType(invalidModelFileRecord.artifact_type)}.`
      );
      return;
    }

    const datasourceUpdates = changedFields.map((field) => {
      const setting = getCompleteDataSourceSetting(trimmedDatasourceSettings[field.key]);
      const source = setting.mode === "fhir_server" ? normalizeFhirUrl(setting.value) : setting.value.trim();

      return {
        project_id: projectId,
        datasource_group_id: toNullableNumber(field.datasource_group_id),
        source
      };
    });

    const modelFileUpdates = changedModelFileRecords.map((record) => {
      const key = getModelFileRecordKey(record);
      return {
        project_id: projectId,
        datasource_group_id: toNullableNumber(record.datasource_group_id ?? record.datasource_group ?? null),
        model_file_lookup_key: record.model_file_lookup_key,
        model_file_lookup_value: record.model_file_lookup_value,
        model_key: record.model_key,
        artifact_type: record.artifact_type,
        source: (trimmedModelFileSettings[key] || "").trim()
      };
    });

    const userIdentityPayload = userSession.user_id != null
      ? { user_id: userSession.user_id }
      : { username: userSession.username };

    setApplySaving(true);

    try {
      if (datasourceUpdates.length) {
        const datasourcePayload = {
          ...userIdentityPayload,
          updates: datasourceUpdates
        };

        const res = await fetch(`${API_BASE}${API_USER_DATASOURCE_APPLY}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(datasourcePayload)
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
          setApplyError(data.error || "Failed to apply datasource settings.");
          return;
        }

        if (Array.isArray(data.projects)) {
          setSessionProjects(data.projects);

          const refreshedProject = data.projects.find((entry: { project_id: number | string }) => (
            String(entry.project_id) === String(projectId)
          ));
          const refreshedDatasources = refreshedProject?.datasources || [];
          const refreshedSettings = createSettingsFromUserDatasources(datasourceFields, refreshedDatasources);

          setDatasourceSettings(refreshedSettings);
          setInitialDatasourceSettings(refreshedSettings);
        } else {
          const submittedSettings = { ...trimmedDatasourceSettings };

          changedFields.forEach((field) => {
            const setting = getCompleteDataSourceSetting(submittedSettings[field.key]);
            const source = setting.mode === "fhir_server" ? normalizeFhirUrl(setting.value) : setting.value.trim();

            submittedSettings[field.key] = {
              ...setting,
              value: source,
              valuesByMode: {
                ...setting.valuesByMode,
                [setting.mode]: source
              }
            };
          });

          setDatasourceSettings(submittedSettings);
          setInitialDatasourceSettings(submittedSettings);
        }
      }

      if (modelFileUpdates.length) {
        const modelFilePayload = {
          ...userIdentityPayload,
          updates: modelFileUpdates
        };

        const res = await fetch(`${API_BASE}${API_USER_MODEL_FILES_APPLY}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(modelFilePayload)
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
          setApplyError(data.error || "Failed to apply model file settings.");
          return;
        }

        const refreshedModelFileSources = data.model_file_sources_by_project?.[String(projectId)];
        const refreshedRecords = Array.isArray(refreshedModelFileSources?.records)
          ? refreshedModelFileSources.records
          : modelFileRecords.map((record) => ({
            ...record,
            source: trimmedModelFileSettings[getModelFileRecordKey(record)] || record.source
          }));

        const refreshedModelFileSettings = createModelFileSettings(refreshedRecords);
        setModelFileRecords(refreshedRecords);
        setModelFileSettings(refreshedModelFileSettings);
        setInitialModelFileSettings(refreshedModelFileSettings);
      }

      setInitialModelFileLocationModes({ ...modelFileLocationModes });
      setInitialModelFilePatternSettingsByGroup({ ...modelFilePatternSettingsByGroup });
      showSettingsUpdateNotice("User settings updated");
    } catch {
      setApplyError("Network error while saving user settings.");
    } finally {
      setApplySaving(false);
    }
  };

  return (
    <section className="project-workspace-tool-panel user-settings-workspace-panel" aria-label="User settings">
      <div className={`function-container ${animate ? "animate-in" : ""}`}>
        <HeaderTitle
          contained
          iconPath="/icons/nav_icon_user_settings.png"
          title={<>User Settings</>}
          description="Configure project datasource and model file settings for the current user."
        />

        <div className="page-container">
          <div className="child-container-top user-settings-content">
            {loading && <div className="user-settings-state-message">Loading projects...</div>}

            {!loading && error && (
              <div className="user-settings-state-message user-settings-error">{error}</div>
            )}

            {!loading && !error && projects.length === 0 && (
              <div className="user-settings-state-message">No projects available.</div>
            )}

            {!loading && !error && projects.length > 0 && (
              <>
                {settingsUpdateNoticeState !== "hidden" ? (
                  <div
                    className={`user-settings-notice ${settingsUpdateNoticeState === "fading" ? "fading" : ""}`}
                  >
                    {settingsUpdateNoticeMessage}
                  </div>
                ) : null}

                <section className="user-settings-section user-settings-section-first">
                  <div className="user-settings-section-heading">
                    <div>
                      <h3>Project Selection</h3>
                      <p>Select the project and datasource group whose user-specific settings you want to configure.</p>
                    </div>
                  </div>

                  <div className="user-settings-context-grid">
                    <div className="user-settings-field">
                      <label htmlFor="user-settings-project-select">Project</label>
                      <select
                        id="user-settings-project-select"
                        value={selectedProjectId}
                        onChange={handleProjectChange}
                      >
                        {projects.map((project) => (
                          <option key={project.id} value={String(project.id)}>
                            {project.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="user-settings-field">
                      <label htmlFor="user-settings-datasource-group-select">Datasource Group</label>
                      <select
                        id="user-settings-datasource-group-select"
                        value={selectedDatasourceGroupKey}
                        onChange={handleDatasourceGroupChange}
                        disabled={!selectedProject || datasourceFields.length === 0}
                      >
                        {!selectedProject || datasourceFields.length === 0 ? (
                          <option value="">Select a project first</option>
                        ) : null}
                        {datasourceFields.map((field) => (
                          <option key={field.key} value={field.key}>
                            {field.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </section>

                {selectedProject ? (
                  <>
                    <section aria-labelledby="datasource-settings-heading" className="user-settings-section">
                      <div className="user-settings-section-heading">
                        <div>
                          <h3 id="datasource-settings-heading">Datasource Group Location</h3>
                          <p>Choose whether this user's selected datasource group is read from a local JSON bundle or a FHIR server.</p>
                        </div>
                      </div>

                      {selectedDatasourceField ? [selectedDatasourceField].map((field) => {
                        const setting = getCompleteDataSourceSetting(datasourceSettings[field.key]);
                        const isJsonFile = setting.mode === "json_file";

                        return (
                          <div key={field.key} className="user-settings-config-panel">
                            <div className="user-settings-config-panel-heading">
                              <div>
                                <strong>{field.datasource_group_name || field.label}</strong>
                                <span>
                                  {field.datasource_group_name
                                    ? (field.is_default_group ? "Default datasource group" : "Datasource group")
                                    : "Project datasource"}
                                </span>
                              </div>
                            </div>

                            <div className="user-settings-choice-row" role="radiogroup" aria-label={`${field.label} source type`}>
                              <label className={`user-settings-choice ${setting.mode === "json_file" ? "selected" : ""}`}>
                                <input
                                  type="radio"
                                  name={`${field.key}-source-type`}
                                  checked={setting.mode === "json_file"}
                                  onChange={() => handleModeChange(field.key, "json_file")}
                                />
                                <span>JSON file</span>
                              </label>

                              <label className={`user-settings-choice ${setting.mode === "fhir_server" ? "selected" : ""}`}>
                                <input
                                  type="radio"
                                  name={`${field.key}-source-type`}
                                  checked={setting.mode === "fhir_server"}
                                  onChange={() => handleModeChange(field.key, "fhir_server")}
                                />
                                <span>FHIR server URL</span>
                              </label>
                            </div>

                            <div className="user-settings-field user-settings-field-wide">
                              <label htmlFor={`user-settings-datasource-location-${field.key}`}>
                                {isJsonFile ? "JSON bundle location" : "FHIR server URL"}
                              </label>
                              <input
                                id={`user-settings-datasource-location-${field.key}`}
                                type="text"
                                value={setting.value}
                                onChange={(event) => updateDatasourceValue(field.key, event.target.value)}
                                placeholder={isJsonFile ? "Enter a local JSON file path ending in .json" : "https://example.org/fhir"}
                              />
                            </div>
                          </div>
                        );
                      }) : (
                        <div className="user-settings-empty">Select a datasource group to edit its location.</div>
                      )}
                    </section>

                    {shouldShowModelFileSettings ? (
                      <section aria-labelledby="model-file-settings-heading" className="user-settings-section user-settings-section-last">
                        <div className="user-settings-section-heading">
                          <div>
                            <h3 id="model-file-settings-heading">Model File Locations</h3>
                            <p>Configure initiator-local model files for this datasource group, either individually or from a reusable path pattern.</p>
                          </div>
                          {!modelFilesLoading && !modelFilesError && selectedDatasourceGroupModelFileRecords.length > 0 ? (
                            <span className="user-settings-section-count">{selectedDatasourceGroupModelFileRecords.length}</span>
                          ) : null}
                        </div>

                        {modelFilesLoading ? (
                          <div className="user-settings-state-message user-settings-state-message-inline">Loading model file settings...</div>
                        ) : null}

                        {!modelFilesLoading && modelFilesError ? (
                          <div className="user-settings-error">{modelFilesError}</div>
                        ) : null}

                        {!modelFilesLoading && !modelFilesError && selectedDatasourceGroupModelFileRecords.length === 0 ? (
                          <div className="user-settings-empty">No model file settings were found for the selected datasource group.</div>
                        ) : null}

                        {!modelFilesLoading && !modelFilesError && selectedDatasourceGroupModelFileRecords.length > 0 ? (
                          <>
                            <div className="user-settings-config-panel user-settings-model-mode-panel">
                              <div className="user-settings-config-panel-heading">
                                <div>
                                  <strong>Location Strategy</strong>
                                  <span>Set each path directly or derive all paths from a shared pattern.</span>
                                </div>
                              </div>

                              <div className="user-settings-choice-row">
                                <label className={`user-settings-choice ${selectedModelFileLocationMode === "manual" ? "selected" : ""}`}>
                                  <input
                                    type="radio"
                                    name={`${selectedDatasourceField?.key || "model-file"}-location-mode`}
                                    checked={selectedModelFileLocationMode === "manual"}
                                    onChange={() => handleModelFileLocationModeChange("manual")}
                                  />
                                  <span>Set each location</span>
                                </label>

                                <label className={`user-settings-choice ${selectedModelFileLocationMode === "pattern" ? "selected" : ""}`}>
                                  <input
                                    type="radio"
                                    name={`${selectedDatasourceField?.key || "model-file"}-location-mode`}
                                    checked={selectedModelFileLocationMode === "pattern"}
                                    onChange={() => handleModelFileLocationModeChange("pattern")}
                                  />
                                  <span>Derive from pattern</span>
                                </label>
                              </div>

                              {selectedModelFileLocationMode === "pattern" ? (
                                <div className="user-settings-pattern-panel">
                                  <div className="user-settings-pattern-grid">
                                    <div className="user-settings-field">
                                      <label htmlFor="model-file-base-path">Parent location</label>
                                      <input
                                        id="model-file-base-path"
                                        type="text"
                                        value={selectedModelFilePatternSettings.basePath}
                                        onChange={(event) => updateSelectedModelFilePattern({ basePath: event.target.value })}
                                        placeholder="/data/model_files/"
                                      />
                                    </div>

                                    <div className="user-settings-field">
                                      <label htmlFor="model-file-project-folder">Project folder</label>
                                      <input
                                        id="model-file-project-folder"
                                        type="text"
                                        value={selectedModelFilePatternSettings.projectFolderPattern}
                                        onChange={(event) => updateSelectedModelFilePattern({ projectFolderPattern: event.target.value })}
                                        placeholder={`project_${PROJECT_ID_MARKER}/`}
                                      />
                                    </div>

                                    <div className="user-settings-field">
                                      <label htmlFor="model-file-datasource-folder">Datasource group folder</label>
                                      <input
                                        id="model-file-datasource-folder"
                                        type="text"
                                        value={selectedModelFilePatternSettings.datasourceGroupFolderPattern}
                                        onChange={(event) => updateSelectedModelFilePattern({ datasourceGroupFolderPattern: event.target.value })}
                                        placeholder={`datasource_group_${DATASOURCE_GROUP_ID_MARKER}/`}
                                      />
                                    </div>
                                  </div>

                                  <div className="user-settings-marker-help">
                                    Available markers: {PROJECT_ID_MARKER}, {DATASOURCE_GROUP_ID_MARKER}, {DATASOURCE_GROUP_NAME_MARKER}, {MODEL_KEY_MARKER}, {LOOKUP_KEY_MARKER}, {LOOKUP_VALUE_MARKER}, {ARTIFACT_TYPE_MARKER}.
                                  </div>

                                  <div className="user-settings-table-wrap">
                                    <table className="user-settings-table user-settings-pattern-table">
                                      <thead>
                                        <tr>
                                          <th>File</th>
                                          <th>Filename pattern</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {selectedModelFileArtifactTypes.map((artifactType) => (
                                          <tr key={artifactType}>
                                            <td className="user-settings-artifact-cell">{formatArtifactType(artifactType)}</td>
                                            <td>
                                              <input
                                                type="text"
                                                value={selectedModelFilePatternSettings.filenamePatternsByArtifact[artifactType] || getDefaultFilenamePatternForArtifact(artifactType)}
                                                onChange={(event) => updateSelectedModelFileFilenamePattern(artifactType, event.target.value)}
                                                placeholder={getDefaultFilenamePatternForArtifact(artifactType)}
                                              />
                                            </td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              ) : null}
                            </div>

                            <div className="user-settings-table-wrap">
                              <table className="user-settings-table user-settings-model-table">
                                <thead>
                                  <tr>
                                    <th>Lookup Value</th>
                                    <th>Model</th>
                                    <th>File</th>
                                    <th>Location</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {selectedDatasourceGroupModelFileRecords.map((record) => {
                                    const recordKey = getModelFileRecordKey(record);
                                    const sourceValue = modelFileSettings[recordKey] ?? record.source ?? "";

                                    return (
                                      <tr key={recordKey}>
                                        <td>{record.model_file_lookup_value}</td>
                                        <td>{formatModelKey(record.model_key)}</td>
                                        <td>{formatArtifactType(record.artifact_type)}</td>
                                        <td className="user-settings-location-cell">
                                          <input
                                            type="text"
                                            value={sourceValue}
                                            onChange={(event) => updateModelFileValue(record, event.target.value)}
                                            placeholder="/data/model_files/project_2/..."
                                            readOnly={selectedModelFileLocationMode === "pattern"}
                                            className={selectedModelFileLocationMode === "pattern" ? "user-settings-readonly-input" : ""}
                                          />
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </>
                        ) : null}
                      </section>
                    ) : null}

                    {applyError ? (
                      <div className="user-settings-apply-error">{applyError}</div>
                    ) : null}
                  </>
                ) : null}
              </>
            )}

            <div className="footer-button-container surface-action-bar">
              {!isApplyDisabled ? (
                <button
                  type="button"
                  className="secondary-button"
                  onClick={handleCancel}
                >
                  Cancel
                </button>
              ) : null}
              <button
                type="button"
                onClick={handleApply}
                disabled={isApplyDisabled}
              >
                {applySaving ? "Applying..." : "Apply"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default UserSettingsPage;
