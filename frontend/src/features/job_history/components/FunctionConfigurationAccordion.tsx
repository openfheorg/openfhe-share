import React, { useEffect, useMemo, useRef, useState } from "react";
import { Project } from "../../../types/Project";
import AbstractAccordion from "../../../components/AbstractAccordion";

interface ComputationSettingsProps {
  config?: Record<string, any> | null;
  project: Project;
  functionName?: string | null;
}

const labelStyle: React.CSSProperties = {
  fontSize: "0.8rem",
  whiteSpace: "nowrap",
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis"
};

const valueStyle: React.CSSProperties = {
  fontSize: "0.8rem",
  fontWeight: 600,
  minWidth: 0,
  wordBreak: "break-word"
};

const FunctionConfigurationAccordion: React.FC<ComputationSettingsProps> = ({
  config,
  project,
  functionName
}) => {
  const fixed = useMemo(() => {
    const byFn: Record<string, Set<string>> = {};
    const all = new Set<string>();
    const fns = (project as any)?.functions;
    if (!Array.isArray(fns)) return { byFn, all };

    for (const f of fns) {
      if (!f || typeof f !== "object") continue;
      const fnName = typeof (f as any).function === "string" ? (f as any).function.trim() : "";
      if (!fnName) continue;

      const fixedObj = (f as any).custom_configuration_fixed;
      if (!fixedObj || typeof fixedObj !== "object" || Array.isArray(fixedObj)) continue;

      const keys = Object.keys(fixedObj).map((k) => String(k));
      byFn[fnName.toUpperCase()] = new Set(keys);
      for (const k of keys) all.add(k);
    }

    return { byFn, all };
  }, [project]);

  const fnUpper = String(functionName ?? "").trim().toUpperCase();
  const fixedSet = (fnUpper && fixed.byFn[fnUpper]) ? fixed.byFn[fnUpper] : fixed.all;

  const hasConfigObject = !!config && typeof config === "object" && !Array.isArray(config);
  const gridRef = useRef<HTMLDivElement>(null);
  const [columnCount, setColumnCount] = useState(1);

  const entries = useMemo(() => {
    if (!hasConfigObject) return [];
    return Object.entries(config as Record<string, any>).filter(([k]) => {
      const key = String(k);
      if (key === "custom_configuration_fixed") return false;
      return !fixedSet.has(key);
    });
  }, [config, hasConfigObject, fixedSet]);

  useEffect(() => {
    const node = gridRef.current;
    if (!node) return;

    const updateColumnCount = () => {
      const width = node.getBoundingClientRect().width;
      const nextColumnCount = Math.max(1, Math.min(entries.length, Math.floor((width + 20) / 300)));
      setColumnCount((prev) => (prev === nextColumnCount ? prev : nextColumnCount));
    };

    updateColumnCount();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateColumnCount);
      return () => window.removeEventListener("resize", updateColumnCount);
    }

    const observer = new ResizeObserver(updateColumnCount);
    observer.observe(node);
    return () => observer.disconnect();
  }, [entries.length]);

  const lastRowStartIndex = entries.length - (entries.length % columnCount || columnCount);

  if (!hasConfigObject || entries.length === 0) {
    return null;
  }

  return (
    <AbstractAccordion
      title="Function Configuration"
      titleTooltip="Show/Hide Function Configuration"
      defaultOpen={true}
      containerStyle={{ maxWidth: "100%" }}
      bodyStyle={{
        borderRadius: 4,
        border: "1px solid #ccc",
        marginTop: "4px",
        padding: "0.35rem 0.5rem 0.5rem",
        maxWidth: "100%",
        boxSizing: "border-box",
        backgroundColor: "#f9fafb"
      }}
    >
      <div
        ref={gridRef}
        className="function-configuration-accordion-grid"
      >
        {entries.map(([k, v], index) => (
          <div
            key={String(k)}
            className="function-configuration-accordion-block-01" style={{ borderBottom: index >= lastRowStartIndex ? "none" : "1px solid #ccc" }}
          >
            <div style={labelStyle}>{String(k)}:</div>
            <div style={valueStyle}>{String(v)}</div>
          </div>
        ))}
      </div>
    </AbstractAccordion>
  );
};

export default FunctionConfigurationAccordion;
