"""Satchel One sensors: outstanding homework, overdue, next due, detentions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import (
    SatchelConfigEntry,
    SatchelCoordinator,
    SatchelData,
    parse_due,
)


def _todo_brief(todo: dict[str, Any]) -> dict[str, Any]:
    """The fields worth surfacing for one piece of homework."""
    return {
        "title": todo.get("class_task_title"),
        "subject": todo.get("subject"),
        "teacher": todo.get("teacher_name"),
        "due_on": todo.get("due_on"),
        "issued_at": todo.get("issued_at"),
        "type": todo.get("class_task_type"),
        "submission_status": todo.get("submission_status"),
        "has_attachments": todo.get("has_attachments"),
    }


def _outstanding_attrs(data: SatchelData) -> dict[str, Any]:
    return {"items": [_todo_brief(t) for t in data.outstanding[:20]]}


def _overdue_attrs(data: SatchelData) -> dict[str, Any]:
    return {"items": [_todo_brief(t) for t in data.overdue[:20]]}


def _next_due_value(data: SatchelData) -> Any:
    todo = data.due_next
    return parse_due(todo.get("due_on")) if todo else None


def _next_due_attrs(data: SatchelData) -> dict[str, Any]:
    todo = data.due_next
    if not todo:
        return {}
    attrs = _todo_brief(todo)
    due = parse_due(todo.get("due_on"))
    if due:
        delta = (due.date() - dt_util.now().date()).days
        attrs["days_until_due"] = delta
    return attrs


@dataclass(frozen=True, kw_only=True)
class SatchelSensorDescription(SensorEntityDescription):
    """A sensor description plus how to derive value/attributes from the data."""

    value_fn: Callable[[SatchelData], Any]
    attributes_fn: Callable[[SatchelData], dict[str, Any]] | None = None


SENSORS: tuple[SatchelSensorDescription, ...] = (
    SatchelSensorDescription(
        key="homework_outstanding",
        translation_key="homework_outstanding",
        icon="mdi:book-open-page-variant",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="tasks",
        value_fn=lambda data: len(data.outstanding),
        attributes_fn=_outstanding_attrs,
    ),
    SatchelSensorDescription(
        key="homework_overdue",
        translation_key="homework_overdue",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="tasks",
        value_fn=lambda data: len(data.overdue),
        attributes_fn=_overdue_attrs,
    ),
    SatchelSensorDescription(
        key="homework_next_due",
        translation_key="homework_next_due",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_fn=_next_due_value,
        attributes_fn=_next_due_attrs,
    ),
    SatchelSensorDescription(
        key="detentions",
        translation_key="detentions",
        icon="mdi:account-clock",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="detentions",
        value_fn=lambda data: len(data.detentions),
        attributes_fn=lambda data: {"items": data.detentions[:20]},
    ),
    SatchelSensorDescription(
        key="homework_due_this_week",
        translation_key="homework_due_this_week",
        icon="mdi:calendar-week",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="tasks",
        value_fn=lambda data: len(data.due_this_week),
        attributes_fn=lambda data: {
            "items": [_todo_brief(t) for t in data.due_this_week[:20]]
        },
    ),
    SatchelSensorDescription(
        key="behaviour_points",
        translation_key="behaviour_points",
        icon="mdi:star-circle",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: data.praise_summary.get("total_count"),
        attributes_fn=lambda data: {
            "positive_total": data.praise_summary.get("total_positive_count"),
            "negative_total": data.praise_summary.get("total_negative_count"),
            "positive_this_week": data.praise_summary.get("week_positive_count"),
            "negative_this_week": data.praise_summary.get("week_negative_count"),
            "positive_this_month": data.praise_summary.get("month_positive_count"),
            "negative_this_month": data.praise_summary.get("month_negative_count"),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SatchelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Satchel One sensors for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        SatchelSensor(coordinator, entry, description) for description in SENSORS
    )


class SatchelSensor(CoordinatorEntity[SatchelCoordinator], SensorEntity):
    """A single Satchel One value for one pupil."""

    entity_description: SatchelSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SatchelCoordinator,
        entry: SatchelConfigEntry,
        description: SatchelSensorDescription,
    ) -> None:
        """Bind the sensor to its coordinator and pupil device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        name = coordinator.data.student_name if coordinator.data else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Satchel One {name}" if name else "Satchel One",
            manufacturer="Satchel",
            model="Show My Homework",
        )

    @property
    def native_value(self) -> Any:
        """Return the current value for this sensor."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, if this sensor exposes any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
