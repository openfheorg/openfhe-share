"""
ParticipationManager

Overview
--------
Client participation is modeled as:

    nvflare_client_participation (header)
      1 ──< N nvflare_client_participation_functions (function mapping)
      1 ──< N nvflare_client_participation_function_configs (function-config mapping via defined_function_config_sets)

Key points:
- A participation agreement is identified by (client_id, filter_id).
- An optional threshold_config_id links to a threshold configuration for that agreement.
- The stored function set and each function's accepted config sets define the agreement.
- Confirmation (ACCEPT/REJECT) applies to the entire set.

Read rule (used everywhere):
- A participation matches a request iff:
  - its mapped function set includes ALL requested function names,
  - for each requested function, at least one of its mapped config sets includes ALL requested (property_name, property_value) pairs
    (order-agnostic; extra functions/configs are allowed), and
  - if a threshold is provided in the query, the participation row has the same threshold_config_id. If the threshold
    configuration does not exist in the DB, no participation matches.

Write rule:
- record_participation(...) upserts the header row and synchronizes both mappings so the stored sets exactly match
  what was provided. When a threshold is supplied, it is stored and linked via threshold_config_id.

Offline handling:
- Optional: exclude offline clients using a snapshot where last_connect_time == 0 or "0".
"""

from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Tuple, Set, Any

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.managers.FunctionsManager import FunctionsManager
from app.core.mysql.managers.ThresholdManager import Threshold, ThresholdManager


class Confirmation(str, Enum):
    PENDING = "PENDING"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"

    def __str__(self):
        return self.value


class ParticipationManager:
    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def clients_list(self):
        self.cursor.execute(
            f"SELECT client_name FROM {MySQLTable.CLIENTS} ORDER BY client_name"
        )
        return self.cursor.fetchall()

    @staticmethod
    def _is_server_client_name(client_name: Any) -> bool:
        return str(client_name or "").strip().lower() == "server"

    @classmethod
    def _is_server_snapshot_entry(cls, entry: Any) -> bool:
        if not isinstance(entry, Mapping):
            return False
        return bool(entry.get("is_server")) or cls._is_server_client_name(
            entry.get("client_name") or entry.get("name")
        )

    def resolve_client_id(self, client_name: str) -> int | None:
        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.CLIENTS}
            WHERE client_name = %s
            LIMIT 1
            """,
            (client_name,),
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def _normalize_map_for_participation(
        self,
        functions: Mapping[str, Any],
    ) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}

        for fn, raw_cfgs in (functions or {}).items():
            fn_name = str(fn).strip().upper()
            if not fn_name:
                continue

            merged: Dict[str, str] = {}

            if isinstance(raw_cfgs, Mapping):
                cfg_iter: Iterable[Mapping[str, Any]] = [raw_cfgs]
            elif isinstance(raw_cfgs, list):
                cfg_iter = [c for c in raw_cfgs if isinstance(c, Mapping)]
            else:
                cfg_iter = []

            for cfg in cfg_iter:
                for k, v in cfg.items():
                    key = str(k).strip()
                    if not key:
                        continue
                    merged[key] = "" if v is None else str(v)

            if merged:
                out[fn_name] = merged

        return out

    def _persist_threshold_if_needed(self, threshold: Threshold | None) -> Optional[int]:
        if threshold is None:
            return None
        if threshold.id is not None:
            return threshold.id
        tm = ThresholdManager()
        try:
            persisted = tm.get_or_create(threshold)
        finally:
            tm.complete()
        return persisted.id

    def record_participation(
        self,
        client_name: str,
        filter_id: int,
        functions_map: Mapping[str, Any],
        confirmation: Confirmation,
        threshold: Threshold | None = None,
        contributing_party: bool | None = None,
        analyzing_party: bool | None = None,
    ) -> Optional[int]:
        if self._is_server_client_name(client_name):
            return None

        client_id = self.resolve_client_id(client_name)
        if not client_id:
            raise ValueError(f"Unknown client_name: {client_name}")

        fn_map = self._normalize_map_for_participation(functions_map)
        if not fn_map:
            raise ValueError("functions must contain at least one function")

        threshold_config_id = self._persist_threshold_if_needed(threshold)

        contributing_party_value = 1 if contributing_party is None else (1 if contributing_party else 0)
        analyzing_party_value = 1 if analyzing_party is None else (1 if analyzing_party else 0)

        fm = FunctionsManager()
        try:
            self.cursor.execute(
                f"""
                INSERT INTO {MySQLTable.PARTICIPATION} (client_id, filter_id, confirmation, threshold_config_id, contributing_party, analyzing_party)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    confirmation = VALUES(confirmation),
                    threshold_config_id = VALUES(threshold_config_id),
                    contributing_party = IF(%s IS NULL, contributing_party, VALUES(contributing_party)),
                    analyzing_party = IF(%s IS NULL, analyzing_party, VALUES(analyzing_party)),
                    id = LAST_INSERT_ID(id)
                """,
                (
                    client_id,
                    filter_id,
                    confirmation.value,
                    threshold_config_id,
                    contributing_party_value,
                    analyzing_party_value,
                    contributing_party,
                    analyzing_party,
                ),
            )
            participation_id = self.cursor.lastrowid

            fn_ids_by_name = fm.get_function_ids_by_names(list(fn_map.keys()))
            if len(fn_ids_by_name) != len(fn_map):
                unknown = sorted(set(fn_map.keys()) - set(fn_ids_by_name.keys()))
                raise ValueError(f"Unknown function(s): {', '.join(unknown)}")

            desired_fn_ids = sorted(fn_ids_by_name.values())
            if desired_fn_ids:
                placeholders = ",".join(["%s"] * len(desired_fn_ids))
                self.cursor.execute(
                    f"""
                    DELETE pf FROM {MySQLTable.PARTICIPATION_FUNCTIONS} pf
                    WHERE pf.participation_id = %s
                      AND pf.function_id NOT IN ({placeholders})
                    """,
                    [participation_id] + desired_fn_ids,
                )
                self.cursor.execute(
                    f"""
                    INSERT IGNORE INTO {MySQLTable.PARTICIPATION_FUNCTIONS} (participation_id, function_id)
                    SELECT %s AS participation_id, df.id
                    FROM {MySQLTable.FUNCTIONS} df
                    WHERE df.id IN ({placeholders})
                    """,
                    [participation_id] + desired_fn_ids,
                )
            else:
                self.cursor.execute(
                    f"DELETE FROM {MySQLTable.PARTICIPATION_FUNCTIONS} WHERE participation_id = %s",
                    (participation_id,),
                )

            desired_cfg_set_ids: List[int] = []
            for fn_name, merged_props in fn_map.items():
                fn_id = fn_ids_by_name[fn_name]
                props = fm._normalize_props(merged_props or {})
                if not props:
                    continue
                cfg_set_id = fm.get_or_create_function_config_set_id(fn_id, props)
                desired_cfg_set_ids.append(cfg_set_id)

            if desired_cfg_set_ids:
                ph = ",".join(["%s"] * len(desired_cfg_set_ids))
                self.cursor.execute(
                    f"""
                    DELETE FROM {MySQLTable.PARTICIPATION_FUNCTION_CONFIGS}
                    WHERE participation_id = %s
                      AND function_config_id NOT IN (""" + ph + ")",
                    [participation_id] + desired_cfg_set_ids,
                )
                values_clause = ",".join(["(%s,%s)"] * len(desired_cfg_set_ids))
                params: List[int] = []
                for cfg_id in desired_cfg_set_ids:
                    params.extend([participation_id, cfg_id])
                self.cursor.execute(
                    f"""
                    INSERT IGNORE INTO {MySQLTable.PARTICIPATION_FUNCTION_CONFIGS}
                        (participation_id, function_config_id)
                    VALUES """ + values_clause,
                    params,
                )
            else:
                self.cursor.execute(
                    f"DELETE FROM {MySQLTable.PARTICIPATION_FUNCTION_CONFIGS} WHERE participation_id = %s",
                    (participation_id,),
                )

            self.connection.commit()
            return participation_id

        except Exception:
            self.connection.rollback()
            raise
        finally:
            fm.complete()

    def record_pending_participation(
        self,
        client_name: str,
        filter_id: int,
        functions_map: Mapping[str, Any],
        contributing_party: bool,
        analyzing_party: bool,
        threshold: Threshold | None = None,
    ) -> Optional[int]:
        return self.record_participation(
            client_name=client_name,
            filter_id=filter_id,
            functions_map=functions_map,
            confirmation=Confirmation.PENDING,
            threshold=threshold,
            contributing_party=contributing_party,
            analyzing_party=analyzing_party,
        )

    def _candidates_by_functions_only(
        self,
        fn_names: Iterable[str],
        filter_id: int,
        confirmation: Confirmation | None,
        exclude_names: Iterable[str] | None,
        threshold_config_id: int | None,
    ) -> List[dict]:
        names = sorted(
            {str(n).strip().upper() for n in (fn_names or []) if str(n).strip()}
        )
        if not names:
            return []

        n = len(names)
        params: list = [filter_id]
        placeholders = ",".join(["%s"] * n)

        sql = f"""
            SELECT c.client_name,
                   p.id AS participation_id,
                   p.confirmation,
                   p.threshold_config_id,
                   p.contributing_party,
                   p.analyzing_party
            FROM {MySQLTable.CLIENTS} c
            JOIN {MySQLTable.PARTICIPATION} p
              ON p.client_id = c.id AND p.filter_id = %s
            JOIN {MySQLTable.PARTICIPATION_FUNCTIONS} pf
              ON pf.participation_id = p.id
            JOIN {MySQLTable.FUNCTIONS} df
              ON df.id = pf.function_id
        """

        where = [f"df.name IN ({placeholders})"]
        params.extend(names)

        if confirmation:
            where.append("p.confirmation = %s")
            params.append(confirmation.value)

        if threshold_config_id is not None:
            where.append("p.threshold_config_id = %s")
            params.append(threshold_config_id)

        if exclude_names:
            ex = sorted({n for n in exclude_names if n})
            if ex:
                where.append(
                    f"c.client_name NOT IN ({','.join(['%s']*len(ex))})"
                )
                params.extend(ex)

        sql += " WHERE " + " AND ".join(where)

        sql += f"""
            GROUP BY c.client_name, p.id, p.confirmation, p.threshold_config_id, p.contributing_party, p.analyzing_party
            HAVING COUNT(DISTINCT df.name) = %s
            ORDER BY c.client_name
        """
        params.append(n)

        self.cursor.execute(sql, tuple(params))
        return self.cursor.fetchall()

    def _configs_match_for_participation(
        self,
        participation_id: int,
        fn_name: str,
        required_pairs: Mapping[str, str] | dict,
    ) -> bool:
        pairs = [(str(k), str(v)) for k, v in (required_pairs or {}).items()]
        if not pairs:
            return True

        matching_sets: Optional[Set[int]] = None

        for (prop, val) in pairs:
            self.cursor.execute(
                f"""
                SELECT DISTINCT dfcs.id AS config_set_id
                FROM {MySQLTable.PARTICIPATION_FUNCTION_CONFIGS} pfc
                JOIN {MySQLTable.FUNCTION_CONFIG_SETS} dfcs
                  ON dfcs.id = pfc.function_config_id
                JOIN {MySQLTable.FUNCTIONS} df
                  ON df.id = dfcs.function_id
                JOIN {MySQLTable.FUNCTION_CONFIG_SET_MEMBERS} dfcsm
                  ON dfcsm.config_set_id = dfcs.id
                JOIN {MySQLTable.FUNCTION_CONFIG_PROPERTIES} dfcp
                  ON dfcp.id = dfcsm.config_id
                WHERE pfc.participation_id = %s
                  AND df.name = %s
                  AND dfcp.property_name = %s
                  AND dfcp.property_value = %s
                """,
                (participation_id, fn_name, prop, val),
            )
            rows = self.cursor.fetchall()
            ids = {int(r["config_set_id"]) for r in rows}
            if matching_sets is None:
                matching_sets = ids
            else:
                matching_sets &= ids
            if not matching_sets:
                return False

        return bool(matching_sets)

    @staticmethod
    def _config_pair(prop: Any, val: Any) -> Tuple[str, str]:
        # property_name/property_value live under a case-insensitive collation, so the
        # stored row can differ in case from what was submitted (the unique key means
        # only one casing is ever stored). Fold both sides before comparing in Python.
        return (str(prop).strip().casefold(), str(val).strip().casefold())

    def _matching_participation_ids_by_configs(
        self,
        participation_ids: Iterable[int],
        fn_map: Mapping[str, Mapping[str, str]],
    ) -> Set[int]:
        ids = sorted({int(pid) for pid in participation_ids})
        if not ids:
            return set()

        required_by_fn: Dict[str, Set[Tuple[str, str]]] = {}
        for fn_name, pairs in (fn_map or {}).items():
            normalized_pairs = {
                self._config_pair(k, v)
                for k, v in (pairs or {}).items()
            }
            if normalized_pairs:
                required_by_fn[str(fn_name).strip().upper()] = normalized_pairs

        if not required_by_fn:
            return set(ids)

        pair_conditions = []
        pair_params: list = []

        for fn_name in sorted(required_by_fn.keys()):
            fn_pair_conditions = []
            fn_pair_params: list = []
            for prop, val in sorted(required_by_fn[fn_name]):
                fn_pair_conditions.append("(dfcp.property_name = %s AND dfcp.property_value = %s)")
                fn_pair_params.extend([prop, val])
            pair_conditions.append(
                f"(df.name = %s AND ({' OR '.join(fn_pair_conditions)}))"
            )
            pair_params.append(fn_name)
            pair_params.extend(fn_pair_params)

        id_placeholders = ",".join(["%s"] * len(ids))
        pair_where = " OR ".join(pair_conditions)

        sql = f"""
            SELECT pfc.participation_id,
                   df.name AS function_name,
                   dfcs.id AS config_set_id,
                   dfcp.property_name,
                   dfcp.property_value
            FROM {MySQLTable.PARTICIPATION_FUNCTION_CONFIGS} pfc
            JOIN {MySQLTable.FUNCTION_CONFIG_SETS} dfcs
              ON dfcs.id = pfc.function_config_id
            JOIN {MySQLTable.FUNCTIONS} df
              ON df.id = dfcs.function_id
            JOIN {MySQLTable.FUNCTION_CONFIG_SET_MEMBERS} dfcsm
              ON dfcsm.config_set_id = dfcs.id
            JOIN {MySQLTable.FUNCTION_CONFIG_PROPERTIES} dfcp
              ON dfcp.id = dfcsm.config_id
            WHERE pfc.participation_id IN ({id_placeholders})
              AND ({pair_where})
        """

        self.cursor.execute(sql, tuple(ids + pair_params))
        rows = self.cursor.fetchall()

        matched_pairs_by_config: Dict[Tuple[int, str, int], Set[Tuple[str, str]]] = {}
        for row in rows:
            pid = int(row["participation_id"])
            fn_name = str(row["function_name"]).strip().upper()
            config_set_id = int(row["config_set_id"])
            pair = self._config_pair(row["property_name"], row["property_value"])
            matched_pairs_by_config.setdefault((pid, fn_name, config_set_id), set()).add(pair)

        matched_functions_by_participation: Dict[int, Set[str]] = {}
        for (pid, fn_name, _), matched_pairs in matched_pairs_by_config.items():
            required_pairs = required_by_fn.get(fn_name)
            if required_pairs and required_pairs.issubset(matched_pairs):
                matched_functions_by_participation.setdefault(pid, set()).add(fn_name)

        required_functions = set(required_by_fn.keys())
        return {
            pid
            for pid, matched_functions in matched_functions_by_participation.items()
            if required_functions.issubset(matched_functions)
        }

    def list_client_participation_status(
        self,
        functions: Mapping[str, Any],
        filter_id: int,
        confirmation: Confirmation | None = None,
        clients_snapshot: list[dict] | None = None,
        threshold: Threshold | None = None,
    ) -> list[dict]:
        fn_map = self._normalize_map_for_participation(functions)
        if not fn_map:
            return []

        exclude = set()
        if clients_snapshot:
            for e in clients_snapshot:
                if self._is_server_snapshot_entry(e):
                    continue
                name = (e.get("client_name") or e.get("name") or "").strip()
                lo = e.get(
                    "last_online",
                    e.get("last_connect_time", e.get("lastConnect")),
                )
                if name and (lo == 0 or (isinstance(lo, str) and lo.strip() == "0")):
                    exclude.add(name)

        threshold_config_id: int | None = None
        if threshold is not None:
            tm = ThresholdManager()
            try:
                existing = tm.get_if_exists(threshold)
            finally:
                tm.complete()

            if not existing:
                return []
            threshold_config_id = existing.id

        candidates = self._candidates_by_functions_only(
            fn_names=fn_map.keys(),
            filter_id=filter_id,
            confirmation=confirmation,
            exclude_names=exclude,
            threshold_config_id=threshold_config_id,
        )
        if not candidates:
            return []

        matching_ids = self._matching_participation_ids_by_configs(
            participation_ids=[int(row["participation_id"]) for row in candidates],
            fn_map=fn_map,
        )
        if not matching_ids:
            return []

        out: list[dict] = []
        for row in candidates:
            if int(row["participation_id"]) in matching_ids:
                out.append(
                    {
                        "client_name": row["client_name"],
                        "confirmation": row["confirmation"],
                        "threshold_config_id": row["threshold_config_id"],
                        "contributing_party": bool(row["contributing_party"]),
                        "analyzing_party": bool(row["analyzing_party"]),
                    }
                )
        return out

    def list_clients_with_accepted_participation_csv(
        self,
        functions: Mapping[str, Any],
        filter_id: int,
        clients_snapshot,
        threshold: Threshold | None = None,
    ) -> str:
        rows = self.list_client_participation_status(
            functions=functions,
            filter_id=filter_id,
            confirmation=Confirmation.ACCEPT,
            clients_snapshot=clients_snapshot,
            threshold=threshold,
        )
        return ",".join([row["client_name"] for row in rows])

    def list_clients_without_participation_csv(
        self,
        functions: Mapping[str, Any],
        filter_id: int,
        clients_snapshot,
        threshold: Threshold | None = None,
    ) -> str:
        snapshot_names = {
            c["client_name"]
            for c in (clients_snapshot or [])
            if not self._is_server_snapshot_entry(c)
            and c.get("last_connect_time")
            and str(c["last_connect_time"]).strip() != "0"
        }
        satisfied = {
            r["client_name"]
            for r in self.list_client_participation_status(
                functions=functions,
                filter_id=filter_id,
                confirmation=None,
                clients_snapshot=None,
                threshold=threshold,
            )
        }
        missing = sorted(snapshot_names - satisfied)
        return ",".join(missing)
    

    def get_all_initiator_client_names(self) -> set[str]:
        # Resolve all NVFlare client names associated with INITIATOR users.
        sql = f"""
            SELECT DISTINCT nc.client_name
            FROM users u
            INNER JOIN defined_roles r
                ON r.id = u.role_id
            INNER JOIN {MySQLTable.CLIENTS} nc
                ON nc.user_id = u.id
            WHERE UPPER(r.name) = 'INITIATOR'
            ORDER BY nc.client_name
        """
        print(f"ParticipationManager.get_all_initiator_client_names: sql={sql}", flush=True)

        self.cursor.execute(sql)
        rows = self.cursor.fetchall()
        print(f"ParticipationManager.get_all_initiator_client_names: rows={rows}", flush=True)

        result = {
            row["client_name"].strip()
            for row in rows
            if row.get("client_name")
        }
        print(f"ParticipationManager.get_all_initiator_client_names: result={result}", flush=True)
        return result
    

    def get_client_names_for_username(self, username: str) -> set[str]:
        # Resolve all NVFlare client names associated with the supplied username,
        # regardless of role.
        username = (username or "").strip()
        print(f"ParticipationManager.get_client_names_for_username: username={username}", flush=True)

        if not username:
            print("ParticipationManager.get_client_names_for_username: empty username", flush=True)
            return set()

        sql = f"""
            SELECT nc.client_name
            FROM users u
            INNER JOIN {MySQLTable.CLIENTS} nc
                ON nc.user_id = u.id
            WHERE u.username = %s
            ORDER BY nc.client_name
        """
        print(f"ParticipationManager.get_client_names_for_username: sql={sql}", flush=True)

        self.cursor.execute(sql, (username,))
        rows = self.cursor.fetchall()
        print(f"ParticipationManager.get_client_names_for_username: rows={rows}", flush=True)

        result = {
            row["client_name"].strip()
            for row in rows
            if row.get("client_name")
        }
        print(f"ParticipationManager.get_client_names_for_username: result={result}", flush=True)
        return result
    
    
    def auto_accept_participation_for_username(
        self,
        username: str,
        filter_id: int,
        functions_map: Mapping[str, Any],
        threshold: Threshold | None = None,
    ) -> str | None:
        username = (username or "").strip()
        print(f"ParticipationManager.auto_accept_participation_for_username: username={username}", flush=True)

        if not username:
            print("ParticipationManager.auto_accept_participation_for_username: empty username", flush=True)
            return None

        client_names = sorted(self.get_client_names_for_username(username))
        print(f"ParticipationManager.auto_accept_participation_for_username: client_names={client_names}", flush=True)

        if not client_names:
            print("ParticipationManager.auto_accept_participation_for_username: no client mapping found", flush=True)
            return None

        client_name = client_names[0]
        print(
            f"ParticipationManager.auto_accept_participation_for_username: auto-accepting client_name={client_name}",
            flush=True,
        )

        self.record_participation(
            client_name=client_name,
            filter_id=filter_id,
            functions_map=functions_map,
            confirmation=Confirmation.ACCEPT,
            threshold=threshold,
        )

        return client_name    
