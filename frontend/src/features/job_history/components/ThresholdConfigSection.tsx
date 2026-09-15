import React from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { NVFlareJob } from "../../../types/JobsDataTypes";

interface ThresholdConfigSectionProps {
    job: NVFlareJob;
    jobKey: string;
    isOpen: boolean;
    onToggle: () => void;
    formatThresholdMethod: (method: string) => string;
}

export default function ThresholdConfigSection({
    job,
    jobKey,
    isOpen,
    onToggle,
    formatThresholdMethod
}: ThresholdConfigSectionProps) {
    return (
        <AbstractAccordion
            title="Threshold Configuration"
            titleTooltip="Show/Hide Threshold Configuration"
            isOpen={isOpen}
            onToggle={onToggle}
            stopPropagation={true}
            containerStyle={{ padding: "5px 0" }}
            bodyStyle={{
                border: "1px solid black",
                marginTop: "5px",
                padding: "0.75rem 1rem",
                fontSize: 12
            }}
        >
            {job.threshold ? (
                <div
                    className="duality-d-grid-grid-cols-200px-1fr-row-gap-6px"
                >
                    <div>Method:</div>
                    <div className="duality-font-semibold">{formatThresholdMethod(job.threshold.method)}</div>
                    <div>Threshold value:</div>
                    <div className="duality-font-semibold">{job.threshold.threshold}</div>
                </div>
            ) : (
                <div className="duality-text-64748b-fs-12px">
                    No threshold configuration associated with this job.
                </div>
            )}
        </AbstractAccordion>
    );
}
