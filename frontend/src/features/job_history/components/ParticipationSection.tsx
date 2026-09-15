import React from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { NVFlareJob } from "../../../types/JobsDataTypes";

interface ParticipationSectionProps {
    job: NVFlareJob;
    jobKey: string;
    isOpen: boolean;
    onToggle: () => void;
}

function parseCsvList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value
            .map((item) => String(item || "").trim())
            .filter(Boolean);
    }

    if (typeof value !== "string") return [];

    return value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
}

function PartyList({ label, values }: { label: string; values: string[] }) {
    if (values.length === 0) return null;
    return (
        <div
            className="participation-section-block-01"
        >
            <div>{label}:</div>
            <div className="participation-section-block-02">
                {values.map((value) => (
                    <span
                        key={`${label}-${value}`}
                        className="participation-section-block-03"
                    >
                        {value}
                    </span>
                ))}
            </div>
        </div>
    );
}

export default function ParticipationSection({
    job,
    jobKey,
    isOpen,
    onToggle
}: ParticipationSectionProps) {
    const nonContributingClients = parseCsvList((job as any).non_contributing_clients);
    const excludeAnalyzingClients = parseCsvList((job as any).exclude_analyzing_clients);

    if (nonContributingClients.length === 0 && excludeAnalyzingClients.length === 0) {
        return null;
    }

    return (
        <AbstractAccordion
            key={`${jobKey}-participation`}
            title="Participation Settings"
            titleTooltip="Show/Hide Participation Settings"
            isOpen={isOpen}
            onToggle={onToggle}
            stopPropagation={true}
            containerStyle={{ padding: "0" }}
            bodyStyle={{
                border: "1px solid black",
                marginTop: "5px",
                padding: "0.75rem 1rem",
                fontSize: 12
            }}
        >
            <div className="participation-section-block-04">
                <PartyList label="Excluded from Contributing" values={nonContributingClients} />
                <PartyList label="Excluded from Analyzing" values={excludeAnalyzingClients} />
            </div>
        </AbstractAccordion>
    );
}
