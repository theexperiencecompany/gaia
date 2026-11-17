"""An error the backend sends after the spoken reply is still heard and shown, once."""

import asyncio
from collections.abc import AsyncIterator
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from livekit import rtc
from livekit.agents import AgentSession
import pytest
from src import constants
from src.llm import CustomLLM

ERROR_FRAME = json.dumps({"error": "Your reply could not be saved."})


class _FakeContent:
    def __init__(self, frames: list[str]) -> None:
        self._lines = [f"data: {frame}\n".encode() for frame in frames]

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for line in self._lines:
            yield line


def _drain(frames: list[str]) -> tuple[MagicMock, AsyncMock]:
    send_text = AsyncMock()
    room = SimpleNamespace(local_participant=SimpleNamespace(send_text=send_text))
    llm = CustomLLM(base_url="http://api.test", room=cast(rtc.Room, room))
    session = MagicMock()
    llm.session = cast(AgentSession, session)
    resp = SimpleNamespace(content=_FakeContent(frames), release=AsyncMock())

    asyncio.run(llm._drain(cast(aiohttp.ClientResponse, resp)))
    return session, send_text


@pytest.mark.regression
def test_an_error_after_the_reply_is_spoken_once_and_shown() -> None:
    session, send_text = _drain([ERROR_FRAME, ERROR_FRAME, "[DONE]"])

    session.say.assert_called_once_with(constants.VOICE_ERROR_REPLY)
    shown = [call.args[0] for call in send_text.await_args_list]
    assert ERROR_FRAME in shown


def test_a_drain_without_errors_stays_quiet() -> None:
    session, _send_text = _drain([json.dumps({"tool_data": {}}), "[DONE]"])

    session.say.assert_not_called()
