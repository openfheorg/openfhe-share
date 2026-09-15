from app.core.job_runner.nvflare_jobs.apis.warn_exception import WarnException


def test_warn_exception_payload_is_stable_and_copies_details():
    details = {"group": "high"}
    warning = WarnException("warning message", code="CODE", details=details)
    details["group"] = "changed"

    assert str(warning) == "warning message"
    assert warning.to_payload() == {
        "exception_type": "WarnException",
        "code": "CODE",
        "message": "warning message",
        "details": {"group": "high"},
    }
