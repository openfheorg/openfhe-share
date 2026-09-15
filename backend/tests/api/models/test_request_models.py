import pytest
from pydantic import ValidationError

from app.api.models.ClientContentRequest import ClientStartupKitRequest
from app.api.models.FunctionBasedRequest import FunctionBasedRequest
from app.core.mysql.SupportedFunction import SupportedFunction


def test_client_startup_kit_request_validates_length():
    assert ClientStartupKitRequest(client_name="site4").client_name == "site4"
    with pytest.raises(ValidationError):
        ClientStartupKitRequest(client_name="")
    with pytest.raises(ValidationError):
        ClientStartupKitRequest(client_name="x" * 65)


def test_function_based_request_coerces_enum_value():
    request = FunctionBasedRequest(function="MEAN")
    assert request.function is SupportedFunction.MEAN
    with pytest.raises(ValidationError):
        FunctionBasedRequest(function="NOT_REAL")
