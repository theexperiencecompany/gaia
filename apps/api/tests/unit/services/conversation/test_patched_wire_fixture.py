"""A scripted run as wire 2 writes it, which the clients' applier replays (libs/shared/ts/src/conversation/view.test.ts).

The frames are the real tracker's patches through the real encoder, so the server's changes and
the TypeScript that applies them are proven as a pair: this file fails when the server's output
drifts from the committed fixture, and the client's test fails when it cannot reach the same items.
"""

from dataclasses import dataclass
import json
import os

from pydantic import BaseModel, ConfigDict, JsonValue
import pytest

from app.models.conversation_frame_models import (
    EntryFrame,
    ReasoningEvent,
    StreamPayload,
    SubagentEndEvent,
    SubagentStartEvent,
    TodoProgressEvent,
    ToolDataEvent,
    ToolOutputEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    Entry,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_screen_models import ScreenFrame, ScreenStreamFrame
from app.models.stream_events import (
    ReasoningPayload,
    SubagentEndPayload,
    SubagentStartPayload,
    ToolOutputPayload,
)
from app.services.conversation.patched_wire import PatchedWire
from app.services.conversation.screen_patches import ScreenTracker
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation.tool_timeline import tool_timeline
from shared.py.conversation_wire import (
    CardsDelta,
    ChangeOp,
    ItemChange,
    ReplyDeltaFrame,
    ToolDataEntry,
)
from tests.helpers import REPO_ROOT
from tests.unit.services.conversation.change_helpers import with_changes
from tests.unit.services.conversation.log_helpers import at, logged, opened, settled, user

pytestmark = pytest.mark.unit

FIXTURE = REPO_ROOT / "libs/shared/ts/src/conversation/fixtures/wire2-run.frames.json"
#: Set to write the fixture from this run instead of comparing against it.
_REWRITE = "REWRITE_WIRE2_FIXTURE"
CONVERSATION = "c-wire2"
STARTED_AT = "2026-11-12T09:00:02+00:00"


def _call(call_id: str, subagent_id: str | None = None) -> ToolDataEvent:
    card: ToolDataEntry = {
        "tool_name": "tool_calls_data",
        "tool_category": "gmail",
        "data": {
            "tool_name": "GMAIL_FETCH",
            "tool_category": "gmail",
            "message": f"Fetching {call_id}",
            "tool_call_id": call_id,
            "inputs": {"query": call_id},
        },
    }
    if subagent_id is not None:
        card["subagent_id"] = subagent_id
    return ToolDataEvent(tool_data=card)


def _output(call_id: str, subagent_id: str | None = None) -> ToolOutputEvent:
    return ToolOutputEvent(
        tool_output=ToolOutputPayload(
            tool_call_id=call_id, output=f"result of {call_id}", subagent_id=subagent_id
        )
    )


def _thinks(text: str, subagent_id: str | None = None) -> ReasoningEvent:
    return ReasoningEvent(reasoning=ReasoningPayload(content=text, subagent_id=subagent_id))


#: What one executor run publishes: its own calls, a subagent's, thinking that grows, and its todos.
WORK: tuple[StreamPayload, ...] = (
    _thinks("I should "),
    _thinks("look at the inbox."),
    _call("c1"),
    _output("c1"),
    SubagentStartEvent(
        subagent_start=SubagentStartPayload(
            subagent_id="s1",
            subagent_name="Gmail",
            agent_type="spawned",
            started_at=STARTED_AT,
            tool_category="gmail",
        )
    ),
    _thinks("Reading ", "s1"),
    _thinks("three threads.", "s1"),
    _call("c2", "s1"),
    _call("c3", "s1"),
    _output("c2", "s1"),
    _output("c3", "s1"),
    SubagentEndEvent(subagent_end=SubagentEndPayload(subagent_id="s1", duration_ms=1500)),
    TodoProgressEvent(todo_progress={"source": "executor", "todos": [{"id": "t", "done": False}]}),
    TodoProgressEvent(todo_progress={"source": "executor", "todos": [{"id": "t", "done": True}]}),
    _call("c4"),
)


def _entry(seq: int, entry: Entry) -> EntryFrame:
    return EntryFrame(seq=seq, at=at(seq), entry=entry)


class _Sent(BaseModel):
    """One frame of the run, read back as a client reads it."""

    model_config = ConfigDict(extra="ignore")

    kind: str
    id: str | None = None
    base: int | None = None
    changes: list[ItemChange] = []
    item: dict[str, JsonValue] | None = None
    items: list[dict[str, JsonValue]] = []


@dataclass(frozen=True)
class _Run:
    """The frames a wire 2 connection is sent over one run, and what a client holds at its end."""

    lines: list[str]
    items: list[JsonValue]
    reply_timeline: JsonValue

    @property
    def frames(self) -> list[_Sent]:
        return [_Sent.model_validate(json.loads(line)["frame"]) for line in self.lines]

    def fixture(self) -> JsonValue:
        return {
            "frames": [json.loads(line) for line in self.lines],
            "items": self.items,
            "reply_timeline": self.reply_timeline,
        }


async def _run() -> _Run:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    tracker = ScreenTracker(CONVERSATION, [logged(1, user("u1")), logged(2, started)], {})
    wire = PatchedWire()
    lines: list[str] = []

    def send(*frames: ScreenStreamFrame) -> None:
        lines.extend(wire.line(frame) for frame in frames)

    send(ScreenFrame(items=tuple(tracker.items), head=tracker.head))
    for index, payload in enumerate(WORK):
        send(*await tracker.on_work(WorkDeltaFrame(task_id="t1", index=index, payload=payload)))
    finished = WorkFinished(
        id="work:t1:finished",
        task_id="t1",
        outcome=WorkOutcome.DONE,
        report="read three threads",
        tool_data=fold_cards(WORK).tool_data,
    )
    send(*tracker.take(_entry(3, finished)))
    reply = opened("r1").model_copy(update={"text": "Three threads need you."})
    send(*tracker.take(_entry(4, reply)))
    own: list[ToolDataEntry] = []
    shown: tuple[StreamPayload, ...] = (_call("c5"), _output("c5"))
    for index, card in enumerate(shown):
        own = list(fold_cards([card], own).tool_data)
        delta = CardsDelta(tool_data=tuple(own), timeline=tool_timeline(own))
        send(ReplyDeltaFrame(attempt_id="a1", reply_id="r1", index=index, payload=delta))
    send(*tracker.take(_entry(5, settled("s5", ["u1"], 1))))
    return _Run(
        lines=lines,
        items=[item.model_dump(mode="json", exclude={"tool_data"}) for item in tracker.items],
        reply_timeline=tool_timeline(own).model_dump(mode="json"),
    )


async def test_the_run_the_clients_replay_is_what_the_server_sends() -> None:
    run = (await _run()).fixture()
    if os.environ.get(_REWRITE):
        FIXTURE.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(FIXTURE.read_text()) == run, f"rerun with {_REWRITE}=1 and commit"


async def test_the_run_patches_inside_a_subagent_group_and_grows_text_in_place() -> None:
    patches = [frame for frame in (await _run()).frames if frame.kind == "screen_patch"]
    changes = [change for frame in patches for change in frame.changes]
    assert {change.op for change in changes} >= {ChangeOp.SET, ChangeOp.APPEND}
    assert any("tool_calls" in change.path for change in changes)
    work = [frame.base for frame in patches if frame.id == "work:t1"]
    assert work == list(range(len(work)))
    assert len(work) > len(WORK) // 2


async def test_applying_the_run_s_patches_in_order_gives_the_screen_it_ends_on() -> None:
    run = await _run()
    held: dict[str, JsonValue] = {}
    for frame in run.frames:
        if frame.item is not None:
            held[str(frame.item["id"])] = frame.item
        elif frame.kind == "screen_patch" and frame.id is not None:
            held[frame.id] = with_changes(held[frame.id], frame.changes)
        else:
            held.update((str(item["id"]), item) for item in frame.items)
    assert list(held.values()) == run.items
