"""Config flow: the container's address and its chat password."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import (
    BadResponse,
    CannotConnect,
    ContainerInSetup,
    ContainerTooOld,
    HaiAgentClient,
    InvalidAuth,
    RateLimited,
    normalize_url,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        probatio.Required(CONF_PASSWORD): _PASSWORD,
    }
)
STEP_REAUTH_SCHEMA = probatio.Schema({probatio.Required(CONF_PASSWORD): _PASSWORD})


async def _validate(hass: HomeAssistant, url: str, password: str) -> dict[str, str]:
    """Errors (as translation keys) found when trying the address and password; empty when fine."""
    client = HaiAgentClient(async_get_clientsession(hass), url, password)
    try:
        await client.async_check()
    except InvalidAuth:
        return {"base": "invalid_auth"}
    except RateLimited:
        return {"base": "rate_limited"}
    except CannotConnect:
        return {"base": "cannot_connect"}
    except ContainerInSetup:
        return {"base": "container_in_setup"}
    except ContainerTooOld:
        return {"base": "container_too_old"}
    except BadResponse:
        return {"base": "not_hai_agent"}
    except Exception:
        _LOGGER.exception("Unexpected error while checking the HA AI Agent container")
        return {"base": "unknown"}
    return {}


class HaiAgentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the container as a conversation agent."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        try:
            url = normalize_url(cv.url(user_input[CONF_URL].strip()))
        except probatio.Invalid:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
                errors={"base": "invalid_url"},
            )
        password = user_input[CONF_PASSWORD].strip()

        await self.async_set_unique_id(url)
        self._abort_if_unique_id_configured()

        if errors := await _validate(self.hass, url, password):
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
                errors=errors,
            )
        return self.async_create_entry(
            title="HA AI Agent", data={CONF_URL: url, CONF_PASSWORD: password}
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The password stopped working (the container was re-enrolled, or it was changed)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", data_schema=STEP_REAUTH_SCHEMA)

        password = user_input[CONF_PASSWORD].strip()
        if errors := await _validate(self.hass, entry.data[CONF_URL], password):
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=self.add_suggested_values_to_schema(STEP_REAUTH_SCHEMA, user_input),
                errors=errors,
            )
        return self.async_update_reload_and_abort(
            entry, data_updates={CONF_PASSWORD: password}
        )
