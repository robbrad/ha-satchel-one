"""Satchel One calendar platform: the pupil's timetable as calendar events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import SatchelConnectionError, lesson_times
from .coordinator import SatchelConfigEntry, SatchelCoordinator
from .entity import SatchelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SatchelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Satchel One timetable calendar."""
    async_add_entities([SatchelCalendar(entry.runtime_data, entry)])


def _teacher(lesson: dict[str, Any]) -> str | None:
    teacher = lesson.get("teacher") or {}
    if name := teacher.get("name"):
        return str(name)
    parts = [teacher.get("title"), teacher.get("forename"), teacher.get("surname")]
    return " ".join(p for p in parts if p) or None


def _to_event(lesson: dict[str, Any]) -> CalendarEvent | None:
    """Convert one timetable lesson into a calendar event."""
    start, end = lesson_times(lesson)
    if start is None or end is None:
        return None
    group = lesson.get("classGroup") or {}
    description = " - ".join(p for p in (group.get("name"), _teacher(lesson)) if p)
    return CalendarEvent(
        uid=str(lesson.get("id")) if lesson.get("id") is not None else None,
        summary=group.get("subject") or group.get("name") or "Lesson",
        start=dt_util.as_local(start) if start.tzinfo is None else start,
        end=dt_util.as_local(end) if end.tzinfo is None else end,
        description=description or None,
        location=lesson.get("room") or None,
    )


class SatchelCalendar(
    SatchelEntity, CoordinatorEntity[SatchelCoordinator], CalendarEntity
):
    """The pupil's lesson timetable."""

    _attr_translation_key = "timetable"

    def __init__(
        self, coordinator: SatchelCoordinator, entry: SatchelConfigEntry
    ) -> None:
        """Bind the calendar to its coordinator and pupil device."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_timetable"

    @property
    def event(self) -> CalendarEvent | None:
        """The lesson happening now, else the next one still to come."""
        now = dt_util.now()
        events = sorted(
            (e for e in map(_to_event, self.coordinator.data.lessons) if e),
            key=lambda e: e.start,
        )
        for candidate in events:
            if candidate.start <= now < candidate.end:
                return candidate
        return next((e for e in events if e.start > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Fetch lessons for whatever range the calendar view asks for."""
        try:
            lessons = await self.coordinator.api.async_get_lessons(
                self.coordinator.data.student_id, start_date.date(), end_date.date()
            )
        except SatchelConnectionError:
            # A failed fetch must not break the calendar view.
            lessons = self.coordinator.data.lessons
        events = []
        for lesson in lessons:
            event = _to_event(lesson)
            if event and event.end > start_date and event.start < end_date:
                events.append(event)
        return sorted(events, key=lambda e: e.start)
