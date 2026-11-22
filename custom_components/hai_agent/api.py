"""Client for HAI container's chat API (contract/chat-api/).

Knows nothing about Home Assistant except that it is handed an aiohttp session, so it can be tested
on its own. Every failure is one of the exceptions below; the callers turn them into messages.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any, NoReturn

import aiohttp

from .const import (
    CHAT_TIMEOUT_SECONDS,
    CHECK_TIMEOUT_SECONDS,
    MAX_SESSION_ID_CHARS,
    MAX_TEXT_CHARS,
    SOURCE,
)

# The container accepts only a plain language tag here, because the value reaches the model.
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class HaiError(Exception):
    """Anything that went wrong talking to the container."""


class CannotConnect(HaiError):
    """The container did not answer (down, wrong address, network, timeout)."""


class InvalidAuth(HaiError):
    """The chat password was refused."""


class RateLimited(HaiError):
    """The container asked us to slow down (too many requests, or locked out by wrong passwords)."""

    def __init__(self, retry_after: int | None) -> None:
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class BadResponse(HaiError):
    """The container answered, but not in the way the contract says (wrong address, old version)."""


class ContainerTooOld(BadResponse):
    """It is probably an HAI, but a version from before the password check existed."""


class ContainerInSetup(BadResponse):
    """It is an HAI, but its first-run setup (or a re-enrollment) is not finished yet."""


class _NotFound(BadResponse):
    """HTTP 404 (kept apart so the caller can look closer; never leaves this module)."""


@dataclass(frozen=True)
class ChatReply:
    text: str
    error_kind: str | None = None
    error_detail: str | None = None


def normalize_url(url: str) -> str:
    """`http://host:8099/` and `http://host:8099` are the same container."""
    return url.strip().rstrip("/")


def session_id_for(conversation_id: str) -> str:
    """The container allows 100 characters. Home Assistant's own ids are far shorter, but a caller
    of `conversation.process` may pass anything, so a long one becomes a stable hash of itself."""
    if len(conversation_id) <= MAX_SESSION_ID_CHARS:
        return conversation_id
    return hashlib.sha256(conversation_id.encode()).hexdigest()


def clean_language(language: str | None) -> str | None:
    return language if language and _LANGUAGE_TAG.fullmatch(language) else None


class HaiAgentClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, password: str) -> None:
        self._session = session
        self._url = normalize_url(url)
        self._headers = {"Authorization": f"Bearer {password}"}

    async def async_check(self) -> None:
        """Raise unless the container is there and accepts the password (no model call, free)."""
        try:
            await self._request(
                "GET", "/api/auth/check", timeout=CHECK_TIMEOUT_SECONDS, expect_status="ok"
            )
        except _NotFound:
            await self._raise_why_not_found(old_container_possible=True)

    async def _raise_why_not_found(self, *, old_container_possible: bool) -> NoReturn:
        """An endpoint answered 404. /healthz tells an HAI still in first-run setup
        ("setup": finish it first) from one that predates the endpoint ("ok": update it) and from
        something else entirely (a router page, another app)."""
        try:
            health = await self._request("GET", "/healthz", timeout=CHECK_TIMEOUT_SECONDS)
        except HaiError:
            raise BadResponse("not found") from None
        status = health.get("status")
        if status == "setup":
            raise ContainerInSetup("the container has not finished its setup")
        if status == "ok" and old_container_possible:
            raise ContainerTooOld("the container has no /api/auth/check")
        raise BadResponse("not found")

    async def async_chat(
        self, session_id: str, text: str, language: str | None = None
    ) -> ChatReply:
        body: dict[str, Any] = {
            "session_id": session_id_for(session_id),
            "text": text[:MAX_TEXT_CHARS],
            "source": SOURCE,
        }
        if (tag := clean_language(language)) is not None:
            body["language"] = tag
        try:
            data = await self._request(
                "POST", "/api/chat", timeout=CHAT_TIMEOUT_SECONDS, json=body
            )
        except _NotFound:
            # Every container with /api/auth/check (which setup required) also has /api/chat, so a
            # 404 here means it was sent back to setup (re-enrolled) or is something else now.
            await self._raise_why_not_found(old_container_possible=False)
        reply = data.get("text")
        if not isinstance(reply, str):
            raise BadResponse("the reply has no text")
        return ChatReply(
            text=reply,
            error_kind=_optional_str(data.get("error_kind")),
            error_detail=_optional_str(data.get("error_detail")),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        json: dict[str, Any] | None = None,
        expect_status: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with asyncio.timeout(timeout):
                async with self._session.request(
                    method, self._url + path, json=json, headers=self._headers
                ) as response:
                    if response.status == 401:
                        raise InvalidAuth
                    if response.status == 429:
                        raise RateLimited(_retry_after(response.headers.get("Retry-After")))
                    if response.status == 404:
                        raise _NotFound("not found")
                    if response.status != 200:
                        raise BadResponse(f"unexpected status {response.status}")
                    data = await response.json(content_type=None)
        except HaiError:
            raise
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise CannotConnect(str(err)) from err
        except ValueError as err:  # not JSON: most likely not our container
            raise BadResponse("the answer is not JSON") from err
        if not isinstance(data, dict):
            raise BadResponse("the answer is not a JSON object")
        if expect_status is not None and data.get("status") != expect_status:
            raise BadResponse("not an HAI container")
        return data


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _retry_after(value: str | None) -> int | None:
    try:
        return max(1, int(value)) if value is not None else None
    except ValueError:
        return None
