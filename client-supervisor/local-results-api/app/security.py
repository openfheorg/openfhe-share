from fastapi import Header, HTTPException
from typing import Optional
import os


def require_token(
    authorization: Optional[str] = Header(default=None),
    x_duality_token: Optional[str] = Header(default=None),
):
    token = (os.environ.get("DUALITY_CLIENT_AGENT_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="Server token not configured")

    bearer = ""
    if authorization:
        authorization = authorization.strip()
        if authorization.lower().startswith("bearer "):
            bearer = authorization[7:].strip()

    provided = (x_duality_token or "").strip() or bearer
    if not provided or provided != token:
        raise HTTPException(status_code=401, detail="Unauthorized")
