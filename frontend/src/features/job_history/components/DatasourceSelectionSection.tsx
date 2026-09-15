import React, { useMemo } from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { useSelectedProjectDatasources } from "../../../context/UserRoleContext";
import { NVFlareJob } from "../../../types/JobsDataTypes";

interface DatasourceSelectionSectionProps {
    job: NVFlareJob;
    jobKey: string;
    isOpen: boolean;
    onToggle: () => void;
}

export default function DatasourceSelectionSection({
    job,
    jobKey,
    isOpen,
    onToggle
}: DatasourceSelectionSectionProps) {
    const selectedProjectDatasources = useSelectedProjectDatasources();
    const datasourceLog = job.datasource_log;
    const datasourceGroupName = datasourceLog?.datasource_group_name || job.datasource_group_name || null;
    const datasourceGroupId = datasourceLog?.datasource_group_id ?? job.datasource_group_id ?? null;

    const datasourceDetails = useMemo(() => {
        if (!selectedProjectDatasources.length) {
            return null;
        }

        if (datasourceGroupId != null) {
            const groupedMatch = selectedProjectDatasources.find((entry) => entry.datasource_group_id === datasourceGroupId);
            if (groupedMatch) {
                return {
                    showGroup: true,
                    groupName: datasourceGroupName || groupedMatch.datasource_group_name || `Group ${datasourceGroupId}`,
                    source: groupedMatch.source,
                    href: groupedMatch.source.toLowerCase().endsWith(".json") ? null : groupedMatch.source,
                };
            }
        }

        const defaultDatasource =
            selectedProjectDatasources.find((entry) => entry.is_default_group) ||
            selectedProjectDatasources.find((entry) => entry.datasource_group_id == null) ||
            selectedProjectDatasources[0];

        if (!defaultDatasource) {
            return null;
        }

        return {
            showGroup: false,
            groupName: null,
            source: defaultDatasource.source,
            href: defaultDatasource.source.toLowerCase().endsWith(".json") ? null : defaultDatasource.source,
        };
    }, [selectedProjectDatasources, datasourceGroupId, datasourceGroupName]);

    return (
        <AbstractAccordion
            title="Data Source Selection (You)"
            titleTooltip="Show/Hide Data Source Selection"
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
            {datasourceDetails ? (
                <div
                    className="duality-d-grid-grid-cols-200px-1fr-row-gap-6px"
                >
                    {datasourceDetails.showGroup ? (
                        <>
                            <div>Data source group:</div>
                            <div className="duality-font-semibold">{datasourceDetails.groupName || "--"}</div>
                        </>
                    ) : null}

                    <div>Data source:</div>
                    {datasourceDetails.href ? (
                        <a
                            target="_blank"
                            rel="noreferrer"
                            href={datasourceDetails.href}
                            className="datasource-selection-section-shared-01"
                        >
                            {datasourceDetails.source}
                        </a>
                    ) : (
                        <div className="datasource-selection-section-shared-01">
                            {datasourceDetails.source}
                        </div>
                    )}
                </div>
            ) : (
                <div className="duality-text-64748b-fs-12px">
                    No data source selection information associated with this job.
                </div>
            )}
        </AbstractAccordion>
    );
}
