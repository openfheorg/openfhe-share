import React, { useEffect, useMemo, useState } from "react";
import { Project } from "../../../types/Project";


interface OptionConfig {
  label?: string;
  value?: string | number | boolean;
  [key: string]: any;
}

interface ControlConfig {
  id?: string;
  field?: string;
  label?: string;
  type?: string;
  default?: any;
  options?: OptionConfig[];
  fhir?: Record<string, any>;
  query?: Record<string, any>;
  save?: Record<string, any>;
  localPass?: Record<string, any>;
  ui?: Record<string, any>;
  [key: string]: any;
}

interface ResolverConfig {
  [key: string]: any;
}

interface ResourceConfig {
  type?: string;
  [key: string]: any;
}

interface FilterConfigFile {
  version?: string;
  resource?: ResourceConfig;
  controls?: ControlConfig[];
  defaultsResolver?: ResolverConfig;
  localPass?: Record<string, any>;
  [key: string]: any;
}

interface FilterManagerPageProps {
  project: Project;
  fhirServer?: string | null;
}

interface LoadedFilterConfig {
  key: string;
  title: string;
  description: string;
  path: string;
  systemScope: string;
  loadedConfig: FilterConfigFile | null;
  editedConfig: FilterConfigFile | null;
  loading: boolean;
  error: string | null;
  copied: boolean;
}

const FILTER_CONFIGS: Array<{
  key: string;
  title: string;
  description: string;
  path: string;
  systemScope: string;
}> = [
  {
    key: "patientQuery",
    title: "Patient Query",
    description: "DEFAULT filter-system Patient query controls.",
    path: "/filters/default/patient/patient_query.json",
    systemScope: "DEFAULT"
  },
  {
    key: "observationQuery",
    title: "Observation Query",
    description: "DEFAULT filter-system Observation query controls.",
    path: "/filters/default/observation/observation_query.json",
    systemScope: "DEFAULT"
  },
  {
    key: "observationData",
    title: "Observation Data",
    description: "DEFAULT filter-system Observation local-pass and metrics controls.",
    path: "/filters/default/observation/observation_data.json",
    systemScope: "DEFAULT"
  }
];

function prettyJson(value: any): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "";
  }
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function parseJsonOrFallback<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function fromJsonInput(raw: string): any {
  const trimmed = raw.trim();
  if (!trimmed) {
    return "";
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return raw;
  }
}

function getProjectLabel(project: Project): string {
  return (project as any)?.name || (project as any)?.project_name || project?.id || "Unknown Project";
}

const cardStyle: React.CSSProperties = {
  background: "#ffffff",
  border: "1px solid #ccc",
  borderRadius: 4,
  padding: "1rem",
  marginBottom: "1.5rem"
};

const labelStyle: React.CSSProperties = {
  fontWeight: 600
};

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "220px 1fr",
  gap: "0.75rem 1rem",
  alignItems: "start"
};

const FilterManagerPage: React.FC<FilterManagerPageProps> = ({ project, fhirServer }) => {
  const [configs, setConfigs] = useState<Record<string, LoadedFilterConfig>>({});

  useEffect(() => {
    let active = true;

    async function loadConfigs() {
      const initialState: Record<string, LoadedFilterConfig> = {};
      for (const cfg of FILTER_CONFIGS) {
        initialState[cfg.key] = {
          ...cfg,
          loadedConfig: null,
          editedConfig: null,
          loading: true,
          error: null,
          copied: false
        };
      }

      if (active) {
        setConfigs(initialState);
      }

      await Promise.all(
        FILTER_CONFIGS.map(async (cfg) => {
          try {
            const response = await fetch(cfg.path, { cache: "no-store" });
            if (!response.ok) {
              throw new Error(`Failed to load config (${response.status})`);
            }

            const data = await response.json();

            if (!active) {
              return;
            }

            setConfigs((prev) => ({
              ...prev,
              [cfg.key]: {
                ...prev[cfg.key],
                loadedConfig: data,
                editedConfig: data,
                loading: false,
                error: null
              }
            }));
          } catch (err: any) {
            if (!active) {
              return;
            }

            setConfigs((prev) => ({
              ...prev,
              [cfg.key]: {
                ...prev[cfg.key],
                loading: false,
                error: err?.message || "Failed to load config."
              }
            }));
          }
        })
      );
    }

    loadConfigs();

    return () => {
      active = false;
    };
  }, []);

  const orderedConfigs = useMemo(() => {
    return FILTER_CONFIGS.map((cfg) => configs[cfg.key]).filter(Boolean) as LoadedFilterConfig[];
  }, [configs]);

  function updateConfigRoot(configKey: string, key: keyof FilterConfigFile, value: any) {
    setConfigs((prev) => {
      const current = prev[configKey];
      if (!current?.editedConfig) {
        return prev;
      }

      return {
        ...prev,
        [configKey]: {
          ...current,
          editedConfig: {
            ...current.editedConfig,
            [key]: value
          }
        }
      };
    });
  }

  function updateControl(configKey: string, index: number, updater: (current: ControlConfig) => ControlConfig) {
    setConfigs((prev) => {
      const current = prev[configKey];
      const editedConfig = current?.editedConfig;
      if (!current || !editedConfig) {
        return prev;
      }

      const controls: ControlConfig[] = Array.isArray(editedConfig.controls) ? [...editedConfig.controls] : [];
      const currentControl: ControlConfig = controls[index] || {};
      controls[index] = updater(currentControl);

      return {
        ...prev,
        [configKey]: {
          ...current,
          editedConfig: {
            ...editedConfig,
            controls
          }
        }
      };
    });
  }

  function updateOptions(configKey: string, index: number, raw: string) {
    setConfigs((prev) => {
      const current = prev[configKey];
      const editedConfig = current?.editedConfig;
      if (!current || !editedConfig) {
        return prev;
      }

      const controls: ControlConfig[] = Array.isArray(editedConfig.controls) ? [...editedConfig.controls] : [];
      const currentControl: ControlConfig = controls[index] || {};
      const fallback: OptionConfig[] = Array.isArray(currentControl.options) ? currentControl.options : [];
      const options: OptionConfig[] = parseJsonOrFallback<OptionConfig[]>(raw, fallback);

      controls[index] = {
        ...currentControl,
        options
      };

      return {
        ...prev,
        [configKey]: {
          ...current,
          editedConfig: {
            ...editedConfig,
            controls
          }
        }
      };
    });
  }

  function handleReset(configKey: string) {
    setConfigs((prev) => {
      const current = prev[configKey];
      if (!current?.loadedConfig) {
        return prev;
      }

      return {
        ...prev,
        [configKey]: {
          ...current,
          editedConfig: deepClone(current.loadedConfig)
        }
      };
    });
  }

  async function handleCopyJson(configKey: string) {
    const current = configs[configKey];
    if (!current?.editedConfig) {
      return;
    }

    try {
      await navigator.clipboard.writeText(JSON.stringify(current.editedConfig, null, 2));
      setConfigs((prev) => ({
        ...prev,
        [configKey]: {
          ...prev[configKey],
          copied: true
        }
      }));

      window.setTimeout(() => {
        setConfigs((prev) => {
          const next = prev[configKey];
          if (!next) {
            return prev;
          }

          return {
            ...prev,
            [configKey]: {
              ...next,
              copied: false
            }
          };
        });
      }, 1500);
    } catch {
    }
  }

  return (
    <div className="page-container">
      <div className="child-container-results-page">
        <div style={cardStyle}>
          <div className="duality-d-grid-grid-cols-1fr-1fr-gap-1rem">
            <div>
              <div className="duality-weight-700-mb-0p35rem">Project</div>
              <div>{getProjectLabel(project)}</div>
            </div>

            <div>
              <div className="duality-weight-700-mb-0p35rem">FHIR Server</div>
              <div>{fhirServer || "No FHIR server URL provided"}</div>
            </div>
          </div>
        </div>

        <div style={cardStyle}>
          <div className="duality-fs-18px-weight-700-mb-0p35rem">Filter Manager</div>
          <div className="duality-text-555">
            Manager for DEFAULT filter-system configs. This page loads Patient and Observation config files and lets users reshape controls, defaults, query metadata, save targets, and local-pass logic to match their data.
          </div>
        </div>

        {orderedConfigs.map((configState) => {
          const edited: FilterConfigFile | null = configState.editedConfig;
          const resource: ResourceConfig = edited?.resource || {};
          const defaultsResolver: ResolverConfig = edited?.defaultsResolver || {};
          const localPass: Record<string, any> = edited?.localPass || {};
          const controls: ControlConfig[] = edited && Array.isArray(edited?.controls) ? edited.controls : [];

          return (
            <div key={configState.key} style={cardStyle}>
              <div className="duality-d-flex-justify-space-between-gap-1rem">
                <div>
                  <div className="duality-fs-18px-weight-700-mb-0p35rem">{configState.title}</div>
                  <div className="duality-text-555-mb-0p35rem">{configState.description}</div>
                  <div className="duality-fs-13px-text-666">
                    Scope: {configState.systemScope} | Path: {configState.path}
                  </div>
                </div>

                {!configState.loading && !configState.error && edited && (
                  <div className="duality-d-flex-gap-0p75rem-wrap-wrap">
                    <button className="secondary-button" onClick={() => handleReset(configState.key)}>
                      Reset to Loaded Config
                    </button>
                    <button onClick={() => handleCopyJson(configState.key)}>
                      {configState.copied ? "Copied" : "Copy JSON"}
                    </button>
                  </div>
                )}
              </div>

              {configState.loading && (
                <div className="duality-mt-1">
                  Loading config...
                </div>
              )}

              {configState.error && (
                <div className="filter-manager-page-block-01">
                  {configState.error}
                </div>
              )}

              {!configState.loading && !configState.error && edited && (
                <>
                  <div className="duality-mt-1" style={{ ...gridStyle }}>
                    <label style={labelStyle}>Version</label>
                    <input
                      type="text"
                      value={edited.version || ""}
                      onChange={(e) => updateConfigRoot(configState.key, "version", e.target.value)}
                    />

                    <label style={labelStyle}>Resource Type</label>
                    <input
                      type="text"
                      value={resource.type || ""}
                      onChange={(e) =>
                        updateConfigRoot(configState.key, "resource", {
                          ...resource,
                          type: e.target.value
                        })
                      }
                    />

                    <label style={labelStyle}>Additional Resource JSON</label>
                    <textarea
                      rows={6}
                      value={prettyJson(
                        Object.fromEntries(Object.entries(resource).filter(([key]) => key !== "type"))
                      )}
                      onChange={(e) => {
                        const extra = parseJsonOrFallback<Record<string, any>>(
                          e.target.value,
                          Object.fromEntries(Object.entries(resource).filter(([key]) => key !== "type"))
                        );

                        updateConfigRoot(configState.key, "resource", {
                          ...extra,
                          type: resource.type
                        });
                      }}
                    />

                    {"defaultsResolver" in edited && (
                      <>
                        <label style={labelStyle}>Defaults Resolver JSON</label>
                        <textarea
                          rows={8}
                          value={prettyJson(defaultsResolver)}
                          onChange={(e) =>
                            updateConfigRoot(
                              configState.key,
                              "defaultsResolver",
                              parseJsonOrFallback<Record<string, any>>(e.target.value, defaultsResolver)
                            )
                          }
                        />
                      </>
                    )}

                    {"localPass" in edited && (
                      <>
                        <label style={labelStyle}>Local Pass JSON</label>
                        <textarea
                          rows={12}
                          value={prettyJson(localPass)}
                          onChange={(e) =>
                            updateConfigRoot(
                              configState.key,
                              "localPass",
                              parseJsonOrFallback<Record<string, any>>(e.target.value, localPass)
                            )
                          }
                        />
                      </>
                    )}
                  </div>

                  <div className="filter-manager-page-block-02">
                    <div className="duality-fs-16px-weight-700-mb-1rem">Controls</div>

                    {controls.length === 0 && (
                      <div className="duality-text-666">No controls found in this config.</div>
                    )}

                    {controls.map((control, index) => {
                      const extraJson: ControlConfig = { ...control };
                      delete extraJson.id;
                      delete extraJson.field;
                      delete extraJson.label;
                      delete extraJson.type;
                      delete extraJson.default;
                      delete extraJson.options;
                      delete extraJson.fhir;
                      delete extraJson.query;
                      delete extraJson.save;
                      delete extraJson.localPass;
                      delete extraJson.ui;

                      return (
                        <div key={`${configState.key}-${index}-${control.id || "control"}`} style={{ ...cardStyle, marginBottom: "1rem" }}>
                          <div className="duality-fs-16px-weight-700-mb-1rem">
                            {control.label || control.id || `Control ${index + 1}`}
                          </div>

                          <div style={gridStyle}>
                            <label style={labelStyle}>ID</label>
                            <input
                              type="text"
                              value={control.id || ""}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  id: e.target.value
                                }))
                              }
                            />

                            <label style={labelStyle}>Field</label>
                            <input
                              type="text"
                              value={control.field || ""}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  field: e.target.value
                                }))
                              }
                            />

                            <label style={labelStyle}>Label</label>
                            <input
                              type="text"
                              value={control.label || ""}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  label: e.target.value
                                }))
                              }
                            />

                            <label style={labelStyle}>Type</label>
                            <input
                              type="text"
                              value={control.type || ""}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  type: e.target.value
                                }))
                              }
                            />

                            <label style={labelStyle}>Default Value</label>
                            <textarea
                              rows={3}
                              value={
                                typeof control.default === "string"
                                  ? control.default
                                  : prettyJson(control.default)
                              }
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  default: fromJsonInput(e.target.value)
                                }))
                              }
                            />

                            <label style={labelStyle}>Options JSON</label>
                            <textarea
                              rows={8}
                              value={prettyJson(control.options || [])}
                              onChange={(e) => updateOptions(configState.key, index, e.target.value)}
                            />

                            <label style={labelStyle}>FHIR JSON</label>
                            <textarea
                              rows={7}
                              value={prettyJson(control.fhir || {})}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  fhir: parseJsonOrFallback<Record<string, any>>(e.target.value, current.fhir || {})
                                }))
                              }
                            />

                            <label style={labelStyle}>Query JSON</label>
                            <textarea
                              rows={7}
                              value={prettyJson(control.query || {})}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  query: parseJsonOrFallback<Record<string, any>>(e.target.value, current.query || {})
                                }))
                              }
                            />

                            <label style={labelStyle}>Save JSON</label>
                            <textarea
                              rows={7}
                              value={prettyJson(control.save || {})}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  save: parseJsonOrFallback<Record<string, any>>(e.target.value, current.save || {})
                                }))
                              }
                            />

                            <label style={labelStyle}>Local Pass JSON</label>
                            <textarea
                              rows={6}
                              value={prettyJson(control.localPass || {})}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  localPass: parseJsonOrFallback<Record<string, any>>(e.target.value, current.localPass || {})
                                }))
                              }
                            />

                            <label style={labelStyle}>UI JSON</label>
                            <textarea
                              rows={5}
                              value={prettyJson(control.ui || {})}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => ({
                                  ...current,
                                  ui: parseJsonOrFallback<Record<string, any>>(e.target.value, current.ui || {})
                                }))
                              }
                            />

                            <label style={labelStyle}>Additional JSON</label>
                            <textarea
                              rows={8}
                              value={prettyJson(extraJson)}
                              onChange={(e) =>
                                updateControl(configState.key, index, (current) => {
                                  const parsed = parseJsonOrFallback<Record<string, any>>(e.target.value, extraJson);
                                  return {
                                    ...parsed,
                                    id: current.id,
                                    field: current.field,
                                    label: current.label,
                                    type: current.type,
                                    default: current.default,
                                    options: current.options,
                                    fhir: current.fhir,
                                    query: current.query,
                                    save: current.save,
                                    localPass: current.localPass,
                                    ui: current.ui
                                  };
                                })
                              }
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="filter-manager-page-block-03">
                    Quick view: controls={controls.length}
                    {" | "}
                    defaultsResolverKeys={Object.keys(defaultsResolver).length}
                    {" | "}
                    localPassKeys={Object.keys(localPass).length}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default FilterManagerPage;