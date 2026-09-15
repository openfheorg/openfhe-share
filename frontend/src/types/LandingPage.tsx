import { ProjectDatasourceGroup, ProjectFunctionCapability } from "./Project";
import { NVFlareJob } from "./JobsDataTypes";

export interface LandingHomeJobStatus {
  status: string;
  count: number;
}

export interface LandingHomeUserRole {
  role_id: number;
  role: string;
  description?: string | null;
  count: number;
}

export interface LandingHomeFunction {
  id: number;
  name: string;
  description?: string | null;
}

export interface LandingHomeSummary {
  total_jobs: number;
  total_users?: number;
  total_functions: number;
  job_statuses?: LandingHomeJobStatus[];
  user_roles?: LandingHomeUserRole[];
  functions: LandingHomeFunction[];
}

export interface LandingHomeResponse {
  status: string;
  home?: LandingHomeSummary;
  error?: string;
}

export interface LandingProjectSummary {
  id: number;
  name: string;
  description?: string | null;
  status?: string | null;
  fixed?: boolean | null;
  function_restrictions_enabled: boolean;
  model_file_settings_enabled?: boolean | null;
  filter_system_id?: number | null;
  filter_system?: string | null;
  registered_user_count: number;
  total_jobs: number;
  function_count: number;
  datasource_groups_defined: boolean;
  datasource_groups: ProjectDatasourceGroup[];
  default_datasource_group?: ProjectDatasourceGroup | null;
  functions: ProjectFunctionCapability[];
}


export interface LandingProjectFunctionUsage {
  functions: string[];
  count: number;
}

export interface LandingProjectResponse {
  status: string;
  project?: LandingProjectSummary;
  recent_jobs?: NVFlareJob[];
  function_usage_distribution?: LandingProjectFunctionUsage[];
  error?: string;
}
