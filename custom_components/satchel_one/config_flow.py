"""Config and options flow for Satchel One: find the school, then sign in."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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

from .api import (
    SatchelApi,
    SatchelAuthError,
    SatchelConnectionError,
    async_search_schools,
)
from .const import (
    CONF_SCAN_MINUTES,
    CONF_SCHOOL_ID,
    CONF_STUDENT_ID,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    MAX_SCAN_MINUTES,
    MIN_SCAN_MINUTES,
)
from .coordinator import SatchelConfigEntry, pupil_name

CONF_SCHOOL = "school"


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


STEP_SCHOOL_SCHEMA = vol.Schema({vol.Required(CONF_SCHOOL): TextSelector()})


def school_label(school: dict[str, Any]) -> str:
    """'Example High School - Exampleton, EX1 2AB' for the picker."""
    where = ", ".join(
        str(p) for p in (school.get("town"), school.get("post_code")) if p
    )
    name = str(school.get("name") or school.get("id"))
    return f"{name} - {where}" if where else name


class SatchelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Satchel One setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Hold state between the school, credential and pupil steps."""
        self._schools: list[dict[str, Any]] = []
        self._school_id: str | None = None
        self._data: dict[str, Any] = {}
        self._students: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search Satchel's public directory for the school."""
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                self._schools = await async_search_schools(
                    session, user_input[CONF_SCHOOL]
                )
            except SatchelConnectionError:
                errors["base"] = "cannot_connect"
            else:
                if not self._schools:
                    errors[CONF_SCHOOL] = "school_not_found"
                elif len(self._schools) == 1:
                    self._school_id = str(self._schools[0]["id"])
                    return await self.async_step_credentials()
                else:
                    return await self.async_step_school()

        return self.async_show_form(
            step_id="user", data_schema=STEP_SCHOOL_SCHEMA, errors=errors
        )

    async def async_step_school(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Disambiguate when the search matched several schools."""
        if user_input is not None:
            self._school_id = user_input[CONF_SCHOOL_ID]
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="school",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHOOL_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": str(school["id"]),
                                    "label": school_label(school),
                                }
                                for school in self._schools
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify the parent login against the chosen school."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._students = await _fetch_students(
                    self.hass,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    self._school_id,
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
                        CONF_SCHOOL_ID: self._school_id,
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
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): TextSelector(),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_SCAN_MINUTES, default=DEFAULT_SCAN_MINUTES
                    ): _interval_selector(),
                }
            ),
            errors=errors,
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


async def _fetch_students(hass, username, password, school_id) -> list[dict[str, Any]]:
    """Sign in and list the pupils on the account, or raise."""
    api = SatchelApi(async_get_clientsession(hass), username, password, school_id)
    await api.async_login()
    return await api.async_get_students()


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
