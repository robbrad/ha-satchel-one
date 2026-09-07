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
    task_id: int | None = None,
    task_type: str = "Homework",
) -> dict:
    """Build a to-do the way the /api/todos endpoint returns one."""
    if due_on is None and due_in_days is not None:
        due_on = (NOW + timedelta(days=due_in_days)).isoformat()
    return {
        "id": task_id if task_id is not None else abs(hash(title)) % 100000,
        "class_task_title": title,
        "class_task_description": f"Do the {title} work",
        "subject": "Maths",
        "teacher_name": "Mr Example",
        "due_on": due_on,
        "issued_at": (NOW - timedelta(days=7)).isoformat(),
        "class_task_type": task_type,
        "submission_status": "not_submitted",
        "has_attachments": False,
        "completed": completed,
    }


def lesson(
    subject: str,
    *,
    start_hour: int,
    end_hour: int,
    day_offset: int = 0,
    lesson_id: int = 1,
    room: str = "M7",
) -> dict:
    """Build a lesson the way the timetable endpoint returns one."""
    day = (NOW + timedelta(days=day_offset)).date()
    return {
        "id": lesson_id,
        "url": None,
        "classGroup": {"subject": subject, "name": "7GD", "id": 12407856},
        "period": {
            "startDateTime": f"{day}T{start_hour:02d}:00:00+00:00",
            "endDateTime": f"{day}T{end_hour:02d}:00:00+00:00",
            "session": "AM",
        },
        "room": room,
        "teacher": {
            "title": "Mr",
            "forename": "Alan",
            "surname": "Turing",
            "name": "Mr A Turing",
        },
        "dueClassTasks": [],
    }


def praise(points: int, *, praise_id: int = 1, reason: str = "Great work") -> dict:
    """Build a behaviour event the way /api/student_praises returns one."""
    return {
        "id": praise_id,
        "score": points,
        "comments": reason,
        "category": "Effort",
        "teacher_name": "Mr Example",
        "created_at": NOW.isoformat(),
    }


@pytest.fixture(autouse=True)
def frozen_now(freezer):
    """Freeze the whole clock, not just the coordinator's view of it.

    The calendar entity schedules its next update from the current event's end
    time. Patching only the coordinator left Home Assistant's own clock live,
    so fixture lessons looked long finished and the timer re-fired in a tight
    loop. Freezing globally keeps both in step.
    """
    freezer.move_to(NOW)
    yield NOW


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/satchel_one in every test."""
    yield
