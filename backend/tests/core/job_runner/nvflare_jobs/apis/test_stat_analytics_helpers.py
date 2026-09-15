from app.core.job_runner.nvflare_jobs.apis.stat_analytics import (
    _attach_warning,
    _degenerate_lr_warning,
    _low_signal_warning,
    _single_risk_group_warning,
)


def test_attach_warning_preserves_result_fields_and_adds_ui_payload():
    result = {"value": 3}
    warning = _degenerate_lr_warning()
    returned = _attach_warning(result, warning)
    assert returned is result
    assert result["value"] == 3
    assert result["status"] == "WARN"
    assert result["warning"]["code"] == "DEGENERATE_LOGISTIC_REGRESSION"


def test_low_signal_warning_records_values_and_path_message():
    warning = _low_signal_warning(-1e-7, 2e-7, encrypted=False)
    payload = warning.to_payload()
    assert payload["code"] == "LOW_SIGNAL_TO_NOISE"
    assert payload["details"]["mean"] == -1e-7
    assert "will be dominated" in payload["message"]


def test_single_risk_group_warning_optionally_records_group():
    assert _single_risk_group_warning().details == {}
    assert _single_risk_group_warning("high").details == {"group": "high"}
