"""A reply's text as it streams, and the bubble deltas that carry it to clients.

The server splits once: the text folds here, its bubbles are split_message_bubbles of it,
and a client only appends to the bubble a delta names, so live and reloaded bubbles match.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.models.conversation_frame_models import MessageBoundaryEvent, ResponseEvent
from app.utils.message_breaks import split_message_bubbles
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER, BubblesDelta, BubbleTextDelta


@dataclass(frozen=True)
class ReplyText:
    """The raw text of the messages a reply kept, each later one opened by a break."""

    raw: str = ""
    # Where in raw the message still streaming begins.
    message_start: int = 0
    # A kept message just ended: the next text opens a new bubble.
    break_pending: bool = False

    def take(self, payload: ResponseEvent | MessageBoundaryEvent) -> ReplyText:
        """Fold one streamed chunk or message boundary; a discarded message's text is cut back out."""
        match payload:
            case ResponseEvent(response=chunk) if self.break_pending:
                raw = f"{self.raw}{NEW_MESSAGE_BREAKER}"
                return ReplyText(raw=raw + chunk, message_start=len(raw))
            case ResponseEvent(response=chunk):
                return replace(self, raw=self.raw + chunk)
            case MessageBoundaryEvent(message_boundary=boundary) if boundary.discarded:
                return replace(self, raw=self.raw[: self.message_start])
            case MessageBoundaryEvent():
                return ReplyText(
                    raw=self.raw,
                    message_start=len(self.raw),
                    break_pending=len(self.raw) > self.message_start,
                )

    @property
    def bubbles(self) -> tuple[str, ...]:
        return tuple(split_message_bubbles(self.raw))

    @property
    def text(self) -> str:
        """Return the bubbles joined by the break: the text a reply entry stores."""
        return NEW_MESSAGE_BREAKER.join(self.bubbles)


def bubble_deltas(shown: Sequence[str], now: Sequence[str]) -> list[BubbleTextDelta | BubblesDelta]:
    """Return the deltas that carry a client from the shown bubbles to now.

    Text only appends to the last shown bubble or opens later ones; anything else (text the
    model took back) replaces every bubble at once.
    """
    if list(now[: max(len(shown) - 1, 0)]) != list(shown[:-1]) or len(now) < len(shown):
        return [BubblesDelta(bubbles=tuple(now))]
    if shown and not now[len(shown) - 1].startswith(shown[-1]):
        return [BubblesDelta(bubbles=tuple(now))]
    deltas: list[BubbleTextDelta | BubblesDelta] = []
    for bubble in range(len(now)):
        before = shown[bubble] if bubble < len(shown) else ""
        if now[bubble] != before:
            deltas.append(BubbleTextDelta(bubble=bubble, text=now[bubble][len(before) :]))
    return deltas
