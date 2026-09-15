import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from "@tanstack/react-table";
import { ChevronDown, ChevronUp } from "react-bootstrap-icons";
import { strFromU8, unzipSync } from "fflate";
import { Patient } from "../../../../../types/Patient";
import FilterControlsSection from "../../../components/FilterControlsSection";
import { Condition, FilterCollection } from "../../../utils/FilterPayloadConfigUtils";
import { Project } from "../../../../../types/Project";
import { useUserSession } from "../../../../../context/UserRoleContext";

interface FilterScreenPatientsProps {
  project: Project;
  patients: Patient[];
  medications: any[];
  onBack: () => void;
  onProceedToVariants: (patients: Patient[]) => void;
  setFilterCollection: <K extends keyof FilterCollection>(key: K, jsonString: string) => void;
  existingQueryFilter: string | null;
  existingPatientFilter: string | null;
  lockFilterConfig: boolean;
  onConfigSelected?: (config: FilterCollection | null) => void;
  selectedFilterName?: string;
  setSelectedFilterName?: (name: string) => void;
  selectedDatasourceGroupId: number | null;
  onSelectedDatasourceGroupIdChange: (datasourceGroupId: number | null) => void;
}

interface CancerTypeOption {
  label?: string;
  value?: string;
  code?: string;
  dataSourceGroups?: Array<number | string>;
}

interface DatasourceGroupOption {
  id: number;
  groupName: string;
  source?: string;
  isUnsupported: boolean;
}

const CANCER_TYPE_SCHEMA_URL = "/filters/cancer_type/patient/patient_query.json";

function getDatasourcePatientQuerySchemaUrl(
  projectId: number,
  datasourceGroupId: number
): string {
  return `/filters/project_${projectId}/datasource_group_${datasourceGroupId}/patient_query.json`;
}

interface DatasourceLoadProgress {
  percent: number;
  label: string;
}

type DatasourceLoadProgressHandler = (progress: DatasourceLoadProgress) => void;

function buildPatientDataFromConditions(conditions: Condition[]): { cancer_type?: string } {
  const data: { cancer_type?: string } = {};

  for (const c of conditions || []) {
    if (c.filter_type !== "PATIENT_DATA") continue;

    if (c.column_name === "cancer_type" && c.operator === "=" && typeof c.value === "string") {
      const v = c.value.trim();
      if (v !== "") data.cancer_type = v;
    }
  }

  return data;
}

function applyCancerTypeFilter(basePatients: Patient[], dataFilters: { cancer_type?: string }): Patient[] {
  const wanted = String(dataFilters.cancer_type || "").trim();
  if (!wanted) return basePatients;

  return basePatients.flatMap((patient) => {
    const scopedCancerTypes = Array.isArray((patient as any)?.cancer_types)
      ? ((patient as any).cancer_types as any[])
          .map((value) => String(value || "").trim())
          .filter((value) => value !== "")
      : [];

    if (scopedCancerTypes.length > 0) {
      if (!scopedCancerTypes.includes(wanted)) {
        return [];
      }

      // Keep the preview row aligned with the cancer that actually matched.
      return [{ ...(patient as any), cancer_type: wanted } as Patient];
    }

    return String((patient as any)?.cancer_type || "").trim() === wanted ? [patient] : [];
  });
}

function isConditionScopedBiomarkerLinkage(schema: any): boolean {
  return String(schema?.biomarker_resource_linkage?.scope || "")
    .trim()
    .toLowerCase() === "condition";
}

function getCancerTypeFromExistingPatientFilter(existingPatientFilter: string | null): string {
  if (!existingPatientFilter || existingPatientFilter === "{}") return "";
  try {
    const parsed = JSON.parse(existingPatientFilter) as any;
    const raw =
      (typeof parsed?.cancer_type === "string" && parsed.cancer_type) ||
      (typeof parsed?.cancerType === "string" && parsed.cancerType) ||
      "";
    return String(raw || "").trim();
  } catch {
    return "";
  }
}

function getCancerTypeFromConditions(conditions: Condition[]): string {
  for (const c of conditions || []) {
    if (c?.filter_type !== "PATIENT_DATA") continue;
    if (c?.column_name !== "cancer_type") continue;
    if (c?.operator !== "=") continue;
    if (typeof c?.value !== "string") continue;
    const v = c.value.trim();
    if (v) return v;
  }
  return "";
}

function normalizeCancerTypeOptions(options: CancerTypeOption[]): {
  byCode: Map<string, string>;
  byLabel: Map<string, string>;
} {
  const byCode = new Map<string, string>();
  const byLabel = new Map<string, string>();

  for (const option of options || []) {
    const value = String(option?.value || option?.label || "").trim();
    const label = String(option?.label || option?.value || "").trim();
    const code = String(option?.code || "").trim();

    const canonical = value || label;
    if (!canonical) continue;

    if (code) {
      byCode.set(code, canonical);
    }

    if (label) {
      byLabel.set(label.toLowerCase(), canonical);
    }

    if (value) {
      byLabel.set(value.toLowerCase(), canonical);
    }
  }

  return { byCode, byLabel };
}

function getDatasourceGroupIdsForCancerTypeOption(option: CancerTypeOption): number[] {
  return (option?.dataSourceGroups || [])
    .map((groupId) => Number(groupId))
    .filter((groupId) => Number.isFinite(groupId));
}

function getCancerTypeOptionsFromSchema(schema: any): CancerTypeOption[] {
  const controls = Array.isArray(schema?.controls) ? schema.controls : [];
  const cancerTypeControl = controls.find((control: any) => control?.id === "cancer_type");
  return Array.isArray(cancerTypeControl?.options) ? cancerTypeControl.options : [];
}

function filterCancerTypeSchemaByDatasourceGroup(schema: any, datasourceGroupId: number | null): any {
  if (datasourceGroupId == null) {
    return schema;
  }

  const controls = Array.isArray(schema?.controls) ? schema.controls : [];

  return {
    ...schema,
    controls: controls.map((control: any) => {
      if (control?.id !== "cancer_type" || !Array.isArray(control?.options)) {
        return control;
      }

      const options = (control.options as CancerTypeOption[]).filter((option) =>
        getDatasourceGroupIdsForCancerTypeOption(option).includes(datasourceGroupId)
      );

      const currentDefault = String(control?.default || "").trim();
      const defaultStillAvailable = options.some((option) => {
        const value = String(option?.value || option?.label || "").trim();
        const label = String(option?.label || option?.value || "").trim();
        return value === currentDefault || label === currentDefault;
      });

      return {
        ...control,
        options,
        default: defaultStillAvailable ? control.default : options[0]?.value || options[0]?.label || ""
      };
    })
  };
}

function resolveCancerTypeLabel(
  code: string,
  display: string,
  maps?: {
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null
): string {
  const trimmedCode = String(code || "").trim();
  const trimmedDisplay = String(display || "").trim();

  if (maps?.byCode?.has(trimmedCode)) {
    return maps.byCode.get(trimmedCode) || "";
  }

  if (maps?.byLabel?.has(trimmedDisplay.toLowerCase())) {
    return maps.byLabel.get(trimmedDisplay.toLowerCase()) || "";
  }

  return trimmedDisplay || trimmedCode || "";
}

function extractPatientIdFromReference(ref: any): string {
  const s = String(ref || "").trim();
  const idx = s.lastIndexOf("Patient/");
  if (idx >= 0) return s.slice(idx + "Patient/".length).trim();
  if (s.startsWith("Patient/")) return s.slice("Patient/".length).trim();
  return "";
}

function publishDatasourceProgress(
  onProgress: DatasourceLoadProgressHandler | undefined,
  progress: DatasourceLoadProgress
): void {
  onProgress?.(progress);
}

function waitForDatasourcePaint(): Promise<void> {
  if (typeof requestAnimationFrame !== "function") {
    return new Promise((resolve) => setTimeout(resolve, 0));
  }

  // Resolve on the second animation frame so the progress state reported before
  // this call is guaranteed a chance to paint before the next synchronous
  // datasource stage blocks the main thread. This is used only at the handful
  // of expensive stage boundaries, not for download-percentage updates.
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve());
    });
  });
}

function getCancerTypeMapSignature(
  cancerTypeMaps?: {
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null
): string {
  if (!cancerTypeMaps) return "";

  const byCode = Array.from(cancerTypeMaps.byCode.entries()).sort(([a], [b]) => a.localeCompare(b));
  const byLabel = Array.from(cancerTypeMaps.byLabel.entries()).sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify([byCode, byLabel]);
}

interface InFlightDatasourceLoad {
  promise: Promise<Patient[]>;
  subscribers: Set<DatasourceLoadProgressHandler>;
  latestProgress: DatasourceLoadProgress | null;
}

// This is deliberately NOT a cache. Entries exist only while a ZIP is actively loading
// so duplicate React effects share the same download/unzip/parse work.
const inFlightDatasourceLoads = new Map<string, InFlightDatasourceLoad>();

// Deduplicate the complete datasource load (including ZIP version resolution). This is
// intentionally in-flight only: the entry is removed as soon as the load finishes.
// That prevents React duplicate effects from resolving/downloading/parsing the same
// datasource twice without retaining stale datasource data between visits.
const inFlightDatasourceSourceLoads = new Map<string, InFlightDatasourceLoad>();

function normalizeDatasourceToZipUrl(source: string): string {
  const trimmed = String(source || "").trim();
  if (!trimmed) {
    throw new Error("Datasource source is empty.");
  }

  const basename = trimmed.split(/[\\/]/).pop() || trimmed;
  const lower = basename.toLowerCase();

  if (lower.endsWith(".zip")) {
    return `/test-data/${basename}`;
  }

  if (lower.endsWith(".json")) {
    return `/test-data/${basename.replace(/\.json$/i, ".zip")}`;
  }

  return `/test-data/${basename}.zip`;
}

function splitVersionedDatasourceFilename(filename: string): { stem: string; extension: string } {
  const dotIndex = filename.lastIndexOf(".");
  const name = dotIndex >= 0 ? filename.slice(0, dotIndex) : filename;
  const extension = dotIndex >= 0 ? filename.slice(dotIndex) : "";
  const stem = name.replace(/_v\d+$/i, "") || name;

  return { stem, extension };
}

function buildVersionedDatasourceUrl(stem: string, extension: string, version: number): string {
  const filename = version === 0 ? `${stem}${extension}` : `${stem}_v${version}${extension}`;
  return `/test-data/${filename}`;
}

function isDatasourceFileResponse(res: Response): boolean {
  if (!res.ok) {
    return false;
  }

  const contentType = String(res.headers.get("content-type") || "").toLowerCase();
  return !contentType.includes("text/html");
}

async function datasourceFileExists(url: string): Promise<boolean> {
  const probeUrl = `${url}?_=${Date.now()}-${Math.random().toString(36).slice(2)}`;

  try {
    const headRes = await fetch(probeUrl, { method: "HEAD", cache: "no-store" });
    if (isDatasourceFileResponse(headRes)) {
      return true;
    }

    if (headRes.status !== 405) {
      return false;
    }
  } catch {
  }

  try {
    const getRes = await fetch(probeUrl, {
      method: "GET",
      cache: "no-store",
      headers: { Range: "bytes=0-0" }
    });

    return isDatasourceFileResponse(getRes);
  } catch {
    return false;
  }
}

async function resolveLatestDatasourceZipUrl(source: string): Promise<string> {
  const fallbackUrl = normalizeDatasourceToZipUrl(source);
  const fallbackFilename = fallbackUrl.split("/").pop() || "";
  const { stem, extension } = splitVersionedDatasourceFilename(fallbackFilename);
  const maxVersion = 200;
  const maxConsecutiveMissesAfterMatch = 10;
  let latestUrl = "";
  let consecutiveMissesAfterMatch = 0;

  for (let version = 0; version <= maxVersion; version += 1) {
    const candidateUrl = buildVersionedDatasourceUrl(stem, extension, version);
    const exists = await datasourceFileExists(candidateUrl);

    if (exists) {
      latestUrl = candidateUrl;
      consecutiveMissesAfterMatch = 0;
      continue;
    }

    if (latestUrl) {
      consecutiveMissesAfterMatch += 1;
      if (consecutiveMissesAfterMatch >= maxConsecutiveMissesAfterMatch) {
        break;
      }
    }
  }

  if (latestUrl) {
    return latestUrl;
  }


  throw new Error(
    `Datasource ZIP not found for "${source}". Expected a file matching ${fallbackUrl} or a versioned variant such as ${stem}_v1${extension} under /test-data.`
  );
}

function isZipPayload(bytes: Uint8Array): boolean {
  if (bytes.length < 4) {
    return false;
  }

  return (
    bytes[0] === 0x50 &&
    bytes[1] === 0x4b &&
    (
      (bytes[2] === 0x03 && bytes[3] === 0x04) ||
      (bytes[2] === 0x05 && bytes[3] === 0x06) ||
      (bytes[2] === 0x07 && bytes[3] === 0x08)
    )
  );
}

async function loadCancerPatientsFromZipUrlCore(
  zipUrl: string,
  cancerTypeMaps?: {
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null,
  conditionScoped = false,
  onProgress?: DatasourceLoadProgressHandler
): Promise<Patient[]> {
  const reportProgress = (progress: DatasourceLoadProgress): void => {
    publishDatasourceProgress(onProgress, progress);
  };

  const reportProgressAndPaint = async (progress: DatasourceLoadProgress): Promise<void> => {
    reportProgress(progress);
    await waitForDatasourcePaint();
  };

  reportProgress({ percent: 5, label: "Preparing data source..." });

  const requestUrl = `${zipUrl}${zipUrl.includes("?") ? "&" : "?"}_=${Date.now()}`;
  const res = await fetch(requestUrl, { cache: "no-store" });

  if (!res.ok) {
    throw new Error(`Failed to fetch datasource ZIP ${zipUrl}: HTTP ${res.status}`);
  }

  const contentType = String(res.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("text/html")) {
    throw new Error(
      `Datasource ZIP request returned HTML instead of a ZIP: ${zipUrl}. Check that the file exists under frontend/public/test-data with the expected filename.`
    );
  }

  const contentLength = Number(res.headers.get("content-length") || "0");
  let zipBytes: Uint8Array;

  if (res.body && contentLength > 0) {
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let received = 0;
    let lastDownloadPercent = 5;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      if (value) {
        chunks.push(value);
        received += value.length;

        const downloadPercent = Math.min(20, Math.floor((received / contentLength) * 15) + 5);
        if (downloadPercent !== lastDownloadPercent) {
          lastDownloadPercent = downloadPercent;
          reportProgress({
            percent: downloadPercent,
            label: `Loading data source... ${downloadPercent}%`
          });
        }
      }
    }

    zipBytes = new Uint8Array(received);
    let offset = 0;

    for (const chunk of chunks) {
      zipBytes.set(chunk, offset);
      offset += chunk.length;
    }
  } else {
    reportProgress({ percent: 15, label: "Loading data source..." });
    zipBytes = new Uint8Array(await res.arrayBuffer());
  }


  if (!isZipPayload(zipBytes)) {
    const signature = Array.from(zipBytes.slice(0, 8))
      .map((value) => value.toString(16).padStart(2, "0"))
      .join(" ");

    throw new Error(
      `Datasource response is not valid ZIP data: ${zipUrl}. ` +
      `Received ${zipBytes.length} bytes with content-type "${contentType || "unknown"}" ` +
      `and leading bytes "${signature || "empty"}".`
    );
  }

  await reportProgressAndPaint({ percent: 25, label: "Processing data..." });

  let files: ReturnType<typeof unzipSync>;
  try {
    files = unzipSync(zipBytes);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Unable to unzip datasource ${zipUrl}: ${message}`);
  }

  await reportProgressAndPaint({ percent: 60, label: "Processing data..." });

  const jsonFilename = Object.keys(files).find((name) => name.toLowerCase().endsWith(".json")) || "";

  if (!jsonFilename) {
    const names = Object.keys(files || {}).join(", ");
    throw new Error(`No JSON file found in ${zipUrl}. Found: ${names}`);
  }

  const fileBytes = files[jsonFilename] as Uint8Array | undefined;
  if (!fileBytes) {
    throw new Error(`Unable to read ${jsonFilename} from ${zipUrl}.`);
  }

  const jsonText = strFromU8(fileBytes);

  await reportProgressAndPaint({ percent: 76, label: "Processing data..." });
  const json = JSON.parse(jsonText);

  await reportProgressAndPaint({ percent: 92, label: "Preparing filter options..." });
  const entries = json.entry || [];
  const cancerByPatientId = new Map<string, string>();
  const cancersByPatientId = new Map<string, Set<string>>();

  entries
    .filter((entry: any) => entry.resource.resourceType === "Condition")
    .forEach((entry: any) => {
      const r = entry.resource;
      const patientId = extractPatientIdFromReference(r?.subject?.reference);
      if (!patientId) return;

      const codings = Array.isArray(r?.code?.coding) ? r.code.coding : [];
      const matchingLabels = new Set<string>();

      for (const coding of codings) {
        const code = String(coding?.code || "").trim();
        const display = String(coding?.display || "").trim();

        if (conditionScoped && cancerTypeMaps) {
          const configuredLabel =
            cancerTypeMaps.byCode.get(code) ||
            cancerTypeMaps.byLabel.get(display.toLowerCase()) ||
            "";

          if (configuredLabel) {
            matchingLabels.add(configuredLabel);
          }
          continue;
        }

        const label = resolveCancerTypeLabel(code, display, cancerTypeMaps);
        if (label) {
          matchingLabels.add(label);
          break;
        }
      }

      if (matchingLabels.size === 0) return;

      if (conditionScoped) {
        const existing = cancersByPatientId.get(patientId) || new Set<string>();
        matchingLabels.forEach((label) => existing.add(label));
        cancersByPatientId.set(patientId, existing);
        return;
      }

      const firstLabel = matchingLabels.values().next().value as string | undefined;
      if (firstLabel) {
        cancerByPatientId.set(patientId, firstLabel);
      }
    });

  const patientEntries = entries.filter((entry: any) => entry.resource.resourceType === "Patient");
  const nextPatients: Patient[] = [];
  const seenPatientIds = new Set<string>();

  for (const entry of patientEntries) {
    const patientId = String(entry.resource.id || "").trim();

    // Condition-scoped MSK bundles can repeat the same Patient resource once per
    // sample. The preview is patient-level, so count each Patient id only once.
    if (conditionScoped && patientId && seenPatientIds.has(patientId)) {
      continue;
    }
    if (conditionScoped && patientId) {
      seenPatientIds.add(patientId);
    }

    const nameObj = entry.resource.name?.[0] || {};
    const base: any = {
      id: entry.resource.id,
      family: nameObj.family ?? "",
      given: nameObj.given?.[0] ?? "",
      gender: entry.resource.gender,
      birthDate: entry.resource.birthDate,
      deceasedDateTime: entry.resource.deceasedDateTime ?? "",
      fullUrl: entry.fullUrl
    };

    if (conditionScoped) {
      const cancerTypes = Array.from(cancersByPatientId.get(patientId) || []);
      if (cancerTypes.length > 0) {
        base.cancer_types = cancerTypes;
        if (cancerTypes.length === 1) {
          base.cancer_type = cancerTypes[0];
        }
      }
    } else {
      const ct = cancerByPatientId.get(patientId);
      if (ct) base.cancer_type = ct;
    }

    nextPatients.push(base as Patient);
  }

  reportProgress({ percent: 100, label: "Ready" });



  return nextPatients;
}

async function loadCancerPatientsFromZipUrl(
  zipUrl: string,
  cancerTypeMaps?: {
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null,
  conditionScoped = false,
  onProgress?: DatasourceLoadProgressHandler
): Promise<Patient[]> {
  const loadKey = `${zipUrl}|${getCancerTypeMapSignature(cancerTypeMaps)}|scope:${conditionScoped ? "condition" : "patient"}`;
  const existingLoad = inFlightDatasourceLoads.get(loadKey);

  if (existingLoad) {

    if (onProgress) {
      existingLoad.subscribers.add(onProgress);
      if (existingLoad.latestProgress) {
        onProgress(existingLoad.latestProgress);
      }
    }

    try {
      return await existingLoad.promise;
    } finally {
      if (onProgress) {
        existingLoad.subscribers.delete(onProgress);
      }
    }
  }

  const subscribers = new Set<DatasourceLoadProgressHandler>();
  if (onProgress) subscribers.add(onProgress);

  const inFlight: InFlightDatasourceLoad = {
    promise: Promise.resolve([] as Patient[]),
    subscribers,
    latestProgress: null
  };

  const broadcastProgress = (progress: DatasourceLoadProgress): void => {
    inFlight.latestProgress = progress;
    inFlight.subscribers.forEach((subscriber) => subscriber(progress));
  };

  inFlight.promise = loadCancerPatientsFromZipUrlCore(
    zipUrl,
    cancerTypeMaps,
    conditionScoped,
    broadcastProgress
  );
  inFlightDatasourceLoads.set(loadKey, inFlight);

  try {
    return await inFlight.promise;
  } finally {
    if (inFlightDatasourceLoads.get(loadKey) === inFlight) {
      inFlightDatasourceLoads.delete(loadKey);
    }
  }
}

async function loadCancerPatientsFromDatasourceSource(
  source: string,
  cancerTypeMaps?: {
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null,
  conditionScoped = false,
  onProgress?: DatasourceLoadProgressHandler
): Promise<Patient[]> {
  const sourceKey = `${source}|${getCancerTypeMapSignature(cancerTypeMaps)}|scope:${conditionScoped ? "condition" : "patient"}`;
  const existingLoad = inFlightDatasourceSourceLoads.get(sourceKey);

  if (existingLoad) {

    if (onProgress) {
      existingLoad.subscribers.add(onProgress);
      if (existingLoad.latestProgress) {
        onProgress(existingLoad.latestProgress);
      }
    }

    try {
      return await existingLoad.promise;
    } finally {
      if (onProgress) {
        existingLoad.subscribers.delete(onProgress);
      }
    }
  }

  const subscribers = new Set<DatasourceLoadProgressHandler>();
  if (onProgress) subscribers.add(onProgress);

  const inFlight: InFlightDatasourceLoad = {
    promise: Promise.resolve([] as Patient[]),
    subscribers,
    latestProgress: null
  };

  const broadcastProgress = (progress: DatasourceLoadProgress): void => {
    inFlight.latestProgress = progress;
    inFlight.subscribers.forEach((subscriber) => subscriber(progress));
  };

  // Reserve the source-level key before starting any asynchronous version probes.
  // A second React effect will therefore join here immediately instead of resolving
  // the ZIP independently and arriving after the first expensive load has finished.
  inFlightDatasourceSourceLoads.set(sourceKey, inFlight);

  inFlight.promise = (async () => {
    const zipUrl = await resolveLatestDatasourceZipUrl(source);
    const nextPatients = await loadCancerPatientsFromZipUrl(
      zipUrl,
      cancerTypeMaps,
      conditionScoped,
      broadcastProgress
    );
    return nextPatients;
  })();

  try {
    return await inFlight.promise;
  } finally {
    if (inFlightDatasourceSourceLoads.get(sourceKey) === inFlight) {
      inFlightDatasourceSourceLoads.delete(sourceKey);
    }
  }
}

const FilterScreenPatients_CancerType: React.FC<FilterScreenPatientsProps> = ({
  project,
  patients,
  onBack,
  onProceedToVariants,
  setFilterCollection,
  existingPatientFilter,
  lockFilterConfig,
  selectedDatasourceGroupId,
  onSelectedDatasourceGroupIdChange
}) => {
  const userSession = useUserSession();

  const [compiledConditions, setCompiledConditions] = useState<Condition[]>([]);
  const [previewPatients, setPreviewPatients] = useState<Patient[]>([]);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const hasPreviewedRef = useRef(hasPreviewed);
  const [initialControlValues, setInitialControlValues] = useState<Record<string, any>>({});
  const [initialConditions, setInitialConditions] = useState<Condition[]>([]);
  const [loadedPatients, setLoadedPatients] = useState<Patient[]>(patients || []);
  const [isDatasourceLoading, setIsDatasourceLoading] = useState(false);
  const [datasourceLoadProgress, setDatasourceLoadProgress] = useState<DatasourceLoadProgress>({
    percent: 0,
    label: ""
  });
  const [, setDatasourceLoadError] = useState("");
  const [baseCancerTypeSchema, setBaseCancerTypeSchema] = useState<any | null>(null);
  const [cancerTypeMaps, setCancerTypeMaps] = useState<{
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null>(null);
  const [datasourceCancerTypeSchema, setDatasourceCancerTypeSchema] = useState<any | null>(null);
  const [datasourceSpecificCancerTypeMaps, setDatasourceSpecificCancerTypeMaps] = useState<{
    byCode: Map<string, string>;
    byLabel: Map<string, string>;
  } | null>(null);
  const [cancerTypeSupportByDatasourceGroup, setCancerTypeSupportByDatasourceGroup] =
    useState<Map<number, Set<string>>>(new Map());
  const seededKeyRef = useRef<string>("");
  const lockedCancerTypeRef = useRef<string>("");
  const shouldRerunPreviewAfterDatasourceLoadRef = useRef(false);

  const userProjectEntry = useMemo(() => {
    return userSession.projects.find((entry) => entry.project_id === project.id) || null;
  }, [userSession.projects, project.id]);

  const defaultDatasource = useMemo(() => {
    if (!userProjectEntry) {
      return null;
    }

    const groupedDatasources = (userProjectEntry.datasources || []).filter(
      (entry) => entry.datasource_group_id != null
    );

    return (
      groupedDatasources.find((entry) => entry.is_default_group) ||
      groupedDatasources[0] ||
      null
    );
  }, [userProjectEntry]);

  const selectedDatasource = useMemo(() => {
    if (!userProjectEntry) {
      return null;
    }

    if (selectedDatasourceGroupId == null) {
      return defaultDatasource;
    }

    return (userProjectEntry.datasources || []).find(
      (entry) => Number(entry.datasource_group_id) === Number(selectedDatasourceGroupId)
    ) || null;
  }, [userProjectEntry, selectedDatasourceGroupId, defaultDatasource]);

  const effectiveDatasourceGroupId = useMemo(() => {
    if (selectedDatasourceGroupId != null) {
      const selectedId = Number(selectedDatasourceGroupId);
      return Number.isFinite(selectedId) ? selectedId : null;
    }

    const datasourceGroupId = Number((selectedDatasource as any)?.datasource_group_id);
    return Number.isFinite(datasourceGroupId) ? datasourceGroupId : null;
  }, [selectedDatasourceGroupId, selectedDatasource]);

  useEffect(() => {
    if (selectedDatasourceGroupId != null || effectiveDatasourceGroupId == null) {
      return;
    }

    // The dropdown can derive and display the default datasource even when the
    // runner state was cleared by Start Over. Keep the runner state in sync so
    // submission always carries the same datasource group the patient screen
    // is actually using.
    onSelectedDatasourceGroupIdChange(effectiveDatasourceGroupId);
  }, [
    selectedDatasourceGroupId,
    effectiveDatasourceGroupId,
    onSelectedDatasourceGroupIdChange,
  ]);

  const lockedCancerType = useMemo(() => {
    return getCancerTypeFromExistingPatientFilter(existingPatientFilter);
  }, [existingPatientFilter]);

  const lockedCancerTypeDatasourceGroupIds = useMemo(() => {
    if (!lockFilterConfig || !lockedCancerType) {
      return null;
    }

    if (cancerTypeSupportByDatasourceGroup.size === 0) {
      return null;
    }

    const wanted = lockedCancerType.trim().toLowerCase();
    const supportedGroupIds = new Set<number>();

    for (const [groupId, supportedCancerTypes] of cancerTypeSupportByDatasourceGroup.entries()) {
      if (supportedCancerTypes.has(wanted)) {
        supportedGroupIds.add(groupId);
      }
    }

    return supportedGroupIds;
  }, [cancerTypeSupportByDatasourceGroup, lockFilterConfig, lockedCancerType]);

  const datasourceGroupOptions = useMemo<DatasourceGroupOption[]>(() => {
    const byId = new Map<number, Omit<DatasourceGroupOption, "isUnsupported">>();

    for (const group of project.datasource_groups || []) {
      const id = Number((group as any)?.id);
      if (!Number.isFinite(id)) {
        continue;
      }

      byId.set(id, {
        id,
        groupName: String((group as any)?.group_name || (group as any)?.name || `Datasource Group ${id}`).trim(),
      });
    }

    for (const datasource of userProjectEntry?.datasources || []) {
      const id = Number((datasource as any)?.datasource_group_id);
      if (!Number.isFinite(id)) {
        continue;
      }

      const existing = byId.get(id);
      byId.set(id, {
        id,
        groupName: String(
          (datasource as any)?.datasource_group_name || existing?.groupName || `Datasource Group ${id}`
        ).trim(),
        source: String((datasource as any)?.source || existing?.source || ""),
      });
    }

    return Array.from(byId.values()).map((option) => ({
      ...option,
      isUnsupported:
        !!lockFilterConfig &&
        !!lockedCancerType &&
        lockedCancerTypeDatasourceGroupIds !== null &&
        !lockedCancerTypeDatasourceGroupIds.has(option.id),
    }));
  }, [project.datasource_groups, userProjectEntry?.datasources, lockFilterConfig, lockedCancerType, lockedCancerTypeDatasourceGroupIds]);

  useEffect(() => {
    let cancelled = false;

    async function loadDatasourceCancerSupport() {
      const groupIds = Array.from(
        new Set(
          (project.datasource_groups || [])
            .map((group: any) => Number(group?.id))
            .filter((groupId: number) => Number.isFinite(groupId))
        )
      );

      if (!groupIds.length) {
        setCancerTypeSupportByDatasourceGroup(new Map());
        return;
      }

      const results = await Promise.all(
        groupIds.map(async (groupId) => {
          const schemaUrl = getDatasourcePatientQuerySchemaUrl(Number(project.id), groupId);

          try {
            const res = await fetch(schemaUrl, { cache: "no-store" });
            if (!res.ok) {
              throw new Error(`HTTP ${res.status}`);
            }

            const schema = await res.json();
            const supportedCancerTypes = new Set<string>();

            for (const option of getCancerTypeOptionsFromSchema(schema)) {
              const value = String(option?.value || "").trim().toLowerCase();
              const label = String(option?.label || "").trim().toLowerCase();

              if (value) supportedCancerTypes.add(value);
              if (label) supportedCancerTypes.add(label);
            }

            return [groupId, supportedCancerTypes] as const;
          } catch (error) {
            console.error(
              `[CancerTypeFilter] Failed to load cancer support schema ${schemaUrl}:`,
              error
            );
            return [groupId, new Set<string>()] as const;
          }
        })
      );

      if (cancelled) return;

      setCancerTypeSupportByDatasourceGroup(new Map(results));
    }

    loadDatasourceCancerSupport();

    return () => {
      cancelled = true;
    };
  }, [project.id, project.datasource_groups]);

  const selectedDatasourceGroupName = useMemo(() => {
    if (selectedDatasource?.datasource_group_name) {
      return selectedDatasource.datasource_group_name;
    }

    const groups = project.datasource_groups || [];
    if (effectiveDatasourceGroupId == null) {
      return null;
    }
    const match = groups.find((group) => Number(group.id) === effectiveDatasourceGroupId);
    return match?.group_name || null;
  }, [project.datasource_groups, selectedDatasource, effectiveDatasourceGroupId]);

  useEffect(() => {
    if (!lockFilterConfig || !lockedCancerType || !lockedCancerTypeDatasourceGroupIds) {
      return;
    }

    if (!datasourceGroupOptions.length || effectiveDatasourceGroupId == null) {
      return;
    }

    if (lockedCancerTypeDatasourceGroupIds.has(effectiveDatasourceGroupId)) {
      return;
    }

    const fallbackGroup = datasourceGroupOptions.find((option) => !option.isUnsupported);
    if (fallbackGroup && fallbackGroup.id !== effectiveDatasourceGroupId) {
      onSelectedDatasourceGroupIdChange(fallbackGroup.id);
    }
  }, [
    datasourceGroupOptions,
    effectiveDatasourceGroupId,
    lockedCancerType,
    lockedCancerTypeDatasourceGroupIds,
    lockFilterConfig,
    onSelectedDatasourceGroupIdChange,
  ]);

  const filteredCancerTypeSchema = useMemo(() => {
    if (effectiveDatasourceGroupId != null) {
      return datasourceCancerTypeSchema;
    }

    if (!baseCancerTypeSchema) {
      return null;
    }

    return filterCancerTypeSchemaByDatasourceGroup(baseCancerTypeSchema, effectiveDatasourceGroupId);
  }, [
    baseCancerTypeSchema,
    effectiveDatasourceGroupId,
    datasourceCancerTypeSchema,
  ]);

  const filteredCancerTypeOptions = useMemo<CancerTypeOption[]>(() => {
    return getCancerTypeOptionsFromSchema(filteredCancerTypeSchema);
  }, [filteredCancerTypeSchema]);

  const filteredCancerTypeSchemaUrl = useMemo(() => {
    if (!filteredCancerTypeSchema) {
      return "";
    }

    return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(filteredCancerTypeSchema))}`;
  }, [filteredCancerTypeSchema]);

  useEffect(() => {
    hasPreviewedRef.current = hasPreviewed;
  }, [hasPreviewed]);

  useEffect(() => {
    let cancelled = false;

    async function loadCancerTypeSchema() {
      try {
        const res = await fetch(CANCER_TYPE_SCHEMA_URL, { cache: "no-store" });
        if (!res.ok) {
          throw new Error(`Failed to fetch cancer type schema: HTTP ${res.status}`);
        }

        const schema = await res.json();
        if (cancelled) return;

        setBaseCancerTypeSchema(schema);
        setCancerTypeMaps(normalizeCancerTypeOptions(getCancerTypeOptionsFromSchema(schema)));
      } catch (error) {
        if (cancelled) return;
        console.error("[CancerTypeFilter] Failed to load generic cancer type schema:", error);
        setBaseCancerTypeSchema(null);
        setCancerTypeMaps({
          byCode: new Map<string, string>(),
          byLabel: new Map<string, string>(),
        });
      }
    }

    loadCancerTypeSchema();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadDatasourceCancerTypeSchema() {
      if (effectiveDatasourceGroupId == null) {
        setDatasourceCancerTypeSchema(null);
        setDatasourceSpecificCancerTypeMaps(null);
        return;
      }

      const schemaUrl = getDatasourcePatientQuerySchemaUrl(
        Number(project.id),
        effectiveDatasourceGroupId
      );

      setDatasourceCancerTypeSchema(null);
      setDatasourceSpecificCancerTypeMaps(null);

      try {
        const res = await fetch(schemaUrl, { cache: "no-store" });
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const schema = await res.json();
        if (cancelled) return;

        setDatasourceCancerTypeSchema(schema);
        setDatasourceSpecificCancerTypeMaps(
          normalizeCancerTypeOptions(getCancerTypeOptionsFromSchema(schema))
        );

      } catch (error) {
        if (cancelled) return;

        console.error(
          `[CancerTypeFilter] Failed to load datasource patient query schema ${schemaUrl}:`,
          error
        );
        setDatasourceCancerTypeSchema(null);
        setDatasourceSpecificCancerTypeMaps(null);
      }
    }

    loadDatasourceCancerTypeSchema();

    return () => {
      cancelled = true;
    };
  }, [project.id, effectiveDatasourceGroupId]);

  useEffect(() => {
    const nextValues: Record<string, any> = {};
    const nextInitialConditions: Condition[] = [];


    const lockedCt = getCancerTypeFromExistingPatientFilter(existingPatientFilter);
    lockedCancerTypeRef.current = lockedCt;


    if (lockedCt) {
      nextValues["cancer_type"] = lockedCt;
      nextValues["cancerType"] = lockedCt;

      nextInitialConditions.push({
        filter_type: "PATIENT_DATA",
        column_name: "cancer_type",
        operator: "=",
        value: lockedCt
      } as Condition);
    }


    setInitialControlValues(nextValues);
    setInitialConditions(nextInitialConditions);

    const seedKey = `${lockFilterConfig ? "1" : "0"}|${existingPatientFilter || ""}`;
    if (seededKeyRef.current !== seedKey) {
      setCompiledConditions(nextInitialConditions);
      seededKeyRef.current = seedKey;
    }
  }, [existingPatientFilter, lockFilterConfig]);

  const handleCompiledChange = useCallback(
    ({ conditions }: { conditions: Condition[]; fhirParams: string }) => {

      const lockedCt = (lockedCancerTypeRef.current || "").trim();
      const incomingCt = getCancerTypeFromConditions(conditions || []);

      if (lockFilterConfig && lockedCt) {
        if (!incomingCt || incomingCt !== lockedCt) {
          const lockedConditions: Condition[] = [
            {
              filter_type: "PATIENT_DATA",
              column_name: "cancer_type",
              operator: "=",
              value: lockedCt
            } as Condition
          ];
          setCompiledConditions(lockedConditions);
          return;
        }
      }

      setCompiledConditions(conditions || []);
    },
    [lockFilterConfig]
  );

  useEffect(() => {
    if (lockFilterConfig) {
      return;
    }

    const currentCancerType = getCancerTypeFromConditions(compiledConditions || []);
    if (!currentCancerType) {
      return;
    }

    const allowedCancerTypes = new Set(
      filteredCancerTypeOptions
        .map((option) => String(option?.value || option?.label || "").trim())
        .filter((value) => value !== "")
    );

    if (allowedCancerTypes.size === 0 || allowedCancerTypes.has(currentCancerType)) {
      return;
    }

    const fallbackCancerType = String(
      filteredCancerTypeOptions[0]?.value || filteredCancerTypeOptions[0]?.label || ""
    ).trim();

    const fallbackConditions = fallbackCancerType
      ? ([
          {
            filter_type: "PATIENT_DATA",
            column_name: "cancer_type",
            operator: "=",
            value: fallbackCancerType
          } as Condition
        ] as Condition[])
      : [];

    setInitialControlValues(
      fallbackCancerType
        ? { cancer_type: fallbackCancerType, cancerType: fallbackCancerType }
        : {}
    );
    setInitialConditions(fallbackConditions);
    setCompiledConditions(fallbackConditions);
  }, [compiledConditions, filteredCancerTypeOptions, lockFilterConfig]);

  const runPreview = useCallback((basePatientsOverride?: Patient[]) => {
    const basePatients = basePatientsOverride || loadedPatients || [];
    const dataFilters = buildPatientDataFromConditions(compiledConditions);

    const afterData = applyCancerTypeFilter(basePatients, dataFilters);

    setPreviewPatients(afterData);
    setHasPreviewed(true);
  }, [compiledConditions, loadedPatients]);

  const datasourceCancerTypeMaps = useMemo(() => {
    if (effectiveDatasourceGroupId != null) {
      return datasourceSpecificCancerTypeMaps;
    }

    return cancerTypeMaps;
  }, [
    effectiveDatasourceGroupId,
    datasourceSpecificCancerTypeMaps,
    cancerTypeMaps,
  ]);

  const conditionScopedCancerPreview = useMemo(() => {
    return isConditionScopedBiomarkerLinkage(datasourceCancerTypeSchema);
  }, [datasourceCancerTypeSchema]);

  useEffect(() => {
    let cancelled = false;

    async function loadSelectedDatasourcePatients() {
      if (!selectedDatasource?.source) {
        setLoadedPatients(patients || []);
        setDatasourceLoadError("");
        setIsDatasourceLoading(false);
        return;
      }

      const source = String(selectedDatasource.source).trim();

      const lowerSource = source.toLowerCase();

      if (!lowerSource.endsWith(".json") && !lowerSource.endsWith(".zip")) {
        setLoadedPatients(patients || []);
        setDatasourceLoadError("");
        setIsDatasourceLoading(false);
        return;
      }

      if (!datasourceCancerTypeMaps) {
        setIsDatasourceLoading(true);
        return;
      }

      try {
        setIsDatasourceLoading(true);
        setDatasourceLoadProgress({ percent: 0, label: "Preparing data source..." });
        setDatasourceLoadError("");
        const nextPatients = await loadCancerPatientsFromDatasourceSource(
          source,
          datasourceCancerTypeMaps,
          conditionScopedCancerPreview,
          (progress) => {
            if (cancelled) return;
            setDatasourceLoadProgress(progress);
          }
        );
        if (cancelled) return;
        setLoadedPatients(nextPatients);
      } catch (error: any) {
        if (cancelled) return;
        console.error("[CancerTypeFilter] Failed to load datasource patients:", error);
        setLoadedPatients([]);
        setDatasourceLoadError(error?.message || "Failed to load datasource file.");
      } finally {
        if (!cancelled) {
          setDatasourceLoadProgress({ percent: 100, label: "Ready" });
          setIsDatasourceLoading(false);
        }
      }
    }

    if (hasPreviewedRef.current) {
      shouldRerunPreviewAfterDatasourceLoadRef.current = true;
    }

    setPreviewPatients([]);

    setHasPreviewed(false);

    loadSelectedDatasourcePatients();

    return () => {
      cancelled = true;
    };
  }, [
    selectedDatasource?.source,
    effectiveDatasourceGroupId,
    datasourceCancerTypeMaps,
    conditionScopedCancerPreview,
    patients
  ]);

  useEffect(() => {
    if (isDatasourceLoading) {
      return;
    }

    if (shouldRerunPreviewAfterDatasourceLoadRef.current) {
      shouldRerunPreviewAfterDatasourceLoadRef.current = false;
      runPreview(loadedPatients);
      return;
    }

    if (!loadedPatients || loadedPatients.length === 0) {
      setPreviewPatients([]);
      setHasPreviewed(false);
      return;
    }

    runPreview(loadedPatients);
  }, [compiledConditions, loadedPatients, isDatasourceLoading, runPreview]);

  const filteredPatients = useMemo(() => previewPatients, [previewPatients]);

  const columns = useMemo<ColumnDef<Patient>[]>(
    () => [
      { accessorKey: "id", header: "ID" },
      { accessorKey: "family", header: "Family Name" },
      { accessorKey: "given", header: "Given Name" },
      {
        id: "cancer_type",
        header: "Cancer Type",
        accessorFn: (row) => String((row as any)?.cancer_type || "")
      },
      { accessorKey: "gender", header: "Gender" },
      { accessorKey: "birthDate", header: "Birth Date" },
      { accessorKey: "deceasedDateTime", header: "Deceased Date" }
    ],
    []
  );

  const table = useReactTable({
    data: filteredPatients,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row: any) => row.id || row.ID || JSON.stringify(row),
    initialState: {
      pagination: {
        pageSize: 10
      }
    },
    enableRowSelection: true
  });

  const canProceed = filteredPatients.length > 0;

const handleContinue = () => {
  if (!hasPreviewed) return;

  const dataFilters = buildPatientDataFromConditions(compiledConditions);
  const resolvedPatientDataFilters =
    lockFilterConfig && existingPatientFilter
      ? existingPatientFilter
      : JSON.stringify(dataFilters);


  setFilterCollection("patientQueryFilters", JSON.stringify({}));
  setFilterCollection("patientDataFilters", resolvedPatientDataFilters);

  onProceedToVariants(filteredPatients);
};

  const filterControlsKey = useMemo(() => {
    const lockedCt = (lockedCancerTypeRef.current || "").trim();
    return `ct:${lockedCt}|lock:${lockFilterConfig ? "1" : "0"}|raw:${existingPatientFilter || ""}|group:${effectiveDatasourceGroupId ?? "null"}|source:${selectedDatasource?.source || ""}|schema:${filteredCancerTypeSchemaUrl || "pending"}`;
  }, [existingPatientFilter, lockFilterConfig, effectiveDatasourceGroupId, selectedDatasource?.source, filteredCancerTypeSchemaUrl]);

  return (
    <>
      <div className="page-container">
        <div className="child-container-top">



          <div className="duality-mb-1">
            <label
              htmlFor="datasource-group-select"
              className="filter-screen-patients-cancer-type-datasource-group-select-label"
            >
              Datasource Group
            </label>
            <select
              id="datasource-group-select"
              value={effectiveDatasourceGroupId ?? ""}
              onChange={(event) => {
                const nextId = Number(event.target.value);
                onSelectedDatasourceGroupIdChange(Number.isFinite(nextId) ? nextId : null);
              }}
              className="filter-screen-patients-cancer-type-datasource-group-select"
            >
              {datasourceGroupOptions.length === 0 ? (
                <option value="">No datasource groups available</option>
              ) : (
                datasourceGroupOptions.map((option) => (
                  <option
                  key={option.id} value={option.id} disabled={option.isUnsupported}>
                    {option.groupName}
                    {option.isUnsupported ? " (Unsupported)" : ""}
                  </option>
                ))
              )}
            </select>
            {lockFilterConfig && lockedCancerType && datasourceGroupOptions.some((option) => option.isUnsupported) && (
              <div className="filter-screen-patients-cancer-type-block-01">
                Datasource groups marked unsupported do not contain the selected cancer type: {lockedCancerType}.
              </div>
            )}
          </div>


          <h3 className="duality-mb-075">Patient Filters</h3>


          <div className="duality-mt-0p75rem-mb-1rem">
            {filteredCancerTypeSchemaUrl ? (
              <FilterControlsSection
                key={filterControlsKey}
                schemaUrl={filteredCancerTypeSchemaUrl}
                filterType="PATIENT_DATA"
                initialConditions={initialConditions}
                initialValues={initialControlValues}
                lock={lockFilterConfig}
                onCompiledChange={handleCompiledChange}
              />
            ) : (
              <div className="filter-screen-patients-cancer-type-block-02">Loading cancer type options...</div>
            )}
          </div>
          {isDatasourceLoading ? (
            <div
              className="filter-screen-patients-cancer-type-block-03"
            >
              <div className="duality-mb-0p5rem">
                {datasourceLoadProgress.label || "Preparing data source..."}
              </div>
              <div
                className="filter-screen-patients-cancer-type-block-04"
              >
                <div
                  className="filter-screen-patients-cancer-type-block-05" style={{ width: `${Math.max(0, Math.min(100, datasourceLoadProgress.percent))}%` }}
                />
              </div>
              <div className="filter-screen-patients-cancer-type-block-06">
                {Math.max(0, Math.min(100, datasourceLoadProgress.percent))}%
              </div>
            </div>
          ) : <>
            <div

              className="filter-screen-patients-cancer-type-block-07"
            >
              <h3>Patient Data Preview</h3>
              <div className="filter-screen-patients-cancer-type-block-08">
                {hasPreviewed && filteredPatients.length > 0 && (
                  <h4 className="duality-text-black-m-0">
                    Filtered to {table.getFilteredRowModel().rows.length} results
                  </h4>
                )}
              </div>
            </div>

            <table className="duality-table-full">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="duality-border-1px-solid-e0e0e0-p-0p5rem-cursor-pointer"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {header.column.getIsSorted() === "asc" && <ChevronUp size={12} />}
                        {header.column.getIsSorted() === "desc" && <ChevronDown size={12} />}{" "}
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="duality-border-1px-solid-e0e0e0-p-0p5rem">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
                {hasPreviewed && table.getRowModel().rows.length === 0 && (
                  <tr>
                    <td colSpan={columns.length} className="duality-p-0p75rem">
                      No patients match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>

            <div
              className="duality-d-flex-justify-center-align-center-7b984"
            >
              <button type="button" className="link-button-reset duality-underline"
                onClick={(e) => {
                  e.preventDefault();
                  table.previousPage();
                }}
                style={{ color: table.getCanPreviousPage() ? "#007BFF" : "#A0A0A0", cursor: table.getCanPreviousPage() ? "pointer" : "not-allowed", pointerEvents: table.getCanPreviousPage() ? "auto" : "none" }}
                  >
                Previous
              </button>

              {(() => {
                const pageIndex = table.getState().pagination.pageIndex;
                const pageCount = table.getPageCount();
                const windowSize = 5;
                let start = Math.max(0, pageIndex - Math.floor(windowSize / 2));
                let end = start + windowSize;

                if (end > pageCount) {
                  end = pageCount;
                  start = Math.max(0, end - windowSize);
                }

                return Array.from({ length: end - start }, (_, i) => {
                  const pageNum = start + i;
                  return (
                    <button type="button" className="link-button-reset duality-p-0p25rem-0p5rem-radius-4px-decoration-underline-97edf"
                      key={pageNum}
                      onClick={(e) => {
                        e.preventDefault();
                        table.setPageIndex(pageNum);
                      }}
                      style={{ color: pageNum === pageIndex ? "#fff" : "#007BFF", backgroundColor: pageNum === pageIndex ? "#007BFF" : "transparent" }}
                              >
                      {pageNum + 1}
                    </button>
                  );
                });
              })()}

              <button type="button" className="link-button-reset duality-decoration-underline-cursor-pointer"
                onClick={(e) => {
                  e.preventDefault();
                  table.nextPage();
                }}
                style={{ color: table.getCanNextPage() ? "#007BFF" : "#A0A0A0", pointerEvents: table.getCanNextPage() ? "auto" : "none" }}
                  >
                Next
              </button>
            </div>
          </>}

        </div>
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>
            Back to Filter History
          </button>
          <button
            className="wizard-next-button"
            disabled={!canProceed || isDatasourceLoading}
            onClick={() => {
              if (!canProceed || isDatasourceLoading) return;
              handleContinue();
            }}
          >
            Set Modeling Method
          </button>
        </div>
      </div>
    </>
  );
};

export default FilterScreenPatients_CancerType;