import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from "@tanstack/react-table";
import { ChevronDown, ChevronUp } from "react-bootstrap-icons";
import { Medication } from "../../../../../types/Medication";
import { Patient } from "../../../../../types/Patient";
import { Project } from "../../../../../types/Project";
import FilterControlsSection from "../../../components/FilterControlsSection";
import DatasourceGroupSelector from "../../../components/DatasourceGroupSelector";
import {
  buildDefaultFilterCollectionFromConditions,
  Condition,
  createEmptyFilterCollection,
  FilterCollection,
  getInitialValuesFromCollection
} from "../../../utils/FilterPayloadConfigUtils";

interface FilterScreenPatientsJSONProps {
  project: Project;
  patients: Patient[];
  medications: Medication[];
  loading: boolean;
  loadError: string;
  onBack: () => void;
  onProceedToVariants: (patients: Patient[]) => void;
  setFilterCollection: <K extends keyof FilterCollection>(key: K, jsonString: string) => void;
  existingQueryFilter: string | null;
  existingPatientFilter: string | null;
  lockFilterConfig: boolean;
  selectedDatasourceGroupId: number | null;
  onSelectedDatasourceGroupIdChange: (datasourceGroupId: number | null) => void;
}

function patientIdFromReference(reference: unknown): string {
  const value = String(reference || "").trim();
  const marker = value.lastIndexOf("Patient/");
  return marker >= 0 ? value.slice(marker + "Patient/".length) : value;
}

function dateInRange(value: string | undefined, values: string[] | undefined): boolean {
  if (!value || !Array.isArray(values) || values.length !== 2) return false;
  const date = value.slice(0, 10);
  const lower = String(values[0] || "").slice(0, 10);
  const upper = String(values[1] || "").slice(0, 10);
  return Boolean(date && (!lower || lower <= date) && (!upper || date <= upper));
}

function medicationMatches(patient: Patient, medications: Medication[], wantedValue: unknown): boolean {
  // FHIR token search uses comma-separated values as OR (for example
  // J7527,J9299 means Everolimus OR Nivolumab). Mirror that behavior for
  // local JSON previews so they produce the same cohort as the FHIR-server
  // query path and the NVFlare local-bundle filter engine.
  const wantedTokens = String(wantedValue || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  if (wantedTokens.length === 0) return false;

  return medications.some((medication) => {
    const reference = String(medication.subjectReference || "").trim();
    if (
      reference !== patient.fullUrl &&
      reference !== `Patient/${patient.id}` &&
      patientIdFromReference(reference) !== String(patient.id || "")
    ) return false;

    return (medication.medicationCodeableConcept?.coding || []).some((coding: any) => {
      const system = String(coding?.system || "").trim().toLowerCase();
      const code = String(coding?.code || "").trim().toLowerCase();
      const display = String(coding?.display || "").trim().toLowerCase();
      const token = `${system}|${code}`;
      return wantedTokens.some(
        (wanted) => wanted === code || wanted === display || wanted === token
      );
    });
  });
}

function patientMatches(patient: Patient, medications: Medication[], conditions: Condition[]): boolean {
  return conditions.every((condition) => {
    const column = String(condition.column_name || "").trim();
    if (condition.filter_type !== "PATIENT_QUERY" && condition.filter_type !== "PATIENT_DATA") return true;
    if (column === "gender") {
      const wanted = String(condition.value || "").trim().toLowerCase();
      return !wanted || String(patient.gender || "").trim().toLowerCase() === wanted;
    }
    if (column === "birthDate") return dateInRange(patient.birthDate, condition.values);
    if (column === "deceased_date") return dateInRange(patient.deceasedDateTime, condition.values);
    if (column === "medication") return medicationMatches(patient, medications, condition.value);
    return true;
  });
}

const FilterScreenPatientsJSON: React.FC<FilterScreenPatientsJSONProps> = ({
  project,
  patients,
  medications,
  loading,
  loadError,
  onBack,
  onProceedToVariants,
  setFilterCollection,
  existingQueryFilter,
  existingPatientFilter,
  lockFilterConfig,
  selectedDatasourceGroupId,
  onSelectedDatasourceGroupIdChange
}) => {
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [initialValues, setInitialValues] = useState<Record<string, any>>({});

  useEffect(() => {
    const collection = createEmptyFilterCollection();
    collection.patientQueryFilters = existingQueryFilter || "{}";
    collection.patientDataFilters = existingPatientFilter || "{}";
    setInitialValues(getInitialValuesFromCollection(collection, project));
  }, [existingPatientFilter, existingQueryFilter, project]);

  const handleCompiledChange = useCallback(({ conditions: next }: { conditions: Condition[] }) => {
    const patientConditions = (next || []).filter(
      (condition) => condition.filter_type === "PATIENT_QUERY" || condition.filter_type === "PATIENT_DATA"
    );
    console.log("[GeneralStatisticsPreview][PatientFilters] compiled conditions", patientConditions);
    setConditions(patientConditions);
  }, []);

  const filteredPatients = useMemo(
    () => (loading || loadError ? [] : patients.filter((patient) => patientMatches(patient, medications, conditions))),
    [conditions, loadError, loading, medications, patients]
  );

  useEffect(() => {
    const medicationValues = Array.from(
      new Set(
        medications.flatMap((medication) =>
          (medication.medicationCodeableConcept?.coding || []).flatMap((coding: any) => [
            coding?.code,
            coding?.display,
            coding?.system && coding?.code ? `${coding.system}|${coding.code}` : null
          ]).filter(Boolean)
        )
      )
    ).slice(0, 50);

    const conditionDiagnostics = conditions.map((condition) => ({
      condition,
      matchesIndependently: patients.filter((patient) => patientMatches(patient, medications, [condition])).length
    }));

    console.group("[GeneralStatisticsPreview][PatientFilters] filter diagnostics");
    console.log("[GeneralStatisticsPreview][PatientFilters] incoming data", {
      loading,
      loadError,
      patientCount: patients.length,
      medicationCount: medications.length,
      firstPatient: patients[0] || null,
      firstMedication: medications[0] || null
    });
    console.log("[GeneralStatisticsPreview][PatientFilters] conditions", conditions);
    console.log("[GeneralStatisticsPreview][PatientFilters] matches by condition", conditionDiagnostics);
    console.log("[GeneralStatisticsPreview][PatientFilters] available medication values", medicationValues);
    console.log("[GeneralStatisticsPreview][PatientFilters] final filtered count", filteredPatients.length);
    console.groupEnd();
  }, [conditions, filteredPatients.length, loadError, loading, medications, patients]);

  const columns = useMemo<ColumnDef<Patient>[]>(
    () => [
      { accessorKey: "id", header: "ID" },
      { accessorKey: "family", header: "Family Name" },
      { accessorKey: "given", header: "Given Name" },
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
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row: any) => row.id || row.ID || JSON.stringify(row),
    initialState: { pagination: { pageSize: 10 } }
  });

  useEffect(() => {
    table.setPageIndex(0);
  }, [conditions, table]);

  const handleContinue = () => {
    if (loading || loadError || filteredPatients.length === 0) return;
    if (!lockFilterConfig) {
      const collection = buildDefaultFilterCollectionFromConditions(conditions, project);
      setFilterCollection("patientQueryFilters", collection.patientQueryFilters);
      setFilterCollection("patientDataFilters", collection.patientDataFilters);
    }
    onProceedToVariants(filteredPatients);
  };

  return (
    <>
      <div className="page-container">
        <div className="child-container-top">
          <DatasourceGroupSelector
            project={project}
            selectedDatasourceGroupId={selectedDatasourceGroupId}
            onChange={onSelectedDatasourceGroupIdChange}
            disabled={lockFilterConfig}
          />
          <h3 className="duality-mb-075">Patient Filters</h3>
          <div className="duality-mt-0p75rem-mb-1rem">
            <FilterControlsSection
              project={project}
              filterType="PATIENT_QUERY"
              initialConditions={[]}
              initialValues={initialValues}
              lock={lockFilterConfig}
              onCompiledChange={handleCompiledChange}
            />
          </div>

          <div className="filter-screen-patients-block-03">
            <h3>Patient Data Preview</h3>
            {!loading && !loadError && <h4 className="filter-screen-patients-h4">Total Results: {filteredPatients.length}</h4>}
          </div>
          {loading && <div className="duality-p-0p75rem">Loading local General Statistics bundle...</div>}
          {loadError && <div className="duality-mb-0p75rem-mr-1rem-p-0p75rem">{loadError}</div>}
          {!loading && !loadError && (
            <>
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
                          {header.column.getIsSorted() === "desc" && <ChevronDown size={12} />} {flexRender(header.column.columnDef.header, header.getContext())}
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
                  {table.getRowModel().rows.length === 0 && (
                    <tr><td colSpan={columns.length} className="duality-p-0p75rem">No patients match the current filters.</td></tr>
                  )}
                </tbody>
              </table>
              <div className="duality-d-flex-justify-center-align-center-7b984">
                <button type="button" className="link-button-reset duality-underline" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>Previous</button>
                <span>Page {table.getState().pagination.pageIndex + 1} of {Math.max(table.getPageCount(), 1)}</span>
                <button type="button" className="link-button-reset duality-underline" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>Next</button>
              </div>
            </>
          )}
        </div>
      </div>
      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>Back to Filter History</button>
          <button className="wizard-next-button" disabled={loading || Boolean(loadError) || filteredPatients.length === 0} onClick={handleContinue}>
            Filter by Genetic Variant Assessments
          </button>
        </div>
      </div>
    </>
  );
};

export default FilterScreenPatientsJSON;
