import AbstractModal from "../../../../components/AbstractModal";
import { ExportFormat } from "../../utils/ExportDocTypes";

interface ExportFormatModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectFormat: (format: ExportFormat) => void;
}

const formats: Array<{ format: ExportFormat; title: string; description: string }> = [
  {
    format: "pdf",
    title: "PDF",
    description: "Best for read-only sharing, review, and archiving.",
  },
  {
    format: "docx",
    title: "Word Document",
    description: "Best for editing, annotation, and client-facing drafts.",
  },
  {
    format: "html",
    title: "HTML",
    description: "Best for preserving rich browser-rendered report content.",
  },
  {
    format: "png",
    title: "PNG Image",
    description: "Best for a visual snapshot of the visible results page.",
  },
];

export default function ExportFormatModal({ isOpen, onClose, onSelectFormat }: ExportFormatModalProps) {
  return (
    <AbstractModal
      isOpen={isOpen}
      title="Export As..."
      titleStyle={{ fontSize: "16pt", marginLeft: "1rem", color: "#3F5FFF", fontWeight: 700, width: "100%" }}
      ariaLabel="Export format modal"
      onClose={onClose} width="min(500px, 96vw)">
      <style>
        {`
          .duality-export-format-option {
            transition: background-color 0.15s ease, border-color 0.15s ease;
          }

          .duality-export-format-option:hover {
            background: #f3f4f6 !important;
            border-color: #9ca3af !important;
          }
        `}
      </style>

      <div className="export-format-modal-block-01">
        Choose an export format for the current results. 
      </div>
      <div className="export-format-modal-block-02">
        PDF, Word, and HTML exports let you select specific report sections, workflows, metrics, and tables before generating the file. PNG exports capture the Results Viewer exactly as it appears on screen, so adjust the visible results before exporting an image.
      </div>
      <div
        className="export-format-modal-block-03"
      >
        {formats.map((item) => (
          <button
            key={item.format}
            type="button"
            className="duality-export-format-option export-format-modal-block-04"
            onClick={() => onSelectFormat(item.format)}
            
          >
            <div className="export-format-modal-block-05">{item.title}</div>
            <div className="export-format-modal-block-06">{item.description}</div>
          </button>
        ))}
      </div>
    </AbstractModal>
  );
}
