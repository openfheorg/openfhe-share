import { buildPatientVariantSummary } from "./VariantHelperUtils";
import { Patient } from "../../../types/Patient";

const patient = (fullUrl: string): Patient => ({ fullUrl } as Patient);

describe("buildPatientVariantSummary", () => {
  test("combines variants, totals, and regions for each selected patient", () => {
    const patients = [patient("Patient/1"), patient("Patient/2")];

    expect(
      buildPatientVariantSummary(
        patients,
        {
          "Patient/1": { TP53: 2, VHL: 1 },
          "Patient/2": { PBRM1: 4 },
        },
        {
          "Patient/1": ["exon-1"],
          "Patient/2": ["exon-2", "exon-3"],
        }
      )
    ).toEqual([
      {
        patient: patients[0],
        variants: { TP53: 2, VHL: 1 },
        totalVariants: 3,
        regions: ["exon-1"],
      },
      {
        patient: patients[1],
        variants: { PBRM1: 4 },
        totalVariants: 4,
        regions: ["exon-2", "exon-3"],
      },
    ]);
  });

  test("uses empty summaries when a patient has no variant data", () => {
    const p = patient("Patient/missing");
    expect(buildPatientVariantSummary([p], {}, {})).toEqual([
      { patient: p, variants: {}, totalVariants: 0, regions: [] },
    ]);
  });

  test("preserves selected patient ordering", () => {
    const patients = [patient("Patient/2"), patient("Patient/1")];
    expect(buildPatientVariantSummary(patients, {}, {}).map((row) => row.patient.fullUrl)).toEqual([
      "Patient/2",
      "Patient/1",
    ]);
  });
});
