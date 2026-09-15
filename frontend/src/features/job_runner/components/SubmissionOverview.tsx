import React, { JSX, useMemo } from "react";
import { Project, WorkflowGroupData } from "../../../types/Project";
import AccordionSection from "../../../components/AccordionSection";
import { formatFunctionName } from "../../../components/FunctionSelector";

interface ThresholdConfig {
  enabled?: boolean;
  thresholdMethod?: string;
  threshold?: number | string;
}

interface SubmissionOverviewProps {
  submittedFilterName: string;
  submittedFilter: Record<string, any> | null;
  selectedFunctions: Record<string, any>;
  hasSelectedFunctions: boolean;
  selectedThresholdConfig?: ThresholdConfig | null;
  selectedDatasourceGroupName?: string | null;
  workflowGroupData?: WorkflowGroupData | null;
  project: Project;
}

type FunctionConfigWarningRule = {
  property: string;
  values: string[];
  text: string;
  highlightColor: string;
};

const WARNING_PANEL_COLORS = {
  background: "#fff8db",
  border: "#d6a426",
  heading: "#8a5a00"
} as const;

const FUNCTION_CONFIG_WARNING_RULES: FunctionConfigWarningRule[] = [
  {
    property: "CI_type",
    values: ["log-log", "linear"],
    text: "Computing both the survival curve and confidence intervals reveals the underlying event counts and at risk totals for each time bin. If this level of data disclosure is not acceptable, please disable confidence interval computation.",
    highlightColor: WARNING_PANEL_COLORS.background
  }
];

function prettifyKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/^./, (str) => str.toUpperCase());
}

function formatValue(value: any): string {
  if (Array.isArray(value)) {
    const primitives = value.filter(
      (v) => v === null || (typeof v !== "object" && typeof v !== "function")
    );
    if (primitives.length === value.length) {
      return primitives.map((v) => (v ?? "").toString()).join(" - ");
    }
    return "";
  }
  return value?.toString?.() ?? "";
}

const sectionTitleStyle: React.CSSProperties = {
  fontWeight: 600,
  fontSize: "16px",
  marginBottom: ".5rem",
  borderBottom: "1px solid #ccc"
};

const labelStyle: React.CSSProperties = {
  color: "#4b5563",
  marginBottom: ".5rem"
};

const valueStyle: React.CSSProperties = {
  fontWeight: 600,
  color: "#111827"
};

const tdMini: React.CSSProperties = {
  padding: "5px 6px",
  borderBottom: "1px solid #F3F4F6",
  verticalAlign: "top",
  wordBreak: "break-word"
};

function isEmptySection(v: any): boolean {
  if (v == null) return true;

  if (typeof v === "string") {
    const s = v.trim();
    if (!s || s === "{}" || s === "[]" || s === "null") return true;
    try {
      const parsed = JSON.parse(s);
      return isEmptySection(parsed);
    } catch {
      return false;
    }
  }

  if (Array.isArray(v)) {
    if (v.length === 0) return true;
    return v.every((x) => isEmptySection(x));
  }

  if (typeof v === "object") {
    const keys = Object.keys(v);
    if (keys.length === 0) return true;
    return keys.every((k) => isEmptySection((v as any)[k]));
  }

  return false;
}

function getFunctionConfigWarning(propertyName: string, value: any): FunctionConfigWarningRule | null {
  const normalizedProperty = String(propertyName || "").trim().toLowerCase();
  const normalizedValue = String(value ?? "").trim().toLowerCase();

  for (const rule of FUNCTION_CONFIG_WARNING_RULES) {
    if (rule.property.trim().toLowerCase() !== normalizedProperty) continue;

    const matches = rule.values.some(
      (ruleValue) => ruleValue.trim().toLowerCase() === normalizedValue
    );

    if (matches) {
      return rule;
    }
  }

  return null;
}

const SubmissionOverview: React.FC<SubmissionOverviewProps> = ({
  submittedFilterName,
  submittedFilter,
  selectedFunctions,
  hasSelectedFunctions,
  selectedThresholdConfig,
  selectedDatasourceGroupName,
  workflowGroupData,
  project
}) => {
  const fixedPropsByFn = useMemo(() => {
    const out: Record<string, Set<string>> = {};
    const fns = (project as any)?.functions;
    if (!Array.isArray(fns)) return out;

    for (const f of fns) {
      if (!f || typeof f !== "object") continue;
      const fnName = typeof (f as any).function === "string" ? (f as any).function.trim() : "";
      if (!fnName) continue;

      const fixed = (f as any).custom_configuration_fixed;
      if (!fixed || typeof fixed !== "object" || Array.isArray(fixed)) continue;

      out[fnName.toUpperCase()] = new Set(Object.keys(fixed));
    }

    return out;
  }, [project]);

  const hasThreshold =
    !!selectedThresholdConfig &&
    !!selectedThresholdConfig.enabled &&
    !!selectedThresholdConfig.thresholdMethod &&
    selectedThresholdConfig.threshold != null;

  const hasFilters = !!submittedFilter && Object.keys(submittedFilter).length > 0;

  const workflowGroupRows = useMemo(() => {
    const rows: Array<{ groupLabel: string; optionLabel: string }> = [];
    const groups = Array.isArray(project?.workflow_groups) ? project.workflow_groups : [];

    for (const group of groups) {
      const selectedValues = workflowGroupData?.[group.group_key]?.selected_values || [];
      if (!Array.isArray(selectedValues) || selectedValues.length === 0) continue;

      const options = Array.isArray(group.options) ? group.options : [];

      for (const selectedValue of selectedValues) {
        const matchedOption = options.find(
          (option) => String(option?.option_value) === String(selectedValue)
        );

        rows.push({
          groupLabel: group.group_label,
          optionLabel: matchedOption?.option_label || String(selectedValue)
        });
      }
    }

    return rows;
  }, [project, workflowGroupData]);

  const hasWorkflowGroups = workflowGroupRows.length > 0;

  const hasContent = hasFilters || hasSelectedFunctions || hasThreshold || hasWorkflowGroups;

  if (!hasContent && !submittedFilterName) {
    return <></>;
  }

  const renderPrimitiveBlock = (label: string, v: any) => (
    <div
      key={label}
      className="duality-flex-column-min-0"
    >
      <div style={labelStyle}>{label}</div>
      <div style={valueStyle}>{formatValue(v)}</div>
    </div>
  );

  const renderFilterSectionRows = () => {
    if (!hasFilters || !submittedFilter) return null;

    const rows: JSX.Element[] = [];
    const groupBorder = "1px solid #000";

    Object.entries(submittedFilter).forEach(([sectionKey, value]) => {
      let parsedValue: any;
      try {
        parsedValue = typeof value === "string" ? JSON.parse(value) : value;
      } catch {
        parsedValue = value;
      }

      if (isEmptySection(parsedValue)) {
        return;
      }

      const sectionTitle = prettifyKey(sectionKey.replace("Filters", "").trim()) + " Filters";

      rows.push(
        <tr key={`${sectionKey}-label`}>
          <td
            colSpan={3}
            style={{
              ...tdMini,
              fontWeight: 600,
              padding: ".5rem",
              color: "#3F5FFF",
              borderBottom: "1px solid #E5E7EB"
            }}
          >
            {sectionTitle}
          </td>
        </tr>
      );

      if (Array.isArray(parsedValue)) {
        const nonEmptyItems = parsedValue.filter((item) => !isEmptySection(item));

        if (nonEmptyItems.length === 0) {
          rows.push(
            <tr key={`${sectionKey}-empty`}>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  maxWidth: "33.3333%",
                  borderBottom: groupBorder
                }}
              >
                &nbsp;
              </td>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  borderBottom: groupBorder
                }}
              >
                --
              </td>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  borderBottom: groupBorder
                }}
              >
                --
              </td>
            </tr>
          );
          return;
        }

        nonEmptyItems.forEach((item, itemIdx) => {
          if (item && typeof item === "object" && !Array.isArray(item)) {
            const entries = Object.entries(item).filter(([, v]) => !isEmptySection(v));

            if (entries.length === 0) {
              return;
            }

            entries.forEach(([k, v], entryIdx) => {
              const isLast =
                itemIdx === nonEmptyItems.length - 1 && entryIdx === entries.length - 1;

              rows.push(
                <tr key={`${sectionKey}-item-${itemIdx}-${k}`}>
                  <td
                    style={{
                      ...tdMini,
                      width: "33.3333%",
                      maxWidth: "33.3333%",
                      borderBottom: isLast ? groupBorder : "1px solid #F3F4F6"
                    }}
                  >
                    &nbsp;
                  </td>
                  <td
                    style={{
                      ...tdMini,
                      width: "33.3333%",
                      borderBottom: isLast ? groupBorder : "1px solid #F3F4F6"
                    }}
                  >
                    {prettifyKey(k)}
                  </td>
                  <td
                    style={{
                      ...tdMini,
                      width: "33.3333%",
                      borderBottom: isLast ? groupBorder : "1px solid #F3F4F6",
                      fontWeight: 600
                    }}
                  >
                    {formatValue(v)}
                  </td>
                </tr>
              );
            });
          } else {
            const isLast = itemIdx === nonEmptyItems.length - 1;

            rows.push(
              <tr key={`${sectionKey}-item-${itemIdx}`}>
                <td
                  style={{
                    ...tdMini,
                    width: "33.3333%",
                    maxWidth: "33.3333%",
                    borderBottom: isLast ? groupBorder : "1px solid #F3F4F6"
                  }}
                >
                  &nbsp;
                </td>
                <td
                  style={{
                    ...tdMini,
                    width: "33.3333%",
                    borderBottom: isLast ? groupBorder : "1px solid #F3F4F6"
                  }}
                >
                  Value
                </td>
                <td
                  style={{
                    ...tdMini,
                    width: "33.3333%",
                    borderBottom: isLast ? groupBorder : "1px solid #F3F4F6",
                    fontWeight: 600
                  }}
                >
                  {formatValue(item)}
                </td>
              </tr>
            );
          }
        });

        return;
      }

      if (parsedValue && typeof parsedValue === "object" && !Array.isArray(parsedValue)) {
        const entries = Object.entries(parsedValue).filter(([, v]) => !isEmptySection(v));

        if (entries.length === 0) {
          rows.push(
            <tr key={`${sectionKey}-empty`}>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  maxWidth: "33.3333%",
                  borderBottom: groupBorder
                }}
              >
                &nbsp;
              </td>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  borderBottom: groupBorder
                }}
              >
                --
              </td>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  borderBottom: groupBorder
                }}
              >
                --
              </td>
            </tr>
          );
          return;
        }

        entries.forEach(([k, v], entryIdx) => {
          const isLast = entryIdx === entries.length - 1;

          rows.push(
            <tr key={`${sectionKey}-${k}`}>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  maxWidth: "33.3333%",
                  borderBottom: isLast ? groupBorder : "1px solid #F3F4F6"
                }}
              >
                &nbsp;
              </td>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  borderBottom: isLast ? groupBorder : "1px solid #F3F4F6"
                }}
              >
                {prettifyKey(k)}
              </td>
              <td
                style={{
                  ...tdMini,
                  width: "33.3333%",
                  borderBottom: isLast ? groupBorder : "1px solid #F3F4F6",
                  fontWeight: 600
                }}
              >
                {formatValue(v)}
              </td>
            </tr>
          );
        });

        return;
      }

      const s = formatValue(parsedValue);

      if (!s) {
        return;
      }

      rows.push(
        <tr key={`${sectionKey}-value`}>
          <td
            style={{
              ...tdMini,
              width: "33.3333%",
              maxWidth: "33.3333%",
              borderBottom: groupBorder
            }}
          >
            &nbsp;
          </td>
          <td
            style={{
              ...tdMini,
              width: "33.3333%",
              borderBottom: groupBorder
            }}
          >
            Value
          </td>
          <td
            style={{
              ...tdMini,
              width: "33.3333%",
              borderBottom: groupBorder,
              fontWeight: 600
            }}
          >
            {s}
          </td>
        </tr>
      );
    });

    return rows;
  };

  const content = (
    <div
      className="submission-overview-block-01"
    >
      {/* <div
        style={{
          marginBottom: "0.75rem"
        }}
      >
        <span style={{ fontSize: "16px", fontWeight: 600, marginRight: "1rem" }}>
          Filter Set Name:{" "}
        </span>
        <span>{submittedFilterName}</span>
      </div> */}

      <div
        className="submission-overview-block-02"
      >

        {selectedDatasourceGroupName ? (
          <div
            className="duality-min-width-0"
          >
            <div
              className="submission-overview-block-03"
            >
              <span>Datasource Group:</span>
              <strong> <span  >{selectedDatasourceGroupName}</span></strong>
              
            </div>
          </div>
        ) : null}

        <div
          className="duality-min-width-0"
        >
          <div
            style={{
              ...sectionTitleStyle,
              border: "0"
            }}
          >
            Selected Filters
          </div>

          <div
            className="submission-overview-shared-01"
          >
            <div
              className="submission-overview-shared-02"
            >
              Section
            </div>
            <div
              className="submission-overview-shared-02"
            >
              Property
            </div>
            <div
              className="submission-overview-shared-02"
            >
              Value
            </div>
          </div>

          <div
            className="submission-overview-shared-03"
          >
            <table
              className="submission-overview-shared-04"
            >
              <tbody>
                {hasFilters ? (
                  renderFilterSectionRows()
                ) : (
                  <tr>
                    <td
                      style={{
                        ...tdMini,
                        width: "33.3333%",
                        maxWidth: "33.3333%",
                        borderBottom: "1px solid #000"
                      }}
                    >
                      &nbsp;
                    </td>
                    <td
                      style={{
                        ...tdMini,
                        width: "33.3333%",
                        borderBottom: "1px solid #000"
                      }}
                    >
                      --
                    </td>
                    <td
                      style={{
                        ...tdMini,
                        width: "33.3333%",
                        borderBottom: "1px solid #000"
                      }}
                    >
                      --
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {hasWorkflowGroups ? (
          <div
            className="duality-min-width-0"
          >
            <div style={{ ...sectionTitleStyle, border: "0" }}>
              Custom Workflow Options
            </div>

            <div
              className="submission-overview-shared-01"
            >
              <div
                className="submission-overview-shared-05"
              >
                Group
              </div>
              <div
                className="submission-overview-shared-05"
              >
                Selected Option
              </div>
            </div>

            <div
              className="submission-overview-shared-03"
            >
              <table
                className="submission-overview-shared-04"
              >
                <tbody>
                  {workflowGroupRows.map((row, idx) => {
                    const isLast = idx === workflowGroupRows.length - 1;
                    return (
                      <tr key={`${row.groupLabel}-${row.optionLabel}-${idx}`}>
                        <td
                          style={{
                            ...tdMini,
                            width: "50%",
                            borderBottom: isLast ? "1px solid #000" : "1px solid #F3F4F6"
                          }}
                        >
                          {row.groupLabel}
                        </td>
                        <td
                          style={{
                            ...tdMini,
                            width: "50%",
                            borderBottom: isLast ? "1px solid #000" : "1px solid #F3F4F6",
                            fontWeight: 600
                          }}
                        >
                          {row.optionLabel}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        <div
          className="duality-min-width-0"
        >
          {hasSelectedFunctions && selectedFunctions && Object.keys(selectedFunctions).length > 0 && (
            <div
              className="submission-overview-shared-06"
            >
              <div style={{ ...sectionTitleStyle, border: "0" }}>
                {"Selected Analysis Functions & Parameters"}
              </div>
              <div
                className="submission-overview-shared-01"
              >
                <div
                  className="submission-overview-shared-02"
                >
                  Function
                </div>
                <div
                  className="submission-overview-shared-02"
                >
                  Property
                </div>
                <div
                  className="submission-overview-shared-02"
                >
                  Value
                </div>
              </div>
              <div
                className="submission-overview-shared-03"
              >

                <table
                  className="submission-overview-shared-04"
                >
                  <tbody>
                    {Object.keys(selectedFunctions)
                      .sort()
                      .flatMap((fn) => {
                        const rawCfg = selectedFunctions[fn];

                        const configs: Record<string, any>[] = Array.isArray(rawCfg)
                          ? rawCfg
                          : rawCfg && typeof rawCfg === "object"
                            ? [rawCfg as Record<string, any>]
                            : [];

                        const fixedSet = fixedPropsByFn[String(fn).toUpperCase()] || new Set<string>();

                        const groupBorder = "1px solid #000";

                        if (configs.length === 0) {
                          return (
                            <React.Fragment key={fn}>
                              <tr>
                                <td
                                  colSpan={3}
                                  style={{
                                    ...tdMini,
                                    fontWeight: 600,
                                    backgroundColor: "#ddfdee",
                                    borderBottom: groupBorder
                                  }}
                                >
                                  {formatFunctionName(fn)}
                                </td>
                              </tr>
                              <tr>
                                <td
                                  style={{
                                    ...tdMini,
                                    width: "33%",
                                    maxWidth: "33%",
                                    borderBottom: groupBorder
                                  }}
                                >
                                  &nbsp;
                                </td>
                                <td
                                  style={{
                                    ...tdMini,
                                    borderBottom: groupBorder
                                  }}
                                >
                                  --
                                </td>
                                <td
                                  style={{
                                    ...tdMini,
                                    borderBottom: groupBorder
                                  }}
                                >
                                  --
                                </td>
                              </tr>
                            </React.Fragment>
                          );
                        }

                        const rows: JSX.Element[] = [];

                        configs.forEach((cfg, cfgIndex) => {
                          const entries = Object.entries(cfg || {})
                            .filter(([k]) => !fixedSet.has(k))
                            .sort((a, b) => a[0].localeCompare(b[0]));

                          const label =
                            cfgIndex === 0 ? formatFunctionName(fn) : `${formatFunctionName(fn)} ${cfgIndex + 1}`;

                          rows.push(
                            <tr key={`${fn}-cfg-${cfgIndex}-label`}>
                              <td
                                colSpan={3}
                                style={{
                                  ...tdMini,
                                  fontWeight: 600,
                                  padding: ".5rem",
                                  color: "#3F5FFF",
                                  borderBottom: entries.length === 0 ? groupBorder : "1px solid #E5E7EB"
                                }}
                              >
                                {label}
                              </td>
                            </tr>
                          );

                          if (entries.length === 0) {
                            rows.push(
                              <tr key={`${fn}-cfg-${cfgIndex}-empty`}>
                                <td
                                  style={{
                                    ...tdMini,
                                    width: "33%",
                                    maxWidth: "33%",
                                    borderBottom: groupBorder
                                  }}
                                >
                                  &nbsp;
                                </td>
                                <td
                                  style={{
                                    ...tdMini,
                                    borderBottom: groupBorder
                                  }}
                                >
                                  --
                                </td>
                                <td
                                  style={{
                                    ...tdMini,
                                    borderBottom: groupBorder
                                  }}
                                >
                                  --
                                </td>
                              </tr>
                            );
                            return;
                          }

                          entries.forEach(([k, v], entryIdx) => {
                            const warningRule = getFunctionConfigWarning(k, v);
                            const isWarningRow = !!warningRule;
                            const isLast = entryIdx === entries.length - 1;
                            const baseBorderBottom = isLast ? groupBorder : "1px solid #F3F4F6";

                            const sharedCellStyle: React.CSSProperties = {
                              backgroundColor: isWarningRow ? warningRule.highlightColor : undefined,
                              borderTop: isWarningRow
                                ? `2px solid ${WARNING_PANEL_COLORS.border}`
                                : undefined,
                              borderBottom: isWarningRow
                                ? `2px solid ${WARNING_PANEL_COLORS.border}`
                                : baseBorderBottom
                            };

                            rows.push(
                              <tr key={`${fn}-cfg-${cfgIndex}-${k}`}>
                                <td
                                  style={{
                                    ...tdMini,
                                    ...sharedCellStyle,
                                    width: "33%",
                                    maxWidth: "33%",
                                    borderLeft: isWarningRow
                                      ? `2px solid ${WARNING_PANEL_COLORS.border}`
                                      : undefined,
                                    borderTop: isWarningRow
                                      ? `2px solid ${WARNING_PANEL_COLORS.border}`
                                      : undefined,
                                    fontSize: isWarningRow ? "0.75rem" : undefined,
                                    lineHeight: isWarningRow ? 1.35 : undefined
                                  }}
                                >
                                  {isWarningRow ? (
                                    <>
                                      <strong style={{ color: WARNING_PANEL_COLORS.heading }}>
                                        WARNING:
                                      </strong>{" "}
                                      {warningRule.text}
                                    </>
                                  ) : (
                                    ""
                                  )}
                                </td>
                                <td
                                  style={{
                                    ...tdMini,
                                    ...sharedCellStyle,
                                  }}
                                >
                                  {prettifyKey(k)}
                                </td>
                                <td
                                  style={{
                                    ...tdMini,
                                    ...sharedCellStyle,
                                    borderRight: isWarningRow
                                      ? `2px solid ${WARNING_PANEL_COLORS.border}`
                                      : undefined,
                                    borderTop: isWarningRow
                                      ? `2px solid ${WARNING_PANEL_COLORS.border}`
                                      : undefined,
                                    fontWeight: isWarningRow ? 700 : undefined
                                  }}
                                >
                                  {String(v)}
                                </td>
                              </tr>
                            );
                          });
                        });

                        return rows;
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {!hasSelectedFunctions && (
            <div
              className="submission-overview-shared-06"
            >
              <div style={{ ...sectionTitleStyle, border: "0" }}>
                {"Selected Analysis Functions & Parameters"}
              </div>
              <div
                className="submission-overview-shared-01"
              >
                <div
                  className="submission-overview-shared-02"
                >
                  Function
                </div>
                <div
                  className="submission-overview-shared-02"
                >
                  Property
                </div>
                <div
                  className="submission-overview-shared-02"
                >
                  Value
                </div>
              </div>
              <div
                className="submission-overview-shared-03"
              >
                <table
                  className="submission-overview-shared-04"
                >
                  <tbody>
                    <tr>
                      <td
                        style={{
                          ...tdMini,
                          width: "33.3333%",
                          borderBottom: "1px solid #000"
                        }}
                      >
                        --
                      </td>
                      <td
                        style={{
                          ...tdMini,
                          width: "33.3333%",
                          borderBottom: "1px solid #000"
                        }}
                      >
                        --
                      </td>
                      <td
                        style={{
                          ...tdMini,
                          width: "33.3333%",
                          borderBottom: "1px solid #000"
                        }}
                      >
                        --
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {hasThreshold && selectedThresholdConfig && (
            <div
              className="submission-overview-block-04"
            >
              <div style={sectionTitleStyle}>Threshold Configuration</div>
              <div
                className="submission-overview-block-05"
              >
                {renderPrimitiveBlock("Threshold", selectedThresholdConfig.threshold)}
                {renderPrimitiveBlock("Method", selectedThresholdConfig.thresholdMethod)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <section className="submission-overview-block-06">
      <AccordionSection title="Submission Overview" defaultExpanded>
        {content}
      </AccordionSection>
    </section>
  );
};

export default SubmissionOverview;