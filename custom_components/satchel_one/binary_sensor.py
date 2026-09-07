"""Satchel One binary sensors: the yes/no questions worth automating on."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SatchelConfigEntry, SatchelCoordinator, SatchelData
from .entity import SatchelEntity


@dataclass(frozen=True, kw_only=True)
class SatchelBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor plus how to derive its state from the data."""

    value_fn: Callable[[SatchelData], bool]
    attributes_fn: Callable[[SatchelData], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[SatchelBinarySensorDescription, ...] = (
    SatchelBinarySensorDescription(
        key="homework_overdue",
        translation_key="has_overdue_homework",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:alert-circle-outline",
        value_fn=lambda data: bool(data.overdue),
        attributes_fn=lambda data: {"count": len(data.overdue)},
    ),
    SatchelBinarySensorDescription(
        key="detention_today",
        translation_key="detention_today",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:account-clock",
        value_fn=lambda data: bool(data.detentions_today),
        attributes_fn=lambda data: {"count": len(data.detentions_today)},
    ),
    SatchelBinarySensorDescription(
        key="homework_due_today",
        translation_key="homework_due_today",
        icon="mdi:calendar-today",
        value_fn=lambda data: any(
            (due := t.get("due_on")) and str(due)[:10] == _today()
            for t in data.outstanding
        ),
    ),
)


def _today() -> str:
    from homeassistant.util import dt as dt_util

    return dt_util.now().date().isoformat()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SatchelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Satchel One binary sensors."""
    async_add_entities(
        SatchelBinarySensor(entry.runtime_data, entry, description)
        for description in BINARY_SENSORS
    )


class SatchelBinarySensor(
    SatchelEntity, CoordinatorEntity[SatchelCoordinator], BinarySensorEntity
):
    """One yes/no Satchel One value for a pupil."""

    entity_description: SatchelBinarySensorDescription

    def __init__(
        self,
        coordinator: SatchelCoordinator,
        entry: SatchelConfigEntry,
        description: SatchelBinarySensorDescription,
    ) -> None:
        """Bind the sensor to its coordinator and pupil device."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, if this sensor exposes any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
