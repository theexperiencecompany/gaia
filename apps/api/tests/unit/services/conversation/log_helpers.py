"""Builders for conversation log entries and a fold over reduce, shared by the reducer tests."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.constants.chat import ConversationSource
from app.constants.todos import TodoWakeKind
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    BargeIn,
    CommsPhase,
    ConversationState,
    Effect,
    Entry,
    FailureReason,
    LoggedEntry,
    Notice,
    Rejected,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StopBy,
    StopRequested,
    TodoWoke,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkflowRun,
    WorkOutcome,
    WorkStarted,
)
from app.models.message_models import SelectedWorkflowData
from app.models.todo_wake_models import TodoRunWake
from app.models.workflow_trigger_models import WorkflowTriggerContext
from app.services.conversation.reducer import reduce
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import worker_context

EMPTY = ConversationState(
    head=0,
    settled_through=0,
    stopped_through=0,
    unsettled_waking=(),
    comms=CommsPhase.IDLE,
    open_reply=None,
    work=(),
)
T0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def at(seq: int) -> datetime:
    return T0 + timedelta(seconds=seq)


def logged(seq: int, entry: Entry) -> LoggedEntry:
    return LoggedEntry(seq=seq, at=at(seq), entry=entry)


def user(entry_id: str, *, voice: bool = False) -> UserMessage:
    return UserMessage(
        id=entry_id, text=f"text of {entry_id}", surface=ConversationSource.WEB, voice=voice
    )


def stop(
    entry_id: str, covers_through: int | None = None, by: StopBy = StopBy.USER
) -> StopRequested:
    return StopRequested(id=entry_id, by=by, covers_through=covers_through)


def barge(entry_id: str, reply_id: str) -> BargeIn:
    return BargeIn(id=entry_id, reply_id=reply_id, heard_text="heard")


def workflow_run(execution_id: str = "ex_1") -> WorkflowRun:
    return WorkflowRun(
        workflow=SelectedWorkflowData(
            id="wf_1", title="Morning brief", description="Brief me", steps=[]
        ),
        execution_id=execution_id,
        timezone="Asia/Kolkata",
        reservation=f":{execution_id}-reservation",
        trigger=WorkflowTriggerContext(workflow_id="wf_1"),
        attribution=worker_context(Trigger.SCHEDULE).attribution,
    )


def fired(entry_id: str, execution_id: str = "ex_1") -> WorkflowFired:
    return WorkflowFired(id=entry_id, run=workflow_run(execution_id))


def todo_woke(entry_id: str) -> TodoWoke:
    wake = TodoRunWake(kind=TodoWakeKind.SCHEDULE, trigger_names=[], approval_summary=None)
    return TodoWoke(id=entry_id, todo_id="todo_1", wake=wake)


def notice(entry_id: str) -> Notice:
    return Notice(id=entry_id, text="delivered", origin="reminder")


def started(entry_id: str, task_id: str, cause_through: int) -> WorkStarted:
    return WorkStarted(id=entry_id, task_id=task_id, cause_through=cause_through)


def asked(entry_id: str, task_id: str, approval_id: str) -> ApprovalRequested:
    return ApprovalRequested(id=entry_id, task_id=task_id, approval_id=approval_id)


def decided(entry_id: str, approval_id: str) -> ApprovalDecided:
    return ApprovalDecided(id=entry_id, approval_id=approval_id, decision="approve")


def finished(entry_id: str, task_id: str, outcome: WorkOutcome = WorkOutcome.DONE) -> WorkFinished:
    return WorkFinished(id=entry_id, task_id=task_id, outcome=outcome, report="report")


def opened(entry_id: str, reply_id: str = "r1") -> Reply:
    return Reply(id=entry_id, reply_id=reply_id, attempt_id="a1")


def settled(
    entry_id: str,
    answers: Sequence[str],
    through: int,
    *,
    reply_id: str = "r1",
    outcome: ReplyOutcome = ReplyOutcome.ANSWERED,
) -> ReplySettled:
    return ReplySettled(
        id=entry_id,
        reply_id=reply_id,
        outcome=outcome,
        answers=tuple(answers),
        through=through,
        quote_target=None,
        failure=FailureReason.SERVER_RESTART if outcome is ReplyOutcome.FAILED else None,
    )


def replied(
    entry_id: str, answers: Sequence[str], through: int, *, reply_id: str = "r1"
) -> list[Entry]:
    """Open a reply and settle it as answered: two entries, two seqs."""
    return [
        opened(f"{entry_id}-open", reply_id),
        settled(entry_id, answers, through, reply_id=reply_id),
    ]


def fold(entries: Sequence[Entry]) -> tuple[ConversationState, list[Effect]]:
    """Fold entries numbered 1..n from the empty state; fail on any rejection."""
    state = EMPTY
    effects: list[Effect] = []
    for seq, entry in enumerate(entries, start=1):
        result = reduce(state, logged(seq, entry))
        assert not isinstance(result, Rejected), f"seq {seq} rejected: {result.reason}"
        state = result.state
        effects.extend(result.effects)
    return state, effects
