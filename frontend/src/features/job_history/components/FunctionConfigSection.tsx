import React, { JSX } from "react";
import { Project } from "../../../types/Project";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { NVFlareJob } from "../../../types/JobsDataTypes";
import { formatFunctionName } from "../../../components/FunctionSelector";

const thMini: React.CSSProperties = {
  textAlign: "left",
  fontWeight: 600,
  fontSize: 11,
  padding: "3px 4px",
  borderBottom: "1px solid #E5E7EB"
};

const tdMini: React.CSSProperties = {
  fontSize: 12,
  padding: "5px 6px",
  borderBottom: "1px solid #F3F4F6",
  verticalAlign: "top",
  wordBreak: "break-word"
};

interface FunctionConfigSectionProps {
  job: NVFlareJob;
  jobKey: string;
  isOpen: boolean;
  onToggle: () => void;
  project: Project;
}

function getFixedKeysByFnUpper(project: Project): Record<string, Set<string>> {
  const out: Record<string, Set<string>> = {};
  const fns = (project as any)?.functions;

  if (!Array.isArray(fns)) return out;

  for (const f of fns) {
    const fnName = typeof f?.function === "string" ? f.function.trim() : "";
    if (!fnName) continue;

    const fixed = f?.custom_configuration_fixed;
    if (fixed && typeof fixed === "object" && !Array.isArray(fixed)) {
      out[fnName.toUpperCase()] = new Set(Object.keys(fixed as Record<string, any>).map((k) => String(k)));
    }
  }

  return out;
}

export default function FunctionConfigSection({
  job,
  jobKey,
  isOpen,
  onToggle,
  project
}: FunctionConfigSectionProps) {
  const groupBorder = "1px solid #000";

  const fixedKeysByFnUpper = React.useMemo(() => getFixedKeysByFnUpper(project), [project]);

  return (
    <AbstractAccordion
      title="Function Configurations"
      titleTooltip="Show/Hide Function Configs"
      isOpen={isOpen}
      onToggle={onToggle}
      stopPropagation={true}
      containerStyle={{ padding: "5px 0" }}
      bodyStyle={{
        borderLeft: "1px solid black",
        borderTop: "1px solid black",
        borderRight: "1px solid black",
        marginTop: "5px"
      }}
    >
      {job.functions_map && Object.keys(job.functions_map).length > 0 ? (
        <table className="function-config-section-block-01">
          <thead>
            <tr>
              <th style={thMini}>Function</th>
              <th style={thMini}>Property</th>
              <th style={thMini}>Value</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(job.functions_map)
              .sort()
              .flatMap((fn) => {
                const rawCfg = job.functions_map?.[fn];

                const configs: Record<string, any>[] = Array.isArray(rawCfg)
                  ? rawCfg
                  : rawCfg && typeof rawCfg === "object"
                    ? [rawCfg as Record<string, any>]
                    : [];

                const fixedKeys = fixedKeysByFnUpper[String(fn).toUpperCase()] || new Set<string>();

                if (configs.length === 0) {
                  return (
                    <tr key={fn}>
                      <td style={{ ...tdMini, borderBottom: groupBorder }}>{formatFunctionName(fn)}</td>
                      <td style={{ ...tdMini, borderBottom: groupBorder }}>--</td>
                      <td style={{ ...tdMini, borderBottom: groupBorder }}>--</td>
                    </tr>
                  );
                }

                const rows: JSX.Element[] = [];

                configs.forEach((cfg, cfgIndex) => {
                  const entriesAll = Object.entries(cfg || {}).sort((a, b) => a[0].localeCompare(b[0]));
                  const entries = entriesAll.filter(([k]) => !fixedKeys.has(String(k)));

                  const label =
                    cfgIndex === 0 ? formatFunctionName(fn) : `${formatFunctionName(fn)} ${cfgIndex + 1}`;

                  if (entries.length === 0) {
                    rows.push(
                      <tr key={`${fn}-cfg-${cfgIndex}`}>
                        <td style={{ ...tdMini, borderBottom: groupBorder }}>{label}</td>
                        <td style={{ ...tdMini, borderBottom: groupBorder }}>--</td>
                        <td style={{ ...tdMini, borderBottom: groupBorder }}>--</td>
                      </tr>
                    );
                    return;
                  }

                  entries.forEach(([k, v], entryIdx) => {
                    const isLast = entryIdx === entries.length - 1;
                    rows.push(
                      <tr key={`${fn}-cfg-${cfgIndex}-${k}`}>
                        <td style={{ ...tdMini, borderBottom: isLast ? groupBorder : 0 }}>
                          {entryIdx === 0 ? label : ""}
                        </td>
                        <td style={{ ...tdMini, ...(isLast ? { borderBottom: groupBorder } : {}) }}>{k}</td>
                        <td style={{ ...tdMini, ...(isLast ? { borderBottom: groupBorder } : {}) }}>
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
      ) : (
        <div className="function-config-section-block-02">
          No function configurations recorded.
        </div>
      )}
    </AbstractAccordion>
  );
}
