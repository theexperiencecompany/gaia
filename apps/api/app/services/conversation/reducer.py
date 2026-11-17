"""The pure fold of a conversation's log into its state: state_n = reduce(state_{n-1}, entry_n)."""

from app.constants.chat import ConversationSource
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
    WithdrawApprovals,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
    WorkStarted,
)
from shared.py.approvals import ApprovalOutcome

#: Decisions the decision path hands on: it starts the work that carries them out or reports the skip.
#: A withdrawal is made by a live run (a revoke) or delivered to one (the sweep's, for a lost request).
CONTINUED_DECISIONS = frozenset(
    {
        ApprovalOutcome.APPROVED,
        ApprovalOutcome.DENIED,
        ApprovalOutcome.EXPIRED,
        ApprovalOutcome.WITHDRAWN,
    }
)


def reduce(state: ConversationState, logged: LoggedEntry) -> Transition | Rejected:
    """Return the state after logged and the effects its append must run, or why it is refused."""
    seq = logged.seq
    if seq != state.head + 1:
        return Rejected(reason=RejectReason.OUT_OF_ORDER)
    result = _apply(state.model_copy(update={"head": seq}), seq, logged.entry)
    if isinstance(result, Transition) and result.state.approvals_asked and not result.state.asking:
        # None open: the next approval asked is number 1 again.
        return result.model_copy(
            update={"state": result.state.model_copy(update={"approvals_asked": 0})}
        )
    return result


def stamped(state: ConversationState, entry: Entry) -> Entry:
    """Return entry as the log stores it after state: an approval request takes the next free number."""
    if isinstance(entry, ApprovalRequested):
        return entry.model_copy(update={"number": state.approvals_asked + 1})
    return entry


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
            result = _open_reply(state, seq, entry)
        case ReplySettled():
            result = _settle_reply(state, seq, entry)
    return result


def amend_refusal(stored: Reply | UserMessage, revised: Reply | UserMessage) -> RejectReason | None:
    """Return why an amend is refused: a reply's stored text is what clients showed, so it only grows."""
    if isinstance(stored, Reply) and not revised.text.startswith(stored.text):
        return RejectReason.SHOWN_TEXT_TAKEN_BACK
    return None


def _wake_effects(entry: UserMessage | WorkflowFired | IntegrationConnected) -> tuple[Effect, ...]:
    match entry:
        case UserMessage(id=message_id, surface=surface) if surface is not ConversationSource.VOICE:
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
    effects = _wake_effects(entry)
    if not isinstance(entry, WorkflowFired):
        return Transition(state=_wake(state, seq), effects=effects)
    if state.unsettled_fires or state.work:
        return Rejected(reason=RejectReason.FIRE_OVERLAPS)
    woken = _wake(state, seq).model_copy(update={"unsettled_fires": (*state.unsettled_fires, seq)})
    return Transition(state=woken, effects=effects)


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
        cause_from=entry.cause_from,
        answers=entry.answers,
        pending_approvals=(),
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
        item.model_copy(update={"pending_approvals": (*item.pending_approvals, entry.approval_id)})
        if item.task_id == entry.task_id
        else item
        for item in state.work
    )
    asked = state.model_copy(update={"work": work, "approvals_asked": state.approvals_asked + 1})
    return Transition(state=asked, effects=())


def _decide_approval(state: ConversationState, entry: ApprovalDecided) -> Transition:
    """Release the approval; parked work the user decided ends, as the work the decision starts continues it.

    The executor run under way when it is decided may still ask it (it resumed an earlier
    decision of the same work), so the approval counts as decided for that run too.
    """
    continued = entry.outcome in CONTINUED_DECISIONS
    answers_an_ask = continued and entry.approval_id in state.asking
    released = (
        item.model_copy(
            update={
                "pending_approvals": tuple(
                    approval for approval in item.pending_approvals if approval != entry.approval_id
                ),
                "decided_approvals": (
                    (*item.decided_approvals, entry.approval_id)
                    if answers_an_ask
                    and (entry.approval_id in item.pending_approvals or _carries_decisions(item))
                    else item.decided_approvals
                ),
            }
        )
        for item in state.work
    )
    work = tuple(
        item for item in released if not (item.ended and continued and not item.pending_approvals)
    )
    return Transition(state=state.model_copy(update={"work": work}), effects=())


def _carries_decisions(item: LiveWork) -> bool:
    """Return whether item is the executor run under way with nothing of its own to ask."""
    return not (item.ended or item.detached or item.pending_approvals)


def _finish_work(state: ConversationState, seq: int, entry: WorkFinished) -> Transition:
    live = _live(state, entry.task_id)
    if live is None:
        return Transition(state=state, effects=())
    if entry.left_to_decision and live.pending_approvals:
        return Transition(state=_park(state, live), effects=())
    remaining = state.model_copy(
        update={"work": tuple(item for item in state.work if item.task_id != entry.task_id)}
    )
    # Nothing carries out a decision on what the ended run still asked: it is withdrawn, unanswerable.
    withdraw: tuple[Effect, ...] = (
        (WithdrawApprovals(approval_ids=live.pending_approvals),) if live.pending_approvals else ()
    )
    if entry.left_to_decision and entry.awaits_decision and live.decided_approvals:
        # Decided before its run ended: the work that decision started reports, not this ask.
        return Transition(state=remaining, effects=withdraw)
    if entry.outcome is WorkOutcome.CANCELLED or live.detached:
        return Transition(state=remaining, effects=withdraw)
    result = FinishedWork(
        seq=seq,
        task_id=entry.task_id,
        cause_through=live.cause_through,
        cause_from=live.cause_from,
        answers=live.answers,
    )
    awaiting = remaining.model_copy(update={"finished_work": (*state.finished_work, result)})
    return Transition(state=_wake(awaiting, seq), effects=(*withdraw, KickStep()))


def _open_reply(state: ConversationState, seq: int, entry: Reply) -> Transition | Rejected:
    if state.open_reply is not None:
        return Rejected(reason=RejectReason.REPLY_ALREADY_OPEN)
    opened = state.model_copy(
        update={"comms": CommsPhase.ANSWERING, "open_reply": entry.reply_id, "open_reply_seq": seq}
    )
    return Transition(state=opened, effects=())


def _settle_reply(state: ConversationState, seq: int, entry: ReplySettled) -> Transition | Rejected:
    if entry.imported:
        return _settle_imported(state, seq, entry)
    if entry.reply_id != state.open_reply:
        return Rejected(reason=RejectReason.REPLY_NOT_OPEN)
    if entry.through >= seq:
        return Rejected(reason=RejectReason.REPLY_ANSWERS_FUTURE)
    if entry.answers and state.open_reply_seq is not None and entry.through > state.open_reply_seq:
        # through is the newest input it answers: a reply never sits above what it answers.
        return Rejected(reason=RejectReason.REPLY_ABOVE_ITS_INPUT)
    answered = _answered(state, entry)
    finished = answered.model_copy(
        update={"comms": CommsPhase.IDLE, "open_reply": None, "open_reply_seq": None}
    )
    return Transition(state=finished, effects=())


def _answered(state: ConversationState, entry: ReplySettled) -> ConversationState:
    """Settle the inputs the reply answered; the settled mark stops below the oldest one still open.

    A settle that names no seqs was written before they were recorded: it settles every input through.
    """
    if entry.answered_seqs is None:
        settled = max(state.settled_through, entry.through)
        return _drop_waking_through(state, settled).model_copy(update={"settled_through": settled})
    answered = frozenset(entry.answered_seqs)
    left = state.model_copy(
        update={
            "unsettled_waking": tuple(w for w in state.unsettled_waking if w not in answered),
            "unsettled_fires": tuple(f for f in state.unsettled_fires if f not in answered),
            "finished_work": tuple(w for w in state.finished_work if w.seq not in answered),
        }
    )
    open_below = min(left.unsettled_waking, default=entry.through + 1) - 1
    settled = max(state.settled_through, min(entry.through, open_below))
    return left.model_copy(update={"settled_through": settled})


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
