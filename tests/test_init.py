"""Setup, reload and unload of a Satchel One config entry."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.satchel_one.api import (
    SatchelAuthError,
    SatchelConnectionError,
)
from custom_components.satchel_one.const import (
    CONF_SCAN_MINUTES,
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DOMAIN,
)

from .conftest import todo

ALEX = {"id": 42, "forename": "Alex", "surname": "Example"}
SAM = {"id": 43, "forename": "Sam", "surname": "Example"}

PRAISE = {
    "total_count": 120,
    "total_positive_count": 130,
    "total_negative_count": 10,
    "week_positive_count": 5,
    "week_negative_count": 1,
    "month_positive_count": 20,
    "month_negative_count": 2,
}


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
    """Patch every API call the coordinator makes in one place."""
    prefix = "custom_components.satchel_one.coordinator.SatchelApi"
    with (
        patch(
            f"{prefix}.async_get_students", new=AsyncMock(return_value=[ALEX, SAM])
        ) as students,
        patch(
            f"{prefix}.async_get_todos",
            new=AsyncMock(
                return_value=[
                    todo("Overdue essay", due_in_days=-3),
                    todo("Due tomorrow", due_in_days=1),
                    todo("Handed in", due_in_days=-1, completed=True),
                ]
            ),
        ),
        patch(f"{prefix}.async_get_detentions", new=AsyncMock(return_value=[])),
        patch(
            f"{prefix}.async_get_praise_summary",
            new=AsyncMock(return_value=PRAISE),
        ),
        patch(f"{prefix}.async_get_events", new=AsyncMock(return_value=[])),
    ):
        yield students


async def test_setup_and_unload(hass: HomeAssistant, entry, mock_api):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    outstanding = hass.states.get(
        "sensor.satchel_one_alex_example_homework_outstanding"
    )
    assert outstanding.state == "2"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_all_sensors_are_created(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    created = [
        state.entity_id
        for state in hass.states.async_all("sensor")
        if state.entity_id.startswith("sensor.satchel_one_")
    ]
    assert len(created) == 6


async def test_entry_tracks_its_configured_pupil(hass: HomeAssistant, mock_api):
    """A second-child entry must not silently fall back to the first pupil."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="43", data=_entry_data(43))
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.data.student_id == 43
    assert entry.runtime_data.data.student_name == "Sam Example"


async def test_legacy_entry_without_a_pupil_id_uses_the_first(
    hass: HomeAssistant, mock_api
):
    """Entries created before pupil selection existed keep working."""
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
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_changing_options_reloads_the_entry(hass: HomeAssistant, entry, mock_api):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_MINUTES: 120})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval.total_seconds() == 120 * 60
