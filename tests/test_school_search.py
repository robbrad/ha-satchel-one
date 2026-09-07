"""Tests for the public school-directory search.

The payload shape here matches a real response from
``GET /api/public/school_search``.
"""

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.satchel_one.api import (
    SatchelConnectionError,
    async_search_schools,
)

SEARCH_URL = re.compile(r"^https://api\.satchelone\.com/api/public/school_search.*$")

PAYLOAD = {
    "schools": [
        {
            "id": 7,
            "name": "Panda Academy",
            "town": "London",
            "post_code": "N1 1AA",
            "address": "1 Test St",
            "is_active": True,
            "subdomain": "panda",
            "brand_color": "#123456",
        },
        {
            "id": 43429,
            "name": "John Paul Academy",
            "town": "Glasgow City",
            "post_code": "G15 6LP",
            "address": "2 Test St",
            "is_active": True,
            "subdomain": "jpa",
            "brand_color": "#654321",
        },
        {
            "id": 999,
            "name": "Closed School",
            "town": "Nowhere",
            "post_code": "ZZ1 1ZZ",
            "address": "3 Test St",
            "is_active": False,
            "subdomain": "closed",
            "brand_color": "#000000",
        },
    ]
}


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
def mock_http():
    with aioresponses() as mocked:
        yield mocked


async def test_returns_matches_with_ids(session, mock_http):
    mock_http.get(SEARCH_URL, payload=PAYLOAD)

    schools = await async_search_schools(session, "academy")

    # The school_id needed by the password grant comes straight back - no
    # second request and no HTML parsing.
    assert [s["id"] for s in schools] == [7, 43429]
    assert schools[0]["town"] == "London"
    assert schools[0]["post_code"] == "N1 1AA"


async def test_inactive_schools_are_dropped(session, mock_http):
    mock_http.get(SEARCH_URL, payload=PAYLOAD)

    schools = await async_search_schools(session, "academy")

    # A closed school cannot be logged into, so offering it only misleads.
    assert all(s["name"] != "Closed School" for s in schools)


async def test_sends_the_filter_and_limit(session, mock_http):
    mock_http.get(SEARCH_URL, payload=PAYLOAD)

    await async_search_schools(session, "Example High", limit=5)

    request = next(iter(mock_http.requests.values()))[0]
    query = request.kwargs["params"]
    assert query["filter"] == "Example High"
    assert query["limit"] == 5


async def test_no_matches(session, mock_http):
    mock_http.get(SEARCH_URL, payload={"schools": []})
    assert await async_search_schools(session, "Nowhere") == []


async def test_unexpected_shape_is_tolerated(session, mock_http):
    mock_http.get(SEARCH_URL, payload=[])
    assert await async_search_schools(session, "x") == []


async def test_http_error_raises_connection_error(session, mock_http):
    mock_http.get(SEARCH_URL, status=500, payload={})
    with pytest.raises(SatchelConnectionError):
        await async_search_schools(session, "x")


async def test_network_failure_raises_connection_error(session, mock_http):
    mock_http.get(SEARCH_URL, exception=aiohttp.ClientError("boom"))
    with pytest.raises(SatchelConnectionError):
        await async_search_schools(session, "x")


async def test_search_needs_no_authentication(session, mock_http):
    """The directory is public; sending a bearer token is not required."""
    mock_http.get(SEARCH_URL, payload=PAYLOAD)
    await async_search_schools(session, "academy")

    request = next(iter(mock_http.requests.values()))[0]
    assert "Authorization" not in request.kwargs["headers"]
