import React, { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../../constants/Constants";
import { Project, ProjectWorkflowGroup, WorkflowGroupData } from "../../../types/Project";
import { HelpPanel, HelpToggle } from "../../../components/HelpToggle";

interface WorkflowGroupSelectionPageProps {
  project: Project;
  workflowGroupData: WorkflowGroupData;
  setWorkflowGroupData: React.Dispatch<React.SetStateAction<WorkflowGroupData>>;
  onBack: () => void;
  backToButtonText?: string;
  onNext: () => void;
  username?: string | null;
  userId?: number | null;
  datasourceGroupId?: number | null;
  validationLookupValues?: Record<string, unknown> | null;
}

interface WorkflowGroupValidationState {
  loading: boolean;
  disabledValues: Record<string, string>;
  availableValues: string[];
  error?: string | null;
  waitingForContext?: boolean;
}

function getOrderedWorkflowGroups(project: Project): ProjectWorkflowGroup[] {
  const groups = Array.isArray(project.workflow_groups) ? [...project.workflow_groups] : [];
  return groups.sort((a, b) => {
    const aOrder = typeof a?.page_order === "number" ? a.page_order : Number.MAX_SAFE_INTEGER;
    const bOrder = typeof b?.page_order === "number" ? b.page_order : Number.MAX_SAFE_INTEGER;
    if (aOrder !== bOrder) return aOrder - bOrder;
    return String(a?.group_label || a?.group_key || "").localeCompare(
      String(b?.group_label || b?.group_key || "")
    );
  });
}

function getWorkflowGroupValidationError(
  group: ProjectWorkflowGroup,
  workflowGroupData: WorkflowGroupData
): string | null {
  const selectedValues = workflowGroupData[group.group_key]?.selected_values || [];
  const minSelected = typeof group?.min_selected === "number" ? group.min_selected : 0;
  const maxSelected = typeof group?.max_selected === "number" ? group.max_selected : null;

  if (minSelected > 0 && selectedValues.length < minSelected) {
    if (minSelected === 1) {
      return `Select at least one ${group.group_label}.`;
    }
    return `Select at least ${minSelected} options for ${group.group_label}.`;
  }

  if (maxSelected !== null && selectedValues.length > maxSelected) {
    if (maxSelected === 1) {
      return `Select no more than one ${group.group_label}.`;
    }
    return `Select no more than ${maxSelected} options for ${group.group_label}.`;
  }

  return null;
}

function normalizeEndpoint(endpoint: string): string {
  const value = String(endpoint || "").trim();
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `${API_BASE}${value.startsWith("/") ? value : `/${value}`}`;
}

function getContextValue(
  validationLookupValues: Record<string, unknown> | null | undefined,
  key: string
): string | null {
  if (!validationLookupValues || !key) return null;
  const value = validationLookupValues[key];
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text || null;
}

function getEffectiveDatasourceGroupId(
  project: Project,
  datasourceGroupId?: number | null
): number | null {
  if (typeof datasourceGroupId === "number") return datasourceGroupId;

  const selectedDatasourceGroup = (project as any)?.selected_datasource_group;
  if (selectedDatasourceGroup && typeof selectedDatasourceGroup.id === "number") {
    return selectedDatasourceGroup.id;
  }

  const defaultDatasourceGroup = project.default_datasource_group;
  if (defaultDatasourceGroup && typeof defaultDatasourceGroup.id === "number") {
    return defaultDatasourceGroup.id;
  }

  return null;
}

function getOptionDisabledReason(
  group: ProjectWorkflowGroup,
  optionValue: string,
  dynamicValidationByGroup: Record<string, WorkflowGroupValidationState>
): string | null {
  const validationConfig = group.validation_config;
  if (!validationConfig?.enabled) return null;

  const state = dynamicValidationByGroup[group.group_key];
  if (!state) return "Validating available options...";
  if (state.loading) return "Validating available options...";
  if (state.error) return state.error;
  if (state.waitingForContext) return state.error || "Required validation context is not available yet.";

  return state.disabledValues[optionValue] || null;
}

const WorkflowGroupSelectionPage: React.FC<WorkflowGroupSelectionPageProps> = ({
  project,
  workflowGroupData,
  setWorkflowGroupData,
  onBack,
  backToButtonText = "Back",
  onNext,
  username,
  userId,
  datasourceGroupId,
  validationLookupValues
}) => {
  const [openHelpByOption, setOpenHelpByOption] = useState<Record<string, boolean>>({});
  const [dynamicValidationByGroup, setDynamicValidationByGroup] = useState<Record<string, WorkflowGroupValidationState>>({});

  const workflowGroups = useMemo(() => getOrderedWorkflowGroups(project), [project]);

  const effectiveDatasourceGroupId = useMemo(
    () => getEffectiveDatasourceGroupId(project, datasourceGroupId),
    [project, datasourceGroupId]
  );

  const validationLookupValuesKey = useMemo(
    () => JSON.stringify(validationLookupValues || {}),
    [validationLookupValues]
  );

  useEffect(() => {
    const groupsRequiringValidation = workflowGroups.filter((group) => group.validation_config?.enabled);

    if (!groupsRequiringValidation.length) {
      setDynamicValidationByGroup({});
      return;
    }

    const controller = new AbortController();

    groupsRequiringValidation.forEach((group) => {
      const validationConfig = group.validation_config || {};
      const endpoint = normalizeEndpoint(String(validationConfig.endpoint || ""));
      const lookupKey = String(validationConfig.model_file_lookup_key || "").trim();
      const contextKey = String(validationConfig.lookup_value_context_key || lookupKey).trim();
      const lookupValue = getContextValue(validationLookupValues, contextKey) || getContextValue(validationLookupValues, lookupKey);
      const configuredUsername = validationConfig.username ? String(validationConfig.username).trim() : "";
      const requestUsername = username || configuredUsername || null;
      const requestUserId = typeof userId === "number" ? userId : typeof validationConfig.user_id === "number" ? validationConfig.user_id : null;
      const optionValues = (Array.isArray(group.options) ? group.options : [])
        .map((option) => String(option.option_value || "").trim())
        .filter(Boolean);

      if (!endpoint || !lookupKey || !lookupValue || (!requestUsername && requestUserId === null)) {
        const reason = !lookupValue
          ? `Cannot validate ${group.group_label} until ${contextKey || lookupKey || "the lookup value"} is selected.`
          : `Cannot validate ${group.group_label}; validation endpoint or user context is missing.`;

        const disabledValues = optionValues.reduce((acc, optionValue) => {
          acc[optionValue] = reason;
          return acc;
        }, {} as Record<string, string>);

        setDynamicValidationByGroup((prev) => ({
          ...prev,
          [group.group_key]: {
            loading: false,
            disabledValues,
            availableValues: [],
            error: reason,
            waitingForContext: true
          }
        }));
        return;
      }

      setDynamicValidationByGroup((prev) => ({
        ...prev,
        [group.group_key]: {
          loading: true,
          disabledValues: {},
          availableValues: []
        }
      }));

      const body: Record<string, unknown> = {
        project_id: project.id,
        datasource_group_id: effectiveDatasourceGroupId,
        model_file_lookup_key: lookupKey,
        model_file_lookup_value: lookupValue,
        required_artifact_types: Array.isArray(validationConfig.required_artifact_types)
          ? validationConfig.required_artifact_types
          : ["weights", "cutoff"]
      };

      if (requestUserId !== null) {
        body.user_id = requestUserId;
      } else if (requestUsername) {
        body.username = requestUsername;
      }

      const optionValuesRequestField = String(validationConfig.option_values_request_field || "model_keys");
      body[optionValuesRequestField] = optionValues;

      fetch(endpoint, {
        method: String(validationConfig.method || "POST").toUpperCase(),
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal
      })
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(data?.error || data?.message || `Validation request failed (${response.status})`);
          }
          return data;
        })
        .then((data) => {
          const availableValuesField = String(validationConfig.available_values_response_field || "available_model_keys");
          const availabilityField = String(validationConfig.availability_response_field || "availability_by_model_key");
          const availableValues = Array.isArray(data?.[availableValuesField])
            ? data[availableValuesField].map((value: unknown) => String(value))
            : [];
          const availabilityByValue = data?.[availabilityField] && typeof data[availabilityField] === "object"
            ? data[availabilityField]
            : {};

          const disabledValues: Record<string, string> = {};
          const defaultReason = String(
            validationConfig.disabled_reason || "No corresponding setting exists for this option."
          );

          optionValues.forEach((optionValue) => {
            const availability = availabilityByValue?.[optionValue];
            const explicitlyAvailable = availability?.available === true;
            const includedAsAvailable = availableValues.includes(optionValue);

            if (explicitlyAvailable || includedAsAvailable) {
              return;
            }

            const missing = Array.isArray(availability?.missing_artifact_types)
              ? availability.missing_artifact_types.join(", ")
              : "";
            disabledValues[optionValue] = missing ? `${defaultReason} Missing: ${missing}.` : defaultReason;
          });

          setDynamicValidationByGroup((prev) => ({
            ...prev,
            [group.group_key]: {
              loading: false,
              disabledValues,
              availableValues
            }
          }));
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          const reason = error instanceof Error ? error.message : "Validation request failed.";
          const disabledValues = optionValues.reduce((acc, optionValue) => {
            acc[optionValue] = reason;
            return acc;
          }, {} as Record<string, string>);

          setDynamicValidationByGroup((prev) => ({
            ...prev,
            [group.group_key]: {
              loading: false,
              disabledValues,
              availableValues: [],
              error: reason
            }
          }));
        });
    });

    return () => controller.abort();
  }, [workflowGroups, project.id, effectiveDatasourceGroupId, username, userId, validationLookupValuesKey, validationLookupValues]);

  useEffect(() => {
    setWorkflowGroupData((prev) => {
      let changed = false;
      const next: WorkflowGroupData = { ...prev };

      workflowGroups.forEach((group) => {
        const state = dynamicValidationByGroup[group.group_key];
        if (!state || state.loading) return;

        const selectedValues = prev[group.group_key]?.selected_values || [];
        const filteredValues = selectedValues.filter((value) => !state.disabledValues[String(value)]);

        if (filteredValues.length !== selectedValues.length) {
          changed = true;
          next[group.group_key] = {
            group_key: group.group_key,
            selected_values: filteredValues
          };
        }
      });

      return changed ? next : prev;
    });
  }, [dynamicValidationByGroup, workflowGroups, setWorkflowGroupData]);

  const validationErrors = useMemo(() => {
    const out: Record<string, string | null> = {};
    for (const group of workflowGroups) {
      out[group.group_key] = getWorkflowGroupValidationError(group, workflowGroupData);
    }
    return out;
  }, [workflowGroups, workflowGroupData]);

  const isValid = useMemo(
    () => workflowGroups.every((group) => !validationErrors[group.group_key]),
    [workflowGroups, validationErrors]
  );

  const toggleOption = (group: ProjectWorkflowGroup, optionValue: string) => {
    if (getOptionDisabledReason(group, optionValue, dynamicValidationByGroup)) {
      return;
    }

    setWorkflowGroupData((prev) => {
      const existing = prev[group.group_key]?.selected_values || [];
      const nextValues = existing.includes(optionValue)
        ? existing.filter((value) => value !== optionValue)
        : [...existing, optionValue];

      return {
        ...prev,
        [group.group_key]: {
          group_key: group.group_key,
          selected_values: nextValues
        }
      };
    });
  };

  const toggleOptionHelp = (optionId: string) => {
    setOpenHelpByOption((prev) => ({
      ...prev,
      [optionId]: !prev[optionId]
    }));
  };

  return (
    <>
      <div className="page-container">
        <div className="child-container-top">
          {workflowGroups.map((group) => {
            const selectedValues = workflowGroupData[group.group_key]?.selected_values || [];
            const options = Array.isArray(group.options) ? [...group.options] : [];
            const groupValidationState = dynamicValidationByGroup[group.group_key];

            options.sort((a, b) => {
              const aOrder = typeof a?.option_order === "number" ? a.option_order : Number.MAX_SAFE_INTEGER;
              const bOrder = typeof b?.option_order === "number" ? b.option_order : Number.MAX_SAFE_INTEGER;
              if (aOrder !== bOrder) return aOrder - bOrder;
              return String(a?.option_label || a?.option_value || "").localeCompare(
                String(b?.option_label || b?.option_value || "")
              );
            });

            return (
              <div key={group.group_key} className="patient-filter-section">
                <div className="patient-filter-section-header">
                  <h3>{group.group_label}</h3>
                  {group.group_description ? (
                    <p className="workflow-group-selection-page-p">{group.group_description}</p>
                  ) : null}
                  {groupValidationState?.loading ? (
                    <p className="workflow-group-selection-page-p-4b146">Checking available options...</p>
                  ) : null}
                  {!groupValidationState?.loading && groupValidationState?.error ? (
                    <p className="workflow-group-selection-page-p-f9f43">{groupValidationState.error}</p>
                  ) : null}
                </div>

                <div
                  className="workflow-group-selection-page-block-01"
                >
                  {options.map((option) => {
                    const optionValue = String(option.option_value);
                    const disabledReason = getOptionDisabledReason(group, optionValue, dynamicValidationByGroup);
                    const disabled = Boolean(disabledReason);
                    const checked = selectedValues.includes(optionValue);
                    const optionId = `${group.group_key}_${option.option_key || option.option_value}`;
                    const baseOptionLabel = option.option_label || option.option_value;
                    const suffix = group.validation_config?.disabled_label_suffix || "";
                    const optionLabel = disabled && suffix ? `${baseOptionLabel}${suffix}` : baseOptionLabel;
                    const helpText = (option as any)?.option_description || (option as any)?.description || "";
                    const helpOpen = !!openHelpByOption[optionId];

                    return (
                      <div
                        key={optionId}
                        className="workflow-group-selection-page-block-02" style={{ opacity: disabled ? 0.65 : 1 }}
                      >
                        <label
                          className="workflow-group-selection-page-block-03" style={{ cursor: disabled ? "not-allowed" : "pointer" }}
                          title={disabledReason || undefined}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={disabled}
                            onChange={() => toggleOption(group, optionValue)}
                          />
                          <div
                            className="workflow-group-selection-page-block-04"
                          >
                            <span>{optionLabel}</span>
                            {helpText ? (
                              <HelpToggle
                                open={helpOpen}
                                onToggle={() => toggleOptionHelp(optionId)}
                                ariaLabel={`Show help for ${baseOptionLabel}`}
                                title={`Show help for ${baseOptionLabel}`}
                              />
                            ) : null}
                          </div>
                        </label>
                        {disabledReason ? (
                          <div className="workflow-group-selection-page-block-05">
                            {disabledReason}
                          </div>
                        ) : null}
                        <HelpPanel open={helpOpen} text={helpText} />
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {workflowGroups.some((group) => validationErrors[group.group_key]) && (
            <div className="workflow-group-selection-page-block-06">
              {workflowGroups
                .map((group) => validationErrors[group.group_key])
                .filter(Boolean)
                .map((msg, idx) => (
                  <div key={idx}>{msg}</div>
                ))}
            </div>
          )}
        </div>
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>
            {backToButtonText}
          </button>
          <button className="wizard-next-button" onClick={onNext} disabled={!isValid}>
            Set Function Configuration
          </button>
        </div>
      </div>
    </>
  );
};

export default WorkflowGroupSelectionPage;
