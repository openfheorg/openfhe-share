import React, { useEffect, useMemo, useState } from "react";
import HeaderTitle from "../components/HeaderTitle";
import {
  FUNCTION_ENUM_TO_ID,
  FUNCTION_METADATA,
} from "../components/FunctionSelector";
import {
  JsonObject,
  Project,
  ProjectFunctionCapability,
  ProjectWorkflowGroup,
  WorkflowGroupValidationConfig,
} from "../types/Project";

interface ProjectSettingsPageProps {
  project: Project;
}

function humanizeKey(value: string): string {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatScalar(value: unknown): React.ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function functionMetadata(functionName: string) {
  const normalized = String(functionName || "").trim();
  const metadataId = FUNCTION_ENUM_TO_ID[normalized.toUpperCase()] || normalized.toLowerCase();
  return FUNCTION_METADATA.find((entry) => entry.id === metadataId);
}

const ReadOnlyBadge: React.FC<{ children: React.ReactNode; tone?: "default" | "success" | "muted" }> = ({
  children,
  tone = "default",
}) => <span className={`project-settings-badge ${tone}`}>{children}</span>;

const SettingRows: React.FC<{ data?: JsonObject | null }> = ({ data }) => {
  const entries = Object.entries(data || {});
  if (!entries.length) return <div className="project-settings-empty">No project-level values configured.</div>;

  return (
    <div className="project-settings-kv-list">
      {entries.map(([key, value]) => (
        <div className="project-settings-kv-row" key={key}>
          <span className="project-settings-kv-key">{humanizeKey(key)}</span>
          <span className="project-settings-kv-value">{formatScalar(value)}</span>
        </div>
      ))}
    </div>
  );
};

const VariableConfiguration: React.FC<{ data?: JsonObject | null }> = ({ data }) => {
  const entries = Object.entries(data || {});
  if (!entries.length) return <div className="project-settings-empty">No user-selectable project configuration.</div>;

  return (
    <div className="project-settings-variable-list">
      {entries.map(([property, rawDefinition]) => {
        const definition = rawDefinition && typeof rawDefinition === "object"
          ? (rawDefinition as JsonObject)
          : { default: rawDefinition };
        const options = Array.isArray(definition.options) ? definition.options : [];

        return (
          <div className="project-settings-variable-row" key={property}>
            <div className="project-settings-variable-heading">
              <strong>{humanizeKey(property)}</strong>
              {definition.type ? <ReadOnlyBadge>{String(definition.type)}</ReadOnlyBadge> : null}
            </div>
            <div className="project-settings-variable-meta">
              <span><b>Default:</b> {formatScalar(definition.default)}</span>
              {options.length ? <span><b>Options:</b> {options.join(", ")}</span> : null}
            </div>
            {definition.description ? (
              <div className="project-settings-variable-description">{String(definition.description)}</div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
};

const FunctionConfigurationCard: React.FC<{ capability: ProjectFunctionCapability }> = ({ capability }) => {
  const metadata = functionMetadata(capability.function);
  const hasFixed = Boolean(Object.keys(capability.custom_configuration_fixed || {}).length);
  const hasVariable = Boolean(Object.keys(capability.custom_configuration_variable || {}).length);
  const hasOverride = Boolean(Object.keys(capability.override_configuration || {}).length);

  return (
    <article className="project-settings-function-card">
      <div className="project-settings-function-header">
        {metadata?.icon ? <img src={`/icons${metadata.icon}`} alt="" aria-hidden="true" /> : null}
        <div className="project-settings-function-title-wrap">
          <div className="project-settings-function-title">{metadata?.title || humanizeKey(capability.function)}</div>
          <div className="project-settings-function-badges">
            <ReadOnlyBadge tone="success">Enabled</ReadOnlyBadge>
            <ReadOnlyBadge tone={capability.configurable ? "default" : "muted"}>
              {capability.configurable ? "Configurable" : "Fixed by project"}
            </ReadOnlyBadge>
          </div>
        </div>
      </div>

      {metadata?.description ? (
        <p className="project-settings-function-description">{metadata.description}</p>
      ) : null}

      {!hasFixed && !hasVariable && !hasOverride ? (
        <div className="project-settings-empty project-settings-function-empty">
          Uses the standard function configuration; no project-specific overrides are defined.
        </div>
      ) : (
        <div className="project-settings-function-config-grid">
          {hasFixed ? (
            <div className="project-settings-subpanel">
              <h4>Fixed Configuration</h4>
              <SettingRows data={capability.custom_configuration_fixed} />
            </div>
          ) : null}

          {hasVariable ? (
            <div className="project-settings-subpanel project-settings-subpanel-wide">
              <h4>Selectable Configuration</h4>
              <VariableConfiguration data={capability.custom_configuration_variable} />
            </div>
          ) : null}

          {hasOverride ? (
            <div className="project-settings-subpanel">
              <h4>Runtime Overrides</h4>
              <SettingRows data={capability.override_configuration} />
            </div>
          ) : null}
        </div>
      )}
    </article>
  );
};

function collectValidationConfigs(workflowGroups: ProjectWorkflowGroup[]): WorkflowGroupValidationConfig[] {
  return workflowGroups
    .map((group) => group.validation_config)
    .filter((config): config is WorkflowGroupValidationConfig => Boolean(config && config.enabled !== false));
}

const ProjectSettingsPage: React.FC<ProjectSettingsPageProps> = ({ project }) => {
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [project.id]);

  const workflowGroups = Array.isArray(project.workflow_groups) ? [...project.workflow_groups] : [];
  workflowGroups.sort((a, b) => (a.page_order ?? 0) - (b.page_order ?? 0));

  const datasourceGroups = Array.isArray(project.datasource_groups) ? project.datasource_groups : [];
  const functions = Array.isArray(project.functions) ? project.functions : [];
  const allowedFilterTypes = useMemo(() => {
    const explicit = Array.isArray(project.filter_system_allowed_filter_types)
      ? project.filter_system_allowed_filter_types
      : [];
    return explicit.length ? explicit : Object.keys(project.filter_schemas || {});
  }, [project.filter_system_allowed_filter_types, project.filter_schemas]);
  const validationConfigs = collectValidationConfigs(workflowGroups);

  return (
    <div className={`function-container ${animate ? "animate-in" : ""}`}>
      <HeaderTitle
        contained
        iconPath="/icons/nav_icon_project_configuration.png"
        title={<>Project Configuration: <span className="project-settings-title-project">{project.name}</span></>}
        description={`Configuration details that define this project, including its functions, filters, datasource groups, workflows, and other project-level customizations.${project.fixed ? " This is a fixed project configuration and is read only." : ""}`}
      />

      <div className="page-container">
        <div className="child-container project-settings-content">
          <section className="project-settings-section project-settings-section-first">
            <div className="project-settings-section-heading">
              <div>
                <h3>Project Definition</h3>
                <p>Core project behavior and feature flags.</p>
              </div>
              <ReadOnlyBadge tone="muted">Read only</ReadOnlyBadge>
            </div>

            <div className="project-settings-summary-grid">
              <div className="project-settings-summary-item">
                <span>Status</span>
                <strong>{project.status || "—"}</strong>
              </div>
              <div className="project-settings-summary-item">
                <span>Fixed Definition</span>
                <strong>{project.fixed ? "Yes" : "No"}</strong>
              </div>
              <div className="project-settings-summary-item">
                <span>Function Restrictions</span>
                <strong>{project.function_restrictions_enabled ? "Enabled" : "Disabled"}</strong>
              </div>
              <div className="project-settings-summary-item">
                <span>Model File Settings</span>
                <strong>{project.model_file_settings_enabled ? "Enabled" : "Disabled"}</strong>
              </div>
              <div className="project-settings-summary-item">
                <span>Filter System</span>
                <strong>{project.filter_system || "—"}</strong>
              </div>
              <div className="project-settings-summary-item">
                <span>Supported Functions</span>
                <strong>{functions.length}</strong>
              </div>
            </div>

            {project.description ? <p className="project-settings-project-description">{project.description}</p> : null}
          </section>

          <section className="project-settings-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Filter System</h3>
                <p>Filter contract exposed to this project by its configured filter system.</p>
              </div>
            </div>

            <div className="project-settings-inline-definition">
              <span className="project-settings-inline-label">System</span>
              <strong>{project.filter_system || "Not configured"}</strong>
            </div>
            <div className="project-settings-chip-row">
              {allowedFilterTypes.length ? allowedFilterTypes.map((filterType) => (
                <ReadOnlyBadge key={String(filterType)}>{String(filterType)}</ReadOnlyBadge>
              )) : <span className="project-settings-empty">No allowed filter types reported.</span>}
            </div>
          </section>

          <section className="project-settings-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Datasource Groups</h3>
                <p>Project-level datasource choices. User-specific FHIR source locations are managed separately in User Settings.</p>
              </div>
              <span className="project-settings-section-count">{datasourceGroups.length}</span>
            </div>

            {datasourceGroups.length ? (
              <div className="project-settings-datasource-grid">
                {datasourceGroups.map((group) => (
                  <div className={`project-settings-datasource-card ${group.is_default ? "default" : ""}`} key={group.id}>
                    <strong>{group.group_name}</strong>
                    <span>Datasource Group {group.id}</span>
                    {group.is_default ? <ReadOnlyBadge tone="success">Default</ReadOnlyBadge> : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="project-settings-empty">This project does not define datasource groups.</div>
            )}
          </section>

          <section className="project-settings-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Functions & Project Configuration</h3>
                <p>Allowed functions plus fixed, selectable, and runtime override values supplied by the project definition.</p>
              </div>
              <span className="project-settings-section-count">{functions.length}</span>
            </div>

            <div className="project-settings-function-list">
              {functions.length ? functions.map((capability) => (
                <FunctionConfigurationCard capability={capability} key={capability.function} />
              )) : <div className="project-settings-empty">No project functions are configured.</div>}
            </div>
          </section>

          <section className="project-settings-section">
            <div className="project-settings-section-heading">
              <div>
                <h3>Workflow Configuration</h3>
                <p>Project-defined workflow choices, selection constraints, and validation behavior.</p>
              </div>
              <span className="project-settings-section-count">{workflowGroups.length}</span>
            </div>

            {workflowGroups.length ? (
              <div className="project-settings-workflow-list">
                {workflowGroups.map((group) => (
                  <article className="project-settings-workflow-card" key={group.group_key}>
                    <div className="project-settings-workflow-heading">
                      <div>
                        <h4>{group.group_label}</h4>
                        <div className="project-settings-code-label">{group.group_key}</div>
                      </div>
                      <div className="project-settings-function-badges">
                        {group.is_required ? <ReadOnlyBadge tone="success">Required</ReadOnlyBadge> : <ReadOnlyBadge tone="muted">Optional</ReadOnlyBadge>}
                        {group.status ? <ReadOnlyBadge>{group.status}</ReadOnlyBadge> : null}
                      </div>
                    </div>
                    {group.group_description ? <p>{group.group_description}</p> : null}

                    <div className="project-settings-workflow-rules">
                      <span><b>Minimum selections:</b> {group.min_selected ?? 0}</span>
                      <span><b>Maximum selections:</b> {group.max_selected ?? "No limit"}</span>
                      <span><b>Page order:</b> {group.page_order ?? 0}</span>
                    </div>

                    <div className="project-settings-options-list">
                      {(group.options || []).map((option) => (
                        <div className="project-settings-option-row" key={option.option_key || option.option_value}>
                          <div>
                            <strong>{option.option_label || humanizeKey(option.option_value)}</strong>
                            <span className="project-settings-code-label">{option.option_value}</span>
                          </div>
                          <div className="project-settings-option-copy">
                            {option.option_description || "No additional option description."}
                          </div>
                          {option.is_default ? <ReadOnlyBadge tone="success">Default</ReadOnlyBadge> : null}
                        </div>
                      ))}
                    </div>

                    {group.validation_config ? (
                      <div className="project-settings-validation-panel">
                        <h5>Validation</h5>
                        <SettingRows data={group.validation_config} />
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <div className="project-settings-empty">This project does not define workflow groups.</div>
            )}
          </section>

          <section className="project-settings-section project-settings-section-last">
            <div className="project-settings-section-heading">
              <div>
                <h3>Model File Behavior</h3>
                <p>Whether the project participates in model-file lookup and availability validation.</p>
              </div>
              <ReadOnlyBadge tone={project.model_file_settings_enabled ? "success" : "muted"}>
                {project.model_file_settings_enabled ? "Enabled" : "Disabled"}
              </ReadOnlyBadge>
            </div>

            {project.model_file_settings_enabled ? (
              <div className="project-settings-model-grid">
                <div className="project-settings-subpanel">
                  <h4>Project Behavior</h4>
                  <div className="project-settings-kv-list">
                    <div className="project-settings-kv-row">
                      <span className="project-settings-kv-key">Per-user model mappings</span>
                      <span className="project-settings-kv-value">Enabled</span>
                    </div>
                    <div className="project-settings-kv-row">
                      <span className="project-settings-kv-key">Datasource-aware lookup</span>
                      <span className="project-settings-kv-value">Enabled</span>
                    </div>
                  </div>
                </div>

                {validationConfigs.length ? (
                  <div className="project-settings-subpanel">
                    <h4>Availability Validation</h4>
                    <div className="project-settings-kv-list">
                      <div className="project-settings-kv-row">
                        <span className="project-settings-kv-key">Validation type</span>
                        <span className="project-settings-kv-value">{formatScalar(validationConfigs[0].validation_type)}</span>
                      </div>
                      <div className="project-settings-kv-row">
                        <span className="project-settings-kv-key">Lookup key</span>
                        <span className="project-settings-kv-value">{formatScalar(validationConfigs[0].model_file_lookup_key)}</span>
                      </div>
                      <div className="project-settings-kv-row">
                        <span className="project-settings-kv-key">Required artifacts</span>
                        <span className="project-settings-kv-value">{formatScalar(validationConfigs[0].required_artifact_types)}</span>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="project-settings-empty">
                Model-file source mappings are not part of this project's configuration.
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
};

export default ProjectSettingsPage;
