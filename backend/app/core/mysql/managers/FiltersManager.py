"""
FiltersManager (function-agnostic, project-scoped)

This class is responsible for:
  - Validating and normalizing an incoming "filters" definition.
  - Computing a stable hash over the normalized conditions so identical filter
    sets dedupe to a single DB row (via a UNIQUE filter_hash), scoped by project_id.
  - Looking up an existing filter by hash for a given project, or inserting a new
    header + its conditions in a single, canonical format.

Key design points:
  - Filters are independent of any function (no function_id ties).
  - Filters are scoped to a project via project_id. Identical condition sets
    in different projects are stored as separate rows.
  - Conditions are normalized before hashing:
      - filter_type, column_name, operator are canonicalized
      - values are serialized deterministically
      - the list is sorted for stable ordering
  - Equality checks handle set-like operators (IN / NOT_IN / IN_ALL / BETWEEN).
"""

import hashlib
from enum import Enum
from typing import List, Dict, Any

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.job_tracking.JobStatusWriter import (
    JobRunnerStatus,
    JobStatusWriter,
    safe_status_update,
)
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider


# FilterType is just an enum that classifies where a filter applies.
# PATIENT_QUERY filters hit query-level attributes like demographics,
# PATIENT_DATA filters are for patient record fields (like dates),
# and OBSERVATION filters cover measured data points such as genomic variants.
class FilterType(str, Enum):
    PATIENT_QUERY = "PATIENT_QUERY"
    PATIENT_DATA = "PATIENT_DATA"
    OBSERVATION = "OBSERVATION"
    OBSERVATION_QUERY = "OBSERVATION_QUERY"
    OBSERVATION_DATA = "OBSERVATION_DATA"


# Operator standardizes the set of comparison operators we allow in filters.
# It makes sure we don’t get oddball inputs like “==” or “<>” sneaking into the DB.
# This keeps all conditions stored consistently and makes equality checks reliable.
class Operator(str, Enum):
    EQ = "="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    LIKE = "LIKE"
    IN = "IN"
    NOT_IN = "NOT_IN"
    BETWEEN = "BETWEEN"
    IN_ALL = "IN_ALL"


# Canonical operator spellings we accept and map to our enum.
_CANON_OPS = {
    "=": Operator.EQ,
    "==": Operator.EQ,
    "!=": Operator.NE,
    "<>": Operator.NE,
    ">": Operator.GT,
    ">=": Operator.GTE,
    "<": Operator.LT,
    "<=": Operator.LTE,
    "LIKE": Operator.LIKE,
    "IN": Operator.IN,
    "IN_ALL": Operator.IN_ALL,
    "IN ALL": Operator.IN_ALL,
    "NOT_IN": Operator.NOT_IN,
    "NOT IN": Operator.NOT_IN,
    "BETWEEN": Operator.BETWEEN,
}


# FiltersManager is the main workhorse here. It’s responsible for taking in a filter definition,
# validating and normalizing it, then either finding an existing matching filter in the DB
# or saving a new one. This avoids duplicates, ensures consistency, and guarantees filters
# are stored in a canonical form. Filters are now function-agnostic and scoped by project_id.
class FiltersManager:
    def __init__(self, project_id: int, filters: dict | None, status_writer: JobStatusWriter | None = None):
        # project_id binds all lookups/inserts to a specific project. The same
        # filter_hash may exist in multiple projects as separate rows.
        self.status_writer = status_writer
        safe_status_update(
            self.status_writer,
            JobRunnerStatus.FILTERS_PROCESSING,
            "FiltersManager: Processing filters"
        )

        self.project_id = project_id

        # Name and normalized conditions derived from the incoming filters payload.
        self.filters_name: str | None = None
        self.conditions: List[Dict[str, str]] = []

        if filters:
            f = filters or {}
            self.filters_name = f.get("name")
            raw_conditions = f.get("conditions")

            # Validate + normalize up front; raises ValueError on any issue
            self.conditions = self._validate_and_normalize_conditions(self.filters_name, raw_conditions)

        # Open a connection/cursor for subsequent lookups and writes.
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        # Ensure DB resources are closed from the caller (try/finally around this).
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def save_or_get_filter_id(self) -> int:
        """
        Resolves filter_id for this project if it exists (by hash),
        otherwise creates a new header + conditions and returns the new id.
        The hash comparison and uniqueness are scoped by project_id.
        """
        filter_id = self.get_id_by_filters()
        if filter_id:
            safe_status_update(
                self.status_writer,
                JobRunnerStatus.FILTERS_PROCESSING,
                "FiltersManager: Existing filters found"
            )
            return filter_id

        # Insert a new filter header + conditions
        hash_val = self._compute_hash(self.conditions)
        new_id = self._insert_filter(self.filters_name, hash_val)
        self._insert_conditions(new_id, self.conditions)

        safe_status_update(
            self.status_writer,
            JobRunnerStatus.FILTERS_PROCESSING,
            "FiltersManager: Filters saved"
        )
        return new_id

    def get_id_by_filters(self) -> int | None:
        """
        Lookup a filter_id by hash for this project (function-agnostic).
        Returns the ID if found, or None if not. Does not create new rows.
        """
        hash_val = self._compute_hash(self.conditions)
        self.cursor.execute(
            """
            SELECT id
            FROM defined_fhir_filters
            WHERE project_id = %s
              AND filter_hash = %s
            """,
            (self.project_id, hash_val),
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None



    def _csv_encode(self, items: List[Any]) -> str:
        """
        Internal helper to serialize lists of values into a safe comma separated value string.
        Escapes commas and backslashes, deduplicates (caller should pre-clean), and joins.
        This gives deterministic, comparable strings for storage in the DB.
        """
        items = ["" if v is None else str(v) for v in (items or [])]
        items = [s.replace("\\", "\\\\").replace(",", "\\,") for s in items]
        return ",".join(items)

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

    def _canonicalize_operator(self, op_in: Any) -> Operator:
        """
        Normalizes a raw operator string into one of the Operator enum values.
        Handles odd spellings like "==" or "NOT IN" so the rest of the system
        only ever deals with a single canonical form.
        """
        op_raw = str(op_in or "").strip().upper()
        if op_raw in _CANON_OPS:
            return _CANON_OPS[op_raw]
        op_try = op_raw.replace("_", " ")
        if op_try in _CANON_OPS:
            return _CANON_OPS[op_try]
        raise ValueError(f"Unsupported operator: {op_in}")

    def _validate_and_normalize_conditions(self, name: Any, conditions: Any) -> List[Dict[str, str]]:
        """
        Runs up-front validation of the provided filters.
        Checks for required fields, ensures types are correct, normalizes operators,
        encodes values properly, and sorts everything. Raises ValueError on bad input.
        The return is a list of consistently structured condition dicts.
        """
        if not name or not isinstance(name, str):
            raise ValueError("filters.name is required and must be a string")

        # Allow no conditions, treat None or [] as "no filters"
        if conditions is None:
            return []
        if not isinstance(conditions, list):
            raise ValueError("filters.conditions must be an array")
        if len(conditions) == 0:
            return []

        valid_types = {t.value for t in FilterType}
        norm: List[Dict[str, str]] = []

        for idx, c in enumerate(conditions):
            if not isinstance(c, dict):
                raise ValueError(f"conditions[{idx}] must be an object")

            ft = str(c.get("filter_type") or "").strip().upper()
            if ft not in valid_types:
                raise ValueError(f"conditions[{idx}].filter_type invalid: {ft}")

            col = str(c.get("column_name") or "").strip()
            if not col:
                raise ValueError(f"conditions[{idx}].column_name is required")

            op = self._canonicalize_operator(c.get("operator"))

            if op in (Operator.IN, Operator.NOT_IN, Operator.IN_ALL):
                # Operators that expect an array; we accept single "value" for convenience and coerce to [value]
                vals = c.get("values")
                if vals is None and "value" in c:
                    vals = [c.get("value")]
                if not isinstance(vals, list) or not vals:
                    raise ValueError(f"conditions[{idx}]: operator {op.value} requires a non-empty 'values' array")
                csv_val = self._csv_encode(vals)
                norm.append({"filter_type": ft, "column_name": col, "operator": op.value, "value": csv_val})

            elif op == Operator.BETWEEN:
                # BETWEEN must have exactly two values (lower, upper)
                vals = c.get("values")
                if not isinstance(vals, list) or len(vals) != 2:
                    raise ValueError(f"conditions[{idx}]: operator BETWEEN requires 'values' with exactly 2 entries")
                csv_val = self._csv_encode(vals)
                norm.append({"filter_type": ft, "column_name": col, "operator": op.value, "value": csv_val})

            else:
                # Simple operators expect a scalar "value"
                if "value" not in c:
                    raise ValueError(f"conditions[{idx}]: operator {op.value} requires 'value'")
                v = "" if c.get("value") is None else str(c.get("value"))
                norm.append({"filter_type": ft, "column_name": col, "operator": op.value, "value": v})

        # Sort to make the signature stable and equality comparisons deterministic
        norm.sort(key=lambda x: (x["filter_type"], x["column_name"], x["operator"], x["value"]))
        return norm


    def _conditions_equal(self, a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
        """
        Compares two lists of conditions for equality. Special logic is applied
        for IN, NOT_IN, IN_ALL, and BETWEEN to compare sets instead of exact CSV strings.
        Used to decide whether a new filter definition matches an existing one.
        """
        if len(a) != len(b):
            return False
        for i in range(len(a)):
            ai, bi = a[i], b[i]
            if ai["filter_type"] != bi["filter_type"]:
                return False
            if ai["column_name"] != bi["column_name"]:
                return False
            if ai["operator"] != bi["operator"]:
                return False

            op = ai["operator"]
            if op in {Operator.IN.value, Operator.NOT_IN.value, Operator.BETWEEN.value, Operator.IN_ALL.value}:
                if set(self._csv_decode(ai["value"])) != set(self._csv_decode(bi["value"])):  # compare sets
                    return False
            else:
                if ai["value"] != bi["value"]:
                    return False
        return True

    # Hash signature of the conditions allows us to enforce a unique_key and avoid duplicate filter sets
    def _build_signature(self, conditions: List[Dict[str, str]]) -> str:
        return "".join(
            f"[{c['filter_type']}|{c['column_name']}|{c['operator']}|{c['value']}]"
            for c in conditions
        )

    def _compute_hash(self, conditions: List[Dict[str, str]]) -> str:
        """
        Computes a deterministic SHA-256 over the normalized conditions. Any semantically
        identical filter set should hash to the same value, enabling deduplication
        within a given project_id.
        """
        signature = self._build_signature(conditions)
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()

    def _insert_filter(self, name: str | None, hash_val: str) -> int:
        """
        Inserts a new filter header row into defined_fhir_filters for this project.
        Filters are stored with (project_id, name, filter_hash).
        Returns the auto-incremented filter ID.
        """
        self.cursor.execute(
            "INSERT INTO defined_fhir_filters (project_id, name, filter_hash) VALUES (%s, %s, %s)",
            (self.project_id, name, hash_val),
        )
        self.connection.commit()
        return self.cursor.lastrowid

    def _insert_conditions(self, filter_id: int, conditions: List[Dict[str, str]]):
        """
        Inserts all normalized conditions for a given filter in one batch.
        If conditions is empty it just exits. Commits immediately.
        """
        if not conditions:
            return
        self.cursor.executemany(
            """
            INSERT INTO defined_fhir_filter_conditions
            (filter_id, filter_type, column_name, operator, value)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [(filter_id, c["filter_type"], c["column_name"], c["operator"], c["value"]) for c in conditions],
        )
        self.connection.commit()
