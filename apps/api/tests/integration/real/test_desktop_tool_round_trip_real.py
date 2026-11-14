"""A desktop tool call reaches the user's desktop app over the user WebSocket and resumes on its result, against real Redis.

Stops short of the Electron app itself: DesktopApp stands in for the renderer that
receives the pushed request, runs it over IPC, and POSTs the result.
"""

import asyncio
import contextlib
from typing import Any

import pytest

from app.agents.tools.desktop_tools import read_clipboard
from app.constants.websocket import DESKTOP_TOOL_REQUEST_MESSAGE
from app.core.websocket_broadcast_listener import _consume
from app.core.websocket_manager import websocket_manager
from app.services.desktop.bridge import relay_desktop_result

pytestmark = pytest.mark.service

USER_ID = "desktop_round_trip_user"


class DesktopApp:
    """A connected desktop client: answers each pushed tool request through the result endpoint's relay."""

    def __init__(self, clipboard: str) -> None:
        self.clipboard = clipboard
        self.requests: list[dict[str, Any]] = []
        self._answers: set[asyncio.Task[None]] = set()

    async def send_json(self, message: dict[str, Any]) -> None:
        if message.get("type") != DESKTOP_TOOL_REQUEST_MESSAGE:
            return
        request = message["request"]
        self.requests.append(request)
        task = asyncio.create_task(
            relay_desktop_result(
                request_id=request["request_id"],
                user_id=USER_ID,
                ok=True,
                data={"text": self.clipboard},
                error=None,
            )
        )
        self._answers.add(task)


@pytest.fixture
async def listening(real_redis):
    """Run this replica's broadcast listener, as the API process does."""
    listener = asyncio.create_task(_consume())
    await asyncio.sleep(0.1)
    yield
    listener.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener


@pytest.fixture
def desktop(listening):
    app = DesktopApp(clipboard="copied on the desktop")
    websocket_manager.connections[USER_ID] = {app}  # type: ignore[arg-type]  # duck-typed socket: only send_json is called
    yield app
    websocket_manager.connections.pop(USER_ID, None)


@pytest.mark.asyncio
async def test_a_desktop_tool_resumes_with_the_result_its_desktop_app_posted(desktop) -> None:
    config = {"configurable": {"conversation_source": "desktop", "user_id": USER_ID}}

    async with asyncio.timeout(5):
        result = await read_clipboard.coroutine(config=config)

    assert result == "Clipboard contents:\ncopied on the desktop"
    assert [request["tool"] for request in desktop.requests] == ["read_clipboard"]
