import React, { useCallback, useEffect, useMemo, useState } from "react";
import WorkflowErrorPanel, { getWorkflowWarning } from "../../../components/WorkflowErrorPanel";
import { Project } from "../../../types/Project";
import {
  ProfileSummaryWorkflows,
  WorkflowJobData,
  getWorkflowErrorFromJobData,
  formatPValueForUI,
  formatWorkflowDisplayName,
} from "../utils/JobsDataUtils";
import { WorkflowAnalyticsAccordion, buildWorkflowAnalyticsExportBlocks } from "./AnalyticsMetricsAccordion";
import FunctionConfigurationAccordion from "./FunctionConfigurationAccordion";
import { UserRole } from "../../../context/UserRoleContext";
import { ExportBlock, ExportSection } from "../utils/ExportDocTypes";
import { useRegisterExportSection } from "./export/useRegisterExportSection";
import OddsRatioLollipopPlot, { createOddsRatioLollipopPlotPng } from "./OddsRatioLollipopPlot";

export interface ScalarResultWorkflowProps {
  workflows: WorkflowJobData[];
  activeIndex: number;
  onActiveIndexChange: (idx: number) => void;
  analyticsWorkflows?: ProfileSummaryWorkflows | null;
  project: Project;
  userRole: UserRole;
}

interface ScalarPropertyConfig {
  keys: string[];
  label: string;
  agentLabel?: string;
  precision?: number;
  unitLabel?: string;
  exact?: boolean;
}

type RowVariant = "agent" | "aggregated";

interface ResultCardProps extends ScalarResultWorkflowProps {
  title: string;
  workflowDisplayNamePrefix?: string;
  properties: ScalarPropertyConfig[];
  defaultPrecision?: number;
  project: Project;
  // Figure rendered prominently above the value tables for each workflow card,
  // mirroring how the Kaplan-Meier plot leads the survival results. Optional on
  // this base only because it is shared with figure-less scalar cards (T-Test,
  // Mean, Chi², StDev); the cards that have a figure always provide one.
  figure?: (ctx: {
    agentResults: any;
    aggregatedResults: any;
    agentLabel: string;
  }) => React.ReactNode;
  exportFigure?: (ctx: {
    agentResults: any;
    aggregatedResults: any;
    agentLabel: string;
  }) => Promise<Extract<ExportBlock, { kind: "image" }> | null>;
}

interface ScalarRow {
  label: string;
  displayValue: string;
}

function toNumeric(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function isPValueProp(prop: ScalarPropertyConfig): boolean {
  return prop.keys.includes("p_value");
}

function buildRows(
  source: any,
  properties: ScalarPropertyConfig[],
  defaultPrecision: number,
  variant: RowVariant = "aggregated"
): ScalarRow[] {
  if (!source || typeof source !== "object") return [];
  const rows: ScalarRow[] = [];

  for (const prop of properties) {
    let raw: unknown = undefined;

    for (const k of prop.keys) {
      if (source[k] !== undefined && source[k] !== null) {
        raw = source[k];
        break;
      }
    }

    if (raw === undefined || raw === null) continue;

    let valueStr: string;

    if (isPValueProp(prop)) {
      const formatted = formatPValueForUI(raw);
      valueStr = formatted ?? String(raw);
    } else {
      const num = toNumeric(raw);

      if (num !== null) {
        if (prop.exact) {
          valueStr = typeof raw === "string" ? raw : String(num);
        } else {
          const prec = prop.precision ?? defaultPrecision;
          valueStr = prec >= 0 ? num.toFixed(prec) : String(num);
        }
      } else {
        valueStr = String(raw);
      }

      if (prop.unitLabel) {
        valueStr = `${valueStr} ${prop.unitLabel}`;
      }
    }

    const label =
      variant === "agent" && prop.agentLabel ? prop.agentLabel : prop.label;

    rows.push({
      label,
      displayValue: valueStr,
    });
  }

  return rows;
}

function getAgentResults(jobData: any, userRole: UserRole) {
  const isClient = userRole === UserRole.CLIENT;

  const agentResults = isClient
    ? jobData?.local_results ?? jobData?.local?.local_results ?? null
    : jobData?.initiator_results ?? null;

  const agentProcessedResults = isClient
    ? jobData?.local_processed_results ??
      jobData?.local?.local_processed_results ??
      jobData?.local_results ??
      jobData?.local?.local_results ??
      null
    : jobData?.initiator_processed_results ?? jobData?.initiator_results ?? null;

  return { agentResults, agentProcessedResults };
}

function toExportId(title: string): string {
  const normalized = (title || "").trim().toLowerCase();
  if (normalized.includes("t-test")) return "result-function-t-test";
  if (normalized === "mean") return "result-function-mean";
  if (normalized.includes("chi")) return "result-function-chi-square-test";
  if (normalized.includes("standard deviation")) return "result-function-standard-deviation";
  const s = normalized.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `result-function-${s || "unknown"}`;
}

function formatConfigValue(value: any): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function buildFunctionConfigRows(functionConfig: any): (string | number)[][] {
  if (!functionConfig || typeof functionConfig !== "object") return [];
  return Object.entries(functionConfig)
    .filter(([, value]) => value !== null && value !== undefined && formatConfigValue(value) !== "")
    .map(([key, value]) => [key, formatConfigValue(value)]);
}

function defaultExportOrder(title: string): number {
  const t = (title || "").toLowerCase();
  if (t.includes("t-test")) return 20;
  if (t === "mean") return 21;
  if (t.includes("chi")) return 22;
  if (t.includes("standard deviation")) return 23;
  return 29;
}

const LABEL_COLUMN_WIDTH = 175;

const BaseScalarResultCard: React.FC<ResultCardProps> = ({
  title,
  workflowDisplayNamePrefix,
  workflows,
  activeIndex,
  onActiveIndexChange,
  properties,
  defaultPrecision = 3,
  analyticsWorkflows,
  project,
  userRole,
  figure,
  exportFigure,
}) => {
  const [selectedWorkflowIds, setSelectedWorkflowIds] = useState<string[]>([]);
  const hasWorkflows = !!workflows && workflows.length > 0;

  const exportSection = useCallback(async (): Promise<ExportSection | null> => {
    if (!hasWorkflows) return null;

    const agentLabel = userRole === UserRole.CLIENT ? "Client" : "Initiator";

    const exportWorkflows = await Promise.all(workflows.map(async (wf, idx) => {
      const workflowLabel = wf.workflowId || `Config ${idx + 1}`;
      const workflowDisplayName = formatWorkflowDisplayName(
        workflowLabel,
        workflowDisplayNamePrefix,
        idx + 1,
      );
      const jobData = (wf as any).jobData ?? (wf as any).results ?? {};
      const { agentResults } = getAgentResults(jobData, userRole);
      const aggregatedResults = jobData.aggregate_processed_results ?? null;
      const functionConfigRows = buildFunctionConfigRows((wf as any).functionConfig || (wf as any).function_config || null);

      const agentRows = buildRows(agentResults, properties, defaultPrecision, "agent");
      const aggregatedRows = buildRows(aggregatedResults, properties, defaultPrecision, "aggregated");
      const blocks: ExportBlock[] = [];

      if (exportFigure) {
        const exportedFigure = await exportFigure({
          agentResults,
          aggregatedResults,
          agentLabel,
        });

        if (exportedFigure) {
          blocks.push(exportedFigure);
        }
      }

      if (functionConfigRows.length) {
        blocks.push({ kind: "paragraph", text: "Function Configuration" });
        blocks.push({
          kind: "table",
          columns: ["Setting", "Value"],
          rows: functionConfigRows,
        });
      }

      const rowsOut: (string | number)[][] = [];
      if (agentRows.length) {
        agentRows.forEach((r) => rowsOut.push([agentLabel, r.label, r.displayValue]));
      } else {
        rowsOut.push([agentLabel, "Value", "N/A"]);
      }

      if (aggregatedRows.length) {
        aggregatedRows.forEach((r) => rowsOut.push(["Aggregated", r.label, r.displayValue]));
      } else {
        rowsOut.push(["Aggregated", "Value", "N/A"]);
      }

      blocks.push({
        kind: "table",
        columns: ["Source", "Metric", "Value"],
        rows: rowsOut,
      });

      const rawWorkflowError =
        (wf as any).workflowError ?? getWorkflowErrorFromJobData(jobData);
      const workflowWarning = getWorkflowWarning(
        rawWorkflowError,
        jobData,
        jobData?.aggregate_processed_results,
      );
      const workflowError = workflowWarning ? null : rawWorkflowError;
      if (workflowWarning) {
        blocks.push({ kind: "paragraph", text: `Workflow Warning: ${workflowWarning.message}` });
      } else if (workflowError) {
        const errText =
          typeof workflowError === "string"
            ? workflowError
            : JSON.stringify(workflowError);
        blocks.push({ kind: "paragraph", text: `Workflow Error: ${errText}` });
      }

      blocks.push(...buildWorkflowAnalyticsExportBlocks(workflowLabel, analyticsWorkflows, userRole));

      return {
        id: workflowLabel,
        title: workflowDisplayName,
        blocks,
        options: [{ id: "analytics_metrics", label: "Include analytics metrics", checkedByDefault: true }],
      };
    }));

    return { title, workflows: exportWorkflows };
  }, [hasWorkflows, workflows, userRole, properties, defaultPrecision, title, workflowDisplayNamePrefix, analyticsWorkflows, exportFigure]);

  useRegisterExportSection({
    id: toExportId(title),
    order: defaultExportOrder(title),
    title,
    exportSection,
  });

  const workflowOptions = useMemo(
    () =>
      workflows.map((wf, idx) => ({
        workflow: wf,
        index: idx,
        workflowKey: wf.workflowId || `Config ${idx + 1}`,
        displayName: formatWorkflowDisplayName(
          wf.workflowId || `Config ${idx + 1}`,
          workflowDisplayNamePrefix,
          idx + 1,
        ),
      })),
    [workflows, workflowDisplayNamePrefix],
  );

  const selectedWorkflowEntries = useMemo(
    () =>
      workflowOptions.filter((entry) =>
        selectedWorkflowIds.includes(entry.workflowKey),
      ),
    [workflowOptions, selectedWorkflowIds],
  );

  useEffect(() => {
    if (!hasWorkflows) {
      setSelectedWorkflowIds([]);
      return;
    }

    const availableIds = workflowOptions.map((entry) => entry.workflowKey);
    setSelectedWorkflowIds((prev) => {
      const filtered = prev.filter((id) => availableIds.includes(id));
      if (filtered.length > 0) {
        if (
          filtered.length === prev.length &&
          filtered.every((id, idx) => id === prev[idx])
        ) {
          return prev;
        }
        return filtered;
      }
      return availableIds;
    });
  }, [hasWorkflows, workflowOptions, workflows.length, activeIndex]);

  if (!hasWorkflows) {
    return null;
  }

  const agentLabel = userRole === UserRole.CLIENT ? "Client" : "Initiator";
  const allWorkflowIdsSelected = workflowOptions.every((entry) =>
    selectedWorkflowIds.includes(entry.workflowKey),
  );

  const selectedWorkflowCount = selectedWorkflowIds.length;
  const workflowSelectionRuleId = `${toExportId(title)}-workflow-selection-rule`;

  const handleWorkflowCheckboxChange = (
    workflowKey: string,
    index: number,
    checked: boolean,
  ) => {
    setSelectedWorkflowIds((prev) => {
      if (!checked && prev.includes(workflowKey) && prev.length <= 1) {
        return prev;
      }

      const next = checked
        ? prev.includes(workflowKey)
          ? prev
          : [...prev, workflowKey]
        : prev.filter((id) => id !== workflowKey);

      const ordered = workflowOptions
        .map((entry) => entry.workflowKey)
        .filter((id) => next.includes(id));

      const nextActiveId = ordered[0];
      const nextActiveIndex = workflowOptions.find(
        (entry) => entry.workflowKey === nextActiveId,
      )?.index;

      if (nextActiveIndex !== undefined) {
        onActiveIndexChange(nextActiveIndex);
      } else if (checked) {
        onActiveIndexChange(index);
      }

      return ordered;
    });
  };

  const handleSelectAllWorkflowIds = () => {
    setSelectedWorkflowIds(workflowOptions.map((entry) => entry.workflowKey));
    if (workflowOptions.length > 0) {
      onActiveIndexChange(workflowOptions[0].index);
    }
  };

  const selectedEntryCount = selectedWorkflowEntries.length;

  return (
    <section
      className="scalar-result-card-section result-card-block-01"
    >
      <style>
        {`
          .scalar-result-card-section {
            container-type: inline-size;
          }

          .scalar-workflow-card-grid {
            display: grid;
            gap: 0.75rem;
            align-items: stretch;
            grid-template-columns: minmax(0, 1fr);
          }

          .scalar-workflow-card {
            min-width: 0;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            padding: 0.75rem;
            background: #fff;
            container-type: inline-size;
          }

          .scalar-result-table-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: 0.55rem 0.75rem;
            align-items: start;
            padding-bottom: 0.9rem;
          }

          @container (min-width: 560px) {
            .scalar-result-table-grid-2 {
              grid-template-columns: repeat(2, minmax(0, 1fr));
            }
          }

          .scalar-workflow-card-single {
            border: 0;
            padding: 0;
          }

          @container (min-width: 640px) {
            .scalar-workflow-card-grid-2,
            .scalar-workflow-card-grid-3 {
              grid-template-columns: repeat(2, minmax(0, 1fr));
            }
          }

          @container (min-width: 960px) {
            .scalar-workflow-card-grid-3 {
              grid-template-columns: repeat(3, minmax(0, 1fr));
            }
          }
        `}
      </style>

      <h3
        className="result-card-h3"
      >
        {title}
      </h3>

      <div
        className="duality-pb-0p75rem"
      >
        <div
          className="duality-d-flex-wrap-wrap-gap-0p55rem-1rem"
        >
          Workflows:
          {workflowOptions.map((entry) => {
              const isSelected = selectedWorkflowIds.includes(entry.workflowKey);
              const isRequiredSelection = isSelected && selectedWorkflowCount <= 1;

              return (
                <label
                  key={entry.workflowKey}
                  title={isRequiredSelection ? "At least one workflow must remain selected" : undefined}
                  className="result-card-block-02"
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    ref={(input) => {
                      if (input) {
                        input.defaultChecked = isSelected;
                      }
                    }}
                    aria-label={`${entry.displayName} workflow selection`}
                    aria-describedby={workflowSelectionRuleId}
                    onClick={(e) => {
                      if (isRequiredSelection) {
                        e.preventDefault();
                      }
                    }}
                    onChange={(e) =>
                      handleWorkflowCheckboxChange(
                        entry.workflowKey,
                        entry.index,
                        e.target.checked,
                      )
                    }
                  />
                  <span>{entry.displayName}</span>
                </label>
              );
            })}
          {!allWorkflowIdsSelected && (
            <button
              type="button"
              className="button-href result-card-block-03"
              onClick={handleSelectAllWorkflowIds}
            >
              Select All
            </button>
          )}
        </div>
      </div>

      {selectedWorkflowEntries.length === 0 ? (
        <div
          className="result-card-shared-01"
        >
          <div
            className="duality-text-666"
          >
            Select at least one workflow to view results.
          </div>
        </div>
      ) : (
        <div
          className={`scalar-workflow-card-grid scalar-workflow-card-grid-${Math.min(
            selectedWorkflowEntries.length,
            3,
          )}`}
        >
          {selectedWorkflowEntries.map((entry) => {
            const activeWorkflow = entry.workflow;
            const index = entry.index;
            const jobData = (activeWorkflow as any).jobData ?? (activeWorkflow as any).results ?? {};
            const rawWorkflowError =
              (activeWorkflow as any).workflowError ?? getWorkflowErrorFromJobData(jobData);
            const workflowWarning = getWorkflowWarning(
              rawWorkflowError,
              jobData,
              jobData?.aggregate_processed_results,
            );
            const workflowError = workflowWarning ? null : rawWorkflowError;
            const { agentResults } = getAgentResults(jobData, userRole);
            const aggregatedResults = jobData.aggregate_processed_results ?? null;

            const agentRows = buildRows(agentResults, properties, defaultPrecision, "agent");
            const aggregatedRows = buildRows(aggregatedResults, properties, defaultPrecision, "aggregated");

            const hasAgent = agentRows.length > 0;
            const hasAggregated = aggregatedRows.length > 0;
            const hasAnyValue = hasAgent || hasAggregated;

            const functionConfig =
              (activeWorkflow as any).function_config || (activeWorkflow as any).functionConfig;
            const activeWorkflowId = activeWorkflow.workflowId;

            return (
              <div
                key={activeWorkflowId || entry.workflowKey || index}
                className={`scalar-workflow-card${
                  selectedEntryCount === 1 ? " scalar-workflow-card-single" : ""
                }`}
              >
                {selectedEntryCount > 1 && (
                  <div
                    className="result-card-block-04"
                  >
                    {entry.displayName}
                  </div>
                )}

                {functionConfig && typeof functionConfig === "object" && (
                  <div
                    className="result-card-block-05"
                  >
                    <FunctionConfigurationAccordion
                      key={activeWorkflow.workflowId || index}
                      config={functionConfig}
                      project={project}
                    />
                  </div>
                )}

                {workflowWarning && (
                  <WorkflowErrorPanel
                    error={workflowWarning}
                    variant="warning"
                    defaultExpanded={false}
                    showTracebackToggle={false}
                  />
                )}

                {workflowError && (
                  <WorkflowErrorPanel
                    error={workflowError}
                    variant="error"
                    defaultExpanded={false}
                    showTracebackToggle={true}
                  />
                )}

                {figure && (
                  <div className="duality-mb-1">
                    {figure({ agentResults, aggregatedResults, agentLabel })}
                  </div>
                )}

                {hasAnyValue ? (
                  <div
                    className={[`scalar-result-table-grid${
                      hasAgent && hasAggregated ? " scalar-result-table-grid-2" : ""
                    }`, "result-card-block-06"].filter(Boolean).join(" ")}
                    
                  >
                    {hasAgent && (
                      <div>
                        <div
                          className="result-card-block-07"
                        >
                          {agentLabel}
                        </div>
                        <table
                          className="result-card-shared-02"
                        >
                          <tbody>
                            {agentRows.map((row) => (
                              <tr key={row.label}>
                                <td
                                  className="result-card-shared-03" style={{ width: LABEL_COLUMN_WIDTH }}
                                >
                                  {row.label}
                                </td>
                                <td
                                  className="result-card-block-08"
                                >
                                  {row.displayValue}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {hasAggregated && (
                      <div>
                        <div
                          className="result-card-block-09"
                        >
                          Aggregated
                        </div>
                        <table
                          className="result-card-shared-02"
                        >
                          <tbody>
                            {aggregatedRows.map((row) => (
                              <tr key={row.label}>
                                <td
                                  className="result-card-shared-03" style={{ width: LABEL_COLUMN_WIDTH }}
                                >
                                  {row.label}
                                </td>
                                <td
                                  className="result-card-block-10"
                                >
                                  {row.displayValue}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ) : (
                  <div
                    className="result-card-shared-01"
                  >
                    <div
                      className="duality-text-666" style={{ width: LABEL_COLUMN_WIDTH }}
                    >
                      Value
                    </div>
                    <div
                      className="result-card-block-11"
                    >
                      <span
                        className="result-card-block-12"
                      >
                        N/A
                      </span>
                    </div>
                  </div>
                )}

                {analyticsWorkflows && activeWorkflowId && (
                  <WorkflowAnalyticsAccordion
                    workflowId={activeWorkflowId}
                    workflows={analyticsWorkflows}
                    role={userRole}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export const TTestResultCard: React.FC<ScalarResultWorkflowProps> = (props) => {
  const TTEST_PROPERTIES: ScalarPropertyConfig[] = [
    { keys: ["t_score"], label: "T-Score", precision: 4 },
    { keys: ["dof"], label: "Degrees of Freedom", precision: 3 },
    { keys: ["p_value"], label: "T-Test", exact: true },
  ];

  return (
    <BaseScalarResultCard
      title="T-Test"
      workflowDisplayNamePrefix="T-Test"
      properties={TTEST_PROPERTIES}
      defaultPrecision={3}
      {...props}
    />
  );
};

export const MeanResultCard: React.FC<ScalarResultWorkflowProps> = (props) => {
  const MEAN_PROPERTIES: ScalarPropertyConfig[] = [
    { keys: ["mean"], label: "Mean", precision: 3 },
  ];

  return (
    <BaseScalarResultCard
      title="Mean"
      workflowDisplayNamePrefix="Mean"
      properties={MEAN_PROPERTIES}
      defaultPrecision={3}
      {...props}
    />
  );
};

export const Chi2ResultCard: React.FC<ScalarResultWorkflowProps> = (props) => {
  const CHI2_PROPERTIES: ScalarPropertyConfig[] = [
    { keys: ["chi2"], label: "Chi-Square Value", precision: 3 },
    { keys: ["p_value"], label: "Chi-Square Test", exact: true },
  ];

  return (
    <BaseScalarResultCard
      title="Chi Square Test"
      workflowDisplayNamePrefix="Chi Square Test"
      properties={CHI2_PROPERTIES}
      defaultPrecision={3}
      {...props}
    />
  );
};

export const StDevResultCard: React.FC<ScalarResultWorkflowProps> = (props) => {
  const STDEV_PROPERTIES: ScalarPropertyConfig[] = [
    { keys: ["stdev"], label: "Standard Deviation", precision: 3 },
  ];

  return (
    <BaseScalarResultCard
      title="Standard Deviation"
      workflowDisplayNamePrefix="Standard Deviation"
      properties={STDEV_PROPERTIES}
      defaultPrecision={3}
      {...props}
    />
  );
};

export const LogisticCalibrationResultCard: React.FC<ScalarResultWorkflowProps> = (props) => {
  // Fixed-effects inverse-variance meta-analysis of the per-client logistic
  // calibration slope β₁. ``meta_beta1`` is the pooled effect size,
  // ``ci_lower``/``ci_upper`` bracket it at 95%, and ``p_value`` is the
  // standard normal two-sided test for β₁ = 0. The Aggregated panel shows the
  // pooled values; the Initiator panel shows this site's local fit (agentLabel).
  const LOG_CALIBRATION_PROPERTIES: ScalarPropertyConfig[] = [
    { keys: ["meta_beta1"], label: "Pooled β₁", agentLabel: "Local β₁", precision: 4 },
    { keys: ["meta_se_beta1"], label: "Pooled SE(β₁)", agentLabel: "Local SE(β₁)", precision: 4 },
    { keys: ["z"], label: "Pooled z", agentLabel: "Local z", precision: 4 },
    { keys: ["p_value"], label: "Pooled p-value", agentLabel: "Local p-value", precision: 4 },
    { keys: ["ci_lower"], label: "95% CI lower", precision: 4 },
    { keys: ["ci_upper"], label: "95% CI upper", precision: 4 },
  ];

  return (
    <BaseScalarResultCard
      title="Exceptional Response Discrimination"
      workflowDisplayNamePrefix="Exceptional Response Discrimination"
      properties={LOG_CALIBRATION_PROPERTIES}
      defaultPrecision={3}
      figure={({ agentResults, aggregatedResults }) => (
        <OddsRatioLollipopPlot
          agentResults={agentResults}
          aggregatedResults={aggregatedResults}
          userRole={props.userRole}
        />
      )}
      exportFigure={async ({ agentResults, aggregatedResults, agentLabel }) => {
        const exportedPlot = await createOddsRatioLollipopPlotPng(
          agentResults,
          aggregatedResults,
          agentLabel
        );

        if (!exportedPlot) {
          return null;
        }

        return {
          kind: "image",
          dataUrl: exportedPlot.dataUrl,
          width: exportedPlot.width,
          height: exportedPlot.height,
          caption: "Odds Ratio (exp(β₁)) with 95% confidence intervals",
        };
      }}
      {...props}
    />
  );
};
