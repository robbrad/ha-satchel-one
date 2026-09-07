"""Setup, entity creation, events and unload for a Satchel One config entry."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.satchel_one.api import (
    SatchelAuthError,
    SatchelConnectionError,
)
from custom_components.satchel_one.const import (
    CONF_SCAN_MINUTES,
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DOMAIN,
    EVENT_BEHAVIOUR_POINT,
    EVENT_HOMEWORK_COMPLETED,
    EVENT_NEW_HOMEWORK,
)

from .conftest import lesson, praise, todo

ALEX = {"id": 42, "forename": "Alex", "surname": "Example"}
SAM = {"id": 43, "forename": "Sam", "surname": "Example"}

PRAISE_SUMMARY = {
    "total_count": 120,
    "total_positive_count": 130,
    "total_negative_count": 10,
    "week_positive_count": 5,
    "week_negative_count": 1,
    "month_positive_count": 20,
    "month_negative_count": 2,
}

TODOS = [
    todo("Overdue essay", due_in_days=-3, task_id=1),
    todo("Due tomorrow", due_in_days=1, task_id=2),
    todo("Handed in", due_in_days=-1, completed=True, task_id=3),
]
LESSONS = [lesson("Maths", start_hour=9, end_hour=10, lesson_id=11)]
PRAISES = [praise(3, praise_id=101)]


def _entry_data(student_id: int | None = 42) -> dict:
    data = {
        CONF_USERNAME: "parent@example.com",
        CONF_PASSWORD: "hunter2",
        CONF_SCHOOL_ID: "999",
        CONF_SCAN_MINUTES: 60,
    }
    if student_id is not None:
        data[CONF_STUDENT_ID] = student_id
    return data


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="42", data=_entry_data())
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_api():
    """Patch every API call the coordinator makes."""
    p = "custom_components.satchel_one.coordinator.SatchelApi"
    with (
        patch(
            f"{p}.async_get_students", new=AsyncMock(return_value=[ALEX, SAM])
        ) as students,
        patch(f"{p}.async_get_todos", new=AsyncMock(return_value=list(TODOS))),
        patch(f"{p}.async_get_detentions", new=AsyncMock(return_value=[])),
        patch(
            f"{p}.async_get_praise_summary", new=AsyncMock(return_value=PRAISE_SUMMARY)
        ),
        patch(f"{p}.async_get_praises", new=AsyncMock(return_value=list(PRAISES))),
        patch(f"{p}.async_get_events", new=AsyncMock(return_value=[])),
        patch(f"{p}.async_get_lessons", new=AsyncMock(return_value=list(LESSONS))),
    ):
        yield students


async def test_setup_creates_every_platform(hass: HomeAssistant, entry, mock_api):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    prefix = "alex_example"
    assert (
        hass.states.get(f"sensor.satchel_one_{prefix}_homework_outstanding").state
        == "2"
    )
    assert (
        hass.states.get(f"binary_sensor.satchel_one_{prefix}_overdue_homework").state
        == "on"
    )
    assert hass.states.get(f"todo.satchel_one_{prefix}_homework").state == "2"
    assert hass.states.get(f"calendar.satchel_one_{prefix}_timetable") is not None


async def test_entity_counts_per_platform(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    def count(domain):
        return len(
            [
                s
                for s in hass.states.async_all(domain)
                if s.entity_id.startswith(f"{domain}.satchel_one_")
            ]
        )

    assert count("sensor") == 6
    assert count("binary_sensor") == 3
    assert count("todo") == 1
    assert count("calendar") == 1


async def test_unload(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_first_refresh_fires_no_events(hass: HomeAssistant, entry, mock_api):
    """Startup must not announce every task that already existed."""
    events = async_capture_events(hass, EVENT_NEW_HOMEWORK)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert events == []


async def test_new_homework_fires_an_event(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    events = async_capture_events(hass, EVENT_NEW_HOMEWORK)
    fresh = todo("Brand new task", due_in_days=4, task_id=99)
    with patch(
        "custom_components.satchel_one.coordinator.SatchelApi.async_get_todos",
        new=AsyncMock(return_value=[*TODOS, fresh]),
    ):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["task_id"] == 99
    assert events[0].data["title"] == "Brand new task"
    assert events[0].data["student_name"] == "Alex Example"
    # The deep link lets a notification link straight to the task.
    assert events[0].data["url"] == "https://www.satchelone.com/school/homeworks/99"


async def test_completing_homework_fires_an_event(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    events = async_capture_events(hass, EVENT_HOMEWORK_COMPLETED)
    done = [dict(t, completed=True) if t["id"] == 2 else t for t in TODOS]
    with patch(
        "custom_components.satchel_one.coordinator.SatchelApi.async_get_todos",
        new=AsyncMock(return_value=done),
    ):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert [e.data["task_id"] for e in events] == [2]


async def test_new_behaviour_point_fires_an_event(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    events = async_capture_events(hass, EVENT_BEHAVIOUR_POINT)
    with patch(
        "custom_components.satchel_one.coordinator.SatchelApi.async_get_praises",
        new=AsyncMock(
            return_value=[*PRAISES, praise(-2, praise_id=102, reason="Late")]
        ),
    ):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["points"] == -2
    # severity lets automations branch without sign maths.
    assert events[0].data["severity"] == 2
    assert events[0].data["positive"] is False


async def test_entry_tracks_its_configured_pupil(hass: HomeAssistant, mock_api):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="43", data=_entry_data(43))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data.student_id == 43


async def test_legacy_entry_without_a_pupil_id_uses_the_first(
    hass: HomeAssistant, mock_api
):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="42", data=_entry_data(None))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data.student_id == 42


async def test_no_pupils_fails_the_refresh(hass: HomeAssistant, entry, mock_api):
    mock_api.return_value = []
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_unreachable(hass: HomeAssistant, entry, mock_api):
    mock_api.side_effect = SatchelConnectionError("down")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_bad_credentials_trigger_reauth(hass: HomeAssistant, entry, mock_api):
    mock_api.side_effect = SatchelAuthError("nope")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )


async def test_changing_options_reloads_the_entry(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_MINUTES: 120})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval.total_seconds() == 120 * 60
