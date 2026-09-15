import React, { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, API_FILTERS_FETCH } from "../../../../constants/Constants";
import { buildDefaultFilterCollectionFromConditions, FilterCollection } from "../../utils/FilterPayloadConfigUtils";
import RefreshablePanel from "../../../../components/RefreshablePanel";
import FilterSummary from "../../../../components/FilterSummary";
import { Project } from "../../../../types/Project";

const PAGE_SIZE = 10;

export interface FilterHistoryRow {
  id: number;
  name: string;
  create_date?: string;
  update_date?: string;
  filter_collection: FilterCollection;
}

interface FilterHistoryTableProps {
  project: Project;
  onUseFilter: (config: FilterCollection, name: string) => void;
  onCreateNewFilterSet: () => void;
}

const FilterHistoryTable: React.FC<FilterHistoryTableProps> = ({
  project,
  onUseFilter,
  onCreateNewFilterSet
}) => {
  const [rows, setRows] = useState<FilterHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterText, setFilterText] = useState("");
  const [page, setPage] = useState(1);
  const [selectedFilterId, setSelectedFilterId] = useState<number | null>(null);
  const [expandedFilterId, setExpandedFilterId] = useState<number | null>(null);

  const tdBase: React.CSSProperties = {
    padding: "8px",
    borderBottom: "1px solid #b4b4b4",
    verticalAlign: "middle",
    fontSize: 14,
    lineHeight: 1.25,
    borderLeft: "none",
    borderRight: "none",
    borderTop: "none"
  };

  const thBase: React.CSSProperties = {
    textAlign: "left",
    fontWeight: 700,
    fontSize: 16,
    padding: "6px 8px",
    whiteSpace: "nowrap",
    borderLeft: "none",
    borderRight: "none",
    borderTop: "none",
    borderBottom: "1px solid #b4b4b4",
    background: "#fff",
    position: "sticky",
    top: 0,
    zIndex: 1
  };

  const fetchFilters = useCallback(async () => {
    if (!project.id) {
      setRows([]);
      setSelectedFilterId(null);
      setExpandedFilterId(null);
      return;
    }
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}${API_FILTERS_FETCH}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: project.id })
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      const list: FilterHistoryRow[] = Array.isArray(data?.filters)
        ? data.filters.map((r: any) => ({
            id: r.id,
            name: r.name,
            create_date: r.create_date,
            update_date: r.update_date,
            filter_collection: buildDefaultFilterCollectionFromConditions(r.conditions || [], project)
          }))
        : [];
      setRows(list);
      setSelectedFilterId(null);
      setExpandedFilterId(null);
      setPage(1);
    } catch (e) {
      console.error("Failed to fetch filters", e);
      setRows([]);
      setSelectedFilterId(null);
      setExpandedFilterId(null);
    } finally {
      setLoading(false);
    }
  }, [project]);

  useEffect(() => {
    fetchFilters();
  }, [fetchFilters]);

  const filteredRows = useMemo(() => {
    const q = filterText.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      const haystack = [
        String(r.id || ""),
        r.name || "",
        r.create_date || "",
        r.update_date || ""
      ]
        .join(" | ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [rows, filterText]);

  useEffect(() => {
    const total = filteredRows.length;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > totalPages) setPage(totalPages);
  }, [filteredRows, page]);

  useEffect(() => {
    setPage(1);
  }, [filterText]);

  const total = filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const startIdx = (page - 1) * PAGE_SIZE;
  const endIdx = Math.min(startIdx + PAGE_SIZE, total);
  const pageRows = filteredRows.slice(startIdx, endIdx);

  const selectedRow = selectedFilterId
    ? rows.find((r) => r.id === selectedFilterId) || null
    : null;

  const primaryButtonLabel = selectedRow ? "Use Selected Filter Set" : "Create New Filter Set";

  const handlePrimaryClick = () => {
    if (selectedRow) {
      onUseFilter(selectedRow.filter_collection, selectedRow.name);
    } else {
      onCreateNewFilterSet();
    }
  };

  const toggleSelectAndExpand = (rowId: number) => {
    setSelectedFilterId((current) => {
      const next = current === rowId ? null : rowId;
      setExpandedFilterId(next);
      return next;
    });
  };

  return (
    <>
      <div className="page-container">
        <RefreshablePanel
          header="Filter History"
          loading={loading}
          onRefresh={fetchFilters}
          refreshAriaLabel="Refresh filters"
          refreshTitle="Refresh"
          right={
            <div
              className="filter-history-table-block-01"
            >
              <h5 className="duality-p-0-m-0-min-w-80px">Quick Filter</h5>
              <input
                type="text"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="Filter by name or date"
                className="duality-p-0-8px-border-1px-solid-ccc-radius-4px"
                aria-label="Filter saved filters"
              />
            </div>
          }
        >
          {rows.length === 0 ? (
            <div>No saved filters found. To begin, select "Create New Filter Set"</div>
          ) : filteredRows.length === 0 ? (
            <div>No filters match your search.</div>
          ) : (
            <div className="duality-w-100pct-overflow-y-hidden-pt-p5rem">
              <table
                className="duality-w-100pct-collapse-collapse-border-spa-0"
              >
                <thead>
                  <tr>
                    <th style={thBase} aria-label="Select" />
                    <th style={thBase}>Filter Name</th>
                    <th style={thBase}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => {
                    const isSelected = selectedFilterId === row.id;
                    const isExpanded = expandedFilterId === row.id;
                    const createdLabel = row.create_date
                      ? new Date(row.create_date).toLocaleString() + " UTC"
                      : "Not recorded";
                    return (
                      <React.Fragment key={row.id}>
                        <tr
                          tabIndex={0}
                          className="filter-history-table-tr" style={{ background: isExpanded ? "#F9F9F9" : "white" }}
                          onClick={() => toggleSelectAndExpand(row.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              toggleSelectAndExpand(row.id);
                            }
                          }}
                        >
                          <td style={{ ...tdBase, width: 40 }}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelectAndExpand(row.id)}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </td>
                          <td style={tdBase}>
                            {row.name}
                          </td>
                          <td style={tdBase}>
                            <div>{createdLabel}</div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr
                            className="filter-history-table-tr-44dd5"
                          >
                            <td
                              style={{
                                ...tdBase,
                                padding: "0.75rem"
                              }}
                              colSpan={3}
                            >
                              <FilterSummary
                                submittedFilterSet={row.filter_collection}
                                // submittedFilterSetName={row.name}
                              />
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>

              {totalPages > 1 && (
                <div
                  className="duality-d-flex-justify-center-align-center"
                >
                  <button type="button" className="link-button-reset duality-decoration-underline-text-under-2px-text-decor-1px"
                    onClick={(e) => {
                      e.preventDefault();
                      if (page > 1) setPage((p) => Math.max(1, p - 1));
                    }}
                    style={{ color: page > 1 ? "#007BFF" : "#A0A0A0", cursor: page > 1 ? "pointer" : "not-allowed", pointerEvents: page > 1 ? "auto" : "none" }}
                          >
                    Previous
                  </button>

                  {(() => {
                    const current = page;
                    const pageCount = totalPages;
                    const windowSize = 5;
                    let start = Math.max(1, current - Math.floor(windowSize / 2));
                    let end = start + windowSize - 1;
                    if (end > pageCount) {
                      end = pageCount;
                      start = Math.max(1, end - windowSize + 1);
                    }
                    return Array.from({ length: end - start + 1 }, (_, i) => {
                      const pageNum = start + i;
                      const isActive = pageNum === current;
                      return (
                        <button type="button" className="link-button-reset duality-p-0p25rem-0p5rem-radius-4px-decoration-underline"
                          key={pageNum}
                          onClick={(e) => {
                            e.preventDefault();
                            setPage(pageNum);
                          }}
                          style={{ color: isActive ? "#fff" : "#007BFF", backgroundColor: isActive ? "#007BFF" : "transparent" }}
                                      >
                          {pageNum}
                        </button>
                      );
                    });
                  })()}

                  <button type="button" className="link-button-reset duality-decoration-underline-text-under-2px-text-decor-1px"
                    onClick={(e) => {
                      e.preventDefault();
                      if (page < totalPages) setPage((p) => Math.min(totalPages, p + 1));
                    }}
                    style={{ color: page < totalPages ? "#007BFF" : "#A0A0A0", cursor: page < totalPages ? "pointer" : "not-allowed", pointerEvents: page < totalPages ? "auto" : "none" }}
                          >
                    Next
                  </button>
                </div>
              )}
            </div>
          )}
        </RefreshablePanel>
      </div>

      <div className="page-container">
        <div className="footer-button-container wizard-start-action-bar">
          <button className="wizard-next-button" onClick={handlePrimaryClick} disabled={loading}>
            {primaryButtonLabel}
          </button>
        </div>
      </div>
    </>
  );
};

export default FilterHistoryTable;
