import { FilterSchema, FilterType } from "./FilterSchema";

export type JsonObject = Record<string, any>;

export interface ProjectFunctionCapability {
  function: string;
  configurable: boolean;
  custom_configuration_fixed?: JsonObject | null;
  custom_configuration_variable?: JsonObject | null;
  override_configuration?: JsonObject | null;
}

export type FilterSystem = "DEFAULT" | "CANCER_TYPE" | (string & {});

export interface ProjectDatasourceGroup {
  id: number;
  project_id: number;
  group_name: string;
  is_default: boolean;
}



export interface WorkflowGroupValidationConfig {
  enabled?: boolean;
  validation_type?: string;
  endpoint?: string;
  method?: string;
  username?: string;
  user_id?: number;
  model_file_lookup_key?: string;
  lookup_value_context_key?: string;
  option_values_request_field?: string;
  required_artifact_types?: string[];
  available_values_response_field?: string;
  availability_response_field?: string;
  disabled_label_suffix?: string;
  disabled_reason?: string;
  [key: string]: any;
}

export interface ProjectWorkflowGroupOption {
  id?: number;
  option_key?: string;
  option_label?: string;
  option_value: string;
  option_order?: number;
  option_description?: string | null;
  is_default?: boolean;
  status?: string | null;
}

export interface ProjectWorkflowGroup {
  id?: number;
  group_key: string;
  group_label: string;
  group_description?: string | null;
  min_selected?: number | null;
  max_selected?: number | null;
  is_required?: boolean;
  page_order?: number;
  status?: string | null;
  validation_config?: WorkflowGroupValidationConfig | null;
  options: ProjectWorkflowGroupOption[];
}

export interface WorkflowGroupSelection {
  group_key: string;
  selected_values: string[];
}

export type WorkflowGroupData = Record<string, WorkflowGroupSelection>;

export interface Project {
  id: number;
  name: string;
  description?: string | null;
  status?: string | null;
  fixed?: boolean | null;
  function_restrictions_enabled: boolean;
  model_file_settings_enabled?: boolean | null;
  filter_system?: FilterSystem | null;
  filter_system_allowed_filter_types?: FilterType[] | null;
  filter_schemas: Partial<Record<FilterType, FilterSchema>>;
  functions: ProjectFunctionCapability[];
  datasource_groups_defined?: boolean;
  datasource_groups?: ProjectDatasourceGroup[] | null;
  default_datasource_group?: ProjectDatasourceGroup | null;
  workflow_groups?: ProjectWorkflowGroup[] | null;
  create_date?: string | null;
  update_date?: string | null;
  /** Optional project summary value when supplied by the project landing endpoint. */
  registered_user_count?: number | null;
}