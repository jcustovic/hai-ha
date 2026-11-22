"""Shared fixtures: a container that answers through Home Assistant's mocked HTTP client."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hai_agent.const import DOMAIN

URL = "http://hai.test:8099"
PASSWORD = "secret-chat-password"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/ from this repository."""


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="HA AI Agent",
        data={"url": URL, "password": PASSWORD},
        unique_id=URL,
    )


@pytest.fixture(autouse=True)
async def _core_is_running(hass: HomeAssistant) -> None:
    """Home Assistant's own conversation component expects the `homeassistant` core component
    (entity exposure) to be set up, as it always is in a real installation."""
    assert await async_setup_component(hass, "homeassistant", {})
