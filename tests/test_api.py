"""Tests for the reverse-engineered Satchel One client.

Quirks worth locking down: data calls must use ``smhw_token`` (not
``access_token``), a 401 must be retried once with the refresh token rather
than re-sending the password, and every GET must be cache-busted because the
CDN in front of the API caches failures.
"""

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.satchel_one.api import (
    SatchelApi,
    SatchelAuthError,
    SatchelConnectionError,
    lesson_times,
)

from .conftest import lesson

API = r"https://api\.satchelone\.com/api"
TOKEN_URL = re.compile(r"^https://api\.satchelone\.com/oauth/token.*$")


def url(path: str) -> re.Pattern:
    """Match an API path regardless of the cache-buster and other params."""
    return re.compile(rf"^{API}{path}(\?.*)?$")


GRANT = {
    "access_token": "access-token-value",
    "smhw_token": "smhw-token-value",
    "refresh_token": "refresh-token-value",
}


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
def api(session):
    return SatchelApi(session, "parent@example.com", "hunter2", "999")


@pytest.fixture
def mock_http():
    with aioresponses() as mocked:
        yield mocked


def _calls(mock_http, method):
    return [
        call
        for key, calls in mock_http.requests.items()
        for call in calls
        if key[0] == method
    ]


async def test_login_sends_the_school_id(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    await api.async_login()

    body = _calls(mock_http, "POST")[0].kwargs["data"]
    # Without school_id the server answers invalid_credentials even for a
    # correct password.
    assert body["school_id"] == "999"
    assert body["grant_type"] == "password"


async def test_data_calls_use_smhw_token_not_access_token(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/students"), payload={"students": [{"id": 42}]})

    assert await api.async_get_students() == [{"id": 42}]

    headers = _calls(mock_http, "GET")[0].kwargs["headers"]
    assert headers["Authorization"] == "Bearer smhw-token-value"
    assert headers["Accept"].startswith("application/smhw.v")


async def test_every_get_is_cache_busted(api, mock_http):
    """The CDN caches failures, so requests must never be byte-identical."""
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/students"), payload={"students": []})

    await api.async_get_students()

    assert "_cb" in _calls(mock_http, "GET")[0].kwargs["params"]


async def test_todos_ask_for_dateless_and_past_tasks(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/todos"), payload={"todos": [{"id": 1}]})

    assert await api.async_get_todos(42) == [{"id": 1}]

    params = _calls(mock_http, "GET")[0].kwargs["params"]
    # Without these the API drops undated homework and anything already due.
    assert params["add_dateless"] == "true"
    assert params["student_id"] == 42
    assert params["from"] == "2000-01-01"


async def test_set_todo_completed_writes_back(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.put(url("/todos/7"), payload={})

    await api.async_set_todo_completed(7, True)

    put = _calls(mock_http, "PUT")[0]
    assert put.kwargs["json"] == {"todo": {"completed": True}}
    assert put.kwargs["headers"]["Authorization"] == "Bearer smhw-token-value"


async def test_set_todo_completed_can_uncomplete(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.put(url("/todos/7"), payload={})

    await api.async_set_todo_completed(7, False)

    assert _calls(mock_http, "PUT")[0].kwargs["json"] == {"todo": {"completed": False}}


async def test_put_failure_raises_connection_error(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.put(url("/todos/7"), status=500, payload={})

    with pytest.raises(SatchelConnectionError):
        await api.async_set_todo_completed(7, True)


async def test_expired_token_is_refreshed_without_the_password(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/students"), status=401, payload={})
    mock_http.post(TOKEN_URL, payload={**GRANT, "smhw_token": "second-token"})
    mock_http.get(url("/students"), payload={"students": [{"id": 42}]})

    assert await api.async_get_students() == [{"id": 42}]

    grants = _calls(mock_http, "POST")
    assert grants[1].kwargs["data"]["grant_type"] == "refresh_token"
    assert "password" not in grants[1].kwargs["data"]


async def test_still_401_after_refresh_is_an_auth_error(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/students"), status=401, payload={}, repeat=True)
    mock_http.post(TOKEN_URL, payload=GRANT)

    with pytest.raises(SatchelAuthError):
        await api.async_get_students()


async def test_rejected_credentials_raise_auth_error(api, mock_http):
    mock_http.post(TOKEN_URL, status=401, payload={"errors": ["invalid_credentials"]})
    with pytest.raises(SatchelAuthError):
        await api.async_login()


async def test_grant_without_a_token_raises_auth_error(api, mock_http):
    mock_http.post(TOKEN_URL, payload={"errors": ["invalid_credentials"]})
    with pytest.raises(SatchelAuthError):
        await api.async_login()


async def test_network_failure_raises_connection_error(api, mock_http):
    mock_http.post(TOKEN_URL, exception=aiohttp.ClientError("boom"))
    with pytest.raises(SatchelConnectionError):
        await api.async_login()


async def test_server_error_raises_connection_error(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/students"), status=500, payload={})
    with pytest.raises(SatchelConnectionError):
        await api.async_get_students()


@pytest.mark.parametrize(
    ("method", "path", "payload", "expected"),
    [
        (
            "async_get_detentions",
            "/detentions",
            {"detentions": [{"id": 2}]},
            [{"id": 2}],
        ),
        ("async_get_events", "/events", {"events": [{"id": 3}]}, [{"id": 3}]),
        (
            "async_get_praises",
            "/student_praises",
            {"student_praises": [{"id": 4}]},
            [{"id": 4}],
        ),
    ],
)
async def test_list_endpoints(api, mock_http, method, path, payload, expected):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url(path), payload=payload)
    assert await getattr(api, method)(42) == expected


async def test_list_endpoints_tolerate_an_unexpected_shape(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(url("/todos"), payload=[])
    assert await api.async_get_todos(42) == []


async def test_praise_summary_is_unwrapped(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(
        url("/student_praise_summaries/42"),
        payload={"student_praise_summary": {"total_count": 7}},
    )
    assert await api.async_get_praise_summary(42) == {"total_count": 7}


async def test_lessons_walk_week_by_week(api, mock_http):
    """The timetable endpoint is week-based, so a fortnight needs two calls."""
    import datetime

    mock_http.post(TOKEN_URL, payload=GRANT)
    week = {
        "weeks": [
            {
                "days": [
                    {
                        "lessons": [
                            lesson("Maths", start_hour=9, end_hour=10, lesson_id=1)
                        ]
                    }
                ]
            }
        ]
    }
    week2 = {
        "weeks": [
            {
                "days": [
                    {
                        "lessons": [
                            lesson("English", start_hour=9, end_hour=10, lesson_id=2)
                        ]
                    }
                ]
            }
        ]
    }
    pattern = url("/timetable/school/999/student/42")
    mock_http.get(pattern, payload=week)
    mock_http.get(pattern, payload=week2)

    lessons = await api.async_get_lessons(
        42, datetime.date(2026, 9, 7), datetime.date(2026, 9, 18)
    )

    assert [x["id"] for x in lessons] == [1, 2]
    assert len(_calls(mock_http, "GET")) == 2


async def test_lessons_deduplicate_across_weeks(api, mock_http):
    """Overlapping weeks return the same lesson twice; it must appear once."""
    import datetime

    mock_http.post(TOKEN_URL, payload=GRANT)
    same = {
        "weeks": [
            {
                "days": [
                    {
                        "lessons": [
                            lesson("Maths", start_hour=9, end_hour=10, lesson_id=1)
                        ]
                    }
                ]
            }
        ]
    }
    pattern = url("/timetable/school/999/student/42")
    mock_http.get(pattern, payload=same, repeat=True)

    lessons = await api.async_get_lessons(
        42, datetime.date(2026, 9, 7), datetime.date(2026, 9, 18)
    )
    assert [x["id"] for x in lessons] == [1]


def test_lesson_times_parses_the_period():
    start, end = lesson_times(lesson("Maths", start_hour=9, end_hour=10))
    assert start.hour == 9
    assert end.hour == 10


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"period": {}},
        {"period": {"startDateTime": "not-a-date", "endDateTime": None}},
    ],
)
def test_lesson_times_tolerates_bad_input(bad):
    assert lesson_times(bad) == (None, None)
