"""The worker tells the API the call is live while it lasts, with the session's own agent token."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import aiohttp
import pytest
from src import call_presence
from src.call_presence import end_call_presence, hold_call_presence
from src.llm import CustomLLM

from shared.py.voice_call import CALL_HEARTBEAT_SECONDS

ROOM = "voice_session_6812f0b3c9a14e2b7d5a91cc_0f3a9c"


class _Http:
    """Stands in for the aiohttp session: records each request and answers with a status."""

    def __init__(self, status: int = 204, raises: Exception | None = None) -> None:
        self.status = status
        self.raises = raises
        self.requests: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []

    def __call__(self, **_: Any) -> "_Http":
        return self

    async def __aenter__(self) -> "_Http":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def request(self, method: str, url: str, *, json: dict[str, Any], headers: dict[str, str]):
        self.requests.append((method, url, json, headers))
        if self.raises is not None:
            raise self.raises
        return _Response(self.status)


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientError(f"status {self.status}")


def _llm(token: str | None = "agent-jwt") -> CustomLLM:
    return cast(CustomLLM, SimpleNamespace(agent_token=token, base_url="http://api.test"))


async def _test_the_end_of_a_call_is_posted_with_the_agent_token() -> None:
    http = _Http()
    with patch.object(call_presence.aiohttp, "ClientSession", http):
        await end_call_presence(_llm(), ROOM)

    assert http.requests == [
        (
            "POST",
            "http://api.test/api/v1/voice/session/end",
            {"room_name": ROOM},
            {"Authorization": "Bearer agent-jwt"},
        )
    ]


async def _test_nothing_is_sent_before_the_session_has_its_agent_token() -> None:
    http = _Http()
    with patch.object(call_presence.aiohttp, "ClientSession", http):
        await end_call_presence(_llm(token=None), ROOM)

    assert http.requests == []


async def _test_the_heartbeat_repeats_until_cancelled() -> None:
    http = _Http()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    with (
        patch.object(call_presence.aiohttp, "ClientSession", http),
        patch.object(call_presence.asyncio, "sleep", sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await hold_call_presence(_llm(), ROOM)

    assert [request[0] for request in http.requests] == ["PUT", "PUT"]
    assert sleeps == [CALL_HEARTBEAT_SECONDS, CALL_HEARTBEAT_SECONDS]


async def _test_a_failed_beat_is_logged_and_retried_not_raised() -> None:
    http = _Http(status=503)

    with patch.object(call_presence.aiohttp, "ClientSession", http):
        await end_call_presence(_llm(), ROOM)

    assert len(http.requests) == 1


def test_the_end_of_a_call_is_posted_with_the_agent_token() -> None:
    asyncio.run(_test_the_end_of_a_call_is_posted_with_the_agent_token())


def test_nothing_is_sent_before_the_session_has_its_agent_token() -> None:
    asyncio.run(_test_nothing_is_sent_before_the_session_has_its_agent_token())


def test_the_heartbeat_repeats_until_cancelled() -> None:
    asyncio.run(_test_the_heartbeat_repeats_until_cancelled())


def test_a_failed_beat_is_logged_and_retried_not_raised() -> None:
    asyncio.run(_test_a_failed_beat_is_logged_and_retried_not_raised())
