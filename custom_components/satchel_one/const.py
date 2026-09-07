"""Constants for the Satchel One (Show My Homework) integration."""

from __future__ import annotations

DOMAIN = "satchel_one"

# The public SPA ships these client credentials in its JS bundle; the API has no
# other client and the OAuth2 password grant requires them.
CLIENT_ID = "55283c8c45d97ffd88eb9f87e13f390675c75d22b4f2085f43b0d7355c1f"
CLIENT_SECRET = "c8f7d8fcd0746adc50278bc89ed6f004402acbbf4335d3cb12d6ac6497d3"

WEB_BASE = "https://www.satchelone.com"
API_BASE = "https://api.satchelone.com"
# The token endpoint lives at the domain root. Posting to /api/oauth/token hits
# a CDN-fronted route that never authenticates.
TOKEN_URL = f"{API_BASE}/oauth/token"
API_ROOT = f"{API_BASE}/api"

# The API version is carried as a vendor media type in the Accept header.
API_VERSION = "2021.5"
API_ACCEPT = f"application/smhw.v{API_VERSION}+json"

CONF_SCHOOL_ID = "school_id"
CONF_STUDENT_ID = "student_id"
CONF_SCAN_MINUTES = "scan_minutes"

DEFAULT_SCAN_MINUTES = 60
MIN_SCAN_MINUTES = 15
MAX_SCAN_MINUTES = 1440

# How far ahead the "due this week" sensor looks.
DUE_SOON_DAYS = 7

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Events fired on the Home Assistant bus so automations do not have to poll
# sensor attributes to notice something new.
EVENT_NEW_HOMEWORK = f"{DOMAIN}_new_homework"
EVENT_HOMEWORK_COMPLETED = f"{DOMAIN}_homework_completed"
EVENT_NEW_DETENTION = f"{DOMAIN}_new_detention"
EVENT_BEHAVIOUR_POINT = f"{DOMAIN}_behaviour_point"

# Satchel's own web routes, used to deep-link a task from a notification.
TASK_WEB_PATHS = {
    "Homework": "homeworks",
    "Classwork": "classworks",
    "FlexibleTask": "flexible-tasks",
    "Quiz": "quizzes",
    "Spelling": "spelling-tests",
}
