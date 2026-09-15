import React from "react";
import { AnimateIn } from "./AnimateIn";

type HelpToggleProps = {
  open: boolean;
  onToggle: () => void;
  ariaLabel: string;
  title?: string;
};

export function HelpToggle({ open, onToggle, ariaLabel, title }: HelpToggleProps) {
  return (
    <button
      type="button"
      className="help-qmark"
      aria-label={ariaLabel}
      title={title ?? ariaLabel}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
    >
      ?
    </button>
  );
}

type HelpPanelProps = {
  open: boolean;
  text?: React.ReactNode;
};

export function HelpPanel({ open, text }: HelpPanelProps) {
  if (!open || text === null || text === undefined) return null;

  if (typeof text === "string") {
    const t = text.trim();
    if (!t) return null;
    return (
      <AnimateIn>
        <div className="help-panel" onClick={(e) => e.stopPropagation()}>
          {t}
        </div>
      </AnimateIn>
    );
  }

  return (
    <AnimateIn>
      <div className="help-panel" onClick={(e) => e.stopPropagation()}>
        {text}
      </div>
    </AnimateIn>
  );
}
