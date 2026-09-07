"""Tests for the reverse-engineered Satchel One client.

The two quirks worth locking down: data calls must use ``smhw_token`` (not
``access_token``), and a 401 must be retried once with the refresh token
rather than re-sending the password.
"""

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.satchel_one.api import (
    SatchelApi,
    SatchelAuthError,
    SatchelConnectionError,
)
from custom_components.satchel_one.const import API_BASE

# The token URL carries the SPA client_id/client_secret as query params,
# so match it by pattern rather than by exact string.
TOKEN_URL = re.compile(r"^https://api\.satchelone\.com/oauth/token.*$")

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


async def test_login_sends_the_school_id(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    await api.async_login()

    request = next(iter(mock_http.requests.values()))[0]
    body = request.kwargs["data"]
    # Without school_id the server answers invalid_credentials, even for a
    # correct password - so this field must always be present.
    assert body["school_id"] == "999"
    assert body["grant_type"] == "password"
    assert body["username"] == "parent@example.com"


async def test_data_calls_use_smhw_token_not_access_token(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(f"{API_BASE}/api/students", payload={"students": [{"id": 42}]})

    assert await api.async_get_students() == [{"id": 42}]

    get_request = next(
        call
        for key, calls in mock_http.requests.items()
        for call in calls
        if key[0] == "GET"
    )
    assert get_request.kwargs["headers"]["Authorization"] == "Bearer smhw-token-value"
    # The API version travels as a vendor media type, not a query parameter.
    assert get_request.kwargs["headers"]["Accept"].startswith("application/smhw.v")


async def test_expired_token_is_refreshed_without_the_password(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(f"{API_BASE}/api/students", status=401, payload={})
    mock_http.post(TOKEN_URL, payload={**GRANT, "smhw_token": "second-token"})
    mock_http.get(f"{API_BASE}/api/students", payload={"students": [{"id": 42}]})

    assert await api.async_get_students() == [{"id": 42}]

    grants = [
        call
        for key, calls in mock_http.requests.items()
        for call in calls
        if key[0] == "POST"
    ]
    assert grants[1].kwargs["data"]["grant_type"] == "refresh_token"
    assert "password" not in grants[1].kwargs["data"]


async def test_still_401_after_refresh_is_an_auth_error(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(f"{API_BASE}/api/students", status=401, payload={})
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(f"{API_BASE}/api/students", status=401, payload={})

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
    mock_http.get(f"{API_BASE}/api/students", status=500, payload={})

    with pytest.raises(SatchelConnectionError):
        await api.async_get_students()


@pytest.mark.parametrize(
    ("method", "path", "payload", "expected"),
    [
        ("async_get_todos", "/api/todos", {"todos": [{"id": 1}]}, [{"id": 1}]),
        (
            "async_get_detentions",
            "/api/detentions",
            {"detentions": [{"id": 2}]},
            [{"id": 2}],
        ),
        ("async_get_events", "/api/events", {"events": [{"id": 3}]}, [{"id": 3}]),
    ],
)
async def test_list_endpoints(api, mock_http, method, path, payload, expected):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(f"{API_BASE}{path}?student_id=42", payload=payload)

    assert await getattr(api, method)(42) == expected


async def test_list_endpoints_tolerate_an_unexpected_shape(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(f"{API_BASE}/api/todos?student_id=42", payload=[])

    assert await api.async_get_todos(42) == []


async def test_praise_summary_is_unwrapped(api, mock_http):
    mock_http.post(TOKEN_URL, payload=GRANT)
    mock_http.get(
        f"{API_BASE}/api/student_praise_summaries/42",
        payload={"student_praise_summary": {"total_count": 7}},
    )

    assert await api.async_get_praise_summary(42) == {"total_count": 7}
