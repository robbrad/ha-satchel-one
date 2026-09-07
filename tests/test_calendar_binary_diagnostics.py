"""Tests for the timetable calendar, binary sensors and diagnostics."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.satchel_one.api import SatchelConnectionError
from custom_components.satchel_one.const import (
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DOMAIN,
)
from custom_components.satchel_one.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import NOW, lesson, praise, todo

ALEX = {"id": 42, "forename": "Alex", "surname": "Example"}
CAL = "calendar.satchel_one_alex_example_timetable"

# NOW is 09:00; these bracket it so "current" and "next" are both exercised.
LESSONS = [
    lesson("Maths", start_hour=8, end_hour=9, lesson_id=1, room="M1"),
    lesson("English", start_hour=9, end_hour=10, lesson_id=2, room="E2"),
    lesson("Science", start_hour=11, end_hour=12, lesson_id=3, room="S3"),
]
TODOS = [
    todo("Overdue", due_in_days=-2, task_id=1),
    todo("Due today", due_on=NOW.date().isoformat(), task_id=2),
]
DETENTIONS = [
    {"id": 5, "detention_date": NOW.isoformat(), "description": "Late", "room": "D1"},
]


@pytest.fixture
async def setup_entry(hass: HomeAssistant, request):
    lessons = getattr(request, "param", {}).get("lessons", LESSONS)
    detentions = getattr(request, "param", {}).get("detentions", DETENTIONS)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="42",
        data={
            CONF_USERNAME: "p@example.com",
            CONF_PASSWORD: "x",
            CONF_SCHOOL_ID: "999",
            CONF_STUDENT_ID: 42,
        },
    )
    entry.add_to_hass(hass)
    p = "custom_components.satchel_one.coordinator.SatchelApi"
    with (
        patch(f"{p}.async_get_students", new=AsyncMock(return_value=[ALEX])),
        patch(f"{p}.async_get_todos", new=AsyncMock(return_value=TODOS)),
        patch(f"{p}.async_get_detentions", new=AsyncMock(return_value=detentions)),
        patch(
            f"{p}.async_get_praise_summary",
            new=AsyncMock(return_value={"total_count": 5}),
        ),
        patch(
            f"{p}.async_get_praises",
            new=AsyncMock(return_value=[praise(3, praise_id=1)]),
        ),
        patch(f"{p}.async_get_events", new=AsyncMock(return_value=[])),
        patch(f"{p}.async_get_lessons", new=AsyncMock(return_value=lessons)),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


# ---------------------------- calendar ----------------------------


async def test_calendar_shows_the_lesson_happening_now(
    hass: HomeAssistant, setup_entry
):
    state = hass.states.get(CAL)
    # 09:00 falls inside the 09:00-10:00 English lesson.
    assert state.attributes["message"] == "English"
    assert state.attributes["location"] == "E2"
    assert state.state == "on"


@pytest.mark.parametrize(
    "setup_entry",
    [{"lessons": [lesson("Science", start_hour=11, end_hour=12, lesson_id=3)]}],
    indirect=True,
)
async def test_calendar_falls_back_to_the_next_lesson(hass: HomeAssistant, setup_entry):
    state = hass.states.get(CAL)
    assert state.attributes["message"] == "Science"
    assert state.state == "off"


@pytest.mark.parametrize("setup_entry", [{"lessons": []}], indirect=True)
async def test_calendar_with_no_lessons(hass: HomeAssistant, setup_entry):
    assert hass.states.get(CAL).state == "off"


async def test_calendar_get_events_filters_the_window(hass: HomeAssistant, setup_entry):
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "start_date_time": NOW.isoformat(),
            "end_date_time": (NOW + timedelta(hours=1)).isoformat(),
        },
        target={"entity_id": CAL},
        blocking=True,
        return_response=True,
    )
    # Only the 09:00-10:00 lesson overlaps that hour.
    assert [e["summary"] for e in events[CAL]["events"]] == ["English"]


async def test_calendar_survives_a_failed_fetch(hass: HomeAssistant, setup_entry):
    """A timetable outage must not break the calendar view."""
    with patch(
        "custom_components.satchel_one.coordinator.SatchelApi.async_get_lessons",
        new=AsyncMock(side_effect=SatchelConnectionError("down")),
    ):
        events = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "start_date_time": NOW.isoformat(),
                "end_date_time": (NOW + timedelta(hours=4)).isoformat(),
            },
            target={"entity_id": CAL},
            blocking=True,
            return_response=True,
        )
    # Falls back to the lessons already cached by the coordinator.
    assert [e["summary"] for e in events[CAL]["events"]] == ["English", "Science"]


# -------------------------- binary sensors --------------------------


async def test_overdue_binary_sensor(hass: HomeAssistant, setup_entry):
    state = hass.states.get("binary_sensor.satchel_one_alex_example_overdue_homework")
    assert state.state == "on"
    assert state.attributes["count"] == 1


async def test_due_today_binary_sensor(hass: HomeAssistant, setup_entry):
    assert (
        hass.states.get(
            "binary_sensor.satchel_one_alex_example_homework_due_today"
        ).state
        == "on"
    )


async def test_detention_today_binary_sensor(hass: HomeAssistant, setup_entry):
    state = hass.states.get("binary_sensor.satchel_one_alex_example_detention_today")
    assert state.state == "on"
    assert state.attributes["count"] == 1


@pytest.mark.parametrize("setup_entry", [{"detentions": []}], indirect=True)
async def test_detention_today_off_without_detentions(hass: HomeAssistant, setup_entry):
    assert (
        hass.states.get("binary_sensor.satchel_one_alex_example_detention_today").state
        == "off"
    )


# ---------------------------- diagnostics ----------------------------


async def test_diagnostics_redact_credentials(hass: HomeAssistant, setup_entry):
    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    data = diag["entry"]["data"]
    assert data[CONF_USERNAME] == "**REDACTED**"
    assert data[CONF_PASSWORD] == "**REDACTED**"
    assert data[CONF_SCHOOL_ID] == "**REDACTED**"


async def test_diagnostics_report_counts_not_content(hass: HomeAssistant, setup_entry):
    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    assert diag["counts"]["todos"] == 2
    assert diag["counts"]["overdue"] == 1
    assert diag["counts"]["lessons"] == 3
    assert diag["counts"]["praises"] == 1
    assert diag["coordinator"]["last_update_success"] is True

    blob = repr(diag)
    # Field names are useful; a child's homework titles are not.
    assert "class_task_title" in blob
    assert "Overdue" not in blob
    assert "Great work" not in blob
