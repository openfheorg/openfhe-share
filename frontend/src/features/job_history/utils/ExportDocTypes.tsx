export type ExportFormat = "pdf" | "docx" | "html" | "png";

export type ExportKeyValue = { label: string; value: string };

export type ExportBlock =
  | { kind: "heading"; text: string; level?: 1 | 2 | 3; optionId?: string }
  | { kind: "paragraph"; text: string; optionId?: string }
  | { kind: "keyValues"; items: ExportKeyValue[]; columns?: number; optionId?: string }
  | { kind: "table"; columns: string[]; rows: (string | number)[][]; optionId?: string }
  | { kind: "image"; dataUrl: string; alt?: string; caption?: string; width?: number; height?: number; optionId?: string }
  | { kind: "html"; html: string; optionId?: string }
  | { kind: "spacer"; mm?: number; size?: "sm" | "md" | "lg"; optionId?: string }
  | { kind: "pageBreak"; optionId?: string };

export type ExportSectionOption = {
  id: string;
  label: string;
  checkedByDefault?: boolean;
};

export type ExportWorkflow = {
  id: string;
  title?: string;
  blocks: ExportBlock[];
  options?: ExportSectionOption[];
};

export type ExportSection = {
  id?: string;
  title: string;
  blocks?: ExportBlock[];
  workflows?: ExportWorkflow[];
  options?: ExportSectionOption[];
};

export type ExportSectionSelection = {
  sectionId: string;
  selectedOptionIds: string[];
  selectedWorkflowIds?: string[];
  optionSelectionsByWorkflowId?: Record<string, string[]>;
};

export type ExportDocument = {
  title: string;
  generatedAt: string;
  sections: ExportSection[];
};
