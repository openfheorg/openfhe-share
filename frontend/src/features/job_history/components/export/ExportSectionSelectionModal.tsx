import { useEffect, useMemo, useState } from "react";
import { toPng } from "html-to-image";
import AbstractModal from "../../../../components/AbstractModal";
import { ExportBlock, ExportDocument, ExportFormat, ExportSection, ExportWorkflow } from "../../utils/ExportDocTypes";
import { getExportDocumentCss, renderExportDocumentBodyHtml } from "../../utils/ExportDocumentRenderUtils";

type ExportSectionDraft = {
  id: string;
  title: string;
  section: ExportSection;
};

export type ExportWorkflowSelectionBySectionId = Record<
  string,
  {
    workflowIds: string[];
    optionSelectionsByWorkflowId: Record<string, string[]>;
  }
>;

interface ExportSectionSelectionModalProps {
  isOpen: boolean;
  format: ExportFormat | null;
  sections: ExportSectionDraft[];
  isExporting?: boolean;
  onBack: () => void;
  onClose: () => void;
  onExport: (
    sectionIds: string[],
    optionSelectionsBySectionId: Record<string, string[]>,
    workflowSelectionsBySectionId: ExportWorkflowSelectionBySectionId
  ) => void;
}

function formatLabel(format: ExportFormat | null): string {
  if (format === "docx") return "Word Document";
  if (format === "html") return "HTML";
  if (format === "png") return "PNG Image";
  return "PDF";
}

function blockOptionId(block: ExportBlock): string | undefined {
  return "optionId" in block ? block.optionId : undefined;
}

function shouldIncludeBlock(block: ExportBlock, selectedOptionIds: string[]): boolean {
  const optionId = blockOptionId(block);
  return !optionId || selectedOptionIds.includes(optionId);
}

function normalizeExportSectionText(value: string | undefined): string {
  return String(value || "").trim().toLowerCase();
}

function isKaplanMeierExportSection(section: ExportSectionDraft): boolean {
  const id = normalizeExportSectionText(section.id);
  const title = normalizeExportSectionText(section.title || section.section.title);
  return id.includes("kaplan") || title.includes("kaplan") || title.includes("survival curve");
}

function isSurvivalTableExportOption(option: { id: string; label: string }): boolean {
  const id = normalizeExportSectionText(option.id);
  const label = normalizeExportSectionText(option.label);
  return (id.includes("survival") && id.includes("table")) || (label.includes("survival") && label.includes("table"));
}

function hasSurvivalTableExportOptions(section: ExportSectionDraft): boolean {
  return (section.section.workflows || []).some((workflow) => (workflow.options || []).some(isSurvivalTableExportOption));
}

function areAllSurvivalTableExportOptionsSelected(
  section: ExportSectionDraft,
  workflowSelection: { workflowIds: string[]; optionSelectionsByWorkflowId: Record<string, string[]> }
): boolean {
  const selectedWorkflowIds = new Set(workflowSelection.workflowIds);
  const workflows = section.section.workflows || [];
  const selectedWorkflows = workflows.filter((workflow) => selectedWorkflowIds.has(workflow.id));
  const workflowsToCheck = selectedWorkflows.length > 0 ? selectedWorkflows : workflows;
  const workflowsWithSurvivalTables = workflowsToCheck.filter((workflow) => (workflow.options || []).some(isSurvivalTableExportOption));

  if (!workflowsWithSurvivalTables.length) {
    return false;
  }

  return workflowsWithSurvivalTables.every((workflow) => {
    const selectedOptionIds = workflowSelection.optionSelectionsByWorkflowId[workflow.id] || [];
    return (workflow.options || [])
      .filter(isSurvivalTableExportOption)
      .every((option) => selectedOptionIds.includes(option.id));
  });
}

export default function ExportSectionSelectionModal({
  isOpen,
  format,
  sections,
  isExporting,
  onBack,
  onClose,
  onExport,
}: ExportSectionSelectionModalProps) {
  const isPngExport = format === "png";
  const defaultSelectedSectionIds = useMemo(() => sections.map((section) => section.id), [sections]);
  const [selectedSectionIds, setSelectedSectionIds] = useState<string[]>(defaultSelectedSectionIds);
  const [optionSelectionsBySectionId, setOptionSelectionsBySectionId] = useState<Record<string, string[]>>({});
  const [workflowSelectionsBySectionId, setWorkflowSelectionsBySectionId] = useState<ExportWorkflowSelectionBySectionId>({});
  const [pngPreviewDataUrl, setPngPreviewDataUrl] = useState<string | null>(null);
  const [pngPreviewLoading, setPngPreviewLoading] = useState(false);
  const [pngPreviewError, setPngPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    setSelectedSectionIds(defaultSelectedSectionIds);
    setOptionSelectionsBySectionId(
      sections.reduce<Record<string, string[]>>((acc, section) => {
        const options = section.section.options || [];
        acc[section.id] = options.filter((option) => option.checkedByDefault !== false).map((option) => option.id);
        return acc;
      }, {})
    );
    setWorkflowSelectionsBySectionId(
      sections.reduce<ExportWorkflowSelectionBySectionId>((acc, section) => {
        const workflows = section.section.workflows || [];
        acc[section.id] = {
          workflowIds: workflows.map((workflow) => workflow.id),
          optionSelectionsByWorkflowId: workflows.reduce<Record<string, string[]>>((wfAcc, workflow) => {
            wfAcc[workflow.id] = (workflow.options || [])
              .filter((option) => option.checkedByDefault !== false)
              .map((option) => option.id);
            return wfAcc;
          }, {}),
        };
        return acc;
      }, {})
    );
  }, [isOpen, defaultSelectedSectionIds, sections]);

  useEffect(() => {
    if (!isOpen || !isPngExport) {
      setPngPreviewDataUrl(null);
      setPngPreviewLoading(false);
      setPngPreviewError(null);
      return;
    }

    let cancelled = false;

    async function generatePngPreview() {
      setPngPreviewLoading(true);
      setPngPreviewError(null);

      try {
        await new Promise((resolve) => window.requestAnimationFrame(() => resolve(null)));

        const exportRoot = window.document.getElementById("share-results-export-root");
        if (!exportRoot) {
          if (!cancelled) {
            setPngPreviewError("Unable to find the current Results Viewer.");
          }
          return;
        }

        const dataUrl = await toPng(exportRoot, {
          backgroundColor: "#ffffff",
          pixelRatio: 0.35,
          cacheBust: true,
        });

        if (!cancelled) {
          setPngPreviewDataUrl(dataUrl);
        }
      } catch {
        if (!cancelled) {
          setPngPreviewError("Unable to generate the current Results Viewer preview.");
        }
      } finally {
        if (!cancelled) {
          setPngPreviewLoading(false);
        }
      }
    }

    generatePngPreview();

    return () => {
      cancelled = true;
    };
  }, [isOpen, isPngExport]);

  const selectedCount = selectedSectionIds.length;
  const allSelected = sections.length > 0 && selectedCount === sections.length;

  const previewDocument = useMemo<ExportDocument>(() => {
    const selectedSections = sections
      .filter((section) => selectedSectionIds.includes(section.id))
      .map((section) => {
        const selectedSectionOptionIds = optionSelectionsBySectionId[section.id] || [];
        const workflowSelection = workflowSelectionsBySectionId[section.id] || { workflowIds: [], optionSelectionsByWorkflowId: {} };
        const workflows = (section.section.workflows || [])
          .filter((workflow: ExportWorkflow) => workflowSelection.workflowIds.includes(workflow.id))
          .map((workflow: ExportWorkflow) => {
            const selectedWorkflowOptionIds = workflowSelection.optionSelectionsByWorkflowId[workflow.id] || [];
            return {
              ...workflow,
              blocks: (workflow.blocks || []).filter((block) => shouldIncludeBlock(block, selectedWorkflowOptionIds)),
            };
          });

        return {
          ...section.section,
          id: section.section.id || section.id,
          title: section.title || section.section.title,
          blocks: (section.section.blocks || []).filter((block) => shouldIncludeBlock(block, selectedSectionOptionIds)),
          workflows,
        };
      });

    return {
      title: "SHARE Job Results Export",
      generatedAt: new Date().toLocaleString(),
      sections: isPngExport ? [] : selectedSections,
    };
  }, [isPngExport, sections, selectedSectionIds, optionSelectionsBySectionId, workflowSelectionsBySectionId]);

  const previewHtml = useMemo(() => renderExportDocumentBodyHtml(previewDocument, true), [previewDocument]);
  const previewCss = useMemo(() => getExportDocumentCss(".duality-export-preview-pane"), []);

  const selectedWorkflowCount = useMemo(() => {
    if (isPngExport) return 0;

    return sections.reduce((count, section) => {
      if (!selectedSectionIds.includes(section.id)) return count;
      return count + (workflowSelectionsBySectionId[section.id]?.workflowIds.length || 0);
    }, 0);
  }, [isPngExport, sections, selectedSectionIds, workflowSelectionsBySectionId]);

  const toggleSection = (id: string, checked: boolean) => {
    setSelectedSectionIds((prev) => {
      if (!checked && prev.length <= 1 && prev.includes(id)) {
        return prev;
      }

      const next = checked ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter((sectionId) => sectionId !== id);
      return sections.map((section) => section.id).filter((sectionId) => next.includes(sectionId));
    });
  };

  const toggleSectionOption = (sectionId: string, optionId: string, checked: boolean) => {
    setOptionSelectionsBySectionId((prev) => {
      const current = prev[sectionId] || [];
      const next = checked ? (current.includes(optionId) ? current : [...current, optionId]) : current.filter((id) => id !== optionId);
      return { ...prev, [sectionId]: next };
    });
  };

  const toggleWorkflow = (sectionId: string, workflowId: string, checked: boolean) => {
    setWorkflowSelectionsBySectionId((prev) => {
      const section = sections.find((entry) => entry.id === sectionId);
      const workflowIds = section?.section.workflows?.map((workflow) => workflow.id) || [];
      const current = prev[sectionId]?.workflowIds || [];

      if (!checked && current.length <= 1 && current.includes(workflowId)) {
        return prev;
      }

      const next = checked ? (current.includes(workflowId) ? current : [...current, workflowId]) : current.filter((id) => id !== workflowId);
      return {
        ...prev,
        [sectionId]: {
          workflowIds: workflowIds.filter((id) => next.includes(id)),
          optionSelectionsByWorkflowId: prev[sectionId]?.optionSelectionsByWorkflowId || {},
        },
      };
    });
  };

  const toggleWorkflowOption = (sectionId: string, workflowId: string, optionId: string, checked: boolean) => {
    setWorkflowSelectionsBySectionId((prev) => {
      const sectionSelection = prev[sectionId] || { workflowIds: [], optionSelectionsByWorkflowId: {} };
      const current = sectionSelection.optionSelectionsByWorkflowId[workflowId] || [];
      const next = checked ? (current.includes(optionId) ? current : [...current, optionId]) : current.filter((id) => id !== optionId);
      return {
        ...prev,
        [sectionId]: {
          ...sectionSelection,
          optionSelectionsByWorkflowId: {
            ...sectionSelection.optionSelectionsByWorkflowId,
            [workflowId]: next,
          },
        },
      };
    });
  };

  const toggleAllSurvivalTableOptions = (section: ExportSectionDraft, checked: boolean) => {
    setWorkflowSelectionsBySectionId((prev) => {
      const currentSelection = prev[section.id] || { workflowIds: [], optionSelectionsByWorkflowId: {} };
      const nextOptionSelectionsByWorkflowId = { ...currentSelection.optionSelectionsByWorkflowId };

      (section.section.workflows || []).forEach((workflow) => {
        const survivalTableOptionIds = (workflow.options || [])
          .filter(isSurvivalTableExportOption)
          .map((option) => option.id);

        if (!survivalTableOptionIds.length) {
          return;
        }

        const currentOptionIds = nextOptionSelectionsByWorkflowId[workflow.id] || [];
        nextOptionSelectionsByWorkflowId[workflow.id] = checked
          ? Array.from(new Set([...currentOptionIds, ...survivalTableOptionIds]))
          : currentOptionIds.filter((optionId) => !survivalTableOptionIds.includes(optionId));
      });

      return {
        ...prev,
        [section.id]: {
          ...currentSelection,
          optionSelectionsByWorkflowId: nextOptionSelectionsByWorkflowId,
        },
      };
    });
  };

  const selectAllSections = (checked: boolean) => {
    if (checked) {
      setSelectedSectionIds(sections.map((section) => section.id));
    } else if (sections.length > 0) {
      setSelectedSectionIds([sections[0].id]);
    }
  };

  const handleExport = () => {
    onExport(isPngExport ? defaultSelectedSectionIds : selectedSectionIds, optionSelectionsBySectionId, workflowSelectionsBySectionId);
  };

  const footer = (
    <div className="export-section-selection-modal-block-01">
      <button className="secondary-button" type="button" onClick={onBack} disabled={isExporting}>
        Back
      </button>
      <button
        type="button"
        onClick={handleExport}
        disabled={isExporting || (!isPngExport && (sections.length === 0 || selectedSectionIds.length === 0))}
      >
        {isExporting ? "Exporting..." : isPngExport ? "Export Current Results Viewer" : `Export ${formatLabel(format)}`}
      </button>
    </div>
  );

  return (
    <AbstractModal
      isOpen={isOpen}
      title="Select Content to Export"
      ariaLabel="Export section selection modal"
      onClose={onClose}
      width={isPngExport ? "min(860px, 96vw)" : "min(1240px, 98vw)"}
      bodyStyle={{ padding: "1.5rem" }}
      titleStyle={{ fontSize: "16pt", marginLeft: "1rem", color: "#3F5FFF", fontWeight: 700, width: "100%" }}
      closeButtonDisabled={isExporting}
      footer={footer}
    >
      <div className="export-section-selection-modal-block-02">{formatLabel(format)}</div>
      {isPngExport ? (
        <div
          className="export-section-selection-modal-block-03"
        >
          <div
            className="export-section-selection-modal-block-04"
          >
            <div className="export-section-selection-modal-block-05">PNG exports are a screen grab of the current Results Viewer.</div>
            <div>
              Section and workflow selections are not customized for PNG output. To adjust what appears in the exported image, change the visible Results Viewer first, then export the current view.
            </div>
          </div>

          <div className="export-section-selection-modal-block-06">
            <div className="export-section-selection-modal-block-07">
              <div
                className="export-section-selection-modal-block-08"
              >
                {pngPreviewLoading ? (
                  <div className="export-section-selection-modal-shared-01">Generating preview...</div>
                ) : pngPreviewError ? (
                  <div className="export-section-selection-modal-shared-01">{pngPreviewError}</div>
                ) : pngPreviewDataUrl ? (
                  <>
                    <img
                      src={pngPreviewDataUrl}
                      alt="Current Results Viewer PNG preview"
                      className="export-section-selection-modal-current-results-viewer-png-preview"
                    />
                    <div
                      className="export-section-selection-modal-block-09"
                    />
                  </>
                ) : (
                  <div className="export-section-selection-modal-shared-01">Preview unavailable.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : sections.length === 0 ? (
        <div className="duality-text-muted">No exportable sections are currently available.</div>
      ) : (
        <div className="export-section-selection-modal-block-10">
          <div className="duality-min-width-0">
            <div className="export-section-selection-modal-block-11">
              <label className="export-section-selection-modal-shared-02">
                <input type="checkbox" checked={allSelected} onChange={(e) => selectAllSections(e.target.checked)} />
                Select all sections
              </label>
              <div className="export-section-selection-modal-block-12">{selectedCount} selected</div>
            </div>

            <div className="export-section-selection-modal-block-13">
              {sections.map((section) => {
                const sectionOptions = section.section.options || [];
                const workflows = section.section.workflows || [];
                const selected = selectedSectionIds.includes(section.id);
                const workflowSelection = workflowSelectionsBySectionId[section.id] || { workflowIds: [], optionSelectionsByWorkflowId: {} };
                const showSurvivalTableToggle = isKaplanMeierExportSection(section) && hasSurvivalTableExportOptions(section);
                const allSurvivalTablesSelected = showSurvivalTableToggle && areAllSurvivalTableExportOptionsSelected(section, workflowSelection);

                return (
                  <div key={section.id} className="export-section-selection-modal-block-14">
                    <div className="export-section-selection-modal-block-15">
                      <label className="export-section-selection-modal-block-16">
                        <input type="checkbox" checked={selected} onChange={(e) => toggleSection(section.id, e.target.checked)} />
                        {section.title}
                      </label>

                      {showSurvivalTableToggle && (
                        <label className="export-section-selection-modal-block-17" style={{ color: selected ? "#374151" : "#6b7280" }}>
                          <input
                            type="checkbox"
                            disabled={!selected}
                            checked={allSurvivalTablesSelected}
                            onChange={(e) => toggleAllSurvivalTableOptions(section, e.target.checked)}
                          />
                          Include Survival Tables
                        </label>
                      )}
                    </div>

                    {workflows.length > 0 && (
                      <div className="export-section-selection-modal-block-18">
                        {workflows.map((workflow) => {
                          const workflowSelected = workflowSelection.workflowIds.includes(workflow.id);
                          const workflowOptions = workflow.options || [];
                          const selectedWorkflowOptions = workflowSelection.optionSelectionsByWorkflowId[workflow.id] || [];

                          return (
                            <div key={workflow.id} className="export-section-selection-modal-block-19">
                              <label className="export-section-selection-modal-shared-02" style={{ color: selected ? "#111827" : "#6b7280" }}>
                                <input
                                  type="checkbox"
                                  disabled={!selected}
                                  checked={workflowSelected}
                                  onChange={(e) => toggleWorkflow(section.id, workflow.id, e.target.checked)}
                                />
                                {workflow.title || workflow.id}
                              </label>

                              {workflowOptions.length > 0 && (
                                <div className="export-section-selection-modal-block-20">
                                  {workflowOptions.map((option) => (
                                    <label key={option.id} className="duality-flex-center-gap-8" style={{ color: selected && workflowSelected ? "#111827" : "#6b7280" }}>
                                      <input
                                        type="checkbox"
                                        disabled={!selected || !workflowSelected}
                                        checked={selectedWorkflowOptions.includes(option.id)}
                                        onChange={(e) => toggleWorkflowOption(section.id, workflow.id, option.id, e.target.checked)}
                                      />
                                      {option.label}
                                    </label>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {sectionOptions.length > 0 && workflows.length === 0 && (
                      <div className="export-section-selection-modal-block-21">
                        {sectionOptions.map((option) => (
                          <label key={option.id} className="duality-flex-center-gap-8" style={{ color: selected ? "#111827" : "#6b7280" }}>
                            <input
                              type="checkbox"
                              disabled={!selected}
                              checked={(optionSelectionsBySectionId[section.id] || []).includes(option.id)}
                              onChange={(e) => toggleSectionOption(section.id, option.id, e.target.checked)}
                            />
                            {option.label}
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="export-section-selection-modal-block-22">
            <style>{previewCss}</style>
            <div className="export-section-selection-modal-block-23">
              <div className="export-section-selection-modal-block-24">Export Preview</div>
              <div className="export-section-selection-modal-block-25">
                {selectedCount} section{selectedCount === 1 ? "" : "s"}{selectedWorkflowCount > 0 ? `, ${selectedWorkflowCount} workflow${selectedWorkflowCount === 1 ? "" : "s"}` : ""}
              </div>
            </div>
            <div className="duality-export-preview-pane export-section-selection-modal-block-26" >
              {previewDocument.sections.length > 0 ? (
                <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
              ) : (
                <div className="export-section-selection-modal-block-27">Select at least one section to preview the export content.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </AbstractModal>
  );
}
