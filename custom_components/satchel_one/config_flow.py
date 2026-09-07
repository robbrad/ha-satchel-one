"""Config and options flow for Satchel One: resolve the school, then sign in."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from bs4 import BeautifulSoup
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SatchelApi, SatchelAuthError, SatchelConnectionError
from .const import (
    CONF_SCAN_MINUTES,
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    MAX_SCAN_MINUTES,
    MIN_SCAN_MINUTES,
    USER_AGENT,
    WEB_BASE,
)
from .coordinator import SatchelConfigEntry, pupil_name

CONF_SCHOOL = "school"

_SLUG_RE = re.compile(r'href="/v7/login/([a-z0-9\-]+)"')


def _interval_selector() -> NumberSelector:
    """The shared poll-interval control, in minutes."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SCAN_MINUTES,
            max=MAX_SCAN_MINUTES,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCHOOL): TextSelector(),
        vol.Required(CONF_USERNAME): TextSelector(),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_SCAN_MINUTES, default=DEFAULT_SCAN_MINUTES): (
            _interval_selector()
        ),
    }
)


async def _resolve_school(hass, query: str) -> str | None:
    """Return the numeric school_id for a school-name search, or None.

    The password grant needs a school_id, but parents only know the school's
    name. Satchel's public login page exposes the mapping: searching returns a
    turbo-stream fragment of matching schools, and each school's login page
    carries its id in a hidden ``session[school_id]`` field.
    """
    session = async_create_clientsession(hass)
    try:
        async with session.get(
            f"{WEB_BASE}/v7/login",
            params={"filters[search]": query, "table": "mis/public/login/table"},
            headers={
                "Accept": "text/vnd.turbo-stream.html",
                "User-Agent": USER_AGENT,
            },
        ) as resp:
            html = await resp.text()
        match = _SLUG_RE.search(html)
        if not match:
            return None
        async with session.get(
            f"{WEB_BASE}/v7/login/{match.group(1)}",
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            page = await resp.text()
    except ClientError:
        return None
    finally:
        await session.close()

    field = BeautifulSoup(page, "html.parser").find(
        "input", attrs={"name": "session[school_id]"}
    )
    return field["value"] if field and field.get("value") else None


async def _fetch_students(hass, username, password, school_id) -> list[dict[str, Any]]:
    """Sign in and list the pupils on the account, or raise."""
    session = async_create_clientsession(hass)
    api = SatchelApi(session, username, password, school_id)
    try:
        await api.async_login()
        return await api.async_get_students()
    finally:
        await session.close()


class SatchelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Satchel One setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Hold the verified credentials between the login and pupil steps."""
        self._data: dict[str, Any] = {}
        self._students: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect school + credentials, resolve the school, verify the login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            school_id = await _resolve_school(self.hass, user_input[CONF_SCHOOL])
            if not school_id:
                errors[CONF_SCHOOL] = "school_not_found"
            else:
                try:
                    self._students = await _fetch_students(
                        self.hass,
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                        school_id,
                    )
                except SatchelAuthError:
                    errors["base"] = "invalid_auth"
                except SatchelConnectionError:
                    errors["base"] = "cannot_connect"
                else:
                    if not self._students:
                        errors["base"] = "no_students"
                    else:
                        self._data = {
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_SCHOOL_ID: school_id,
                            CONF_SCAN_MINUTES: int(
                                user_input.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
                            ),
                        }
                        # One entry tracks one pupil, so a parent with several
                        # children picks which; a single pupil needs no step.
                        if len(self._students) == 1:
                            return await self._async_create(self._students[0])
                        return await self.async_step_pupil()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_pupil(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which pupil this entry should track (multi-child accounts)."""
        if user_input is not None:
            chosen = next(
                pupil
                for pupil in self._students
                if str(pupil["id"]) == user_input[CONF_STUDENT_ID]
            )
            return await self._async_create(chosen)

        return self.async_show_form(
            step_id="pupil",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STUDENT_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": str(pupil["id"]),
                                    "label": pupil_name(pupil) or str(pupil["id"]),
                                }
                                for pupil in self._students
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def _async_create(self, pupil: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry for one pupil, refusing duplicates."""
        await self.async_set_unique_id(str(pupil["id"]))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=pupil_name(pupil) or "Satchel One",
            data={**self._data, CONF_STUDENT_ID: pupil["id"]},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when Satchel One rejects the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password and update the entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            merged = {**reauth_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await _fetch_students(
                    self.hass,
                    merged[CONF_USERNAME],
                    merged[CONF_PASSWORD],
                    merged[CONF_SCHOOL_ID],
                )
            except SatchelAuthError:
                errors["base"] = "invalid_auth"
            except SatchelConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=merged)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={CONF_USERNAME: reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: SatchelConfigEntry) -> SatchelOptionsFlow:
        """Return the options flow (poll interval)."""
        return SatchelOptionsFlow()


class SatchelOptionsFlow(OptionsFlow):
    """Let the user change how often Satchel One is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the poll interval."""
        if user_input is not None:
            user_input[CONF_SCAN_MINUTES] = int(user_input[CONF_SCAN_MINUTES])
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_MINUTES,
            self.config_entry.data.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SCAN_MINUTES, default=current): _interval_selector()}
            ),
        )
