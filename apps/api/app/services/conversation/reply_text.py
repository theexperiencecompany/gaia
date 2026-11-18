"""A reply's text as it streams, and the bubble deltas that carry it to clients.

The server turns text into bubbles in one place, screen_bubbles, for the live deltas and the settled
screen alike, and shown text only grows: a client only appends to the bubble a delta names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.models.conversation_frame_models import MessageBoundaryEvent, ResponseEvent
from app.utils.errors import ShownTextTakenBackError
from app.utils.file_links import FileLinks, unfinished_path_start
from app.utils.message_breaks import shown_so_far, split_message_bubbles
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER, BubbleTextDelta


@dataclass(frozen=True)
class ReplyText:
    """The raw text of the messages a reply kept, each later one opened by a break."""

    raw: str = ""
    # Where in raw the message still streaming begins.
    message_start: int = 0
    # A kept message just ended: the next text opens a new bubble.
    break_pending: bool = False

    @classmethod
    def kept(cls, text: str) -> ReplyText:
        """Return text as one whole kept message, so the next chunk opens a bubble below it."""
        return cls(raw=text, message_start=len(text), break_pending=bool(text))

    def take(self, payload: ResponseEvent | MessageBoundaryEvent) -> ReplyText:
        """Fold one streamed chunk or message boundary; text only ever grows."""
        match payload:
            case ResponseEvent(response=chunk) if self.break_pending:
                raw = f"{self.raw}{NEW_MESSAGE_BREAKER}"
                return ReplyText(raw=raw + chunk, message_start=len(raw))
            case ResponseEvent(response=chunk):
                return replace(self, raw=self.raw + chunk)
            case MessageBoundaryEvent():
                return ReplyText(
                    raw=self.raw,
                    message_start=len(self.raw),
                    break_pending=len(self.raw) > self.message_start,
                )

    @property
    def text(self) -> str:
        """Return the bubbles joined by the break: the text a reply entry stores."""
        return _joined_bubbles(self.raw)

    @property
    def shown(self) -> str:
        """Return the text a client may see yet: all of it but a break or sandbox path the open message is still writing."""
        if len(self.raw) == self.message_start:
            return self.text
        open_message = shown_so_far(self.raw[self.message_start :])
        return _joined_bubbles(
            self.raw[: self.message_start] + open_message[: unfinished_path_start(open_message)]
        )


def _joined_bubbles(raw: str) -> str:
    return NEW_MESSAGE_BREAKER.join(split_message_bubbles(raw))


def screen_bubbles(text: str, conversation_id: str, links: FileLinks) -> tuple[str, ...]:
    """Return the bubbles every client shows for a reply's text, live or settled: sandbox paths resolved, then split."""
    return tuple(split_message_bubbles(links.resolve(text, conversation_id)))


def bubble_deltas(shown: Sequence[str], now: Sequence[str]) -> list[BubbleTextDelta]:
    """Return the deltas that carry a client from the shown bubbles to now: text only appends.

    The one place shown text is guarded: now short of shown is held until it reads past it, and
    now that changes shown text raises, since no client takes back what it showed.
    """
    if NEW_MESSAGE_BREAKER.join(shown).startswith(NEW_MESSAGE_BREAKER.join(now)):
        return []
    rewrites = list(now[: max(len(shown) - 1, 0)]) != list(shown[:-1]) or len(now) < len(shown)
    if rewrites or (shown and not now[len(shown) - 1].startswith(shown[-1])):
        raise ShownTextTakenBackError(
            message="a reply's bubbles would change text a client already showed",
            meta={"shown": list(shown), "now": list(now)},
        )
    return [
        BubbleTextDelta(bubble=bubble, text=now[bubble][len(before) :])
        for bubble in range(len(now))
        if now[bubble] != (before := shown[bubble] if bubble < len(shown) else "")
    ]
