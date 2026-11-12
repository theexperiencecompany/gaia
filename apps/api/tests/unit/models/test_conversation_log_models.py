"""Shape rules of the conversation log types: what can and cannot be constructed, and how they round-trip."""

from pydantic import BaseModel, TypeAdapter, ValidationError
import pytest

from app.models.conversation_frame_models import (
    DeltaFrame,
    DeltaPayload,
    OutputFrame,
    RetractFrame,
    StateFrame,
)
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationDisplay,
    ConversationState,
    Entry,
    LiveWork,
    LoggedEntry,
    ReplyOutcome,
    ReplySettled,
    WorkPhase,
)
from app.models.hil_models import HILApprovalStatus
from app.models.stream_events import (
    ApprovalRequestEntry,
    ApprovalRequestEntryData,
    FollowUpActionsFrame,
    MessageBoundaryPayload,
    ReasoningPayload,
    ResponseFrame,
    SubagentEndPayload,
    SubagentStartPayload,
    TodoProgressFrame,
    ToolCallsDataEntry,
    ToolCallsDataEntryData,
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
    settled("r", [], 1, outcome=ReplyOutcome.FAILED),
]


def _state(comms: CommsPhase, *work: LiveWork) -> ConversationState:
    return ConversationState.empty().model_copy(update={"comms": comms, "work": work})


def _work(*approvals: str) -> LiveWork:
    return LiveWork(
        task_id="t1", cause_through=1, answers=(), pending_approvals=frozenset(approvals)
    )


@pytest.mark.parametrize("entry", _ALL_ENTRIES, ids=lambda entry: entry.kind)
def test_every_entry_kind_round_trips_through_json_as_itself(entry: Entry) -> None:
    item = logged(1, entry)
    assert LoggedEntry.model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize("outcome", [ReplyOutcome.STOPPED, ReplyOutcome.FAILED])
def test_a_stopped_or_failed_reply_may_settle_answering_nothing(outcome: ReplyOutcome) -> None:
    assert ReplySettled(id="s", reply_id="r", outcome=outcome, answers=(), through=1).answers == ()


@pytest.mark.parametrize("outcome", [ReplyOutcome.ANSWERED, ReplyOutcome.SILENT])
def test_an_answered_or_silent_reply_must_name_what_it_answers(outcome: ReplyOutcome) -> None:
    with pytest.raises(ValidationError):
        ReplySettled(id="s", reply_id="r", outcome=outcome, answers=(), through=1)


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


@pytest.mark.parametrize(
    ("state", "display", "work_phase"),
    [
        (_state(CommsPhase.IDLE), ConversationDisplay.IDLE, WorkPhase.NONE),
        (_state(CommsPhase.IDLE, _work()), ConversationDisplay.WORKING, WorkPhase.RUNNING),
        (
            _state(CommsPhase.IDLE, _work("ap")),
            ConversationDisplay.AWAITING_APPROVAL,
            WorkPhase.AWAITING_APPROVAL,
        ),
        (_state(CommsPhase.THINKING), ConversationDisplay.THINKING, WorkPhase.NONE),
        (_state(CommsPhase.ANSWERING, _work()), ConversationDisplay.THINKING, WorkPhase.RUNNING),
        (
            _state(CommsPhase.THINKING, _work("ap")),
            ConversationDisplay.THINKING,
            WorkPhase.AWAITING_APPROVAL,
        ),
    ],
)
def test_display_puts_comms_first_and_work_phase_ignores_comms(
    state: ConversationState, display: ConversationDisplay, work_phase: WorkPhase
) -> None:
    assert (state.display, state.work_phase) == (display, work_phase)


@pytest.mark.parametrize(("reply_id", "task_id"), [(None, None), ("r", "t")])
def test_a_delta_targets_exactly_one_of_a_reply_or_a_task(
    reply_id: str | None, task_id: str | None
) -> None:
    with pytest.raises(ValidationError):
        DeltaFrame(
            attempt_id="a", reply_id=reply_id, task_id=task_id, payload=ResponseFrame(response="x")
        )


_PAYLOADS: list[BaseModel] = [
    ResponseFrame(response="hi"),
    ReasoningPayload(content="thinking"),
    ToolCallsDataEntry(
        tool_name="search",
        tool_category="web",
        data=ToolCallsDataEntryData(
            tool_name="search",
            tool_category="web",
            message=None,
            show_category=True,
            tool_call_id="c1",
            inputs={},
            icon_url=None,
            integration_name=None,
        ),
        timestamp="2026-11-12T09:00:00Z",
        mcp_ui=None,
        mcp_server_url=None,
    ),
    ApprovalRequestEntry(
        tool_name="approval_request",
        tool_category="hil",
        data=ApprovalRequestEntryData(
            approval_id="ap",
            tool_call_id="c1",
            gated_tool_name="send_email",
            integration_name=None,
            summary="Send it",
            args_preview={},
            status=HILApprovalStatus.PENDING,
            feedback=None,
            auto_reason=None,
            timeout_seconds=60,
        ),
        timestamp="2026-11-12T09:00:00Z",
    ),
    ToolOutputPayload(tool_call_id="c1", output="ok"),
    MessageBoundaryPayload(message_id="m1", discarded=True),
    SubagentStartPayload(
        subagent_id="s1", subagent_name="gmail", agent_type="mcp", started_at="now"
    ),
    SubagentEndPayload(subagent_id="s1", duration_ms=10),
    FollowUpActionsFrame(follow_up_actions=["more"]),
    TodoProgressFrame(todo_progress={"done": 1}),
]


@pytest.mark.parametrize("payload", _PAYLOADS, ids=lambda payload: type(payload).__name__)
def test_every_delta_payload_round_trips_as_its_own_type(payload: DeltaPayload) -> None:
    frame = DeltaFrame(attempt_id="a", task_id="t1", payload=payload)
    parsed = TypeAdapter(OutputFrame).validate_json(frame.model_dump_json())
    assert isinstance(parsed, DeltaFrame)
    assert type(parsed.payload) is type(payload)
    assert parsed == frame


@pytest.mark.parametrize(
    "frame",
    [
        RetractFrame(attempt_id="a"),
        StateFrame(head=3, display=ConversationDisplay.WORKING, work_phase=WorkPhase.RUNNING),
    ],
    ids=lambda frame: frame.kind,
)
def test_output_frames_round_trip_on_their_kind(frame: BaseModel) -> None:
    assert TypeAdapter(OutputFrame).validate_json(frame.model_dump_json()) == frame
