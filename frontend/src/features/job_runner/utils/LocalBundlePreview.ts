import { strFromU8, unzipSync } from "fflate";
import { Medication } from "../../../types/Medication";
import { Observation } from "../../../types/Observation";
import { Patient } from "../../../types/Patient";

export interface LocalBundlePreviewData {
  patients: Patient[];
  medications: Medication[];
  observations: Observation[];
}

// Match the Biomarker patient-preview datasource behavior: MySQL stores the
// runtime JSON filename, while the browser resolves the corresponding ZIP from
// /public/test-data. Versioned archives such as _v1.zip, _v2.zip, etc. are
// discovered automatically rather than hardcoded.

interface InFlightGeneralStatisticsLoad {
  promise: Promise<LocalBundlePreviewData>;
}

const inFlightGeneralStatisticsLoads = new Map<string, InFlightGeneralStatisticsLoad>();

const GS_DEBUG = "[GeneralStatisticsPreview]";

function normalizeDatasourceToZipUrl(source: string): string {
  const trimmed = String(source || "").trim();
  if (!trimmed) {
    throw new Error("General Statistics datasource source is empty.");
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
    const exists = isDatasourceFileResponse(headRes);
    console.log(GS_DEBUG, "ZIP probe HEAD", { url, status: headRes.status, contentType: headRes.headers.get("content-type"), exists });
    if (exists) {
      return true;
    }

    if (headRes.status !== 405) {
      return false;
    }
  } catch (error) {
    console.log(GS_DEBUG, "ZIP probe HEAD failed; trying GET", { url, error });
  }

  try {
    const getRes = await fetch(probeUrl, {
      method: "GET",
      cache: "no-store",
      headers: { Range: "bytes=0-0" }
    });

    const exists = isDatasourceFileResponse(getRes);
    console.log(GS_DEBUG, "ZIP probe GET", { url, status: getRes.status, contentType: getRes.headers.get("content-type"), exists });
    return exists;
  } catch (error) {
    console.log(GS_DEBUG, "ZIP probe GET failed", { url, error });
    return false;
  }
}

async function resolveLatestDatasourceZipUrl(source: string): Promise<string> {
  const fallbackUrl = normalizeDatasourceToZipUrl(source);
  console.groupCollapsed(`${GS_DEBUG} resolving datasource ZIP`);
  console.log(GS_DEBUG, "configured datasource", source);
  console.log(GS_DEBUG, "base ZIP candidate", fallbackUrl);
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
    console.log(GS_DEBUG, "selected ZIP", latestUrl);
    console.groupEnd();
    return latestUrl;
  }

  console.error(GS_DEBUG, "no datasource ZIP found", { source, fallbackUrl });
  console.groupEnd();
  throw new Error(
    `Datasource ZIP not found for "${source}". Expected a file matching ${fallbackUrl} ` +
    `or a versioned variant such as ${stem}_v1${extension} under /test-data.`
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

async function loadGeneralStatisticsPreviewDataCore(
  fhirSource: string
): Promise<LocalBundlePreviewData> {
  console.group(`${GS_DEBUG} load`);
  console.log(GS_DEBUG, "starting load", { fhirSource });
  const zipUrl = await resolveLatestDatasourceZipUrl(fhirSource);
  console.log(GS_DEBUG, "resolved ZIP URL", zipUrl);
  const requestUrl = `${zipUrl}${zipUrl.includes("?") ? "&" : "?"}_=${Date.now()}`;
  const response = await fetch(requestUrl, { cache: "no-store" });
  console.log(GS_DEBUG, "ZIP response", {
    requested: requestUrl,
    status: response.status,
    ok: response.ok,
    contentType: response.headers.get("content-type"),
    contentLength: response.headers.get("content-length")
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch datasource ZIP ${zipUrl}: HTTP ${response.status}`);
  }

  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("text/html")) {
    throw new Error(
      `Datasource ZIP request returned HTML instead of a ZIP: ${zipUrl}. ` +
      `Check that the file exists under frontend/public/test-data with the expected filename.`
    );
  }

  const zipBytes = new Uint8Array(await response.arrayBuffer());
  console.log(GS_DEBUG, "downloaded ZIP bytes", { byteLength: zipBytes.length, signature: Array.from(zipBytes.slice(0, 4)) });
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

  let files: ReturnType<typeof unzipSync>;
  try {
    files = unzipSync(zipBytes);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Unable to unzip datasource ${zipUrl}: ${message}`);
  }

  // Biomarker intentionally uses the JSON actually present in the archive rather
  // than assuming that the member name includes the archive version suffix.
  const archiveFilenames = Object.keys(files);
  console.log(GS_DEBUG, "archive contents", archiveFilenames);
  const jsonFilename = archiveFilenames.find((name) => name.toLowerCase().endsWith(".json")) || "";
  console.log(GS_DEBUG, "selected JSON member", jsonFilename);

  if (!jsonFilename) {
    const names = Object.keys(files || {}).join(", ");
    throw new Error(`No JSON file found in ${zipUrl}. Found: ${names}`);
  }

  const fileBytes = files[jsonFilename] as Uint8Array | undefined;
  if (!fileBytes) {
    throw new Error(`Unable to read ${jsonFilename} from ${zipUrl}.`);
  }

  const jsonText = strFromU8(fileBytes);
  if (jsonText.trimStart().startsWith("<")) {
    throw new Error(`${jsonFilename} inside ${zipUrl} contains HTML instead of JSON.`);
  }

  let bundle: any;
  try {
    bundle = JSON.parse(jsonText);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Unable to parse ${jsonFilename} from ${zipUrl}: ${message}`);
  }

  const entries = Array.isArray(bundle?.entry) ? bundle.entry : [];
  const resourceTypeCounts = entries.reduce((counts: Record<string, number>, entry: any) => {
    const type = String(entry?.resource?.resourceType || "<missing>");
    counts[type] = (counts[type] || 0) + 1;
    return counts;
  }, {});
  console.log(GS_DEBUG, "parsed FHIR bundle", {
    bundleResourceType: bundle?.resourceType,
    entryCount: entries.length,
    resourceTypeCounts
  });

  const patients: Patient[] = entries
    .filter((entry: any) => entry?.resource?.resourceType === "Patient")
    .map((entry: any) => {
      const resource = entry.resource;
      const name = resource.name?.[0] || {};
      return {
        id: resource.id || "",
        family: name.family || "",
        given: Array.isArray(name.given) ? name.given.join(" ") : "",
        gender: resource.gender || "",
        birthDate: resource.birthDate || "",
        deceasedDateTime: resource.deceasedDateTime || resource.deceasedDate || "",
        fullUrl: entry.fullUrl || (resource.id ? `Patient/${resource.id}` : "")
      } as Patient;
    });

  const medications: Medication[] = entries
    .filter((entry: any) => entry?.resource?.resourceType === "MedicationStatement")
    .map((entry: any) => ({
      id: entry.resource.id || "",
      subjectReference: entry.resource.subject?.reference || "",
      medicationCodeableConcept: entry.resource.medicationCodeableConcept,
      status: entry.resource.status || "unknown"
    }));

  const observations: Observation[] = entries
    .filter((entry: any) => entry?.resource?.resourceType === "Observation")
    .map((entry: any) => ({
      id: entry.resource.id || "",
      subjectReference: entry.resource.subject?.reference || "",
      components: entry.resource.component || [],
      code: entry.resource.code,
      interpretation: entry.resource.interpretation
    }));

  console.log(GS_DEBUG, "normalized preview data", {
    patients: patients.length,
    medications: medications.length,
    observations: observations.length,
    firstPatient: patients[0] || null,
    firstMedication: medications[0] || null,
    firstObservation: observations[0] || null
  });
  console.groupEnd();

  return { patients, medications, observations };
}

export async function loadGeneralStatisticsPreviewData(
  fhirSource: string
): Promise<LocalBundlePreviewData> {
  const sourceKey = String(fhirSource || "").trim();
  console.log(GS_DEBUG, "load requested", { sourceKey });
  const existingLoad = inFlightGeneralStatisticsLoads.get(sourceKey);
  if (existingLoad) {
    console.log(GS_DEBUG, "joining in-flight load", sourceKey);
    return existingLoad.promise;
  }

  const inFlight: InFlightGeneralStatisticsLoad = {
    promise: loadGeneralStatisticsPreviewDataCore(sourceKey)
  };
  inFlightGeneralStatisticsLoads.set(sourceKey, inFlight);

  try {
    return await inFlight.promise;
  } catch (error) {
    console.error(GS_DEBUG, "load failed", error);
    try { console.groupEnd(); } catch {}
    throw error;
  } finally {
    if (inFlightGeneralStatisticsLoads.get(sourceKey) === inFlight) {
      inFlightGeneralStatisticsLoads.delete(sourceKey);
    }
  }
}
