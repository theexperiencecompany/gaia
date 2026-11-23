"""What one chat of the browser stack was sent, oldest first, and a wait for a line in it."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import time

_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class Delivery:
    """One message the bot would have sent."""

    destination_id: str
    is_channel: bool
    text: str
    photo_url: str | None
    caption: str | None
    at: float

    @property
    def said(self) -> str:
        """Everything the user reads in it: the text, or a photo's caption."""
        return self.text or (self.caption or "")


@dataclass
class Transcript:
    """Everything delivered to one chat, oldest first."""

    destination_id: str
    deliveries: list[Delivery] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [d.text for d in self.deliveries if d.text]

    @property
    def photos(self) -> list[Delivery]:
        return [d for d in self.deliveries if d.photo_url]

    def matching(self, pattern: str) -> list[Delivery]:
        return [d for d in self.deliveries if re.search(pattern, d.said, re.IGNORECASE)]


async def wait_for(transcript: Transcript, pattern: str, *, timeout: float) -> Delivery:
    """Return the first delivery to transcript matching pattern, polling until timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = transcript.matching(pattern)
        if found:
            return found[0]
        await asyncio.sleep(_POLL_SECONDS)
    raise AssertionError(
        f"nothing matching {pattern!r} reached {transcript.destination_id} in {timeout}s: "
        f"{[d.said[:120] for d in transcript.deliveries]}"
    )
