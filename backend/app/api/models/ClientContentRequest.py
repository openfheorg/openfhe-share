"""Request models for client content delivery endpoints."""

from pydantic import BaseModel, Field


class ClientStartupKitRequest(BaseModel):
    """Identifies the client site whose NVFlare startup kit should be packaged."""

    client_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="NVFlare client site folder name, for example site2.",
        examples=["site2"],
    )
