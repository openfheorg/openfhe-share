# Collect a snapshot of NVFlare clients using fl_admin.sh (no SSH).
# Runs "check_status server" via NVFlareAdminKitManager and parses the output table
# into a list of {"client_name", "last_connect_time"} dicts. Then merges in any
# clients registered in MySQL but not present in NVFlare's list (marked with "0").
#
# Initiator status is always resolved from MySQL for all clients:
#   {"is_initiator": True}
#
# If a username is supplied, any client rows associated with that username will also include:
#   {"is_submitted_user": True}

import re
import traceback
from typing import Optional, Set

from app.core.mysql.SupportedFunction import SupportedFunction
from app.core.mysql.managers.ParticipationManager import ParticipationManager
from app.core.nvflare.NVFlareAdminKitManager import NVFlareAdminKitManager

CHECK_STATUS_TIMEOUT_SECONDS = 20
SERVER_CLIENT_NAME = "Server"

# CLIENT | FQCN | FQSN | LEAF | TOKEN | LAST CONNECT TIME
CLIENT_ROW_RE = re.compile(
    r"^\|\s*([^\|]+?)\s*\|"   # CLIENT
    r"\s*([^\|]+?)\s*\|"      # FQCN
    r"\s*([^\|]+?)\s*\|"      # FQSN
    r"\s*([^\|]+?)\s*\|"      # LEAF
    r"\s*([^\|]+?)\s*\|"      # TOKEN
    r"\s*([^\|]+?)\s*\|"      # LAST CONNECT TIME
    r"$"
)


class NVFlareClientSnapshot:
    def __init__(self):
        self._admin_mgr = NVFlareAdminKitManager()

    def get_clients(self, username: Optional[str] = None):
        code = None
        output = ""
        server_error = None

        # Execute "check_status server" through fl_admin.sh
        try:
            code, output = self._admin_mgr.run(
                commands=["check_status server"],
                timeout=CHECK_STATUS_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            server_error = str(exc)
            print(
                f"NVFlareClientSnapshot: check_status server failed: {traceback.format_exc().splitlines()}",
                flush=True,
            )

        # Parse whatever we got; if fl_admin returned non-zero but still printed a table,
        # we can still recover useful data.
        clients = self._parse_clients(output or "")
        server_online = code == 0
        server_entry = {
            "client_name": SERVER_CLIENT_NAME,
            "last_connect_time": "SERVER_ONLINE" if server_online else "0",
            "registered": False,
            "is_server": True,
            "server_online": server_online,
        }
        if server_error:
            server_entry["connection_error"] = server_error
        elif not server_online:
            server_entry["connection_error"] = "NVFlare server status could not be resolved."

        # Merge in any clients registered in MySQL that aren't present in NVFlare output.
        # Initiator status is always checked for all clients.
        # If a username was supplied, also mark any matching client rows as submitted-user rows.
        pm = ParticipationManager()
        try:
            roster = pm.clients_list() or []
            mysql_names = {r["client_name"].strip() for r in roster if r.get("client_name")}

            initiator_client_names: Set[str] = pm.get_all_initiator_client_names()
            submitted_user_client_names: Set[str] = set()

            if username:
                submitted_user_client_names = pm.get_client_names_for_username(username)
        finally:
            pm.complete()

        clients.insert(0, server_entry)

        # Mark any matching live NVFlare entries.
        for client in clients:
            if client.get("is_server"):
                continue
            client_name = client["client_name"]
            client["registered"] = client_name in mysql_names
            if client_name in initiator_client_names:
                client["is_initiator"] = True
            if client_name in submitted_user_client_names:
                client["is_submitted_user"] = True

        # Add MySQL-registered clients missing from NVFlare output, marked with "0".
        nv_names = {c["client_name"] for c in clients if not c.get("is_server")}
        for name in sorted(mysql_names - nv_names):
            entry = {
                "client_name": name,
                "last_connect_time": "0",
                "registered": True,
            }
            if name in initiator_client_names:
                entry["is_initiator"] = True
            if name in submitted_user_client_names:
                entry["is_submitted_user"] = True
            clients.append(entry)

        return clients

    def _parse_clients(self, text: str):
        # Parse the tabular output from NVFlare `check_status server`
        clients = []
        for ln in text.splitlines():
            m = CLIENT_ROW_RE.match(ln.strip())
            if m and m.group(1).strip().lower() != "client":
                name = m.group(1).strip()
                last = m.group(6).strip()
                clients.append({"client_name": name, "last_connect_time": last})
        return clients
