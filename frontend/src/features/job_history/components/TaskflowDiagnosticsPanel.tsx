import React from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import {
  getTaskflowArtifactUrl,
  TaskflowArtifact,
  TaskflowDiagnosticsResponse,
  TaskflowRoundMetrics,
} from "../utils/JobsDataUtils";

interface TaskflowDiagnosticsPanelProps {
  diagnostics: TaskflowDiagnosticsResponse;
  nvflareJobId: string;
}


function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString();
}

function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(3)} s`;
}

function artifactExists(artifacts: TaskflowArtifact[] | undefined, filename: string): boolean {
  return Boolean(artifacts?.some((artifact) => artifact.filename === filename));
}

const summaryLabelStyle: React.CSSProperties = {
  fontSize: "0.78rem",
  color: "#4b5563",
};

const summaryValueStyle: React.CSSProperties = {
  fontSize: "0.9rem",
  fontWeight: 600,
  color: "#111827",
  overflowWrap: "anywhere",
};

const summaryGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: "0.5rem 1rem",
};

const topLevelBodyStyle: React.CSSProperties = {
  borderRadius: 4,
  border: "1px solid #ccc",
  padding: "0.6rem 0.75rem 0.75rem 0.75rem",
  marginTop: "4px",
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
  backgroundColor: "white",
  maxWidth: "100%",
};

const nestedBodyStyle: React.CSSProperties = {
  borderRadius: 4,
  border: "1px solid #e5e7eb",
  padding: "0.6rem",
  marginTop: "4px",
  backgroundColor: "#fff",
  maxWidth: "100%",
};

const TaskflowDiagnosticsPanel: React.FC<TaskflowDiagnosticsPanelProps> = ({
  diagnostics,
  nvflareJobId,
}) => {
  const summary = diagnostics.summary;
  const rounds = diagnostics.rounds || [];
  const artifacts = diagnostics.artifacts || [];
  const timelineAvailable = artifactExists(artifacts, "taskflow.timeline.svg");
  const [timelineScale, setTimelineScale] = React.useState<number>(100);
  const progressPercent = Math.max(0, Math.min(100, Math.round(diagnostics.status.progress ?? 0)));
  const isPending = ["idle", "queued", "running"].includes(diagnostics.status.state);
  const artifactUrl = (filename: string) => getTaskflowArtifactUrl(nvflareJobId, filename);

  if (isPending) {
    return (
      <section className="taskflow-diagnostics-panel-shared-01">
        <div className="taskflow-diagnostics-panel-shared-02">
          Taskflow Diagnostics
        </div>
        <div style={topLevelBodyStyle}>
          <div
            className="duality-d-flex-justify-space-between-align-center"
          >
            <span>{diagnostics.status.label || "Preparing Taskflow Diagnostics"}</span>
            <span>{progressPercent}%</span>
          </div>
          <div
            className="duality-h-0p75rem-w-100pct-bg-e5e7eb"
          >
            <div
              className="duality-h-100pct-bg-2563eb-transition-width-160ms-ease-i" style={{ width: `${progressPercent}%` }}
            />
          </div>
          <div className="duality-mt-0p35rem-fs-10pt-text-4b5563">
            Your workflow results are ready and can be reviewed while this section finishes rendering.
          </div>
        </div>
      </section>
    );
  }

  if (diagnostics.status.state === "unavailable") {
    return (
      <section className="taskflow-diagnostics-panel-shared-01">
        <div className="taskflow-diagnostics-panel-shared-02">
          Taskflow Diagnostics
        </div>
        <div style={topLevelBodyStyle}>
          <div className="taskflow-diagnostics-panel-block-01">
            {diagnostics.status.label}. The statistical workflow results above are unaffected.
          </div>
        </div>
      </section>
    );
  }

  if (diagnostics.status.state === "failed") {
    return (
      <section className="taskflow-diagnostics-panel-shared-01">
        <div className="taskflow-diagnostics-panel-shared-02">
          Taskflow Diagnostics
        </div>
        <div style={topLevelBodyStyle}>
          <div className="taskflow-diagnostics-panel-block-02">
            {diagnostics.status.error || diagnostics.status.label}
          </div>
        </div>
      </section>
    );
  }

  if (diagnostics.status.state !== "complete" || !summary) {
    return null;
  }

  return (
    <AbstractAccordion
      defaultOpen={false}
      as="section"
      title="Taskflow Diagnostics"
      titleTooltip="Show/Hide Taskflow Diagnostics"
      containerStyle={{ maxWidth: "100%" }}
      bodyStyle={topLevelBodyStyle}
    >
      <>
            <div style={summaryGridStyle}>
              <div>
                <div style={summaryLabelStyle}>Parties</div>
                <div style={summaryValueStyle}>{formatNumber(summary.parties?.length ?? summary.lanes)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Trace Events</div>
                <div style={summaryValueStyle}>{formatNumber(summary.events)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Execution Spans</div>
                <div style={summaryValueStyle}>{formatNumber(summary.spans)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Messages</div>
                <div style={summaryValueStyle}>{formatNumber(summary.edges)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Federated Rounds</div>
                <div style={summaryValueStyle}>{formatNumber(summary.rounds)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Causal Depth</div>
                <div style={summaryValueStyle}>{formatNumber(summary.lamport_depth)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Total Straggler Wait</div>
                <div style={summaryValueStyle}>{formatSeconds(summary.straggler_wait_total_sec)}</div>
              </div>
              <div>
                <div style={summaryLabelStyle}>Max Round Straggler</div>
                <div style={summaryValueStyle}>{formatSeconds(summary.straggler_wait_max_sec)}</div>
              </div>
            </div>

            <div
              style={{
                ...summaryGridStyle,
                marginTop: "0.75rem",
                paddingTop: "0.5rem",
                borderTop: "1px solid #e5e7eb",
              }}
            >
              {summary.parties && summary.parties.length > 0 && (
                <div>
                  <div style={summaryLabelStyle}>Party Names</div>
                  <div style={summaryValueStyle}>{summary.parties.join(", ")}</div>
                </div>
              )}
              <div>
                <div style={summaryLabelStyle}>Message Correlation</div>
                <div style={summaryValueStyle}>
                  {formatNumber(summary.edges_by_id)} by ID / {formatNumber(summary.edges_fallback)} fallback
                </div>
              </div>
              {summary.acyclic !== undefined && (
                <div>
                  <div style={summaryLabelStyle}>Causal Graph</div>
                  <div style={summaryValueStyle}>{summary.acyclic ? "Acyclic" : "Cycle detected"}</div>
                </div>
              )}
            </div>

            {timelineAvailable && (
              <AbstractAccordion
                defaultOpen={true}
                as="section"
                title="Taskflow Timeline"
                titleTooltip="Show/Hide Taskflow Timeline"
                containerStyle={{ maxWidth: "100%", marginTop: "1rem" }}
                bodyStyle={nestedBodyStyle}
              >
                <>
                  <div
                    className="taskflow-diagnostics-panel-block-03"
                  >
                    <img
                      src={artifactUrl("taskflow.timeline.svg")}
                      alt="Federated taskflow timeline"
                      className="taskflow-diagnostics-panel-federated-taskflow-timeline" style={{ width: `${timelineScale}%`, maxWidth: 1280 * (timelineScale / 100) }}
                    />
                  </div>
                  <div
                    className="taskflow-diagnostics-panel-block-04"
                  >
                    <div className="taskflow-diagnostics-panel-block-05">
                      <label htmlFor="taskflow-timeline-scale" className="taskflow-diagnostics-panel-taskflow-timeline-scale-label">
                        Scale
                      </label>
                      <select
                        id="taskflow-timeline-scale"
                        value={timelineScale}
                        onChange={(event) => setTimelineScale(Number(event.target.value))}
                        aria-label="Taskflow timeline scale"
                        className="taskflow-diagnostics-panel-taskflow-timeline-scale"
                      >
                        {[25, 50, 75, 100].map((scale) => (
                          <option key={scale} value={scale}>
                            {scale}%
                          </option>
                        ))}
                      </select>
                    </div>
                    <a href={artifactUrl("taskflow.timeline.svg")} target="_blank" rel="noreferrer">
                      Open full timeline
                    </a>
                  </div>
                </>
              </AbstractAccordion>
            )}

            {rounds.length > 0 && (
              <AbstractAccordion
                defaultOpen={true}
                as="section"
                title="Per-Round Timing"
                titleTooltip="Show/Hide Per-Round Timing"
                containerStyle={{ maxWidth: "100%", marginTop: "1rem" }}
                bodyStyle={{ ...nestedBodyStyle, padding: 0 }}
              >
                <div className="duality-overflow-x-auto">
                  <table className="taskflow-diagnostics-panel-block-06">
                    <thead>
                      <tr className="taskflow-diagnostics-panel-tr">
                        <th className="taskflow-diagnostics-panel-shared-03">Workflow</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Round</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Contributors</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Compute Max</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Slowest Client</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Straggler Gap</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Wait Max</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Fetch Max</th>
                        <th className="taskflow-diagnostics-panel-shared-03">Send Max</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rounds.map((round: TaskflowRoundMetrics, index: number) => (
                        <tr key={`${round.workflow || "workflow"}-${round.round ?? index}-${index}`} className="taskflow-diagnostics-panel-tr-6755d">
                          <td className="taskflow-diagnostics-panel-block-07">{round.workflow || "—"}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{round.round ?? "—"}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{formatNumber(round.contributions)}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{formatSeconds(round.compute_sec?.max)}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{round.compute_sec?.slowest_client || "—"}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{formatSeconds(round.straggler_gap_sec)}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{formatSeconds(round.wait_sec?.max)}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{formatSeconds(round.fetch_sec?.max)}</td>
                          <td className="taskflow-diagnostics-panel-shared-03">{formatSeconds(round.send_sec?.max)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </AbstractAccordion>
            )}

      </>
    </AbstractAccordion>
  );
};

export default TaskflowDiagnosticsPanel;
