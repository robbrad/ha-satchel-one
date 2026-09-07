"""Tests for resolving a school name to the school_id the token grant needs."""

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.satchel_one.config_flow import _resolve_school
from custom_components.satchel_one.const import WEB_BASE

SEARCH_URL = re.compile(rf"^{re.escape(WEB_BASE)}/v7/login\?.*$")
SCHOOL_URL = f"{WEB_BASE}/v7/login/example-high-school"

SEARCH_RESULTS = """
<turbo-stream action="replace" target="schools">
  <template>
    <a href="/v7/login/example-high-school">Example High School</a>
    <a href="/v7/login/other-school">Other School</a>
  </template>
</turbo-stream>
"""

SCHOOL_PAGE = """
<form action="/v7/login/example-high-school" method="post">
  <input type="hidden" name="session[school_id]" value="999" />
  <input name="session[login]" />
</form>
"""


@pytest.fixture
def mock_http():
    with aioresponses() as mocked:
        yield mocked


async def test_resolves_the_first_match(hass, mock_http):
    mock_http.get(SEARCH_URL, body=SEARCH_RESULTS)
    mock_http.get(SCHOOL_URL, body=SCHOOL_PAGE)

    assert await _resolve_school(hass, "Example High") == "999"


async def test_no_matching_school(hass, mock_http):
    mock_http.get(SEARCH_URL, body="<turbo-stream></turbo-stream>")

    assert await _resolve_school(hass, "Nowhere") is None


async def test_school_page_without_the_hidden_field(hass, mock_http):
    mock_http.get(SEARCH_URL, body=SEARCH_RESULTS)
    mock_http.get(SCHOOL_URL, body="<form></form>")

    assert await _resolve_school(hass, "Example High") is None


async def test_search_failure_returns_none(hass, mock_http):
    mock_http.get(SEARCH_URL, exception=aiohttp.ClientError("boom"))

    assert await _resolve_school(hass, "Example High") is None


async def test_school_page_failure_returns_none(hass, mock_http):
    mock_http.get(SEARCH_URL, body=SEARCH_RESULTS)
    mock_http.get(SCHOOL_URL, exception=aiohttp.ClientError("boom"))

    assert await _resolve_school(hass, "Example High") is None
