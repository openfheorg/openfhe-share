import React, { useMemo } from "react";
import { UserRole } from "../../../context/UserRoleContext";

// Same palette as the survival (Kaplan-Meier) figures: the local/Initiator fit
// is green, the Aggregated meta-analysis is blue.
const COLOR_AGENT = "#3FD28B";
const COLOR_AGGREGATED = "#3F5FFF";

type CalibrationStats = {
  meta_beta1?: number | null;
  ci_lower?: number | null;
  ci_upper?: number | null;
} | null | undefined;

export interface OddsRatioLollipopPlotProps {
  agentResults: CalibrationStats;
  aggregatedResults: CalibrationStats;
  userRole: UserRole;
}

type LollipopEntry = {
  key: string;
  label: string;
  color: string;
  or: number;
  orLow: number;
  orHigh: number;
};

function finiteOrNull(value: unknown): number | null {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

// Odds ratio = exp(β₁); the CI bounds are exp() of the log-scale CI on β₁.
function toEntry(
  key: string,
  label: string,
  color: string,
  stats: CalibrationStats,
): LollipopEntry | null {
  if (!stats || typeof stats !== "object") return null;
  const beta1 = finiteOrNull(stats.meta_beta1);
  const lo = finiteOrNull(stats.ci_lower);
  const hi = finiteOrNull(stats.ci_upper);
  if (beta1 === null || lo === null || hi === null) return null;
  return {
    key,
    label,
    color,
    or: Math.exp(beta1),
    orLow: Math.exp(Math.min(lo, hi)),
    orHigh: Math.exp(Math.max(lo, hi)),
  };
}

// Fixed odds-ratio axis so figures for different models can be compared
// side by side. Linear scale (0 cannot live on a log axis anyway).
const AXIS_MIN = 0;
const AXIS_MAX = 10;
const AXIS_TICKS = [0, 2, 4, 6, 8, 10];

function formatOr(v: number): string {
  return v >= 100 ? v.toFixed(0) : v.toFixed(2);
}

function buildEntries(
  agentResults: CalibrationStats,
  aggregatedResults: CalibrationStats,
  agentLabel: string
): LollipopEntry[] {
  const out: LollipopEntry[] = [];
  const agent = toEntry("agent", agentLabel, COLOR_AGENT, agentResults);
  if (agent) out.push(agent);
  const aggregated = toEntry("aggregated", "Aggregated", COLOR_AGGREGATED, aggregatedResults);
  if (aggregated) out.push(aggregated);
  return out;
}

function escapeSvgText(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function buildOddsRatioSvg(entries: LollipopEntry[]): { svg: string; width: number; height: number } | null {
  if (!entries.length) return null;

  const W = 720;
  const marginLeft = 96;
  const marginRight = 28;
  const marginTop = 36;
  const rowHeight = 56;
  const axisHeight = 52;
  const plotLeft = marginLeft;
  const plotRight = W - marginRight;
  const plotWidth = plotRight - plotLeft;
  const H = marginTop + entries.length * rowHeight + axisHeight;

  const xOf = (value: number) => {
    const frac = (value - AXIS_MIN) / (AXIS_MAX - AXIS_MIN);
    const clamped = frac < 0 ? 0 : frac > 1 ? 1 : frac;
    return plotLeft + clamped * plotWidth;
  };

  const axisY = marginTop + entries.length * rowHeight;
  const refX = xOf(1);

  const gridLines = AXIS_TICKS.map(
    (tick) => `<line x1="${xOf(tick)}" x2="${xOf(tick)}" y1="${marginTop - 8}" y2="${axisY}" stroke="#eef1f5" stroke-width="1" />`
  ).join("");

  const dataRows = entries
    .map((entry, index) => {
      const cy = marginTop + index * rowHeight + rowHeight / 2;
      const xLow = xOf(entry.orLow);
      const xHigh = xOf(entry.orHigh);
      const xDot = xOf(entry.or);
      const label = escapeSvgText(entry.label);
      const annotation = `${formatOr(entry.or)} (${formatOr(entry.orLow)}–${formatOr(entry.orHigh)})`;

      return `
        <g>
          <text x="${plotLeft - 12}" y="${cy + 4}" text-anchor="end" font-family="Arial, sans-serif" font-size="13" font-weight="600" fill="${entry.color}">${label}</text>
          <line x1="${xLow}" x2="${xHigh}" y1="${cy}" y2="${cy}" stroke="${entry.color}" stroke-width="2.5" stroke-linecap="round" />
          <line x1="${xLow}" x2="${xLow}" y1="${cy - 7}" y2="${cy + 7}" stroke="${entry.color}" stroke-width="2" />
          <line x1="${xHigh}" x2="${xHigh}" y1="${cy - 7}" y2="${cy + 7}" stroke="${entry.color}" stroke-width="2" />
          <circle cx="${xDot}" cy="${cy}" r="6.5" fill="${entry.color}" stroke="#fff" stroke-width="1.5" />
          <text x="${xDot}" y="${cy - 13}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="700" fill="${entry.color}">${escapeSvgText(annotation)}</text>
        </g>`;
    })
    .join("");

  const ticks = AXIS_TICKS.map(
    (tick) => `
      <g>
        <line x1="${xOf(tick)}" x2="${xOf(tick)}" y1="${axisY}" y2="${axisY + 5}" stroke="#cbd2dd" stroke-width="1" />
        <text x="${xOf(tick)}" y="${axisY + 19}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#6b7280">${tick}</text>
      </g>`
  ).join("");

  return {
    width: W,
    height: H,
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
      <rect width="100%" height="100%" fill="#ffffff" />
      ${gridLines}
      <line x1="${refX}" x2="${refX}" y1="${marginTop - 8}" y2="${axisY}" stroke="#9aa3b2" stroke-width="1" stroke-dasharray="4 4" />
      <text x="${refX}" y="${marginTop - 12}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#6b7280">OR = 1</text>
      ${dataRows}
      <line x1="${plotLeft}" x2="${plotRight}" y1="${axisY}" y2="${axisY}" stroke="#cbd2dd" stroke-width="1" />
      ${ticks}
      <text x="${plotLeft + plotWidth / 2}" y="${axisY + 40}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#374151">Odds Ratio, 95% CI</text>
    </svg>`,
  };
}

export async function createOddsRatioLollipopPlotPng(
  agentResults: CalibrationStats,
  aggregatedResults: CalibrationStats,
  agentLabel: string
): Promise<{ dataUrl: string; width: number; height: number } | null> {
  const rendered = buildOddsRatioSvg(buildEntries(agentResults, aggregatedResults, agentLabel));
  if (!rendered) return null;

  return new Promise((resolve) => {
    const svgDataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(rendered.svg)}`;
    const image = new Image();

    image.onload = () => {
      const scale = 2;
      const canvas = window.document.createElement("canvas");
      canvas.width = rendered.width * scale;
      canvas.height = rendered.height * scale;

      const context = canvas.getContext("2d");
      if (!context) {
        resolve(null);
        return;
      }

      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);

      resolve({
        dataUrl: canvas.toDataURL("image/png"),
        width: rendered.width,
        height: rendered.height,
      });
    };

    image.onerror = () => resolve(null);
    image.src = svgDataUrl;
  });
}

const OddsRatioLollipopPlot: React.FC<OddsRatioLollipopPlotProps> = ({
  agentResults,
  aggregatedResults,
  userRole,
}) => {
  const agentLabel = userRole === UserRole.CLIENT ? "Client" : "Initiator";

  const entries = useMemo(
    () => buildEntries(agentResults, aggregatedResults, agentLabel),
    [agentResults, aggregatedResults, agentLabel]
  );

  if (entries.length === 0) {
    return (
      <div className="odds-ratio-lollipop-plot-block-01">
        Odds ratio figure unavailable (no calibration estimate).
      </div>
    );
  }

  // SVG geometry (responsive via viewBox).
  const W = 720;
  const marginLeft = 96;
  const marginRight = 28;
  const marginTop = 36;
  const rowHeight = 56;
  const axisHeight = 52;
  const plotLeft = marginLeft;
  const plotRight = W - marginRight;
  const plotWidth = plotRight - plotLeft;
  const H = marginTop + entries.length * rowHeight + axisHeight;
  const axisY = marginTop + entries.length * rowHeight;

  // Fixed linear [0, 20] axis; clamp so estimates beyond the range stay inside
  // the plot (the numeric annotation still shows the true value).
  const xOf = (v: number) => {
    const frac = (v - AXIS_MIN) / (AXIS_MAX - AXIS_MIN);
    const clamped = frac < 0 ? 0 : frac > 1 ? 1 : frac;
    return plotLeft + clamped * plotWidth;
  };

  const ticks = AXIS_TICKS;
  const refX = xOf(1);

  return (
    <div className="duality-width-full">
      <div
        className="odds-ratio-lollipop-plot-block-02"
      >
        Odds Ratio (exp(β₁))
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Odds ratio lollipop chart with 95% confidence intervals"
        className="odds-ratio-lollipop-plot-odds-ratio-lollipop-chart-with-95-confidence-intervals"
      >
        {/* Vertical gridlines at each axis tick (drawn first, behind data) */}
        {ticks.map((t) => (
          <line
            key={`grid-${t}`}
            x1={xOf(t)}
            x2={xOf(t)}
            y1={marginTop - 8}
            y2={axisY}
            stroke="#eef1f5"
            strokeWidth={1}
          />
        ))}

        {/* OR = 1 null-effect reference line */}
        <g>
          <line
            x1={refX}
            x2={refX}
            y1={marginTop - 8}
            y2={axisY}
            stroke="#9aa3b2"
            strokeWidth={1}
            strokeDasharray="4 4"
          />
          <text
            x={refX}
            y={marginTop - 12}
            textAnchor="middle"
            fontSize="11"
            fill="#6b7280"
          >
            OR = 1
          </text>
        </g>

        {/* One lollipop per source */}
        {entries.map((e, i) => {
          const cy = marginTop + i * rowHeight + rowHeight / 2;
          const xLow = xOf(e.orLow);
          const xHigh = xOf(e.orHigh);
          const xDot = xOf(e.or);
          const capHalf = 7;
          return (
            <g key={e.key}>
              {/* Row label */}
              <text
                x={plotLeft - 12}
                y={cy + 4}
                textAnchor="end"
                fontSize="13"
                fontWeight={600}
                fill={e.color}
              >
                {e.label}
              </text>

              {/* Confidence-interval line (the stick) */}
              <line
                x1={xLow}
                x2={xHigh}
                y1={cy}
                y2={cy}
                stroke={e.color}
                strokeWidth={2.5}
                strokeLinecap="round"
              />
              {/* CI whisker caps */}
              <line x1={xLow} x2={xLow} y1={cy - capHalf} y2={cy + capHalf} stroke={e.color} strokeWidth={2} />
              <line x1={xHigh} x2={xHigh} y1={cy - capHalf} y2={cy + capHalf} stroke={e.color} strokeWidth={2} />

              {/* Point estimate (the candy) */}
              <circle cx={xDot} cy={cy} r={6.5} fill={e.color} stroke="#fff" strokeWidth={1.5} />

              {/* Value annotation */}
              <text
                x={xDot}
                y={cy - 13}
                textAnchor="middle"
                fontSize="12"
                fontWeight={700}
                fill={e.color}
              >
                {formatOr(e.or)}
                <tspan fontWeight={400} fill="#6b7280">
                  {` (${formatOr(e.orLow)}–${formatOr(e.orHigh)})`}
                </tspan>
              </text>
            </g>
          );
        })}

        {/* X-axis */}
        <line x1={plotLeft} x2={plotRight} y1={axisY} y2={axisY} stroke="#cbd2dd" strokeWidth={1} />
        {ticks.map((t) => {
          const x = xOf(t);
          return (
            <g key={t}>
              <line x1={x} x2={x} y1={axisY} y2={axisY + 5} stroke="#cbd2dd" strokeWidth={1} />
              <text x={x} y={axisY + 19} textAnchor="middle" fontSize="11" fill="#6b7280">
                {t}
              </text>
            </g>
          );
        })}
        <text
          x={plotLeft + plotWidth / 2}
          y={axisY + 40}
          textAnchor="middle"
          fontSize="12"
          fill="#374151"
        >
          Odds Ratio, 95% CI
        </text>
      </svg>
    </div>
  );
};

export default OddsRatioLollipopPlot;
