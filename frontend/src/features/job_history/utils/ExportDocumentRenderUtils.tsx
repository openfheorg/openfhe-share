import { ExportBlock, ExportDocument, ExportSection, ExportWorkflow } from "./ExportDocTypes";

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderSpacer(block: Extract<ExportBlock, { kind: "spacer" }>): string {
  const height = block.mm ? `${block.mm}mm` : block.size === "lg" ? "18px" : block.size === "sm" ? "6px" : "10px";
  return `<div class="duality-export-spacer" style="height:${height}"></div>`;
}

function chunkRows<T>(rows: T[], chunkSize: number): T[][] {
  if (!rows.length) return [];
  if (chunkSize <= 0 || rows.length <= chunkSize) return [rows];

  const chunks: T[][] = [];
  for (let i = 0; i < rows.length; i += chunkSize) {
    chunks.push(rows.slice(i, i + chunkSize));
  }

  return chunks;
}

function shouldUseCompactTableGrid(columns: unknown[], rows: unknown[]): boolean {
  return columns.length <= 3 && rows.length > 16;
}

function renderBlock(block: ExportBlock): string {
  if (block.kind === "pageBreak") {
    return `<div class="duality-export-page-break"><span>Page break</span></div>`;
  }

  if (block.kind === "spacer") {
    return renderSpacer(block);
  }

  if (block.kind === "heading") {
    const level = block.level === 1 ? 1 : block.level === 3 ? 3 : 2;
    return `<h${level} class="duality-export-block-heading duality-export-heading-${level}">${escapeHtml(block.text)}</h${level}>`;
  }

  if (block.kind === "paragraph") {
    return `<p class="duality-export-paragraph">${escapeHtml(block.text)}</p>`;
  }

  if (block.kind === "keyValues") {
    const items = block.items || [];
    if (!items.length) return "";

    const rows = items
      .map(
        (item) =>
          `<tr><th>${escapeHtml(item.label)}</th><td>${escapeHtml(item.value)}</td></tr>`
      )
      .join("");

    return `<table class="duality-export-table duality-export-key-values"><tbody>${rows}</tbody></table>`;
  }

  if (block.kind === "table") {
    const columns = block.columns || [];
    const rows = block.rows || [];
    if (!columns.length || !rows.length) return "";

    const header = columns
      .map((column) =>
        String(column ?? "").trim()
          ? `<th>${escapeHtml(column)}</th>`
          : `<td class="duality-export-empty-header-cell"></td>`
      )
      .join("");
    const compactGrid = shouldUseCompactTableGrid(columns, rows);
    const rowChunks = compactGrid ? chunkRows(rows, 18) : [rows];

    const tables = rowChunks
      .map((rowChunk) => {
        const body = rowChunk
          .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`)
          .join("");

        return `
          <div class="duality-export-table-wrap">
            <table class="duality-export-table">
              <thead><tr>${header}</tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>`;
      })
      .join("");

    return compactGrid ? `<div class="duality-export-table-grid">${tables}</div>` : tables;
  }

  if (block.kind === "image") {
    if (!block.dataUrl) return "";
    const caption = block.caption ? `<figcaption>${escapeHtml(block.caption)}</figcaption>` : "";
    return `
      <figure class="duality-export-figure">
        <img src="${escapeHtml(block.dataUrl)}" alt="${escapeHtml(block.alt || block.caption || "Export image")}" />
        ${caption}
      </figure>`;
  }

  if (block.kind === "html") {
    return `<div class="duality-export-html-block">${block.html || ""}</div>`;
  }

  return "";
}

function renderWorkflow(workflow: ExportWorkflow): string {
  const blocks = (workflow.blocks || []).map(renderBlock).join("\n");

  return `
    <article class="duality-export-workflow" id="${escapeHtml(workflow.id)}">
      <div class="duality-export-workflow-title">Workflow: ${escapeHtml(workflow.title || workflow.id)}</div>
      ${blocks || `<div class="duality-export-empty">No workflow content selected.</div>`}
    </article>`;
}

function renderSection(section: ExportSection): string {
  const sectionBlocks = (section.blocks || []).map(renderBlock).join("\n");
  const workflowBlocks = (section.workflows || []).map(renderWorkflow).join("\n");
  const empty = !sectionBlocks && !workflowBlocks ? `<div class="duality-export-empty">No content selected for this section.</div>` : "";

  return `
    <section class="duality-export-section" id="${escapeHtml(section.id || "")}">
      <div class="duality-export-section-title">${escapeHtml(section.title)}</div>
      ${sectionBlocks}
      ${workflowBlocks}
      ${empty}
    </section>`;
}

export function getExportDocumentCss(scopeSelector = ""): string {
  const scope = scopeSelector ? `${scopeSelector} ` : "";

  return `
    ${scope}.duality-export-document {
      box-sizing: border-box;
      width: 100%;
      background: white;
      color: #111827;
      font-family: Arial, Helvetica, sans-serif;
      padding: 18px;
      line-height: 1.35;
    }

    ${scope}.duality-export-document * {
      box-sizing: border-box;
    }

    ${scope}.duality-export-header {
      border: 1px solid #dbe3ef;
      border-radius: 6px;
      padding: 14px 16px;
      background: #ffffff;
      margin-bottom: 12px;
    }

    ${scope}.duality-export-title {
      font-size: 20px;
      line-height: 1.2;
      font-weight: 800;
      color: #111827;
      margin: 0 0 4px;
    }

    ${scope}.duality-export-generated {
      color: #64748b;
      font-size: 12px;
      margin: 0;
    }

    ${scope}.duality-export-section {
      border: 1px solid #dbe3ef;
      border-radius: 6px;
      padding: 14px;
      background: #ffffff;
      margin-bottom: 12px;
      break-inside: avoid;
      page-break-inside: avoid;
    }

    ${scope}.duality-export-section-title {
      font-size: 16px;
      line-height: 1.2;
      font-weight: 800;
      color: #3F5FFF;
      margin-bottom: 9px;
    }

    ${scope}.duality-export-workflow {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #e5e7eb;
      break-inside: avoid;
      page-break-inside: avoid;
    }

    ${scope}.duality-export-workflow-title {
      font-size: 14px;
      line-height: 1.25;
      font-weight: 700;
      color: #1f2937;
      margin-bottom: 6px;
    }

    ${scope}.duality-export-block-heading {
      font-weight: 700;
      color: #111827;
      margin: 10px 0 6px;
      line-height: 1.25;
    }

    ${scope}.duality-export-heading-1 {
      font-size: 18px;
    }

    ${scope}.duality-export-heading-2 {
      font-size: 16px;
    }

    ${scope}.duality-export-heading-3 {
      font-size: 14px;
    }

    ${scope}.duality-export-paragraph {
      font-size: 13px;
      line-height: 1.45;
      color: #374151;
      margin: 6px 0;
    }

    ${scope}.duality-export-table-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(235px, 1fr));
      gap: 8px;
      align-items: start;
      margin: 8px 0;
      break-inside: avoid;
      page-break-inside: avoid;
    }

    ${scope}.duality-export-table-wrap {
      width: 100%;
      overflow-x: auto;
      border: 1px solid #e5e7eb;
      border-radius: 4px;
      margin: 8px 0;
      break-inside: avoid;
      page-break-inside: avoid;
    }

    ${scope}.duality-export-table-grid .duality-export-table-wrap {
      margin: 0;
    }

    ${scope}.duality-export-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 9px;
      line-height: 1.18;
      background: #ffffff;
    }

    ${scope}.duality-export-table th {
      border: 1px solid #e5e7eb;
      background: #F9F9F9;
      padding: 3px 4px;
      text-align: left;
      vertical-align: top;
      font-weight: 700;
      color: #111827;
    }

    ${scope}.duality-export-table .duality-export-empty-header-cell {
      border: 1px solid #e5e7eb;
      background: #ffffff;
      padding: 3px 4px;
    }

    ${scope}.duality-export-table td {
      border: 1px solid #e5e7eb;
      padding: 3px 4px;
      text-align: left;
      vertical-align: top;
      color: #1f2937;
      word-break: break-word;
    }

    ${scope}.duality-export-key-values {
      margin: 8px 0;
    }

    ${scope}.duality-export-key-values th {
      width: 38%;
    }

    ${scope}.duality-export-figure {
      margin: 12px 0;
      text-align: left;
      break-inside: avoid;
      page-break-inside: avoid;
    }

    ${scope}.duality-export-figure img {
      display: block;
      max-width: 100%;
      break-inside: avoid;
      page-break-inside: avoid;
      max-height: 520px;
      border: 1px solid #e5e7eb;
      border-radius: 4px;
      object-fit: contain;
      background: #ffffff;
    }

    ${scope}.duality-export-figure figcaption {
      font-size: 11px;
      color: #64748b;
      margin-top: 5px;
    }

    ${scope}.duality-export-html-block {
      font-size: 13px;
      line-height: 1.45;
      color: #374151;
      margin: 6px 0;
    }

    ${scope}.duality-export-page-break {
      border-top: 1px dashed #cbd5e1;
      margin: 12px 0;
      color: #64748b;
      font-size: 11px;
      padding-top: 6px;
      page-break-before: always;
      break-before: page;
    }

    ${scope}.duality-export-empty {
      color: #64748b;
      font-size: 13px;
      line-height: 1.45;
      margin: 6px 0;
    }

    @media print {
      ${scope}.duality-export-document {
        background: #ffffff;
        padding: 0;
      }

      ${scope}.duality-export-section {
        break-inside: avoid;
      }
    }
  `;
}

export function renderExportDocumentBodyHtml(document: ExportDocument, includeHeader = true): string {
  return `
    <div class="duality-export-document">
      ${
        includeHeader
          ? `<header class="duality-export-header">
              <h1 class="duality-export-title">${escapeHtml(document.title)}</h1>
              <p class="duality-export-generated">Generated ${escapeHtml(document.generatedAt)}</p>
            </header>`
          : ""
      }
      ${document.sections.map(renderSection).join("\n")}
    </div>`;
}

export function renderExportDocumentHtml(document: ExportDocument): string {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(document.title)}</title>
  <style>
    body {
      margin: 0;
      background: #F9F9F9;
    }

    .duality-export-page {
      max-width: 1040px;
      margin: 0 auto;
      padding: 24px;
    }

    ${getExportDocumentCss(".duality-export-page")}
  </style>
</head>
<body>
  <main class="duality-export-page">
    ${renderExportDocumentBodyHtml(document, true)}
  </main>
</body>
</html>`;
}

export function mountExportDocumentForCapture(document: ExportDocument): HTMLDivElement {
  const wrapper = window.document.createElement("div");
  wrapper.style.position = "fixed";
  wrapper.style.left = "-100000px";
  wrapper.style.top = "0";
  wrapper.style.width = "960px";
  wrapper.style.background = "#F9F9F9";
  wrapper.style.zIndex = "-1";

  const style = window.document.createElement("style");
  style.textContent = getExportDocumentCss(".duality-export-capture-root");

  const root = window.document.createElement("div");
  root.className = "duality-export-capture-root";
  root.innerHTML = renderExportDocumentBodyHtml(document, true);

  wrapper.appendChild(style);
  wrapper.appendChild(root);
  window.document.body.appendChild(wrapper);
  return wrapper;
}
