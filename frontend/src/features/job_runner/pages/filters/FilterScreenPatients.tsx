import React from "react";
import { Patient } from "../../../../types/Patient";
import { Medication } from "../../../../types/Medication";
import DefaultFilterScreenPatients from "./default/FilterScreenPatients";
import FilterScreenPatientsCancerType from "./cancer_type/FilterScreenPatients_CancerType";
import { FilterCollection } from "../../utils/FilterPayloadConfigUtils";
import { Project } from "../../../../types/Project";

export interface PatientQuery {
  gender?: string;
  ageRange?: [number, number];
  medication?: string;
}

interface FilterScreenPatientsProps {
  project: Project;
  filterSystem?: string | null;
  patients: Patient[];
  medications: Medication[];
  onBack: () => void;
  onProceedToVariants: (patients: Patient[]) => void;
  setFilterCollection: <K extends keyof FilterCollection>(key: K, jsonString: string) => void;
  existingQueryFilter: string | null;
  existingPatientFilter: string | null;
  lockFilterConfig: boolean;
  selectedDatasourceGroupId: number | null;
  onSelectedDatasourceGroupIdChange: (datasourceGroupId: number | null) => void;
}

const FilterScreenPatients: React.FC<FilterScreenPatientsProps> = ({
  filterSystem,
  ...rest
}) => {
  const fs = String(filterSystem || "DEFAULT").trim().toUpperCase();

  if (fs === "CANCER_TYPE") {
    return <FilterScreenPatientsCancerType {...rest} />;
  }

  return <DefaultFilterScreenPatients {...rest} />;
};

export default FilterScreenPatients;
