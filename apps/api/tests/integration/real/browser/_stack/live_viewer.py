"""The person in the live view: the socket the web page dials through the proxy, frames in and input out.

Every message is the one the web live view sends (useLiveInput.ts) and every
frame the one it draws, so a scenario acts on the run's page only the way a
user can: by looking at the streamed screen and clicking and typing into it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import time
from urllib.parse import urlsplit

import websockets
from websockets.asyncio.client import ClientConnection

#: The live view's input messages, as useLiveInput.ts builds them.
_ENTER = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}


@dataclass(frozen=True)
class LiveFrame:
    """One screen the live view drew: the page it shows."""

    url: str
    title: str

    @property
    def path(self) -> str:
        return urlsplit(self.url).path


class LiveViewer:
    """One open live view, driven like the web page drives it."""

    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket

    @classmethod
    @asynccontextmanager
    async def open(cls, url: str) -> AsyncIterator[LiveViewer]:
        async with websockets.connect(url, max_size=None) as socket:
            yield cls(socket)

    async def frame(self, *, timeout: float) -> LiveFrame:
        """Return the next screen the page streams; other messages are skipped."""
        async with asyncio.timeout(timeout):
            while True:
                message = json.loads(await self._socket.recv())
                if message.get("type") == "frame" and message.get("data"):
                    return LiveFrame(url=message.get("url", ""), title=message.get("title", ""))

    async def until_on(self, path: str, *, timeout: float) -> LiveFrame:
        """Watch the stream until it shows path, failing with the last page it did show."""
        deadline = time.monotonic() + timeout
        seen: LiveFrame | None = None
        while (left := deadline - time.monotonic()) > 0:
            try:
                seen = await self.frame(timeout=left)
            except TimeoutError:
                break
            if seen.path == path:
                return seen
        raise AssertionError(f"the live view never showed {path} (last showed {seen})")

    async def click(self, x: int, y: int) -> None:
        for event, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
            await self._send(
                {
                    "type": "mouse",
                    "event": event,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "buttons": buttons,
                    "clickCount": 1,
                }
            )

    async def type(self, text: str) -> None:
        """Type text as a phone keyboard commits it: one edit into the focused field."""
        await self._send({"type": "text", "text": text})

    async def press_enter(self) -> None:
        await self._send({"type": "key", "event": "keyDown", **_ENTER, "text": "\r"})
        await self._send({"type": "key", "event": "keyUp", **_ENTER})

    async def _send(self, message: dict[str, object]) -> None:
        await self._socket.send(json.dumps(message))
