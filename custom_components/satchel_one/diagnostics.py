"""Diagnostics for Satchel One.

Returns a snapshot that is useful in a bug report without exposing the
account's credentials or the child's personal details.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_SCHOOL_ID, CONF_STUDENT_ID
from .coordinator import SatchelConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, CONF_SCHOOL_ID, CONF_STUDENT_ID}


def _shape(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Keep only structural/enum fields, never free text or names."""
    return [{k: row.get(k) for k in keys} for row in rows[:20]]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SatchelConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "version": entry.version,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "counts": {
            "todos": len(data.todos),
            "outstanding": len(data.outstanding),
            "overdue": len(data.overdue),
            "due_this_week": len(data.due_this_week),
            "detentions": len(data.detentions),
            "detentions_today": len(data.detentions_today),
            "praises": len(data.praises),
            "events": len(data.events),
            "lessons": len(data.lessons),
        },
        # Field names only, so a maintainer can see whether Satchel changed the
        # API shape without the reporter leaking their child's homework.
        "sample_keys": {
            "todo": sorted(data.todos[0]) if data.todos else [],
            "detention": sorted(data.detentions[0]) if data.detentions else [],
            "praise": sorted(data.praises[0]) if data.praises else [],
            "lesson": sorted(data.lessons[0]) if data.lessons else [],
            "praise_summary": sorted(data.praise_summary),
        },
        "todos": _shape(
            data.todos,
            ("id", "class_task_type", "completed", "due_on", "submission_status"),
        ),
    }
