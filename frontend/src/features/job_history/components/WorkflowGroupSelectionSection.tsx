import React, { useEffect, useMemo, useState } from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { NVFlareJob } from "../../../types/JobsDataTypes";

interface WorkflowGroupSelectionSectionProps {
    job: NVFlareJob;
    jobKey: string;
    isOpen: boolean;
    onToggle: () => void;
}

export default function WorkflowGroupSelectionSection({
    job,
    jobKey,
    isOpen
}: WorkflowGroupSelectionSectionProps) {
    const workflowGroups = useMemo(() => job.workflow_groups || [], [job.workflow_groups]);

    const groupKeys = useMemo(
        () => workflowGroups.map((group, index) => String(group.nvflare_job_workflow_group_id || group.workflow_group_id || group.group_key || index)),
        [workflowGroups]
    );

    const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

    useEffect(() => {
        const nextState: Record<string, boolean> = {};
        groupKeys.forEach((key) => {
            nextState[key] = isOpen;
        });
        setOpenGroups(nextState);
    }, [groupKeys, isOpen]);

    if (workflowGroups.length === 0) {
        return (
            <div className="workflow-group-selection-section-block-01">
                No workflow group selection information associated with this job.
            </div>
        );
    }

    return (
        <div className="workflow-group-selection-section-block-02">
            {workflowGroups.map((group, index) => {
                const selectedOptions = group.selected_options || [];
                const accordionKey = String(group.nvflare_job_workflow_group_id || group.workflow_group_id || group.group_key || index);
                const title = group.group_label || group.group_key || `Workflow Group ${index + 1}`;

                return (
                    <AbstractAccordion
                        key={`${jobKey}-${accordionKey}`}
                        title={title}
                        titleTooltip={`Show/Hide ${title}`}
                        isOpen={!!openGroups[accordionKey]}
                        onToggle={() => {
                            setOpenGroups((prev) => ({
                                ...prev,
                                [accordionKey]: !prev[accordionKey]
                            }));
                        }}
                        stopPropagation={true}
                        containerStyle={{ padding: "0" }}
                        bodyStyle={{
                            border: "1px solid black",
                            marginTop: "5px",
                            padding: "0.75rem 1rem",
                            fontSize: 12
                        }}
                    >
                        <div
                            className="duality-d-grid-grid-cols-200px-1fr-row-gap-6px"
                        >
                            {/* <div>Group key:</div>
                            <div style={{ fontWeight: 600 }}>{group.group_key || "--"}</div> */}
                            <div>Selected options:</div>
                            <div className="duality-font-semibold">
                                {selectedOptions.length > 0
                                    ? selectedOptions
                                        .map((option) => option.option_label || option.option_value || option.option_key)
                                        .filter(Boolean)
                                        .join(", ")
                                    : "--"}
                            </div>
                        </div>
                    </AbstractAccordion>
                );
            })}
        </div>
    );
}
