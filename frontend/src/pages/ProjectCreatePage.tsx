import React, { useEffect, useMemo, useState } from "react";
import HeaderTitle from "../components/HeaderTitle";
import {
  FUNCTION_ENUM_TO_ID,
  FUNCTION_METADATA,
} from "../components/FunctionSelector";
import {
  API_BASE,
  API_PROJECTS_CREATE,
  API_PROJECTS_CREATION_OPTIONS,
} from "../constants/Constants";
import { Project } from "../types/Project";

interface CreationFunctionOption {
  id: number;
  name: string;
  description?: string | null;
  property_types?: Record<string, string>;
  default_properties?: Record<string, string>;
}

interface CreationFilterSystemOption {
  id: number;
  name: string;
  description?: string | null;
  allowed_filter_types?: string[];
}

interface CreationOptionsResponse {
  status?: string;
  functions?: CreationFunctionOption[];
  filter_systems?: CreationFilterSystemOption[];
  error?: string;
}

interface FunctionConfigurationDraft {
  configurable: boolean;
  fixed: string;
  variable: string;
  override: string;
}

interface DatasourceGroupDraft {
  key: string;
  group_name: string;
  is_default: boolean;
}

interface WorkflowOptionDraft {
  key: string;
  option_key: string;
  option_label: string;
  option_value: string;
  option_description: string;
  is_default: boolean;
}

interface WorkflowGroupDraft {
  key: string;
  group_key: string;
  group_label: string;
  group_description: string;
  min_selected: string;
  max_selected: string;
  is_required: boolean;
  validation_config: string;
  options: WorkflowOptionDraft[];
}

interface ProjectCreatePageProps {
  onCancel: () => void;
  onCreated: (project: Project) => void | Promise<void>;
}

const makeKey = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;

function getFunctionMetadata(functionName: string) {
  const normalized = String(functionName || "").trim();
  const metadataId = FUNCTION_ENUM_TO_ID[normalized.toUpperCase()] || normalized.toLowerCase();
  return FUNCTION_METADATA.find((entry) => entry.id === metadataId);
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value || {}, null, 2);
}

function parseOptionalJsonObject(raw: string, label: string): Record<string, unknown> | null {
  const normalized = raw.trim();
  if (!normalized || normalized === "{}") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(normalized);
  } catch {
    throw new Error(`${label} must contain valid JSON.`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

const ProjectCreatePage: React.FC<ProjectCreatePageProps> = ({ onCancel, onCreated }) => {
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [functions, setFunctions] = useState<CreationFunctionOption[]>([]);
  const [filterSystems, setFilterSystems] = useState<CreationFilterSystemOption[]>([]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const [filterSystem, setFilterSystem] = useState("");
  const [modelFileSettingsEnabled, setModelFileSettingsEnabled] = useState(false);
  const [selectedFunctions, setSelectedFunctions] = useState<string[]>([]);
  const [functionDrafts, setFunctionDrafts] = useState<Record<string, FunctionConfigurationDraft>>({});
  const [datasourceGroups, setDatasourceGroups] = useState<DatasourceGroupDraft[]>([]);
  const [workflowGroups, setWorkflowGroups] = useState<WorkflowGroupDraft[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoadingOptions(true);
      setError("");
      try {
        const response = await fetch(`${API_BASE}${API_PROJECTS_CREATION_OPTIONS}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        const data = (await response.json().catch(() => ({}))) as CreationOptionsResponse;
        if (!response.ok || data.status !== "SUCCESS") {
          throw new Error(data.error || "Unable to load project creation options.");
        }
        if (cancelled) return;
        const nextFunctions = Array.isArray(data.functions) ? data.functions : [];
        const nextFilterSystems = Array.isArray(data.filter_systems) ? data.filter_systems : [];
        setFunctions(nextFunctions);
        setFilterSystems(nextFilterSystems);
        setFilterSystem(nextFilterSystems[0]?.name || "");
      } catch (caughtError) {
        if (!cancelled) {
          setError(caughtError instanceof Error ? caughtError.message : "Unable to load project creation options.");
        }
      } finally {
        if (!cancelled) setLoadingOptions(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedFilterSystem = useMemo(
    () => filterSystems.find((item) => item.name === filterSystem) || null,
    [filterSystems, filterSystem]
  );

  const toggleFunction = (option: CreationFunctionOption) => {
    const selected = selectedFunctions.includes(option.name);
    if (selected) {
      setSelectedFunctions((current) => current.filter((nameValue) => nameValue !== option.name));
      return;
    }
    setSelectedFunctions((current) => [...current, option.name]);
    setFunctionDrafts((current) => ({
      ...current,
      [option.name]: current[option.name] || {
        configurable: true,
        fixed: "{}",
        variable: "{}",
        override: "{}",
      },
    }));
  };

  const updateFunctionDraft = (functionName: string, patch: Partial<FunctionConfigurationDraft>) => {
    setFunctionDrafts((current) => ({
      ...current,
      [functionName]: {
        configurable: true,
        fixed: "{}",
        variable: "{}",
        override: "{}",
        ...(current[functionName] || {}),
        ...patch,
      },
    }));
  };

  const addDatasourceGroup = () => {
    setDatasourceGroups((current) => [
      ...current,
      {
        key: makeKey(),
        group_name: "",
        is_default: current.length === 0,
      },
    ]);
  };

  const setDefaultDatasourceGroup = (key: string) => {
    setDatasourceGroups((current) => current.map((group) => ({
      ...group,
      is_default: group.key === key,
    })));
  };

  const removeDatasourceGroup = (key: string) => {
    setDatasourceGroups((current) => {
      const removed = current.find((group) => group.key === key);
      const next = current.filter((group) => group.key !== key);
      if (removed?.is_default && next.length > 0) {
        next[0] = { ...next[0], is_default: true };
      }
      return next;
    });
  };

  const addWorkflowGroup = () => {
    setWorkflowGroups((current) => [
      ...current,
      {
        key: makeKey(),
        group_key: "",
        group_label: "",
        group_description: "",
        min_selected: "0",
        max_selected: "",
        is_required: false,
        validation_config: "{}",
        options: [],
      },
    ]);
  };

  const updateWorkflowGroup = (key: string, patch: Partial<WorkflowGroupDraft>) => {
    setWorkflowGroups((current) => current.map((group) => group.key === key ? { ...group, ...patch } : group));
  };

  const addWorkflowOption = (groupKey: string) => {
    setWorkflowGroups((current) => current.map((group) => group.key === groupKey ? {
      ...group,
      options: [
        ...group.options,
        {
          key: makeKey(),
          option_key: "",
          option_label: "",
          option_value: "",
          option_description: "",
          is_default: false,
        },
      ],
    } : group));
  };

  const updateWorkflowOption = (groupKey: string, optionKey: string, patch: Partial<WorkflowOptionDraft>) => {
    setWorkflowGroups((current) => current.map((group) => group.key === groupKey ? {
      ...group,
      options: group.options.map((option) => option.key === optionKey ? { ...option, ...patch } : option),
    } : group));
  };

  const removeWorkflowOption = (groupKey: string, optionKey: string) => {
    setWorkflowGroups((current) => current.map((group) => group.key === groupKey ? {
      ...group,
      options: group.options.filter((option) => option.key !== optionKey),
    } : group));
  };

  const submit = async () => {
    setError("");
    if (!name.trim()) {
      setError("Project title is required.");
      return;
    }
    if (!selectedFunctions.length) {
      setError("Select at least one function for the project.");
      return;
    }

    let payload: Record<string, unknown>;
    try {
      payload = {
        name: name.trim(),
        description: description.trim() || null,
        status,
        filter_system: filterSystem || null,
        model_file_settings_enabled: modelFileSettingsEnabled,
        functions: selectedFunctions.map((functionName) => {
          const draft = functionDrafts[functionName] || {
            configurable: true,
            fixed: "{}",
            variable: "{}",
            override: "{}",
          };
          return {
            function: functionName,
            configurable: draft.configurable,
            custom_configuration_fixed: parseOptionalJsonObject(draft.fixed, `${functionName} fixed configuration`),
            custom_configuration_variable: parseOptionalJsonObject(draft.variable, `${functionName} selectable configuration`),
            override_configuration: parseOptionalJsonObject(draft.override, `${functionName} runtime overrides`),
          };
        }),
        datasource_groups: datasourceGroups.map((group) => ({
          group_name: group.group_name.trim(),
          is_default: group.is_default,
        })),
        workflow_groups: workflowGroups.map((group, groupIndex) => ({
          group_key: group.group_key.trim(),
          group_label: group.group_label.trim(),
          group_description: group.group_description.trim() || null,
          min_selected: Number(group.min_selected || 0),
          max_selected: group.max_selected.trim() ? Number(group.max_selected) : null,
          is_required: group.is_required,
          page_order: groupIndex,
          status: "ACTIVE",
          validation_config: parseOptionalJsonObject(group.validation_config, `${group.group_label || group.group_key || "Workflow group"} validation configuration`),
          options: group.options.map((option, optionIndex) => ({
            option_key: option.option_key.trim(),
            option_label: option.option_label.trim(),
            option_value: option.option_value.trim(),
            option_description: option.option_description.trim() || null,
            option_order: optionIndex,
            is_default: option.is_default,
            status: "ACTIVE",
          })),
        })),
      };
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Project configuration is invalid.");
      return;
    }

    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}${API_PROJECTS_CREATE}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status !== "SUCCESS" || !data.project) {
        throw new Error(data.error || "Unable to create project.");
      }
      await onCreated({ ...data.project, filter_schemas: {} } as Project);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unable to create project.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="function-container animate-in">
      <HeaderTitle
        contained
        title="Create Project"
        description="Define a new analysis project, select its functions, and configure project-specific behavior. User-created projects remain removable from the project list."
      />

      <div className="page-container">
        <div className="child-container project-create-content">
          {error ? <div className="project-create-error">{error}</div> : null}

          <section className="project-create-section project-create-section-first">
            <div className="project-settings-section-heading">
              <div>
                <h3>Project Definition</h3>
                <p>Basic identity and top-level project behavior.</p>
              </div>
            </div>

            <div className="project-create-form-grid">
              <label className="project-create-field project-create-field-wide">
                <span>Project Title</span>
                <input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} placeholder="New Analysis Project" />
              </label>

              <label className="project-create-field project-create-field-wide">
                <span>Description</span>
                <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={4} placeholder="Describe the purpose of this analysis pipeline." />
              </label>

              <label className="project-create-field">
                <span>Status</span>
                <select value={status} onChange={(event) => setStatus(event.target.value)}>
                  <option value="ACTIVE">ACTIVE</option>
                  <option value="ARCHIVED">ARCHIVED</option>
                </select>
              </label>

              <label className="project-create-field">
                <span>Filter System</span>
                <select value={filterSystem} onChange={(event) => setFilterSystem(event.target.value)} disabled={loadingOptions}>
                  {filterSystems.map((filter) => <option key={filter.id} value={filter.name}>{filter.name}</option>)}
                </select>
              </label>
            </div>

            {selectedFilterSystem ? (
              <div className="project-create-filter-summary">
                <strong>{selectedFilterSystem.name}</strong>
                {selectedFilterSystem.description ? <span>{selectedFilterSystem.description}</span> : null}
                {(selectedFilterSystem.allowed_filter_types || []).length ? (
                  <span>Allowed filter types: {(selectedFilterSystem.allowed_filter_types || []).join(", ")}</span>
                ) : null}
              </div>
            ) : null}

            <label className="project-create-check-row">
              <input type="checkbox" checked={modelFileSettingsEnabled} onChange={(event) => setModelFileSettingsEnabled(event.target.checked)} />
              <span>
                <strong>Enable model-file settings</strong>
                <small>Allows project workflows to use datasource-aware model file mappings and availability validation.</small>
              </span>
            </label>
          </section>

          <section className="project-create-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Functions & Configuration</h3>
                <p>Select the functions exposed by this project, then optionally define fixed, selectable, or runtime override configuration.</p>
              </div>
              <span className="project-settings-section-count">{selectedFunctions.length}</span>
            </div>

            {loadingOptions ? <div className="project-settings-empty">Loading supported functions…</div> : (
              <div className="project-create-function-list">
                {functions.map((option) => {
                  const selected = selectedFunctions.includes(option.name);
                  const metadata = getFunctionMetadata(option.name);
                  const draft = functionDrafts[option.name] || {
                    configurable: true,
                    fixed: "{}",
                    variable: "{}",
                    override: "{}",
                  };
                  return (
                    <article className={`project-create-function-card ${selected ? "selected" : ""}`} key={option.id}>
                      <label className="project-create-function-selector">
                        <input type="checkbox" checked={selected} onChange={() => toggleFunction(option)} />
                        {metadata?.icon ? <img src={`/icons${metadata.icon}`} alt="" aria-hidden="true" /> : null}
                        <span>
                          <strong>{metadata?.title || option.name}</strong>
                          <small>{metadata?.description || option.description || "Supported analysis function"}</small>
                        </span>
                      </label>

                      {selected ? (
                        <div className="project-create-function-config">
                          <label className="project-create-check-row project-create-function-configurable">
                            <input
                              type="checkbox"
                              checked={draft.configurable}
                              onChange={(event) => updateFunctionDraft(option.name, { configurable: event.target.checked })}
                            />
                            <span><strong>Allow runtime configuration</strong></span>
                          </label>

                          <div className="project-create-json-grid">
                            <label className="project-create-field">
                              <span>Fixed Configuration (JSON)</span>
                              <textarea value={draft.fixed} onChange={(event) => updateFunctionDraft(option.name, { fixed: event.target.value })} rows={7} spellCheck={false} />
                              {Object.keys(option.default_properties || {}).length ? (
                                <button type="button" className="project-create-inline-action" onClick={() => updateFunctionDraft(option.name, { fixed: prettyJson(option.default_properties) })}>
                                  Use standard defaults
                                </button>
                              ) : null}
                            </label>
                            <label className="project-create-field">
                              <span>Selectable Configuration (JSON)</span>
                              <textarea value={draft.variable} onChange={(event) => updateFunctionDraft(option.name, { variable: event.target.value })} rows={7} spellCheck={false} />
                            </label>
                            <label className="project-create-field">
                              <span>Runtime Overrides (JSON)</span>
                              <textarea value={draft.override} onChange={(event) => updateFunctionDraft(option.name, { override: event.target.value })} rows={7} spellCheck={false} />
                            </label>
                          </div>
                          {Object.keys(option.property_types || {}).length ? (
                            <div className="project-create-property-reference">
                              <strong>Known properties:</strong> {Object.entries(option.property_types || {}).map(([property, type]) => `${property} (${type})`).join(", ")}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="project-create-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Datasource Groups</h3>
                <p>Optional project-level datasource choices. User-specific FHIR locations remain configured separately.</p>
              </div>
              <button type="button" className="project-create-section-action" onClick={addDatasourceGroup}>+ Add Datasource Group</button>
            </div>

            {datasourceGroups.length ? (
              <div className="project-create-datasource-list">
                {datasourceGroups.map((group) => (
                  <div className="project-create-datasource-row" key={group.key}>
                    <label className="project-create-field">
                      <span>Group Name</span>
                      <input value={group.group_name} onChange={(event) => setDatasourceGroups((current) => current.map((item) => item.key === group.key ? { ...item, group_name: event.target.value } : item))} placeholder="Datasource Group" />
                    </label>
                    <label className="project-create-radio-row">
                      <input type="radio" name="default-datasource-group" checked={group.is_default} onChange={() => setDefaultDatasourceGroup(group.key)} />
                      <span>Default</span>
                    </label>
                    <button type="button" className="project-create-remove-row" onClick={() => removeDatasourceGroup(group.key)} aria-label={`Remove ${group.group_name || "datasource group"}`}>−</button>
                  </div>
                ))}
              </div>
            ) : <div className="project-settings-empty">No datasource groups defined.</div>}
          </section>

          <section className="project-create-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Workflow Configuration</h3>
                <p>Optional grouped choices, constraints, and validation rules shown during job setup.</p>
              </div>
              <button type="button" className="project-create-section-action" onClick={addWorkflowGroup}>+ Add Workflow Group</button>
            </div>

            {workflowGroups.length ? (
              <div className="project-create-workflow-list">
                {workflowGroups.map((group) => (
                  <article className="project-create-workflow-card" key={group.key}>
                    <div className="project-create-workflow-heading">
                      <strong>{group.group_label || "New Workflow Group"}</strong>
                      <button type="button" className="project-create-remove-row" onClick={() => setWorkflowGroups((current) => current.filter((item) => item.key !== group.key))} aria-label="Remove workflow group">−</button>
                    </div>
                    <div className="project-create-form-grid">
                      <label className="project-create-field"><span>Group Key</span><input value={group.group_key} onChange={(event) => updateWorkflowGroup(group.key, { group_key: event.target.value })} placeholder="predictive_modeling_method_ids" /></label>
                      <label className="project-create-field"><span>Group Label</span><input value={group.group_label} onChange={(event) => updateWorkflowGroup(group.key, { group_label: event.target.value })} placeholder="Predictive Model Configuration" /></label>
                      <label className="project-create-field project-create-field-wide"><span>Description</span><textarea rows={3} value={group.group_description} onChange={(event) => updateWorkflowGroup(group.key, { group_description: event.target.value })} /></label>
                      <label className="project-create-field"><span>Minimum Selections</span><input type="number" min="0" value={group.min_selected} onChange={(event) => updateWorkflowGroup(group.key, { min_selected: event.target.value })} /></label>
                      <label className="project-create-field"><span>Maximum Selections</span><input type="number" min="0" value={group.max_selected} onChange={(event) => updateWorkflowGroup(group.key, { max_selected: event.target.value })} placeholder="No limit" /></label>
                    </div>
                    <label className="project-create-check-row">
                      <input type="checkbox" checked={group.is_required} onChange={(event) => updateWorkflowGroup(group.key, { is_required: event.target.checked })} />
                      <span><strong>Require a selection from this group</strong></span>
                    </label>
                    <label className="project-create-field project-create-validation-field">
                      <span>Validation Configuration (JSON)</span>
                      <textarea rows={6} spellCheck={false} value={group.validation_config} onChange={(event) => updateWorkflowGroup(group.key, { validation_config: event.target.value })} />
                    </label>

                    <div className="project-create-options-heading">
                      <strong>Options</strong>
                      <button type="button" className="project-create-inline-action" onClick={() => addWorkflowOption(group.key)}>+ Add Option</button>
                    </div>
                    {group.options.length ? (
                      <div className="project-create-options-list">
                        {group.options.map((option) => (
                          <div className="project-create-option-row" key={option.key}>
                            <label className="project-create-field"><span>Key</span><input value={option.option_key} onChange={(event) => updateWorkflowOption(group.key, option.key, { option_key: event.target.value })} /></label>
                            <label className="project-create-field"><span>Label</span><input value={option.option_label} onChange={(event) => updateWorkflowOption(group.key, option.key, { option_label: event.target.value })} /></label>
                            <label className="project-create-field"><span>Value</span><input value={option.option_value} onChange={(event) => updateWorkflowOption(group.key, option.key, { option_value: event.target.value })} /></label>
                            <label className="project-create-field project-create-option-description"><span>Description</span><input value={option.option_description} onChange={(event) => updateWorkflowOption(group.key, option.key, { option_description: event.target.value })} /></label>
                            <label className="project-create-radio-row"><input type="checkbox" checked={option.is_default} onChange={(event) => updateWorkflowOption(group.key, option.key, { is_default: event.target.checked })} /><span>Default</span></label>
                            <button type="button" className="project-create-remove-row" onClick={() => removeWorkflowOption(group.key, option.key)} aria-label="Remove workflow option">−</button>
                          </div>
                        ))}
                      </div>
                    ) : <div className="project-settings-empty">No workflow options defined.</div>}
                  </article>
                ))}
              </div>
            ) : <div className="project-settings-empty">No workflow groups defined.</div>}
          </section>

          <div className="project-create-actions">
            <button type="button" className="secondary-button" onClick={onCancel} disabled={saving}>Cancel</button>
            <button type="button" className="project-action-button project-action-primary" onClick={() => void submit()} disabled={saving || loadingOptions}>
              {saving ? "Creating Project…" : "Create Project"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProjectCreatePage;
