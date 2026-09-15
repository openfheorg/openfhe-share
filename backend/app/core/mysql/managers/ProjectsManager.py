'''
User roles will be used to determine access to functionality. 
This class returns information from the roles table. 
It’s a simple wrapper around role lookups so that other code 
doesn’t need to write raw SQL directly.

This class will cache results since the id should be something that doesn't change.
'''

from dataclasses import dataclass
from typing import Optional, Any
import json

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.SupportedFilterSystem import SupportedFilterSystem
from app.core.mysql.SupportedFunction import SupportedFunction


@dataclass
class ProjectFunctionCapability:
    function: SupportedFunction
    configurable: bool
    custom_configuration_fixed: Optional[dict[str, Any]] = None
    custom_configuration_variable: Optional[dict[str, Any]] = None
    override_configuration: Optional[dict[str, Any]] = None


@dataclass
class FilterSystemInfo:
    id: int
    name: str
    description: Optional[str]
    allowed_filter_types: list[str]


@dataclass
class ProjectDatasourceGroup:
    id: int
    group_name: str
    is_default: bool


@dataclass
class ProjectWorkflowGroupOption:
    id: int
    option_key: str
    option_label: str
    option_value: str
    option_description: Optional[str]
    option_order: int
    is_default: bool


@dataclass
class ProjectWorkflowGroup:
    id: int
    group_key: str
    group_label: str
    group_description: Optional[str]
    min_selected: int
    max_selected: Optional[int]
    is_required: bool
    page_order: int
    validation_config: Optional[dict[str, Any]]
    options: list[ProjectWorkflowGroupOption]


@dataclass
class Project:
    id: int
    name: str
    description: Optional[str]
    status: Optional[str]
    fixed: Optional[bool]
    function_restrictions_enabled: bool
    filter_system: Optional[str]
    filter_system_allowed_filter_types: list[str]
    functions: list[ProjectFunctionCapability]
    datasource_groups_defined: bool
    datasource_groups: list[ProjectDatasourceGroup]
    default_datasource_group: Optional[ProjectDatasourceGroup]
    selected_datasource_group: Optional[ProjectDatasourceGroup]
    workflow_groups_defined: bool
    workflow_groups: list[ProjectWorkflowGroup]


class ProjectsManager:
    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def _safe_json_loads(self, raw: Any) -> Optional[dict[str, Any]]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (list, tuple)):
            return None
        try:
            s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            s = s.strip()
            if not s or s == "null":
                return None
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _get_filter_system_map(self) -> dict[int, FilterSystemInfo]:
        self.cursor.execute(
            """
            SELECT
                dfs.id AS filter_system_id,
                dfs.name AS filter_system_name,
                dfs.description AS filter_system_description
            FROM defined_filter_system dfs
            """
        )
        rows = self.cursor.fetchall() or []

        by_id: dict[int, FilterSystemInfo] = {}
        for r in rows:
            fs_id = r.get("filter_system_id")
            fs_name = r.get("filter_system_name")
            if not fs_id or not fs_name:
                continue
            by_id[int(fs_id)] = FilterSystemInfo(
                id=int(fs_id),
                name=str(fs_name),
                description=r.get("filter_system_description"),
                allowed_filter_types=[],
            )

        self.cursor.execute(
            """
            SELECT
                filter_system_id,
                filter_type
            FROM defined_filter_system_allowed_filter_types
            """
        )
        rows2 = self.cursor.fetchall() or []
        for r in rows2:
            fs_id = r.get("filter_system_id")
            ft = r.get("filter_type")
            if fs_id is None or not ft:
                continue
            fs = by_id.get(int(fs_id))
            if not fs:
                continue
            ft_s = str(ft)
            if ft_s not in fs.allowed_filter_types:
                fs.allowed_filter_types.append(ft_s)

        for fs in by_id.values():
            fs.allowed_filter_types.sort()

        return by_id

    def _get_project_functions(
        self,
        project_id: int,
        restrictions_enabled: bool,
    ) -> list[ProjectFunctionCapability]:
        if not restrictions_enabled:
            return [
                ProjectFunctionCapability(
                    function=f,
                    configurable=True,
                    custom_configuration_fixed=None,
                    custom_configuration_variable=None,
                    override_configuration=None,
                )
                for f in SupportedFunction
            ]

        self.cursor.execute(
            """
            SELECT
                dpf.function_id,
                dpf.enabled,
                dpf.configurable,
                dpf.custom_configuration_fixed,
                dpf.custom_configuration_variable,
                dpf.override_configuration,
                df.name AS function_name
            FROM defined_project_function_restrictions dpf
            JOIN defined_functions df
                ON dpf.function_id = df.id
            WHERE dpf.project_id = %s
              AND dpf.enabled = 'ENABLED'
            ORDER BY df.name
            """,
            (project_id,),
        )
        rows = self.cursor.fetchall() or []

        name_to_enum = {str(f): f for f in SupportedFunction}
        out: list[ProjectFunctionCapability] = []

        for r in rows:
            fn_name = r.get("function_name")
            fn_enum = name_to_enum.get(fn_name)
            if not fn_enum:
                continue

            configurable = bool(r.get("configurable"))
            fixed_cfg = self._safe_json_loads(r.get("custom_configuration_fixed"))
            variable_cfg = self._safe_json_loads(r.get("custom_configuration_variable"))
            override_cfg = self._safe_json_loads(r.get("override_configuration"))

            out.append(
                ProjectFunctionCapability(
                    function=fn_enum,
                    configurable=configurable,
                    custom_configuration_fixed=fixed_cfg,
                    custom_configuration_variable=variable_cfg,
                    override_configuration=override_cfg,
                )
            )

        return out

    def get_defined_project_datasource_groups(self, project_id: int) -> list[ProjectDatasourceGroup]:
        self.cursor.execute(
            """
            SELECT
                id,
                group_name,
                is_default
            FROM defined_project_datasource_groups
            WHERE project_id = %s
            ORDER BY is_default DESC, group_name ASC, id ASC
            """,
            (project_id,),
        )
        rows = self.cursor.fetchall() or []

        out: list[ProjectDatasourceGroup] = []
        for row in rows:
            group_id = row.get("id")
            group_name = row.get("group_name")
            if group_id is None or not group_name:
                continue
            out.append(
                ProjectDatasourceGroup(
                    id=int(group_id),
                    group_name=str(group_name),
                    is_default=bool(row.get("is_default")),
                )
            )

        return out

    def get_default_project_datasource_group(self, project_id: int) -> Optional[ProjectDatasourceGroup]:
        groups = self.get_defined_project_datasource_groups(project_id)
        for group in groups:
            if group.is_default:
                return group
        return None

    def get_project_datasource_group_by_id(
        self,
        project_id: int,
        datasource_group_id: Optional[int],
    ) -> Optional[ProjectDatasourceGroup]:
        if datasource_group_id is None:
            return None

        self.cursor.execute(
            """
            SELECT
                id,
                group_name,
                is_default
            FROM defined_project_datasource_groups
            WHERE project_id = %s
              AND id = %s
            LIMIT 1
            """,
            (project_id, datasource_group_id),
        )
        row = self.cursor.fetchone()
        if not row:
            return None

        return ProjectDatasourceGroup(
            id=int(row["id"]),
            group_name=str(row["group_name"]),
            is_default=bool(row.get("is_default")),
        )

    def get_project_datasource_group_summary(self, project_id: int) -> dict[str, Any]:
        groups = self.get_defined_project_datasource_groups(project_id)
        default_group = None
        for group in groups:
            if group.is_default:
                default_group = group
                break

        return {
            "datasource_groups_defined": len(groups) > 0,
            "datasource_groups": groups,
            "default_datasource_group": default_group,
        }


    def get_defined_project_workflow_groups(self, project_id: int) -> list[ProjectWorkflowGroup]:
        self.cursor.execute(
            """
            SELECT
                id,
                group_key,
                group_label,
                group_description,
                min_selected,
                max_selected,
                is_required,
                page_order,
                validation_config
            FROM defined_project_workflow_groups
            WHERE project_id = %s
              AND status = 'ACTIVE'
            ORDER BY page_order ASC, group_label ASC, id ASC
            """,
            (project_id,),
        )
        group_rows = self.cursor.fetchall() or []

        if not group_rows:
            return []

        self.cursor.execute(
            """
            SELECT
                workflow_group_id,
                id,
                option_key,
                option_label,
                option_value,
                option_description,
                option_order,
                is_default
            FROM defined_project_workflow_group_options
            WHERE workflow_group_id IN (
                SELECT id
                FROM defined_project_workflow_groups
                WHERE project_id = %s
                  AND status = 'ACTIVE'
            )
              AND status = 'ACTIVE'
            ORDER BY workflow_group_id ASC, option_order ASC, option_label ASC, id ASC
            """,
            (project_id,),
        )
        option_rows = self.cursor.fetchall() or []

        options_by_group_id: dict[int, list[ProjectWorkflowGroupOption]] = {}
        for row in option_rows:
            workflow_group_id = row.get("workflow_group_id")
            option_id = row.get("id")
            option_key = row.get("option_key")
            option_label = row.get("option_label")
            option_value = row.get("option_value")
            if workflow_group_id is None or option_id is None or not option_key or not option_label or not option_value:
                continue

            if int(workflow_group_id) not in options_by_group_id:
                options_by_group_id[int(workflow_group_id)] = []

            options_by_group_id[int(workflow_group_id)].append(
                ProjectWorkflowGroupOption(
                    id=int(option_id),
                    option_key=str(option_key),
                    option_label=str(option_label),
                    option_value=str(option_value),
                    option_description=row.get("option_description"),
                    option_order=int(row.get("option_order") or 0),
                    is_default=bool(row.get("is_default")),
                )
            )

        out: list[ProjectWorkflowGroup] = []
        for row in group_rows:
            group_id = row.get("id")
            group_key = row.get("group_key")
            group_label = row.get("group_label")
            if group_id is None or not group_key or not group_label:
                continue

            out.append(
                ProjectWorkflowGroup(
                    id=int(group_id),
                    group_key=str(group_key),
                    group_label=str(group_label),
                    group_description=row.get("group_description"),
                    min_selected=int(row.get("min_selected") or 0),
                    max_selected=int(row["max_selected"]) if row.get("max_selected") is not None else None,
                    is_required=bool(row.get("is_required")),
                    page_order=int(row.get("page_order") or 0),
                    validation_config=self._safe_json_loads(row.get("validation_config")),
                    options=list(options_by_group_id.get(int(group_id), [])),
                )
            )

        return out

    def get_project_workflow_group_summary(self, project_id: int) -> dict[str, Any]:
        groups = self.get_defined_project_workflow_groups(project_id)
        return {
            "workflow_groups_defined": len(groups) > 0,
            "workflow_groups": groups,
        }

    def _build_project(
        self,
        row: dict[str, Any],
        filter_system_map: dict[int, FilterSystemInfo],
        datasource_group_id: Optional[int] = None,
    ) -> Project:
        fs_id = row.get("filter_system_id")
        fs = filter_system_map.get(int(fs_id)) if fs_id is not None else None

        restrictions_enabled = bool(row.get("function_restrictions_enabled"))
        functions = self._get_project_functions(
            project_id=row["id"],
            restrictions_enabled=restrictions_enabled,
        )

        datasource_group_summary = self.get_project_datasource_group_summary(row["id"])
        selected_datasource_group = self.get_project_datasource_group_by_id(row["id"], datasource_group_id)
        workflow_group_summary = self.get_project_workflow_group_summary(row["id"])

        return Project(
            id=row["id"],
            name=row["name"],
            description=row.get("description"),
            status=row.get("status"),
            fixed=bool(row["fixed"]) if row.get("fixed") is not None else None,
            function_restrictions_enabled=restrictions_enabled,
            filter_system=fs.name if fs else None,
            filter_system_allowed_filter_types=list(fs.allowed_filter_types) if fs else [],
            functions=functions,
            datasource_groups_defined=bool(datasource_group_summary["datasource_groups_defined"]),
            datasource_groups=list(datasource_group_summary["datasource_groups"]),
            default_datasource_group=datasource_group_summary["default_datasource_group"],
            selected_datasource_group=selected_datasource_group,
            workflow_groups_defined=bool(workflow_group_summary["workflow_groups_defined"]),
            workflow_groups=list(workflow_group_summary["workflow_groups"]),
        )

    def get_project_list(self) -> list[Project]:
        filter_system_map = self._get_filter_system_map()

        self.cursor.execute(
            f"""
            SELECT
                p.id,
                p.name,
                p.description,
                p.status,
                p.fixed,
                p.function_restrictions_enabled,
                p.filter_system_id,
                p.create_date,
                p.update_date
            FROM {MySQLTable.PROJECTS} p
            ORDER BY p.name
            """
        )
        rows = self.cursor.fetchall() or []

        out: list[Project] = []
        for r in rows:
            out.append(self._build_project(r, filter_system_map))

        return out

    def get_project(self, project_id: int, datasource_group_id: Optional[int] = None) -> Project | None:
        filter_system_map = self._get_filter_system_map()

        self.cursor.execute(
            f"""
            SELECT
                p.id,
                p.name,
                p.description,
                p.status,
                p.fixed,
                p.function_restrictions_enabled,
                p.filter_system_id
            FROM {MySQLTable.PROJECTS} p
            WHERE p.id = %s
            LIMIT 1
            """,
            (project_id,),
        )
        row = self.cursor.fetchone()
        if not row:
            return None

        return self._build_project(row, filter_system_map, datasource_group_id)
