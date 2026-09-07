"""Shared fixtures for the Satchel One tests."""

from datetime import UTC, datetime, timedelta

import pytest

# All time-based assertions hang off this instant.
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def todo(
    title: str,
    *,
    due_in_days: float | None = None,
    completed: bool = False,
    due_on: str | None = None,
) -> dict:
    """Build a to-do the way the /api/todos endpoint returns one."""
    if due_on is None and due_in_days is not None:
        due_on = (NOW + timedelta(days=due_in_days)).isoformat()
    return {
        "class_task_title": title,
        "subject": "Maths",
        "teacher_name": "Mr Example",
        "due_on": due_on,
        "issued_at": (NOW - timedelta(days=7)).isoformat(),
        "class_task_type": "Homework",
        "submission_status": "not_submitted",
        "has_attachments": False,
        "completed": completed,
    }


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    """Pin dt_util.now() in the coordinator so due-date windows are stable."""
    from custom_components.satchel_one import coordinator

    monkeypatch.setattr(coordinator.dt_util, "now", lambda: NOW)
    yield NOW


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/satchel_one in every test."""
    yield
