import React from "react";
import { FilterCollection } from "../features/job_runner/utils/FilterPayloadConfigUtils";
import AbstractAccordion from "./AbstractAccordion";

interface FilterSummaryProps {
    submittedFilterSet: FilterCollection;
    submittedFilterSetName?: string;
    boldBorder?: boolean;
    defaultOpen?: boolean;
    isOpen?: boolean;
    onToggle?: () => void;
}

function prettifyKey(key: string): string {
    return key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (str) =>
        str.toUpperCase()
    );
}

function formatValue(value: any): string {
    if (Array.isArray(value)) {
        const primitives = value.filter(
            (v) => v === null || (typeof v !== "object" && typeof v !== "function")
        );
        if (primitives.length === value.length) {
            return primitives.map((v) => (v ?? "").toString()).join(" - ");
        }
        return "";
    }
    return value?.toString?.() ?? "";
}

function hasRenderableValue(value: any): boolean {
    if (value === null || value === undefined) return false;

    if (typeof value === "string") {
        return value.trim() !== "";
    }

    if (typeof value === "number") {
        return Number.isFinite(value);
    }

    if (typeof value === "boolean") {
        return true;
    }

    if (Array.isArray(value)) {
        if (value.length === 0) return false;
        return value.some((item) => hasRenderableValue(item));
    }

    if (typeof value === "object") {
        const entries = Object.entries(value);
        if (entries.length === 0) return false;
        return entries.some(([, v]) => hasRenderableValue(v));
    }

    return false;
}

const sectionTitleStyle: React.CSSProperties = {
    fontWeight: 600,
    marginBottom: "0.15rem",
    borderBottom: "1px solid #ccc",
};

const labelStyle: React.CSSProperties = {
    color: "#4b5563",
};

const valueStyle: React.CSSProperties = {
    fontWeight: 600,
    color: "#111827",
};

const FilterSummary: React.FC<FilterSummaryProps> = ({
    submittedFilterSet,
    submittedFilterSetName,
    boldBorder = false,
    defaultOpen = true,
    isOpen,
    onToggle
}) => {
    if (!submittedFilterSet) {
        return <></>;
    }

    const hasFilterDetails = Object.values(submittedFilterSet).some((value) => {
        let parsedValue: any;
        try {
            parsedValue = typeof value === "string" ? JSON.parse(value) : value;
        } catch {
            parsedValue = value;
        }
        return hasRenderableValue(parsedValue);
    });

    const bodyClassName = [
        "filter-summary-body",
        submittedFilterSetName && !hasFilterDetails ? "filter-summary-body-name-only" : "",
    ]
        .filter(Boolean)
        .join(" ");

    return (
        <AbstractAccordion
            as="section"
            title="Filters Overview"
            titleTooltip="Show/Hide Filters Overview"
            defaultOpen={defaultOpen}
            isOpen={isOpen}
            onToggle={onToggle}
            containerStyle={{ maxWidth: "100%" }}
            bodyClassName={bodyClassName}
            bodyStyle={{
                fontSize: submittedFilterSetName ? "13px" : "12px",
                border: boldBorder ? "1px solid black" : "1px solid #ccc",
                borderRadius: boldBorder ? "0" : "4px",
                backgroundColor: "white",
                maxWidth: "100%",
            }}
        >
            <>
                {submittedFilterSetName && (
                    <div
                        className="filter-summary-block-01"
                    >
                        <span className="duality-font-semibold">Name: </span>
                        <span>{submittedFilterSetName}</span>
                    </div>
                )}

                <div
                    className="filter-summary-block-02"
                >
                    {Object.entries(submittedFilterSet).map(([sectionKey, value]) => {
                        let parsedValue: any;
                        try {
                            parsedValue = typeof value === "string" ? JSON.parse(value) : value;
                        } catch {
                            parsedValue = value;
                        }

                        if (!hasRenderableValue(parsedValue)) {
                            return null;
                        }

                        const sectionTitle =
                            prettifyKey(sectionKey.replace("Filters", "").trim()) + " Filters";

                        const renderPrimitiveBlock = (label: string, v: any) => (
                            <div
                                key={label}
                                className="duality-flex-column-min-0"
                            >
                                <div style={labelStyle}>{label}</div>
                                <div style={valueStyle}>{formatValue(v)}</div>
                            </div>
                        );

                        return (
                            <div
                                key={sectionKey}
                                className="filter-summary-block-03"
                            >
                                <div style={sectionTitleStyle}>{sectionTitle}</div>
                                <div
                                    className="duality-d-grid-grid-cols-repeat-auto-fit-mi-gap-0p3rem-0p65rem"
                                >
                                    {Array.isArray(parsedValue) ? (
                                        parsedValue
                                            .map((item, idx) => {
                                                if (!hasRenderableValue(item)) {
                                                    return null;
                                                }

                                                if (
                                                    item &&
                                                    typeof item === "object" &&
                                                    !Array.isArray(item)
                                                ) {
                                                    const entries = Object.entries(item).filter(
                                                        ([, v]) => hasRenderableValue(v)
                                                    );
                                                    if (!entries.length) {
                                                        return null;
                                                    }
                                                    return (
                                                        <div
                                                            key={`${sectionKey}-item-${idx}`}
                                                            className="filter-summary-block-04"
                                                        >
                                                            <div
                                                                className="filter-summary-block-05"
                                                            >
                                                                Condition {idx + 1}
                                                            </div>
                                                            <div
                                                                className="filter-summary-block-06"
                                                            >
                                                                {entries.map(([k, v]) =>
                                                                    renderPrimitiveBlock(
                                                                        prettifyKey(k),
                                                                        v
                                                                    )
                                                                )}
                                                            </div>
                                                        </div>
                                                    );
                                                }

                                                return renderPrimitiveBlock(
                                                    `Value ${idx + 1}`,
                                                    item
                                                );
                                            })
                                            .filter(Boolean)
                                    ) : parsedValue &&
                                        typeof parsedValue === "object" &&
                                        !Array.isArray(parsedValue) ? (
                                        Object.entries(parsedValue)
                                            .filter(([, v]) => hasRenderableValue(v))
                                            .map(([k, v]) => renderPrimitiveBlock(prettifyKey(k), v))
                                    ) : (
                                        renderPrimitiveBlock("Value", parsedValue)
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </>
        </AbstractAccordion>
    );
};

export default FilterSummary;
