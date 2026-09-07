"""Satchel One API client: OAuth2 password grant + parent data endpoints.

Reverse-engineered from the public SPA. Several quirks are easy to miss:

* ``school_id`` is mandatory in the password grant - without it the server
  returns ``invalid_credentials`` even for a correct password.
* the token endpoint lives at the domain root; ``/api/oauth/token`` is
  CDN-fronted and never authenticates.
* data requests authenticate with the ``smhw_token`` field from the grant, not
  ``access_token``, and the API version travels as a vendor media type in the
  Accept header.
* the CDN in front of the API caches failed responses, so every GET carries a
  cache-busting parameter.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    API_ACCEPT,
    API_ROOT,
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


async def async_search_schools(
    session: ClientSession, query: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Search Satchel's public school directory.

    The password grant needs a numeric ``school_id`` that parents do not know.
    This public endpoint maps a name or postcode onto it, and returns the town
    and postcode too so near-identical school names can be told apart.
    """
    try:
        async with session.get(
            f"{API_ROOT}/public/school_search",
            params={"filter": query, "limit": limit},
            headers={"Accept": API_ACCEPT, "User-Agent": USER_AGENT},
        ) as resp:
            if resp.status >= 400:
                raise SatchelConnectionError(f"school search returned {resp.status}")
            body = await resp.json(content_type=None)
    except (ClientError, ClientResponseError) as err:
        raise SatchelConnectionError(str(err)) from err

    if not isinstance(body, dict):
        return []
    # Schools that are no longer active cannot be logged into.
    return [s for s in body.get("schools", []) if s.get("is_active", True)]


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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._smhw_token}",
            "Accept": API_ACCEPT,
            "X-Platform": "web",
            "User-Agent": USER_AGENT,
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a JSON API path, refreshing the token once on a 401."""
        if self._smhw_token is None:
            await self.async_login()
        try:
            data, status = await self._request(path, params)
            if status == 401:
                await self._refresh()
                data, status = await self._request(path, params)
            if status == 401:
                raise SatchelAuthError("token rejected after refresh")
            if status >= 400:
                raise SatchelConnectionError(f"{path} returned HTTP {status}")
            return data
        except (ClientError, ClientResponseError) as err:
            raise SatchelConnectionError(str(err)) from err

    async def _request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[Any, int]:
        # The CDN fronting the API caches failures, including transient 400s, so
        # every request is made unique.
        query = {**(params or {}), "_cb": int(time.time() * 1000)}
        async with self._session.get(
            f"{API_ROOT}{path}", params=query, headers=self._headers()
        ) as resp:
            if resp.status == 401:
                return None, 401
            # A wrong path returns the HTML SPA shell, not JSON - treat as 404.
            body = await resp.json(content_type=None)
            return body, resp.status

    async def _put(self, path: str, payload: dict[str, Any]) -> Any:
        """PUT JSON to the API, refreshing the token once on a 401."""
        if self._smhw_token is None:
            await self.async_login()
        try:
            for attempt in (1, 2):
                async with self._session.put(
                    f"{API_ROOT}{path}",
                    json=payload,
                    headers={**self._headers(), "Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        await self._refresh()
                        continue
                    if resp.status == 401:
                        raise SatchelAuthError("token rejected after refresh")
                    if resp.status >= 400:
                        raise SatchelConnectionError(
                            f"{path} returned HTTP {resp.status}"
                        )
                    return await resp.json(content_type=None)
        except (ClientError, ClientResponseError) as err:
            raise SatchelConnectionError(str(err)) from err
        return None

    async def async_get_students(self) -> list[dict[str, Any]]:
        """List the pupils on this parent account."""
        data = await self._get("/students")
        return data.get("students", []) if isinstance(data, dict) else []

    async def async_get_todos(self, student_id: int) -> list[dict[str, Any]]:
        """Homework/quiz to-dos for one pupil.

        ``add_dateless`` keeps tasks with no due date, which the default view
        drops, and the wide date range keeps ones already past due.
        """
        data = await self._get(
            "/todos",
            {
                "student_id": student_id,
                "add_dateless": "true",
                "from": "2000-01-01",
                "to": "3000-01-01",
            },
        )
        return data.get("todos", []) if isinstance(data, dict) else []

    async def async_set_todo_completed(
        self, todo_id: str | int, completed: bool
    ) -> None:
        """Mark one to-do complete or incomplete in Satchel."""
        await self._put(f"/todos/{todo_id}", {"todo": {"completed": completed}})

    async def async_get_detentions(self, student_id: int) -> list[dict[str, Any]]:
        """Outstanding detentions for one pupil."""
        data = await self._get("/detentions", {"student_id": student_id})
        return data.get("detentions", []) if isinstance(data, dict) else []

    async def async_get_praise_summary(self, student_id: int) -> dict[str, Any]:
        """Behaviour-point totals (positive/negative) by day/week/month/all-time."""
        data = await self._get(f"/student_praise_summaries/{student_id}")
        if isinstance(data, dict):
            return data.get("student_praise_summary", {})
        return {}

    async def async_get_praises(self, student_id: int) -> list[dict[str, Any]]:
        """Individual behaviour events, which the summary only counts."""
        data = await self._get("/student_praises", {"student_id": student_id})
        return data.get("student_praises", []) if isinstance(data, dict) else []

    async def async_get_events(self, student_id: int) -> list[dict[str, Any]]:
        """School calendar events visible to this pupil."""
        data = await self._get("/events", {"student_id": student_id})
        return data.get("events", []) if isinstance(data, dict) else []

    async def async_get_lessons(
        self, student_id: int, start: date, end: date
    ) -> list[dict[str, Any]]:
        """Timetabled lessons between two dates.

        The timetable endpoint is week-based and returns whole weeks, so walk
        week by week from the Monday on or before ``start``.
        """
        lessons: list[dict[str, Any]] = []
        week = start - timedelta(days=start.weekday())
        seen: set[Any] = set()
        while week <= end:
            data = await self._get(
                f"/timetable/school/{self._school_id}/student/{student_id}",
                {"requestDate": week.isoformat()},
            )
            for block in (data or {}).get("weeks", []):
                for day in block.get("days", []):
                    for lesson in day.get("lessons", []):
                        if lesson.get("id") not in seen:
                            seen.add(lesson.get("id"))
                            lessons.append(lesson)
            week += timedelta(days=7)
        return lessons


def lesson_times(lesson: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """Parse a lesson's start/end, preferring the local wall-clock fields."""
    period = lesson.get("period") or {}
    out: list[datetime | None] = []
    for key in ("startDateTime", "endDateTime"):
        raw = period.get(key)
        try:
            out.append(datetime.fromisoformat(raw) if raw else None)
        except (TypeError, ValueError):
            out.append(None)
    return out[0], out[1]
