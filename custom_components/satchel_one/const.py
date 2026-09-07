"""Constants for the Satchel One (Show My Homework) integration."""

from __future__ import annotations

DOMAIN = "satchel_one"

# The public SPA ships these client credentials in its JS bundle; the API has no
# other client and the OAuth2 password grant requires them.
CLIENT_ID = "55283c8c45d97ffd88eb9f87e13f390675c75d22b4f2085f43b0d7355c1f"
CLIENT_SECRET = "c8f7d8fcd0746adc50278bc89ed6f004402acbbf4335d3cb12d6ac6497d3"

WEB_BASE = "https://www.satchelone.com"
API_BASE = "https://api.satchelone.com"
TOKEN_URL = f"{API_BASE}/oauth/token"

# The API version is carried as a vendor media type in the Accept header.
API_VERSION = "2021.5"
API_ACCEPT = f"application/smhw.v{API_VERSION}+json"

CONF_SCHOOL_ID = "school_id"
CONF_STUDENT_ID = "student_id"
CONF_SCAN_MINUTES = "scan_minutes"

DEFAULT_SCAN_MINUTES = 60
MIN_SCAN_MINUTES = 15
MAX_SCAN_MINUTES = 1440

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
