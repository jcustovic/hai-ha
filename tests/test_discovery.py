"""Discovery: HAI add-on announces itself through the Supervisor (`hassio` step).

The add-on sends {"host", "port", "password"} at start and again after a password reset
(hai-agent: ha_discovery.py; described in contract/chat-api/README.md).
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.hai_agent.const import DOMAIN
from tests.conftest import PASSWORD, URL

SLUG = "abcd1234_hai_agent"
HOST = "abcd1234-hai-agent"
ADDON_URL = f"http://{HOST}:8099"
NAME = "HAI - Your home AI Agent"  # the add-on's name, sent with its announcement


def info(password: str = "addon-password", **config: Any) -> HassioServiceInfo:
    return HassioServiceInfo(
        config={"host": HOST, "port": 8099, "password": password, **config},
        name=NAME,
        slug=SLUG,
        uuid="uuid-1",
    )


async def discover(hass: HomeAssistant, discovery: HassioServiceInfo) -> Any:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=discovery
    )


async def test_a_running_add_on_is_offered_and_added_with_nothing_typed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{ADDON_URL}/api/auth/check", json={"status": "ok"})

    result = await discover(hass, info())
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "hassio_confirm"
    assert result["description_placeholders"] == {"name": NAME}
    assert aioclient_mock.call_count == 0  # nothing is tried before the user confirms

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"url": ADDON_URL, "password": "addon-password"}
    assert result["result"].unique_id == f"addon:{SLUG}"
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer addon-password"


async def test_a_new_password_from_the_add_on_updates_the_entry_by_itself(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """After 'Reset chat password' the add-on announces again: no re-authentication needed."""
    aioclient_mock.get(f"{ADDON_URL}/api/auth/check", json={"status": "ok"})
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=f"addon:{SLUG}",
        data={"url": ADDON_URL, "password": "old"}, source=config_entries.SOURCE_HASSIO,
    )
    entry.add_to_hass(hass)

    result = await discover(hass, info(password="new"))

    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data == {"url": ADDON_URL, "password": "new"}


async def test_an_add_on_already_added_by_its_address_is_not_offered_twice(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)  # added by hand at http://hai.test:8099, with the same password
    result = await discover(hass, info(password=PASSWORD))
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data == {"url": URL, "password": PASSWORD}  # left as the user set it


async def test_an_ignored_add_on_is_not_offered_again(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=f"addon:{SLUG}", source=config_entries.SOURCE_IGNORE, data={}
    ).add_to_hass(hass)
    result = await discover(hass, info())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


@pytest.mark.parametrize(
    "config",
    [{"host": HOST, "port": 8099}, {"host": HOST, "password": "x"}, {"port": "x", "host": HOST,
                                                                      "password": "x"}],
)
async def test_incomplete_details_are_refused(hass: HomeAssistant, config: dict[str, Any]) -> None:
    discovery = HassioServiceInfo(config=config, name=NAME, slug=SLUG, uuid="u")
    result = await discover(hass, discovery)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "invalid_discovery_info"


async def test_a_problem_on_confirm_is_shown_and_can_be_retried(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{ADDON_URL}/api/auth/check", status=401, json={"detail": "x"})
    result = await discover(hass, info())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_auth"}
    assert hass.config_entries.async_entries(DOMAIN) == []
