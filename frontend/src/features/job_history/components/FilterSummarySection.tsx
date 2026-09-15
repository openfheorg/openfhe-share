import React, { useEffect, useState } from "react";
import {
    buildDefaultFilterCollectionFromConditions,
    type FilterCollection
} from "../../job_runner/utils/FilterPayloadConfigUtils";
import { API_BASE, API_FILTERS_FETCH_SINGLE } from "../../../constants/Constants";
import FilterSummary from "../../../components/FilterSummary";
import { Project } from "../../../types/Project";

interface FilterSummarySectionProps {
    filterId: number;
    project: Project;
    jobKey: string;
    isOpen: boolean;
    onToggle: () => void;
}

const FilterSummarySection: React.FC<FilterSummarySectionProps> = ({
    filterId,
    project,
    isOpen = true,
    onToggle
}) => {
    const [filterSet, setFilterSet] = useState<FilterCollection | null>(null);

    useEffect(() => {
        const fetchFilter = async () => {
            try {
                const res = await fetch(`${API_BASE}${API_FILTERS_FETCH_SINGLE}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filter_id: filterId, project_id: project.id })
                });

                const data = await res.json();
                const r = data?.filter;
                const collection = buildDefaultFilterCollectionFromConditions(r?.conditions || [], project);
                setFilterSet(collection);
            } catch {
                setFilterSet(null);
            }
        };

        fetchFilter();
    }, [filterId, project]);

    if (!filterSet) return null;

    return (
        <div className="filter-summary-section-block-01">
            <FilterSummary submittedFilterSet={filterSet} boldBorder defaultOpen={isOpen} isOpen={isOpen} onToggle={onToggle} />
        </div>
    );
};

export default FilterSummarySection;
