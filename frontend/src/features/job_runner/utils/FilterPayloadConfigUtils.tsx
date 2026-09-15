import { Project } from "../../../types/Project";
import {
  Condition,
  ControlSchema,
  FilterCollection,
  FilterSchema,
  FilterType,
  QuerySchema,
  SaveSchema,
  SaveTargetSchema
} from "../../../types/FilterSchema";

export type {
  Condition,
  ControlSchema,
  FilterCollection,
  FilterSchema,
  FilterType,
  QuerySchema,
  SaveSchema,
  SaveTargetSchema
};

type StoredBucket = Record<string, any>;
type StoredCollectionMap = Partial<Record<keyof FilterCollection, StoredBucket>>;
type ConditionValuePayload = Partial<Pick<Condition, "value" | "values">>;

const FILTER_TYPES: FilterType[] = [
  "PATIENT_QUERY",
  "PATIENT_DATA",
  "OBSERVATION",
  "OBSERVATION_QUERY",
  "OBSERVATION_DATA"
];

function parseJson<T>(s: string | undefined | null, fallback: T): T {
  if (!s || s.trim() === "") {
    return fallback;
  }
  try {
    return JSON.parse(s) as T;
  } catch {
    return fallback;
  }
}

function stringifyMeaningful(obj: Record<string, any>): string {
  return Object.keys(obj).length > 0 ? JSON.stringify(obj) : "{}";
}

function normalizeFilterType(value: string | undefined | null): FilterType | null {
  const normalized = String(value || "").trim().toUpperCase();
  return FILTER_TYPES.includes(normalized as FilterType) ? (normalized as FilterType) : null;
}

function inferCollectionKey(filterGroup: FilterType): keyof FilterCollection {
  switch (filterGroup) {
    case "PATIENT_QUERY":
      return "patientQueryFilters";
    case "PATIENT_DATA":
      return "patientDataFilters";
    case "OBSERVATION":
    case "OBSERVATION_QUERY":
      return "observationQueryFilters";
    case "OBSERVATION_DATA":
      return "observationDataFilters";
    default:
      return "observationQueryFilters";
  }
}

function getSchemasFromProject(project: Project): Partial<Record<FilterType, FilterSchema>> {
  return project.filter_schemas || {};
}

export function createEmptyFilterCollection(): FilterCollection {
  return {
    patientQueryFilters: "{}",
    patientDataFilters: "{}",
    observationQueryFilters: "{}",
    observationDataFilters: "{}"
  };
}

function getStoredCollectionMap(collection: FilterCollection): StoredCollectionMap {
  return {
    patientQueryFilters: parseJson<Record<string, any>>(collection.patientQueryFilters, {}),
    patientDataFilters: parseJson<Record<string, any>>(collection.patientDataFilters, {}),
    observationQueryFilters: parseJson<Record<string, any>>(collection.observationQueryFilters, {}),
    observationDataFilters: parseJson<Record<string, any>>(collection.observationDataFilters, {})
  };
}

function buildCollectionFromBuckets(buckets: StoredCollectionMap): FilterCollection {
  return {
    patientQueryFilters: stringifyMeaningful(buckets.patientQueryFilters || {}),
    patientDataFilters: stringifyMeaningful(buckets.patientDataFilters || {}),
    observationQueryFilters: stringifyMeaningful(buckets.observationQueryFilters || {}),
    observationDataFilters: stringifyMeaningful(buckets.observationDataFilters || {})
  };
}

function getControlField(control: ControlSchema): string {
  return String(control.field || control.id || "").trim();
}

function getSaveTargets(control: ControlSchema): SaveTargetSchema[] {
  const targets = control.save?.targets;
  return Array.isArray(targets) ? targets : [];
}

function getTargetField(target: SaveTargetSchema): string {
  return String(target.field || target.column_name || "").trim();
}

function getTargetFilterGroup(target: SaveTargetSchema): FilterType | null {
  return normalizeFilterType(target.filter_group || target.filter_type);
}

function getControlStoredValue(
  control: ControlSchema,
  collectionMap: StoredCollectionMap
): any {
  const targets = getSaveTargets(control);
  const controlField = String(control.field || "").trim();
  const controlId = String(control.id || "").trim();

  for (const target of targets) {
    const filterGroup = getTargetFilterGroup(target);
    const targetField = getTargetField(target);
    if (!filterGroup) {
      continue;
    }

    const bucketKey = inferCollectionKey(filterGroup);
    const bucket = collectionMap[bucketKey] || {};
    const candidates = [targetField, controlField, controlId].filter(Boolean);

    for (const candidate of candidates) {
      if (Object.prototype.hasOwnProperty.call(bucket, candidate)) {
        return bucket[candidate];
      }
    }
  }

  const field = getControlField(control);
  if (!field) {
    return undefined;
  }

  for (const target of targets) {
    const filterGroup = getTargetFilterGroup(target);
    if (!filterGroup) {
      continue;
    }

    const bucketKey = inferCollectionKey(filterGroup);
    const bucket = collectionMap[bucketKey] || {};
    if (Object.prototype.hasOwnProperty.call(bucket, field)) {
      return bucket[field];
    }
  }

  return undefined;
}

function isBlankValue(value: any): boolean {
  if (value === undefined || value === null) {
    return true;
  }

  if (typeof value === "string") {
    return value.trim() === "";
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return true;
    }
    return value.every((item: any) => String(item ?? "").trim() === "");
  }

  return false;
}

function normalizeStoredValueForControl(control: ControlSchema, rawValue: any): any {
  if (rawValue === undefined || rawValue === null) {
    return rawValue;
  }

  switch (control.type) {
    case "date-range":
      if (Array.isArray(rawValue)) {
        return rawValue.slice(0, 2).map((item: any) => String(item ?? ""));
      }
      if (typeof rawValue === "string") {
        return rawValue.split(",").map((item: string) => item.trim()).slice(0, 2);
      }
      return rawValue;

    case "multi-select":
    case "multi-select-grid":
      if (Array.isArray(rawValue)) {
        return rawValue.map((item: any) => String(item));
      }
      if (typeof rawValue === "string") {
        return rawValue
          .split(",")
          .map((item: string) => item.trim())
          .filter(Boolean);
      }
      return rawValue;

    case "number":
      if (typeof rawValue === "number") {
        return rawValue;
      }
      if (typeof rawValue === "string" && rawValue.trim() !== "") {
        const parsed = Number(rawValue);
        return Number.isNaN(parsed) ? rawValue : parsed;
      }
      return rawValue;

    case "checkbox":
      if (typeof rawValue === "boolean") {
        return rawValue;
      }
      if (typeof rawValue === "string") {
        return rawValue.trim().toLowerCase() === "true";
      }
      return Boolean(rawValue);

    default:
      return rawValue;
  }
}

function buildConditionValue(
  control: ControlSchema,
  target: SaveTargetSchema,
  storedValue: any
): ConditionValuePayload {
  const normalized = normalizeStoredValueForControl(control, storedValue);

  if (target.operator === "BETWEEN" || control.type === "date-range" || Array.isArray(normalized)) {
    const values = Array.isArray(normalized)
      ? normalized.map((item: any) => String(item ?? ""))
      : [String(normalized ?? "")];
    return { values };
  }

  if (control.type === "number" && typeof normalized === "number") {
    return { value: String(normalized) };
  }

  if (control.type === "checkbox") {
    return { value: String(Boolean(normalized)) };
  }

  return { value: String(normalized ?? "") };
}

function controlMatchesCondition(control: ControlSchema, condition: Condition): boolean {
  const conditionType = normalizeFilterType(condition.filter_type);
  if (!conditionType) {
    return false;
  }

  return getSaveTargets(control).some((target) => {
    const targetType = getTargetFilterGroup(target);
    const targetField = getTargetField(target);
    return (
      targetType === conditionType &&
      targetField === String(condition.column_name || "").trim() &&
      String(target.operator || "").trim().toUpperCase() ===
        String(condition.operator || "").trim().toUpperCase()
    );
  });
}

function conditionToStoredValue(control: ControlSchema, condition: Condition): any {
  switch (control.type) {
    case "date-range":
      if (Array.isArray(condition.values)) {
        return condition.values.slice(0, 2);
      }
      if (condition.value) {
        return condition.value.split(",").map((item: string) => item.trim()).slice(0, 2);
      }
      return undefined;

    case "multi-select":
    case "multi-select-grid":
      if (Array.isArray(condition.values)) {
        return condition.values;
      }
      if (condition.value) {
        return condition.value
          .split(",")
          .map((item: string) => item.trim())
          .filter(Boolean);
      }
      return [];

    case "number":
      if (condition.value === undefined || condition.value === null || String(condition.value).trim() === "") {
        return undefined;
      }
      return Number(condition.value);

    case "checkbox":
      if (condition.value === undefined || condition.value === null) {
        return undefined;
      }
      return String(condition.value).trim().toLowerCase() === "true";

    default:
      if (Array.isArray(condition.values) && condition.values.length === 1) {
        return condition.values[0];
      }
      if (condition.value !== undefined) {
        return condition.value;
      }
      if (Array.isArray(condition.values)) {
        return condition.values;
      }
      return undefined;
  }
}

function dedupeConditions(conditions: Condition[]): Condition[] {
  const seen = new Set<string>();
  const out: Condition[] = [];

  for (const condition of conditions) {
    const key = JSON.stringify(condition);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push(condition);
  }

  return out;
}

function buildFiltersPayloadFromSchemasInternal(
  name: string,
  collection: FilterCollection,
  schemas: Partial<Record<FilterType, FilterSchema>>
): { name: string; conditions: Condition[] } {
  const collectionMap = getStoredCollectionMap(collection);
  const conditions: Condition[] = [];

  for (const filterType of FILTER_TYPES) {
    const schema = schemas[filterType];
    const controls = schema?.controls ?? [];

    for (const control of controls) {
      const storedValue = getControlStoredValue(control, collectionMap);
      if (isBlankValue(storedValue)) {
        continue;
      }

      for (const target of getSaveTargets(control)) {
        const filterGroup = getTargetFilterGroup(target);
        const targetField = getTargetField(target);
        if (!filterGroup || !targetField) {
          continue;
        }

        const valuePayload = buildConditionValue(control, target, storedValue);
        conditions.push({
          filter_type: filterGroup,
          column_name: targetField,
          operator: target.operator,
          ...valuePayload
        });
      }
    }
  }

  return {
    name,
    conditions: dedupeConditions(conditions)
  };
}

function buildDefaultFilterCollectionFromConditionsInternal(
  conditions: Condition[],
  schemas: Partial<Record<FilterType, FilterSchema>>
): FilterCollection {
  const buckets: StoredCollectionMap = {
    patientQueryFilters: {},
    patientDataFilters: {},
    observationQueryFilters: {},
    observationDataFilters: {}
  };

  for (const filterType of FILTER_TYPES) {
    const schema = schemas[filterType];
    const controls = schema?.controls ?? [];

    for (const control of controls) {
      const field = getControlField(control);
      if (!field) {
        continue;
      }

      const matchingCondition = conditions.find((condition) => controlMatchesCondition(control, condition));
      if (!matchingCondition) {
        continue;
      }

      const matchingTarget = getSaveTargets(control).find((target) => {
        const targetType = getTargetFilterGroup(target);
        const targetField = getTargetField(target);
        return (
          targetType === normalizeFilterType(matchingCondition.filter_type) &&
          targetField === String(matchingCondition.column_name || "").trim() &&
          String(target.operator || "").trim().toUpperCase() ===
            String(matchingCondition.operator || "").trim().toUpperCase()
        );
      });

      if (!matchingTarget) {
        continue;
      }

      const targetGroup = getTargetFilterGroup(matchingTarget);
      const targetField = getTargetField(matchingTarget);
      const storedValue = conditionToStoredValue(control, matchingCondition);

      if (!targetGroup || !targetField || storedValue === undefined) {
        continue;
      }

      const bucketKey = inferCollectionKey(targetGroup);
      (buckets[bucketKey] as StoredBucket)[targetField] = storedValue;
    }
  }

  return buildCollectionFromBuckets(buckets);
}

export function getInitialValuesFromCollection(
  collection: FilterCollection,
  project: Project
): Record<string, any> {
  const resolvedSchemas = getSchemasFromProject(project);
  const collectionMap = getStoredCollectionMap(collection);
  const initialValues: Record<string, any> = {};

  for (const filterType of FILTER_TYPES) {
    const schema = resolvedSchemas[filterType];
    const controls = schema?.controls ?? [];

    for (const control of controls) {
      const field = getControlField(control);
      if (!field) {
        continue;
      }

      const storedValue = getControlStoredValue(control, collectionMap);
      if (storedValue === undefined) {
        continue;
      }

      initialValues[control.id] = normalizeStoredValueForControl(control, storedValue);
    }
  }

  return initialValues;
}

export function buildFiltersPayload(
  name: string,
  collection: FilterCollection,
  project: Project
): { name: string; conditions: Condition[] } {
  const resolvedSchemas = getSchemasFromProject(project);
  return buildFiltersPayloadFromSchemasInternal(name, collection, resolvedSchemas);
}

export function buildDefaultFilterCollectionFromConditions(
  conditions: Condition[],
  project: Project
): FilterCollection {
  const resolvedSchemas = getSchemasFromProject(project);
  return buildDefaultFilterCollectionFromConditionsInternal(conditions, resolvedSchemas);
}