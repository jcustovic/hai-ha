"""The conversation agent: forwards what the user says to the container and returns its reply.

The LLM API of Home Assistant is deliberately never requested (no `async_provide_llm_data`), so
the model gets no tools, no system prompt and no entity context from Home Assistant. The
container's agent decides, acts through its own safety policy, and asks the user to confirm
sensitive actions. Such a question ends in "?", so a voice satellite keeps listening, and the
answer arrives in the same Home Assistant conversation, which is the container's session.
"""

from __future__ import annotations

import logging
from typing import Literal

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HaiAgentConfigEntry
from .api import (
    BadResponse,
    CannotConnect,
    ContainerInSetup,
    HaiError,
    InvalidAuth,
    RateLimited,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# What the user hears when something is wrong. No question marks: that would keep a satellite
# listening.
MESSAGE_CANNOT_CONNECT = "I can't reach the HA AI Agent right now. Check that it is running."
MESSAGE_INVALID_AUTH = (
    "The HA AI Agent did not accept the saved password. Please enter it again in Home Assistant."
)
MESSAGE_UNEXPECTED = "Something went wrong while talking to the HA AI Agent."
MESSAGE_IN_SETUP = (
    "The HA AI Agent is not set up yet. Finish its setup on its own page, then try again."
)


def message_rate_limited(retry_after: int | None) -> str:
    wait = f" Try again in {retry_after} seconds." if retry_after else " Try again in a moment."
    return f"The HA AI Agent is busy.{wait}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaiAgentConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HaiAgentConversationEntity(entry)])


class HaiAgentConversationEntity(
    conversation.ConversationEntity, conversation.AbstractConversationAgent
):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: HaiAgentConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HAI",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL  # the container's model answers in whatever language it is spoken to

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        text = await self._ask(chat_log.conversation_id, user_input)
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=text)
        )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _ask(self, conversation_id: str, user_input: conversation.ConversationInput) -> str:
        """The reply to speak: the container's answer, or a plain explanation of what failed."""
        try:
            reply = await self.entry.runtime_data.async_chat(
                conversation_id, user_input.text, user_input.language
            )
        except InvalidAuth:
            self.entry.async_start_reauth(self.hass)
            return MESSAGE_INVALID_AUTH
        except CannotConnect:
            return MESSAGE_CANNOT_CONNECT
        except RateLimited as err:
            return message_rate_limited(err.retry_after)
        except ContainerInSetup:
            return MESSAGE_IN_SETUP
        except BadResponse:
            _LOGGER.warning("The HA AI Agent answered in an unexpected way", exc_info=True)
            return MESSAGE_UNEXPECTED
        except HaiError:
            _LOGGER.exception("Unexpected error from the HA AI Agent")
            return MESSAGE_UNEXPECTED
        if reply.error_kind:
            _LOGGER.debug("The AI provider failed: %s (%s)", reply.error_kind, reply.error_detail)
        return reply.text or MESSAGE_UNEXPECTED
