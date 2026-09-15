 // Figures out which to use based on npm start or Amplify's npm run build.
const LOCAL_API_BASE = "http://localhost:8000";
export const CLIENT_API_BASE_PORT = 8088;
export const CLIENT_API_BASE = `http://127.0.0.1:${CLIENT_API_BASE_PORT}`;
export const IS_LOCAL_APP = process.env.NODE_ENV === "development";
// The standalone (self-hosted) frontend is a production bundle, so NODE_ENV is
// "production" there just like the hosted AWS build. REACT_APP_BUILD_FLAVOR is
// baked in at build time by standalone/docker_stage/frontend.Dockerfile
// (default "local") and is what distinguishes the self-hosted deployment.
export const IS_STANDALONE_APP = process.env.REACT_APP_BUILD_FLAVOR === "local";
const PROD_FALLBACK_API_BASE = "https://api.example.org";

export function getClientApiBase(clientName?: string | null): string {
  // Hosted AWS: every client browser reaches a single co-located results agent
  // at CLIENT_API_BASE. Local dev and standalone: each site runs its own agent
  // on CLIENT_API_BASE_PORT + siteNumber (site1 -> 8089, site2 -> 8090, ...).
  if (!IS_LOCAL_APP && !IS_STANDALONE_APP) {
    return CLIENT_API_BASE;
  }

  const normalizedClientName = (clientName ?? "").trim();
  const siteMatch = /^site[-_]?(\d+)$/i.exec(normalizedClientName);

  if (!siteMatch) {
    throw new Error(
      `The logged-in client does not have a valid NVFlare client name: ${normalizedClientName || "<missing>"}`
    );
  }

  const siteNumber = Number(siteMatch[1]);
  if (!Number.isSafeInteger(siteNumber) || siteNumber < 1) {
    throw new Error(`Invalid NVFlare client site number in ${normalizedClientName}`);
  }

  return `http://127.0.0.1:${CLIENT_API_BASE_PORT + siteNumber}`;
}

export const ALB_API_BASE = "http://api.example.org"

//used for websocket:
export const PROD_FALLBACK_API_WS_BASE = "wss://ws.example.org/prod"

export const API_BASE =
  process.env.NODE_ENV === "development"
    ? LOCAL_API_BASE
    : process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_BASE;

export const WS_API_BASE =
  process.env.NODE_ENV === "development"
    ? LOCAL_API_BASE
    : process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_WS_BASE;

export const API_SUBMIT_JOB = "/nvflare/jobs/submit";
export const API_JOB_HISTORY = "/nvflare/jobs/history";
export const API_JOB_RESULTS_CONTEXT = "/nvflare/jobs/results_context";
export const API_LANDING_HOME = "/landing/home";
export const API_LANDING_PROJECT = "/landing/project";

export const API_JOB_STATUS = "/jobs/status";
export const API_JOB_STATUS_WEBSOCKET = "/jobs/status/ws";

export const API_JOB_RESULTS = "/jobs/results";
export const API_JOB_RESULTS_MAPPING = "/jobs/results/mapping";
export const API_JOB_RESULTS_FUNCTION_CONFIG = "/jobs/function/config";
export const API_JOB_TASKFLOW_START = "/jobs/taskflow/start";
export const API_JOB_TASKFLOW_STATUS = "/jobs/taskflow/status";
export const API_JOB_TASKFLOW_ARTIFACT = "/jobs/taskflow/artifact";


export const API_FILTERS_FETCH_SINGLE = "/filters/fetch_single_filter"
export const API_FILTERS_FETCH = "/filters/fetch_filters"

export const API_FUNCTIONS_SUPPORTED = "/functions/supported_functions"

export const API_CLIENTS_PARTICIPATION_STATUS = "/clients/participation/status"
export const API_CLIENTS_CONNECTION_STATUS = "/clients/connection/status"

export const API_PROJECTS_LIST = "/projects/list"
export const API_PROJECTS_FHIR_SOURCE = "/projects/fhir/source"


export enum SupportedFunction {
  SURVIVAL_ANALYSIS = "SURVIVAL_ANALYSIS",
  CHI_SQUARE_TEST = "CHI_SQUARE_TEST",
  STANDARD_DEVIATION = "STANDARD_DEVIATION",
  MEAN = "MEAN",
  T_TEST = "T_TEST",
  EXCEPTIONAL_RESPONSE_DISCRIMINATION = "EXCEPTIONAL_RESPONSE_DISCRIMINATION"
}


export const DELETION_REGIONS = [
  "10q23.31",
  "10q26.3",
  "11q12.3",
  "11q23.1",
  "12q24.33",
  "14q32.33",
  "15q11.2",
  "19p13.3",
  "19q13.42",
  "1p36.11",
  "1p36.31",
  "1q42.3",
  "22q11.21",
  "2q37.1",
  "3p21.1",
  "5q14.1",
  "6p12.1",
  "6p21.32",
  "6p22.2",
  "6q25.2",
  "8p23.2",
  "9p21.3",
  "9q34.3",
] as const;

export const AMPLIFICATION_REGIONS = [
  "11q13.3",
  "11q14.1",
  "12q24.32",
  "17q21.2",
  "17q25.3",
  "1p36.32",
  "1q21.3",
  "1q32.1",
  "20q13.33",
  "21q22.3",
  "2q37.3",
  "5p15.33",
  "5q31.3",
  "5q35.3",
  "6p21.2",
  "6q21",
  "7p22.2",
  "7q36.2",
  "8p11.21",
  "8q24.3",
  "9q34.11",
] as const;

export type Cytoband = typeof DELETION_REGIONS[number] | typeof AMPLIFICATION_REGIONS[number];

export const description_job_runner = `The NVFlare Analysis Runner lets you launch 
and monitor analytics jobs. To begin, create a new filter set or select one 
from your saved list (a single filter set applies to all chosen functions), 
then pick one or more analysis functions, review function configuration, 
verify client connectivity and participation, and submit.`;

export const description_job_history = `All previously run NVFlare analyses, both 
successful and unsuccessful, will reside here. Each record contains information on 
the creation date, run duration, functions selected, configurations per 
function, and log output from the job run. By default the query looks for 
jobs from the last 30 days. To adjust, expand the Query Configuration section.`;

export const description_nvflare_manager = `This management screen provides access to 
client connectivity state. COMING SOON: User -> Client mapping records, unused client 
startup kit overview.`;
