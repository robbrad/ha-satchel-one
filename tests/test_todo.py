"""Tests for the homework to-do list, including writing back to Satchel."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.todo import TodoItemStatus
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.satchel_one.api import SatchelConnectionError
from custom_components.satchel_one.const import (
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DOMAIN,
)

from .conftest import todo

ALEX = {"id": 42, "forename": "Alex", "surname": "Example"}
ENTITY = "todo.satchel_one_alex_example_homework"

TODOS = [
    todo("Due later", due_in_days=5, task_id=2),
    todo("Due sooner", due_in_days=1, task_id=1),
    todo("No due date", due_on=None, task_id=3),
    todo("Already done", due_in_days=-1, completed=True, task_id=4),
]


@pytest.fixture
def mock_set():
    with patch(
        "custom_components.satchel_one.coordinator.SatchelApi.async_set_todo_completed",
        new=AsyncMock(),
    ) as mocked:
        yield mocked


@pytest.fixture
async def entry(hass: HomeAssistant, mock_set):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="42",
        data={
            CONF_USERNAME: "parent@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_SCHOOL_ID: "999",
            CONF_STUDENT_ID: 42,
        },
    )
    entry.add_to_hass(hass)
    p = "custom_components.satchel_one.coordinator.SatchelApi"
    with (
        patch(f"{p}.async_get_students", new=AsyncMock(return_value=[ALEX])),
        patch(f"{p}.async_get_todos", new=AsyncMock(return_value=TODOS)),
        patch(f"{p}.async_get_detentions", new=AsyncMock(return_value=[])),
        patch(f"{p}.async_get_praise_summary", new=AsyncMock(return_value={})),
        patch(f"{p}.async_get_praises", new=AsyncMock(return_value=[])),
        patch(f"{p}.async_get_events", new=AsyncMock(return_value=[])),
        patch(f"{p}.async_get_lessons", new=AsyncMock(return_value=[])),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


async def test_state_counts_only_outstanding(hass: HomeAssistant, entry):
    # The completed task is listed but must not count towards the badge.
    assert hass.states.get(ENTITY).state == "3"


async def test_items_are_sorted_by_due_date(hass: HomeAssistant, entry):
    items = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": ENTITY},
        blocking=True,
        return_response=True,
    )
    summaries = [i["summary"] for i in items[ENTITY]["items"]]
    # Strictly by due date - "Already done" is due yesterday, so it leads.
    # Home Assistant's to-do card groups completed items separately anyway.
    # Undated homework sorts last rather than breaking the comparison.
    assert summaries == ["Already done", "Due sooner", "Due later", "No due date"]


async def test_completed_status_is_reflected(hass: HomeAssistant, entry):
    items = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": ENTITY},
        blocking=True,
        return_response=True,
    )
    by_summary = {i["summary"]: i for i in items[ENTITY]["items"]}
    assert by_summary["Already done"]["status"] == TodoItemStatus.COMPLETED
    assert by_summary["Due sooner"]["status"] == TodoItemStatus.NEEDS_ACTION


async def test_description_carries_detail_and_link(hass: HomeAssistant, entry):
    items = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": ENTITY},
        blocking=True,
        return_response=True,
    )
    desc = next(i for i in items[ENTITY]["items"] if i["summary"] == "Due sooner")[
        "description"
    ]
    assert "Homework - Maths - Mr Example" in desc
    assert "https://www.satchelone.com/school/homeworks/1" in desc


async def test_ticking_an_item_writes_back_to_satchel(
    hass: HomeAssistant, entry, mock_set
):
    await hass.services.async_call(
        "todo",
        "update_item",
        {"item": "Due sooner", "status": "completed"},
        target={"entity_id": ENTITY},
        blocking=True,
    )
    mock_set.assert_awaited_once_with("1", True)


async def test_unticking_an_item_writes_back(hass: HomeAssistant, entry, mock_set):
    await hass.services.async_call(
        "todo",
        "update_item",
        {"item": "Already done", "status": "needs_action"},
        target={"entity_id": ENTITY},
        blocking=True,
    )
    mock_set.assert_awaited_once_with("4", False)


async def test_api_failure_surfaces_to_the_user(hass: HomeAssistant, entry, mock_set):
    mock_set.side_effect = SatchelConnectionError("down")
    with pytest.raises(HomeAssistantError, match="Could not update homework"):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "Due sooner", "status": "completed"},
            target={"entity_id": ENTITY},
            blocking=True,
        )
