"""Tests for the pupil data model: outstanding, overdue and due-date windows."""

from datetime import UTC, datetime

import pytest

from custom_components.satchel_one.coordinator import (
    SatchelData,
    parse_due,
    pupil_name,
)

from .conftest import NOW, todo


@pytest.fixture
def data():
    """A pupil with a mix of done, overdue, imminent and distant homework."""
    return SatchelData(
        student_id=42,
        student_name="Alex Example",
        todos=[
            todo("Overdue essay", due_in_days=-3),
            todo("Due tomorrow", due_in_days=1),
            todo("Due in 6 days", due_in_days=6),
            todo("Due in 30 days", due_in_days=30),
            todo("Already handed in", due_in_days=-1, completed=True),
            todo("No due date", due_on=None),
        ],
    )


def test_outstanding_excludes_completed(data):
    titles = [t["class_task_title"] for t in data.outstanding]
    assert "Already handed in" not in titles
    assert len(data.outstanding) == 5


def test_overdue_is_past_due_and_not_completed(data):
    assert [t["class_task_title"] for t in data.overdue] == ["Overdue essay"]


def test_due_next_picks_the_soonest(data):
    # The overdue essay is the soonest due date of all, including past ones.
    assert data.due_next["class_task_title"] == "Overdue essay"


def test_due_next_is_none_without_dates():
    assert SatchelData(todos=[todo("No due date", due_on=None)]).due_next is None


def test_due_this_week_is_the_next_seven_days(data):
    titles = [t["class_task_title"] for t in data.due_this_week]
    # Not the overdue one (past), not the 30-day one (beyond the horizon).
    assert titles == ["Due tomorrow", "Due in 6 days"]


def test_empty_data_is_all_empty():
    data = SatchelData()
    assert data.outstanding == []
    assert data.overdue == []
    assert data.due_this_week == []
    assert data.due_next is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-10T23:59:59+00:00", datetime(2026, 9, 10, 23, 59, 59, tzinfo=UTC)),
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_due(value, expected):
    assert parse_due(value) == expected


def test_parse_due_accepts_a_bare_date_and_returns_aware():
    parsed = parse_due("2026-09-10")
    assert parsed is not None
    # A timestamp sensor rejects naive datetimes, so this must carry a tzinfo.
    assert parsed.tzinfo is not None
    assert parsed.date() == datetime(2026, 9, 10).date()


def test_parse_due_localises_a_naive_timestamp():
    assert parse_due("2026-09-10T12:00:00").tzinfo is not None


@pytest.mark.parametrize(
    ("pupil", "expected"),
    [
        ({"forename": "Alex", "surname": "Example"}, "Alex Example"),
        ({"forename": "Alex"}, "Alex"),
        ({"surname": "Example"}, "Example"),
        ({}, None),
        ({"forename": None, "surname": None}, None),
    ],
)
def test_pupil_name(pupil, expected):
    assert pupil_name(pupil) == expected


def test_now_is_frozen(frozen_now):
    assert frozen_now == NOW
