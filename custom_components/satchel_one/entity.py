"""Shared device wiring for every Satchel One entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class SatchelEntity(CoordinatorEntity):
    """Attaches an entity to the device representing one pupil."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry) -> None:
        """Group every platform's entities under a single pupil device."""
        super().__init__(coordinator)
        name = coordinator.data.student_name if coordinator.data else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Satchel One {name}" if name else "Satchel One",
            manufacturer="Satchel",
            model="Show My Homework",
            configuration_url="https://www.satchelone.com",
        )
