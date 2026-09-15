export interface ThresholdPayload {
  id: number;
  method: string;
  threshold: number;
}

export interface CryptoAuditRecord {
  nvflare_job_id: string;
  security_level?: string | null;
  ring_dimension: number;
  batch_size: number;
  scale_mod_size: number;
  multiplicative_depth: number;
  scaling_technique: string;
  keyswitch_technique: string;
  ckks_data_type: string;
  ind_cpa_noise_bits: number;
  created_at?: string | null;
}

export interface DatasourceLogPayload {
  project_id: number;
  datasource_group_id?: number | null;
  datasource_group_name?: string | null;
  create_date?: string | null;
  update_date?: string | null;
}

export interface WorkflowGroupSelectedOption {
  workflow_group_option_id?: number;
  option_key?: string;
  option_label?: string;
  option_value?: string;
}

export interface WorkflowGroupSelection {
  nvflare_job_workflow_group_id?: number;
  workflow_group_id?: number;
  group_key?: string;
  group_label?: string;
  selected_options?: WorkflowGroupSelectedOption[];
}

export interface NVFlareJob {
  id: number;
  nvflare_assigned_id?: string;
  filter_id?: number;
  status?: string;
  job_path?: string;
  output_path?: string;
  job_runner_id?: string;
  non_contributing_clients?: string | null;
  exclude_analyzing_clients?: string | null;
  submit_time?: string;
  run_duration?: string;
  create_date: string;
  update_date: string;
  completed_date?: string;
  functions?: string[];
  functions_map?: Record<string, Record<string, string> | Record<string, string>[]>;
  threshold?: ThresholdPayload;
  crypto_audit_record?: CryptoAuditRecord;
  datasource_group_id?: number | null;
  datasource_group_name?: string | null;
  datasource_log?: DatasourceLogPayload;
  workflow_group_data?: Record<string, string[]>;
  workflow_groups?: WorkflowGroupSelection[];
}

export interface JobLogEntry {
  timestamp: string;
  message: string;
}

export interface JobLogData {
  jobId?: string;
  jobStatus?: string;
  jobLog?: string[];
  referencedBy?: string[];
  run_duration?: string;
  functions?: string[];
}