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
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

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
from .const import DOMAIN, ENTRY_TITLE

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
        _LOGGER.exception("Unexpected error while checking HAI container")
        return {"base": "unknown"}
    return {}


class HaiAgentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the container as a conversation agent."""

    VERSION = 1
    _discovered: dict[str, str]

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
            title=ENTRY_TITLE, data={CONF_URL: url, CONF_PASSWORD: password}
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

    # --- discovery: HAI add-on announced itself through the Supervisor -------------

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The add-on sends its internal address and chat password at start and after a reset."""
        config = discovery_info.config
        try:
            url = normalize_url(f"http://{config['host']}:{int(config['port'])}")
            password = str(config["password"])
        except (KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_discovery_info")

        # Already added from an earlier announcement: take the current address and password, and
        # reload. This is how a reset password reaches the integration with nothing typed.
        await self.async_set_unique_id(f"addon:{discovery_info.slug}")
        self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_PASSWORD: password})

        # Added by hand before (by its direct address): the same container has the same password
        # (random, 24 characters), so it is not offered a second time.
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_PASSWORD) == password or entry.data.get(CONF_URL) == url:
                return self.async_abort(reason="already_configured")

        self._discovered = {CONF_URL: url, CONF_PASSWORD: password}
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        name = self.context.get("title_placeholders", {}).get("name", ENTRY_TITLE)
        if user_input is None:
            return self.async_show_form(
                step_id="hassio_confirm", description_placeholders={"name": name}
            )
        data = self._discovered
        if errors := await _validate(self.hass, data[CONF_URL], data[CONF_PASSWORD]):
            return self.async_show_form(
                step_id="hassio_confirm", description_placeholders={"name": name}, errors=errors
            )
        return self.async_create_entry(title=ENTRY_TITLE, data=dict(data))
