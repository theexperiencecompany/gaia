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
    IntegrationConnected,
    IntegrationNeeded,
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
from shared.py.approvals import ApprovalOutcome

#: Decisions the user made: the decision path starts the work that carries them out or reports the skip.
USER_DECISIONS = frozenset({ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED})


def reduce(state: ConversationState, logged: LoggedEntry) -> Transition | Rejected:
    """Return the state after logged and the effects its append must run, or why it is refused."""
    seq = logged.seq
    if seq != state.head + 1:
        return Rejected(reason=RejectReason.OUT_OF_ORDER)
    return _apply(state.model_copy(update={"head": seq}), seq, logged.entry)


def _apply(state: ConversationState, seq: int, entry: Entry) -> Transition | Rejected:
    result: Transition | Rejected
    match entry:
        case (
            TodoWoke()
            | Notice()
            | IntegrationNeeded()
            | UserMessage(first_contact=True)
            | UserMessage(imported=True)
            | Reply(imported=True)
        ):
            result = Transition(state=state, effects=())
        case UserMessage() | WorkflowFired() | IntegrationConnected():
            result = _wake_input(state, seq, entry)
        case BargeIn(reply_id=reply_id):
            result = Transition(state=state, effects=_barge_effects(state, reply_id))
        case StopRequested():
            result = _stop(state, seq, entry)
        case WorkStarted():
            result = _start_work(state, seq, entry)
        case ApprovalRequested():
            result = _request_approval(state, entry)
        case ApprovalDecided():
            result = _decide_approval(state, entry)
        case WorkFinished():
            result = _finish_work(state, seq, entry)
        case Reply():
            result = _open_reply(state, entry)
        case ReplySettled():
            result = _settle_reply(state, seq, entry)
    return result


def _wake_effects(entry: UserMessage | WorkflowFired | IntegrationConnected) -> tuple[Effect, ...]:
    match entry:
        case UserMessage(voice=False, id=message_id):
            return (KickStep(), StartAck(message_id=message_id))
        case _:
            return (KickStep(),)


def _barge_effects(state: ConversationState, reply_id: str) -> tuple[Effect, ...]:
    """Cut the open reply in its running attempt, or have a step cut the settled one; the user's words wake it."""
    if reply_id == state.open_reply:
        return (Preempt(barge_reply_id=reply_id), KickStep())
    return (KickStep(),)


def _wake_input(
    state: ConversationState, seq: int, entry: UserMessage | WorkflowFired | IntegrationConnected
) -> Transition | Rejected:
    """Wake for an input; a fire is refused while the previous fire is unanswered or work still runs here."""
    if not isinstance(entry, WorkflowFired):
        return Transition(state=_wake(state, seq), effects=_wake_effects(entry))
    if state.unsettled_fires or state.work:
        return Rejected(reason=RejectReason.FIRE_OVERLAPS)
    woken = _wake(state, seq).model_copy(update={"unsettled_fires": (*state.unsettled_fires, seq)})
    return Transition(state=woken, effects=_wake_effects(entry))


def _wake(state: ConversationState, seq: int) -> ConversationState:
    return state.model_copy(update={"unsettled_waking": (*state.unsettled_waking, seq)})


def _stop(state: ConversationState, seq: int, entry: StopRequested) -> Transition | Rejected:
    covers = seq - 1 if entry.covers_through is None else entry.covers_through
    if covers >= seq:
        return Rejected(reason=RejectReason.STOP_COVERS_FUTURE)
    covered = [item for item in state.work if item.cause_through <= covers]
    cancelled = tuple(task_id for item in covered for task_id in (item.task_id, *item.joined))
    approvals = tuple(sorted(approval for item in covered for approval in item.pending_approvals))
    stopped = _drop_waking_through(state, covers).model_copy(
        update={
            "stopped_through": max(state.stopped_through, covers),
            "work": tuple(item for item in state.work if item.cause_through > covers),
        }
    )
    cancel: tuple[Effect, ...] = (
        (CancelWork(task_ids=cancelled, approval_ids=approvals),) if cancelled else ()
    )
    return Transition(state=stopped, effects=(Preempt(stop_through=covers), *cancel))


def _start_work(state: ConversationState, seq: int, entry: WorkStarted) -> Transition | Rejected:
    if entry.cause_through >= seq:
        return Rejected(reason=RejectReason.CAUSE_NOT_BEFORE_WORK)
    if entry.cause_through <= state.stopped_through:
        return Rejected(reason=RejectReason.CAUSE_STOPPED)
    if _live(state, entry.task_id) is not None:
        return Rejected(reason=RejectReason.TASK_ALREADY_LIVE)
    if _overlaps_a_replay(state, entry):
        return Rejected(reason=RejectReason.FIRE_OVERLAPS)
    if entry.joins is not None:
        return _join_work(state, entry, entry.joins)
    work = LiveWork(
        task_id=entry.task_id,
        cause_through=entry.cause_through,
        answers=entry.answers,
        pending_approvals=frozenset(),
        detached=entry.detached,
        exclusive=entry.exclusive,
    )
    return Transition(state=state.model_copy(update={"work": (*state.work, work)}), effects=())


def _overlaps_a_replay(state: ConversationState, entry: WorkStarted) -> bool:
    """Return whether the work would run beside a replay, or the replay beside other work or an unanswered fire."""
    if entry.exclusive:
        return bool(state.work or state.unsettled_fires)
    return any(item.exclusive for item in state.work)


def _join_work(state: ConversationState, entry: WorkStarted, joins: str) -> Transition | Rejected:
    """Fold the handed-over task into the live work it joined: its answers, and its stop."""
    if _live(state, joins) is None:
        return Rejected(reason=RejectReason.TASK_NOT_LIVE)
    work = tuple(
        item.model_copy(
            update={
                "answers": tuple(dict.fromkeys((*item.answers, *entry.answers))),
                "joined": (*item.joined, entry.task_id),
            }
        )
        if item.task_id == joins
        else item
        for item in state.work
    )
    return Transition(state=state.model_copy(update={"work": work}), effects=())


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


def _decide_approval(state: ConversationState, entry: ApprovalDecided) -> Transition:
    """Release the approval; parked work the user decided ends, as the work the decision starts continues it."""
    released = (
        item.model_copy(update={"pending_approvals": item.pending_approvals - {entry.approval_id}})
        for item in state.work
    )
    continued = entry.outcome in USER_DECISIONS
    work = tuple(
        item for item in released if not (item.ended and continued and not item.pending_approvals)
    )
    return Transition(state=state.model_copy(update={"work": work}), effects=())


def _finish_work(state: ConversationState, seq: int, entry: WorkFinished) -> Transition:
    live = _live(state, entry.task_id)
    if live is None:
        return Transition(state=state, effects=())
    if entry.continued_by_decision and live.pending_approvals and entry.outcome is WorkOutcome.DONE:
        return Transition(state=_park(state, live), effects=())
    remaining = state.model_copy(
        update={"work": tuple(item for item in state.work if item.task_id != entry.task_id)}
    )
    if entry.outcome is WorkOutcome.CANCELLED or live.detached:
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
    if entry.imported:
        return _settle_imported(state, seq, entry)
    if entry.reply_id != state.open_reply:
        return Rejected(reason=RejectReason.REPLY_NOT_OPEN)
    if entry.through >= seq:
        return Rejected(reason=RejectReason.REPLY_ANSWERS_FUTURE)
    settled = max(state.settled_through, entry.through)
    finished = _drop_waking_through(state, settled).model_copy(
        update={"comms": CommsPhase.IDLE, "open_reply": None, "settled_through": settled}
    )
    return Transition(state=finished, effects=())


def _settle_imported(
    state: ConversationState, seq: int, entry: ReplySettled
) -> Transition | Rejected:
    """Settle imported history: its reply never opened, so only the settled watermark moves."""
    if entry.through >= seq:
        return Rejected(reason=RejectReason.REPLY_ANSWERS_FUTURE)
    settled = max(state.settled_through, entry.through)
    return Transition(
        state=_drop_waking_through(state, settled).model_copy(update={"settled_through": settled}),
        effects=(),
    )


def _drop_waking_through(state: ConversationState, seq: int) -> ConversationState:
    return state.model_copy(
        update={
            "unsettled_waking": tuple(waking for waking in state.unsettled_waking if waking > seq),
            "unsettled_fires": tuple(fire for fire in state.unsettled_fires if fire > seq),
            "finished_work": tuple(item for item in state.finished_work if item.seq > seq),
        }
    )


def _park(state: ConversationState, parked: LiveWork) -> ConversationState:
    """Keep work whose run ended while it waits on an approval live, so nothing narrates it as finished."""
    work = tuple(
        item.model_copy(update={"ended": True}) if item.task_id == parked.task_id else item
        for item in state.work
    )
    return state.model_copy(update={"work": work})


def _live(state: ConversationState, task_id: str) -> LiveWork | None:
    return next((item for item in state.work if item.task_id == task_id), None)
