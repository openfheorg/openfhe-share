import React from "react";
import { createPortal } from "react-dom";

interface AbstractModalProps {
  isOpen: boolean;
  title: React.ReactNode;
  ariaLabel: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
  maxHeight?: string;
  bodyStyle?: React.CSSProperties;
  headerStyle?: React.CSSProperties;
  titleStyle?: React.CSSProperties;
  closeButtonDisabled?: boolean;
  closeOnOverlayClick?: boolean;
}

const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.35)",
  zIndex: 2147483647,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 16,
};

const closeButtonStyle: React.CSSProperties = {
  border: 0,
  background: "transparent",
  color: "#6b7280",
  fontSize: 34,
  lineHeight: 1,
  fontWeight: 400,
  cursor: "pointer",
  padding: "0 0.25rem",
  width: "36px",
  height: "36px",
};

export default function AbstractModal({
  isOpen,
  title,
  ariaLabel,
  onClose,
  children,
  footer,
  width = "min(720px, 96vw)",
  maxHeight = "90vh",
  bodyStyle,
  headerStyle,
  titleStyle,
  closeButtonDisabled,
  closeOnOverlayClick = true,
}: AbstractModalProps) {
  if (!isOpen) return null;

  const modalStyle: React.CSSProperties = {
    width,
    background: "#fff",
    color: "#111827",
    maxHeight,
    borderRadius: 8,
    border: "1px solid #ccc",
    boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  };

  const defaultHeaderStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 12px",
    borderBottom: "1px solid #ddd",
    background: "#F9F9F9",
    ...headerStyle,
  };

  const defaultTitleStyle: React.CSSProperties = {
    fontWeight: 700,
    width: "100%",
    ...titleStyle,
  };

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
      onClick={closeOnOverlayClick ? onClose : undefined}
      style={overlayStyle}
    >
      <div onClick={(e) => e.stopPropagation()} style={modalStyle}>
        <div style={defaultHeaderStyle}>
          <div style={defaultTitleStyle}>{title}</div>
          <button type="button" onClick={onClose} disabled={closeButtonDisabled} aria-label="Close" title="Close" style={closeButtonStyle}>
            ×
          </button>
        </div>
        <div className="abstract-modal-block-01" style={{ ...bodyStyle }}>{children}</div>
        {footer && <div>{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
