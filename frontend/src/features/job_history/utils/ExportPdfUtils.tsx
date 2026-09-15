import jsPDF from "jspdf";
import { ExportBlock, ExportDocument, ExportSection } from "./ExportDocTypes";

type RenderOptions = {
  filename: string;
};

type PdfCursor = {
  y: number;
};

const PAGE_MARGIN = 36;
const PAGE_WIDTH = 612;
const PAGE_HEIGHT = 792;
const CONTENT_WIDTH = PAGE_WIDTH - PAGE_MARGIN * 2;
const SECTION_PADDING = 10;

// jsPDF's built-in Helvetica only supports WinAnsi (Latin-1). Any character
// outside it (subscripts like ₁₀, Greek like β, ∞, …) renders as mojibake and
// drags the whole string into jsPDF's broken 2-byte mode (the "& between every
// character" garbling). Transliterate scientific Unicode to ASCII, then drop any
// remaining non-Latin-1 so a stray glyph can never garble the export again.
const PDF_CHAR_MAP: Record<string, string> = {
  // subscripts ₀–₉ and ₊₋₌₍₎
  "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
  "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
  "₊": "+", "₋": "-", "₌": "=", "₍": "(", "₎": ")",
  // superscripts ⁰–⁹ (incl. Latin-1 ¹²³) and ⁺⁻⁼⁽⁾ⁿ
  "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
  "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
  "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")", "ⁿ": "n",
  // Greek lowercase used in stat labels (β₁, χ², μ, σ, τ, ε, …)
  "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
  "ε": "epsilon", "ϵ": "epsilon", "ζ": "zeta", "η": "eta",
  "θ": "theta", "ϑ": "theta", "ι": "iota", "κ": "kappa",
  "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "o",
  "π": "pi", "ρ": "rho", "σ": "sigma", "ς": "sigma",
  "τ": "tau", "υ": "upsilon", "φ": "phi", "χ": "chi",
  "ψ": "psi", "ω": "omega",
  // Greek uppercase
  "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda",
  "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma", "Φ": "Phi",
  "Ψ": "Psi", "Ω": "Omega",
  // math / misc symbols (incl. n-ary, set, logic operators)
  "∞": "inf", "−": "-", "≤": "<=", "≥": ">=", "≠": "!=",
  "≈": "~", "≡": "==", "±": "+/-", "∓": "-/+", "×": "x",
  "÷": "/", "√": "sqrt", "∑": "sum", "∏": "prod",
  "∫": "integral", "∂": "d", "∇": "grad", "∝": "prop",
  "∈": "in", "∉": "not in", "∋": "contains", "∀": "for all",
  "∃": "exists", "∅": "empty", "∙": ".", "∘": "o", "∥": "||",
  "…": "...", "–": "-", "—": "-", "→": "->", "←": "<-",
  "⇒": "=>", "⇐": "<=", "⇔": "<=>", "↔": "<->",
};

function toPdfSafe(input: string): string {
  return input
    // transliterate known scientific Unicode; drop anything else in those ranges
    .replace(/[⁰-₟Ͱ-Ͽ←-⇿∀-⋿±²³¹×÷–—…]/g, (c) => PDF_CHAR_MAP[c] ?? "")
    // catch-all: keep tab/newlines, printable ASCII, and Latin-1 (é, ñ, …); drop the rest
    .replace(/[^\t\n\r\x20-\x7E -ÿ]/g, "");
}

function normalizeText(value: unknown): string {
  return toPdfSafe(String(value ?? "")).replace(/\s+/g, " ").trim();
}

function stripHtml(html: string): string {
  const div = window.document.createElement("div");
  div.innerHTML = html || "";
  return normalizeText(div.textContent || div.innerText || "");
}

function dataUrlImageType(dataUrl: string): "PNG" | "JPEG" {
  return dataUrl.startsWith("data:image/jpeg") || dataUrl.startsWith("data:image/jpg") ? "JPEG" : "PNG";
}

function ensureSpace(pdf: jsPDF, cursor: PdfCursor, height: number): void {
  if (cursor.y + height <= PAGE_HEIGHT - PAGE_MARGIN) {
    return;
  }

  pdf.addPage();
  cursor.y = PAGE_MARGIN;
}

function addWrappedText(
  pdf: jsPDF,
  cursor: PdfCursor,
  text: string,
  x: number,
  maxWidth: number,
  fontSize: number,
  options?: {
    fontStyle?: "normal" | "bold";
    color?: [number, number, number];
    lineHeight?: number;
    after?: number;
  }
): void {
  const cleaned = normalizeText(text);
  if (!cleaned) return;

  const lineHeight = options?.lineHeight ?? fontSize * 1.25;
  pdf.setFont("helvetica", options?.fontStyle || "normal");
  pdf.setFontSize(fontSize);
  if (options?.color) {
    pdf.setTextColor(...options.color);
  } else {
    pdf.setTextColor(17, 24, 39);
  }

  const lines = pdf.splitTextToSize(cleaned, maxWidth);
  ensureSpace(pdf, cursor, lines.length * lineHeight + (options?.after ?? 0));
  pdf.text(lines, x, cursor.y);
  cursor.y += lines.length * lineHeight + (options?.after ?? 0);
}

function addHeader(pdf: jsPDF, document: ExportDocument, cursor: PdfCursor): void {
  pdf.setDrawColor(219, 227, 239);
  pdf.setFillColor(255, 255, 255);
  // pdf.roundedRect(PAGE_MARGIN, cursor.y, CONTENT_WIDTH, 54, 6, 6, "FD");

  cursor.y += 20;
  addWrappedText(pdf, cursor, document.title, PAGE_MARGIN + 14, CONTENT_WIDTH - 28, 18, {
    fontStyle: "bold",
    lineHeight: 18,
    after: 2,
  });
  addWrappedText(pdf, cursor, `Generated ${document.generatedAt}`, PAGE_MARGIN + 14, CONTENT_WIDTH - 28, 10, {
    color: [100, 116, 139],
    lineHeight: 11,
  });
  cursor.y = PAGE_MARGIN + 68;
}

function getSpacerHeight(block: Extract<ExportBlock, { kind: "spacer" }>): number {
  if (typeof block.mm === "number") return Math.max(1, block.mm * 2.835);
  if (block.size === "lg") return 18;
  if (block.size === "sm") return 6;
  return 10;
}

function estimateTextHeight(pdf: jsPDF, text: string, maxWidth: number, fontSize: number, lineHeight: number): number {
  const lines = pdf.splitTextToSize(normalizeText(text), maxWidth);
  return Math.max(lineHeight, lines.length * lineHeight);
}

function drawTable(
  pdf: jsPDF,
  cursor: PdfCursor,
  columns: string[],
  rows: (string | number)[][],
  options?: {
    x?: number;
    width?: number;
    fontSize?: number;
    compact?: boolean;
  }
): void {
  if (!columns.length || !rows.length) return;

  const x = options?.x ?? PAGE_MARGIN + SECTION_PADDING;
  const width = options?.width ?? CONTENT_WIDTH - SECTION_PADDING * 2;
  const fontSize = options?.fontSize ?? 8;
  const cellPadding = options?.compact ? 3 : 5;
  const lineHeight = fontSize * 1.25;
  const columnWidth = width / columns.length;

  const drawHeader = () => {
    const headerHeight = Math.max(
      16,
      ...columns.map((column) => estimateTextHeight(pdf, column, columnWidth - cellPadding * 2, fontSize, lineHeight) + cellPadding * 2)
    );

    ensureSpace(pdf, cursor, headerHeight);
    pdf.setFillColor(249, 249, 249);
    pdf.setDrawColor(229, 231, 235);

    columns.forEach((column, columnIndex) => {
      const cellX = x + columnIndex * columnWidth;
      const headerText = normalizeText(column);

      pdf.setDrawColor(229, 231, 235);
      if (headerText) {
        pdf.setFillColor(249, 249, 249);
        pdf.rect(cellX, cursor.y, columnWidth, headerHeight, "FD");
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(fontSize);
        pdf.setTextColor(17, 24, 39);
        const lines = pdf.splitTextToSize(headerText, columnWidth - cellPadding * 2);
        pdf.text(lines, cellX + cellPadding, cursor.y + cellPadding + fontSize);
      } else {
        pdf.setFillColor(255, 255, 255);
        pdf.rect(cellX, cursor.y, columnWidth, headerHeight, "FD");
      }
    });

    cursor.y += headerHeight;
  };

  drawHeader();

  rows.forEach((row) => {
    const rowTexts = columns.map((_, columnIndex) => normalizeText(row[columnIndex]));
    const rowHeight = Math.max(
      15,
      ...rowTexts.map((cell) => estimateTextHeight(pdf, cell, columnWidth - cellPadding * 2, fontSize, lineHeight) + cellPadding * 2)
    );

    if (cursor.y + rowHeight > PAGE_HEIGHT - PAGE_MARGIN) {
      pdf.addPage();
      cursor.y = PAGE_MARGIN;
      drawHeader();
    }

    pdf.setFillColor(255, 255, 255);
    pdf.setDrawColor(229, 231, 235);

    rowTexts.forEach((cell, columnIndex) => {
      const cellX = x + columnIndex * columnWidth;
      pdf.rect(cellX, cursor.y, columnWidth, rowHeight, "S");
      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(fontSize);
      pdf.setTextColor(31, 41, 55);
      const lines = pdf.splitTextToSize(cell, columnWidth - cellPadding * 2);
      pdf.text(lines, cellX + cellPadding, cursor.y + cellPadding + fontSize);
    });

    cursor.y += rowHeight;
  });

  cursor.y += 8;
}

function estimateTableHeight(
  pdf: jsPDF,
  columns: string[],
  rows: (string | number)[][],
  width: number,
  fontSize: number,
  compact: boolean
): number {
  if (!columns.length || !rows.length) return 0;

  const cellPadding = compact ? 3 : 5;
  const lineHeight = fontSize * 1.25;
  const columnWidth = width / columns.length;
  const headerHeight = Math.max(
    16,
    ...columns.map((column) => estimateTextHeight(pdf, column, columnWidth - cellPadding * 2, fontSize, lineHeight) + cellPadding * 2)
  );

  const bodyHeight = rows.reduce((total, row) => {
    const rowTexts = columns.map((_, columnIndex) => normalizeText(row[columnIndex]));
    const rowHeight = Math.max(
      15,
      ...rowTexts.map((cell) => estimateTextHeight(pdf, cell, columnWidth - cellPadding * 2, fontSize, lineHeight) + cellPadding * 2)
    );

    return total + rowHeight;
  }, 0);

  return headerHeight + bodyHeight + 8;
}

function drawTableAt(
  pdf: jsPDF,
  columns: string[],
  rows: (string | number)[][],
  x: number,
  y: number,
  width: number,
  fontSize: number,
  compact: boolean
): number {
  if (!columns.length || !rows.length) return y;

  const cellPadding = compact ? 3 : 5;
  const lineHeight = fontSize * 1.25;
  const columnWidth = width / columns.length;
  let currentY = y;

  const headerHeight = Math.max(
    16,
    ...columns.map((column) => estimateTextHeight(pdf, column, columnWidth - cellPadding * 2, fontSize, lineHeight) + cellPadding * 2)
  );

  columns.forEach((column, columnIndex) => {
    const cellX = x + columnIndex * columnWidth;
    const headerText = normalizeText(column);

    pdf.setDrawColor(229, 231, 235);
    if (headerText) {
      pdf.setFillColor(249, 249, 249);
      pdf.rect(cellX, currentY, columnWidth, headerHeight, "FD");
      pdf.setFont("helvetica", "bold");
      pdf.setFontSize(fontSize);
      pdf.setTextColor(17, 24, 39);
      const lines = pdf.splitTextToSize(headerText, columnWidth - cellPadding * 2);
      pdf.text(lines, cellX + cellPadding, currentY + cellPadding + fontSize);
    } else {
      pdf.setFillColor(255, 255, 255);
      pdf.rect(cellX, currentY, columnWidth, headerHeight, "FD");
    }
  });

  currentY += headerHeight;

  rows.forEach((row) => {
    const rowTexts = columns.map((_, columnIndex) => normalizeText(row[columnIndex]));
    const rowHeight = Math.max(
      15,
      ...rowTexts.map((cell) => estimateTextHeight(pdf, cell, columnWidth - cellPadding * 2, fontSize, lineHeight) + cellPadding * 2)
    );

    pdf.setFillColor(255, 255, 255);
    pdf.setDrawColor(229, 231, 235);

    rowTexts.forEach((cell, columnIndex) => {
      const cellX = x + columnIndex * columnWidth;
      pdf.rect(cellX, currentY, columnWidth, rowHeight, "S");
      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(fontSize);
      pdf.setTextColor(31, 41, 55);
      const lines = pdf.splitTextToSize(cell, columnWidth - cellPadding * 2);
      pdf.text(lines, cellX + cellPadding, currentY + cellPadding + fontSize);
    });

    currentY += rowHeight;
  });

  return currentY + 8;
}

function chunkRows<T>(rows: T[], chunkSize: number): T[][] {
  if (!rows.length || rows.length <= chunkSize) return [rows];

  const chunks: T[][] = [];
  for (let i = 0; i < rows.length; i += chunkSize) {
    chunks.push(rows.slice(i, i + chunkSize));
  }
  return chunks;
}

function drawTableBlock(pdf: jsPDF, cursor: PdfCursor, block: Extract<ExportBlock, { kind: "table" }>): void {
  const columns = block.columns || [];
  const rows = block.rows || [];
  if (!columns.length || !rows.length) return;

  const useGrid = columns.length <= 3 && rows.length > 16;
  if (!useGrid) {
    drawTable(pdf, cursor, columns, rows);
    return;
  }

  const chunks = chunkRows(rows, 18);
  const gap = 8;
  const tableWidth = (CONTENT_WIDTH - SECTION_PADDING * 2 - gap) / 2;
  const leftX = PAGE_MARGIN + SECTION_PADDING;
  const rightX = PAGE_MARGIN + SECTION_PADDING + tableWidth + gap;
  const fontSize = 7;
  const compact = true;

  for (let i = 0; i < chunks.length; i += 2) {
    const leftChunk = chunks[i];
    const rightChunk = chunks[i + 1];
    const requiredHeight = Math.max(
      estimateTableHeight(pdf, columns, leftChunk, tableWidth, fontSize, compact),
      rightChunk ? estimateTableHeight(pdf, columns, rightChunk, tableWidth, fontSize, compact) : 0
    );

    ensureSpace(pdf, cursor, requiredHeight);

    const startY = cursor.y;
    const leftEndY = drawTableAt(pdf, columns, leftChunk, leftX, startY, tableWidth, fontSize, compact);
    const rightEndY = rightChunk
      ? drawTableAt(pdf, columns, rightChunk, rightX, startY, tableWidth, fontSize, compact)
      : startY;

    cursor.y = Math.max(leftEndY, rightEndY);
  }
}

function drawKeyValues(pdf: jsPDF, cursor: PdfCursor, block: Extract<ExportBlock, { kind: "keyValues" }>): void {
  const rows = (block.items || []).map((item) => [item.label, item.value]);
  drawTable(pdf, cursor, ["Field", "Value"], rows, {
    fontSize: 8,
  });
}

function addImageBlock(pdf: jsPDF, cursor: PdfCursor, block: Extract<ExportBlock, { kind: "image" }>): void {
  if (!block.dataUrl) return;

  const imageType = dataUrlImageType(block.dataUrl);
  const imageProps = pdf.getImageProperties(block.dataUrl);
  const maxWidth = CONTENT_WIDTH - SECTION_PADDING * 2;
  const maxHeight = 330;
  const widthScale = maxWidth / imageProps.width;
  const heightScale = maxHeight / imageProps.height;
  const scale = Math.min(widthScale, heightScale, 1);
  const imageWidth = imageProps.width * scale;
  const imageHeight = imageProps.height * scale;
  const totalHeight = imageHeight + (block.caption ? 18 : 0) + 10;

  ensureSpace(pdf, cursor, totalHeight);
  pdf.addImage(block.dataUrl, imageType, PAGE_MARGIN + SECTION_PADDING, cursor.y, imageWidth, imageHeight, undefined, "FAST");
  cursor.y += imageHeight + 6;

  if (block.caption) {
    addWrappedText(pdf, cursor, block.caption, PAGE_MARGIN + SECTION_PADDING, maxWidth, 8, {
      color: [100, 116, 139],
      lineHeight: 10,
      after: 6,
    });
  } else {
    cursor.y += 8;
  }
}

function drawBlock(pdf: jsPDF, cursor: PdfCursor, block: ExportBlock): void {
  if (block.kind === "pageBreak") {
    pdf.addPage();
    cursor.y = PAGE_MARGIN;
    return;
  }

  if (block.kind === "spacer") {
    cursor.y += getSpacerHeight(block);
    return;
  }

  if (block.kind === "heading") {
    cursor.y += 10;

    const fontSize = block.level === 1 ? 16 : block.level === 3 ? 12 : 14;
    addWrappedText(pdf, cursor, block.text, PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, fontSize, {
      fontStyle: "bold",
      lineHeight: fontSize * 1.25,
      after: 0,
    });
    return;
  }

  if (block.kind === "paragraph") {
    cursor.y += 10;
    
    addWrappedText(pdf, cursor, block.text, PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, 10, {
      color: [55, 65, 81],
      lineHeight: 13,
      after: 2,
    });
    return;
  }

  if (block.kind === "keyValues") {
    drawKeyValues(pdf, cursor, block);
    return;
  }

  if (block.kind === "table") {
    drawTableBlock(pdf, cursor, block);
    return;
  }

  if (block.kind === "image") {
    addImageBlock(pdf, cursor, block);
    return;
  }

  if (block.kind === "html") {
    addWrappedText(pdf, cursor, stripHtml(block.html), PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, 10, {
      color: [55, 65, 81],
      lineHeight: 13,
      after: 4,
    });
  }
}

function drawWorkflow(pdf: jsPDF, cursor: PdfCursor, workflowTitle: string, blocks: ExportBlock[]): void {
  ensureSpace(pdf, cursor, 38);
  pdf.setDrawColor(229, 231, 235);
  pdf.line(PAGE_MARGIN + SECTION_PADDING, cursor.y, PAGE_WIDTH - PAGE_MARGIN - SECTION_PADDING, cursor.y);
  cursor.y += 15;

  addWrappedText(pdf, cursor, `Workflow: ${workflowTitle}`, PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, 11, {
    fontStyle: "bold",
    color: [31, 41, 55],
    lineHeight: 13,
    after: 3,
  });

  if (!blocks.length) {
    addWrappedText(pdf, cursor, "No workflow content selected.", PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, 10, {
      color: [100, 116, 139],
      lineHeight: 13,
      after: 4,
    });
    return;
  }

  blocks.forEach((block) => drawBlock(pdf, cursor, block));
}

function drawSection(pdf: jsPDF, cursor: PdfCursor, section: ExportSection): void {
  ensureSpace(pdf, cursor, 44);

  cursor.y += 10;

  addWrappedText(pdf, cursor, section.title, PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, 14, {
    fontStyle: "bold",
    color: [63, 95, 255],
    lineHeight: 16,
    after: 3,
  });

  (section.blocks || []).forEach((block) => drawBlock(pdf, cursor, block));
  (section.workflows || []).forEach((workflow) => {
    drawWorkflow(pdf, cursor, workflow.title || workflow.id, workflow.blocks || []);
  });

  if (!(section.blocks || []).length && !(section.workflows || []).length) {
    addWrappedText(pdf, cursor, "No content selected for this section.", PAGE_MARGIN + SECTION_PADDING, CONTENT_WIDTH - SECTION_PADDING * 2, 10, {
      color: [100, 116, 139],
      lineHeight: 13,
      after: 4,
    });
  }

  pdf.setDrawColor(219, 227, 239);
  cursor.y += 14;
}

export async function renderPdf(sections: ExportSection[], options: RenderOptions): Promise<void> {
  const document: ExportDocument = {
    title: "SHARE Job Results Export",
    generatedAt: new Date().toLocaleString(),
    sections,
  };
  await downloadPdf(document, options.filename);
}

export async function downloadPdf(document: ExportDocument, filename: string): Promise<void> {
  const pdf = new jsPDF({ orientation: "p", unit: "pt", format: "letter" });
  const cursor: PdfCursor = { y: PAGE_MARGIN };

  addHeader(pdf, document, cursor);
  document.sections.forEach((section) => drawSection(pdf, cursor, section));

  pdf.save(filename);
}
