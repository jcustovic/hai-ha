"""The conversation agent: what goes to the container, what comes back, what is never sent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp
import jsonschema
import pytest
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests.conftest import PASSWORD, URL

CHECK = f"{URL}/api/auth/check"
CHAT = f"{URL}/api/chat"
AGENT = "conversation.ha_ai_agent"
CONTRACT = Path(__file__).resolve().parents[1] / "contract" / "chat-api"


def _schema(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CONTRACT / name).read_text())
    return data


@pytest.fixture
async def container(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> AiohttpClientMocker:
    """A set-up entry; tests then say how the container answers /api/chat."""
    aioclient_mock.get(CHECK, json={"status": "ok"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return aioclient_mock


def _chat_requests(mock: AiohttpClientMocker) -> list[dict[str, Any]]:
    return [call[2] for call in mock.mock_calls if str(call[1]) == CHAT]


async def _say(
    hass: HomeAssistant, text: str, conversation_id: str | None = None, language: str = "en"
) -> conversation.ConversationResult:
    return await conversation.async_converse(
        hass, text, conversation_id, Context(), language=language, agent_id=AGENT
    )


def _spoken(result: conversation.ConversationResult) -> str:
    return str(result.response.speech["plain"]["speech"])


async def test_the_agent_is_registered_and_speaks_every_language(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    state = hass.states.get(AGENT)
    assert state is not None
    agent = conversation.async_get_agent(hass, AGENT)
    assert agent is not None and agent.supported_languages == "*"


async def test_the_text_goes_to_the_container_and_its_reply_comes_back(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    container.post(CHAT, json={"session_id": "x", "text": "The kitchen light is on."})

    result = await _say(hass, "turn on the kitchen light", language="de")

    assert _spoken(result) == "The kitchen light is on."
    (sent,) = _chat_requests(container)
    assert sent["text"] == "turn on the kitchen light"
    assert sent["source"] == "ha" and sent["language"] == "de"
    assert sent["session_id"] == result.conversation_id  # Home Assistant's id is the session
    jsonschema.validate(sent, _schema("chat_request.schema.json"))  # what the container accepts
    chat_call = next(c for c in container.mock_calls if str(c[1]) == CHAT)
    assert chat_call[3]["Authorization"] == f"Bearer {PASSWORD}"


async def test_a_follow_up_is_the_same_session_so_a_yes_can_release_a_held_action(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    container.post(
        CHAT, json={"session_id": "x", "text": "Do you want me to unlock the front door?"}
    )
    first = await _say(hass, "unlock the front door")
    assert first.continue_conversation is True  # a voice satellite keeps listening for the answer

    container.clear_requests()
    container.post(CHAT, json={"session_id": "x", "text": "Done, the door is unlocked."})
    second = await _say(hass, "yes", conversation_id=first.conversation_id)

    assert second.conversation_id == first.conversation_id
    assert _chat_requests(container)[0]["session_id"] == first.conversation_id
    assert second.continue_conversation is False


async def test_two_conversations_are_two_sessions(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    container.post(CHAT, json={"session_id": "x", "text": "ok"})
    a = await _say(hass, "one")
    b = await _say(hass, "two")
    ids = [r["session_id"] for r in _chat_requests(container)]
    assert ids == [a.conversation_id, b.conversation_id] and ids[0] != ids[1]


async def test_a_provider_failure_is_read_out_like_any_other_reply(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    reply = {"session_id": "x", "text": "I'm out of credits.", "error_kind": "out_of_credits",
             "error_detail": "spend cap reached"}
    jsonschema.validate(reply, _schema("chat_response.schema.json"))
    container.post(CHAT, json=reply)
    assert _spoken(await _say(hass, "hello")) == "I'm out of credits."


async def test_home_assistant_never_sends_its_tools_or_prompt(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    container.post(CHAT, json={"session_id": "x", "text": "ok"})
    await _say(hass, "hello")
    (sent,) = _chat_requests(container)
    assert set(sent) <= {"session_id", "text", "language", "source"}  # only the contract's fields


@pytest.mark.parametrize("language", ["en", "pt-BR", "zh-Hans", "de"])
async def test_languages_home_assistant_uses_pass_the_containers_check(
    hass: HomeAssistant, container: AiohttpClientMocker, language: str
) -> None:
    container.post(CHAT, json={"session_id": "x", "text": "ok"})
    await _say(hass, "hi", language=language)
    jsonschema.validate(_chat_requests(container)[0], _schema("chat_request.schema.json"))


async def test_a_very_long_message_is_cut_to_what_the_container_accepts(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    container.post(CHAT, json={"session_id": "x", "text": "ok"})
    await _say(hass, "a" * 6000)
    sent = _chat_requests(container)[0]
    assert len(sent["text"]) == 4000
    jsonschema.validate(sent, _schema("chat_request.schema.json"))


async def test_a_very_long_conversation_id_is_replaced_by_a_stable_short_one(
    hass: HomeAssistant, container: AiohttpClientMocker
) -> None:
    container.post(CHAT, json={"session_id": "x", "text": "ok"})
    long_id = "c" * 300
    await _say(hass, "one", conversation_id=long_id)
    await _say(hass, "two", conversation_id=long_id)
    first, second = _chat_requests(container)
    assert first["session_id"] == second["session_id"] and len(first["session_id"]) <= 100
    jsonschema.validate(first, _schema("chat_request.schema.json"))


@pytest.mark.parametrize(
    ("mock", "expected"),
    [
        ({"exc": aiohttp.ClientConnectionError()}, "I can't reach the HA AI Agent right now"),
        ({"exc": TimeoutError()}, "I can't reach the HA AI Agent right now"),
        ({"status": 429, "json": {"detail": "slow down"}, "headers": {"Retry-After": "12"}},
         "Try again in 12 seconds"),
        ({"status": 422, "json": {"detail": "x"}}, "Something went wrong"),
        ({"status": 500, "text": "boom"}, "Something went wrong"),
        ({"status": 200, "json": {"unexpected": True}}, "Something went wrong"),
    ],
)
async def test_every_failure_is_told_to_the_user_in_plain_words_without_a_question(
    hass: HomeAssistant, container: AiohttpClientMocker, mock: dict[str, Any], expected: str
) -> None:
    container.post(CHAT, **mock)
    result = await _say(hass, "hello")
    assert expected in _spoken(result)
    assert result.continue_conversation is False  # an error must not keep a satellite listening


async def test_a_refused_password_is_told_and_asks_for_a_new_one(
    hass: HomeAssistant, container: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    container.post(CHAT, status=401, json={"detail": "invalid or missing chat token"})
    result = await _say(hass, "hello")
    assert "did not accept the saved password" in _spoken(result)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler("hai_agent")
    assert [f["context"]["source"] for f in flows] == ["reauth"]


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        ({"json": {"status": "setup"}}, "is not set up yet"),  # re-enrolled: back on its setup page
        ({"json": {"status": "ok"}}, "Something went wrong"),  # running but no /api/chat: odd
        ({"exc": aiohttp.ClientConnectionError()}, "Something went wrong"),
    ],
)
async def test_a_container_sent_back_to_setup_says_so_instead_of_something_went_wrong(
    hass: HomeAssistant, container: AiohttpClientMocker, health: dict[str, Any], expected: str
) -> None:
    container.post(CHAT, status=404, json={"detail": "Not Found"})
    container.get(f"{URL}/healthz", **health)
    result = await _say(hass, "hello")
    assert expected in _spoken(result)
    assert result.continue_conversation is False
