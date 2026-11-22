"""HAI: use an HAI container as a conversation agent in Assist.

Home Assistant offers the model no tools and no entity context here: the text the user says is
forwarded to the container, whose own agent (its safety rules and knowledge of the home) answers.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BadResponse, CannotConnect, HaiAgentClient, InvalidAuth, RateLimited

PLATFORMS = (Platform.CONVERSATION,)

type HaiAgentConfigEntry = ConfigEntry[HaiAgentClient]


async def async_setup_entry(hass: HomeAssistant, entry: HaiAgentConfigEntry) -> bool:
    client = HaiAgentClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_PASSWORD]
    )
    try:
        await client.async_check()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed from err
    except (CannotConnect, RateLimited, BadResponse) as err:
        # Down, or briefly locked out: Home Assistant retries by itself with growing pauses.
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaiAgentConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
