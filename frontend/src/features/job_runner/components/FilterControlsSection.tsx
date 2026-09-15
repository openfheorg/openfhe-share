// src/features/job_runner/components/FilterControlsSection.tsx
import React, { useEffect, useMemo, useState } from "react";
import { Project } from "../../../types/Project";
import {
  Condition,
  ControlSchema,
  FilterSchema,
  FilterType,
  SaveTargetSchema
} from "../../../types/FilterSchema";

type CompiledChange = { conditions: Condition[]; fhirParams: string };

export interface FilterControlsSectionProps {
  schemaUrl?: string;
  project?: Project;
  filterType: FilterType;
  initialConditions?: Condition[];
  initialValues?: Record<string, any>;
  lock?: boolean;
  onCompiledChange: (c: CompiledChange) => void;
}

function toArray<T>(v: T | T[] | undefined | null): T[] {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

function stringifyToken(val: any): string {
  if (val == null) return "";
  if (Array.isArray(val)) return val.filter((x) => x !== "").join(",");
  return String(val);
}

function transformValue(v: any, t?: "int" | "float" | "string") {
  if (t === "int") return v === "" || v == null ? null : parseInt(v, 10);
  if (t === "float") return v === "" || v == null ? null : parseFloat(v);
  if (t === "string") return v == null ? "" : String(v);
  return v;
}

function normalizeTarget(target: SaveTargetSchema): {
  filter_type: FilterType | undefined;
  column_name: string;
  operator: string;
  valueFrom?: "value";
  transform?: "int" | "float" | "string";
} {
  return {
    filter_type: target.filter_group || target.filter_type,
    column_name: String(target.field || target.column_name || "").trim(),
    operator: target.operator,
    valueFrom: target.valueFrom,
    transform: target.transform
  };
}

function resolveDefaultValue(raw: any, defaultsResolver?: Record<string, any>): any {
  if (Array.isArray(raw)) {
    return raw.map((v) => resolveDefaultValue(v, defaultsResolver));
  }

  if (typeof raw !== "string" || !raw.startsWith("$")) {
    return raw;
  }

  if (!defaultsResolver || !defaultsResolver[raw]) {
    return raw;
  }

  const resolver = defaultsResolver[raw];
  if (!resolver || typeof resolver !== "object") {
    return raw;
  }

  if (resolver.fn === "today") {
    return new Date().toISOString().slice(0, 10);
  }

  if (resolver.fn === "offset") {
    const dt = new Date();
    if (typeof resolver.years === "number") {
      dt.setFullYear(dt.getFullYear() + resolver.years);
    }
    if (typeof resolver.months === "number") {
      dt.setMonth(dt.getMonth() + resolver.months);
    }
    if (typeof resolver.days === "number") {
      dt.setDate(dt.getDate() + resolver.days);
    }
    return dt.toISOString().slice(0, 10);
  }

  return raw;
}

const rowStyle: React.CSSProperties = {
  display: "grid",
  gap: "0.75rem",
  gridTemplateColumns: "repeat(12, minmax(0, 1fr))"
};

const cellForSpan = (span?: "full" | "half" | "third") =>
  span === "half"
    ? { gridColumn: "span 6 / span 6" }
    : span === "third"
      ? { gridColumn: "span 4 / span 4" }
      : { gridColumn: "span 12 / span 12" };

function getSchemaFromProject(project: Project | undefined, filterType: FilterType): FilterSchema | null {
  const schema = project?.filter_schemas?.[filterType];
  return schema || null;
}

const FilterControlsSection: React.FC<FilterControlsSectionProps> = ({
  schemaUrl,
  project,
  filterType,
  initialConditions = [],
  initialValues,
  lock = false,
  onCompiledChange
}) => {
  const [schema, setSchema] = useState<FilterSchema | null>(null);
  const [values, setValues] = useState<Record<string, any>>({});
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const projectSchema = getSchemaFromProject(project, filterType);
      if (projectSchema) {
        if (cancelled) return;
        setSchema(projectSchema);
        return;
      }

      if (!schemaUrl) {
        if (cancelled) return;
        setSchema(null);
        return;
      }

      const res = await fetch(schemaUrl, { cache: "no-store" });
      const json = (await res.json()) as FilterSchema;
      if (cancelled) return;

      setSchema(json);
    })();

    return () => {
      cancelled = true;
    };
  }, [schemaUrl, project, filterType]);

  useEffect(() => {
    if (!schema) {
      return;
    }

    const vInit: Record<string, any> = {};
    for (const c of schema.controls || []) {
      if (c.type === "label" || c.type === "hidden") continue;

      const resolvedDefault = resolveDefaultValue(c.default, schema.defaultsResolver);

      if (c.type === "checkbox") {
        vInit[c.id] = !!resolvedDefault;
      } else if (c.type === "multi-select" || c.type === "multi-select-grid") {
        vInit[c.id] = toArray(resolvedDefault);
      } else if (c.type === "number") {
        vInit[c.id] = resolvedDefault ?? "";
      } else if (c.type === "date-range") {
        const rawArr = Array.isArray(resolvedDefault) ? resolvedDefault.slice(0, 2) : ["", ""];
        vInit[c.id] = rawArr.map((d: string) => toHtmlDate(d, schema.defaultsResolver));
      } else if (c.type === "token-select") {
        vInit[c.id] = resolvedDefault ?? "";
      } else {
        vInit[c.id] = resolvedDefault ?? "";
      }
    }

    setValues(vInit);
    setReady(true);
  }, [schema]);

  useEffect(() => {
    if (!schema) return;

    const initialLookup = buildInitialValueLookup(initialConditions, schema.controls || [], filterType);
    if (Object.keys(initialLookup).length === 0) return;

    setValues((prev) => ({ ...prev, ...initialLookup }));
  }, [schema, initialConditions, filterType]);

  useEffect(() => {
    if (!schema) return;
    if (!initialValues) return;
    setValues((prev) => ({ ...prev, ...initialValues }));
  }, [initialValues, schema]);

  const compiled = useMemo<CompiledChange>(() => {
    const conditionsOut: Condition[] = [];
    const params = new URLSearchParams();

    const addParam = (p: string, v: string) => {
      if (!p) return;
      if (v == null || v === "") return;
      params.append(p, v);
    };

    const mergeOrParam = (p: string, valuesToMerge: string[]) => {
      if (!p || valuesToMerge.length === 0) {
        return;
      }

      const existing = params.get(p);
      const existingValues = existing
        ? existing.split(",").map((value) => value.trim()).filter((value) => value !== "")
        : [];
      const merged = Array.from(new Set(existingValues.concat(valuesToMerge)));
      params.delete(p);
      if (merged.length > 0) {
        params.append(p, merged.join(","));
      }
    };

    const compileQueryParam = (control: any, rawValue: any) => {
      const query = control?.query;
      if (!query || !query.param) {
        return;
      }

      if (query.kind === "search-param") {
        const rawToken = query.value != null ? query.value : stringifyToken(rawValue);
        const normalizedToken = String(rawToken || "").trim();
        if (normalizedToken === "") {
          return;
        }

        const value = `${query.valuePrefix || ""}${normalizedToken}`;
        if (query.combine === "or") {
          mergeOrParam(query.param, [value]);
        } else {
          addParam(query.param, value);
        }
        return;
      }

      if (query.kind === "code-list") {
        const sourceValues = Array.isArray(rawValue) ? rawValue : [];
        const compiledValues = sourceValues
          .map((value) => String(value || "").trim())
          .filter((value) => value !== "")
          .map((value) => `${query.valuePrefix || ""}${value}`);

        if (query.combine === "or") {
          mergeOrParam(query.param, compiledValues);
        } else {
          compiledValues.forEach((value) => addParam(query.param, value));
        }
        return;
      }

      if (query.kind === "composite-param") {
        const sourceValues = Array.isArray(rawValue) ? rawValue : rawValue == null || rawValue === "" ? [] : [rawValue];
        const compiledValues = sourceValues
          .map((value) => String(value || "").trim())
          .filter((value) => value !== "")
          .map((value) => {
            const leftSystem = String(query.leftSystem || "").trim();
            const leftCode = String(query.leftCode || "").trim();
            const rightSystem = String(query.rightSystem || "").trim();
            const left = `${leftSystem}|${leftCode}`;
            const right = `${rightSystem}|${value}`;
            return `${left}$${right}`;
          });

        if (query.combine === "or") {
          mergeOrParam(query.param, compiledValues);
        } else {
          compiledValues.forEach((value) => addParam(query.param, value));
        }
      }
    };

    if (schema) {
      for (const c of schema.controls || []) {
        if (c.type === "label" || c.type === "hidden") continue;

        const v = values[c.id];

        if ((c as any).fhir) {
          const fhir = (c as any).fhir;
          if (fhir.kind === "search-param") {
            const value = fhir.value != null ? fhir.value : stringifyToken(v);
            if (value !== "") addParam(fhir.param, value);
          } else if (fhir.kind === "date-range") {
            const [start, end] = Array.isArray(v) ? v : ["", ""];
            if (start) addParam(fhir.param, `ge${start}`);
            if (end) addParam(fhir.param, `le${end}`);
          } else if (fhir.kind === "component-value-concept") {
            const tok = stringifyToken(v);
            if (tok !== "") {
              addParam("component-code", `${fhir.component.system}|${fhir.component.code}`);
              addParam("component-value-concept", tok);
            }
          } else if (fhir.kind === "reverse-chain") {
            const tok = stringifyToken(v);
            if (
              tok !== "" &&
              fhir.has.resource &&
              fhir.has.referenceParam &&
              fhir.has.filterParam
            ) {
              const key = `_has:${fhir.has.resource}:${fhir.has.referenceParam}:${fhir.has.filterParam}`;
              addParam(key, tok);
            }
          }
        }

        compileQueryParam(c as any, v);

        if (c.save?.targets?.length) {
          for (const rawTarget of c.save.targets) {
            const t = normalizeTarget(rawTarget);
            const raw = t.valueFrom === "value" ? v : v;
            const transformed = transformValue(raw, t.transform);

            if (!t.filter_type || !t.column_name) {
              continue;
            }

            if (t.operator === "BETWEEN") {
              const arr = Array.isArray(transformed) ? transformed : [];
              const vals = arr.slice(0, 2).map((x) => (x == null ? "" : String(x)));
              if (vals[0] === "" && vals[1] === "") continue;
              conditionsOut.push({
                filter_type: t.filter_type,
                column_name: t.column_name,
                operator: t.operator,
                values: vals
              });
            } else {
              if (Array.isArray(transformed) && transformed.length === 0) continue;
              if (transformed === "" || transformed == null) continue;

              if (Array.isArray(transformed)) {
                const vals = transformed
                  .map((x) => (x == null ? "" : String(x)))
                  .filter((x) => x !== "");
                if (vals.length === 0) continue;
                conditionsOut.push({
                  filter_type: t.filter_type,
                  column_name: t.column_name,
                  operator: t.operator,
                  values: vals
                });
              } else {
                const val = String(transformed);
                if (val === "") continue;
                conditionsOut.push({
                  filter_type: t.filter_type,
                  column_name: t.column_name,
                  operator: t.operator,
                  value: val
                });
              }
            }
          }
        }
      }
    }

    return { conditions: conditionsOut, fhirParams: params.toString() };
  }, [schema, values]);

  useEffect(() => {
    if (!ready) return;
    onCompiledChange(compiled);
  }, [compiled, ready, onCompiledChange]);

  if (!schema) {
    return (
      <div
        className="filter-controls-section-block-01"
      >
        Loading controls…
      </div>
    );
  }

  const updateValue = (id: string, val: any) => {
    if (lock) return;
    setValues((prev) => ({ ...prev, [id]: val }));
  };

  return (
    <div style={{ ...rowStyle, marginTop: "0.5rem" }}>
      {(schema.controls || []).map((c) => {
        const spanStyle = cellForSpan(c.ui?.span);

        if (c.type === "hidden") return null;

        if (c.type === "label") {
          return (
            <div key={c.id} style={spanStyle}>
              <div className="filter-controls-section-block-02">{c.label}</div>
              {typeof c.default === "string" && c.default.trim() !== "" && (
                <div className="filter-controls-section-block-03">{c.default}</div>
              )}
            </div>
          );
        }

        const isDisabled = lock || c.ui?.editable === false || c.disabled === true;

        if (c.type === "select") {
          return (
            <div key={c.id} style={spanStyle}>
              <label className="field-label" style={{ color: isDisabled ? "#666" : undefined }}>
                {c.label}
              </label>
              <select
                value={values[c.id] ?? ""}
                disabled={isDisabled}
                onChange={(e) => updateValue(c.id, e.target.value)}
                className="duality-w-100pct-p-0p5rem"
              >
                {(c.options || []).map((o) => {
                  const value = o.value ?? "";
                  return (
                    <option key={value} value={value}>
                      {o.label}
                    </option>
                  );
                })}
              </select>
            </div>
          );
        }

        if (c.type === "token-select") {
          const current = values[c.id] ?? "";
          return (
            <div key={c.id} style={spanStyle}>
              <label className="field-label" style={{ color: isDisabled ? "#666" : undefined }}>
                {c.label}
              </label>
              <select
                value={current}
                disabled={isDisabled}
                onChange={(e) => updateValue(c.id, e.target.value)}
                className="duality-w-100pct-p-0p5rem"
              >
                {(c.options || []).map((o) => {
                  const value = o.value ?? o.token ?? "";
                  const label = o.label ?? value;
                  return (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>
          );
        }

        if (c.type === "multi-select") {
          const selected = toArray(values[c.id]).map(String);
          return (
            <div key={c.id} style={spanStyle}>
              <label className="field-label">{c.label}</label>
              <div
                className="filter-controls-section-block-04" style={{ background: isDisabled ? "#f6f6f6" : "white" }}
              >
                {(c.options || []).map((o) => {
                  const v = (o.value ?? o.token ?? "") as string;
                  const checked = selected.includes(String(v));
                  return (
                    <label key={v} className="duality-flex-gap-half-center">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={isDisabled}
                        onChange={(e) => {
                          if (e.target.checked) updateValue(c.id, [...selected, v]);
                          else updateValue(c.id, selected.filter((x) => x !== String(v)));
                        }}
                      />
                      <span>{o.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          );
        }

        if (c.type === "multi-select-grid") {
          const selected = toArray(values[c.id]).map(String);
          const containerStyle: React.CSSProperties = {
            border: "1px solid #ccc",
            borderRadius: 6,
            padding: "0.5rem",
            maxHeight: 200,
            overflow: "auto",
            background: isDisabled ? "#f6f6f6" : "white",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
            gap: "0.25rem"
          };

          return (
            <div key={c.id} style={spanStyle}>
              <label className="field-label">{c.label}</label>
              <div style={containerStyle}>
                {(c.options || []).map((o) => {
                  const v = (o.value ?? o.token ?? "") as string;
                  const checked = selected.includes(String(v));
                  return (
                    <label key={v} className="duality-flex-gap-half-center">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={isDisabled}
                        onChange={(e) => {
                          if (e.target.checked) updateValue(c.id, [...selected, v]);
                          else updateValue(c.id, selected.filter((x) => x !== String(v)));
                        }}
                      />
                      <span>{o.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          );
        }

        if (c.type === "number") {
          return (
            <div key={c.id} style={spanStyle}>
              <label className="field-label">{c.label}</label>
              <input
                type="number"
                value={values[c.id] ?? ""}
                disabled={isDisabled}
                onChange={(e) => updateValue(c.id, e.target.value)}
                className="duality-w-100pct-p-0p5rem"
              />
            </div>
          );
        }

        if (c.type === "checkbox") {
          return (
            <div
              key={c.id}
              style={{ ...spanStyle, display: "flex", alignItems: "center", gap: "0.5rem" }}
            >
              <input
                type="checkbox"
                checked={!!values[c.id]}
                disabled={isDisabled}
                onChange={(e) => updateValue(c.id, e.target.checked)}
              />
              <label className="field-label filter-controls-section-block-05" >
                {c.label}
              </label>
            </div>
          );
        }

        if (c.type === "date-range") {
          const [start, end] = Array.isArray(values[c.id]) ? values[c.id] : ["", ""];
          return (
            <div key={c.id} style={spanStyle}>
              <label className="field-label">{c.label}</label>
              <div className="filter-controls-section-block-06">
                <input
                  type="date"
                  value={start || ""}
                  disabled={isDisabled}
                  onChange={(e) => updateValue(c.id, [fromHtmlDate(e.target.value), end || ""])}
                  className="filter-controls-section-shared-01"
                />
                <input
                  type="date"
                  value={end || ""}
                  disabled={isDisabled}
                  onChange={(e) => updateValue(c.id, [start || "", fromHtmlDate(e.target.value)])}
                  className="filter-controls-section-shared-01"
                />
              </div>
            </div>
          );
        }

        return (
          <div key={c.id} style={spanStyle}>
            <label className="field-label">{c.label}</label>
            <input
              value={values[c.id] ?? ""}
              disabled={isDisabled}
              onChange={(e) => updateValue(c.id, e.target.value)}
              className="duality-w-100pct-p-0p5rem"
            />
          </div>
        );
      })}
    </div>
  );
};

function buildInitialValueLookup(
  initialConditions: Condition[],
  controls: ControlSchema[],
  filterType: FilterType
): Record<string, any> {
  const nextValues: Record<string, any> = {};

  for (const control of controls || []) {
    const targets = control.save?.targets || [];
    for (const rawTarget of targets) {
      const target = normalizeTarget(rawTarget);

      if (target.filter_type !== filterType || !target.column_name) {
        continue;
      }

      const match = initialConditions.find(
        (condition) =>
          condition.filter_type === target.filter_type &&
          condition.column_name === target.column_name &&
          condition.operator === target.operator
      );

      if (!match) {
        continue;
      }

      if (target.operator === "BETWEEN") {
        nextValues[control.id] = Array.isArray(match.values) ? match.values.slice(0, 2) : ["", ""];
      } else if (Array.isArray(match.values)) {
        nextValues[control.id] = match.values.slice();
      } else if (typeof match.value === "string") {
        nextValues[control.id] = match.value;
      }
    }
  }

  return nextValues;
}

function toHtmlDate(raw?: string, defaultsResolver?: Record<string, any>): string {
  if (!raw) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;

  if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(raw)) {
    const [m, d, y] = raw.split("/");
    const mm = m.padStart(2, "0");
    const dd = d.padStart(2, "0");
    return `${y}-${mm}-${dd}`;
  }

  const resolved = resolveDefaultValue(raw, defaultsResolver);
  if (typeof resolved === "string" && /^\d{4}-\d{2}-\d{2}$/.test(resolved)) {
    return resolved;
  }

  return "";
}

function fromHtmlDate(htmlValue: string): string {
  return htmlValue;
}

export default FilterControlsSection;