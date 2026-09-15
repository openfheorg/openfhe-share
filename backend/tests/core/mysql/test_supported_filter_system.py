from app.core.mysql.SupportedFilterSystem import SupportedFilterSystem


def test_is_supported_is_exact_and_handles_empty_values():
    assert SupportedFilterSystem.is_supported("DEFAULT") is True
    assert SupportedFilterSystem.is_supported("CANCER_TYPE") is True
    assert SupportedFilterSystem.is_supported("default") is False
    assert SupportedFilterSystem.is_supported(None) is False
