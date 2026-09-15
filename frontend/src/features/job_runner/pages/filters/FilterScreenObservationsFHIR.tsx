import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from "@tanstack/react-table";
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { ChevronDown, ChevronUp } from "react-bootstrap-icons";
import { Patient } from "../../../../types/Patient";
import { Observation } from "../../../../types/Observation";
import FilterControlsSection from "../../components/FilterControlsSection";
import { Condition, FilterCollection } from "../../utils/FilterPayloadConfigUtils";
import { useFHIRSource, useUserSession } from "../../../../context/UserRoleContext";
import { API_BASE, API_PROJECTS_FHIR_SOURCE } from "../../../../constants/Constants";
import { Project } from "../../../../types/Project";

const LOINC = "http://loinc.org";
const V3_INTERP = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation";
const LNC_DNA_CHANGE_TYPE = "48019-4";
const LNC_GENOMIC_REF_ID = "48013-7";
const SUBJECT_BATCH_SIZE = 50;
const OBSERVATION_FETCH_COUNT = 2400;

interface QuerySchema {
  filter_type?: string;
  column_name?: string;
  filter_group?: string;
  field?: string;
  kind: "search-param" | "date-range" | "reverse-chain-token" | "code-list";
  param?: string;
  startPrefix?: string;
  endPrefix?: string;
  resource?: string;
  referenceParam?: string;
  valuePrefix?: string;
}

interface SaveTargetSchema {
  filter_group?: string;
  field?: string;
  operator?: string;
  valueFrom?: string;
  transform?: string;
}

interface SaveSchema {
  targets?: SaveTargetSchema[];
}

interface LocalPassControlRule {
  metric?: string;
  operator?: string;
  valueFrom?: string;
}

interface ObservationModelRule {
  extractor?: string;
  args?: Record<string, any>;
}

interface PatientMetricRule {
  aggregate?: string;
  where?: Record<string, any>;
  value?: string;
  metrics?: string[];
}

interface LocalPassSchema {
  observationModel?: Record<string, ObservationModelRule>;
  patientMetrics?: Record<string, PatientMetricRule>;
}

interface ControlSchema {
  id: string;
  field?: string;
  label: string;
  type: string;
  default?: any;
  query?: QuerySchema;
  save?: SaveSchema;
  localPass?: LocalPassControlRule;
}

interface FilterSchema {
  version: string;
  resource: { type?: string } | string;
  controls: ControlSchema[];
  defaultsResolver?: Record<string, any>;
  localPass?: LocalPassSchema;
}

interface FhirCoding {
  system?: string;
  code?: string;
  display?: string;
}

interface FhirCodeableConcept {
  coding?: FhirCoding[];
  text?: string;
}

interface FhirReference {
  reference?: string;
  display?: string;
}

interface FhirBundleEntry<T> {
  fullUrl?: string;
  resource?: T;
}

interface FhirBundleLink {
  relation?: string;
  url?: string;
}

interface FhirBundle<T> {
  resourceType?: string;
  total?: number;
  entry?: Array<FhirBundleEntry<T>>;
  link?: FhirBundleLink[];
}

interface FhirObservationResource {
  resourceType: "Observation";
  id?: string;
  status?: string;
  code?: FhirCodeableConcept;
  subject?: FhirReference;
  interpretation?: FhirCodeableConcept[];
  component?: Array<{
    code?: FhirCodeableConcept;
    valueCodeableConcept?: FhirCodeableConcept;
  }>;
  effectiveDateTime?: string;
  valueString?: string;
}

interface ProjectFHIRSourceQueryResponse {
  username?: string;
  user_id?: number;
  project_id?: number;
  source?: string;
  source_type?: "json" | "fhir_server";
  query_executed?: boolean;
  query_execution_message?: string;
  executed_url?: string;
  query_status_code?: number;
  query_results?: FhirBundle<FhirObservationResource>;
}

interface PatientVariantRow {
  patient: Patient;
  variants: { [key: string]: number };
  totalVariants: number;
  regions: string[];
  deletionRegions?: string[];
  amplificationRegions?: string[];
}

interface GeneticVariantTableProps {
  filterSystem?: string | null;
  patients?: Patient[];
  project: Project;
  rawObservations?: Observation[];
  data?: PatientVariantRow[];
  reviewSubmission: (selectedPatients: Patient[]) => void;
  onBack: () => void;
  backToButtonText?: string;
  setFilterCollection: <K extends keyof FilterCollection>(key: K, jsonString: string) => void;
  existingQueryFilter: string | null;
  existingDataFilter: string | null;
  lockFilterConfig: boolean;
  selectedDatasourceGroupId: number | null;
}

interface NormalizedObservation {
  [key: string]: any;
}

function hasCoding(coding: any[] | undefined, sys: string, code: string) {
  return Array.isArray(coding) && coding.some((c) => c?.system === sys && c?.code === code);
}

function getComponent(obs: Observation, sys: string, code: string) {
  return obs.components?.find((c: any) => hasCoding(c?.code?.coding, sys, code));
}

function isPOS(obs: Observation) {
  return !!obs.interpretation?.some((cc) => hasCoding(cc?.coding, V3_INTERP, "POS"));
}

function isPositiveVariant(obs: Observation) {
  if (isPOS(obs)) return true;
  const valueString = String((obs as any).valueString || "").toUpperCase();
  return valueString === "MUT" || valueString === "POS";
}

function extractRegion(obs: Observation): string | undefined {
  const directCode = obs.code?.coding?.[0]?.code || "";
  if (directCode.startsWith("Deletion_")) {
    return directCode.replace(/^Deletion_/, "");
  }
  if (directCode.startsWith("Amplification_")) {
    return directCode.replace(/^Amplification_/, "");
  }

  const comp: any = getComponent(obs, LOINC, LNC_GENOMIC_REF_ID);
  const v = comp?.valueCodeableConcept?.coding?.[0];
  return v?.code || v?.display;
}

function extractChangeType(obs: Observation): "deletion" | "duplication" | "amplification" | undefined {
  const directCode = obs.code?.coding?.[0]?.code || "";
  if (directCode.startsWith("Deletion_")) return "deletion";
  if (directCode.startsWith("Amplification_")) return "amplification";

  const comp: any = getComponent(obs, LOINC, LNC_DNA_CHANGE_TYPE);
  const v = comp?.valueCodeableConcept?.coding?.[0];
  const txt = `${v?.system || ""} ${v?.code || ""} ${v?.display || ""}`.toLowerCase();
  if (txt.includes("deletion") || txt.includes("so:0000159")) return "deletion";
  if (txt.includes("duplication") || txt.includes("so:1000035")) return "duplication";
  if (
    txt.includes("amplification") ||
    txt.includes("copy_number_gain") ||
    txt.includes("so:0001742") ||
    txt.includes("so:0001869")
  ) {
    return "amplification";
  }
  const id = (obs.id || "").toLowerCase();
  if (id.includes("-del-")) return "deletion";
  if (id.includes("-dup-")) return "duplication";
  if (id.includes("-amp-")) return "amplification";
  return undefined;
}

function getSchemaResourceType(schema: FilterSchema | null): string {
  if (!schema?.resource) {
    return "Observation";
  }

  if (typeof schema.resource === "string") {
    return schema.resource;
  }

  if (typeof schema.resource === "object" && typeof schema.resource.type === "string") {
    return schema.resource.type;
  }

  return "Observation";
}

function buildFhirQueryPreview(
  schema: FilterSchema | null,
  compiledFhirParams: string,
  subjectIds: string[],
  obfuscateSubjectIds = false
): string {
  const resource = getSchemaResourceType(schema);
  const params = new URLSearchParams(compiledFhirParams || "");

  if (subjectIds.length > 0) {
    params.set(
      "subject",
      obfuscateSubjectIds ? `[${subjectIds.length} subject ids hidden]` : subjectIds.join(",")
    );
  }

  const entries = Array.from(params.entries());
  if (entries.length === 0) {
    return `/${resource}`;
  }

  const lines = entries.map(([key, value], index) => {
    const renderedValue = key === "subject" && obfuscateSubjectIds
      ? value
      : encodeURIComponent(value);
    return `${index === 0 ? "" : "&"}${key}=${renderedValue}`;
  });

  return `/${resource}?${lines.join("")}`;
}

function buildRelativeExecuteQuery(
  schema: FilterSchema | null,
  compiledFhirParams: string,
  subjectIds: string[]
): string {
  const resource = getSchemaResourceType(schema);
  const params = new URLSearchParams(compiledFhirParams || "");

  if (subjectIds.length > 0) {
    params.set("subject", subjectIds.join(","));
  }

  const query = params.toString();
  if (!query) {
    return `/${resource}`;
  }

  return `/${resource}?${query}`;
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

function chunkArray<T>(items: T[], size: number): T[][] {
  if (size <= 0) {
    return [items];
  }

  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function toObservation(resource: FhirObservationResource, fullUrl?: string): Observation {
  const coding = resource.code?.coding?.[0];
  const subjectReference = resource.subject?.reference || "";

  return {
    id: resource.id || "",
    code: {
      coding: resource.code?.coding || [],
      text: resource.code?.text || coding?.display || coding?.code || ""
    },
    subjectReference,
    interpretation: resource.interpretation || [],
    components:
      resource.component?.map((component) => ({
        code: {
          coding: component.code?.coding || [],
          text:
            component.code?.text ||
            component.code?.coding?.[0]?.display ||
            component.code?.coding?.[0]?.code ||
            ""
        },
        valueCodeableConcept: component.valueCodeableConcept
          ? {
            coding: component.valueCodeableConcept.coding || [],
            text:
              component.valueCodeableConcept.text ||
              component.valueCodeableConcept.coding?.[0]?.display ||
              component.valueCodeableConcept.coding?.[0]?.code ||
              ""
          }
          : undefined
      })) || [],
    valueString: resource.valueString,
    fullUrl: fullUrl || (resource.id ? `Observation/${resource.id}` : "")
  } as Observation;
}

function extractVariantQueryFilterSettings(conditions: Condition[]) {
  let variantAssessmentCode = "69548-6";
  const deletionRegions = new Set<string>();
  const amplificationRegions = new Set<string>();

  for (const c of conditions) {
    if (c.filter_type !== "OBSERVATION_QUERY") continue;

    if (c.column_name === "variantAssessmentCode" && typeof c.value === "string" && c.value.trim() !== "") {
      variantAssessmentCode = c.value.trim();
    }

    if (c.column_name === "deletionRegions") {
      const vals = c.values || (c.value ? [c.value] : []);
      for (const v of vals || []) {
        if (v) deletionRegions.add(String(v));
      }
    }

    if (c.column_name === "amplificationRegions") {
      const vals = c.values || (c.value ? [c.value] : []);
      for (const v of vals || []) {
        if (v) amplificationRegions.add(String(v));
      }
    }
  }

  return { variantAssessmentCode, deletionRegions, amplificationRegions };
}

function getSaveTargets(control: ControlSchema): SaveTargetSchema[] {
  return Array.isArray(control.save?.targets) ? control.save!.targets! : [];
}

function findControlForCondition(controls: ControlSchema[], condition: Condition): ControlSchema | undefined {
  return controls.find((control) =>
    getSaveTargets(control).some((target) => {
      return (
        String(target.filter_group || "").trim() === String(condition.filter_type || "").trim() &&
        String(target.field || "").trim() === String(condition.column_name || "").trim() &&
        String(target.operator || "").trim().toUpperCase() === String(condition.operator || "").trim().toUpperCase()
      );
    })
  );
}

function getComponentValueStrings(component: any): string[] {
  const out: string[] = [];
  const valueCodeableConcept = component?.valueCodeableConcept;

  if (valueCodeableConcept) {
    const text = String(valueCodeableConcept.text || "").trim();
    if (text) out.push(text);

    for (const coding of valueCodeableConcept.coding || []) {
      const code = String(coding?.code || "").trim();
      const display = String(coding?.display || "").trim();
      const system = String(coding?.system || "").trim();
      if (code) out.push(code);
      if (display) out.push(display);
      if (system) out.push(system);
    }
  }

  const valueString = String(component?.valueString || "").trim();
  if (valueString) {
    out.push(valueString);
  }

  return out;
}

function getObservationCodeStrings(obs: Observation): string[] {
  const out: string[] = [];
  const text = String((obs.code as any)?.text || "").trim();
  if (text) out.push(text);

  for (const coding of obs.code?.coding || []) {
    const code = String(coding?.code || "").trim();
    const display = String(coding?.display || "").trim();
    const system = String(coding?.system || "").trim();
    if (code) out.push(code);
    if (display) out.push(display);
    if (system) out.push(system);
  }

  const id = String(obs.id || "").trim();
  if (id) out.push(id);

  return out;
}

function runObservationExtractor(
  obs: Observation,
  extractor: string,
  args: Record<string, any>
): any {
  if (extractor === "interpretation_positive") {
    return isPositiveVariant(obs);
  }

  if (extractor === "component_or_text_code") {
    const componentCodeSystem = String(args.componentCodeSystem || "").trim();
    const componentCode = String(args.componentCode || "").trim();
    const valueMap = args.valueMap || {};
    const idFallback = args.idFallback || {};

    const strings: string[] = [];
    const component = getComponent(obs, componentCodeSystem, componentCode);
    if (component) {
      strings.push(...getComponentValueStrings(component));
    }
    strings.push(...getObservationCodeStrings(obs));

    const lowered = strings.map((value) => value.toLowerCase());
    for (const [normalizedValue, tokens] of Object.entries(valueMap)) {
      const tokenList = Array.isArray(tokens)
        ? tokens.map((token) => String(token).trim().toLowerCase()).filter(Boolean)
        : [];
      if (tokenList.length > 0 && lowered.some((candidate) => tokenList.some((token) => candidate.includes(token)))) {
        return normalizedValue;
      }
    }

    const idLower = String(obs.id || "").toLowerCase();
    for (const [normalizedValue, tokens] of Object.entries(idFallback)) {
      const tokenList = Array.isArray(tokens)
        ? tokens.map((token) => String(token).trim().toLowerCase()).filter(Boolean)
        : [];
      if (tokenList.length > 0 && tokenList.some((token) => idLower.includes(token))) {
        return normalizedValue;
      }
    }

    return undefined;
  }

  if (extractor === "component_or_id_region") {
    const componentCodeSystem = String(args.componentCodeSystem || "").trim();
    const componentCode = String(args.componentCode || "").trim();
    const idRegex = String(args.idRegex || "").trim();

    const directComponent = getComponent(obs, componentCodeSystem, componentCode);
    if (directComponent) {
      const directStrings = getComponentValueStrings(directComponent);
      if (directStrings.length > 0) {
        return directStrings[0];
      }
    }

    if (idRegex) {
      const match = String(obs.id || "").match(new RegExp(idRegex, "i"));
      if (match) {
        return match[1];
      }
    }

    for (const component of obs.components || []) {
      const strings = getComponentValueStrings(component);
      if (strings.length > 0) {
        return strings[0];
      }
    }

    return undefined;
  }

  return undefined;
}

function normalizeObservation(
  obs: Observation,
  schema: FilterSchema | null
): NormalizedObservation {
  const observationModel = schema?.localPass?.observationModel || {};
  const normalized: NormalizedObservation = {};

  for (const [fieldName, rule] of Object.entries(observationModel)) {
    normalized[fieldName] = runObservationExtractor(
      obs,
      String(rule?.extractor || "").trim(),
      rule?.args || {}
    );
  }

  return normalized;
}

function matchesWhere(normalized: NormalizedObservation, where: Record<string, any>): boolean {
  for (const [key, expected] of Object.entries(where || {})) {
    if (normalized[key] !== expected) {
      return false;
    }
  }
  return true;
}

function buildPatientMetrics(
  observations: Observation[],
  schema: FilterSchema | null
): Record<string, any> {
  const normalizedObservations = observations.map((obs) => normalizeObservation(obs, schema));
  const metricRules = schema?.localPass?.patientMetrics || {};
  const metrics: Record<string, any> = {};
  const unresolved = new Map<string, PatientMetricRule>(Object.entries(metricRules));

  while (unresolved.size > 0) {
    let progressed = false;

    for (const [metricName, rule] of Array.from(unresolved.entries())) {
      const aggregate = String(rule?.aggregate || "").trim();

      if (aggregate === "count") {
        metrics[metricName] = normalizedObservations.filter((obs) => matchesWhere(obs, rule.where || {})).length;
        unresolved.delete(metricName);
        progressed = true;
        continue;
      }

      if (aggregate === "set") {
        const valueField = String(rule?.value || "").trim();
        const values = new Set<string>();
        for (const obs of normalizedObservations) {
          if (!matchesWhere(obs, rule.where || {})) {
            continue;
          }
          const value = obs[valueField];
          if (value !== undefined && value !== null && String(value).trim() !== "") {
            values.add(String(value).trim());
          }
        }
        metrics[metricName] = values;
        unresolved.delete(metricName);
        progressed = true;
        continue;
      }

      if (aggregate === "sumMetrics") {
        const deps = Array.isArray(rule?.metrics) ? rule.metrics : [];
        if (deps.every((dep) => Object.prototype.hasOwnProperty.call(metrics, dep))) {
          metrics[metricName] = deps.reduce((sum, dep) => sum + Number(metrics[dep] || 0), 0);
          unresolved.delete(metricName);
          progressed = true;
        }
        continue;
      }

      if (aggregate === "unionMetrics") {
        const deps = Array.isArray(rule?.metrics) ? rule.metrics : [];
        if (deps.every((dep) => Object.prototype.hasOwnProperty.call(metrics, dep))) {
          const merged = new Set<string>();
          deps.forEach((dep) => {
            const value = metrics[dep];
            if (value instanceof Set) {
              value.forEach((item) => {
                merged.add(String(item));
              });
            } else if (Array.isArray(value)) {
              value.forEach((item) => {
                merged.add(String(item));
              });
            }
          });
          metrics[metricName] = merged;
          unresolved.delete(metricName);
          progressed = true;
        }
        continue;
      }

      metrics[metricName] = undefined;
      unresolved.delete(metricName);
      progressed = true;
    }

    if (!progressed) {
      break;
    }
  }

  return metrics;
}

function getConditionExpectedValue(condition: Condition, valueFrom: string): any {
  if (valueFrom === "values") {
    if (Array.isArray(condition.values)) {
      return condition.values.map((value) => String(value).trim()).filter(Boolean);
    }
    if (typeof condition.value === "string" && condition.value.trim() !== "") {
      return condition.value.split(",").map((value) => value.trim()).filter(Boolean);
    }
    return [];
  }

  if (condition.value !== undefined && condition.value !== null && String(condition.value).trim() !== "") {
    return condition.value;
  }

  if (Array.isArray(condition.values)) {
    if (condition.values.length === 1) {
      return condition.values[0];
    }
    return condition.values;
  }

  return undefined;
}

function toStringSet(value: any): Set<string> {
  if (value instanceof Set) {
    return new Set(Array.from(value).map((item) => String(item).trim()).filter(Boolean));
  }
  if (Array.isArray(value)) {
    return new Set(value.map((item) => String(item).trim()).filter(Boolean));
  }
  if (typeof value === "string") {
    return new Set(value.split(",").map((item) => item.trim()).filter(Boolean));
  }
  if (value !== undefined && value !== null && String(value).trim() !== "") {
    return new Set([String(value).trim()]);
  }
  return new Set();
}

function compareMetric(actual: any, operator: string, expected: any): boolean {
  if (operator === ">=") {
    return Number(actual || 0) >= Number(expected || 0);
  }

  if (operator === "<=") {
    return Number(actual || 0) <= Number(expected || 0);
  }

  if (operator === ">") {
    return Number(actual || 0) > Number(expected || 0);
  }

  if (operator === "<") {
    return Number(actual || 0) < Number(expected || 0);
  }

  if (operator === "=") {
    return actual === expected;
  }

  if (operator === "IN") {
    const actualSet = toStringSet(actual);
    const expectedSet = toStringSet(expected);

    if (expectedSet.size === 0) {
      return true;
    }

    let allMatched = true;
    expectedSet.forEach((value) => {
      if (!actualSet.has(value)) {
        allMatched = false;
      }
    });

    return allMatched;
  }

  if (operator === "overlaps") {
    const actualSet = toStringSet(actual);
    const expectedSet = toStringSet(expected);

    let matched = false;
    expectedSet.forEach((value) => {
      if (actualSet.has(value)) {
        matched = true;
      }
    });

    return matched;
  }

  return false;
}

function patientSatisfiesObservationDataFilters(
  observations: Observation[],
  conditions: Condition[],
  schema: FilterSchema | null
): boolean {
  if (!schema) {
    return true;
  }

  const activeConditions = conditions.filter(
    (condition) => condition.filter_type === "OBSERVATION_DATA" || condition.filter_type === "OBSERVATION"
  );

  if (activeConditions.length === 0) {
    return true;
  }

  const metrics = buildPatientMetrics(observations, schema);

  for (const condition of activeConditions) {
    const control = findControlForCondition(schema.controls || [], condition);
    if (!control?.localPass) {
      continue;
    }

    const metricName = String(control.localPass.metric || "").trim();
    const operator = String(control.localPass.operator || "").trim();
    const valueFrom = String(control.localPass.valueFrom || "value").trim();

    if (!metricName || !operator) {
      continue;
    }

    const actual = metrics[metricName];
    const expected = getConditionExpectedValue(condition, valueFrom);

    if (!compareMetric(actual, operator, expected)) {
      return false;
    }
  }

  return true;
}

const FilterScreenObservations: React.FC<GeneticVariantTableProps> = ({
  filterSystem,
  patients,
  project,
  rawObservations: _rawObservations,
  data: _data,
  reviewSubmission,
  onBack,
  backToButtonText = "Back to Patient Filters",
  setFilterCollection,
  existingQueryFilter,
  existingDataFilter,
  lockFilterConfig,
  selectedDatasourceGroupId
}) => {
  const userSession = useUserSession();
  const fhirSource = useFHIRSource();
  const isLocalJsonSource = String(fhirSource || "").trim().toLowerCase().endsWith(".json");

  const [queryConditions] = useState<Condition[]>([]);
  const [queryFhirParams] = useState("");
  const [dataConditions, setDataConditions] = useState<Condition[]>([]);
  const [, setInitialQueryValues] = useState<Record<string, any>>({});
  const [initialDataValues, setInitialDataValues] = useState<Record<string, any>>({});
  const [querySchema, setQuerySchema] = useState<FilterSchema | null>(null);
  const [dataSchema, setDataSchema] = useState<FilterSchema | null>(null);
  const [previewError, setPreviewError] = useState<string>("");
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [queryResultCount, setQueryResultCount] = useState(0);
  const [queriedObservations, setQueriedObservations] = useState<Observation[]>([]);
  const [previewProgressPercent, setPreviewProgressPercent] = useState(0);
  const [previewProgressLabel, setPreviewProgressLabel] = useState("");
  const [previewCompletedText, setPreviewCompletedText] = useState("");

  const subjectIds = useMemo(() => {
    return (patients || []).map((p) => p.id).filter((id) => !!id);
  }, [patients]);

  const fs = (filterSystem || "default").toLowerCase();
  const querySchemaUrl = `/filters/${fs}/observation/observation_query.json`;
  const dataSchemaUrl = `/filters/${fs}/observation/observation_data.json`;

  useEffect(() => {
    let isMounted = true;

    fetch(querySchemaUrl)
      .then((res) => res.json())
      .then((schema: FilterSchema) => {
        if (!isMounted) {
          return;
        }
        setQuerySchema(schema);
      })
      .catch(() => {
        if (!isMounted) {
          return;
        }
        setQuerySchema(null);
      });

    fetch(dataSchemaUrl)
      .then((res) => res.json())
      .then((schema: FilterSchema) => {
        if (!isMounted) {
          return;
        }
        setDataSchema(schema);
      })
      .catch(() => {
        if (!isMounted) {
          return;
        }
        setDataSchema(null);
      });

    return () => {
      isMounted = false;
    };
  }, [querySchemaUrl, dataSchemaUrl]);

  useEffect(() => {
    if (existingQueryFilter === null || existingQueryFilter === "{}") {
      setInitialQueryValues({
        variantAssessmentCode: ""
      });
      return;
    }

    try {
      const parsed = JSON.parse(existingQueryFilter) as {
        variantAssessmentCode?: string;
        deletionRegions?: string[];
        amplificationRegions?: string[];
      };

      const queryValues: Record<string, any> = {};

      if (typeof parsed.variantAssessmentCode === "string" && parsed.variantAssessmentCode.trim() !== "") {
        queryValues["variantAssessmentCode"] = parsed.variantAssessmentCode;
      }

      if (Array.isArray(parsed.deletionRegions)) {
        queryValues["deletionRegions"] = parsed.deletionRegions;
      }

      if (Array.isArray(parsed.amplificationRegions)) {
        queryValues["amplificationRegions"] = parsed.amplificationRegions;
      }

      setInitialQueryValues(queryValues);
    } catch {
      setInitialQueryValues({
        variantAssessmentCode: ""
      });
    }
  }, [existingQueryFilter]);

  useEffect(() => {
    if (existingDataFilter === null) {
      setInitialDataValues({});
      return;
    }

    try {
      const parsed = JSON.parse(existingDataFilter) as Record<string, any>;
      const dataValues: Record<string, any> = { ...parsed };

      if (!Object.prototype.hasOwnProperty.call(parsed, "variantAssessmentCode")) {
        dataValues.variantAssessmentCode = "";
      }

      setInitialDataValues(dataValues);
    } catch {
      setInitialDataValues({});
    }
  }, [existingDataFilter]);

  const handleDataCompiledChange = useCallback(({ conditions }: { conditions: Condition[]; fhirParams: string }) => {
    setDataConditions(conditions || []);
  }, []);

  const fhirPreview = useMemo(() => {
    return buildFhirQueryPreview(querySchema, queryFhirParams, subjectIds, true);
  }, [querySchema, queryFhirParams, subjectIds]);

  const queryFilterSettings = useMemo(
    () => extractVariantQueryFilterSettings(queryConditions),
    [queryConditions]
  );

  const observationSource = useMemo(() => {
    if (!hasPreviewed) {
      return [];
    }
    return queriedObservations;
  }, [hasPreviewed, queriedObservations]);

  const observationsByPatientId = useMemo(() => {
    const byRef = new Map<string, string>();

    (patients || []).forEach((patient) => {
      if (patient.fullUrl) {
        byRef.set(patient.fullUrl, patient.id);
      }
      byRef.set(`Patient/${patient.id}`, patient.id);
      byRef.set(patient.id, patient.id);
    });

    const grouped = new Map<string, Observation[]>();

    for (const observation of observationSource) {
      const patientId =
        byRef.get(observation.subjectReference) ||
        byRef.get((observation.subjectReference || "").replace(/^Patient\//, ""));

      if (!patientId) {
        continue;
      }

      const existing = grouped.get(patientId) || [];
      existing.push(observation);
      grouped.set(patientId, existing);
    }

    return grouped;
  }, [observationSource, patients]);

  const baseRows: PatientVariantRow[] = useMemo(() => {
    if (!hasPreviewed || !patients) {
      return [];
    }

    const byRef = new Map<string, Patient>();
    patients.forEach((p) => {
      if (p.fullUrl) byRef.set(p.fullUrl, p);
      byRef.set(`Patient/${p.id}`, p);
      byRef.set(p.id, p);
    });

    const per: Record<string, { del: Set<string>; amp: Set<string>; dup: Set<string>; counts: Record<string, number> }> = {};

    for (const obs of observationSource) {
      const pt =
        byRef.get(obs.subjectReference) ||
        byRef.get((obs.subjectReference || "").replace(/^Patient\//, ""));

      if (!pt) continue;

      const kind = extractChangeType(obs);
      const region = extractRegion(obs);
      if (!kind || !region) continue;
      if (!isPositiveVariant(obs)) continue;

      const pid = pt.id;
      const slot = per[pid] || (per[pid] = { del: new Set(), amp: new Set(), dup: new Set(), counts: {} });

      if (kind === "deletion") slot.del.add(region);
      if (kind === "amplification") slot.amp.add(region);
      if (kind === "duplication") slot.dup.add(region);
      slot.counts[kind] = (slot.counts[kind] || 0) + 1;
    }

    const matchedPatientIds = Array.from(observationsByPatientId.keys());

    return matchedPatientIds
      .map((patientId) => byRef.get(patientId))
      .filter((patient): patient is Patient => Boolean(patient))
      .map((patient) => {
        const slot = per[patient.id] || { del: new Set<string>(), amp: new Set<string>(), dup: new Set<string>(), counts: {} as Record<string, number> };
        const deletion = slot.counts["deletion"] || 0;
        const amplification = slot.counts["amplification"] || 0;
        const duplication = slot.counts["duplication"] || 0;
        const total = deletion + amplification;
        const delArr = Array.from(slot.del);
        const ampArr = Array.from(slot.amp);

        return {
          patient,
          variants: { deletion, amplification, duplication },
          totalVariants: total,
          regions: Array.from(new Set(delArr.concat(ampArr))),
          deletionRegions: delArr,
          amplificationRegions: ampArr
        };
      });
  }, [hasPreviewed, observationSource, observationsByPatientId, patients]);

  const filteredData = useMemo(() => {
    return baseRows.filter((row) => {
      const patientObservations = observationsByPatientId.get(row.patient.id) || [];
      return patientSatisfiesObservationDataFilters(patientObservations, dataConditions, dataSchema);
    });
  }, [baseRows, observationsByPatientId, dataConditions, dataSchema]);

  const columns = useMemo<ColumnDef<PatientVariantRow>[]>(
    () => [
      { header: "Mutation Deletions", accessorFn: (row) => row.variants["deletion"] || 0 },
      { header: "Mutation Amplifications", accessorFn: (row) => row.variants["amplification"] || 0 },
      { id: "totalVariants", header: "Total Mutation Variants (Del + Amp)", accessorKey: "totalVariants" },
      { header: "Regions (Positive Mutation)", accessorFn: (row) => row.regions.join(", ") }
    ],
    []
  );

  const table = useReactTable({
    data: filteredData,
    columns,
    initialState: {
      sorting: [{ id: "totalVariants", desc: true }]
    },
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel()
  });

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
    if (subjectIds.length === 0) {
      setPreviewError("No subject IDs were supplied from the patient filter stage.");
      setHasPreviewed(false);
      setQueryResultCount(0);
      setQueriedObservations([]);
      setPreviewProgressPercent(0);
      setPreviewProgressLabel("");
      setPreviewCompletedText("");
      return;
    }

    setIsPreviewLoading(true);
    setPreviewError("");
    setHasPreviewed(false);
    setQueryResultCount(0);
    setQueriedObservations([]);
    setPreviewProgressPercent(0);
    setPreviewProgressLabel("");
    setPreviewCompletedText("");
    const previewStartTime = performance.now();

    try {
      if (!fhirSource) {
        throw new Error("No FHIR source is available for this user and project.");
      }

      if (isLocalJsonSource) {
        const selectedIds = new Set(subjectIds);
        const selectedReferences = new Set(
          (patients || []).flatMap((patient) => [patient.id, `Patient/${patient.id}`, patient.fullUrl].filter(Boolean))
        );
        const nextObservations = (_rawObservations || []).filter((observation) => {
          const reference = String(observation.subjectReference || "");
          const patientId = reference.includes("Patient/")
            ? reference.slice(reference.lastIndexOf("Patient/") + "Patient/".length)
            : reference;
          return selectedReferences.has(reference) || selectedIds.has(patientId);
        });
        setQueriedObservations(nextObservations);
        setQueryResultCount(nextObservations.length);
        setHasPreviewed(true);
        setPreviewProgressPercent(100);
        setPreviewProgressLabel("Local bundle data ready");
        const elapsedSeconds = ((performance.now() - previewStartTime) / 1000).toFixed(2);
        setPreviewCompletedText(`Local filter data prepared in ${elapsedSeconds}s`);
        table.setPageIndex(0);
        return;
      }

      const subjectBatches = chunkArray(subjectIds, SUBJECT_BATCH_SIZE);
      const observationsByKey = new Map<string, Observation>();
      let completedBatches = 0;

      setPreviewProgressLabel(`Loading ${subjectBatches.length} observation batches`);

      const runSingleBatch = async (batchSubjectIds: string[], batchIndex: number) => {
        const batchRelativePath = buildRelativeExecuteQuery(querySchema, queryFhirParams, batchSubjectIds);

        let nextExecuteQuery: string | null = buildExecuteQuery(batchRelativePath, {
          _count: String(OBSERVATION_FETCH_COUNT),
          _total: "accurate"
        });

        let pageIndex = 0;

        while (nextExecuteQuery) {
          setPreviewProgressLabel(
            `Loading batch ${batchIndex + 1} of ${subjectBatches.length}, page ${pageIndex + 1} (${completedBatches}/${subjectBatches.length} batches complete)`
          );

          const payload = await executeProjectFHIRQuery(nextExecuteQuery);

          if (
            payload.query_status_code !== undefined &&
            payload.query_status_code >= 400
          ) {
            throw new Error(`Preview query failed with status ${payload.query_status_code}`);
          }

          const previewBundle = (payload.query_results || {}) as FhirBundle<FhirObservationResource>;
          const batchObservations =
            previewBundle.entry?.flatMap((entry) => {
              if (!entry.resource || entry.resource.resourceType !== "Observation") {
                return [];
              }
              return [toObservation(entry.resource, entry.fullUrl)];
            }) || [];

          batchObservations.forEach((observation) => {
            const key = observation.id;
            if (key) {
              observationsByKey.set(key, observation);
            }
          });

          const nextLink = previewBundle.link?.find((link) => link?.relation === "next")?.url || null;
          nextExecuteQuery = nextLink
            ? getRelativeExecuteQueryFromUrl(nextLink, fhirSource)
            : null;

          if (nextLink && !nextExecuteQuery) {
            throw new Error("Unable to derive next page query from FHIR bundle link.");
          }

          pageIndex += 1;
        }

        completedBatches += 1;
        setPreviewProgressPercent(Math.round((completedBatches / subjectBatches.length) * 100));
        setPreviewProgressLabel(`Completed ${completedBatches} of ${subjectBatches.length} batches`);
      };

      for (let batchIndex = 0; batchIndex < subjectBatches.length; batchIndex += 1) {
        await runSingleBatch(subjectBatches[batchIndex], batchIndex);
      }

      const nextObservations = Array.from(observationsByKey.values());
      setQueriedObservations(nextObservations);
      setQueryResultCount(nextObservations.length);
      setHasPreviewed(true);
      setPreviewProgressPercent(100);
      setPreviewProgressLabel("FHIR data fetch complete");
      const elapsedMs = performance.now() - previewStartTime;
      const elapsedSeconds = (elapsedMs / 1000).toFixed(2);
      setPreviewCompletedText(`Fetch completed in ${elapsedSeconds}s`);
      table.setPageIndex(0);
    } catch (error: any) {
      setPreviewError(error?.message || "Failed to preview FHIR query.");
      setHasPreviewed(false);
      setQueryResultCount(0);
      setQueriedObservations([]);
      setPreviewProgressPercent(0);
      setPreviewProgressLabel("");
      setPreviewCompletedText("");
    } finally {
      setIsPreviewLoading(false);
    }
  }, [_rawObservations, executeProjectFHIRQuery, fhirSource, isLocalJsonSource, patients, queryFhirParams, querySchema, subjectIds, table]);

  const handleSubmit = () => {
    if (!filteredData.length) return;

    const observationQueryPayload: Record<string, any> = {
      // variantAssessmentCode: queryFilterSettings.variantAssessmentCode,
      deletionRegions: Array.from(queryFilterSettings.deletionRegions),
      amplificationRegions: Array.from(queryFilterSettings.amplificationRegions)
    };

    const observationDataPayload: Record<string, any> = {};
    for (const condition of dataConditions) {
      if (condition.filter_type !== "OBSERVATION_DATA") {
        continue;
      }

      if (Array.isArray(condition.values)) {
        observationDataPayload[condition.column_name] = condition.values;
      } else if (condition.value !== undefined) {
        const raw = String(condition.value).trim();
        if (raw !== "" && !Number.isNaN(Number(raw)) && raw === String(Number(raw))) {
          observationDataPayload[condition.column_name] = Number(raw);
        } else {
          observationDataPayload[condition.column_name] = condition.value;
        }
      }
    }

    if (!lockFilterConfig) {
      setFilterCollection("observationQueryFilters", JSON.stringify(observationQueryPayload));
      setFilterCollection("observationDataFilters", JSON.stringify(observationDataPayload));
    }

    reviewSubmission(filteredData.map((row) => row.patient));
  };

  const canSubmit = hasPreviewed && filteredData.length > 0;

  return (
    <>
      <div className="page-container">
        <div className="child-container-top">
          <div className="filter-screen-observations-fhir-shared-01">
            <h3>{isLocalJsonSource ? "Observation Data" : "Observation Data Fetch"}</h3>
            <h4 className="duality-text-black">
              {subjectIds.length > 0 ? `Qualified Subject IDs: ${subjectIds.length}` : "No patient subjects supplied"}
            </h4>
          </div>

          <div
            className="filter-screen-observations-fhir-block-01"
          >
            <button
              className="button duality-pos-absolute-top-0p5rem-right-0p5rem"
              type="button"
              onClick={handlePreviewQuery}
              disabled={isPreviewLoading || subjectIds.length === 0}
              
            >
              {isPreviewLoading ? "Loading..." : isLocalJsonSource ? "Fetch Data" : "Fetch Data"}
            </button>

            <div className="duality-weight-600-mb-0p5rem-pr-5rem">
              {isLocalJsonSource ? "Local Bundle Filter" : "FHIR Query"}
            </div>

            <div
              className="duality-font-monospace-fs-0p95rem-space-pre-wrap"
            >
              {fhirPreview}
            </div>

            {(isPreviewLoading || hasPreviewed) && (
              <div className="duality-mt-1">
                <div className="filter-screen-observations-fhir-block-02">
                  {previewProgressLabel || "Preparing preview..."}
                </div>
                <div
                  className="filter-screen-observations-fhir-block-03"
                >
                  <div
                    className="filter-screen-observations-fhir-block-04" style={{ width: `${previewProgressPercent}%` }}
                  />
                </div>
                <div className="filter-screen-observations-fhir-block-05">
                  {previewProgressPercent}%
                </div>
              </div>
            )}
          </div>

          <div className="filter-screen-observations-fhir-shared-01">
            <h3>Observation Filters (Local Pass)</h3>
            <div className="duality-text-right">
              <h4 className="duality-text-black-m-0">
                {hasPreviewed
                  ? `${isLocalJsonSource ? "Bundle contains" : "Query returned"} ${queryResultCount} observations`
                  : isLocalJsonSource ? "Apply filters to the local bundle" : "Run preview to load observations"}
              </h4>
              {previewCompletedText && (
                <div className="filter-screen-observations-fhir-block-06">
                  {previewCompletedText}
                </div>
              )}
            </div>
          </div>

          <div className="filter-screen-observations-fhir-block-07">
            <FilterControlsSection
              schemaUrl={dataSchemaUrl}
              filterType="OBSERVATION_DATA"
              initialConditions={[]}
              lock={lockFilterConfig}
              onCompiledChange={handleDataCompiledChange}
              initialValues={initialDataValues}
            />
          </div>

          {previewError && (
            <div
              className="duality-mb-0p75rem-mr-1rem-p-0p75rem"
            >
              {previewError}
            </div>
          )}

          <div style={{ display: hasPreviewed ? "block" : "none" }}>
            <div className="filter-screen-observations-fhir-shared-01">
              <h3>Observation Results</h3>
              <h4 className="duality-text-black">
                {`Filtered to ${filteredData.length} patient rows`}
              </h4>
            </div>

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
                      No patient rows match the current observation filters.
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
          </div>
        </div>
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>
            {backToButtonText}
          </button>
          <button
            className="wizard-next-button"
            disabled={!canSubmit}
            onClick={() => {
              if (!canSubmit) {
                return;
              }
              handleSubmit();
            }}
          >
            Set Function Configuration
          </button>
        </div>
      </div>
    </>
  );
};

export default FilterScreenObservations;
