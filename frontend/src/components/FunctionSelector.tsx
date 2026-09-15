/**
 * FunctionSelector.tsx
 *
 * This component renders the list of available functions the user can launch.
 *
 * Responsibilities:
 *   - Provide two layout variants:
 *       - "grid" (default): large clickable cards with icons and descriptions.
 *       - "nav": vertical navigation panel with a simple list of functions.
 *   - Handle hover/selection styling for function options.
 *   - Expose selected function IDs to the parent via onSelectionFunctionConfigChange.
 *   - Include the shared Footer in both variants.
 *
 * Exports:
 *   - FUNCTION_METADATA: default metadata for available functions (without click handlers).
 *   - FunctionSelector: the component itself.
 *
 * Props:
 *   - options: list of functions to display, including id, title, description, and optional icon.
 *   - variant: layout style ("grid" | "nav"), defaults to "grid".
 *   - selected: used in "nav" mode to highlight the active function (labeling only).
 *   - onSelectionFunctionConfigChange: callback receiving the current selection map.
 *   - initialSelectedIds: initial selection map (functionId -> arg map) to hydrate on load.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import CompactBanner from "./CompactBanner";
import {
  FunctionConfigs,
  FunctionConfigProps,
  ThresholdConfig,
  ThresholdMethod,
} from "../types/FunctionConfigs";
import { Project } from "../types/Project";
import { FilterCollection } from "../features/job_runner/utils/FilterPayloadConfigUtils";
import { HelpPanel, HelpToggle } from "./HelpToggle";
import { ChevronDown } from "react-bootstrap-icons";

type ArgType = "int" | "str" | "select";

export interface FunctionArg {
  property: string;
  type: ArgType;
  default?: string;
  description?: string;
  options?: string[];
  disabledOptions?: string[];
  disabled?: boolean;
  always_configurable?: boolean;
}

export interface FunctionOption {
  id: string;
  title: string;
  description: string;
  disabled: boolean;
  icon?: string;
  args: FunctionArg[];
}



const GENE_OPTIONS = [
  "ARID1A",
  "ATM",
  "BAP1",
  "COL9A3",
  "KDM5C",
  "MTOR",
  "NF2",
  "PBRM1",
  "PCK1",
  "PIK3CA",
  "PTEN",
  "S100B",
  "SETD2",
  "SMARCA4",
  "TCEB1",
  "TP53",
  "TRMT2B",
  "TSC1",
  "USP32",
  "VHL",
  "WNT8A",
  "ZNF800",
];

export const FUNCTION_METADATA: Omit<FunctionOption, never>[] = [
  {
    id: "survival_analysis",
    title: "Survival Analysis",
    description: "Run Kaplan-Meier analysis on filtered patient data",
    icon: "/function_icon_SA.png",
    disabled: false,
    args: [
      {
        property: "group_column_id",
        type: "select",
        options: GENE_OPTIONS,
        default: "PBRM1",
        description:
          "Column indicating group membership (categorical). Gene options tap into MUT/WT values within Observation data",
      },
      {
        property: "time_column_id",
        type: "select",
        options: ["OS", "PFS"],
        default: "OS",
        description: "Column of event times (numeric).",
      },
      {
        property: "censoring_column_id",
        type: "select",
        options: ["OS_CNSR", "PFS_CNSR"],
        default: "OS_CNSR",
        description:
          "Column specifying event occurrence 1=death, 0=censored (categorical).",
      },
      {
        property: "time_grid_min",
        type: "int",
        default: "0",
        description: "Grid minimum.",
        always_configurable: true,
      },
      {
        property: "time_grid_step",
        type: "int",
        default: "0.1",
        description: "Grid step.",
        always_configurable: true,
      },
      {
        property: "time_grid_max",
        type: "int",
        default: "62",
        description: "Grid maximum.",
        always_configurable: true,
      },
      {
        property: "CI_type",
        type: "select",
        default: "None",
        options: ["None", "log-log", "linear"],
        description:
          "CI_type selects the method used to compute confidence intervals for survival curves:\n\rlog-log: Log-transformed, asymmetric bounds\n\rlinear: Symmetric bounds on the survival probability",
      },
    ],
  },
  {
    id: "chi_square_test",
    title: "Chi-Square Test",
    description: "Association test between categorical variables",
    icon: "/function_icon_Chi.png",
    disabled: false,
    args: [
      {
        property: "category_column_1_id",
        type: "select",
        default: "PBRM1",
        options: [...GENE_OPTIONS, "gender", "Medication"],
        description:
          "First categorical column. Gene options tap into MUT/WT values within Observation data",
      },
      {
        property: "category_column_2_id",
        type: "select",
        default: "gender",
        options: [...GENE_OPTIONS, "gender", "Medication"],
        description: "Second categorical column.",
      },
    ],
  },
  {
    id: "mean",
    title: "Mean",
    description: "Summarize a numeric column (average).",
    icon: "/function_icon_Mean.png",
    disabled: false,
    args: [
      {
        property: "data_column_id",
        type: "select",
        default: "Age",
        options: ["Age"],
        description:
          "Numeric column to compute the mean on. Age is linked to Patient.Age",
      },
    ],
  },
  {
    id: "standard_deviation",
    title: "Standard Deviation",
    description: "Spread of measurements around the mean.",
    icon: "/function_icon_Std.png",
    disabled: false,
    args: [
      {
        property: "data_column_id",
        type: "select",
        default: "Age",
        options: ["Age"],
        description:
          "Numeric column to compute the standard deviation on. Age is linked to Patient.Age",
      },
      {
        property: "std_type",
        type: "select",
        options: ["sample", "population"],
        default: "population",
        description: 'Type of SD: "sample" or "population".',
      },
    ],
  },
  {
    id: "t_test",
    title: "T-Test",
    description: "Compare means of two groups.",
    icon: "/function_icon_TTest.png",
    disabled: false,
    args: [
      {
        property: "data_column_id",
        type: "select",
        default: "Age",
        options: ["Age"],
        description: "Numeric column to test.",
      },
      {
        property: "category_column_1_id",
        type: "select",
        default: "PBRM1",
        options: [...GENE_OPTIONS, "gender", "Medication"],
        description: "Grouping column (two categories).",
      },
    ],
  },
  {
    id: "encrypted_filtering",
    title: "Encrypted Filtering",
    description: "Apply filters securely in encrypted form.",
    icon: "/function_icon_EncFil.png",
    disabled: true,
    args: [],
  },
  {
    id: "count",
    title: "Count",
    description: "Number of records matching filters.",
    icon: "/function_icon_Count.png",
    disabled: true,
    args: [],
  },
  {
    id: "exceptional_response_discrimination",
    title: "Exceptional Response Discrimination",
    description: "Compute odds ratio per standard deviation of predictive model score for exceptional response.",
    icon: "/function_icon_LogCal.png",
    disabled: false,
    args: [],
  },
];

// Human-readable name for a function id or enum value (e.g.
// "EXCEPTIONAL_RESPONSE_DISCRIMINATION"). Prefers the curated FUNCTION_METADATA
// title and falls back to title-casing the id.
export const formatFunctionName = (name: string): string => {
  const meta = FUNCTION_METADATA.find((f) => f.id === name.toLowerCase());
  if (meta) return meta.title;
  return name
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
};

export const FUNCTION_ENUM_TO_ID: Record<string, string> = {
  SURVIVAL_ANALYSIS: "survival_analysis",
  CHI_SQUARE_TEST: "chi_square_test",
  MEAN: "mean",
  STANDARD_DEVIATION: "standard_deviation",
  T_TEST: "t_test",
  ENCRYPTED_FILTERING: "encrypted_filtering",
  COUNT: "count",
  EXCEPTIONAL_RESPONSE_DISCRIMINATION: "exceptional_response_discrimination",
};

interface FunctionSelectorProps {
  variant?: "grid" | "nav";
  compact?: boolean;
  onSelectionFunctionConfigChange?: (selection: FunctionConfigs) => void;
  initialSelectedFunctions?: FunctionConfigs;
  onArgsChange?: (map: Record<string, Record<string, string>>) => void;
  onThresholdSamplesChange?: (thressholdConfig: ThresholdConfig) => void;
  initialSelectedThresholdConfig?: ThresholdConfig;
  project?: Project;
  filterSet?: FilterCollection;
}

const THRESHOLD_DESC_PROTECTED =
  "PROTECTED: Performs the threshold check without exposing any sample counts; the initiator only learns whether the minimum sample threshold is met.";
const THRESHOLD_DESC_EXPOSED =
  "EXPOSED: Performs a straightforward threshold check and allows the initiator to see the total number of samples and whether it meets the configured threshold.";
const THRESHOLD_DESC =
  "Run an analysis only if there are at least k records behind it. The maximum value of the threshold k is 20.";
const DEFAULT_THRESHOLD = 10;

const FunctionSelector: React.FC<FunctionSelectorProps> = ({
  onSelectionFunctionConfigChange,
  initialSelectedFunctions = {},
  onArgsChange,
  compact = false,
  onThresholdSamplesChange,
  initialSelectedThresholdConfig,
  project,
  filterSet,
}) => {
  const [selectedFunctionConfigs, setSelectedFunctionConfigs] =
    useState<FunctionConfigs>(initialSelectedFunctions);

  const [activeConfigIndex, setActiveConfigIndex] =
    useState<Record<string, number>>({});
  const [openTooltips, setOpenTooltips] =
    useState<Record<string, Set<string>>>({});
  const [configPanelFlash, setConfigPanelFlash] =
    useState<Record<string, boolean>>({});
  const [showScrollChevronByFn, setShowScrollChevronByFn] = useState<
    Record<string, boolean>
  >({});

  const [thresholdCheckEnabled, setThresholdCheckEnabled] = useState(
    initialSelectedThresholdConfig?.enabled ?? false
  );
  const [thresholdMethod, setThresholdMethod] = useState<ThresholdMethod>(
    initialSelectedThresholdConfig?.thresholdMethod ?? "PROTECTED"
  );
  const [threshold, setThreshold] = useState<number>(
    initialSelectedThresholdConfig?.threshold ?? DEFAULT_THRESHOLD
  );
  const [thresholdHelpOpen, setThresholdHelpOpen] = useState(false);

  const onSelectionRef = useRef(onSelectionFunctionConfigChange);
  const onArgsChangeRef = useRef(onArgsChange);
  const onThresholdSamplesChangeRef = useRef(onThresholdSamplesChange);
  const filterSetRef = useRef<FilterCollection | undefined>(filterSet);

  const argsWrapRefByFn = useRef<Record<string, HTMLDivElement | null>>({});
  const [argsWrapWidthByFn, setArgsWrapWidthByFn] = useState<Record<string, number>>(
    {}
  );

  const updateScrollChevron = (fnId: string) => {
    const el = argsWrapRefByFn.current[fnId];
    if (!el) return;

    const hasMoreBelow = el.scrollHeight - el.scrollTop - el.clientHeight > 25;

    setShowScrollChevronByFn((prev) =>
      prev[fnId] === hasMoreBelow ? prev : { ...prev, [fnId]: hasMoreBelow }
    );
  };

  useEffect(() => {
    onSelectionRef.current = onSelectionFunctionConfigChange;
  }, [onSelectionFunctionConfigChange]);

  useEffect(() => {
    onArgsChangeRef.current = onArgsChange;
  }, [onArgsChange]);

  useEffect(() => {
    onThresholdSamplesChangeRef.current = onThresholdSamplesChange;
  }, [onThresholdSamplesChange]);

  useEffect(() => {
    filterSetRef.current = filterSet;
  }, [filterSet]);

  useEffect(() => {
    const observed = new Map<string, ResizeObserver>();

    Object.keys(argsWrapRefByFn.current || {}).forEach((fnId) => {
      const el = argsWrapRefByFn.current[fnId];
      if (!el) return;

      const ro = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        const w = entry.contentRect.width;
        setArgsWrapWidthByFn((prev) => {
          if (prev[fnId] === w) return prev;
          return { ...prev, [fnId]: w };
        });
        updateScrollChevron(fnId);
      });

      ro.observe(el);
      observed.set(fnId, ro);

      const w0 = el.getBoundingClientRect().width;
      if (w0) {
        setArgsWrapWidthByFn((prev) => {
          if (prev[fnId] === w0) return prev;
          return { ...prev, [fnId]: w0 };
        });
      }

      updateScrollChevron(fnId);
    });

    return () => {
      observed.forEach((ro) => ro.disconnect());
      observed.clear();
    };
  });

  const filterSetKey = useMemo(() => {
    if (!filterSet) return "";
    return [
      filterSet.patientQueryFilters || "",
      filterSet.patientDataFilters || "",
      filterSet.observationQueryFilters || "",
      filterSet.observationDataFilters || "",
    ].join("||");
  }, [filterSet]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      Object.keys(argsWrapRefByFn.current || {}).forEach((fnId) => {
        updateScrollChevron(fnId);
      });
    });

    return () => cancelAnimationFrame(raf);
  }, [selectedFunctionConfigs, activeConfigIndex, argsWrapWidthByFn]);

  useEffect(() => {
    onSelectionRef.current?.(selectedFunctionConfigs);

    const cb = onArgsChangeRef.current;
    if (cb) {
      const firstConfigMap: Record<string, Record<string, string>> = {};
      Object.entries(selectedFunctionConfigs).forEach(([fnId, configs]) => {
        if (configs && configs[0]) {
          firstConfigMap[fnId] = configs[0];
        }
      });
      cb(firstConfigMap);
    }
  }, [selectedFunctionConfigs]);

  useEffect(() => {
    onThresholdSamplesChangeRef.current?.({
      enabled: thresholdCheckEnabled,
      threshold,
      thresholdMethod,
    });
  }, [thresholdCheckEnabled, threshold, thresholdMethod]);

  const hasFunctionCapabilities =
    project && Array.isArray(project.functions) && project.functions.length > 0;

  const customById = useMemo(() => {
    const fixed = new Map<string, Record<string, any> | null>();
    const variable = new Map<string, any | null>();
    const override = new Map<string, Record<string, any> | null>();

    if (hasFunctionCapabilities) {
      project!.functions.forEach((pf: any) => {
        const id = FUNCTION_ENUM_TO_ID[pf.function];
        if (!id) return;

        const f = pf.custom_configuration_fixed ?? null;
        const v = pf.custom_configuration_variable ?? null;
        const o = pf.override_configuration ?? null;

        fixed.set(id, f && typeof f === "object" ? f : null);
        variable.set(id, v ?? null);
        override.set(id, o && typeof o === "object" ? o : null);
      });
    }

    return { fixed, variable, override };
  }, [hasFunctionCapabilities, project]);

  const supportedIds = useMemo(() => {
    const s = new Set<string>();
    if (hasFunctionCapabilities) {
      project!.functions.forEach((pf: any) => {
        const id = FUNCTION_ENUM_TO_ID[pf.function];
        if (id) s.add(id);
      });
    }
    return s;
  }, [hasFunctionCapabilities, project]);

  const gridFunctions = hasFunctionCapabilities
    ? FUNCTION_METADATA.filter((fn) => supportedIds.has(fn.id))
    : FUNCTION_METADATA;

  const selectableFunctions = gridFunctions.filter((fn) => !fn.disabled);
  const singleFunctionId =
    selectableFunctions.length === 1 ? selectableFunctions[0].id : null;

  const valueToDefaultString = (v: any): string => {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v;
    if (typeof v === "number") return String(v);
    if (typeof v === "boolean") return v ? "true" : "false";
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  };

  const parseJson = <T,>(s: string | undefined | null): T => {
    if (!s || s.trim() === "") return {} as T;
    try {
      return JSON.parse(s) as T;
    } catch {
      return {} as T;
    }
  };

  const toLowerCamelFromScreamingSnake = (s: string): string => {
    const parts = String(s)
      .split("_")
      .map((p) => p.trim())
      .filter(Boolean);
    if (!parts.length) return "";
    const head = parts[0].toLowerCase();
    const tail = parts
      .slice(1)
      .map((p) => p.toLowerCase())
      .map((p) => (p.length ? p[0].toUpperCase() + p.slice(1) : p));
    return [head, ...tail].join("");
  };

  const normalizeKeyCandidates = (k: string): string[] => {
    const raw = String(k || "").trim();
    if (!raw) return [];
    const lower = raw.toLowerCase();
    const camel = toLowerCamelFromScreamingSnake(raw);
    const snake = lower;
    const noUnderscore = raw.replace(/_/g, "");
    const noUnderscoreLower = noUnderscore.toLowerCase();
    const uniq = (arr: string[]) => Array.from(new Set(arr.filter(Boolean)));
    return uniq([raw, lower, camel, snake, noUnderscore, noUnderscoreLower]);
  };

  const stringifyResolved = (v: any): string => {
    if (v === null || v === undefined) return "";
    if (Array.isArray(v)) {
      const parts = v.map((x) => valueToDefaultString(x)).filter((x) => x !== "");
      return parts.join(",");
    }
    return valueToDefaultString(v);
  };

  const normalizeVariableCfgToArgs = (variableCfg: any): FunctionArg[] => {
    if (!variableCfg) return [];

    if (typeof variableCfg === "object") {
      const out: FunctionArg[] = [];
      Object.keys(variableCfg).forEach((k) => {
        const rawVal = (variableCfg as any)[k];

        if (rawVal && typeof rawVal === "object" && !Array.isArray(rawVal)) {
          const typeRaw = String((rawVal as any).type || "").trim();
          const type: ArgType =
            typeRaw === "select" ? "select" : typeRaw === "int" ? "int" : "str";

          const arg: FunctionArg = {
            property: k,
            type,
          };

          if ((rawVal as any).default !== undefined) {
            arg.default = valueToDefaultString((rawVal as any).default);
          }
          if (typeof (rawVal as any).description === "string") {
            arg.description = (rawVal as any).description;
          }
          if (Array.isArray((rawVal as any).options)) {
            arg.options = (rawVal as any).options.filter((o: any) => typeof o === "string");
          }
          if (Array.isArray((rawVal as any).disabled_options)) {
            arg.disabledOptions = (rawVal as any).disabled_options.filter((o: any) => typeof o === "string");
          }
          if ((rawVal as any).disabled === true) arg.disabled = true;
          if ((rawVal as any).always_configurable === true) arg.always_configurable = true;

          out.push(arg);
          return;
        }

        out.push({
          property: k,
          type: "str",
          default: valueToDefaultString(rawVal),
          description: "",
        });
      });
      return out;
    }

    return [];
  };

  const resolveVariableBinding = (binding: string): string => {
    const b0 = String(binding || "").trim();
    const b = b0.startsWith("$") ? b0.slice(1) : b0;

    const fs = filterSetRef.current;
    if (!b || !fs) return "";

    const prefixes = [
      "PATIENT_QUERY_",
      "PATIENT_DATA_",
      "OBSERVATION_QUERY_",
      "OBSERVATION_DATA_",
      "OBSERVATION_",
    ] as const;
    const prefix = prefixes.find((p) => b.startsWith(p));
    if (!prefix) return "";

    const rest = b.slice(prefix.length);
    if (!rest) return "";

    const sourceObj =
      prefix === "PATIENT_QUERY_"
        ? parseJson<Record<string, any>>(fs.patientQueryFilters)
        : prefix === "PATIENT_DATA_"
          ? parseJson<Record<string, any>>(fs.patientDataFilters)
          : prefix === "OBSERVATION_QUERY_"
            ? parseJson<Record<string, any>>(fs.observationQueryFilters)
            : prefix === "OBSERVATION_DATA_"
              ? parseJson<Record<string, any>>(fs.observationDataFilters)
              : {
                ...parseJson<Record<string, any>>(fs.observationQueryFilters),
                ...parseJson<Record<string, any>>(fs.observationDataFilters),
              };

    const candidates = normalizeKeyCandidates(rest);
    for (const key of candidates) {
      if (Object.prototype.hasOwnProperty.call(sourceObj, key)) {
        const val = (sourceObj as any)[key];
        const s = stringifyResolved(val);
        if (String(s).trim() !== "") return s;
      }
    }

    return "";
  };

  const getEffectiveArgs = (fnId: string): FunctionArg[] => {
    const base = FUNCTION_METADATA.find((f) => f.id === fnId);
    const baseArgs: FunctionArg[] = (base?.args || []).map((a) => ({ ...a }));

    const variableCfgRaw = customById.variable.get(fnId) || null;
    const variableArgs = normalizeVariableCfgToArgs(variableCfgRaw);

    const overrideCfg = customById.override.get(fnId) || null;

    const byProp = new Map<string, FunctionArg>();
    baseArgs.forEach((a) => byProp.set(a.property, a));

    if (overrideCfg) {
      Object.keys(overrideCfg).forEach((k) => {
        const existing = byProp.get(k);
        if (!existing) return;

        const val = valueToDefaultString((overrideCfg as any)[k]);
        existing.default = val;

        if (existing.type === "select") {
          const opts = Array.isArray(existing.options) ? [...existing.options] : [];
          if (val !== "" && !opts.includes(val)) {
            opts.unshift(val);
          }
          existing.options = opts;
        }

        if (existing.always_configurable !== true) {
          existing.disabled = true;
        }
      });
    }

    if (variableArgs.length > 0) {
      variableArgs.forEach((argDef) => {
        const k = argDef.property;
        const existing = byProp.get(k);

        if (argDef.type === "select") {
          const opts = (argDef.options || []).filter((x) => String(x).trim() !== "");
          const def = valueToDefaultString(argDef.default ?? opts[0] ?? "");

          if (existing) {
            existing.type = "select";
            existing.options = opts;
            existing.disabledOptions = argDef.disabledOptions;
            if (!existing.default || String(existing.default).trim() === "") {
              existing.default = def;
            } else if (existing.default && opts.length > 0 && !opts.includes(existing.default)) {
              existing.default = def;
            }
            if (typeof argDef.description === "string") {
              existing.description = existing.description
                ? `${existing.description}\n${argDef.description}`
                : argDef.description;
            }
            if (argDef.disabled === true) existing.disabled = true;
            return;
          }

          const a: FunctionArg = {
            property: k,
            type: "select",
            options: opts,
            disabledOptions: argDef.disabledOptions,
            default: def,
            description: typeof argDef.description === "string" ? argDef.description : undefined,
            disabled: argDef.disabled === true ? true : undefined,
          };
          byProp.set(k, a);
          baseArgs.push(a);
          return;
        }

        const defRaw = valueToDefaultString(argDef.default ?? "");
        const isBinding = defRaw.startsWith("$");

        if (isBinding) {
          const resolved = resolveVariableBinding(defRaw);
          const shouldDisable = String(resolved).trim() !== "";

          if (existing) {
            if (resolved) {
              existing.default = resolved;
              if (existing.type === "select") {
                const opts = Array.isArray(existing.options) ? [...existing.options] : [];
                if (!opts.includes(resolved)) opts.unshift(resolved);
                existing.options = opts;
              }
            }
            existing.disabled = shouldDisable || existing.disabled === true;
            if (typeof argDef.type === "string") {
              existing.type = argDef.type === "int" ? "int" : "str";
            }
            return;
          }

          const a: FunctionArg = {
            property: k,
            type: argDef.type === "int" ? "int" : "str",
            default: resolved,
            description: `${argDef.description}`,
            disabled: shouldDisable || argDef.disabled === true,
          };
          byProp.set(k, a);
          baseArgs.push(a);
          return;
        }

        const fallback = defRaw;

        if (existing) {
          if (existing.default === undefined || String(existing.default).trim() === "") {
            existing.default = fallback;
          }
          if (typeof argDef.description === "string") {
            existing.description = existing.description
              ? `${existing.description}\n${argDef.description}`
              : argDef.description;
          }
          if (argDef.disabled === true) existing.disabled = true;
          if (typeof argDef.type === "string") {
            existing.type = argDef.type === "int" ? "int" : "str";
          }
          return;
        }

        const a: FunctionArg = {
          property: k,
          type: argDef.type === "int" ? "int" : "str",
          default: fallback,
          description: typeof argDef.description === "string" ? argDef.description : undefined,
          disabled: argDef.disabled === true ? true : undefined,
        };
        byProp.set(k, a);
        baseArgs.push(a);
      });
    }

    return baseArgs;
  };

  const applyProjectForcingToConfig = (
    fnId: string,
    cfg: FunctionConfigProps
  ): FunctionConfigProps => {
    const variableCfgRaw = customById.variable.get(fnId) || null;
    const variableArgs = normalizeVariableCfgToArgs(variableCfgRaw);

    // const overrideCfg = customById.override.get(fnId) || null;

    let changed = false;
    const next: FunctionConfigProps = { ...cfg };

    // const forceVal = (k: string, v: any) => {
    //   const asStr = valueToDefaultString(v);
    //   if (next[k] !== asStr) {
    //     next[k] = asStr;
    //     changed = true;
    //   }
    // };

    // if (overrideCfg) {
    //   Object.keys(overrideCfg).forEach((k) => {
    //     forceVal(k, (overrideCfg as any)[k]);
    //   });
    // }

    if (variableArgs.length > 0) {
      variableArgs.forEach((argDef) => {
        const k = argDef.property;

        if (argDef.type === "select") {
          const opts = (argDef.options || []).filter((x) => String(x).trim() !== "");
          const desired = valueToDefaultString(argDef.default ?? opts[0] ?? "");
          const cur = next[k] ?? "";
          if (!cur || (opts.length > 0 && !opts.includes(cur))) {
            next[k] = desired;
            changed = true;
          }
          return;
        }

        const defRaw = valueToDefaultString(argDef.default ?? "");
        const isBinding = defRaw.startsWith("$");

        if (isBinding) {
          const resolved = resolveVariableBinding(defRaw);
          if (String(resolved).trim() !== "") {
            if (next[k] !== resolved) {
              next[k] = resolved;
              changed = true;
            }
          }
          return;
        }

        const v = valueToDefaultString(argDef.default ?? "");
        const cur = next[k];
        if (cur === undefined || String(cur).trim() === "") {
          if (next[k] !== v) {
            next[k] = v;
            changed = true;
          }
        }
      });
    }

    return changed ? next : cfg;
  };

  const computeDefaults = (fnId: string): FunctionConfigProps => {
    const args = getEffectiveArgs(fnId);
    const init: FunctionConfigProps = {};
    (args || []).forEach((a) => {
      init[a.property] =
        a.type === "select"
          ? a.default ?? a.options?.[0] ?? ""
          : a.default ?? "";
    });
    return applyProjectForcingToConfig(fnId, init);
  };

  useEffect(() => {
    if (!hasFunctionCapabilities) return;

    setSelectedFunctionConfigs((prev) => {
      let anyChanged = false;
      const next: FunctionConfigs = { ...prev };

      Object.keys(next).forEach((fnId) => {
        const configs = next[fnId] || [];
        if (!configs.length) return;

        const updated = configs.map((c) => applyProjectForcingToConfig(fnId, c));
        const sameRef = updated.every((c, i) => c === configs[i]);

        if (!sameRef) {
          next[fnId] = updated;
          anyChanged = true;
        }
      });

      return anyChanged ? next : prev;
    });
  // applyProjectForcingToConfig is intentionally evaluated from the capability/config state above.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasFunctionCapabilities, customById, filterSetKey]);

  useEffect(() => {
    if (!singleFunctionId) return;
    setSelectedFunctionConfigs((prev) => {
      if (prev[singleFunctionId] && prev[singleFunctionId].length > 0) {
        return prev;
      }
      return {
        ...prev,
        [singleFunctionId]: [computeDefaults(singleFunctionId)],
      };
    });
    setActiveConfigIndex((prev) => ({
      ...prev,
      [singleFunctionId]: 0,
    }));
  // computeDefaults is intentionally refreshed by the project/capability inputs above.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [singleFunctionId, hasFunctionCapabilities, project, filterSetKey]);

  const triggerConfigPanelFlash = (functionId: string) => {
    setConfigPanelFlash((prev) => ({
      ...prev,
      [functionId]: true,
    }));
    setTimeout(() => {
      setConfigPanelFlash((prev) => ({
        ...prev,
        [functionId]: false,
      }));
    }, 120);
  };

  const toggleSelection = (id: string) => {
    if (singleFunctionId === id) {
      return;
    }
    setSelectedFunctionConfigs((prev) => {
      if (prev[id] && prev[id].length > 0) {
        const { [id]: _remove, ...rest } = prev;
        return rest;
      }
      return { ...prev, [id]: [computeDefaults(id)] };
    });
    setActiveConfigIndex((prev) => ({
      ...prev,
      [id]: 0,
    }));
  };

  const handleArgChange = (
    functionId: string,
    configIndex: number,
    arg: FunctionArg,
    raw: string
  ) => {
    const v =
      arg.type === "int"
        ? /^-?\d*(\.\d*)?$/.test(raw)
          ? raw
          : ""
        : raw;

    setSelectedFunctionConfigs((prev) => {
      const existingConfigs = prev[functionId] || [];
      const configs =
        existingConfigs.length > 0
          ? [...existingConfigs]
          : [computeDefaults(functionId)];
      const baseConfig: FunctionConfigProps =
        configs[configIndex] || computeDefaults(functionId);
      const updatedConfig: FunctionConfigProps = {
        ...baseConfig,
        [arg.property]: v,
      };
      configs[configIndex] = applyProjectForcingToConfig(functionId, updatedConfig);
      return {
        ...prev,
        [functionId]: configs,
      };
    });
  };

  const handleAddConfig = (functionId: string) => {
    setSelectedFunctionConfigs((prev) => {
      const existingConfigs = prev[functionId] || [];
      const newConfig = computeDefaults(functionId);
      const updated = [...existingConfigs, newConfig];
      const next = {
        ...prev,
        [functionId]: updated,
      };
      setActiveConfigIndex((prevIdx) => ({
        ...prevIdx,
        [functionId]: updated.length - 1,
      }));
      return next;
    });
    triggerConfigPanelFlash(functionId);
  };

  const handleRemoveConfig = (functionId: string, configIndex: number) => {
    setSelectedFunctionConfigs((prev) => {
      const existingConfigs = prev[functionId] || [];
      if (existingConfigs.length <= 1) {
        return prev;
      }
      const updated = existingConfigs.filter((_, idx) => idx !== configIndex);
      const next = {
        ...prev,
        [functionId]: updated,
      };
      setActiveConfigIndex((prevIdx) => {
        const current = prevIdx[functionId] ?? 0;
        let nextIndex = current;
        if (current === configIndex) {
          nextIndex = Math.max(0, current - 1);
        } else if (current > configIndex) {
          nextIndex = current - 1;
        }
        return {
          ...prevIdx,
          [functionId]: nextIndex,
        };
      });
      return next;
    });
    triggerConfigPanelFlash(functionId);
  };

  const toggleTooltip = (functionId: string, property: string) => {
    setOpenTooltips((prev) => {
      const next = { ...prev };
      const set = new Set(next[functionId] ?? []);
      if (set.has(property)) set.delete(property);
      else set.add(property);
      next[functionId] = set;
      return next;
    });
  };

  if (compact) {
    const activeFunctions = gridFunctions;

    return (
      <CompactBanner>
        <div className="duality-weight-600-mb-0p25rem">
          Supported functions:
        </div>
        <hr className="duality-m-0-0-0p4rem-0" />
        <div>
          {activeFunctions.map((fn, idx) => {
            const tooltipText = fn.description;

            return (
              <span
                key={fn.id}
                className="tooltip-inline"
                data-tooltip={fn.disabled ? "Coming soon: " + tooltipText : tooltipText}
              >
                <span style={fn.disabled ? { opacity: 0.4 } : undefined}>
                  {fn.title}
                  {idx < activeFunctions.length - 1 ? ",  " : ""}
                </span>
              </span>
            );
          })}
        </div>
      </CompactBanner>
    );
  }

  const useTwoCardFunctionRowSizing = gridFunctions.length === 2;

  return (
    <div className="function-selector-block-01">
      <h3>Analysis Function Configuration</h3>

      <div className="function-selector-block-02">
        <label className="function-selector-block-03">
          <input
            type="checkbox"
            checked={thresholdCheckEnabled}
            onChange={(e) => setThresholdCheckEnabled(e.target.checked)}
            className="function-selector-input"
          />
          Perform Threshold Samples Check
          <span className="function-selector-block-04">
            <HelpToggle
              open={thresholdHelpOpen}
              onToggle={() => setThresholdHelpOpen((p) => !p)}
              ariaLabel="Info about threshold samples check"
              title="Info about threshold samples check"
            />
          </span>
        </label>

        <HelpPanel open={thresholdHelpOpen} text={THRESHOLD_DESC} />

        {thresholdCheckEnabled && (
          <div
            className="function-selector-block-05"
          >
            <div className="function-selector-shared-01">
              <div
                className="function-selector-shared-02"
              >
                <span
                  className="function-selector-shared-03"
                >
                  Threshold:
                </span>
                <input
                  className="function-selector-shared-04"
                  type="number"
                  min={0}
                  max={20}
                  value={threshold}
                  onChange={(e) => {
                    const value = e.target.value;

                    if (value === "") {
                      setThreshold(0);
                      return;
                    }

                    setThreshold(Math.min(20, Math.max(0, Number(value))));
                  }}
                />
              </div>
            </div>
            <div className="function-selector-shared-01">
              <div
                className="function-selector-shared-02"
              >
                <span
                  className="function-selector-shared-03"
                >
                  Method:
                </span>
                <select
                  value={thresholdMethod}
                  onChange={(e) =>
                    setThresholdMethod(
                      e.currentTarget.value === "PROTECTED"
                        ? "PROTECTED"
                        : "EXPOSED"
                    )
                  }
                  className="function-selector-shared-04"
                >
                  <option value="PROTECTED">PROTECTED</option>
                  <option value="EXPOSED">EXPOSED</option>
                </select>
              </div>
              <div className="function-selector-block-06">
                <div>{THRESHOLD_DESC_PROTECTED}</div>
                <div>{THRESHOLD_DESC_EXPOSED}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div
        className="job-runner-function-grid function-selector-block-07"
        style={{ display: useTwoCardFunctionRowSizing ? "flex" : "grid", gridTemplateColumns: useTwoCardFunctionRowSizing
            ? undefined
            : "repeat(auto-fit, minmax(230px, 1fr))", flexWrap: useTwoCardFunctionRowSizing ? "wrap" : undefined, alignItems: useTwoCardFunctionRowSizing ? "stretch" : undefined }}
      >
        {gridFunctions.map((option) => {
          const configsForFn = selectedFunctionConfigs[option.id] || [];
          const isSelected = !!(configsForFn && configsForFn.length > 0);
          const numConfigs = configsForFn.length;

          const activeIndexRaw =
            activeConfigIndex[option.id] !== undefined
              ? activeConfigIndex[option.id]
              : 0;
          const activeIndex =
            numConfigs > 0
              ? Math.min(Math.max(activeIndexRaw, 0), numConfigs - 1)
              : 0;

          const values = numConfigs > 0 ? configsForFn[activeIndex] || {} : {};
          const panelFlashing = configPanelFlash[option.id] ?? false;

          const fields = getEffectiveArgs(option.id);

          const isSingleForced = singleFunctionId === option.id;
          const removeDisabled = numConfigs <= 1;

          const onCardClick = () => {
            if (option.disabled) return;
            if (isSingleForced) return;
            toggleSelection(option.id);
          };

          const argsWrapWidth = argsWrapWidthByFn[option.id] ?? 0;
          const isWideArgsWrap = argsWrapWidth >= 500;

          return (
            <div
              key={option.id}
              className={[`job-runner-function-card ${option.disabled ? "disabled" : ""}`, "function-selector-block-08"].filter(Boolean).join(" ")}
              onClick={onCardClick}
              onMouseEnter={(e) => {
                if (option.disabled) return;
                const el = e.currentTarget as HTMLDivElement;
                el.style.boxShadow = "0 4px 12px rgba(0, 0, 0, 0.12)";
                el.style.borderColor = "#3F5FFF";
              }}
              onMouseLeave={(e) => {
                if (option.disabled) return;
                const el = e.currentTarget as HTMLDivElement;
                el.style.boxShadow = "0 2px 8px rgba(0,0,0,0.08)";
                el.style.borderColor = "#ccc";
              }}
              style={{ flex: useTwoCardFunctionRowSizing
                  ? option.disabled
                    ? "0 0 230px"
                    : "1 1 230px"
                  : undefined, width: useTwoCardFunctionRowSizing
                  ? option.disabled
                    ? "min(100%, 230px)"
                    : undefined
                  : "100%", minWidth:
                  useTwoCardFunctionRowSizing && !option.disabled ? 230 : undefined, maxWidth:
                  useTwoCardFunctionRowSizing && option.disabled ? 230 : undefined, maxHeight: isSelected ? undefined : 90, border: isSelected ? "1px solid #3F5FFF" : "1px solid #ccc", boxShadow: isSelected
                  ? "0 4px 12px rgba(63,95,255,0.2)"
                  : "0 2px 8px rgba(0,0,0,0.08)", cursor: option.disabled ? "not-allowed" : "pointer", background: option.disabled ? "#f6f7f8" : "#fff" }}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={option.disabled || isSingleForced}
                onClick={(e) => e.stopPropagation()}
                onChange={() => {
                  if (!option.disabled && !isSingleForced) onCardClick();
                }}
                className="function-selector-input-8d224" style={{ cursor:
                    option.disabled || isSingleForced ? "not-allowed" : "pointer" }}
              />

              <div
                className="function-selector-block-09"
              >
                {option.icon && (
                  <img
                    src={"/icons" + option.icon}
                    alt={`${option.title} icon`}
                    className="function-selector-img" style={{ opacity: option.disabled ? 0.5 : 1 }}
                  />
                )}
                <h3
                  className="function-selector-h3" style={{ color: option.disabled ? "#999" : "#3F5FFF" }}
                  title={option.title}
                >
                  {option.title}
                </h3>
              </div>

              <p
                className="function-selector-p" style={{ color: option.disabled ? "#aaa" : "#555", WebkitLineClamp: isSelected ? "unset" : 3, WebkitBoxOrient: "vertical" as any }}
                title={option.description}
              >
                {option.description}
              </p>

              {isSelected && fields.length > 0 && (
                <div
                  className="function-selector-block-10" style={{ transform: panelFlashing ? "scale(1.01)" : "scale(1)" }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div
                    className="function-selector-block-11"
                  >
                    {numConfigs > 0 && (
                      <select
                        value={activeIndex}
                        onChange={(e) => {
                          e.stopPropagation();
                          const idx = parseInt(e.currentTarget.value, 10);
                          setActiveConfigIndex((prev) => ({
                            ...prev,
                            [option.id]: isNaN(idx) ? 0 : idx,
                          }));
                          triggerConfigPanelFlash(option.id);
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="function-selector-select"
                      >
                        {configsForFn.map((_, idx) => (
                          <option key={idx} value={idx}>
                            {`Configuration ${idx + 1}`}
                          </option>
                        ))}
                      </select>
                    )}

                    <>
                      <button
                        className="secondary-button function-selector-add-configuration"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleAddConfig(option.id);
                        }}
                        
                        aria-label="Add configuration"
                        title="Add configuration"
                      >
                        +
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (!removeDisabled) {
                            handleRemoveConfig(option.id, activeIndex);
                          }
                        }}
                        disabled={removeDisabled}
                        className="function-selector-remove-configuration" style={{ opacity: removeDisabled ? 0.5 : 1, cursor: removeDisabled ? "not-allowed" : "pointer" }}
                        aria-label="Remove configuration"
                        title="Remove configuration"
                      >
                        –
                      </button>
                    </>
                  </div>

                  <div className="function-selector-block-12">
                    <div
                      ref={(el) => {
                        argsWrapRefByFn.current[option.id] = el;
                      }}
                      onScroll={() => updateScrollChevron(option.id)}
                      className="function-selector-block-13" style={{ flexDirection: isWideArgsWrap ? "row" : "column", flexWrap: isWideArgsWrap ? "wrap" : "nowrap", borderBottom: showScrollChevronByFn[option.id] ? "1px solid #ccc" : "" }}
                    >
                      {fields.map((arg) => {
                        const v = values[arg.property] ?? "";
                        const tooltipOpen = (openTooltips[option.id]?.has(arg.property) ??
                          false) as boolean;
                        const placeholder =
                          arg.default ?? (arg.type === "int" ? "0" : "val");

                        const forcedDisabled = arg.disabled === true;
                        const argDisabled = forcedDisabled;

                        return (
                          <div
                            key={arg.property}
                            style={
                              isWideArgsWrap
                                ? { flex: "1 1 420px", minWidth: 420 }
                                : { width: "100%" }
                            }
                          >
                            <div
                              className="function-selector-block-14"
                            >
                              <label
                                htmlFor={`${option.id}-${arg.property}`}
                                className="function-selector-block-15"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {arg.property}
                              </label>

                              {arg.type === "select" && (arg.options?.length ?? 0) > 0 ? (
                                <select
                                  id={`${option.id}-${arg.property}`}
                                  className="input-compact"
                                  disabled={argDisabled}
                                  value={v}
                                  onChange={(e) =>
                                    handleArgChange(
                                      option.id,
                                      activeIndex,
                                      arg,
                                      e.currentTarget.value
                                    )
                                  }
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {v === "" && (
                                    <option value="" disabled hidden>
                                      {placeholder || "select"}
                                    </option>
                                  )}
                                  {arg.options!.map((opt) => (
                                    <option
                                      key={opt}
                                      value={opt}
                                      disabled={arg.disabledOptions?.includes(opt) ?? false}
                                    >
                                      {opt}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <input
                                  disabled={argDisabled}
                                  id={`${option.id}-${arg.property}`}
                                  type={arg.type === "int" ? "number" : "text"}
                                  inputMode={arg.type === "int" ? "decimal" : "text"}
                                  step={arg.type === "int" ? "any" : undefined}
                                  pattern={
                                    arg.type === "int"
                                      ? "^-?\\d*(\\.\\d*)?$"
                                      : undefined
                                  }
                                  placeholder={placeholder}
                                  value={v}
                                  onChange={(e) =>
                                    handleArgChange(
                                      option.id,
                                      activeIndex,
                                      arg,
                                      e.currentTarget.value
                                    )
                                  }
                                  onClick={(e) => e.stopPropagation()}
                                  className="input-compact"
                                />
                              )}

                              {arg.description ? (
                                <span onClick={(e) => e.stopPropagation()}>
                                  <HelpToggle
                                    open={tooltipOpen}
                                    onToggle={() => toggleTooltip(option.id, arg.property)}
                                    ariaLabel={`Info about ${arg.property}`}
                                    title={`Info about ${arg.property}`}
                                  />
                                </span>
                              ) : (
                                <span />
                              )}
                            </div>

                            {arg.description && (
                              <div onClick={(e) => e.stopPropagation()}>
                                <HelpPanel
                                  open={tooltipOpen}
                                  text={
                                    <span>
                                      {String(arg.description)
                                        .replace(/\r\n/g, "\n")
                                        .replace(/\n\r/g, "\n")
                                        .split("\n")
                                        .map((line, idx) => (
                                          <React.Fragment key={idx}>
                                            {line}
                                            <br />
                                          </React.Fragment>
                                        ))}
                                    </span>
                                  }
                                />
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {showScrollChevronByFn[option.id] && (
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          const el = argsWrapRefByFn.current[option.id];
                          if (el) {
                            el.scrollTo({
                              top: el.scrollHeight,
                              behavior: "smooth",
                            });
                          }
                        }}
                        className="function-selector-block-16"
                      >
                        <ChevronDown />
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default FunctionSelector;