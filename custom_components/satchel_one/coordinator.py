"""Coordinator that polls Satchel One for one pupil's homework and detentions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SatchelApi, SatchelAuthError, SatchelConnectionError
from .const import CONF_SCHOOL_ID, CONF_STUDENT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

type SatchelConfigEntry = ConfigEntry[SatchelCoordinator]


@dataclass
class SatchelData:
    """Everything one refresh yields for a single pupil."""

    student_id: int | None = None
    student_name: str | None = None
    todos: list[dict[str, Any]] = field(default_factory=list)
    detentions: list[dict[str, Any]] = field(default_factory=list)
    praise_summary: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

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
        horizon = now + timedelta(days=7)
        out = []
        for todo in self.outstanding:
            due = parse_due(todo.get("due_on"))
            if due and now <= due <= horizon:
                out.append(todo)
        return out


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
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        day = dt_util.parse_date(value)
        if day is None:
            return None
        parsed = datetime.combine(day, time.max)
    return dt_util.as_local(parsed) if parsed.tzinfo is None else parsed


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
        self.session = async_create_clientsession(hass)
        self.api = SatchelApi(
            self.session,
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_SCHOOL_ID],
        )
        self._student_id = entry.data.get(CONF_STUDENT_ID)

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
            return SatchelData(
                student_id=student_id,
                student_name=pupil_name(pupil),
                todos=await self.api.async_get_todos(student_id),
                detentions=await self.api.async_get_detentions(student_id),
                praise_summary=await self.api.async_get_praise_summary(student_id),
                events=await self.api.async_get_events(student_id),
            )
        except SatchelAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SatchelConnectionError as err:
            raise UpdateFailed(str(err)) from err
