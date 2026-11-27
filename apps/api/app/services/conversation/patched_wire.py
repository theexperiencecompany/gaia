"""One connection's frames on wire 2: each item's cards once, and a change as only what changed.

The projection and the Redis stream give every connection whole items and whole card lists.
This holds what its connection was sent and writes the next frame against it, so a patch is
always against a copy the same connection delivered.
"""

from __future__ import annotations

from pydantic import JsonValue

from app.models.conversation_frame_models import RetractFrame
from app.models.conversation_screen_models import (
    ScreenFrame,
    ScreenInsertFrame,
    ScreenItem,
    ScreenStreamFrame,
    ScreenUpdateFrame,
)
from app.models.conversation_send_models import ConversationEvent
from app.services.conversation.item_changes import changes_between
from shared.py.conversation_wire import (
    CardsDelta,
    ReplyDeltaFrame,
    ReplyItem,
    ScreenPatchFrame,
    TimelineDelta,
    ToolTimeline,
)

#: Sent once, folded, as the item's timeline.
_UNFOLDED = {"tool_data"}
_NO_TIMELINE: JsonValue = ToolTimeline().model_dump(mode="json")


def _json(item: ScreenItem) -> JsonValue:
    return item.model_dump(mode="json", exclude=_UNFOLDED)


class PatchedWire:
    """What one wire 2 connection was sent, and each frame as it is sent next."""

    def __init__(self) -> None:
        self._sent: dict[str, ScreenItem] = {}
        # How many patches each item was sent since it last went whole.
        self._patches: dict[str, int] = {}
        # Each open attempt's reply and the timeline its last cards delta folded to.
        self._timelines: dict[str, tuple[str | None, JsonValue]] = {}

    def line(self, frame: ScreenStreamFrame) -> str:
        """Return frame's JSON for this connection, and hold what it now has."""
        match frame:
            case ScreenFrame(items=items):
                for item in items:
                    self._take(item)
                # Named only when it names something: a reader built before it reads no such key.
                unnamed = set() if frame.held_cards else {"held_cards"}
                exclude = {
                    "frame": {"items": {"__all__": _UNFOLDED}} | dict.fromkeys(unnamed, True)
                }
                return ConversationEvent(frame=frame).model_dump_json(exclude=exclude)
            case ScreenInsertFrame(item=item):
                self._take(item)
                return _whole(frame)
            case ScreenUpdateFrame(item=item, head=head):
                held = self._sent.get(item.id)
                if held is None:
                    self._take(item)
                    return _whole(frame)
                base = self._patches[item.id]
                self._take(item, patches=base + 1)
                changes = changes_between(_json(held), _json(item))
                patch = ScreenPatchFrame(id=item.id, base=base, changes=tuple(changes), head=head)
                return ConversationEvent(frame=patch).model_dump_json()
            case ReplyDeltaFrame(payload=CardsDelta(timeline=timeline)):
                return ConversationEvent(
                    frame=self._timeline_delta(frame, timeline)
                ).model_dump_json()
            case RetractFrame(attempt_id=attempt_id):
                self._timelines.pop(attempt_id, None)
        return ConversationEvent(frame=frame).model_dump_json()

    def _take(self, item: ScreenItem, patches: int = 0) -> None:
        self._sent[item.id] = item
        self._patches[item.id] = patches
        if isinstance(item, ReplyItem) and item.outcome is not None:
            # Settled: no attempt streams into it again.
            self._timelines = {
                attempt: held for attempt, held in self._timelines.items() if held[0] != item.id
            }

    def _timeline_delta(self, frame: ReplyDeltaFrame, timeline: ToolTimeline) -> ReplyDeltaFrame:
        _reply, held = self._timelines.get(frame.attempt_id, (None, _NO_TIMELINE))
        now = timeline.model_dump(mode="json")
        self._timelines[frame.attempt_id] = (frame.reply_id, now)
        delta = TimelineDelta(changes=tuple(changes_between(held, now)))
        return frame.model_copy(update={"payload": delta})


def _whole(frame: ScreenInsertFrame | ScreenUpdateFrame) -> str:
    return ConversationEvent(frame=frame).model_dump_json(exclude={"frame": {"item": _UNFOLDED}})
