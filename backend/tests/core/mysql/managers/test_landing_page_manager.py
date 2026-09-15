from unittest.mock import Mock

from app.core.mysql.managers.LandingPageManager import LandingPageManager


class QueueCursor:
    def __init__(self, fetchall_results=None, fetchone_results=None):
        self.fetchall_results = list(fetchall_results or [])
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.fetchall_results.pop(0)

    def fetchone(self):
        return self.fetchone_results.pop(0)


def test_get_home_summary_derives_full_totals_for_initiator():
    manager = LandingPageManager.__new__(LandingPageManager)
    manager.cursor = QueueCursor(
        fetchone_results=[{"role": "INITIATOR"}],
        fetchall_results=[
            [
                {"status": "FINISHED:COMPLETED", "job_count": 7},
                {"status": "RUNNING", "job_count": 2},
            ],
            [
                {"role_id": 1, "role": "CLIENT", "description": "Client", "user_count": 4},
                {"role_id": 2, "role": "INITIATOR", "description": "Initiator", "user_count": 1},
            ],
            [
                {"id": 1, "name": "MEAN", "description": "Mean"},
                {"id": 2, "name": "T_TEST", "description": "T test"},
            ],
        ],
    )

    result = manager.get_home_summary("initiator")

    assert result is not None
    assert result["total_jobs"] == 9
    assert result["total_users"] == 5
    assert result["total_functions"] == 2
    assert result["job_statuses"][0] == {
        "status": "FINISHED:COMPLETED",
        "count": 7,
    }
    assert result["user_roles"][1]["role"] == "INITIATOR"
    assert result["functions"][1]["name"] == "T_TEST"
    assert len(manager.cursor.executed) == 4
    assert manager.cursor.executed[0][1] == ("initiator",)


def test_get_home_summary_redacts_system_breakdowns_for_client():
    manager = LandingPageManager.__new__(LandingPageManager)
    manager.cursor = QueueCursor(
        fetchone_results=[
            {"role": "CLIENT"},
            {"total_jobs": 9},
        ],
        fetchall_results=[
            [
                {"id": 1, "name": "MEAN", "description": "Mean"},
                {"id": 2, "name": "T_TEST", "description": "T test"},
            ],
        ],
    )

    result = manager.get_home_summary("client")

    assert result == {
        "total_jobs": 9,
        "total_functions": 2,
        "functions": [
            {"id": 1, "name": "MEAN", "description": "Mean"},
            {"id": 2, "name": "T_TEST", "description": "T test"},
        ],
    }
    assert len(manager.cursor.executed) == 3


def test_get_home_summary_returns_none_for_unknown_user():
    manager = LandingPageManager.__new__(LandingPageManager)
    manager.cursor = QueueCursor(fetchone_results=[None])

    assert manager.get_home_summary("missing-user") is None
    assert len(manager.cursor.executed) == 1

def test_get_project_landing_summary_builds_landing_payload_from_summary_helpers():
    manager = LandingPageManager.__new__(LandingPageManager)
    manager.cursor = QueueCursor(
        fetchone_results=[
            {
                "id": 2,
                "name": "General Statistics",
                "description": "Federated stats",
                "status": "ACTIVE",
                "fixed": 1,
                "function_restrictions_enabled": 1,
                "model_file_settings_enabled": 0,
                "filter_system_id": 1,
                "filter_system": "DEFAULT",
                "total_jobs": 28,
                "registered_user_count": 3,
            }
        ]
    )
    manager._get_project_functions = Mock(
        return_value=[{"function_id": 1, "function": "MEAN", "configurable": False}]
    )
    manager._get_project_datasource_groups = Mock(
        return_value=[
            {"id": 10, "project_id": 2, "group_name": "MSKChord", "is_default": True},
            {"id": 11, "project_id": 2, "group_name": "PanelSplit", "is_default": False},
        ]
    )
    manager._get_recent_jobs = Mock(return_value=[{"id": 37, "status": "FINISHED:COMPLETED"}])
    manager._get_function_usage_distribution = Mock(
        return_value=[{"functions": ["MEAN"], "count": 28}]
    )

    result = manager.get_project_landing_summary(2)

    assert result is not None
    assert result["project"]["total_jobs"] == 28
    assert result["project"]["registered_user_count"] == 3
    assert result["project"]["datasource_groups_defined"] is True
    assert result["project"]["default_datasource_group"]["group_name"] == "MSKChord"
    assert result["project"]["function_count"] == 1
    assert result["recent_jobs"][0]["id"] == 37
    assert result["function_usage_distribution"] == [
        {"functions": ["MEAN"], "count": 28}
    ]
    manager._get_recent_jobs.assert_called_once_with(2, 5)
    manager._get_function_usage_distribution.assert_called_once_with(2)

def test_get_function_usage_distribution_counts_exact_function_sets_per_job():
    manager = LandingPageManager.__new__(LandingPageManager)
    manager.cursor = QueueCursor(
        fetchall_results=[
            [
                {"job_id": 1, "function_name": "SURVIVAL_ANALYSIS"},
                {"job_id": 1, "function_name": "CHI_SQUARE_TEST"},
                {"job_id": 2, "function_name": "MEAN"},
                {"job_id": 3, "function_name": "CHI_SQUARE_TEST"},
                {"job_id": 4, "function_name": "CHI_SQUARE_TEST"},
            ]
        ]
    )

    result = manager._get_function_usage_distribution(2)

    assert result == [
        {"functions": ["CHI_SQUARE_TEST"], "count": 2},
        {"functions": ["CHI_SQUARE_TEST", "SURVIVAL_ANALYSIS"], "count": 1},
        {"functions": ["MEAN"], "count": 1},
    ]
    assert manager.cursor.executed[0][1] == (2,)
    sql = manager.cursor.executed[0][0]
    assert "JOIN nvflare_job_functions" in sql
    assert "JOIN defined_functions" in sql
    assert "nvflare_job_function_configs" not in sql

def test_get_project_landing_summary_returns_none_for_unknown_project():
    manager = LandingPageManager.__new__(LandingPageManager)
    manager.cursor = QueueCursor(fetchone_results=[None])

    assert manager.get_project_landing_summary(404) is None
    assert len(manager.cursor.executed) == 1


def test_safe_json_object_accepts_dict_and_json_object_only():
    assert LandingPageManager._safe_json_object({"x": 1}) == {"x": 1}
    assert LandingPageManager._safe_json_object('{"x": 1}') == {"x": 1}
    assert LandingPageManager._safe_json_object('[1, 2]') is None
    assert LandingPageManager._safe_json_object("not-json") is None
