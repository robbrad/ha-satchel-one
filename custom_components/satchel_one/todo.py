"""Satchel One to-do platform: homework as a native Home Assistant list.

Ticking an item here marks it complete in Satchel, so this is the one part of
the integration that writes back to the school's record.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SatchelConnectionError
from .coordinator import (
    SatchelConfigEntry,
    SatchelCoordinator,
    parse_due,
    task_url,
)
from .entity import SatchelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SatchelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Satchel One homework list."""
    async_add_entities([SatchelTodoList(entry.runtime_data, entry)])


def _describe(todo: dict[str, Any]) -> str | None:
    """A one-block description: type, subject, teacher, detail and a link."""
    parts = [
        todo.get("class_task_type"),
        todo.get("subject"),
        todo.get("teacher_name"),
    ]
    lines = [" - ".join(p for p in parts if p)]
    if detail := todo.get("class_task_description"):
        lines.append(str(detail))
    if url := task_url(todo):
        lines.append(url)
    return "\n".join(line for line in lines if line) or None


class SatchelTodoList(
    SatchelEntity, CoordinatorEntity[SatchelCoordinator], TodoListEntity
):
    """Every piece of homework for one pupil, as a to-do list."""

    _attr_translation_key = "homework"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(
        self, coordinator: SatchelCoordinator, entry: SatchelConfigEntry
    ) -> None:
        """Bind the list to its coordinator and pupil device."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_homework"

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Homework as to-do items, soonest due first."""
        if self.coordinator.data is None:
            return None
        items: list[tuple[Any, TodoItem]] = []
        for todo in self.coordinator.data.todos:
            due = parse_due(todo.get("due_on"))
            items.append(
                (
                    due,
                    TodoItem(
                        uid=str(todo.get("id")),
                        summary=todo.get("class_task_title") or "Homework",
                        status=TodoItemStatus.COMPLETED
                        if todo.get("completed")
                        else TodoItemStatus.NEEDS_ACTION,
                        due=due.date() if due else None,
                        description=_describe(todo),
                    ),
                )
            )
        # Undated tasks sort last rather than crashing the comparison.
        items.sort(key=lambda pair: (pair[0] is None, pair[0]))
        return [item for _due, item in items]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Write a completion change back to Satchel."""
        try:
            await self.coordinator.api.async_set_todo_completed(
                item.uid, item.status == TodoItemStatus.COMPLETED
            )
        except SatchelConnectionError as err:
            raise HomeAssistantError(
                f"Could not update homework in Satchel One: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
