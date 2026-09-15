from __future__ import annotations

from typing import Any, Mapping


class WarnException(Exception):
    """A non-fatal, user-facing analytics warning.

    This exception is intentionally raised only at the point where a workflow
    detects a known, non-actionable result condition. Callers must catch it and
    serialize ``to_payload()`` into the normal result object; allowing it to
    escape an NVFlare task would turn an informational warning into a failed
    workflow.
    """

    MARKER = "WarnException"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_payload(self) -> dict[str, Any]:
        return {
            "exception_type": self.MARKER,
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }
