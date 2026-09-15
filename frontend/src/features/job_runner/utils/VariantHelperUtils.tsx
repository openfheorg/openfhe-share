import { Patient } from "../../../types/Patient";

export interface PatientVariantRow {
  patient: Patient;
  variants: { [key: string]: number };
  totalVariants: number;
  regions: string[];
}

export function buildPatientVariantSummary(
  selectedPatients: Patient[],
  patientVariantSummary: {
    [key: string]: {
      [key: string]: number;
    };
  },
  patientRegionSummary: {
    [key: string]: string[];
  }
): PatientVariantRow[] {
  return selectedPatients.map(patient => {
    const variants = patientVariantSummary[patient.fullUrl] || {};
    const regions = patientRegionSummary[patient.fullUrl] || [];
    const totalVariants = Object.values(variants).reduce((sum, count) => sum + count, 0);
    return { patient, variants, totalVariants, regions };
  });
}