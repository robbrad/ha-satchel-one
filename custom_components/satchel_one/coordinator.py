"""Coordinator that polls Satchel One for one pupil's school data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SatchelApi, SatchelAuthError, SatchelConnectionError
from .const import (
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DOMAIN,
    DUE_SOON_DAYS,
    EVENT_BEHAVIOUR_POINT,
    EVENT_HOMEWORK_COMPLETED,
    EVENT_NEW_DETENTION,
    EVENT_NEW_HOMEWORK,
    TASK_WEB_PATHS,
    WEB_BASE,
)

_LOGGER = logging.getLogger(__name__)

type SatchelConfigEntry = ConfigEntry[SatchelCoordinator]


def pupil_name(pupil: dict[str, Any]) -> str | None:
    """'Ada Lovelace' from a pupil record, or None if it has no name."""
    return (
        " ".join(part for part in (pupil.get("forename"), pupil.get("surname")) if part)
        or None
    )


def parse_due(value: str | None) -> datetime | None:
    """Parse a due date into an aware datetime, or None.

    Satchel returns ISO8601 timestamps for most to-dos but a bare date for
    some. Both are normalised to aware datetimes, because the "next due"
    sensor is a timestamp entity and Home Assistant rejects naive values.
    """
    if not value:
        return None
    text = str(value).strip()
    if "T" not in text and " " not in text:
        day = dt_util.parse_date(text)
        if day is not None:
            return dt_util.as_local(datetime.combine(day, time.max))
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        return None
    aware = dt_util.as_local(parsed) if parsed.tzinfo is None else parsed
    local = dt_util.as_local(aware)
    # Satchel expresses a date-only due date as local midnight (and
    # parse_datetime turns a bare date into midnight too). Read literally that
    # marks homework overdue from the first second of the very day it is due,
    # so midnight means "by the end of this day".
    if (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0):
        return local.replace(hour=23, minute=59, second=59, microsecond=999999)
    return aware


def task_url(todo: dict[str, Any]) -> str | None:
    """Deep link to a task on Satchel's website, if its type is known."""
    path = TASK_WEB_PATHS.get(todo.get("class_task_type") or "")
    task_id = todo.get("id")
    return f"{WEB_BASE}/school/{path}/{task_id}" if path and task_id else None


@dataclass
class SatchelData:
    """Everything one refresh yields for a single pupil."""

    student_id: int | None = None
    student_name: str | None = None
    todos: list[dict[str, Any]] = field(default_factory=list)
    detentions: list[dict[str, Any]] = field(default_factory=list)
    praise_summary: dict[str, Any] = field(default_factory=dict)
    praises: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    lessons: list[dict[str, Any]] = field(default_factory=list)

    @property
    def outstanding(self) -> list[dict[str, Any]]:
        """To-dos not yet marked complete."""
        return [t for t in self.todos if not t.get("completed")]

    @property
    def overdue(self) -> list[dict[str, Any]]:
        """Outstanding to-dos whose due date is in the past."""
        now = dt_util.now()
        out = []
        for todo in self.outstanding:
            due = parse_due(todo.get("due_on"))
            if due and due < now:
                out.append(todo)
        return out

    @property
    def due_next(self) -> dict[str, Any] | None:
        """The soonest-due outstanding to-do."""
        dated = [
            (due, todo)
            for todo in self.outstanding
            if (due := parse_due(todo.get("due_on"))) is not None
        ]
        return min(dated, key=lambda item: item[0])[1] if dated else None

    @property
    def due_this_week(self) -> list[dict[str, Any]]:
        """Outstanding to-dos due within the next 7 days."""
        now = dt_util.now()
        horizon = now + timedelta(days=DUE_SOON_DAYS)
        out = []
        for todo in self.outstanding:
            due = parse_due(todo.get("due_on"))
            if due and now <= due <= horizon:
                out.append(todo)
        return out

    @property
    def detentions_today(self) -> list[dict[str, Any]]:
        """Detentions scheduled for today."""
        today = dt_util.now().date()
        out = []
        for detention in self.detentions:
            when = parse_due(detention.get("detention_date") or detention.get("date"))
            if when and when.date() == today:
                out.append(detention)
        return out


class SatchelCoordinator(DataUpdateCoordinator[SatchelData]):
    """Fetches one pupil's Satchel One data on a schedule."""

    def __init__(
        self, hass: HomeAssistant, entry: SatchelConfigEntry, update_interval: timedelta
    ) -> None:
        """Create the coordinator and its API client."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            config_entry=entry,
        )
        # Satchel authenticates with a bearer token per client, not cookies,
        # so the shared Home Assistant session is safe and it owns the
        # lifecycle - closing it ourselves is what HA warns about.
        self.session = async_get_clientsession(hass)
        self.api = SatchelApi(
            self.session,
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_SCHOOL_ID],
        )
        self._student_id = entry.data.get(CONF_STUDENT_ID)
        # Populated on the first refresh so startup does not fire an event for
        # every piece of homework that already existed.
        self._seen_todos: set[Any] | None = None
        self._completed_todos: set[Any] = set()
        self._seen_detentions: set[Any] = set()
        self._seen_praises: set[Any] = set()

    async def _async_update_data(self) -> SatchelData:
        """Fetch this entry's pupil, then their homework, detentions and points."""
        try:
            students = await self.api.async_get_students()
            if not students:
                raise UpdateFailed("Satchel One returned no pupils for this account")
            # Entries created before pupil selection existed have no stored id;
            # they keep tracking the first pupil, as they always did.
            pupil = next(
                (p for p in students if str(p["id"]) == str(self._student_id)),
                students[0],
            )
            student_id = pupil["id"]
            today = dt_util.now().date()
            data = SatchelData(
                student_id=student_id,
                student_name=pupil_name(pupil),
                todos=await self.api.async_get_todos(student_id),
                detentions=await self.api.async_get_detentions(student_id),
                praise_summary=await self.api.async_get_praise_summary(student_id),
                praises=await self.api.async_get_praises(student_id),
                events=await self.api.async_get_events(student_id),
                lessons=await self.api.async_get_lessons(
                    student_id, today, today + timedelta(days=DUE_SOON_DAYS)
                ),
            )
        except SatchelAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SatchelConnectionError as err:
            raise UpdateFailed(str(err)) from err

        self._fire_events(data)
        return data

    def _fire_events(self, data: SatchelData) -> None:
        """Announce anything new since the last refresh on the event bus."""
        base = {"student_id": data.student_id, "student_name": data.student_name}

        todo_ids = {t.get("id") for t in data.todos}
        completed_now = {t.get("id") for t in data.todos if t.get("completed")}

        if self._seen_todos is None:
            # First refresh: record the baseline, announce nothing.
            self._seen_todos = todo_ids
            self._completed_todos = completed_now
            self._seen_detentions = {d.get("id") for d in data.detentions}
            self._seen_praises = {p.get("id") for p in data.praises}
            return

        for todo in data.todos:
            if todo.get("id") not in self._seen_todos:
                self.hass.bus.async_fire(
                    EVENT_NEW_HOMEWORK,
                    {
                        **base,
                        "task_id": todo.get("id"),
                        "title": todo.get("class_task_title"),
                        "subject": todo.get("subject"),
                        "teacher": todo.get("teacher_name"),
                        "type": todo.get("class_task_type"),
                        "due_on": todo.get("due_on"),
                        "url": task_url(todo),
                    },
                )
            if (
                todo.get("id") in completed_now
                and todo.get("id") not in self._completed_todos
            ):
                self.hass.bus.async_fire(
                    EVENT_HOMEWORK_COMPLETED,
                    {
                        **base,
                        "task_id": todo.get("id"),
                        "title": todo.get("class_task_title"),
                        "subject": todo.get("subject"),
                    },
                )

        for detention in data.detentions:
            if detention.get("id") not in self._seen_detentions:
                self.hass.bus.async_fire(
                    EVENT_NEW_DETENTION,
                    {
                        **base,
                        "detention_id": detention.get("id"),
                        "reason": detention.get("description")
                        or detention.get("reason"),
                        "date": detention.get("detention_date")
                        or detention.get("date"),
                        "location": detention.get("room") or detention.get("location"),
                    },
                )

        for praise in data.praises:
            if praise.get("id") not in self._seen_praises:
                points = praise.get("score", praise.get("points"))
                self.hass.bus.async_fire(
                    EVENT_BEHAVIOUR_POINT,
                    {
                        **base,
                        "praise_id": praise.get("id"),
                        "points": points,
                        # severity lets automations branch without sign maths.
                        "severity": abs(points) if isinstance(points, int) else None,
                        "positive": None if points is None else points > 0,
                        "reason": praise.get("comments") or praise.get("reason"),
                        "category": praise.get("category"),
                        "teacher": praise.get("teacher_name"),
                        "awarded_on": praise.get("created_at"),
                    },
                )

        self._seen_todos = todo_ids
        self._completed_todos = completed_now
        self._seen_detentions = {d.get("id") for d in data.detentions}
        self._seen_praises = {p.get("id") for p in data.praises}
