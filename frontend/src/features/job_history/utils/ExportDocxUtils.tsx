import {
  AlignmentType,
  BorderStyle,
  Document,
  HeadingLevel,
  ImageRun,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from "docx";
import { ExportBlock, ExportDocument, ExportKeyValue, ExportSection, ExportWorkflow } from "./ExportDocTypes";

function normalizeText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function stripHtml(html: string): string {
  const div = window.document.createElement("div");
  div.innerHTML = html || "";
  return normalizeText(div.textContent || div.innerText || "");
}

function dataUrlToBytes(dataUrl: string): Uint8Array {
  const base64 = dataUrl.split(",")[1] || "";
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}

function getImageType(dataUrl: string): "png" | "jpg" | "gif" | "bmp" {
  if (dataUrl.startsWith("data:image/jpeg") || dataUrl.startsWith("data:image/jpg")) return "jpg";
  if (dataUrl.startsWith("data:image/gif")) return "gif";
  if (dataUrl.startsWith("data:image/bmp")) return "bmp";
  return "png";
}

function cell(
  text: unknown,
  options?: {
    bold?: boolean;
    shading?: string;
    width?: number;
    size?: number;
    margin?: number;
  }
): TableCell {
  const margin = options?.margin ?? 80;

  return new TableCell({
    width: options?.width
      ? {
          size: options.width,
          type: WidthType.PERCENTAGE,
        }
      : undefined,
    shading: options?.shading
      ? {
          fill: options.shading,
        }
      : undefined,
    margins: {
      top: margin,
      bottom: margin,
      left: margin,
      right: margin,
    },
    children: [
      new Paragraph({
        children: [
          new TextRun({
            text: normalizeText(text),
            bold: options?.bold,
            size: options?.size ?? 16,
          }),
        ],
      }),
    ],
  });
}

function table(
  columns: string[],
  rows: (string | number)[][],
  options?: {
    fontSize?: number;
    cellMargin?: number;
    widthPercent?: number;
  }
): Table {
  const width = Math.floor(100 / Math.max(columns.length, 1));
  const fontSize = options?.fontSize ?? 16;
  const cellMargin = options?.cellMargin ?? 80;

  return new Table({
    width: {
      size: options?.widthPercent ?? 100,
      type: WidthType.PERCENTAGE,
    },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 1, color: "E5E7EB" },
      bottom: { style: BorderStyle.SINGLE, size: 1, color: "E5E7EB" },
      left: { style: BorderStyle.SINGLE, size: 1, color: "E5E7EB" },
      right: { style: BorderStyle.SINGLE, size: 1, color: "E5E7EB" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: "E5E7EB" },
      insideVertical: { style: BorderStyle.SINGLE, size: 1, color: "E5E7EB" },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        cantSplit: true,
        children: columns.map((column) => {
          const headerText = normalizeText(column);
          return cell(headerText, {
            bold: !!headerText,
            shading: headerText ? "F9F9F9" : undefined,
            width,
            size: fontSize,
            margin: cellMargin,
          });
        }),
      }),
      ...rows.map(
        (row) =>
          new TableRow({
            cantSplit: true,
            children: columns.map((_, index) =>
              cell(row[index], {
                width,
                size: fontSize,
                margin: cellMargin,
              })
            ),
          })
      ),
    ],
  });
}

function chunkRows<T>(rows: T[], chunkSize: number): T[][] {
  if (!rows.length || rows.length <= chunkSize) return [rows];

  const chunks: T[][] = [];
  for (let i = 0; i < rows.length; i += chunkSize) {
    chunks.push(rows.slice(i, i + chunkSize));
  }

  return chunks;
}

function shouldUseCompactTableGrid(columns: string[], rows: (string | number)[][]): boolean {
  return columns.length <= 3 && rows.length > 16;
}

function emptyGridCell(): TableCell {
  return new TableCell({
    width: {
      size: 50,
      type: WidthType.PERCENTAGE,
    },
    borders: {
      top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    children: [new Paragraph({ children: [new TextRun({ text: "" })] })],
  });
}

function gridCell(childTable: Table): TableCell {
  return new TableCell({
    width: {
      size: 50,
      type: WidthType.PERCENTAGE,
    },
    margins: {
      top: 0,
      bottom: 120,
      left: 0,
      right: 120,
    },
    borders: {
      top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    children: [childTable],
  });
}

function compactTableGrid(columns: string[], rows: (string | number)[][]): Table {
  const chunks = chunkRows(rows, 18);
  const gridRows: TableRow[] = [];

  for (let i = 0; i < chunks.length; i += 2) {
    const leftTable = table(columns, chunks[i], {
      fontSize: 13,
      cellMargin: 45,
      widthPercent: 100,
    });
    const rightChunk = chunks[i + 1];
    const rightTable = rightChunk
      ? table(columns, rightChunk, {
          fontSize: 13,
          cellMargin: 45,
          widthPercent: 100,
        })
      : null;

    gridRows.push(
      new TableRow({
        cantSplit: true,
        children: [gridCell(leftTable), rightTable ? gridCell(rightTable) : emptyGridCell()],
      })
    );
  }

  return new Table({
    width: {
      size: 100,
      type: WidthType.PERCENTAGE,
    },
    borders: {
      top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: gridRows,
  });
}

function tableChildren(columns: string[], rows: (string | number)[][]): Array<Paragraph | Table> {
  if (shouldUseCompactTableGrid(columns, rows)) {
    return [compactTableGrid(columns, rows), spacer()];
  }

  return [table(columns, rows), spacer()];
}

function keyValues(items: ExportKeyValue[]): Table {
  return table(
    ["Field", "Value"],
    items.map((item) => [item.label, item.value])
  );
}

function spacer(): Paragraph {
  return new Paragraph({
    children: [new TextRun({ text: "" })],
    spacing: {
      after: 120,
    },
  });
}

function imageParagraph(block: Extract<ExportBlock, { kind: "image" }>): Paragraph[] {
  if (!block.dataUrl) return [];

  const width = block.width ? Math.min(block.width, 560) : 560;
  const height = block.height ? Math.min(block.height, 360) : 315;
  const paragraphs: Paragraph[] = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      keepLines: true,
      keepNext: !!block.caption,
      children: [
        new ImageRun({
          data: dataUrlToBytes(block.dataUrl),
          type: getImageType(block.dataUrl),
          transformation: {
            width,
            height,
          },
        } as any),
      ],
    }),
  ];

  if (block.caption) {
    paragraphs.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [
          new TextRun({
            text: block.caption,
            color: "64748B",
            size: 18,
          }),
        ],
        spacing: {
          after: 160,
        },
      })
    );
  }

  return paragraphs;
}

function headingParagraph(text: string, level?: 1 | 2 | 3): Paragraph {
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 3 ? HeadingLevel.HEADING_3 : HeadingLevel.HEADING_2,
    children: [
      new TextRun({
        text: normalizeText(text),
        bold: true,
        color: level === 3 ? "111827" : "3F5FFF",
      }),
    ],
    spacing: {
      before: 120,
      after: 80,
    },
  });
}

function paragraph(text: string, options?: { bold?: boolean; color?: string; size?: number; keepNext?: boolean }): Paragraph {
  return new Paragraph({
    keepNext: options?.keepNext,
    children: [
      new TextRun({
        text: normalizeText(text),
        bold: options?.bold,
        color: options?.color || "374151",
        size: options?.size || 20,
      }),
    ],
    spacing: {
      after: 100,
    },
  });
}

function blockToChildren(block: ExportBlock): Array<Paragraph | Table> {
  if (block.kind === "pageBreak") {
    return [
      new Paragraph({
        pageBreakBefore: true,
        children: [new TextRun({ text: "" })],
      }),
    ];
  }

  if (block.kind === "spacer") {
    return [spacer()];
  }

  if (block.kind === "heading") {
    return [headingParagraph(block.text, block.level)];
  }

  if (block.kind === "paragraph") {
    return [paragraph(block.text)];
  }

  if (block.kind === "keyValues") {
    return [keyValues(block.items || []), spacer()];
  }

  if (block.kind === "table") {
    return tableChildren(block.columns || [], block.rows || []);
  }

  if (block.kind === "image") {
    return imageParagraph(block);
  }

  if (block.kind === "html") {
    return [paragraph(stripHtml(block.html))];
  }

  return [];
}

function workflowToChildren(workflow: ExportWorkflow): Array<Paragraph | Table> {
  const children: Array<Paragraph | Table> = [
    paragraph(`Workflow: ${workflow.title || workflow.id}`, {
      bold: true,
      color: "1F2937",
      size: 21,
      keepNext: true,
    }),
  ];

  if (!workflow.blocks?.length) {
    children.push(paragraph("No workflow content selected.", { color: "64748B" }));
    return children;
  }

  workflow.blocks.forEach((block) => {
    children.push(...blockToChildren(block));
  });

  return children;
}

function sectionToChildren(section: ExportSection): Array<Paragraph | Table> {
  const children: Array<Paragraph | Table> = [
    headingParagraph(section.title, 2),
  ];

  (section.blocks || []).forEach((block) => {
    children.push(...blockToChildren(block));
  });

  (section.workflows || []).forEach((workflow) => {
    children.push(...workflowToChildren(workflow));
  });

  if (!(section.blocks || []).length && !(section.workflows || []).length) {
    children.push(paragraph("No content selected for this section.", { color: "64748B" }));
  }

  return children;
}

export async function downloadDocx(document: ExportDocument, filename: string): Promise<void> {
  const children: Array<Paragraph | Table> = [
    new Paragraph({
      heading: HeadingLevel.TITLE,
      children: [
        new TextRun({
          text: document.title,
          bold: true,
          color: "111827",
        }),
      ],
      spacing: {
        after: 80,
      },
    }),
    new Paragraph({
      children: [
        new TextRun({
          text: `Generated ${document.generatedAt}`,
          color: "64748B",
          size: 20,
        }),
      ],
      spacing: {
        after: 240,
      },
    }),
  ];

  document.sections.forEach((section) => {
    children.push(...sectionToChildren(section));
  });

  if (!document.sections.length) {
    children.push(paragraph("No export content selected."));
  }

  const doc = new Document({
    styles: {
      default: {
        document: {
          run: {
            font: "Arial",
          },
        },
      },
    },
    sections: [
      {
        properties: {
          page: {
            margin: {
              top: 720,
              right: 720,
              bottom: 720,
              left: 720,
            },
          },
        },
        children,
      },
    ],
  });

  const blob = await Packer.toBlob(doc);
  const url = URL.createObjectURL(blob);
  const a = window.document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
