"""Tests for the Satchel One config, pupil, reauth and options flows."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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

USER_INPUT = {
    "school": "Example High School",
    CONF_USERNAME: "parent@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SCAN_MINUTES: 60,
}

ALEX = {"id": 42, "forename": "Alex", "surname": "Example"}
SAM = {"id": 43, "forename": "Sam", "surname": "Example"}

ENTRY_DATA = {
    CONF_USERNAME: "parent@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SCHOOL_ID: "999",
    CONF_STUDENT_ID: 42,
    CONF_SCAN_MINUTES: 60,
}


@pytest.fixture
def mock_school():
    """Patch the school-name lookup."""
    with patch(
        "custom_components.satchel_one.config_flow._resolve_school",
        new=AsyncMock(return_value="999"),
    ) as mocked:
        yield mocked


@pytest.fixture
def mock_students():
    """Patch the sign-in and pupil listing; defaults to a single pupil."""
    with patch(
        "custom_components.satchel_one.config_flow._fetch_students",
        new=AsyncMock(return_value=[ALEX]),
    ) as mocked:
        yield mocked


async def _start(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)


async def test_single_pupil_skips_the_pupil_step(
    hass: HomeAssistant, mock_school, mock_students
):
    result = await _start(hass)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alex Example"
    assert result["data"][CONF_STUDENT_ID] == 42
    assert result["data"][CONF_SCHOOL_ID] == "999"
    assert CONF_SCAN_MINUTES in result["data"]


async def test_multiple_pupils_prompt_for_a_choice(
    hass: HomeAssistant, mock_school, mock_students
):
    mock_students.return_value = [ALEX, SAM]

    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pupil"

    # Pick the second child, not the first the account happens to list.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STUDENT_ID: "43"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sam Example"
    assert result["data"][CONF_STUDENT_ID] == 43


async def test_unknown_school_is_recoverable(
    hass: HomeAssistant, mock_school, mock_students
):
    mock_school.return_value = None
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"school": "school_not_found"}

    mock_school.return_value = "999"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SatchelAuthError("nope"), "invalid_auth"),
        (SatchelConnectionError("down"), "cannot_connect"),
    ],
)
async def test_login_errors(
    hass: HomeAssistant, mock_school, mock_students, error, expected
):
    mock_students.side_effect = error
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_account_without_pupils(hass: HomeAssistant, mock_school, mock_students):
    mock_students.return_value = []
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_students"}


async def test_duplicate_pupil_is_aborted(
    hass: HomeAssistant, mock_school, mock_students
):
    MockConfigEntry(domain=DOMAIN, unique_id="42", data=ENTRY_DATA).add_to_hass(hass)

    result = await _start(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_the_password(
    hass: HomeAssistant, mock_school, mock_students
):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="42", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"


async def test_options_flow_sets_the_interval(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="42", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_MINUTES: 240}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_MINUTES] == 240
    assert isinstance(result["data"][CONF_SCAN_MINUTES], int)
