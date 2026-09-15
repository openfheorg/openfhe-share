import { ExportDocument } from "./ExportDocTypes";
import { renderExportDocumentHtml } from "./ExportDocumentRenderUtils";

export function renderExportHtml(document: ExportDocument): string {
  return renderExportDocumentHtml(document);
}

export function downloadHtml(document: ExportDocument, filename: string): void {
  const html = renderExportHtml(document);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = window.document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
