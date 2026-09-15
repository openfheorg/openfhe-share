// src/features/job_runner/types/FilterSchema.ts
export type FilterType =
  | "PATIENT_QUERY"
  | "PATIENT_DATA"
  | "OBSERVATION"
  | "OBSERVATION_QUERY"
  | "OBSERVATION_DATA";

export interface Condition {
  filter_type: FilterType;
  column_name: string;
  operator: string;
  value?: string;
  values?: string[];
}

export interface FilterCollection {
  patientQueryFilters: string;
  patientDataFilters: string;
  observationQueryFilters: string;
  observationDataFilters: string;
}

export interface SaveTargetSchema {
  filter_type?: FilterType;
  column_name?: string;
  filter_group?: FilterType;
  field?: string;
  operator: string;
  valueFrom?: "value";
  transform?: "int" | "float" | "string";
}

export interface SaveSchema {
  targets?: SaveTargetSchema[];
}

export type ControlFHIR =
  | {
      kind: "search-param";
      param: string;
      value?: string;
    }
  | {
      kind: "date-range";
      param: string;
    }
  | {
      kind: "component-value-concept";
      component: {
        system: string;
        code: string;
      };
    }
  | {
      kind: "reverse-chain";
      has: {
        resource: string;
        referenceParam: string;
        filterParam: string;
      };
    };

export interface QuerySchema {
  filter_type?: FilterType;
  column_name?: string;
  filter_group?: FilterType;
  field?: string;
  kind?: "search-param" | "date-range" | "reverse-chain-token";
  param?: string;
  startPrefix?: string;
  endPrefix?: string;
  resource?: string;
  referenceParam?: string;
}

export interface ControlOption {
  label: string;
  value?: string;
  token?: string;
}

export interface ControlSchema {
  id: string;
  field?: string;
  label?: string;
  type:
    | "select"
    | "multi-select"
    | "multi-select-grid"
    | "number"
    | "checkbox"
    | "date-range"
    | "hidden"
    | "token-select"
    | "label"
    | string;
  default?: any;
  disabled?: boolean;
  options?: ControlOption[];
  fhir?: ControlFHIR;
  query?: QuerySchema;
  save?: SaveSchema;
  ui?: {
    span?: "full" | "half" | "third";
    editable?: boolean;
  };
}

export interface FilterSchema {
  version?: string;
  resource?: {
    type?: string;
  } | string;
  controls?: ControlSchema[];
  defaultsResolver?: Record<string, any>;
}