import React, { useState } from "react";
import FunctionSelector, { FUNCTION_METADATA } from "../../../components/FunctionSelector";
import { FunctionConfigs, ThresholdConfig } from "../../../types/FunctionConfigs";
import { Project } from "../../../types/Project";
import { FilterCollection } from "../utils/FilterPayloadConfigUtils";

interface Props {
  project: Project;
  onBack: () => void;
  onNext: () => void;
  setSelectedFunctions: (selection: FunctionConfigs) => void;
  existingFunctions: FunctionConfigs;
  setSelectedThresholdConfig: (selection: ThresholdConfig) => void;
  existingThresholdConfig: ThresholdConfig;
  filterSet?: FilterCollection;
  backToButtonText?: string;
}

const FunctionSelectionPage: React.FC<Props> = ({
  project,
  onBack,
  onNext,
  setSelectedFunctions,
  existingFunctions,
  setSelectedThresholdConfig,
  existingThresholdConfig,
  filterSet,
  backToButtonText = "Back to Observation Filters"
}) => {
  const [selectedFunctionConfigs, setSelectedFunctionConfigs] =
    useState<FunctionConfigs>(existingFunctions || {});

  function emitSelectedFunctions(nextSelection: FunctionConfigs) {
    setSelectedFunctionConfigs(nextSelection);
    setSelectedFunctions(nextSelection);
  }

  function emitSelectedThresholdConfig(nextSelection: ThresholdConfig) {
    setSelectedThresholdConfig(nextSelection);
  }

  function getDuplicateMessages(): string[] {
    const messages: string[] = [];

    for (const [fnId, configs] of Object.entries(selectedFunctionConfigs)) {
      if (!configs || configs.length <= 1) continue;

      const seen: {
        [signature: string]: { indices: number[]; cfg: Record<string, string> };
      } = {};

      configs.forEach((cfg, idx) => {
        const keys = Object.keys(cfg).sort();
        const normalizedObj: Record<string, string> = {};
        for (const k of keys) {
          normalizedObj[k] = cfg[k];
        }
        const signature = JSON.stringify(normalizedObj);
        if (!seen[signature]) {
          seen[signature] = { indices: [idx], cfg: normalizedObj };
        } else {
          seen[signature].indices.push(idx);
        }
      });

      Object.keys(seen).forEach((signature) => {
        const entry = seen[signature];
        if (entry.indices.length > 1) {
          const cfg = entry.cfg;
          const fnMeta = FUNCTION_METADATA.find((f) => f.id === fnId);
          const fnTitle = fnMeta?.title || fnId;
          const keys = Object.keys(cfg).sort();
          const summary = keys.map((k) => `${k}: ${cfg[k]}`).join(", ");
          const configLabels = entry.indices.map((i) => i + 1).join(", ");
          messages.push(`${fnTitle} (configs ${configLabels}): ${summary}`);
        }
      });
    }

    return messages;
  }

  function normalizeModelType(modelType: string): string {
    return modelType.trim().toLowerCase().replace(/[\s_-]+/g, "");
  }

  function formatModelType(modelType: string): string {
    const normalized = normalizeModelType(modelType);
    if (normalized === "openaccess") return "Open Access";
    if (normalized === "encrypted") return "Encrypted";
    return modelType.trim();
  }

  function getMixedModelTypeMessages(): string[] {
    const byModelType: Record<string, string[]> = {};
    const displayByModelType: Record<string, string> = {};

    for (const [fnId, configs] of Object.entries(selectedFunctionConfigs)) {
      const fnMeta = FUNCTION_METADATA.find((f) => f.id === fnId);
      const fnTitle = fnMeta?.title || fnId;

      (configs || []).forEach((cfg, idx) => {
        const rawModelType = cfg.model_type;
        if (!rawModelType || String(rawModelType).trim() === "") return;

        const normalized = normalizeModelType(String(rawModelType));
        if (!normalized) return;

        if (!byModelType[normalized]) {
          byModelType[normalized] = [];
          displayByModelType[normalized] = formatModelType(String(rawModelType));
        }

        byModelType[normalized].push(`${fnTitle} config ${idx + 1}`);
      });
    }

    const selectedModelTypes = Object.keys(byModelType);
    if (selectedModelTypes.length <= 1) return [];

    return selectedModelTypes
      .sort((a, b) => displayByModelType[a].localeCompare(displayByModelType[b]))
      .map((modelType) => {
        const display = displayByModelType[modelType];
        const configs = byModelType[modelType].join(", ");
        return `${display}: ${configs}`;
      });
  }

  const duplicateMessages = getDuplicateMessages();
  const hasDuplicates = duplicateMessages.length > 0;
  const mixedModelTypeMessages = getMixedModelTypeMessages();
  const hasMixedModelTypes = mixedModelTypeMessages.length > 0;

  const disableNext =
    Object.keys(selectedFunctionConfigs).length === 0 ||
    hasDuplicates ||
    hasMixedModelTypes;

  return (
    <>
      <div className="page-container">
        <div className="child-container-top">
          <FunctionSelector
            onSelectionFunctionConfigChange={emitSelectedFunctions}
            initialSelectedFunctions={existingFunctions}
            onThresholdSamplesChange={emitSelectedThresholdConfig}
            initialSelectedThresholdConfig={existingThresholdConfig}
            project={project}
            filterSet={filterSet}
          />
        </div>
      </div>

      <div className="page-container">
        {hasDuplicates && (
          <div className="child-container-error">
            Duplicate configurations detected. Please ensure each function
            configuration has unique property values.
            <ul className="function-selection-page-shared-01">
              {duplicateMessages.map((msg, idx) => (
                <li key={idx} className="function-selection-page-shared-02">
                  {msg}
                </li>
              ))}
            </ul>
          </div>
        )}

        {hasMixedModelTypes && (
          <div className="child-container-error">
            Mixed model types are not supported in a single job. Once a
            model_type is selected, all selected function configurations that
            include model_type must use that same value.
            <ul className="function-selection-page-shared-01">
              {mixedModelTypeMessages.map((msg, idx) => (
                <li key={idx} className="function-selection-page-shared-02">
                  {msg}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button wizard-back-button" onClick={onBack}>
            {backToButtonText}
          </button>
          <button className="wizard-next-button" onClick={onNext} disabled={disableNext}>
            Review Submission Details
          </button>
        </div>
      </div>
    </>
  );
};

export default FunctionSelectionPage;
