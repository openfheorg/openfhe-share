import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from "@tanstack/react-table";
import { ChevronDown, ChevronUp, Clipboard } from "react-bootstrap-icons";
import { Patient } from "../../../../../types/Patient";
import { Medication } from "../../../../../types/Medication";
import FilterControlsSection from "../../../components/FilterControlsSection";
import {
  Condition,
  createEmptyFilterCollection,
  FilterCollection,
  FilterSchema,
  getInitialValuesFromCollection,
  buildDefaultFilterCollectionFromConditions
} from "../../../utils/FilterPayloadConfigUtils";
import { Project } from "../../../../../types/Project";
import { useFHIRSource, useUserSession } from "../../../../../context/UserRoleContext";
import { API_BASE, API_PROJECTS_FHIR_SOURCE } from "../../../../../constants/Constants";
import DatasourceGroupSelector from "../../../components/DatasourceGroupSelector";

const PREVIEW_PAGE_SIZE = 10;
const FULL_FETCH_PAGE_SIZE = 200;

interface QuerySchema {
  filter_type?: string;
  column_name?: string;
  filter_group?: string;
  field?: string;
  kind: "search-param" | "date-range" | "reverse-chain-token";
  param?: string;
  startPrefix?: string;
  endPrefix?: string;
  resource?: string;
  referenceParam?: string;
}

interface ControlSchema {
  id: string;
  field?: string;
  label: string;
  type: string;
  default?: any;
  query?: QuerySchema;
}

interface FhirBundleLink {
  relation?: string;
  url?: string;
}

interface FhirBundleEntry<T> {
  fullUrl?: string;
  resource?: T;
}

interface FhirPatientResource {
  resourceType: "Patient";
  id?: string;
  gender?: string;
  birthDate?: string;
  deceasedDateTime?: string;
  name?: Array<{
    family?: string;
    given?: string[];
  }>;
}

interface FhirBundle<T> {
  resourceType?: string;
  total?: number;
  entry?: Array<FhirBundleEntry<T>>;
  link?: FhirBundleLink[];
}

interface ProjectFHIRSourceQueryResponse {
  username?: string;
  user_id?: number;
  project_id?: number;
  source?: string;
  source_type?: "json" | "fhir_server";
  datasource_group?: number | null;
  datasource_group_name?: string | null;
  is_default_group?: boolean;
  query_executed?: boolean;
  query_execution_message?: string;
  executed_url?: string;
  query_status_code?: number;
  query_results?: FhirBundle<FhirPatientResource>;
}

interface FilterScreenPatientsProps {
  project: Project;
  patients: Patient[];
  medications: Medication[];
  onBack: () => void;
  onProceedToVariants: (patients: Patient[]) => void;
  setFilterCollection: <K extends keyof FilterCollection>(
    key: K,
    jsonString: string
  ) => void;
  existingQueryFilter: string | null;
  existingPatientFilter: string | null;
  lockFilterConfig: boolean;
  onConfigSelected?: (config: FilterCollection | null) => void;
  selectedFilterName?: string;
  setSelectedFilterName?: (name: string) => void;
  selectedDatasourceGroupId: number | null;
  onSelectedDatasourceGroupIdChange: (datasourceGroupId: number | null) => void;
}

function getSchemaResourceType(schema: FilterSchema | null): string {
  if (!schema?.resource) {
    return "Patient";
  }

  if (typeof schema.resource === "string") {
    return schema.resource;
  }

  if (typeof schema.resource === "object" && typeof schema.resource.type === "string") {
    return schema.resource.type;
  }

  return "Patient";
}

function getQueryMatchKey(query?: QuerySchema): string | null {
  if (!query) {
    return null;
  }

  const filterType = query.filter_group || query.filter_type;
  const field = query.field || query.column_name;

  if (!filterType || !field) {
    return null;
  }

  return `${filterType}::${field}`;
}

function buildConditionLookup(conditions: Condition[]): Map<string, Condition> {
  const map = new Map<string, Condition>();
  for (const condition of conditions) {
    if (condition.filter_type !== "PATIENT_QUERY") {
      continue;
    }
    const key = `${condition.filter_type}::${condition.column_name}`;
    map.set(key, condition);
  }
  return map;
}

function serializeConditionToQueryParts(
  control: ControlSchema,
  condition: Condition
): string[] {
  const query = control.query;
  if (!query) {
    return [];
  }

  if (condition.filter_type !== "PATIENT_QUERY") {
    return [];
  }

  if (query.kind === "search-param") {
    const rawValue = typeof condition.value === "string" ? condition.value.trim() : "";
    if (rawValue === "" || !query.param) {
      return [];
    }
    return [`${query.param}=${encodeURIComponent(rawValue)}`];
  }

  if (query.kind === "date-range") {
    if (!Array.isArray(condition.values) || !query.param) {
      return [];
    }

    const start = String(condition.values[0] || "").trim();
    const end = String(condition.values[1] || "").trim();
    const parts: string[] = [];

    if (start !== "") {
      parts.push(
        `${query.param}=${encodeURIComponent(`${query.startPrefix || "ge"}${start}`)}`
      );
    }

    if (end !== "") {
      parts.push(
        `${query.param}=${encodeURIComponent(`${query.endPrefix || "le"}${end}`)}`
      );
    }

    return parts;
  }

  if (query.kind === "reverse-chain-token") {
    const rawValue = typeof condition.value === "string" ? condition.value.trim() : "";
    if (
      rawValue === "" ||
      !query.resource ||
      !query.referenceParam ||
      !query.param
    ) {
      return [];
    }

    const key = `_has:${query.resource}:${query.referenceParam}:${query.param}`;
    return [`${key}=${encodeURIComponent(rawValue)}`];
  }

  return [];
}

function buildFhirQueryPreview(
  schema: FilterSchema | null,
  conditions: Condition[]
): string {
  const resource = getSchemaResourceType(schema);
  const controls = Array.isArray(schema?.controls) ? (schema?.controls as ControlSchema[]) : [];

  if (controls.length === 0) {
    return `/${resource}`;
  }

  const lookup = buildConditionLookup(conditions);
  const lines: string[] = [];

  for (const control of controls) {
    const query = control.query;
    if (!query) {
      continue;
    }

    const filterType = query.filter_group || query.filter_type;
    if (filterType !== "PATIENT_QUERY") {
      continue;
    }

    const key = getQueryMatchKey(query);
    if (!key) {
      continue;
    }

    const condition = lookup.get(key);
    if (!condition) {
      continue;
    }

    const parts = serializeConditionToQueryParts(control, condition);
    if (parts.length > 0) {
      lines.push(parts.join("&"));
    }
  }

  if (lines.length === 0) {
    return `/${resource}`;
  }

  return `/${resource}?\n${lines
    .map((line, index) => (index === 0 ? line : `&${line}`))
    .join("\n")}`;
}

function flattenPreviewToRelativeUrl(preview: string): string {
  return preview.replace(/\s*\n\s*/g, "").trim();
}

function buildExecuteQuery(relativePath: string, extraParams: Record<string, string>): string {
  const flattened = flattenPreviewToRelativeUrl(relativePath);
  const joiner = flattened.includes("?") ? "&" : "?";
  const extra = new URLSearchParams(extraParams).toString();
  return `${flattened}${extra ? `${joiner}${extra}` : ""}`;
}

function mapFhirPatientToPatient(
  resource: FhirPatientResource,
  fullUrl?: string
): Patient {
  const firstName = resource.name?.[0];

  return {
    id: resource.id || "",
    family: firstName?.family || "",
    given: (firstName?.given || []).join(" "),
    gender: resource.gender || "",
    birthDate: resource.birthDate || "",
    deceasedDateTime: resource.deceasedDateTime || "",
    fullUrl: fullUrl || (resource.id ? `Patient/${resource.id}` : "")
  } as Patient;
}

function getNextLink<T>(bundle: FhirBundle<T>): string | null {
  const nextLink = bundle.link?.find((link) => link.relation === "next" && !!link.url);
  return nextLink?.url || null;
}

function getRelativeExecuteQueryFromUrl(nextUrl: string, fhirSource: string | null): string | null {
  if (!nextUrl) {
    return null;
  }

  if (!fhirSource) {
    return null;
  }

  const normalizedSource = fhirSource.replace(/\/+$/, "");
  if (nextUrl.startsWith(normalizedSource)) {
    const relative = nextUrl.slice(normalizedSource.length);
    return relative.startsWith("/") ? relative : `/${relative}`;
  }

  try {
    const next = new URL(nextUrl);
    return `${next.pathname}${next.search}`;
  } catch {
    return null;
  }
}

const FilterScreenPatients: React.FC<FilterScreenPatientsProps> = ({
  project,
  patients,
  medications,
  onBack,
  onProceedToVariants,
  setFilterCollection,
  existingQueryFilter,
  existingPatientFilter,
  lockFilterConfig,
  selectedDatasourceGroupId,
  onSelectedDatasourceGroupIdChange
}) => {
  const userSession = useUserSession();
  const fhirSource = useFHIRSource();

  const [compiledConditions, setCompiledConditions] = useState<Condition[]>([]);
  const [previewPatients, setPreviewPatients] = useState<Patient[]>([]);
  const [allMatchedPatients, setAllMatchedPatients] = useState<Patient[]>([]);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [initialControlValues, setInitialControlValues] = useState<Record<string, any>>({});
  const [fhirPreview, setFhirPreview] = useState("/Patient");
  const [totalResults, setTotalResults] = useState<number>(0);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string>("");

  const patientFilterSchema = useMemo<FilterSchema | null>(() => {
    return (project.filter_schemas?.PATIENT_QUERY as FilterSchema | undefined) || null;
  }, [project]);

  useEffect(() => {
    const collection = createEmptyFilterCollection();
    collection.patientQueryFilters = existingQueryFilter || "{}";
    collection.patientDataFilters = existingPatientFilter || "{}";

    setInitialControlValues(getInitialValuesFromCollection(collection, project));
  }, [existingQueryFilter, existingPatientFilter, project]);

  const handleCompiledChange = useCallback(
    ({ conditions }: { conditions: Condition[]; fhirParams: string }) => {
      const nextConditions = (conditions || []).filter(
        (condition) => condition.filter_type === "PATIENT_QUERY"
      );
      setCompiledConditions(nextConditions);
      setFhirPreview(buildFhirQueryPreview(patientFilterSchema, nextConditions));
      setHasPreviewed(false);
      setPreviewPatients([]);
      setAllMatchedPatients([]);
      setTotalResults(0);
      setPreviewError("");
    },
    [patientFilterSchema]
  );

  useEffect(() => {
    setFhirPreview(buildFhirQueryPreview(patientFilterSchema, compiledConditions));
  }, [patientFilterSchema, compiledConditions]);

  const filteredPatients = useMemo(() => previewPatients, [previewPatients]);

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
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row: any) => row.id || row.ID || JSON.stringify(row),
    initialState: {
      pagination: {
        pageSize: 10
      }
    },
    enableRowSelection: true
  });

  const canProceed = hasPreviewed && allMatchedPatients.length > 0;

  const handleContinue = () => {
    if (!hasPreviewed) {
      return;
    }

    if (!lockFilterConfig) {
      const nextCollection = buildDefaultFilterCollectionFromConditions(compiledConditions, project);
      setFilterCollection("patientQueryFilters", nextCollection.patientQueryFilters);
      setFilterCollection("patientDataFilters", nextCollection.patientDataFilters);
    }

    onProceedToVariants(allMatchedPatients);
  };

  const handleCopyQuery = async () => {
    try {
      await navigator.clipboard.writeText(fhirPreview);
    } catch (error) {
      console.error("Failed to copy query:", error);
    }
  };

  const executeProjectFHIRQuery = useCallback(
    async (executeQuery: string): Promise<ProjectFHIRSourceQueryResponse> => {
      const response = await fetch(`${API_BASE}${API_PROJECTS_FHIR_SOURCE}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          username: userSession.username,
          project_id: project.id,
          datasource_group: selectedDatasourceGroupId,
          execute_query: executeQuery
        })
      });

      if (!response.ok) {
        throw new Error(`FHIR source query failed with status ${response.status}`);
      }

      return (await response.json()) as ProjectFHIRSourceQueryResponse;
    },
    [project.id, selectedDatasourceGroupId, userSession.username]
  );

  const handlePreviewQuery = useCallback(async () => {
    setIsPreviewLoading(true);
    setPreviewError("");
    setHasPreviewed(false);
    setPreviewPatients([]);
    setAllMatchedPatients([]);
    setTotalResults(0);

    try {
      if (!fhirSource) {
        throw new Error("No FHIR source is available for this user and project.");
      }

      if (fhirSource.toLowerCase().endsWith(".json")) {
        throw new Error("Preview query is only supported for FHIR server sources.");
      }

      const countExecuteQuery = buildExecuteQuery(fhirPreview, {
        _summary: "count",
        _total: "accurate"
      });

      const countPayload = await executeProjectFHIRQuery(countExecuteQuery);
      const countBundle = (countPayload.query_results || {}) as FhirBundle<FhirPatientResource>;
      const nextTotal = typeof countBundle.total === "number" ? countBundle.total : 0;
      setTotalResults(nextTotal);

      if (nextTotal === 0) {
        setHasPreviewed(true);
        table.setPageIndex(0);
        return;
      }

      let nextExecuteQuery: string | null = buildExecuteQuery(fhirPreview, {
        _count: String(FULL_FETCH_PAGE_SIZE),
        _total: "accurate"
      });

      const matchedPatients: Patient[] = [];

      while (nextExecuteQuery) {
        const payload = await executeProjectFHIRQuery(nextExecuteQuery);

        if (
          payload.query_status_code !== undefined &&
          payload.query_status_code >= 400
        ) {
          throw new Error(`Patient query failed with status ${payload.query_status_code}`);
        }

        const bundle = (payload.query_results || {}) as FhirBundle<FhirPatientResource>;
        const pagePatients =
          bundle.entry?.flatMap((entry) => {
            if (!entry.resource || entry.resource.resourceType !== "Patient") {
              return [];
            }
            return [mapFhirPatientToPatient(entry.resource, entry.fullUrl)];
          }) || [];

        matchedPatients.push(...pagePatients);

        const nextLink = getNextLink(bundle);
        nextExecuteQuery = nextLink
          ? getRelativeExecuteQueryFromUrl(nextLink, fhirSource)
          : null;

        if (nextLink && !nextExecuteQuery) {
          throw new Error("Unable to derive next page query from FHIR bundle link.");
        }
      }

      setAllMatchedPatients(matchedPatients);
      setPreviewPatients(matchedPatients.slice(0, PREVIEW_PAGE_SIZE));
      setHasPreviewed(true);
      table.setPageIndex(0);
    } catch (error: any) {
      console.error("Failed to preview FHIR query:", error);
      setPreviewPatients([]);
      setAllMatchedPatients([]);
      setTotalResults(0);
      setPreviewError(error?.message || "Failed to preview FHIR query.");
    } finally {
      setIsPreviewLoading(false);
    }
  }, [executeProjectFHIRQuery, fhirPreview, fhirSource, table]);

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
              initialValues={initialControlValues}
              lock={lockFilterConfig}
              onCompiledChange={handleCompiledChange}
            />
          </div>

          <div
            className="filter-screen-patients-block-01"
          >
            <button
              className="secondary-button filter-screen-patients-copy-query"
              type="button"
              onClick={handleCopyQuery}
              title="Copy query"
              
            >
              <Clipboard size={14} /> <span className="filter-screen-patients-block-02">Copy</span>
            </button>

            <button
              className="button duality-pos-absolute-top-0p5rem-right-0p5rem"
              type="button"
              onClick={handlePreviewQuery}
              disabled={isPreviewLoading}
              
            >
              {isPreviewLoading ? "Loading..." : "Preview Query"}
            </button>

            <div className="duality-weight-600-mb-0p5rem-pr-5rem">
              FHIR Query Preview
            </div>

            <div
              className="duality-font-monospace-fs-0p95rem-space-pre-wrap"
            >
              {fhirPreview}
            </div>
          </div>

          {hasPreviewed && (
            <>
              <div
                className="filter-screen-patients-block-03"
              >
                <h3>Patient Data Preview (Limited to 10)</h3>

                <h4
                  className="filter-screen-patients-h4"
                >
                  Total Results: {totalResults}
                </h4>
              </div>

              {previewError && (
                <div
                  className="duality-mb-0p75rem-mr-1rem-p-0p75rem"
                >
                  {previewError}
                </div>
              )}

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
                          {header.column.getIsSorted() === "desc" && <ChevronDown size={12} />}{" "}
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <td
                          key={cell.id}
                          className="duality-border-1px-solid-e0e0e0-p-0p5rem"
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {hasPreviewed && table.getRowModel().rows.length === 0 && (
                    <tr>
                      <td colSpan={columns.length} className="duality-p-0p75rem">
                        No patients match the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

              <div
                className="duality-d-flex-justify-center-align-center-7b984"
              >
                <button type="button" className="link-button-reset duality-underline"
                  onClick={(e) => {
                    e.preventDefault();
                    table.previousPage();
                  }}
                  style={{ color: table.getCanPreviousPage() ? "#007BFF" : "#A0A0A0", cursor: table.getCanPreviousPage() ? "pointer" : "not-allowed", pointerEvents: table.getCanPreviousPage() ? "auto" : "none" }}
                      >
                  Previous
                </button>

                {(() => {
                  const pageIndex = table.getState().pagination.pageIndex;
                  const pageCount = table.getPageCount();
                  const windowSize = 5;
                  let start = Math.max(0, pageIndex - Math.floor(windowSize / 2));
                  let end = start + windowSize;

                  if (end > pageCount) {
                    end = pageCount;
                    start = Math.max(0, end - windowSize);
                  }

                  return Array.from({ length: end - start }, (_, i) => {
                    const pageNum = start + i;
                    return (
                      <button type="button" className="link-button-reset duality-p-0p25rem-0p5rem-radius-4px-decoration-underline-97edf"
                        key={pageNum}
                        onClick={(e) => {
                          e.preventDefault();
                          table.setPageIndex(pageNum);
                        }}
                        style={{ color: pageNum === pageIndex ? "#fff" : "#007BFF", backgroundColor: pageNum === pageIndex ? "#007BFF" : "transparent" }}
                                  >
                        {pageNum + 1}
                      </button>
                    );
                  });
                })()}

                <button type="button" className="link-button-reset duality-decoration-underline-cursor-pointer"
                  onClick={(e) => {
                    e.preventDefault();
                    table.nextPage();
                  }}
                  style={{ color: table.getCanNextPage() ? "#007BFF" : "#A0A0A0", pointerEvents: table.getCanNextPage() ? "auto" : "none" }}
                      >
                  Next
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>
            Back to Filter History
          </button>
          <button
            className="wizard-next-button"
            disabled={!canProceed}
            onClick={() => {
              if (!canProceed) {
                return;
              }
              handleContinue();
            }}
          >
            Filter by Genetic Variant Assessments
          </button>
        </div>
      </div>
    </>
  );
};

export default FilterScreenPatients;
