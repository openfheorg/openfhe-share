import {
  buildDefaultFilterCollectionFromConditions,
  buildFiltersPayload,
  createEmptyFilterCollection,
  getInitialValuesFromCollection,
} from "./FilterPayloadConfigUtils";
import { Project } from "../../../types/Project";

const project: Project = {
  id: 2,
  name: "Filter Test",
  function_restrictions_enabled: false,
  functions: [],
  filter_schemas: {
    PATIENT_QUERY: {
      controls: [
        {
          id: "age",
          field: "age",
          type: "number",
          save: {
            targets: [
              {
                filter_group: "PATIENT_QUERY",
                field: "age",
                operator: "GTE",
              },
            ],
          },
        },
        {
          id: "active",
          field: "active",
          type: "checkbox",
          save: {
            targets: [
              {
                filter_group: "PATIENT_QUERY",
                field: "active",
                operator: "EQ",
              },
            ],
          },
        },
      ],
    },
    OBSERVATION_QUERY: {
      controls: [
        {
          id: "genes",
          field: "genes",
          type: "multi-select",
          save: {
            targets: [
              {
                filter_group: "OBSERVATION_QUERY",
                field: "gene",
                operator: "IN",
              },
            ],
          },
        },
        {
          id: "dateRange",
          field: "dateRange",
          type: "date-range",
          save: {
            targets: [
              {
                filter_group: "OBSERVATION_QUERY",
                field: "observed_at",
                operator: "BETWEEN",
              },
            ],
          },
        },
      ],
    },
  },
};

describe("FilterPayloadConfigUtils", () => {
  test("creates an empty filter collection", () => {
    expect(createEmptyFilterCollection()).toEqual({
      patientQueryFilters: "{}",
      patientDataFilters: "{}",
      observationQueryFilters: "{}",
      observationDataFilters: "{}",
    });
  });

  test("hydrates control values from stored filter buckets with useful types", () => {
    const values = getInitialValuesFromCollection(
      {
        patientQueryFilters: JSON.stringify({ age: "42", active: "true" }),
        patientDataFilters: "{}",
        observationQueryFilters: JSON.stringify({
          gene: "TP53,VHL",
          observed_at: "2026-01-01,2026-02-01",
        }),
        observationDataFilters: "{}",
      },
      project
    );

    expect(values).toEqual({
      age: 42,
      active: true,
      genes: ["TP53", "VHL"],
      dateRange: ["2026-01-01", "2026-02-01"],
    });
  });

  test("builds API conditions from configured save targets", () => {
    const payload = buildFiltersPayload(
      "Demo Filter",
      {
        patientQueryFilters: JSON.stringify({ age: 65, active: false }),
        patientDataFilters: "{}",
        observationQueryFilters: JSON.stringify({
          gene: ["TP53", "VHL"],
          observed_at: ["2026-01-01", "2026-02-01"],
        }),
        observationDataFilters: "{}",
      },
      project
    );

    expect(payload).toEqual({
      name: "Demo Filter",
      conditions: [
        { filter_type: "PATIENT_QUERY", column_name: "age", operator: "GTE", value: "65" },
        { filter_type: "PATIENT_QUERY", column_name: "active", operator: "EQ", value: "false" },
        {
          filter_type: "OBSERVATION_QUERY",
          column_name: "gene",
          operator: "IN",
          values: ["TP53", "VHL"],
        },
        {
          filter_type: "OBSERVATION_QUERY",
          column_name: "observed_at",
          operator: "BETWEEN",
          values: ["2026-01-01", "2026-02-01"],
        },
      ],
    });
  });

  test("rebuilds stored filter buckets from API conditions", () => {
    const collection = buildDefaultFilterCollectionFromConditions(
      [
        { filter_type: "PATIENT_QUERY", column_name: "age", operator: "GTE", value: "55" },
        { filter_type: "PATIENT_QUERY", column_name: "active", operator: "EQ", value: "true" },
        {
          filter_type: "OBSERVATION_QUERY",
          column_name: "gene",
          operator: "IN",
          values: ["PBRM1", "VHL"],
        },
      ],
      project
    );

    expect(JSON.parse(collection.patientQueryFilters)).toEqual({ age: 55, active: true });
    expect(JSON.parse(collection.observationQueryFilters)).toEqual({ gene: ["PBRM1", "VHL"] });
  });

  test("ignores blank or unrelated stored values", () => {
    const payload = buildFiltersPayload(
      "Blank Filter",
      {
        patientQueryFilters: JSON.stringify({ age: "", unrelated: "ignored" }),
        patientDataFilters: "{}",
        observationQueryFilters: "{}",
        observationDataFilters: "{}",
      },
      project
    );

    expect(payload.conditions).toEqual([]);
  });
});
