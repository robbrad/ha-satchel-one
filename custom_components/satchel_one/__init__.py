"""The Satchel One (Show My Homework) integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES
from .coordinator import SatchelConfigEntry, SatchelCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.TODO,
]


async def async_setup_entry(hass: HomeAssistant, entry: SatchelConfigEntry) -> bool:
    """Set up Satchel One from a config entry."""
    minutes = entry.options.get(
        CONF_SCAN_MINUTES, entry.data.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
    )
    coordinator = SatchelCoordinator(hass, entry, timedelta(minutes=minutes))
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SatchelConfigEntry) -> bool:
    """Unload a config entry.

    The aiohttp session is Home Assistant's shared one, so it is deliberately
    not closed here.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SatchelConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
