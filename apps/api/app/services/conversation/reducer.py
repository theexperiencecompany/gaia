"""The pure fold of a conversation's log into its state: state_n = reduce(state_{n-1}, entry_n)."""

from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    BargeIn,
    CancelWork,
    CommsPhase,
    ConversationState,
    Effect,
    Entry,
    KickStep,
    LiveWork,
    LoggedEntry,
    Notice,
    Preempt,
    Rejected,
    RejectReason,
    Reply,
    StartAck,
    StopRequested,
    TodoWoke,
    Transition,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
    WorkStarted,
)


def reduce(state: ConversationState, logged: LoggedEntry) -> Transition | Rejected:
    """Return the state after logged and the effects its append must run, or why it is refused."""
    seq = logged.seq
    if seq != state.head + 1:
        return Rejected(reason=RejectReason.OUT_OF_ORDER)
    return _apply(state.model_copy(update={"head": seq}), seq, logged.entry)


def with_comms(state: ConversationState, phase: CommsPhase) -> ConversationState:
    """Return state with the comms phase the step observed; the log never sets thinking."""
    return state.model_copy(update={"comms": phase})


def _apply(state: ConversationState, seq: int, entry: Entry) -> Transition | Rejected:
    result: Transition | Rejected
    match entry:
        case UserMessage(voice=voice, id=message_id):
            ack: tuple[Effect, ...] = () if voice else (StartAck(message_id=message_id),)
            result = Transition(state=_wake(state, seq), effects=(KickStep(), *ack))
        case StopRequested():
            result = _stop(state, seq, entry)
        case BargeIn(reply_id=reply_id):
            result = Transition(
                state=_wake(state, seq), effects=(Preempt(barge_reply_id=reply_id), KickStep())
            )
        case WorkflowFired():
            result = Transition(state=_wake(state, seq), effects=(KickStep(),))
        case TodoWoke() | Notice():
            result = Transition(state=state, effects=())
        case WorkStarted():
            result = _start_work(state, seq, entry)
        case ApprovalRequested():
            result = _request_approval(state, entry)
        case ApprovalDecided(approval_id=approval_id):
            work = tuple(
                item.model_copy(
                    update={"pending_approvals": item.pending_approvals - {approval_id}}
                )
                for item in state.work
            )
            result = Transition(state=state.model_copy(update={"work": work}), effects=())
        case WorkFinished():
            result = _finish_work(state, seq, entry)
        case Reply():
            result = _reply(state, seq, entry)
    return result


def _wake(state: ConversationState, seq: int) -> ConversationState:
    return state.model_copy(update={"unsettled_waking": (*state.unsettled_waking, seq)})


def _stop(state: ConversationState, seq: int, entry: StopRequested) -> Transition | Rejected:
    covers = seq - 1 if entry.covers_through is None else entry.covers_through
    if covers >= seq:
        return Rejected(reason=RejectReason.STOP_COVERS_FUTURE)
    cancelled = tuple(item.task_id for item in state.work if item.cause_through <= covers)
    stopped = state.model_copy(
        update={
            "stopped_through": max(state.stopped_through, covers),
            "unsettled_waking": tuple(
                waking for waking in state.unsettled_waking if waking > covers
            ),
            "work": tuple(item for item in state.work if item.cause_through > covers),
        }
    )
    cancel: tuple[Effect, ...] = (CancelWork(task_ids=cancelled),) if cancelled else ()
    return Transition(state=stopped, effects=(Preempt(stop_through=covers), *cancel))


def _start_work(state: ConversationState, seq: int, entry: WorkStarted) -> Transition | Rejected:
    if entry.cause_through >= seq:
        return Rejected(reason=RejectReason.CAUSE_NOT_BEFORE_WORK)
    if entry.cause_through <= state.stopped_through:
        return Rejected(reason=RejectReason.CAUSE_STOPPED)
    if _live(state, entry.task_id) is not None:
        return Rejected(reason=RejectReason.TASK_ALREADY_LIVE)
    work = LiveWork(
        task_id=entry.task_id,
        cause_through=entry.cause_through,
        answers=entry.answers,
        pending_approvals=frozenset(),
    )
    return Transition(state=state.model_copy(update={"work": (*state.work, work)}), effects=())


def _request_approval(state: ConversationState, entry: ApprovalRequested) -> Transition | Rejected:
    if _live(state, entry.task_id) is None:
        return Rejected(reason=RejectReason.TASK_NOT_LIVE)
    work = tuple(
        item.model_copy(update={"pending_approvals": item.pending_approvals | {entry.approval_id}})
        if item.task_id == entry.task_id
        else item
        for item in state.work
    )
    return Transition(state=state.model_copy(update={"work": work}), effects=())


def _finish_work(state: ConversationState, seq: int, entry: WorkFinished) -> Transition:
    if _live(state, entry.task_id) is None:
        return Transition(state=state, effects=())
    remaining = state.model_copy(
        update={"work": tuple(item for item in state.work if item.task_id != entry.task_id)}
    )
    if entry.outcome is WorkOutcome.CANCELLED:
        return Transition(state=remaining, effects=())
    return Transition(state=_wake(remaining, seq), effects=(KickStep(),))


def _reply(state: ConversationState, seq: int, entry: Reply) -> Transition | Rejected:
    if entry.end is None:
        return Transition(state=with_comms(state, CommsPhase.ANSWERING), effects=())
    if entry.end.through >= seq:
        return Rejected(reason=RejectReason.REPLY_ANSWERS_FUTURE)
    settled = max(state.settled_through, entry.end.through)
    finished = state.model_copy(
        update={
            "comms": CommsPhase.IDLE,
            "settled_through": settled,
            "unsettled_waking": tuple(
                waking for waking in state.unsettled_waking if waking > settled
            ),
        }
    )
    return Transition(state=finished, effects=())


def _live(state: ConversationState, task_id: str) -> LiveWork | None:
    return next((item for item in state.work if item.task_id == task_id), None)
