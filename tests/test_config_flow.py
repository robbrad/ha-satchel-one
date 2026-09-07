"""Tests for the Satchel One school, credential, pupil, reauth and options flows."""

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
from custom_components.satchel_one.config_flow import school_label
from custom_components.satchel_one.const import (
    CONF_SCAN_MINUTES,
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DOMAIN,
)

SCHOOL = {
    "id": 999,
    "name": "Example High School",
    "town": "Exampleton",
    "post_code": "EX1 2AB",
    "is_active": True,
}
OTHER_SCHOOL = {
    "id": 1000,
    "name": "Example High School Annexe",
    "town": "Otherton",
    "post_code": "OT1 3CD",
    "is_active": True,
}

ALEX = {"id": 42, "forename": "Alex", "surname": "Example"}
SAM = {"id": 43, "forename": "Sam", "surname": "Example"}

CREDS = {
    CONF_USERNAME: "parent@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SCAN_MINUTES: 60,
}

ENTRY_DATA = {
    CONF_USERNAME: "parent@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SCHOOL_ID: "999",
    CONF_STUDENT_ID: 42,
    CONF_SCAN_MINUTES: 60,
}


@pytest.fixture
def mock_search():
    """Patch the public school-search endpoint; one match by default."""
    with patch(
        "custom_components.satchel_one.config_flow.async_search_schools",
        new=AsyncMock(return_value=[SCHOOL]),
    ) as mocked:
        yield mocked


@pytest.fixture
def mock_students():
    """Patch the sign-in and pupil listing; one pupil by default."""
    with patch(
        "custom_components.satchel_one.config_flow._fetch_students",
        new=AsyncMock(return_value=[ALEX]),
    ) as mocked:
        yield mocked


async def _search(hass, query="Example High"):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school": query}
    )


def test_school_label_includes_town_and_postcode():
    assert school_label(SCHOOL) == "Example High School - Exampleton, EX1 2AB"


def test_school_label_without_location():
    assert school_label({"id": 7, "name": "Panda Academy"}) == "Panda Academy"


async def test_single_school_skips_the_picker(
    hass: HomeAssistant, mock_search, mock_students
):
    result = await _search(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alex Example"
    assert result["data"][CONF_SCHOOL_ID] == "999"
    assert result["data"][CONF_STUDENT_ID] == 42


async def test_several_schools_prompt_for_a_choice(
    hass: HomeAssistant, mock_search, mock_students
):
    mock_search.return_value = [SCHOOL, OTHER_SCHOOL]

    result = await _search(hass)
    assert result["step_id"] == "school"

    # Pick the second, not the first the search happened to return.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SCHOOL_ID: "1000"}
    )
    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    await hass.async_block_till_done()

    assert result["data"][CONF_SCHOOL_ID] == "1000"


async def test_no_school_match_is_recoverable(
    hass: HomeAssistant, mock_search, mock_students
):
    mock_search.return_value = []
    result = await _search(hass, "Nowhere")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"school": "school_not_found"}

    mock_search.return_value = [SCHOOL]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"school": "Example High"}
    )
    assert result["step_id"] == "credentials"


async def test_search_connection_error(hass: HomeAssistant, mock_search):
    mock_search.side_effect = SatchelConnectionError("down")
    result = await _search(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SatchelAuthError("nope"), "invalid_auth"),
        (SatchelConnectionError("down"), "cannot_connect"),
    ],
)
async def test_login_errors(
    hass: HomeAssistant, mock_search, mock_students, error, expected
):
    mock_students.side_effect = error
    result = await _search(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_account_without_pupils(hass: HomeAssistant, mock_search, mock_students):
    mock_students.return_value = []
    result = await _search(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["errors"] == {"base": "no_students"}


async def test_multiple_pupils_prompt_for_a_choice(
    hass: HomeAssistant, mock_search, mock_students
):
    mock_students.return_value = [ALEX, SAM]
    result = await _search(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["step_id"] == "pupil"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STUDENT_ID: "43"}
    )
    await hass.async_block_till_done()

    assert result["title"] == "Sam Example"
    assert result["data"][CONF_STUDENT_ID] == 43


async def test_duplicate_pupil_is_aborted(
    hass: HomeAssistant, mock_search, mock_students
):
    MockConfigEntry(domain=DOMAIN, unique_id="42", data=ENTRY_DATA).add_to_hass(hass)

    result = await _search(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_the_password(
    hass: HomeAssistant, mock_search, mock_students
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
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_MINUTES: 240}
    )
    await hass.async_block_till_done()

    assert result["data"][CONF_SCAN_MINUTES] == 240
    assert isinstance(result["data"][CONF_SCAN_MINUTES], int)
