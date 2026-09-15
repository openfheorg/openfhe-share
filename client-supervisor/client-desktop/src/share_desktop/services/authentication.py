from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class UserSession:
    username: str
    role: str
    user_id: int | None
    client_id: int | None
    client_name: str | None
    projects: list[dict[str, Any]]


class AuthenticationService:
    def __init__(
        self,
        api_base_url: str,
        user_role_path: str = "/user/role",
        timeout_seconds: int = 30,
    ) -> None:
        self.api_base_url = api_base_url.strip().rstrip("/")
        self.user_role_path = "/" + user_role_path.strip().lstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))

    @property
    def endpoint_url(self) -> str:
        if not self.api_base_url:
            raise RuntimeError("Authentication API base URL is not configured.")
        return f"{self.api_base_url}{self.user_role_path}"

    def login(self, username: str) -> UserSession:
        normalized_username = (username or "").strip()
        if not normalized_username:
            raise RuntimeError("Username is required.")

        try:
            response = requests.post(
                self.endpoint_url,
                json={"username": normalized_username},
                timeout=(15, self.timeout_seconds),
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Unable to reach the SHARE backend: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            message = "Login failed"
            if isinstance(payload, dict):
                message = str(payload.get("error") or payload.get("detail") or message)
            raise RuntimeError(message)

        if not isinstance(payload, dict):
            raise RuntimeError("The SHARE backend returned an invalid login response.")

        role = str(payload.get("role") or "").strip()
        if not role:
            raise RuntimeError("Role not found for user.")

        returned_username = str(payload.get("username") or normalized_username).strip()
        client_name_value = payload.get("client_name")
        client_name = client_name_value.strip() if isinstance(client_name_value, str) else None
        projects_value = payload.get("projects")
        projects = projects_value if isinstance(projects_value, list) else []

        return UserSession(
            username=returned_username or normalized_username,
            role=role,
            user_id=_optional_int(payload.get("user_id")),
            client_id=_optional_int(payload.get("client_id")),
            client_name=client_name or None,
            projects=[item for item in projects if isinstance(item, dict)],
        )


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
