import {
  CategoryScale,
  Chart as ChartJS,
  ChartOptions,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Line } from "react-chartjs-2";
import { UserRole } from "../../../context/UserRoleContext";
import { renderAgentDisplayLabel, renderPropertyDisplayLabel } from "../utils/JobsDataUtils";
import AbstractAccordion from "../../../components/AbstractAccordion";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend, Filler);

type KMSeries = { times: number[]; survival: number[] };
type KMResults = { OS?: KMSeries; PFS?: KMSeries };

type RawGroup = { N: number[]; d: number[] };
type RawGroups = Record<string, RawGroup>;

type CIBand = { lower: KMSeries; upper: KMSeries };

type TooltipMeta = {
  datasetMetaKey: string;
  groupKey: string;
  label: string;
  times: number[];
  survival: number[];
  ciLower?: number[];
  ciUpper?: number[];
  rawN?: number[];
  rawD?: number[];
};

type CurveEntry = {
  datasetMetaKey: string;
  groupKey: string;
  label: string;
  dash?: number[];
  xy: { x: number; y: number }[];
  ciLowerXY?: { x: number; y: number }[];
  ciUpperXY?: { x: number; y: number }[];
  tooltipMeta: TooltipMeta;
};

const COLOR_AGENT = "#3FD28B";
const COLOR_AGGREGATED = "#3F5FFF";
const CI_RIBBON_ALPHA_DEFAULT = 0.2;
const CURVE_LEGEND_FILL_ALPHA = 0.2;

function clamp01(v: number) {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}

function hexToRgba(hex: string, alpha: number) {
  const h = (hex || "").trim().replace("#", "");
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) return hex;
  return `rgba(${r},${g},${b},${alpha})`;
}

function isAggregatedGroupKey(groupKey: string) {
  return /aggregat/i.test(groupKey || "");
}

function ciAlphaForGroupKey(groupKey: string, agentAlpha: number, aggregatedAlpha: number) {
  return isAggregatedGroupKey(groupKey) ? aggregatedAlpha : agentAlpha;
}

function curveColorForGroupKey(groupKey: string) {
  const color = isAggregatedGroupKey(groupKey) ? COLOR_AGGREGATED : COLOR_AGENT;
  return darkenHexColor(color, 0.2);
}

function darkenHexColor(hex: string, amount: number) {
  const normalized = hex.replace('#', '');
  const r = parseInt(normalized.slice(0, 2), 16);
  const g = parseInt(normalized.slice(2, 4), 16);
  const b = parseInt(normalized.slice(4, 6), 16);

  const factor = 1 - amount;

  const darkenedR = Math.max(0, Math.floor(r * factor));
  const darkenedG = Math.max(0, Math.floor(g * factor));
  const darkenedB = Math.max(0, Math.floor(b * factor));

  return `#${darkenedR.toString(16).padStart(2, '0')}${darkenedG.toString(16).padStart(2, '0')}${darkenedB.toString(16).padStart(2, '0')}`;
}

function curveLegendFillColorForGroupKey(groupKey: string) {
  return hexToRgba(curveColorForGroupKey(groupKey), CURVE_LEGEND_FILL_ALPHA);
}

function ciLegendFillColorForGroupKey(groupKey: string, agentAlpha: number, aggregatedAlpha: number) {
  return hexToRgba(curveColorForGroupKey(groupKey), isAggregatedGroupKey(groupKey) ? aggregatedAlpha : agentAlpha);
}

function isKMSeries(x: any): x is KMSeries {
  return !!x && Array.isArray(x.times) && Array.isArray(x.survival);
}

function isKMResults(x: any): x is KMResults {
  return !!x && (isKMSeries(x.OS) || isKMSeries(x.PFS));
}

function extractKMResults(input: any): KMResults | null {
  if (!input || (typeof input === "object" && (input as any).error)) return null;
  if (isKMResults(input)) return input;
  if ((input as any)?.results && isKMResults((input as any).results)) return (input as any).results;
  if ((input as any)?.jobs_data && typeof (input as any).jobs_data === "object") {
    for (const k of Object.keys((input as any).jobs_data)) {
      const v = (input as any).jobs_data[k];
      if (v?.results && isKMResults(v.results)) return v.results;
      if (isKMResults(v)) return v;
    }
  }
  return null;
}

function kmGroupsFromAggregatedProcessed(input: any): Record<string, KMSeries> | null {
  if (!input || typeof input !== "object" || (input as any).error) return null;
  const S = (input as any).S_output;
  const T = (input as any).times;
  if (!S || typeof S !== "object" || !Array.isArray(T)) return null;

  const times = T.map(Number);
  const out: Record<string, KMSeries> = {};
  for (const g of Object.keys(S)) {
    const surv = Array.isArray(S[g]) ? (S[g] as any[]).map(Number) : [];
    if (!surv.length || !times.length) continue;
    const m = Math.min(times.length, surv.length);
    out[g] = { times: times.slice(0, m), survival: surv.slice(0, m) };
  }
  return Object.keys(out).length ? out : null;
}

function ciBandsFromAggregatedProcessed(input: any, globalTimes?: number[]): Record<string, CIBand> | null {
  if (!input || typeof input !== "object" || (input as any).error) return null;

  const CI = (input as any).CI;
  const T = (input as any).times;

  if (!CI || typeof CI !== "object" || !Array.isArray(T)) return null;

  const baseTimes = (globalTimes && globalTimes.length ? globalTimes : T).map(Number);
  const out: Record<string, CIBand> = {};

  for (const base of Object.keys(CI)) {
    const band = (CI as any)[base];
    const lowerRaw = band?.lower;
    const upperRaw = band?.upper;

    if (!Array.isArray(lowerRaw) || !Array.isArray(upperRaw)) continue;

    const lower = lowerRaw.map((v: any) => clamp01(Number(v)));
    const upper = upperRaw.map((v: any) => clamp01(Number(v)));

    const m = Math.min(baseTimes.length, lower.length, upper.length);
    if (m <= 0) continue;

    out[base] = {
      lower: { times: baseTimes.slice(0, m), survival: lower.slice(0, m) },
      upper: { times: baseTimes.slice(0, m), survival: upper.slice(0, m) },
    };
  }

  return Object.keys(out).length ? out : null;
}

function rawFromAggregated(input: any): RawGroups | null {
  const numG = input?.numerator_groups;
  const denG = input?.denominator_groups;
  if (!numG || !denG || typeof numG !== "object" || typeof denG !== "object") return null;

  const out: RawGroups = {};
  for (const g of Object.keys(denG)) {
    const N: number[] = Array.isArray(denG[g]) ? denG[g].map(Number) : [];
    const NUM: number[] = Array.isArray(numG[g]) ? numG[g].map(Number) : [];
    if (!N.length || !NUM.length) continue;

    const m = Math.min(N.length, NUM.length);
    const d = new Array<number>(m);
    for (let i = 0; i < m; i++) d[i] = N[i] - NUM[i];
    out[g] = { N: N.slice(0, m), d };
  }
  return Object.keys(out).length ? out : null;
}

function rawFromGroupRoot(input: any): RawGroups | null {
  if (!input || typeof input !== "object") return null;
  const out: RawGroups = {};
  let ok = false;
  for (const k of Object.keys(input)) {
    const v = (input as any)[k];
    if (v && typeof v === "object" && Array.isArray(v.N) && Array.isArray(v.d)) {
      out[k] = { N: v.N, d: v.d };
      ok = true;
    }
  }
  return ok ? out : null;
}

function rawFromClientPayload(input: any): RawGroups | null {
  const cp = input?.client_payload;
  if (!cp || typeof cp !== "object") return null;
  const out: RawGroups = {};
  for (const g of Object.keys(cp)) {
    const obj = cp[g];
    if (obj && Array.isArray(obj.N) && Array.isArray(obj.d)) {
      out[g] = { N: obj.N, d: obj.d };
    }
  }
  return Object.keys(out).length ? out : null;
}

function rawFromLegacyAggregated(input: any): RawGroups | null {
  const Ng = input?.aggregated_N_groups;
  const Dg = input?.aggregated_d_groups;
  if (!Ng || !Dg) return null;
  const out: RawGroups = {};
  for (const g of Object.keys(Ng)) {
    const N = Ng[g];
    const d = Dg[g];
    if (Array.isArray(N) && Array.isArray(d)) {
      out[g] = { N, d };
    }
  }
  return Object.keys(out).length ? out : null;
}

function extractRawGroups(input: any): RawGroups | null {
  return rawFromAggregated(input) || rawFromGroupRoot(input) || rawFromClientPayload(input) || rawFromLegacyAggregated(input);
}

function kmFromNd(N: number[], d: number[]): KMSeries {
  const n = Math.min(N.length, d.length);
  const times = new Array<number>(n);
  const survival = new Array<number>(n);
  let S = 1.0;
  for (let i = 0; i < n; i++) {
    const Nj = Math.max(0, Number(N[i] ?? 0));
    const dj = Math.max(0, Number(d[i] ?? 0));
    times[i] = i;
    if (Nj > 0 && dj >= 0 && dj <= Nj) {
      S *= 1 - dj / Nj;
    }
    if (S < 0) S = 0;
    if (S > 1) S = 1;
    survival[i] = S;
  }
  return { times, survival };
}

function kmSeriesFromRawGroups(groups: RawGroups): Record<string, KMSeries> {
  const out: Record<string, KMSeries> = {};
  for (const g of Object.keys(groups)) {
    const { N, d } = groups[g];
    out[g] = kmFromNd(N, d);
  }
  return out;
}

function formatFixed(value: number | undefined, digits = 3) {
  if (value === undefined || value === null || Number.isNaN(value)) return "n/a";
  return Number(value).toFixed(digits);
}

function formatRawValue(value: number | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return "n/a";
  const rounded = Math.round(value);
  if (Math.abs(value - rounded) < 1e-9) return String(rounded);
  return Number(value).toFixed(3);
}

interface Props {
  data?: unknown;
  seriesMap?: any;
  plotHeight?: number;
  userRole: UserRole;
  onImageDataUrl?: (dataUrl: string | null) => void;
}

export default function KaplanMeierPlotUnified({ data, seriesMap, plotHeight = 420, userRole, onImageDataUrl }: Props) {
  const chartRef = useRef<any>(null);
  const [groupVisible, setGroupVisible] = useState<Record<string, boolean>>({});
  const [ciAlphaAgent, setCiAlphaAgent] = useState<number>(CI_RIBBON_ALPHA_DEFAULT);
  const [ciAlphaAggregated, setCiAlphaAggregated] = useState<number>(CI_RIBBON_ALPHA_DEFAULT);

  const baseModel = useMemo(() => {
    const curveEntries: CurveEntry[] = [];
    const ciAvailableGroups = new Set<string>();
    let explicitTimesDetected = false;

    const getGlobalTimes = (): number[] | undefined => {
      const t1 = seriesMap?.aggregate_processed_results?.times;
      if (Array.isArray(t1) && t1.length) return t1.map(Number);
      const t2 = (seriesMap as any)?.times ?? (data as any)?.times;
      if (Array.isArray(t2) && t2.length) return t2.map(Number);
      return undefined;
    };

    const globalTimes = getGlobalTimes();
    if (globalTimes?.length) explicitTimesDetected = true;

    const dashPatterns: number[][] = [[], [6, 3], [3, 3], [10, 4]];
    const groupDash = (idx: number): number[] | undefined => {
      const p = dashPatterns[idx % dashPatterns.length];
      return p.length ? p : undefined;
    };

    function addCurve(groupKey: string, label: string, series: KMSeries, dash?: number[], band?: CIBand, raw?: RawGroup) {
      if (!series?.times || series.times.length !== series.survival.length || series.times.length === 0) return;

      let aligned: KMSeries = series;
      if (globalTimes && globalTimes.length) {
        const m = Math.min(series.times.length, globalTimes.length, series.survival.length);
        aligned = {
          times: globalTimes.slice(0, m),
          survival: series.survival.slice(0, m),
        };
        explicitTimesDetected = true;
      }

      const n = Math.min(aligned.times.length, aligned.survival.length);
      if (n <= 0) return;

      const times = aligned.times.slice(0, n);
      const survival = aligned.survival.slice(0, n);

      let ciLower: number[] | undefined;
      let ciUpper: number[] | undefined;
      let ciLowerXY: { x: number; y: number }[] | undefined;
      let ciUpperXY: { x: number; y: number }[] | undefined;

      if (band?.lower?.times && band?.lower?.survival) {
        const mLower = Math.min(band.lower.times.length, band.lower.survival.length);
        if (mLower > 0) {
          ciLower = band.lower.survival.slice(0, mLower);
          ciLowerXY = band.lower.times.slice(0, mLower).map((x, i) => ({ x, y: ciLower![i] }));
        }
      }

      if (band?.upper?.times && band?.upper?.survival) {
        const mUpper = Math.min(band.upper.times.length, band.upper.survival.length);
        if (mUpper > 0) {
          ciUpper = band.upper.survival.slice(0, mUpper);
          ciUpperXY = band.upper.times.slice(0, mUpper).map((x, i) => ({ x, y: ciUpper![i] }));
        }
      }

      const datasetMetaKey = `${groupKey}__${label}__${curveEntries.length}`;

      curveEntries.push({
        datasetMetaKey,
        groupKey,
        label,
        dash,
        xy: times.map((x, i) => ({ x, y: survival[i] })),
        ciLowerXY,
        ciUpperXY,
        tooltipMeta: {
          datasetMetaKey,
          groupKey,
          label,
          times,
          survival,
          ciLower,
          ciUpper,
          rawN: raw?.N?.slice(0, n),
          rawD: raw?.d?.slice(0, n),
        },
      });
    }

    if (seriesMap && Object.keys(seriesMap).length > 0) {
      const processedGroups = kmGroupsFromAggregatedProcessed(seriesMap["aggregate_processed_results"]);
      const hasProcessedAggregated = !!processedGroups && Object.keys(processedGroups).length > 0;

      Object.entries(seriesMap).forEach(([label, val]) => {
        if (hasProcessedAggregated && label === "aggregate_results") return;

        const agent = renderAgentDisplayLabel(label, userRole);
        const procGroups = kmGroupsFromAggregatedProcessed(val);

        if (procGroups) {
          const ciBands = ciBandsFromAggregatedProcessed(val, globalTimes);
          const rawGroups = extractRawGroups(val);
          const groupNames = Object.keys(procGroups).sort();

          if (ciBands && Object.keys(ciBands).length > 0) {
            ciAvailableGroups.add(agent);
          }

          groupNames.forEach((gName, gIdx) => {
            addCurve(
              agent,
              `${agent} ${renderPropertyDisplayLabel(gName)}`,
              procGroups[gName],
              groupDash(gIdx),
              ciBands?.[gName],
              rawGroups?.[gName]
            );
          });

          return;
        }

        const r = extractKMResults(val);
        if (r) {
          if (r.OS) addCurve(agent, `${agent} OS`, r.OS);
          if (r.PFS) addCurve(agent, `${agent} PFS`, r.PFS, [6, 3]);
          return;
        }

        const rawGroups = extractRawGroups(val);
        if (rawGroups) {
          const kmGroups = kmSeriesFromRawGroups(rawGroups);
          Object.keys(kmGroups)
            .sort()
            .forEach((gName, gIdx) => {
              addCurve(
                agent,
                `${agent} ${renderPropertyDisplayLabel(gName)}`,
                kmGroups[gName],
                groupDash(gIdx),
                undefined,
                rawGroups[gName]
              );
            });
        }
      });
    } else {
      const procSingleGroups = kmGroupsFromAggregatedProcessed(data);
      if (procSingleGroups) {
        const ciBands = ciBandsFromAggregatedProcessed(data, globalTimes);
        const rawGroups = extractRawGroups(data);

        if (ciBands && Object.keys(ciBands).length > 0) {
          ciAvailableGroups.add("Survival");
        }

        Object.keys(procSingleGroups)
          .sort()
          .forEach((gName, idx) => {
            addCurve("Survival", gName, procSingleGroups[gName], groupDash(idx), ciBands?.[gName], rawGroups?.[gName]);
          });
      } else {
        const single = extractKMResults(data);
        if (single?.OS) addCurve("Survival", "OS", single.OS);
        if (single?.PFS) addCurve("Survival", "PFS", single.PFS, [6, 3]);

        if (!single) {
          const rawSingleGroups = extractRawGroups(data);
          if (rawSingleGroups) {
            const kmGroups = kmSeriesFromRawGroups(rawSingleGroups);
            Object.keys(kmGroups)
              .sort()
              .forEach((gName, gIdx) => {
                addCurve("Survival", gName, kmGroups[gName], groupDash(gIdx), undefined, rawSingleGroups[gName]);
              });
          }
        }
      }
    }

    return {
      curveEntries,
      tooltipMetaByDatasetKey: Object.fromEntries(
        curveEntries.map((entry) => [entry.datasetMetaKey, entry.tooltipMeta])
      ) as Record<string, TooltipMeta>,
      ciAvailableGroups,
      hasExplicitTimes: explicitTimesDetected,
    };
  }, [data, seriesMap, userRole]);

  useEffect(() => {
    if (!baseModel.curveEntries.length) return;

    setGroupVisible((prev) => {
      const next = { ...prev };
      let changed = false;

      for (const entry of baseModel.curveEntries) {
        const g = String(entry.groupKey || "Survival");
        if (next[g] === undefined) {
          next[g] = true;
          changed = true;
        }
      }

      return changed ? next : prev;
    });
  }, [baseModel.curveEntries]);

  const datasets = useMemo(() => {
    const ds: any[] = [];

    for (const entry of baseModel.curveEntries) {
      const alpha = ciAlphaForGroupKey(entry.groupKey, ciAlphaAgent, ciAlphaAggregated);

      ds.push({
        datasetMetaKey: entry.datasetMetaKey,
        groupKey: entry.groupKey,
        label: entry.label,
        data: entry.xy,
        borderColor: curveColorForGroupKey(entry.groupKey),
        backgroundColor: curveLegendFillColorForGroupKey(entry.groupKey),
        stepped: true,
        pointRadius: 0,
        pointHoverRadius: 2,
        pointHoverBackgroundColor: "#000000",
        borderWidth: 2,
        borderDash: entry.dash,
        order: 2,
        parsing: false,
      });

      if (alpha > 0 && entry.ciLowerXY && entry.ciUpperXY) {
        const ciFill = hexToRgba(curveColorForGroupKey(entry.groupKey), alpha);

        ds.push({
          datasetMetaKey: entry.datasetMetaKey,
          groupKey: entry.groupKey,
          label: `${entry.label} CI Lower`,
          data: entry.ciLowerXY,
          borderColor: "rgba(0,0,0,0)",
          backgroundColor: "rgba(0,0,0,0)",
          stepped: true,
          pointRadius: 0,
          borderWidth: 0,
          fill: false,
          order: 0,
          isCI: true,
          ciRole: "lower",
          parsing: false,
          pointHoverRadius: 2,
          pointHoverBackgroundColor: "#000000",
        });

        ds.push({
          datasetMetaKey: entry.datasetMetaKey,
          groupKey: entry.groupKey,
          label: `${entry.label} CI`,
          data: entry.ciUpperXY,
          borderColor: "rgba(0,0,0,0)",
          backgroundColor: ciFill,
          stepped: true,
          pointRadius: 0,
          borderWidth: 0,
          fill: "-1",
          order: 0,
          isCI: true,
          ciRole: "upper",
          parsing: false,
          pointHoverRadius: 2,
          pointHoverBackgroundColor: "#000000",
        });
      }
    }

    return ds;
  }, [baseModel.curveEntries, ciAlphaAgent, ciAlphaAggregated]);

  const visibleDatasets = useMemo(() => {
    return datasets.filter((d) => {
      const g = String(d.groupKey || "Survival");
      return groupVisible[g] !== false;
    });
  }, [datasets, groupVisible]);

  const chartData = useMemo(() => ({ datasets: visibleDatasets }), [visibleDatasets]);

  const curveGroups = useMemo(() => {
    const hasAgent = baseModel.curveEntries.some((entry) => !isAggregatedGroupKey(String(entry.groupKey || "Survival")));
    const hasAggregated = baseModel.curveEntries.some((entry) => isAggregatedGroupKey(String(entry.groupKey || "Survival")));
    const agentLabel = userRole === UserRole.CLIENT ? "Client" : "Initiator";

    const out: { key: string; label: string; color: string; hasCI: boolean }[] = [];

    if (hasAgent) {
      out.push({
        key: "agent",
        label: agentLabel,
        color: curveColorForGroupKey("agent"),
        hasCI: baseModel.curveEntries.some(
          (entry) =>
            !isAggregatedGroupKey(String(entry.groupKey || "Survival")) &&
            !!entry.ciLowerXY &&
            !!entry.ciUpperXY
        ),
      });
    }

    if (hasAggregated) {
      out.push({
        key: "aggregated",
        label: "Aggregated",
        color: curveColorForGroupKey("aggregated"),
        hasCI: baseModel.curveEntries.some(
          (entry) =>
            isAggregatedGroupKey(String(entry.groupKey || "Survival")) &&
            !!entry.ciLowerXY &&
            !!entry.ciUpperXY
        ),
      });
    }

    if (!out.length && baseModel.curveEntries.length > 0) {
      out.push({
        key: "agent",
        label: agentLabel,
        color: curveColorForGroupKey("agent"),
        hasCI: baseModel.curveEntries.some((entry) => !!entry.ciLowerXY && !!entry.ciUpperXY),
      });
    }

    return out;
  }, [baseModel.curveEntries, userRole]);

  const options = useMemo<ChartOptions<"line">>(() => {
    const buildTooltipLines = (items: any[]) => {
      const seenDatasetMetaKeys = new Set<string>();
      const seenLines = new Set<string>();
      const lines: string[] = [];

      for (const item of items) {
        const dataset = item?.dataset as any;
        if (!dataset || dataset.ciRole === "lower") continue;

        const datasetMetaKey = String(dataset.datasetMetaKey || "");
        if (!datasetMetaKey || seenDatasetMetaKeys.has(datasetMetaKey)) continue;
        seenDatasetMetaKeys.add(datasetMetaKey);

        const meta = baseModel.tooltipMetaByDatasetKey[datasetMetaKey];
        if (!meta) continue;

        const idx = Number(item.dataIndex);
        if (!Number.isInteger(idx) || idx < 0 || idx >= meta.survival.length) continue;

        const parts: string[] = [`S=${formatFixed(meta.survival[idx], 3)}`];

        const ciVisible =
          ciAlphaForGroupKey(meta.groupKey, ciAlphaAgent, ciAlphaAggregated) > 0 &&
          meta.ciLower !== undefined &&
          meta.ciUpper !== undefined &&
          idx < meta.ciLower.length &&
          idx < meta.ciUpper.length;

        if (ciVisible && meta.ciLower && meta.ciUpper) {
          parts.push(`CI=[${formatFixed(meta.ciLower[idx], 3)}, ${formatFixed(meta.ciUpper[idx], 3)}]`);
        }

        const hasRaw =
          meta.rawN !== undefined &&
          meta.rawD !== undefined &&
          idx < meta.rawN.length &&
          idx < meta.rawD.length;

        if (hasRaw && meta.rawN && meta.rawD) {
          parts.push(`N=${formatRawValue(meta.rawN[idx])}`);
          parts.push(`d=${formatRawValue(meta.rawD[idx])}`);
        }

        const line = `${meta.label}: ${parts.join(" | ")}`;
        if (seenLines.has(line)) continue;

        seenLines.add(line);
        lines.push(line);

        if (lines.length >= 4) break;
      }

      return lines;
    };

    return {
      responsive: true,
      maintainAspectRatio: false,
      normalized: true,
      animation: false,
      interaction: {
        mode: "x",
        intersect: false,
      },
      plugins: {
        legend: {
          position: "top",
          labels: {
            usePointStyle: true,
            pointStyleWidth: 24,
            generateLabels: (chart: any) => {
              const defaultGen =
                (ChartJS.defaults.plugins.legend.labels as any).generateLabels ||
                ((c: any) => c?.legend?.legendItems || []);

              const all = defaultGen(chart);

              const base = all.filter((li: any) => {
                const d = chart?.data?.datasets?.[li.datasetIndex] as any;
                return !d?.isCI;
              });

              const baseLine = base.map((li: any) => {
                const d = chart?.data?.datasets?.[li.datasetIndex] as any;
                return {
                  ...li,
                  pointStyle: "line",
                  fillStyle: "rgba(0,0,0,0)",
                  strokeStyle: d?.borderColor ?? li.strokeStyle,
                  lineWidth: 2,
                  lineDash: Array.isArray(d?.borderDash) ? d.borderDash : li.lineDash,
                };
              });

              const ciGroupKeys = new Set<string>();
              for (const d of chart?.data?.datasets || []) {
                if ((d as any)?.isCI) ciGroupKeys.add(String((d as any).groupKey || "Survival"));
              }

              const extras = Array.from(ciGroupKeys)
                .sort()
                .map((g) => {
                  const fill = ciLegendFillColorForGroupKey(g, ciAlphaAgent, ciAlphaAggregated);
                  return {
                    text: `${g} CI`,
                    fillStyle: fill,
                    strokeStyle: "rgba(0,0,0,0)",
                    lineWidth: 0,
                    datasetIndex: -1,
                    isCIGroup: true,
                    groupKey: g,
                    pointStyle: "rect",
                  };
                });

              return [...baseLine, ...extras];
            },
          },
          onClick: () => {
            return;
          },
        },
        tooltip: {
          enabled: visibleDatasets.length > 0,
          animation: {
            duration: 0,
          },
          mode: "x",
          intersect: false,
          displayColors: false,
          filter: (ctx: any) => (ctx?.dataset as any)?.ciRole !== "lower",
          callbacks: {
            title: (items: any[]) => {
              const first = items?.find((item) => Number.isFinite(Number(item?.parsed?.x))) || items?.[0];
              const x = Number(first?.parsed?.x);
              if (!Number.isFinite(x)) return "";
              return `Time: ${formatFixed(x, 3)}`;
            },
            afterTitle: (items: any[]) => buildTooltipLines(items),
            label: () => [],
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          beginAtZero: true,
          title: {
            display: true,
            text: baseModel.hasExplicitTimes ? "Time (months)" : "Time (steps)",
          },
        },
        y: {
          min: 0,
          max: 1,
          title: {
            display: true,
            text: "Survival Probability",
          },
        },
      },
      elements: {
        line: {
          tension: 0,
        },
      },
    };
  }, [baseModel.hasExplicitTimes, baseModel.tooltipMetaByDatasetKey, ciAlphaAgent, ciAlphaAggregated, visibleDatasets.length]);

  useEffect(() => {
    if (!onImageDataUrl) return;

    if (!visibleDatasets || visibleDatasets.length === 0) {
      onImageDataUrl(null);
      return;
    }

    const raf = requestAnimationFrame(() => {
      try {
        const inst = chartRef.current;
        const url = inst && typeof inst.toBase64Image === "function" ? inst.toBase64Image() : null;
        onImageDataUrl(url || null);
      } catch {
        onImageDataUrl(null);
      }
    });

    return () => cancelAnimationFrame(raf);
  }, [visibleDatasets, onImageDataUrl]);

  return (
    <div className="kaplan-meier-plot-block-01">
      <div className="kaplan-meier-plot-block-02" style={{ height: plotHeight }}>
        <div className="kaplan-meier-plot-block-03">
          <Line
            data={chartData}
            options={options}
            ref={(instance: any) => {
              chartRef.current = instance || null;
            }}
          />
        </div>
      </div>
      <div className="kaplan-meier-plot-block-04">
        <AbstractAccordion
          title="Configuration"
          titleTooltip="Show/Hide Plot Configuration"
          defaultOpen={true}
          containerStyle={{ maxWidth: "100%" }}
          bodyStyle={{
            marginTop: "4px",
            margin: ".5rem",
            maxWidth: "100%",
            boxSizing: "border-box",
          }}
        >
          <div
            className="kaplan-meier-plot-block-05"
          >
            <div
              className="kaplan-meier-plot-block-06"
            >
              <b className="kaplan-meier-plot-shared-01">Show Survival Curves:</b>
              <div className="kaplan-meier-plot-shared-02"></div>
              <div
                className="duality-d-flex-col-column"
              >
                {curveGroups.map((g) => (
                  <label
                    key={`show_${g.key}`}
                    className="kaplan-meier-plot-block-07" style={{ color: g.color }}
                  >
                    <input
                      type="checkbox"
                      checked={
                        g.key === "aggregated"
                          ? groupVisible["Aggregated"] !== false
                          : Object.keys(groupVisible)
                            .filter((key) => !isAggregatedGroupKey(key))
                            .some((key) => groupVisible[key] !== false)
                      }
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setGroupVisible((prev) => {
                          const next = { ...prev };
                          for (const key of Object.keys(next)) {
                            if (g.key === "aggregated") {
                              if (isAggregatedGroupKey(key)) next[key] = checked;
                            } else {
                              if (!isAggregatedGroupKey(key)) next[key] = checked;
                            }
                          }
                          return next;
                        });
                      }}
                    />
                    <span>{g.label}</span>
                  </label>
                ))}
              </div>
            </div>
            {curveGroups.some((g) => g.hasCI) ? (
              <div
                className="kaplan-meier-plot-block-08"
              >
                <b className="kaplan-meier-plot-shared-01">Confidence Interval Opacity:</b>
                <div className="kaplan-meier-plot-shared-02"></div>
                <div
                  className="kaplan-meier-plot-block-09"
                >
                  {curveGroups.filter((g) => g.hasCI).map((g) => {
                    const isAgg = g.key === "aggregated";
                    const alpha = isAgg ? ciAlphaAggregated : ciAlphaAgent;
                    const setAlpha = isAgg ? setCiAlphaAggregated : setCiAlphaAgent;

                    const isVisible =
                      g.key === "aggregated"
                        ? groupVisible["Aggregated"] !== false
                        : Object.keys(groupVisible)
                          .filter((key) => !isAggregatedGroupKey(key))
                          .some((key) => groupVisible[key] !== false);

                    return (
                      <label
                        key={`alpha_${g.key}`}
                        className="kaplan-meier-plot-block-10" style={{ color: g.color, visibility: isVisible ? "visible" : "hidden" }}
                      >
                        <span className="kaplan-meier-plot-block-11">{g.label}</span>
                        <input
                          type="range"
                          min={0}
                          max={0.6}
                          step={0.025}
                          value={alpha}
                          onChange={(e) => setAlpha(Number(e.target.value))}
                          className="kaplan-meier-plot-input"
                        />
                      </label>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </AbstractAccordion>
      </div>
    </div>
  );
}