from __future__ import annotations

import base64
import json
import zlib
from typing import TypedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SHARE_LAUNCH_PAYLOAD_VERSION = 1


class ShareLaunchPayload(TypedDict, total=False):
    v: int
    username: str
    nvflare_job_id: str


def _require_text(value: str | None, error_message: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(error_message)
    return normalized


def encode_share_launch_payload(
    username: str,
    nvflare_job_id: str | None = None,
) -> str:
    """Create the pako-compatible value used by SHARE's ``launch`` query key.

    The browser decodes this as URL-safe Base64, then calls ``pako.inflate``
    and parses the resulting UTF-8 JSON.  Python's zlib-wrapped DEFLATE stream
    is the matching wire format.
    """
    normalized_username = _require_text(
        username,
        "A signed-in username is required to open SHARE.",
    )
    normalized_job_id = (nvflare_job_id or "").strip()

    payload: ShareLaunchPayload = {
        "v": SHARE_LAUNCH_PAYLOAD_VERSION,
        "username": normalized_username,
    }
    if normalized_job_id:
        payload["nvflare_job_id"] = normalized_job_id

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    # Pako's deflate() defaults to a zlib-wrapped stream at compression level 6.
    compressed = zlib.compress(serialized, level=6)
    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def build_share_launch_url(
    share_url: str,
    username: str,
    nvflare_job_id: str | None = None,
) -> str:
    """Return a SHARE URL with one encoded launch payload.

    A username-only payload is used by **Explore in SHARE**.  Supplying an
    NVFlare job ID adds that folder UUID for **View These Results in SHARE**.
    Existing unrelated query parameters and fragments are retained.
    """
    normalized_url = _require_text(share_url, "SHARE URL is not configured.")
    parts = urlsplit(normalized_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("SHARE URL must be an absolute HTTP or HTTPS URL.")

    launch_value = encode_share_launch_payload(username, nvflare_job_id)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in {"launch", "username", "nvflare_job_id"}
    ]
    query_items.append(("launch", launch_value))

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path or "/",
            urlencode(query_items, doseq=True),
            parts.fragment,
        )
    )
