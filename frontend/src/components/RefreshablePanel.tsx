// src/components/RefreshablePanel.tsx
import React from "react";
import AbstractAccordion from "./AbstractAccordion";

interface RefreshablePanelProps {
  header?: string;
  loading?: boolean;
  loadingStatus?: string;
  onRefresh?: () => void;
  refreshAriaLabel?: string;
  refreshTitle?: string;
  right?: React.ReactNode;
  note?: React.ReactNode;
  accordion?: boolean;
  accordionDefaultExpanded?: boolean;
  children: React.ReactNode;
}

const RefreshablePanel: React.FC<RefreshablePanelProps> = ({
  header = "",
  loading = false,
  loadingStatus = "Loading...",
  onRefresh,
  refreshAriaLabel = "Refresh",
  refreshTitle = "Refresh",
  right,
  note,
  accordion = false,
  accordionDefaultExpanded = true,
  children
}) => {
  const RefreshButton: React.FC = () => (
    <button
      className="secondary-button refreshable-panel-block-01"
      onClick={onRefresh}
      disabled={loading}
      
      aria-label={refreshAriaLabel}
      title={refreshTitle}
    >
      {loading ? "…" : "⟳"}
    </button>
  );

  const body = loading ? (
    <h3 className="refreshable-panel-h3">
      {loadingStatus}
    </h3>
  ) : (
    <>
      {note ? <div className="refreshable-panel-block-02">{note}</div> : null}
      {children}
    </>
  );

  const headerRight = (
    <div className="duality-flex-center-gap-8">
      {right}
      {onRefresh ? <RefreshButton /> : null}
    </div>
  );

  if (accordion) {
    return (
      <div className="child-container-top">
        <AbstractAccordion
          title={<h3 className="refreshable-panel-accordion-title">{header}</h3>}
          defaultOpen={accordionDefaultExpanded}
          headerRight={headerRight}
          containerStyle={{ width: "100%", maxWidth: "100%" }}
          headerClassName="refreshable-panel-accordion-trigger"
          headerRowStyle={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            width: "100%"
          }}
          bodyStyle={{ width: "100%", maxWidth: "100%" }}
        >
          {body}
        </AbstractAccordion>
      </div>
    );
  }

  return (
    <div className="child-container-top">
      <div className="duality-flex-between-center">
        <h3>{header}</h3>
        {headerRight}
      </div>

      {body}
    </div>
  );
};

export default RefreshablePanel;
