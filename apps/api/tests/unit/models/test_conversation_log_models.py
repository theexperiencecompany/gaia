"""Shape rules of the conversation log and frame types: what can and cannot be built, and how they round-trip."""

from collections.abc import Callable

from pydantic import BaseModel, TypeAdapter, ValidationError
import pytest

from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    FollowUpActionsEvent,
    LiveTask,
    MessageBoundaryEvent,
    OutputFrame,
    ReasoningEvent,
    ReplyDeltaFrame,
    ResponseEvent,
    RetractFrame,
    StateFrame,
    StreamPayload,
    StreamPayloadType,
    SubagentEndEvent,
    SubagentStartEvent,
    TodoProgressEvent,
    ToolDataEvent,
    ToolOutputEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    DisplayState,
    Entry,
    LiveWork,
    LoggedEntry,
    Reaction,
    ReactionBy,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
)
from app.models.stream_events import (
    MessageBoundaryPayload,
    ReasoningPayload,
    SubagentEndPayload,
    SubagentStartPayload,
    ToolOutputPayload,
)
from tests.unit.services.conversation.log_helpers import (
    T0,
    asked,
    barge,
    decided,
    finished,
    fired,
    logged,
    notice,
    opened,
    settled,
    started,
    stop,
    todo_woke,
    user,
)

_ALL_ENTRIES: list[Entry] = [
    user("u"),
    user("u").model_copy(
        update={"reaction": Reaction(emoji="👍", by=ReactionBy.JEV), "revision": 2}
    ),
    stop("s", 0),
    barge("b", "r"),
    fired("f"),
    todo_woke("t"),
    notice("n"),
    started("w", "t1", 1),
    asked("a", "t1", "ap"),
    decided("d", "ap"),
    finished("x", "t1"),
    opened("o"),
    settled("r", ["u"], 1),
    settled("r", [], 1, outcome=ReplyOutcome.FAILED).model_copy(update={"quote_target": "u"}),
]


def _state(comms: CommsPhase, *work: LiveWork) -> ConversationState:
    return ConversationState.empty().model_copy(update={"comms": comms, "work": work})


def _work(*approvals: str) -> LiveWork:
    return LiveWork(
        task_id="t1", cause_through=1, answers=(), pending_approvals=frozenset(approvals)
    )


def _settle(outcome: ReplyOutcome) -> ReplySettled:
    return ReplySettled(
        id="s", reply_id="r", outcome=outcome, answers=(), through=1, quote_target=None
    )


@pytest.mark.parametrize("entry", _ALL_ENTRIES, ids=lambda entry: entry.kind)
def test_every_entry_kind_round_trips_through_json_as_itself(entry: Entry) -> None:
    item = logged(1, entry)
    assert LoggedEntry.model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize("outcome", [ReplyOutcome.STOPPED, ReplyOutcome.FAILED])
def test_a_stopped_or_failed_reply_may_settle_answering_nothing(outcome: ReplyOutcome) -> None:
    assert _settle(outcome).answers == ()


@pytest.mark.parametrize("outcome", [ReplyOutcome.ANSWERED, ReplyOutcome.SILENT])
def test_an_answered_or_silent_reply_must_name_what_it_answers(outcome: ReplyOutcome) -> None:
    with pytest.raises(ValidationError):
        _settle(outcome)


def test_a_settled_reply_must_state_its_quote_target() -> None:
    with pytest.raises(ValidationError):
        ReplySettled.model_validate(
            {"id": "s", "reply_id": "r", "outcome": "answered", "answers": ["u"], "through": 1}
        )


def test_an_entry_without_an_id_cannot_be_constructed() -> None:
    with pytest.raises(ValidationError):
        LoggedEntry.model_validate(
            {"seq": 1, "at": T0, "entry": {"kind": "notice", "id": "", "text": "t", "origin": "o"}}
        )


def test_an_entry_with_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        LoggedEntry.model_validate(
            {
                "seq": 1,
                "at": T0,
                "entry": {"kind": "notice", "id": "n", "text": "t", "origin": "o", "extra": 1},
            }
        )


def test_a_logged_entry_needs_a_timezone_and_a_positive_seq() -> None:
    with pytest.raises(ValidationError):
        LoggedEntry(seq=1, at=T0.replace(tzinfo=None), entry=notice("n"))
    with pytest.raises(ValidationError):
        LoggedEntry(seq=0, at=T0, entry=notice("n"))


def test_a_reaction_needs_an_emoji_and_a_revision_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        Reaction(emoji="", by=ReactionBy.CHAT_MODEL)
    with pytest.raises(ValidationError):
        UserMessage.model_validate({**user("u").model_dump(), "revision": -1})


@pytest.mark.parametrize(
    ("state", "display"),
    [
        (_state(CommsPhase.IDLE), DisplayState.IDLE),
        (_state(CommsPhase.IDLE, _work()), DisplayState.WORKING),
        (_state(CommsPhase.IDLE, _work("ap")), DisplayState.AWAITING_APPROVAL),
        (_state(CommsPhase.THINKING), DisplayState.THINKING),
        (_state(CommsPhase.ANSWERING, _work()), DisplayState.THINKING),
        (_state(CommsPhase.THINKING, _work("ap")), DisplayState.THINKING),
    ],
)
def test_display_puts_comms_first_then_approvals_then_work(
    state: ConversationState, display: DisplayState
) -> None:
    assert state.display is display


_PAYLOADS: list[StreamPayload] = [
    ResponseEvent(response="hi"),
    ReasoningEvent(reasoning=ReasoningPayload(content="thinking")),
    ToolDataEvent(tool_data={"tool_name": "search", "data": {"q": "x"}, "tool_category": "web"}),
    ToolOutputEvent(tool_output=ToolOutputPayload(tool_call_id="c1", output="ok")),
    MessageBoundaryEvent(message_boundary=MessageBoundaryPayload(message_id="m1", discarded=True)),
    SubagentStartEvent(
        subagent_start=SubagentStartPayload(
            subagent_id="s1", subagent_name="gmail", agent_type="mcp", started_at="now"
        )
    ),
    SubagentEndEvent(subagent_end=SubagentEndPayload(subagent_id="s1", duration_ms=10)),
    FollowUpActionsEvent(follow_up_actions=["more"]),
    TodoProgressEvent(todo_progress={"done": 1}),
]


def test_every_payload_tag_has_exactly_one_payload_model() -> None:
    assert sorted(payload.type for payload in _PAYLOADS) == sorted(StreamPayloadType)


@pytest.mark.parametrize("payload", _PAYLOADS, ids=lambda payload: type(payload).__name__)
def test_a_payload_is_the_chat_stream_event_plus_its_tag(payload: StreamPayload) -> None:
    dumped = payload.model_dump(mode="json")
    tag = dumped.pop("type")
    assert list(dumped) == [tag]


@pytest.mark.parametrize("payload", _PAYLOADS, ids=lambda payload: type(payload).__name__)
@pytest.mark.parametrize(
    "frame_of",
    [
        lambda payload: ReplyDeltaFrame(attempt_id="a", reply_id=None, index=0, payload=payload),
        lambda payload: WorkDeltaFrame(task_id="t1", index=3, payload=payload),
    ],
    ids=["reply_delta", "work_delta"],
)
def test_every_delta_round_trips_with_its_payload_type(
    payload: StreamPayload, frame_of: Callable[[StreamPayload], ReplyDeltaFrame | WorkDeltaFrame]
) -> None:
    frame = frame_of(payload)
    parsed: OutputFrame = TypeAdapter(OutputFrame).validate_json(frame.model_dump_json())
    assert isinstance(parsed, ReplyDeltaFrame | WorkDeltaFrame)
    assert type(parsed) is type(frame)
    assert type(parsed.payload) is type(payload)
    assert parsed == frame


def test_a_payload_without_its_tag_is_refused() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(OutputFrame).validate_python(
            {"kind": "work_delta", "task_id": "t1", "index": 0, "payload": {"response": "hi"}}
        )


def test_a_delta_index_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        WorkDeltaFrame(task_id="t1", index=-1, payload=ResponseEvent(response="hi"))


@pytest.mark.parametrize(
    "frame",
    [
        EntryFrame(seq=1, at=T0, entry=user("u")),
        EntryUpdatedFrame(
            seq=1, entry=opened("o").model_copy(update={"text": "done", "revision": 1})
        ),
        RetractFrame(attempt_id="a"),
        StateFrame(
            head=3,
            display=DisplayState.AWAITING_APPROVAL,
            work=(
                LiveTask(task_id="t1", awaiting_approval=True),
                LiveTask(task_id="t2", awaiting_approval=False),
            ),
        ),
    ],
    ids=lambda frame: frame.kind,
)
def test_output_frames_round_trip_on_their_kind(frame: BaseModel) -> None:
    assert TypeAdapter(OutputFrame).validate_json(frame.model_dump_json()) == frame
