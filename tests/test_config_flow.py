"""The config flow: address + password, checked against the container before anything is saved."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.hai_agent.const import DOMAIN
from tests.conftest import PASSWORD, URL

CHECK = f"{URL}/api/auth/check"
HEALTH = f"{URL}/healthz"


async def _start(hass: HomeAssistant) -> Any:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _submit(
    hass: HomeAssistant, flow_id: str, url: str = URL, password: str = PASSWORD
) -> Any:
    return await hass.config_entries.flow.async_configure(
        flow_id, {"url": url, "password": password}
    )


async def test_a_working_address_and_password_create_the_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(CHECK, json={"status": "ok"})
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await _submit(hass, result["flow_id"], url=f" {URL}/ ", password=f" {PASSWORD} ")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"url": URL, "password": PASSWORD}  # tidied: no blanks, no final slash
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {PASSWORD}"


@pytest.mark.parametrize(
    ("mock", "error"),
    [
        ({"status": 401, "json": {"detail": "invalid or missing chat token"}}, "invalid_auth"),
        ({"status": 429, "json": {"detail": "too many"}, "headers": {"Retry-After": "30"}},
         "rate_limited"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"exc": TimeoutError()}, "cannot_connect"),
        ({"status": 404, "text": "not found"}, "not_hai_agent"),
        ({"status": 200, "text": "<html>router login</html>"}, "not_hai_agent"),
        ({"status": 200, "json": {"hello": "world"}}, "not_hai_agent"),
    ],
)
async def test_every_failure_is_shown_as_an_error_and_nothing_is_saved(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock: dict[str, Any],
    error: str,
) -> None:
    aioclient_mock.get(CHECK, **mock)
    aioclient_mock.get(HEALTH, status=404, text="not found")  # no sign of an HA AI Agent
    result = await _submit(hass, (await _start(hass))["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_an_older_container_is_told_to_update_not_called_a_stranger(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An old container has no /api/auth/check but does answer /healthz."""
    aioclient_mock.get(CHECK, status=404, json={"detail": "Not Found"})
    aioclient_mock.get(HEALTH, json={"status": "ok"})
    result = await _submit(hass, (await _start(hass))["flow_id"])
    assert result["errors"] == {"base": "container_too_old"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_a_container_still_in_setup_is_told_to_finish_it_not_called_a_stranger(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Before its first-run setup the container has no /api/auth/check; /healthz says "setup"."""
    aioclient_mock.get(CHECK, status=404, json={"detail": "Not Found"})
    aioclient_mock.get(HEALTH, json={"status": "setup"})
    result = await _submit(hass, (await _start(hass))["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "container_in_setup"}
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(
    "health",
    [
        {"status": 200, "text": "<html>router login</html>"},
        {"status": 200, "json": {"status": "degraded"}},
        {"exc": aiohttp.ClientConnectionError()},
    ],
)
async def test_a_404_with_no_healthy_agent_behind_it_is_not_called_an_old_agent(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, health: dict[str, Any]
) -> None:
    aioclient_mock.get(CHECK, status=404, text="not found")
    aioclient_mock.get(HEALTH, **health)
    result = await _submit(hass, (await _start(hass))["flow_id"])
    assert result["errors"] == {"base": "not_hai_agent"}


async def test_a_wrong_password_can_be_corrected_in_the_same_form(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(CHECK, status=401, json={"detail": "x"})
    flow_id = (await _start(hass))["flow_id"]
    assert (await _submit(hass, flow_id, password="wrong"))["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(CHECK, json={"status": "ok"})
    assert (await _submit(hass, flow_id))["type"] is FlowResultType.CREATE_ENTRY


async def test_something_that_is_not_an_address_is_refused_without_a_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    result = await _submit(hass, (await _start(hass))["flow_id"], url="not an address")
    assert result["errors"] == {"base": "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_the_same_container_cannot_be_added_twice(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    aioclient_mock.get(CHECK, json={"status": "ok"})
    result = await _submit(hass, (await _start(hass))["flow_id"], url=URL + "/")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_replaces_only_the_password(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    aioclient_mock.get(CHECK, json={"status": "ok"})
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "new-password"}
    )

    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data == {"url": URL, "password": "new-password"}


async def test_reauth_with_a_wrong_password_stays_on_the_form(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    aioclient_mock.get(CHECK, status=401, json={"detail": "x"})
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "no"})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_auth"}
    assert entry.data["password"] == PASSWORD  # unchanged
