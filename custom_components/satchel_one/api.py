"""Satchel One API client: OAuth2 password grant + parent data endpoints.

Reverse-engineered from the public SPA. Two token quirks that are easy to miss:

* ``school_id`` is mandatory in the password grant - without it the server
  returns ``invalid_credentials`` even for a correct password.
* data requests authenticate with the ``smhw_token`` field from the grant, not
  ``access_token``, and the API version travels as a vendor media type in the
  Accept header.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    API_ACCEPT,
    API_BASE,
    CLIENT_ID,
    CLIENT_SECRET,
    TOKEN_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class SatchelAuthError(Exception):
    """Login rejected - bad credentials or expired session."""


class SatchelConnectionError(Exception):
    """Could not reach Satchel One."""


class SatchelApi:
    """Minimal client for one Satchel One parent account."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        school_id: str,
    ) -> None:
        """Store credentials; tokens are fetched lazily on first use."""
        self._session = session
        self._username = username
        self._password = password
        self._school_id = str(school_id)
        self._smhw_token: str | None = None
        self._refresh_token: str | None = None

    async def async_login(self) -> None:
        """Obtain a fresh token via the password grant."""
        await self._grant(
            {
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
                "school_id": self._school_id,
                "verification_token": "",
            }
        )

    async def _refresh(self) -> None:
        """Swap the refresh token for a new access token, no password sent."""
        if not self._refresh_token:
            await self.async_login()
            return
        await self._grant(
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        )

    async def _grant(self, data: dict[str, str]) -> None:
        params = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
        try:
            async with self._session.post(
                TOKEN_URL,
                params=params,
                data=data,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            ) as resp:
                payload = await resp.json(content_type=None)
                if resp.status == 401 or "access_token" not in payload:
                    raise SatchelAuthError(str(payload.get("errors", payload)))
                resp.raise_for_status()
        except SatchelAuthError:
            raise
        except (ClientError, ClientResponseError) as err:
            raise SatchelConnectionError(str(err)) from err
        # Data calls use smhw_token; refresh_token lets us avoid re-sending the
        # password on every poll (and re-tripping credential-testing guards).
        self._smhw_token = payload.get("smhw_token") or payload["access_token"]
        self._refresh_token = payload.get("refresh_token") or self._refresh_token

    async def _get(self, path: str) -> Any:
        """GET a JSON API path, refreshing the token once on a 401."""
        if self._smhw_token is None:
            await self.async_login()
        try:
            data, status = await self._request(path)
            if status == 401:
                await self._refresh()
                data, status = await self._request(path)
            if status == 401:
                raise SatchelAuthError("token rejected after refresh")
            if status >= 400:
                raise SatchelConnectionError(f"{path} returned HTTP {status}")
            return data
        except (ClientError, ClientResponseError) as err:
            raise SatchelConnectionError(str(err)) from err

    async def _request(self, path: str) -> tuple[Any, int]:
        headers = {
            "Authorization": f"Bearer {self._smhw_token}",
            "Accept": API_ACCEPT,
            "X-Platform": "web",
            "User-Agent": USER_AGENT,
        }
        async with self._session.get(f"{API_BASE}{path}", headers=headers) as resp:
            if resp.status == 401:
                return None, 401
            # A wrong path returns the HTML SPA shell, not JSON - treat as 404.
            body = await resp.json(content_type=None)
            return body, resp.status

    async def async_get_students(self) -> list[dict[str, Any]]:
        """List the pupils on this parent account."""
        data = await self._get("/api/students")
        return data.get("students", []) if isinstance(data, dict) else []

    async def async_get_todos(self, student_id: int) -> list[dict[str, Any]]:
        """Homework/quiz to-dos for one pupil."""
        data = await self._get(f"/api/todos?student_id={student_id}")
        return data.get("todos", []) if isinstance(data, dict) else []

    async def async_get_detentions(self, student_id: int) -> list[dict[str, Any]]:
        """Outstanding detentions for one pupil."""
        data = await self._get(f"/api/detentions?student_id={student_id}")
        return data.get("detentions", []) if isinstance(data, dict) else []

    async def async_get_praise_summary(self, student_id: int) -> dict[str, Any]:
        """Behaviour-point totals (positive/negative) by day/week/month/all-time."""
        data = await self._get(f"/api/student_praise_summaries/{student_id}")
        if isinstance(data, dict):
            return data.get("student_praise_summary", {})
        return {}

    async def async_get_events(self, student_id: int) -> list[dict[str, Any]]:
        """School calendar events visible to this pupil."""
        data = await self._get(f"/api/events?student_id={student_id}")
        return data.get("events", []) if isinstance(data, dict) else []
