import pytest

from app.core.job_runner.nvflare_jobs.apis.stat_analytics_event_type import (
    StatAnalyticsEventType,
    is_stat_analytics_phase_event,
    parse_stat_analytics_phase_event,
)


@pytest.mark.parametrize(
    "event,expected",
    [
        (StatAnalyticsEventType.SETUP_START, ("setup", False)),
        (StatAnalyticsEventType.AGGREGATE_REFERENCE_END, ("aggregate_reference", True)),
        (StatAnalyticsEventType.ENCRYPT_PQC_START, ("encrypt_pqc", False)),
        ("other", None),
        (None, None),
    ],
)
def test_parse_stat_analytics_phase_event(event, expected):
    assert parse_stat_analytics_phase_event(event) == expected


def test_is_stat_analytics_phase_event():
    assert is_stat_analytics_phase_event(StatAnalyticsEventType.DECRYPT_END)
    assert not is_stat_analytics_phase_event("stat_analytics_decrypt")
