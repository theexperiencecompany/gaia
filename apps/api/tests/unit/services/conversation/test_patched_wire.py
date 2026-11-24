"""PatchedWire: one wire 2 connection's frames, written against what that connection was sent."""

import json
from typing import cast

from pydantic import JsonValue, TypeAdapter
import pytest

from app.models.conversation_frame_models import RetractFrame
from app.models.conversation_log_models import WorkStarted
from app.models.conversation_screen_models import (
    ScreenFrame,
    ScreenInsertFrame,
    ScreenItem,
    ScreenStreamFrame,
    ScreenUpdateFrame,
    WorkItem,
)
from app.services.conversation.patched_wire import PatchedWire
from app.services.conversation.screen import project_screen
from app.services.conversation.tool_timeline import tool_timeline
from app.utils.artifact_utils import FILE_LINKS
from shared.py.conversation_wire import (
    BubbleTextDelta,
    CardsDelta,
    ItemChange,
    ReplyDeltaFrame,
    ReplyOutcome,
    ToolDataEntry,
    ToolTimeline,
)
from tests.unit.services.conversation.change_helpers import with_changes
from tests.unit.services.conversation.log_helpers import logged, opened, settled, user

pytestmark = pytest.mark.unit

_CHANGES: TypeAdapter[list[ItemChange]] = TypeAdapter(list[ItemChange])
_Json = dict[str, JsonValue]
_EMPTY: JsonValue = ToolTimeline().model_dump(mode="json")


def _sent(wire: PatchedWire, frame: ScreenStreamFrame) -> _Json:
    return cast(_Json, json.loads(wire.line(frame))["frame"])


def _call(call_id: str, output: str | None = None) -> ToolDataEntry:
    data = {"tool_name": "LIST", "tool_call_id": call_id, "message": f"Listing {call_id}"}
    return {"tool_name": "tool_calls_data", "data": data | ({"output": output} if output else {})}


def _work(*cards: ToolDataEntry) -> WorkItem:
    (item,) = project_screen(
        "c1", [logged(1, WorkStarted(id="work:t1", task_id="t1", cause_through=1))], FILE_LINKS
    )
    assert isinstance(item, WorkItem)
    return item.model_copy(update={"tool_data": cards, "timeline": tool_timeline(cards)})


def _cards(attempt: str, index: int, *cards: ToolDataEntry) -> ReplyDeltaFrame:
    payload = CardsDelta(tool_data=cards, timeline=tool_timeline(cards))
    return ReplyDeltaFrame(attempt_id=attempt, reply_id="r1", index=index, payload=payload)


def _timeline(*cards: ToolDataEntry) -> JsonValue:
    return tool_timeline(cards).model_dump(mode="json")


def _applied(held: JsonValue, frame: _Json) -> JsonValue:
    payload = cast(_Json, frame["payload"])
    assert payload["type"] == "timeline"
    return with_changes(held, _CHANGES.validate_python(payload["changes"]))


def test_the_opening_screen_carries_no_unfolded_cards() -> None:
    frame = _sent(PatchedWire(), ScreenFrame(items=(_work(_call("a", "out")),), head=1))
    (item,) = cast(list[_Json], frame["items"])
    assert "tool_data" not in item
    assert len(cast(list[JsonValue], cast(_Json, item["timeline"])["steps"])) == 1


def test_a_change_to_a_sent_item_is_a_patch_that_carries_it_to_the_new_item() -> None:
    wire = PatchedWire()
    first = _sent(wire, ScreenInsertFrame(item=_work(_call("a")), head=1))
    after = _work(_call("a", "o" * 4000), _call("b"))
    patch = _sent(wire, ScreenUpdateFrame(item=after, head=1))
    assert patch["kind"] == "screen_patch"
    assert (patch["id"], patch["head"]) == ("work:t1", 1)
    changes = _CHANGES.validate_python(patch["changes"])
    assert with_changes(first["item"], changes) == after.model_dump(
        mode="json", exclude={"tool_data"}
    )
    assert len(json.dumps(patch)) < 1.25 * 4000


def test_each_patch_is_against_the_item_as_the_last_one_left_it() -> None:
    wire = PatchedWire()
    held = _sent(wire, ScreenInsertFrame(item=_work(_call("a")), head=1))["item"]
    for cards in ((_call("a", "one"),), (_call("a", "one"), _call("b", "two"))):
        patch = _sent(wire, ScreenUpdateFrame(item=_work(*cards), head=1))
        held = with_changes(held, _CHANGES.validate_python(patch["changes"]))
    assert cast(_Json, held)["timeline"] == _timeline(_call("a", "one"), _call("b", "two"))


def test_a_change_to_an_item_the_connection_never_sent_goes_whole_then_patches() -> None:
    wire = PatchedWire()
    whole = _sent(wire, ScreenUpdateFrame(item=_work(_call("a")), head=1))
    assert whole["kind"] == "screen_update"
    assert "tool_data" not in cast(_Json, whole["item"])
    later = _sent(wire, ScreenUpdateFrame(item=_work(_call("a", "o")), head=1))
    assert later["kind"] == "screen_patch"


def test_a_reply_s_cards_reach_the_client_as_changes_to_its_timeline_from_empty() -> None:
    wire = PatchedWire()
    held = _applied(_EMPTY, _sent(wire, _cards("a1", 0, _call("a"))))
    grown = _sent(wire, _cards("a1", 1, _call("a", "o" * 4000), _call("b")))
    assert _applied(held, grown) == _timeline(_call("a", "o" * 4000), _call("b"))
    assert "tool_data" not in cast(_Json, grown["payload"])
    assert len(json.dumps(grown)) < 1.25 * 4000


def test_two_attempts_keep_their_own_timelines() -> None:
    wire = PatchedWire()
    _sent(wire, _cards("a1", 0, _call("a")))
    other = _sent(wire, _cards("a2", 0, _call("z")))
    assert _applied(_EMPTY, other) == _timeline(_call("z"))


def test_a_retracted_attempt_s_next_cards_start_from_an_empty_timeline() -> None:
    wire = PatchedWire()
    _sent(wire, _cards("a1", 0, _call("a")))
    _sent(wire, RetractFrame(attempt_id="a1"))
    again = _sent(wire, _cards("a1", 0, _call("a")))
    assert _applied(_EMPTY, again) == _timeline(_call("a"))


def _reply(outcome: ReplyOutcome | None) -> ScreenItem:
    entries = [logged(1, user("m1")), logged(2, opened("e2").model_copy(update={"text": "hi"}))]
    if outcome is not None:
        entries.append(logged(3, settled("e3", ["m1"], 1, outcome=outcome)))
    return project_screen("c1", entries, FILE_LINKS)[-1]


def test_a_settled_reply_s_attempt_starts_over_from_an_empty_timeline() -> None:
    wire = PatchedWire()
    _sent(wire, ScreenInsertFrame(item=_reply(None), head=2))
    _sent(wire, _cards("a1", 0, _call("a")))
    _sent(wire, ScreenUpdateFrame(item=_reply(ReplyOutcome.ANSWERED), head=3))
    again = _sent(wire, _cards("a1", 0, _call("a")))
    assert _applied(_EMPTY, again) == _timeline(_call("a"))


def test_frames_that_carry_no_item_or_cards_pass_through_as_they_are() -> None:
    delta = ReplyDeltaFrame(
        attempt_id="a1", reply_id="r1", index=0, payload=BubbleTextDelta(bubble=0, text="hi")
    )
    assert _sent(PatchedWire(), delta) == delta.model_dump(mode="json")
