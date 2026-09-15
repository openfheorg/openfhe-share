import React, { useCallback, useMemo } from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { UserRole } from "../../../context/UserRoleContext";
import {
  CombinedWorkflowMetrics,
  ProfileSummarySystemMetrics,
  ProfileSummaryWorkflows,
} from "../utils/JobsDataUtils";
import { ExportBlock, ExportKeyValue, ExportSection } from "../utils/ExportDocTypes";
import { useRegisterExportSection } from "./export/useRegisterExportSection";

type SystemMetricsPanelProps = {
  metrics: ProfileSummarySystemMetrics | null | undefined;
  combinedMetrics?: CombinedWorkflowMetrics | null | undefined;
  runDurationTime?: string;
  role: UserRole;
};

const smLabelStyle: React.CSSProperties = {
  fontSize: "0.78rem",
  color: "#4b5563",
};

const smValueStyle: React.CSSProperties = {
  fontSize: "0.9rem",
  fontWeight: 600,
  color: "#111827",
};

function parseRunDurationToSeconds(s?: string): number {
  try {
    if (!s) return 0;
    const parts = s.split(":");
    if (parts.length !== 3) return 0;
    const [h, m, secStr] = parts;
    const sec = parseFloat(secStr);
    if (Number.isNaN(sec)) return 0;
    const hours = Number(h) || 0;
    const minutes = Number(m) || 0;
    return hours * 3600 + minutes * 60 + sec;
  } catch {
    return 0;
  }
}

function isNumber(x: any): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

function formatMinFixed4(value: number): string {
  if (!Number.isFinite(value)) return "0.0001";
  if (value === 0) return "0.0001";
  const adjusted = Math.abs(value) < 0.0001 ? (value < 0 ? -0.0001 : 0.0001) : value;
  return adjusted.toFixed(4);
}

function isServerCombinedMetrics(x: any): boolean {
  return (
    !!x &&
    typeof x === "object" &&
    (isNumber((x as any).server_compute_time_sec) ||
      isNumber((x as any).server_aggregation_time_sec) ||
      isNumber((x as any).server_dispatch_time_sec) ||
      isNumber((x as any).payload_in_bytes) ||
      isNumber((x as any).payload_out_bytes))
  );
}

function isClientCombinedMetrics(x: any): boolean {
  return (
    !!x &&
    typeof x === "object" &&
    (isNumber((x as any).client_compute_time_sec) ||
      isNumber((x as any).upstream_rtt_sec) ||
      isNumber((x as any).downstream_rtt_sec))
  );
}

const SystemMetricsAccordion: React.FC<SystemMetricsPanelProps> = ({
  metrics,
  combinedMetrics,
  runDurationTime,
  role,
}) => {
  const m = metrics || null;
  const c: any = combinedMetrics || null;

  const hasAnyData = !!m || !!c;

  const runDurationSec = parseRunDurationToSeconds(runDurationTime);

  const computeTimeSec = useMemo(() => {
    if (!c) return 0;

    if (isServerCombinedMetrics(c)) {
      const serverCompute = isNumber(c.server_compute_time_sec) ? c.server_compute_time_sec : 0;
      const serverAgg = isNumber(c.server_aggregation_time_sec) ? c.server_aggregation_time_sec : 0;
      return serverCompute + serverAgg;
    }

    if (isClientCombinedMetrics(c)) {
      const clientCompute = isNumber(c.client_compute_time_sec) ? c.client_compute_time_sec : 0;
      const up = isNumber(c.upstream_rtt_sec) ? c.upstream_rtt_sec : 0;
      const down = isNumber(c.downstream_rtt_sec) ? c.downstream_rtt_sec : 0;
      return clientCompute + up + down;
    }

    return 0;
  }, [c]);

  const computePctOfRun =
    runDurationSec > 0 && computeTimeSec > 0 ? (computeTimeSec / runDurationSec) * 100 : 0;

  const showCombined = !!c && role !== UserRole.CLIENT;

  const exportSection = useCallback(async (): Promise<ExportSection | null> => {
    if (!hasAnyData) return null;

    const blocks: any[] = [];
    const kv: ExportKeyValue[] = [];

    if (m) {
      kv.push(
        { label: "Wall time (sec)", value: formatMinFixed4(m.wall_time_sec) },
        { label: "CPU util (%)", value: formatMinFixed4(m.cpu_util_pct) },
        { label: "CPU user (%)", value: formatMinFixed4(m.cpu_user_pct) },
        { label: "CPU system (%)", value: formatMinFixed4(m.cpu_system_pct) },
        { label: "CPU iowait (%)", value: formatMinFixed4(m.cpu_iowait_pct) },
        {
          label: "Network TX (KB)",
          value: (m.net_tx_bytes_total / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }),
        },
        {
          label: "Network RX (KB)",
          value: (m.net_rx_bytes_total / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }),
        },
        { label: "Network TX (MB/s)", value: formatMinFixed4(m.net_tx_mb_s) },
        { label: "Network RX (MB/s)", value: formatMinFixed4(m.net_rx_mb_s) },
        { label: "RSS max (KB)", value: m.rss_max_kb.toLocaleString() }
      );
    }

    if (kv.length) {
      blocks.push({ kind: "keyValues", items: kv });
    }

    if (showCombined) {
      const combinedKvs: ExportKeyValue[] = [];

      if (isServerCombinedMetrics(c)) {
        combinedKvs.push(
          {
            label: "Dispatch time (sec, total)",
            value: formatMinFixed4(isNumber(c.server_dispatch_time_sec) ? c.server_dispatch_time_sec : 0),
          },
          {
            label: "Accept time (sec, total)",
            value: formatMinFixed4(isNumber(c.server_accept_time_sec) ? c.server_accept_time_sec : 0),
          },
          {
            label: "Aggregation time (sec, total)",
            value: formatMinFixed4(isNumber(c.server_aggregation_time_sec) ? c.server_aggregation_time_sec : 0),
          },
          {
            label: "Compute time (sec, total)",
            value: formatMinFixed4(isNumber(c.server_compute_time_sec) ? c.server_compute_time_sec : 0),
          },
          {
            label: "Payload in (KB, total)",
            value: ((isNumber(c.payload_in_bytes) ? c.payload_in_bytes : 0) / 1000).toLocaleString(undefined, {
              maximumFractionDigits: 1,
            }),
          },
          {
            label: "Payload out (KB, total)",
            value: ((isNumber(c.payload_out_bytes) ? c.payload_out_bytes : 0) / 1000).toLocaleString(undefined, {
              maximumFractionDigits: 1,
            }),
          }
        );
      } else if (isClientCombinedMetrics(c)) {
        combinedKvs.push(
          {
            label: "Client compute (sec, total)",
            value: formatMinFixed4(isNumber(c.client_compute_time_sec) ? c.client_compute_time_sec : 0),
          },
          {
            label: "Upstream RTT (sec, total)",
            value: formatMinFixed4(isNumber(c.upstream_rtt_sec) ? c.upstream_rtt_sec : 0),
          },
          {
            label: "Downstream RTT (sec, total)",
            value: formatMinFixed4(isNumber(c.downstream_rtt_sec) ? c.downstream_rtt_sec : 0),
          }
        );
      }

      if (combinedKvs.length) {
        blocks.push({ kind: "spacer", mm: 4 });
        blocks.push({ kind: "paragraph", text: "Combined Workflow Metrics (Includes KeyGen and Threshold workflows)" });
        blocks.push({ kind: "keyValues", items: combinedKvs });
      }

      if (runDurationSec > 0 && computeTimeSec > 0) {
        const rtKvs: ExportKeyValue[] = [
          { label: "Total runtime (sec)", value: formatMinFixed4(runDurationSec) },
          {
            label: isServerCombinedMetrics(c)
              ? "Compute + aggregation (sec, total)"
              : "Compute + RTT (sec, total)",
            value: formatMinFixed4(computeTimeSec),
          },
          {
            label: isServerCombinedMetrics(c)
              ? "Compute + aggregation vs runtime (%)"
              : "Compute + RTT vs runtime (%)",
            value: `${formatMinFixed4(computePctOfRun)}%`,
          },
        ];

        blocks.push({ kind: "spacer", mm: 4 });
        blocks.push({
          kind: "paragraph",
          text: `Runtime Comparison (${isServerCombinedMetrics(c) ? "compute + aggregation" : "compute + RTT"})`,
        });
        blocks.push({ kind: "keyValues", items: rtKvs });
      }
    }

    return { title: "System Metrics", blocks };
  }, [hasAnyData, m, c, showCombined, runDurationSec, computeTimeSec, computePctOfRun]);

  useRegisterExportSection({
    id: "system-metrics",
    order: 30,
    title: "System Metrics",
    exportSection,
  });

  if (!hasAnyData) {
    return null;
  }

  return (
    <AbstractAccordion
      defaultOpen={true}
      as="section"
      title="System Metrics"
      titleTooltip="Show/Hide System Metrics"
      containerStyle={{ maxWidth: "100%" }}
      bodyStyle={{
        borderRadius: 4,
        border: "1px solid #ccc",
        padding: "0.6rem 0.75rem 0.75rem 0.75rem",
        marginTop: "4px",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
        backgroundColor: "white",
        maxWidth: "100%",
      }}
    >
      <>
        {m && (
          <div
            className="analytics-metrics-accordion-block-01"
          >
            <div>
              <div style={smLabelStyle}>Wall time (sec)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.wall_time_sec)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>CPU util (%)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.cpu_util_pct)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>CPU user (%)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.cpu_user_pct)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>CPU system (%)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.cpu_system_pct)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>CPU iowait (%)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.cpu_iowait_pct)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>Network TX (KB)</div>
              <div style={smValueStyle}>
                {(m.net_tx_bytes_total / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}
              </div>
            </div>
            <div>
              <div style={smLabelStyle}>Network RX (KB)</div>
              <div style={smValueStyle}>
                {(m.net_rx_bytes_total / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}
              </div>
            </div>
            <div>
              <div style={smLabelStyle}>Network TX (MB/s)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.net_tx_mb_s)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>Network RX (MB/s)</div>
              <div style={smValueStyle}>{formatMinFixed4(m.net_rx_mb_s)}</div>
            </div>
            <div>
              <div style={smLabelStyle}>RSS max (KB)</div>
              <div style={smValueStyle}>{m.rss_max_kb.toLocaleString()}</div>
            </div>
          </div>
        )}

        {showCombined && (
          <div
            className="analytics-metrics-accordion-shared-01"
          >
            <div className="analytics-metrics-accordion-shared-02">
              Combined Workflow Metrics (Includes KeyGen and Threshold workflows)
            </div>

            {isServerCombinedMetrics(c) ? (
              <div
                className="analytics-metrics-accordion-shared-03"
              >
                <div>
                  <div style={smLabelStyle}>Dispatch time (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.server_dispatch_time_sec) ? c.server_dispatch_time_sec : 0)}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Accept time (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.server_accept_time_sec) ? c.server_accept_time_sec : 0)}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Aggregation time (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.server_aggregation_time_sec) ? c.server_aggregation_time_sec : 0)}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Compute time (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.server_compute_time_sec) ? c.server_compute_time_sec : 0)}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Payload in (KB, total)</div>
                  <div style={smValueStyle}>
                    {((isNumber(c.payload_in_bytes) ? c.payload_in_bytes : 0) / 1000).toLocaleString(undefined, {
                      maximumFractionDigits: 1,
                    })}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Payload out (KB, total)</div>
                  <div style={smValueStyle}>
                    {((isNumber(c.payload_out_bytes) ? c.payload_out_bytes : 0) / 1000).toLocaleString(undefined, {
                      maximumFractionDigits: 1,
                    })}
                  </div>
                </div>
              </div>
            ) : isClientCombinedMetrics(c) ? (
              <div
                className="analytics-metrics-accordion-shared-03"
              >
                <div>
                  <div style={smLabelStyle}>Client compute (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.client_compute_time_sec) ? c.client_compute_time_sec : 0)}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Upstream RTT (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.upstream_rtt_sec) ? c.upstream_rtt_sec : 0)}
                  </div>
                </div>
                <div>
                  <div style={smLabelStyle}>Downstream RTT (sec, total)</div>
                  <div style={smValueStyle}>
                    {formatMinFixed4(isNumber(c.downstream_rtt_sec) ? c.downstream_rtt_sec : 0)}
                  </div>
                </div>
              </div>
            ) : (
              <div className="analytics-metrics-accordion-shared-04">No combined metrics available for this role.</div>
            )}

            {runDurationSec > 0 && computeTimeSec > 0 && (
              <div className="analytics-metrics-accordion-shared-01">
                <div className="analytics-metrics-accordion-shared-02">
                  Runtime Comparison ({isServerCombinedMetrics(c) ? "compute + aggregation" : "compute + RTT"})
                </div>

                <div
                  className="analytics-metrics-accordion-shared-03"
                >
                  <div>
                    <div style={smLabelStyle}>Total runtime (sec)</div>
                    <div style={smValueStyle}>{formatMinFixed4(runDurationSec)}</div>
                  </div>
                  <div>
                    <div style={smLabelStyle}>
                      {isServerCombinedMetrics(c) ? "Compute + aggregation (sec, total)" : "Compute + RTT (sec, total)"}
                    </div>
                    <div style={smValueStyle}>{formatMinFixed4(computeTimeSec)}</div>
                  </div>
                  <div>
                    <div style={smLabelStyle}>
                      {isServerCombinedMetrics(c)
                        ? "Compute + aggregation vs runtime (%)"
                        : "Compute + RTT vs runtime (%)"}
                    </div>
                    <div style={smValueStyle}>{formatMinFixed4(computePctOfRun)}%</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </>
    </AbstractAccordion>
  );
};

type WorkflowAnalyticsAccordionProps = {
  workflowId?: string;
  workflows?: ProfileSummaryWorkflows | null;
  role: UserRole;
};

const labelStyle: React.CSSProperties = {
  fontSize: "0.75rem",
  color: "#4b5563",
};

const valueStyle: React.CSSProperties = {
  fontSize: "0.82rem",
  fontWeight: 600,
  color: "#111827",
};

function isServerRoundMetrics(x: any): boolean {
  return (
    !!x &&
    typeof x === "object" &&
    (isNumber(x.server_dispatch_time_sec) ||
      isNumber(x.server_aggregation_time_sec) ||
      isNumber(x.server_compute_time_sec) ||
      isNumber(x.payload_in_bytes) ||
      isNumber(x.payload_out_bytes))
  );
}

function isClientRoundMetrics(x: any): boolean {
  return (
    !!x &&
    typeof x === "object" &&
    (isNumber(x.client_compute_time_sec) || isNumber(x.upstream_rtt_sec) || isNumber(x.downstream_rtt_sec))
  );
}

export function buildWorkflowAnalyticsExportBlocks(
  workflowId: string | undefined,
  workflows: ProfileSummaryWorkflows | null | undefined,
  role: UserRole
): ExportBlock[] {
  if (!workflowId || !workflows) return [];

  const wfMetrics = workflows[workflowId] || null;
  if (!wfMetrics) return [];

  const rounds = Object.entries(wfMetrics).sort(([a], [b]) => Number(a) - Number(b));
  if (!rounds.length) return [];

  const hasAnyServer = rounds.some(([, m]) => isServerRoundMetrics(m));
  const titleText = role === UserRole.CLIENT ? "Client Analytics Metrics" : "Analytics Metrics";
  const rowsOut: (string | number)[][] = [];

  rounds.forEach(([roundKey, metrics]) => {
    const m: any = metrics || {};
    const roundTitle = roundKey === "-1" ? "Init" : hasAnyServer ? `Round ${Number(roundKey) + 1}` : `Round ${roundKey}`;

    if (isServerRoundMetrics(m)) {
      rowsOut.push(
        [roundTitle, "Dispatch (sec)", formatMinFixed4(isNumber(m.server_dispatch_time_sec) ? m.server_dispatch_time_sec : 0)],
        [roundTitle, "Aggregation (sec)", formatMinFixed4(isNumber(m.server_aggregation_time_sec) ? m.server_aggregation_time_sec : 0)],
        [roundTitle, "Compute (sec)", formatMinFixed4(isNumber(m.server_compute_time_sec) ? m.server_compute_time_sec : 0)],
        [roundTitle, "Payload in (KB)", ((isNumber(m.payload_in_bytes) ? m.payload_in_bytes : 0) / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })],
        [roundTitle, "Payload out (KB)", ((isNumber(m.payload_out_bytes) ? m.payload_out_bytes : 0) / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })]
      );
    } else if (isClientRoundMetrics(m)) {
      rowsOut.push(
        [roundTitle, "Client compute (sec)", formatMinFixed4(isNumber(m.client_compute_time_sec) ? m.client_compute_time_sec : 0)],
        [roundTitle, "Upstream RTT (sec)", formatMinFixed4(isNumber(m.upstream_rtt_sec) ? m.upstream_rtt_sec : 0)],
        [roundTitle, "Downstream RTT (sec)", formatMinFixed4(isNumber(m.downstream_rtt_sec) ? m.downstream_rtt_sec : 0)]
      );
    } else {
      rowsOut.push([roundTitle, "Metrics", "No metrics available for this round."]);
    }
  });

  return [
    { kind: "paragraph", text: titleText, optionId: "analytics_metrics" },
    {
      kind: "table",
      columns: ["Round", "Metric", "Value"],
      rows: rowsOut,
      optionId: "analytics_metrics",
    },
  ];
}

const WorkflowAnalyticsAccordion: React.FC<WorkflowAnalyticsAccordionProps> = ({ workflowId, workflows, role }) => {
  const titleText = role === UserRole.CLIENT ? "Client Analytics Metrics" : "Analytics Metrics";

  const wfMetrics = useMemo(() => {
    if (!workflowId || !workflows) return null;
    return workflows[workflowId] || null;
  }, [workflowId, workflows]);

  const rounds = useMemo(() => {
    if (!wfMetrics) return [] as Array<[string, any]>;
    return Object.entries(wfMetrics).sort(([a], [b]) => Number(a) - Number(b));
  }, [wfMetrics]);

  const hasAnyServer = useMemo(() => rounds.some(([, m]) => isServerRoundMetrics(m)), [rounds]);

  const renderRoundTitle = useCallback(
    (roundKey: string) => {
      if (roundKey === "-1") return "Init";
      if (hasAnyServer) {
        const roundNumber = Number(roundKey) + 1;
        return `Round ${roundNumber}`;
      }
      return `Round ${roundKey}`;
    },
    [hasAnyServer]
  );

  const titleTooltip =
    role === UserRole.CLIENT ? "Show/Hide Client Analytics Metrics" : "Show/Hide Analytics Metrics";

  if (!workflowId || !workflows || !wfMetrics || !rounds.length) {
    return null;
  }

  return (
    <AbstractAccordion
      title={titleText}
      titleTooltip={titleTooltip}
      containerStyle={{ padding: "4px 0", maxWidth: "100%" }}
      bodyStyle={{
        borderRadius: 4,
        border: "1px solid #ccc",
        marginTop: "4px",
        padding: "0.35rem 0.5rem 0.5rem",
        fontSize: 12,
        maxWidth: "100%",
        boxSizing: "border-box",
        backgroundColor: "#f9fafb",
      }}
    >
      <div className="analytics-metrics-accordion-block-02">
        {rounds.map(([roundKey, metrics]) => {
          const m: any = metrics || {};
          const isServer = isServerRoundMetrics(m);
          const isClient = isClientRoundMetrics(m);

          return (
            <div key={roundKey} className="analytics-metrics-accordion-block-03">
              <div
                className="analytics-metrics-accordion-block-04"
              >
                {renderRoundTitle(roundKey)}
              </div>

              {isServer ? (
                <div
                  className="analytics-metrics-accordion-shared-05"
                >
                  <div>
                    <div style={labelStyle}>Dispatch (sec)</div>
                    <div style={valueStyle}>
                      {formatMinFixed4(isNumber(m.server_dispatch_time_sec) ? m.server_dispatch_time_sec : 0)}
                    </div>
                  </div>
                  <div>
                    <div style={labelStyle}>Aggregation (sec)</div>
                    <div style={valueStyle}>
                      {formatMinFixed4(isNumber(m.server_aggregation_time_sec) ? m.server_aggregation_time_sec : 0)}
                    </div>
                  </div>
                  <div>
                    <div style={labelStyle}>Compute (sec)</div>
                    <div style={valueStyle}>
                      {formatMinFixed4(isNumber(m.server_compute_time_sec) ? m.server_compute_time_sec : 0)}
                    </div>
                  </div>
                  <div>
                    <div style={labelStyle}>Payload in (KB)</div>
                    <div style={valueStyle}>
                      {((isNumber(m.payload_in_bytes) ? m.payload_in_bytes : 0) / 1000).toLocaleString(undefined, {
                        maximumFractionDigits: 1,
                      })}
                    </div>
                  </div>
                  <div>
                    <div style={labelStyle}>Payload out (KB)</div>
                    <div style={valueStyle}>
                      {((isNumber(m.payload_out_bytes) ? m.payload_out_bytes : 0) / 1000).toLocaleString(undefined, {
                        maximumFractionDigits: 1,
                      })}
                    </div>
                  </div>
                </div>
              ) : isClient ? (
                <div
                  className="analytics-metrics-accordion-shared-05"
                >
                  <div>
                    <div style={labelStyle}>Client compute (sec)</div>
                    <div style={valueStyle}>
                      {formatMinFixed4(isNumber(m.client_compute_time_sec) ? m.client_compute_time_sec : 0)}
                    </div>
                  </div>
                  <div>
                    <div style={labelStyle}>Upstream RTT (sec)</div>
                    <div style={valueStyle}>
                      {formatMinFixed4(isNumber(m.upstream_rtt_sec) ? m.upstream_rtt_sec : 0)}
                    </div>
                  </div>
                  <div>
                    <div style={labelStyle}>Downstream RTT (sec)</div>
                    <div style={valueStyle}>
                      {formatMinFixed4(isNumber(m.downstream_rtt_sec) ? m.downstream_rtt_sec : 0)}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="analytics-metrics-accordion-shared-04">No metrics available for this round.</div>
              )}
            </div>
          );
        })}
      </div>
    </AbstractAccordion>
  );
};

export { SystemMetricsAccordion, WorkflowAnalyticsAccordion };
export default SystemMetricsAccordion;