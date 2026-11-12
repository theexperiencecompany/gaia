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
    FinishedWork,
    KickStep,
    LiveWork,
    LoggedEntry,
    Notice,
    Preempt,
    Rejected,
    RejectReason,
    Reply,
    ReplySettled,
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
        case UserMessage() | BargeIn() | WorkflowFired():
            result = Transition(state=_wake(state, seq), effects=_wake_effects(entry))
        case StopRequested():
            result = _stop(state, seq, entry)
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
            result = _open_reply(state, entry)
        case ReplySettled():
            result = _settle_reply(state, seq, entry)
    return result


def _wake_effects(entry: UserMessage | BargeIn | WorkflowFired) -> tuple[Effect, ...]:
    match entry:
        case UserMessage(voice=False, id=message_id):
            return (KickStep(), StartAck(message_id=message_id))
        case BargeIn(reply_id=reply_id):
            return (Preempt(barge_reply_id=reply_id), KickStep())
        case _:
            return (KickStep(),)


def _wake(state: ConversationState, seq: int) -> ConversationState:
    return state.model_copy(update={"unsettled_waking": (*state.unsettled_waking, seq)})


def _stop(state: ConversationState, seq: int, entry: StopRequested) -> Transition | Rejected:
    covers = seq - 1 if entry.covers_through is None else entry.covers_through
    if covers >= seq:
        return Rejected(reason=RejectReason.STOP_COVERS_FUTURE)
    cancelled = tuple(item.task_id for item in state.work if item.cause_through <= covers)
    stopped = _drop_waking_through(state, covers).model_copy(
        update={
            "stopped_through": max(state.stopped_through, covers),
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
    live = _live(state, entry.task_id)
    if live is None:
        return Transition(state=state, effects=())
    remaining = state.model_copy(
        update={"work": tuple(item for item in state.work if item.task_id != entry.task_id)}
    )
    if entry.outcome is WorkOutcome.CANCELLED:
        return Transition(state=remaining, effects=())
    result = FinishedWork(
        seq=seq, task_id=entry.task_id, cause_through=live.cause_through, answers=live.answers
    )
    awaiting = remaining.model_copy(update={"finished_work": (*state.finished_work, result)})
    return Transition(state=_wake(awaiting, seq), effects=(KickStep(),))


def _open_reply(state: ConversationState, entry: Reply) -> Transition | Rejected:
    if state.open_reply is not None:
        return Rejected(reason=RejectReason.REPLY_ALREADY_OPEN)
    opened = state.model_copy(update={"comms": CommsPhase.ANSWERING, "open_reply": entry.reply_id})
    return Transition(state=opened, effects=())


def _settle_reply(state: ConversationState, seq: int, entry: ReplySettled) -> Transition | Rejected:
    if entry.reply_id != state.open_reply:
        return Rejected(reason=RejectReason.REPLY_NOT_OPEN)
    if entry.through >= seq:
        return Rejected(reason=RejectReason.REPLY_ANSWERS_FUTURE)
    settled = max(state.settled_through, entry.through)
    finished = _drop_waking_through(state, settled).model_copy(
        update={"comms": CommsPhase.IDLE, "open_reply": None, "settled_through": settled}
    )
    return Transition(state=finished, effects=())


def _drop_waking_through(state: ConversationState, seq: int) -> ConversationState:
    return state.model_copy(
        update={
            "unsettled_waking": tuple(waking for waking in state.unsettled_waking if waking > seq),
            "finished_work": tuple(item for item in state.finished_work if item.seq > seq),
        }
    )


def _live(state: ConversationState, task_id: str) -> LiveWork | None:
    return next((item for item in state.work if item.task_id == task_id), None)
