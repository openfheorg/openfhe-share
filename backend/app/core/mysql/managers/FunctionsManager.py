# app/core/mysql/managers/FunctionsManager.py
"""
Utility for resolving functions and their configs from MySQL.
Provides lookups, normalization, creation of config rows, and retrieval/linking helpers.
"""

from typing import Mapping, Dict, List, Set, Optional, Any

import hashlib
from app.core.mysql.SupportedFunction import FUNCTION_DEFAULT_PROPERTIES, FUNCTION_PROPERTY_TYPES, SupportedFunction

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider


class FunctionsManager:
    _function_id_cache: Dict[str, int] = {}

    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    @staticmethod
    def normalize_map(functions_map: Optional[Mapping[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
        """
        Normalize a map of function -> config set(s).

        Accepts values in several shapes:
          - { "SURVIVAL_ANALYSIS": { ...single config... } }
          - { "SURVIVAL_ANALYSIS": [ { ...cfg0... }, { ...cfg1... } ] }

        Returns:
          { "SURVIVAL_ANALYSIS": [ {prop: value}, ... ], ... }
        with:
          - Function names uppercased and trimmed.
          - Property keys trimmed.
          - None values coerced to "".
        """
        if not functions_map:
            return {}

        out: Dict[str, List[Dict[str, str]]] = {}

        for fn_key, cfg_val in functions_map.items():
            fn_name = str(fn_key).strip().upper()
            if not fn_name:
                continue
            fn_enum = SupportedFunction.from_name(fn_name)
            if fn_enum is not None:
                fn_name = str(fn_enum)

            cfg_list: List[Dict[str, str]] = []

            # Single config dict
            if isinstance(cfg_val, Mapping):
                props = FunctionsManager._normalize_props(cfg_val)
                if props:
                    cfg_list.append(props)

            # List/tuple of config dicts
            elif isinstance(cfg_val, (list, tuple)):
                for item in cfg_val:
                    if isinstance(item, Mapping):
                        props = FunctionsManager._normalize_props(item)
                        if props:
                            cfg_list.append(props)

            if cfg_list:
                out[fn_name] = cfg_list

        return out

    @staticmethod
    def _normalize_props(props: Mapping[str, Any]) -> Dict[str, str]:
        """
        Normalize a single config set's properties {prop: value}.
        """
        out: Dict[str, str] = {}
        if not isinstance(props, Mapping):
            return out
        for k, v in props.items():
            key = str(k).strip()
            if not key:
                continue
            out[key] = "" if v is None else str(v)
        return out

    def get_function_id(self, function: SupportedFunction) -> Optional[int]:
        """
        Return the id for a SupportedFunction (by name), using a simple in-process cache.
        """
        key = str(function).strip().upper()
        if key in self._function_id_cache:
            return self._function_id_cache[key]
        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.FUNCTIONS}
            WHERE name=%s
            LIMIT 1
            """,
            (key,),
        )
        row = self.cursor.fetchone()
        if row:
            function_id = int(row["id"])
            self._function_id_cache[key] = function_id
            return function_id
        return None

    def get_supported_functions(self):
        """
        Return all defined functions with ISO timestamps.
        """
        self.cursor.execute(
            f"""
            SELECT id, name, description, create_date, update_date
            FROM {MySQLTable.FUNCTIONS}
            ORDER BY name
            """
        )
        rows = self.cursor.fetchall()
        for r in rows:
            if r.get("create_date"):
                r["create_date"] = r["create_date"].isoformat()
            if r.get("update_date"):
                r["update_date"] = r["update_date"].isoformat()
        return rows

    def get_function_ids_by_names(self, names: List[str]) -> Dict[str, int]:
        """
        Bulk-lookup of function ids by names.
        """
        clean = sorted({n for n in (names or []) if n})
        if not clean:
            return {}
        placeholders = ",".join(["%s"] * len(clean))
        self.cursor.execute(
            f"SELECT id, name FROM {MySQLTable.FUNCTIONS} WHERE name IN ({placeholders})",
            clean,
        )
        rows = self.cursor.fetchall()
        return {r["name"]: int(r["id"]) for r in rows}

    def ensure_functions_exist(self, names: List[str]) -> Dict[str, int]:
        """
        Validate that all given function names exist; returns name->id mapping.
        Raises ValueError if any are unknown.
        """
        mapping = self.get_function_ids_by_names(names)
        if len(mapping) != len({n for n in names if n}):
            unknown = sorted(set(names) - set(mapping.keys()))
            raise ValueError(f"Unknown function(s): {', '.join(unknown)}")
        return mapping

    def link_job_functions(self, job_id: int, names: List[str]) -> None:
        """
        Create job->function mappings for the given function names.
        """
        if not names:
            return
        ph = ",".join(["%s"] * len(names))
        self.cursor.execute(
            """
            INSERT IGNORE INTO nvflare_job_functions (job_id, function_id)
            SELECT %s AS job_id, df.id
            FROM defined_functions df
            WHERE df.name IN (""" + ph + ")",
            [job_id] + names,
        )

    def get_or_create_function_config_property_id(self, function_id: int, prop: str, val: str) -> int:
        """
        Upsert a (function_id, property_name, property_value) property row and return its id.
        """
        self.cursor.execute(
            """
            SELECT id
            FROM defined_function_config_properties
            WHERE function_id = %s AND property_name = %s AND property_value = %s
            LIMIT 1
            """,
            (function_id, prop, val),
        )
        row = self.cursor.fetchone()
        if row:
            return int(row["id"])
        try:
            self.cursor.execute(
                """
                INSERT INTO defined_function_config_properties
                    (function_id, property_name, property_value)
                VALUES (%s, %s, %s)
                """,
                (function_id, prop, val),
            )
            return int(self.cursor.lastrowid)
        except MySQLdb.IntegrityError:
            self.cursor.execute(
                """
                SELECT id
                FROM defined_function_config_properties
                WHERE function_id = %s AND property_name = %s AND property_value = %s
                LIMIT 1
                """,
                (function_id, prop, val),
            )
            row = self.cursor.fetchone()
            if row:
                return int(row["id"])
            raise

    def _compute_config_hash(self, function_id: int, props: Dict[str, str]) -> str:
        """
        Compute a deterministic hash for a function's config set based on property key/value pairs.
        """
        items = sorted(props.items(), key=lambda kv: kv[0])
        payload = f"{function_id}|" + "|".join(f"{k}={v}" for k, v in items)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_or_create_function_config_set_id(self, function_id: int, props: Dict[str, str]) -> int:
        """
        Upsert a function config set (function_id + config_hash) and its member properties, returning the set id.
        """
        if not props:
            raise ValueError("Config set properties cannot be empty.")
        cfg_hash = self._compute_config_hash(function_id, props)

        self.cursor.execute(
            """
            SELECT id
            FROM defined_function_config_sets
            WHERE function_id = %s AND config_hash = %s
            LIMIT 1
            """,
            (function_id, cfg_hash),
        )
        row = self.cursor.fetchone()
        if row:
            return int(row["id"])

        prop_ids: List[int] = []
        for prop, val in props.items():
            pid = self.get_or_create_function_config_property_id(function_id, prop, val)
            prop_ids.append(pid)

        self.cursor.execute(
            """
            INSERT INTO defined_function_config_sets (function_id, config_hash)
            VALUES (%s, %s)
            """,
            (function_id, cfg_hash),
        )
        set_id = int(self.cursor.lastrowid)

        if prop_ids:
            values_clause = ",".join(["(%s,%s)"] * len(prop_ids))
            params: List[int] = []
            for pid in prop_ids:
                params.extend([set_id, pid])
            self.cursor.execute(
                "INSERT IGNORE INTO defined_function_config_set_members (config_set_id, config_id) VALUES "
                + values_clause,
                params,
            )

        return set_id

    def ensure_configs_and_link(self, job_id: int, functions_map: Mapping[str, List[Mapping[str, Any]]]) -> None:
        """
        For each function in functions_map, ensure all config sets exist, then
        bulk-insert job->function_config_set rows into nvflare_job_function_configs.

        Expected shape:
            functions_map = {
                "SURVIVAL_ANALYSIS": [ {prop: value}, {prop: value}, ... ],
                "CHI_SQUARE_TEST":        [ {prop: value}, ... ],
                ...
            }
        """
        if not functions_map:
            return

        names = list(functions_map.keys())
        fn_ids_by_name = self.ensure_functions_exist(names)

        pairs: List[int] = []

        for fn_name, cfg_list in functions_map.items():
            fn_id = fn_ids_by_name[fn_name]

            if not isinstance(cfg_list, list):
                cfg_list = [cfg_list]  # defensive; normalize_map already gives lists

            for cfg in cfg_list:
                props = self._normalize_props(cfg or {})
                if not props:
                    continue
                cfg_set_id = self.get_or_create_function_config_set_id(fn_id, props)
                pairs.extend([job_id, cfg_set_id])

        if pairs:
            values_clause = ",".join(["(%s,%s,NULL)"] * (len(pairs) // 2))
            self.cursor.execute(
                "INSERT IGNORE INTO nvflare_job_function_configs (job_id, function_config_id, workflow_id) VALUES "
                + values_clause,
                pairs,
            )

    def ensure_job_function_config_row(
        self,
        job_id: int,
        function_name: str,
        props: Mapping[str, Any],
    ) -> int:
        """
        Ensure a job->function_config row exists for the given concrete property set.
        Returns the function_config_set id.
        """
        if not job_id:
            raise ValueError("job_id is required")

        fn_name = str(function_name or "").strip().upper()
        if not fn_name:
            raise ValueError("function_name is required")

        normalized_props = self._normalize_props(props or {})
        if not normalized_props:
            raise ValueError("Config set properties cannot be empty.")

        fn_ids_by_name = self.ensure_functions_exist([fn_name])
        fn_id = fn_ids_by_name[fn_name]
        cfg_set_id = self.get_or_create_function_config_set_id(fn_id, normalized_props)

        self.cursor.execute(
            """
            INSERT IGNORE INTO nvflare_job_function_configs (job_id, function_config_id, workflow_id)
            VALUES (%s, %s, NULL)
            """,
            (job_id, cfg_set_id),
        )
        self.connection.commit()
        return cfg_set_id

    def fetch_job_functions(self, job_ids: List[int]) -> Dict[int, Set[str]]:
        """
        Return job_id -> set(function_name) for the given job ids.
        """
        if not job_ids:
            return {}
        ph = ",".join(["%s"] * len(job_ids))
        self.cursor.execute(
            """
            SELECT njf.job_id, df.name AS function_name
            FROM nvflare_job_functions njf
            JOIN defined_functions df ON df.id = njf.function_id
            WHERE njf.job_id IN (""" + ph + ")",
            job_ids,
        )
        out: Dict[int, Set[str]] = {jid: set() for jid in job_ids}
        for r in self.cursor.fetchall():
            out.setdefault(r["job_id"], set()).add(r["function_name"])
        return out

    def fetch_job_function_configs(self, job_ids: List[int]) -> Dict[int, Dict[str, List[Dict[str, str]]]]:
        """
        Return job_id -> function_name -> [ {prop: value}, ... ] for the given job ids.
        Each dict in the list represents a single config set for that function within the job.
        """
        if not job_ids:
            return {}
        ph = ",".join(["%s"] * len(job_ids))
        self.cursor.execute(
            """
            SELECT
                njfc.job_id,
                df.name AS function_name,
                dfcs.id AS config_set_id,
                dfcp.property_name,
                dfcp.property_value
            FROM nvflare_job_function_configs njfc
            JOIN defined_function_config_sets dfcs
                ON dfcs.id = njfc.function_config_id
            JOIN defined_functions df
                ON df.id = dfcs.function_id
            JOIN defined_function_config_set_members dfcsm
                ON dfcsm.config_set_id = dfcs.id
            JOIN defined_function_config_properties dfcp
                ON dfcp.id = dfcsm.config_id
            WHERE njfc.job_id IN (""" + ph + ")",
            job_ids,
        )

        tmp: Dict[int, Dict[str, Dict[int, Dict[str, str]]]] = {jid: {} for jid in job_ids}
        rows = self.cursor.fetchall()
        for r in rows:
            j = r["job_id"]
            fn = r["function_name"]
            cfg_id = r["config_set_id"]
            prop_name = r["property_name"]
            prop_value = r["property_value"]
            fn_map = tmp.setdefault(j, {}).setdefault(fn, {})
            props_map = fn_map.setdefault(cfg_id, {})
            props_map[prop_name] = prop_value

        out: Dict[int, Dict[str, List[Dict[str, str]]]] = {}
        for job_id, fn_map in tmp.items():
            fn_out: Dict[str, List[Dict[str, str]]] = {}
            for fn_name, cfgs in fn_map.items():
                fn_out[fn_name] = list(cfgs.values())
            out[job_id] = fn_out

        return out



# Returns a new dict[str, dict[str, str]] with missing fields given their default (from SupportedFunction).
def _normalize_functions_map(functions: dict) -> dict:
    if not isinstance(functions, dict):
        raise ValueError("functions must be an object mapping function_id -> { args } or [ { args } ]")

    out: dict[str, list[dict[str, object]]] = {}

    for fn_id, raw_args in functions.items():
        fn_key_raw = str(fn_id)
        fn_key = fn_key_raw.strip().upper()
        fn_enum = SupportedFunction.from_name(fn_key)
        if fn_enum is not None:
            fn_key = str(fn_enum)

        # Normalize into a list of dicts, even if caller passed a single dict.
        cfg_list: list[dict] = []
        if isinstance(raw_args, list):
            for cfg in raw_args:
                if isinstance(cfg, dict):
                    cfg_list.append(cfg)
        elif isinstance(raw_args, dict):
            cfg_list.append(raw_args)
        else:
            cfg_list.append({})

        defaults = FUNCTION_DEFAULT_PROPERTIES.get(fn_enum, {}) if fn_enum else {}
        # Build a {prop_name: declared_type} view once per function so we can decide whether
        # a value should be coerced to int/float/bool or stringified. Without a declared type
        # we fall back to legacy string semantics so existing payloads keep working.
        prop_types = FUNCTION_PROPERTY_TYPES.get(fn_enum, {}) if fn_enum else {}
        normalized_cfgs: list[dict[str, object]] = []

        for cfg in cfg_list:
            normalized: dict[str, object] = {}

            # Copy provided args. For properties declared as int/float/bool in
            # FUNCTION_PROPERTY_TYPES, coerce the value so downstream consumers (NVFlare
            # workflow_args, persistor validation, in-job arithmetic) see real numbers/bools.
            # Properties with no declared type, or where coercion fails, are stringified to
            # preserve the previous behavior.
            for k, v in cfg.items():
                key = str(k)
                if v is None:
                    normalized[key] = ""
                    continue
                declared = prop_types.get(key)
                coerced = SupportedFunction.coerce_value_for_type(declared, v) if declared else v
                if isinstance(coerced, (bool, int, float)) and not isinstance(coerced, str):
                    normalized[key] = coerced
                else:
                    normalized[key] = str(coerced) if coerced is not None else ""

            # Backfill defaults for known args if missing/blank. Defaults in
            # FUNCTION_DEFAULT_PROPERTIES are stringified at definition time; coerce them
            # through the same path so a default for a `"float"` field lands as 0.1, not "0.1".
            for k, default_value in defaults.items():
                cur = normalized.get(k)
                missing = cur is None or (isinstance(cur, str) and cur.strip() == "")
                if missing:
                    declared = prop_types.get(k)
                    coerced = SupportedFunction.coerce_value_for_type(declared, default_value) if declared else default_value
                    if isinstance(coerced, (bool, int, float)) and not isinstance(coerced, str):
                        normalized[k] = coerced
                    else:
                        normalized[k] = str(coerced) if coerced is not None else ""

            # enum clamp for std_type on STANDARD_DEVIATION
            if fn_enum is SupportedFunction.STANDARD_DEVIATION:
                options = ["sample", "population"]
                default_std = str(defaults.get("std_type", "sample"))
                current = str(normalized.get("std_type", "")).strip()
                if not current:
                    normalized["std_type"] = default_std
                elif current not in options:
                    normalized["std_type"] = default_std

            normalized_cfgs.append(normalized)

        if normalized_cfgs:
            out[fn_key] = normalized_cfgs

    return out