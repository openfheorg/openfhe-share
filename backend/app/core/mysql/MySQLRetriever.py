'''
Thin wrapper for SELECT-only queries against MySQL.
This class centralizes retrieval logic so endpoints and services
don’t need to worry about SQL or cursor handling.
'''

from typing import Any, Dict, List, Optional
import pymysql

from app.core.mysql.managers.FiltersManager import Operator
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider

class MySQLRetriever:
    '''
    Lifecycle:
      - Grabs a pooled connection from MySQLConnectionProvider.
      - Exposes read-only helper methods for common queries.
      - Call .complete() when finished to release cursor/connection.
    '''
    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()


    def get_all_filters(self, project_id: Optional[int] = None):
        if project_id is not None:
            self.cursor.execute(
                """
                SELECT f.id, f.name, f.project_id, f.create_date, f.update_date
                FROM defined_fhir_filters f
                WHERE f.project_id = %s
                ORDER BY f.create_date DESC, f.id DESC
                """,
                (project_id,),
            )
        else:
            self.cursor.execute(
                """
                SELECT f.id, f.name, f.project_id, f.create_date, f.update_date
                FROM defined_fhir_filters f
                ORDER BY f.create_date DESC, f.id DESC
                """
            )

        filters = self.cursor.fetchall()

        out = []
        for f in filters:
            self.cursor.execute(
                """
                SELECT filter_type, column_name, operator, value
                FROM defined_fhir_filter_conditions
                WHERE filter_id = %s
                """,
                (f["id"],),
            )
            conds = self.cursor.fetchall()
            out.append({
                "id": f["id"],
                "name": f["name"],
                "project_id": f.get("project_id"),
                "conditions": conds,
                "create_date": f["create_date"].isoformat() if f.get("create_date") else None,
                "update_date": f["update_date"].isoformat() if f.get("update_date") else None,
            })
        return out


    def get_single_filter(self, filter_id: int):
        self.cursor.execute(
            """
            SELECT
                id   AS filter_id,
                name AS filter_name,
                create_date,
                update_date
            FROM defined_fhir_filters
            WHERE id = %s
            """,
            (filter_id,),
        )
        f = self.cursor.fetchone()
        if not f:
            return None

        self.cursor.execute(
            """
            SELECT filter_type, column_name, operator, value
            FROM defined_fhir_filter_conditions
            WHERE filter_id = %s
            """,
            (f["filter_id"],),
        )
        conds = self.cursor.fetchall()

        return {
            "id": f["filter_id"],
            "name": f["filter_name"],
            "conditions": conds,
            "create_date": f["create_date"].isoformat() if f.get("create_date") else None,
            "update_date": f["update_date"].isoformat() if f.get("update_date") else None,
        }


    def stage_filters_by_id(self, filter_id: int) -> Dict[str, Any]:
        """
        Look up a filter and reconstruct its definition by ID.
        Returns a dict like:
        {
            "name": <filter_name>,
            "filter_id": <filter_id>,
            "conditions": [ {filter_type, column_name, operator, value, values?}, ... ]
        }
        """
        self.cursor.execute(
            """
            SELECT id, name
            FROM defined_fhir_filters
            WHERE id = %s
            """,
            (filter_id,),
        )
        row = self.cursor.fetchone()
        if not row:
            raise ValueError(f"Filter {filter_id} not found")

        conditions = self._fetch_filter_conditions(filter_id)

        return {
            "filter_id": row["id"],
            "name": row["name"],
            "conditions": conditions,
        }


    def _fetch_filter_conditions(self, filter_id: int) -> List[Dict[str, Any]]:
        """
        Pulls all conditions from the DB for a given filter_id and reconstructs them
        into the normalized format used throughout this class. Values are decoded
        if they were stored as CSV, and the list is sorted for comparison.
        """
        self.cursor.execute(
            """
            SELECT filter_type, column_name, operator, value
            FROM defined_fhir_filter_conditions
            WHERE filter_id = %s
            """,
            (filter_id,),
        )
        rows = self.cursor.fetchall()

        got: List[Dict[str, Any]] = []
        for r in rows:
            op = str(r["operator"] or "").upper()
            val = r["value"] or ""
            cond: Dict[str, Any] = {
                "filter_type": r["filter_type"],
                "column_name": r["column_name"],
                "operator": op,
                "value": val,
            }
            # For set-like operators, also provide a decoded "values" array alongside the raw "value" CSV
            if op in {Operator.IN.value, Operator.NOT_IN.value, Operator.BETWEEN.value, Operator.IN_ALL.value}:
                cond["values"] = self._csv_decode(val)
            got.append(cond)

        got.sort(key=lambda x: (x["filter_type"], x["column_name"], x["operator"], x["value"]))
        return got


    def _csv_decode(self, s: str) -> List[str]:
        """
        Reverses _csv_encode, turning escaped CSV back into a list of values.
        Used when fetching conditions back out of the DB so comparisons can be made properly.
        """
        out, cur, esc = [], [], False
        for ch in s or "":
            if esc:
                cur.append(ch)
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == ",":
                out.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        out.append("".join(cur))
        return out
