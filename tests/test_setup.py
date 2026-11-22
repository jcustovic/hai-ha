"""Setting up and unloading the entry, and what happens when the container is away."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests.conftest import PASSWORD, URL

CHECK = f"{URL}/api/auth/check"
HEALTH = f"{URL}/healthz"


async def test_a_reachable_container_loads_and_unloads(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    aioclient_mock.get(CHECK, json={"status": "ok"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {PASSWORD}"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_a_refused_password_asks_the_user_for_a_new_one(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    aioclient_mock.get(CHECK, status=401, json={"detail": "x"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler("hai_agent")
    assert [f["context"]["source"] for f in flows] == ["reauth"]


@pytest.mark.parametrize(
    "mock",
    [
        {"exc": aiohttp.ClientConnectionError()},
        {"status": 429, "json": {"detail": "x"}, "headers": {"Retry-After": "5"}},
        {"status": 200, "text": "not json"},
        {"status": 404, "text": "not found"},
    ],
)
async def test_an_absent_container_is_retried_later_not_given_up_on(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    mock: dict[str, object],
) -> None:
    aioclient_mock.get(CHECK, **mock)
    aioclient_mock.get(HEALTH, json={"status": "ok"})  # (an old container, for the 404 case)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    # not a password problem, so no re-authentication is asked for
    assert hass.config_entries.flow.async_progress_by_handler("hai_agent") == []


async def test_a_container_back_in_setup_is_retried_until_it_is_finished(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """Re-enrolling sends the container back to its first-run page (no password check there)."""
    aioclient_mock.get(CHECK, status=404, json={"detail": "Not Found"})
    aioclient_mock.get(HEALTH, json={"status": "setup"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason is not None and "setup" in entry.reason
    assert hass.config_entries.flow.async_progress_by_handler("hai_agent") == []
