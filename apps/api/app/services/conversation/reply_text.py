"""A reply's text as it streams, and the bubble deltas that carry it to clients.

The server turns text into bubbles in one place, screen_bubbles, for the live deltas and the settled
screen alike, and a client only appends to the bubble a delta names, so live and reloaded bubbles match.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.models.conversation_frame_models import MessageBoundaryEvent, ResponseEvent
from app.utils.artifact_utils import resolve_sandbox_paths, unfinished_path_start
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
        """Return the text a client may see yet: all of it but a sandbox path the open message is still writing."""
        if len(self.raw) == self.message_start:
            return self.text
        open_message = self.raw[self.message_start :]
        return _joined_bubbles(
            self.raw[: self.message_start] + open_message[: unfinished_path_start(open_message)]
        )


def _joined_bubbles(raw: str) -> str:
    return NEW_MESSAGE_BREAKER.join(split_message_bubbles(raw))


def screen_bubbles(text: str, conversation_id: str) -> tuple[str, ...]:
    """Return the bubbles every client shows for a reply's text, live or settled: sandbox paths resolved, then split."""
    return tuple(split_message_bubbles(resolve_sandbox_paths(text, conversation_id)))


def bubble_deltas(shown: Sequence[str], now: Sequence[str]) -> list[BubbleTextDelta | BubblesDelta]:
    """Return the deltas that carry a client from the shown bubbles to now.

    Text only appends to the last shown bubble or opens later ones. Text the model took back
    stays shown until its replacement reads past it or differently, which then replaces every
    bubble at once: a retried or retracted message is replaced in place, never blanked first.
    """
    if NEW_MESSAGE_BREAKER.join(shown).startswith(NEW_MESSAGE_BREAKER.join(now)):
        return []
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
