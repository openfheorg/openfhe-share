"""
Shared Pydantic models for request payloads.
"""

from pydantic import BaseModel
from app.core.mysql.SupportedFunction import SupportedFunction


class FunctionBasedRequest(BaseModel):
    """Used to retrieve data filtered by a specific function."""
    function: SupportedFunction
