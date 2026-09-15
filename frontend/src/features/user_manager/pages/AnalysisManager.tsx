import React, { useEffect, useMemo, useState } from "react";
import { Project } from "../../../types/Project";

interface AnalysisManagerPageProps {
  project: Project;
  fhirServer?: string | null;
}

interface QueryResourceParam {
  name?: string;
  value?: string | number | boolean;
  values?: Array<string | number | boolean>;
  [key: string]: any;
}

interface QueryResourceConfig {
  resourceType?: string;
  params?: QueryResourceParam[];
  [key: string]: any;
}

interface QueryColumnConfig {
  resources?: QueryResourceConfig[];
  [key: string]: any;
}

interface QueryPropertyConfig {
  columns?: Record<string, QueryColumnConfig>;
  [key: string]: any;
}

interface QueryComputationConfig {
  properties?: Record<string, QueryPropertyConfig>;
  [key: string]: any;
}

interface AnalysisQueryConfigFile {
  version?: string;
  computations?: Record<string, QueryComputationConfig>;
  [key: string]: any;
}

interface DataColumnConfig {
  resourceType?: string;
  extractor?: string;
  args?: Record<string, any>;
  [key: string]: any;
}

interface DataPropertyConfig {
  columns?: Record<string, DataColumnConfig>;
  [key: string]: any;
}

interface DataComputationConfig {
  properties?: Record<string, DataPropertyConfig>;
  [key: string]: any;
}

interface AnalysisDataConfigFile {
  version?: string;
  computations?: Record<string, DataComputationConfig>;
  [key: string]: any;
}

interface LoadedAnalysisConfigs {
  loadedQueryConfig: AnalysisQueryConfigFile | null;
  editedQueryConfig: AnalysisQueryConfigFile | null;
  loadedDataConfig: AnalysisDataConfigFile | null;
  editedDataConfig: AnalysisDataConfigFile | null;
  loading: boolean;
  error: string | null;
  copiedQuery: boolean;
  copiedData: boolean;
}

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

function getProjectKey(project: Project): string {
  return String(project?.id || "project1");
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

const AnalysisManagerPage: React.FC<AnalysisManagerPageProps> = ({ project, fhirServer }) => {
  const projectKey = getProjectKey(project);
  const queryPath = `/analysis_config/analysis_query.json`;
  const dataPath = `/analysis_config/analysis_data.json`;

  const [state, setState] = useState<LoadedAnalysisConfigs>({
    loadedQueryConfig: null,
    editedQueryConfig: null,
    loadedDataConfig: null,
    editedDataConfig: null,
    loading: true,
    error: null,
    copiedQuery: false,
    copiedData: false
  });

  useEffect(() => {
    let active = true;

    async function loadConfigs() {
      try {
        setState((prev) => ({
          ...prev,
          loading: true,
          error: null
        }));

        const [queryResponse, dataResponse] = await Promise.all([
          fetch(queryPath, { cache: "no-store" }),
          fetch(dataPath, { cache: "no-store" })
        ]);

        if (!queryResponse.ok) {
          throw new Error(`Failed to load analysis query config (${queryResponse.status})`);
        }

        if (!dataResponse.ok) {
          throw new Error(`Failed to load analysis data config (${dataResponse.status})`);
        }

        const [queryConfig, dataConfig] = await Promise.all([
          queryResponse.json(),
          dataResponse.json()
        ]);

        if (!active) {
          return;
        }

        setState((prev) => ({
          ...prev,
          loadedQueryConfig: queryConfig,
          editedQueryConfig: queryConfig,
          loadedDataConfig: dataConfig,
          editedDataConfig: dataConfig,
          loading: false,
          error: null
        }));
      } catch (err: any) {
        if (!active) {
          return;
        }

        setState((prev) => ({
          ...prev,
          loading: false,
          error: err?.message || "Failed to load analysis configs."
        }));
      }
    }

    loadConfigs();

    return () => {
      active = false;
    };
  }, [queryPath, dataPath]);

  const computationKeys = useMemo(() => {
    const queryKeys = Object.keys(state.editedQueryConfig?.computations || {});
    const dataKeys = Object.keys(state.editedDataConfig?.computations || {});
    return Array.from(new Set([...queryKeys, ...dataKeys]));
  }, [state.editedQueryConfig, state.editedDataConfig]);

  function updateQueryRoot(key: keyof AnalysisQueryConfigFile, value: any) {
    setState((prev) => {
      if (!prev.editedQueryConfig) {
        return prev;
      }

      return {
        ...prev,
        editedQueryConfig: {
          ...prev.editedQueryConfig,
          [key]: value
        }
      };
    });
  }

  function updateDataRoot(key: keyof AnalysisDataConfigFile, value: any) {
    setState((prev) => {
      if (!prev.editedDataConfig) {
        return prev;
      }

      return {
        ...prev,
        editedDataConfig: {
          ...prev.editedDataConfig,
          [key]: value
        }
      };
    });
  }

  function updateQueryComputationProperty(
    computationKey: string,
    propertyKey: string,
    updater: (current: QueryPropertyConfig) => QueryPropertyConfig
  ) {
    setState((prev) => {
      if (!prev.editedQueryConfig) {
        return prev;
      }

      const computations = prev.editedQueryConfig.computations || {};
      const computation = computations[computationKey] || {};
      const properties = computation.properties || {};
      const currentProperty = properties[propertyKey] || {};

      return {
        ...prev,
        editedQueryConfig: {
          ...prev.editedQueryConfig,
          computations: {
            ...computations,
            [computationKey]: {
              ...computation,
              properties: {
                ...properties,
                [propertyKey]: updater(currentProperty)
              }
            }
          }
        }
      };
    });
  }

  function updateDataComputationProperty(
    computationKey: string,
    propertyKey: string,
    updater: (current: DataPropertyConfig) => DataPropertyConfig
  ) {
    setState((prev) => {
      if (!prev.editedDataConfig) {
        return prev;
      }

      const computations = prev.editedDataConfig.computations || {};
      const computation = computations[computationKey] || {};
      const properties = computation.properties || {};
      const currentProperty = properties[propertyKey] || {};

      return {
        ...prev,
        editedDataConfig: {
          ...prev.editedDataConfig,
          computations: {
            ...computations,
            [computationKey]: {
              ...computation,
              properties: {
                ...properties,
                [propertyKey]: updater(currentProperty)
              }
            }
          }
        }
      };
    });
  }

  function handleResetAll() {
    setState((prev) => ({
      ...prev,
      editedQueryConfig: prev.loadedQueryConfig ? deepClone(prev.loadedQueryConfig) : prev.editedQueryConfig,
      editedDataConfig: prev.loadedDataConfig ? deepClone(prev.loadedDataConfig) : prev.editedDataConfig
    }));
  }

  async function handleCopyQuery() {
    if (!state.editedQueryConfig) {
      return;
    }

    try {
      await navigator.clipboard.writeText(JSON.stringify(state.editedQueryConfig, null, 2));
      setState((prev) => ({ ...prev, copiedQuery: true }));
      window.setTimeout(() => {
        setState((prev) => ({ ...prev, copiedQuery: false }));
      }, 1500);
    } catch {
    }
  }

  async function handleCopyData() {
    if (!state.editedDataConfig) {
      return;
    }

    try {
      await navigator.clipboard.writeText(JSON.stringify(state.editedDataConfig, null, 2));
      setState((prev) => ({ ...prev, copiedData: true }));
      window.setTimeout(() => {
        setState((prev) => ({ ...prev, copiedData: false }));
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
          <div className="duality-fs-18px-weight-700-mb-0p35rem">Analysis Manager</div>
          <div className="duality-text-555-mb-0p35rem">
            Manager for project-level analysis configs. This page loads analysis query and analysis data definitions so users can adapt available computations, resources, extractors, and argument wiring to fit their own data shape.
          </div>
          <div className="duality-fs-13px-text-666">
            Project scope: {projectKey} | Query path: {queryPath} | Data path: {dataPath}
          </div>
        </div>

        {state.loading && (
          <div style={cardStyle}>
            Loading analysis configs...
          </div>
        )}

        {state.error && (
          <div style={{ ...cardStyle, color: "red", fontWeight: 600 }}>
            {state.error}
          </div>
        )}

        {!state.loading && !state.error && state.editedQueryConfig && state.editedDataConfig && (
          <>
            <div style={cardStyle}>
              <div className="duality-d-flex-justify-space-between-gap-1rem">
                <div>
                  <div className="analysis-manager-block-01">Config Headers</div>
                  <div className="duality-text-555">
                    Edit top-level versioning and copy either the query-side or data-side config.
                  </div>
                </div>

                <div className="duality-d-flex-gap-0p75rem-wrap-wrap">
                  <button className="secondary-button" onClick={handleResetAll}>
                    Reset Both to Loaded Configs
                  </button>
                  <button onClick={handleCopyQuery}>{state.copiedQuery ? "Query Copied" : "Copy Query JSON"}</button>
                  <button onClick={handleCopyData}>{state.copiedData ? "Data Copied" : "Copy Data JSON"}</button>
                </div>
              </div>

              <div className="duality-mt-1" style={{ ...gridStyle }}>
                <label style={labelStyle}>Analysis Query Version</label>
                <input
                  type="text"
                  value={state.editedQueryConfig.version || ""}
                  onChange={(e) => updateQueryRoot("version", e.target.value)}
                />

                <label style={labelStyle}>Analysis Data Version</label>
                <input
                  type="text"
                  value={state.editedDataConfig.version || ""}
                  onChange={(e) => updateDataRoot("version", e.target.value)}
                />
              </div>
            </div>

            {computationKeys.map((computationKey) => {
              const queryComputation = state.editedQueryConfig?.computations?.[computationKey] || {};
              const dataComputation = state.editedDataConfig?.computations?.[computationKey] || {};

              const propertyKeys = Array.from(
                new Set([
                  ...Object.keys(queryComputation.properties || {}),
                  ...Object.keys(dataComputation.properties || {})
                ])
              );

              return (
                <div key={computationKey} style={cardStyle}>
                  <div className="duality-fs-18px-weight-700-mb-0p35rem">{computationKey}</div>
                  <div className="analysis-manager-block-02">
                    Query resources on the left, extractor/data behavior on the right.
                  </div>

                  {propertyKeys.map((propertyKey) => {
                    const queryProperty = queryComputation.properties?.[propertyKey] || {};
                    const dataProperty = dataComputation.properties?.[propertyKey] || {};

                    const columnKeys = Array.from(
                      new Set([
                        ...Object.keys(queryProperty.columns || {}),
                        ...Object.keys(dataProperty.columns || {})
                      ])
                    );

                    return (
                      <div key={`${computationKey}-${propertyKey}`} style={{ ...cardStyle, marginBottom: "1rem" }}>
                        <div className="duality-fs-16px-weight-700-mb-1rem">{propertyKey}</div>

                        {columnKeys.map((columnKey) => {
                          const queryColumn = queryProperty.columns?.[columnKey] || {};
                          const dataColumn = dataProperty.columns?.[columnKey] || {};

                          const extraQueryJson = { ...queryColumn };
                          delete extraQueryJson.resources;

                          const extraDataJson = { ...dataColumn };
                          delete extraDataJson.resourceType;
                          delete extraDataJson.extractor;
                          delete extraDataJson.args;

                          return (
                            <div key={`${computationKey}-${propertyKey}-${columnKey}`} style={{ ...cardStyle, marginBottom: "1rem" }}>
                              <div className="analysis-manager-block-03">{columnKey}</div>

                              <div className="analysis-manager-shared-01">
                                <div>
                                  <div className="analysis-manager-shared-02">Query Side</div>
                                  <div style={gridStyle}>
                                    <label style={labelStyle}>Resources JSON</label>
                                    <textarea
                                      rows={12}
                                      value={prettyJson(queryColumn.resources || [])}
                                      onChange={(e) =>
                                        updateQueryComputationProperty(computationKey, propertyKey, (current) => ({
                                          ...current,
                                          columns: {
                                            ...(current.columns || {}),
                                            [columnKey]: {
                                              ...(current.columns?.[columnKey] || {}),
                                              resources: parseJsonOrFallback<QueryResourceConfig[]>(
                                                e.target.value,
                                                queryColumn.resources || []
                                              )
                                            }
                                          }
                                        }))
                                      }
                                    />

                                    <label style={labelStyle}>Additional Query JSON</label>
                                    <textarea
                                      rows={8}
                                      value={prettyJson(extraQueryJson)}
                                      onChange={(e) =>
                                        updateQueryComputationProperty(computationKey, propertyKey, (current) => {
                                          const parsed = parseJsonOrFallback<Record<string, any>>(e.target.value, extraQueryJson);
                                          return {
                                            ...current,
                                            columns: {
                                              ...(current.columns || {}),
                                              [columnKey]: {
                                                ...parsed,
                                                resources: queryColumn.resources
                                              }
                                            }
                                          };
                                        })
                                      }
                                    />
                                  </div>
                                </div>

                                <div>
                                  <div className="analysis-manager-shared-02">Data Side</div>
                                  <div style={gridStyle}>
                                    <label style={labelStyle}>Resource Type</label>
                                    <input
                                      type="text"
                                      value={dataColumn.resourceType || ""}
                                      onChange={(e) =>
                                        updateDataComputationProperty(computationKey, propertyKey, (current) => ({
                                          ...current,
                                          columns: {
                                            ...(current.columns || {}),
                                            [columnKey]: {
                                              ...(current.columns?.[columnKey] || {}),
                                              resourceType: e.target.value
                                            }
                                          }
                                        }))
                                      }
                                    />

                                    <label style={labelStyle}>Extractor</label>
                                    <input
                                      type="text"
                                      value={dataColumn.extractor || ""}
                                      onChange={(e) =>
                                        updateDataComputationProperty(computationKey, propertyKey, (current) => ({
                                          ...current,
                                          columns: {
                                            ...(current.columns || {}),
                                            [columnKey]: {
                                              ...(current.columns?.[columnKey] || {}),
                                              extractor: e.target.value
                                            }
                                          }
                                        }))
                                      }
                                    />

                                    <label style={labelStyle}>Args JSON</label>
                                    <textarea
                                      rows={8}
                                      value={prettyJson(dataColumn.args || {})}
                                      onChange={(e) =>
                                        updateDataComputationProperty(computationKey, propertyKey, (current) => ({
                                          ...current,
                                          columns: {
                                            ...(current.columns || {}),
                                            [columnKey]: {
                                              ...(current.columns?.[columnKey] || {}),
                                              args: parseJsonOrFallback<Record<string, any>>(e.target.value, dataColumn.args || {})
                                            }
                                          }
                                        }))
                                      }
                                    />

                                    <label style={labelStyle}>Additional Data JSON</label>
                                    <textarea
                                      rows={8}
                                      value={prettyJson(extraDataJson)}
                                      onChange={(e) =>
                                        updateDataComputationProperty(computationKey, propertyKey, (current) => {
                                          const parsed = parseJsonOrFallback<Record<string, any>>(e.target.value, extraDataJson);
                                          return {
                                            ...current,
                                            columns: {
                                              ...(current.columns || {}),
                                              [columnKey]: {
                                                ...parsed,
                                                resourceType: dataColumn.resourceType,
                                                extractor: dataColumn.extractor,
                                                args: dataColumn.args
                                              }
                                            }
                                          };
                                        })
                                      }
                                    />
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              );
            })}

            <div style={cardStyle}>
              <div className="duality-fs-16px-weight-700-mb-1rem">Whole Config JSON</div>

              <div className="analysis-manager-shared-01">
                <div>
                  <div className="duality-weight-700-mb-0p5rem">Analysis Query JSON</div>
                  <textarea
                    rows={20}
                    value={prettyJson(state.editedQueryConfig)}
                    onChange={(e) =>
                      setState((prev) => ({
                        ...prev,
                        editedQueryConfig: parseJsonOrFallback<AnalysisQueryConfigFile>(e.target.value, prev.editedQueryConfig || {})
                      }))
                    }
                  />
                </div>

                <div>
                  <div className="duality-weight-700-mb-0p5rem">Analysis Data JSON</div>
                  <textarea
                    rows={20}
                    value={prettyJson(state.editedDataConfig)}
                    onChange={(e) =>
                      setState((prev) => ({
                        ...prev,
                        editedDataConfig: parseJsonOrFallback<AnalysisDataConfigFile>(e.target.value, prev.editedDataConfig || {})
                      }))
                    }
                  />
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default AnalysisManagerPage;