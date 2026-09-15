import React, { useEffect, useMemo } from "react";
import { Project } from "../../../types/Project";
import { useUserSession } from "../../../context/UserRoleContext";

interface DatasourceGroupSelectorProps {
  project: Project;
  selectedDatasourceGroupId: number | null;
  onChange: (datasourceGroupId: number | null) => void;
  disabled?: boolean;
  isDatasourceLoading?: boolean;
  datasourceLoadError?: string | null;
}

type DatasourceGroupOption = {
  id: number;
  group_name: string;
  is_default: boolean;
};

const DatasourceGroupSelector: React.FC<DatasourceGroupSelectorProps> = ({
  project,
  selectedDatasourceGroupId,
  onChange,
  disabled,
  isDatasourceLoading,
  datasourceLoadError
}) => {
  const userSession = useUserSession();

  const projectEntry = useMemo(() => {
    return userSession.projects.find((entry) => entry.project_id === project.id) || null;
  }, [userSession.projects, project.id]);

  const datasourceGroups = useMemo<DatasourceGroupOption[]>(() => {
    if (!projectEntry) {
      return [];
    }

    const byId = new Map<number, DatasourceGroupOption>();

    for (const datasource of projectEntry.datasources || []) {
      if (datasource.datasource_group_id == null) {
        continue;
      }

      if (!byId.has(datasource.datasource_group_id)) {
        byId.set(datasource.datasource_group_id, {
          id: datasource.datasource_group_id,
          group_name: datasource.datasource_group_name || "DEFAULT",
          is_default: !!datasource.is_default_group
        });
      } else if (datasource.is_default_group) {
        const existing = byId.get(datasource.datasource_group_id)!;
        existing.is_default = true;
      }
    }

    return Array.from(byId.values()).sort((a, b) => {
      if (a.is_default && !b.is_default) return -1;
      if (!a.is_default && b.is_default) return 1;
      return a.group_name.localeCompare(b.group_name);
    });
  }, [projectEntry]);

  const defaultDatasourceGroupId = useMemo(() => {
    const found = datasourceGroups.find((group) => group.is_default);
    return found ? found.id : (datasourceGroups[0]?.id ?? null);
  }, [datasourceGroups]);

  const selectedDatasource = useMemo(() => {
    if (!projectEntry) {
      return null;
    }

    if (selectedDatasourceGroupId == null) {
      return (projectEntry.datasources || [])[0] || null;
    }

    return (
      (projectEntry.datasources || []).find(
        (entry) => entry.datasource_group_id === selectedDatasourceGroupId
      ) || null
    );
  }, [projectEntry, selectedDatasourceGroupId]);

  const selectedDatasourceGroupName = useMemo(() => {
    if (selectedDatasource?.datasource_group_name) {
      return selectedDatasource.datasource_group_name;
    }

    if (selectedDatasourceGroupId == null) {
      return null;
    }

    const match = datasourceGroups.find((group) => group.id === selectedDatasourceGroupId);
    return match?.group_name || null;
  }, [selectedDatasource, selectedDatasourceGroupId, datasourceGroups]);

  useEffect(() => {
    if (!datasourceGroups.length) {
      if (selectedDatasourceGroupId !== null) {
        onChange(null);
      }
      return;
    }

    if (selectedDatasourceGroupId == null) {
      onChange(defaultDatasourceGroupId);
      return;
    }

    if (!datasourceGroups.some((group) => group.id === selectedDatasourceGroupId)) {
      onChange(defaultDatasourceGroupId);
    }
  }, [datasourceGroups, selectedDatasourceGroupId, onChange, defaultDatasourceGroupId]);

  if (!datasourceGroups.length) {
    return null;
  }

  return (
    <div
      className="datasource-group-selector-block-01"
    >
      <h3 className="duality-mb-075">Data Source Selection</h3>
      <div className="datasource-group-selector-block-02">
        This project has multiple data source groups assigned. Select which datasource group to use for preview and submission.
      </div>
      <select
        value={selectedDatasourceGroupId ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        disabled={disabled}
        className="datasource-group-selector-select"
      >
        {datasourceGroups.map((group) => (
          <option key={group.id} value={group.id}>
            {group.group_name}{group.is_default ? " (Default)" : ""}
          </option>
        ))}
      </select>

      {(selectedDatasourceGroupName || selectedDatasource?.source) ? (
        <div
          className="datasource-group-selector-block-03"
        >
          <span>Selected Data Source:</span>{" "}
          <strong>
            {selectedDatasourceGroupName ? `${selectedDatasourceGroupName}` : "DEFAULT"}
            {selectedDatasource?.source ? (
              <span> ({selectedDatasource.source})</span>
            ) : null}
          </strong>
          {isDatasourceLoading ? " (loading...)" : ""}
        </div>
      ) : null}

      {datasourceLoadError ? (
        <div className="datasource-group-selector-block-04">
          {datasourceLoadError}
        </div>
      ) : null}
    </div>
  );
};

export default DatasourceGroupSelector;
