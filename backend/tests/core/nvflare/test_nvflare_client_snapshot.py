from unittest.mock import Mock, patch

from app.core.nvflare.NVFlareClientSnapshot import NVFlareClientSnapshot


TABLE = """
| CLIENT | FQCN | FQSN | LEAF | TOKEN | LAST CONNECT TIME |
| site1 | site1 | site1 | True | abc | 2026-07-18 12:00:00 |
| site2 | site2 | site2 | True | def | 2026-07-18 12:01:00 |
"""


def _snapshot_without_init():
    value = object.__new__(NVFlareClientSnapshot)
    value._admin_mgr = Mock()
    return value


def test_parse_clients_ignores_header_and_extracts_values():
    snapshot = _snapshot_without_init()
    assert snapshot._parse_clients(TABLE) == [
        {"client_name": "site1", "last_connect_time": "2026-07-18 12:00:00"},
        {"client_name": "site2", "last_connect_time": "2026-07-18 12:01:00"},
    ]


def test_get_clients_merges_mysql_roster_and_flags():
    snapshot = _snapshot_without_init()
    snapshot._admin_mgr.run.return_value = (0, TABLE)
    manager = Mock()
    manager.clients_list.return_value = [
        {"client_name": "site1"},
        {"client_name": "site3"},
    ]
    manager.get_all_initiator_client_names.return_value = {"site3"}
    manager.get_client_names_for_username.return_value = {"site1"}

    with patch(
        "app.core.nvflare.NVFlareClientSnapshot.ParticipationManager",
        return_value=manager,
    ):
        clients = snapshot.get_clients(username="evan")

    assert clients[0]["is_server"] is True
    assert clients[0]["server_online"] is True
    site1 = next(row for row in clients if row.get("client_name") == "site1")
    site2 = next(row for row in clients if row.get("client_name") == "site2")
    site3 = next(row for row in clients if row.get("client_name") == "site3")
    assert site1["registered"] is True
    assert site1["is_submitted_user"] is True
    assert site2["registered"] is False
    assert site3["last_connect_time"] == "0"
    assert site3["is_initiator"] is True
    manager.complete.assert_called_once()


def test_get_clients_reports_server_error_but_keeps_registered_clients():
    snapshot = _snapshot_without_init()
    snapshot._admin_mgr.run.side_effect = RuntimeError("offline")
    manager = Mock()
    manager.clients_list.return_value = [{"client_name": "site4"}]
    manager.get_all_initiator_client_names.return_value = set()

    with patch(
        "app.core.nvflare.NVFlareClientSnapshot.ParticipationManager",
        return_value=manager,
    ):
        clients = snapshot.get_clients()

    assert clients[0]["server_online"] is False
    assert clients[0]["connection_error"] == "offline"
    assert clients[1]["client_name"] == "site4"
