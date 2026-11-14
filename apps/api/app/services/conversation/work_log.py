"""Background work as conversation log entries: started (fenced on the step's claim), approvals, finished."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from app.agents.core.background.executor_queue import get_lock_holder, parse_lock_value
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.agent_config import StepTurnRef
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    CancelWork,
    LoggedEntry,
    StepClaim,
    StopBy,
    StopRequested,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.work_cancel_models import WorkCancelled
from app.services.conversation.log import accept, publish_appended
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.services.conversation.reply_analytics import capture_unanswered_stop, stopped_waking
from app.services.conversation.runtime import runtime_ports
from shared.py.approvals import ActionResult, ApprovalDecider, ApprovalOutcome
from shared.py.conversation_wire import ImageData, ToolDataEntry
from shared.py.wide_events import log


class WorkNotCancelled(Exception):
    """A Stop was logged but the work it covers could not be cancelled."""


async def record_work_started(
    step: StepTurnRef,
    conversation_id: str,
    user_id: str,
    task_id: str,
    *,
    joins: str | None = None,
    handoff: str | None = None,
) -> bool:
    """Append WorkStarted under the step's claim; False when the log refuses it, so nothing dispatches.

    joins names the live task the work is handed to.
    """
    ports = runtime_ports()
    claim = StepClaim(conversation_id=conversation_id, user_id=user_id, epoch=step["epoch"])
    entry = WorkStarted(
        id=f"work:{task_id}",
        task_id=task_id,
        cause_through=step["cause_through"],
        answers=tuple(step["answers"]),
        joins=joins,
        handoff=handoff,
    )
    try:
        appended = await ports.log.append_fenced(claim, entry)
    except (ClaimLost, EntryRejected) as refused:
        log.warning(
            "work not started: the conversation log refused its WorkStarted",
            conversation_id=conversation_id,
            task_id=task_id,
            joins=joins,
            reason=type(refused).__name__,
        )
        return False
    await publish_appended(ports.frames, conversation_id, appended)
    return True


@dataclass(frozen=True)
class WorkReport:
    """What finished work hands its reply: the report, the cards and image it showed, the review's note, its own word."""

    text: str
    tool_data: Sequence[ToolDataEntry] = ()
    note: str = ""
    nothing_for_user: bool = False
    image: ImageData | None = None


async def record_work_finished(
    conversation_id: str,
    user_id: str,
    task_id: str,
    outcome: WorkOutcome,
    report: WorkReport,
    *,
    continued_by_decision: bool = False,
) -> None:
    """Append WorkFinished; its kick wakes the step, which narrates the result and its cards in the task's own reply."""
    # A lost marker never shares the real result's id, so that result can never be dropped as its duplicate.
    ending = "lost" if outcome is WorkOutcome.LOST else "finished"
    entry = WorkFinished(
        id=f"work:{task_id}:{ending}",
        task_id=task_id,
        outcome=outcome,
        report=report.text,
        tool_data=tuple(report.tool_data),
        note=report.note,
        nothing_for_user=report.nothing_for_user,
        image=report.image,
        continued_by_decision=continued_by_decision,
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def work_of_run(conversation_id: str, user_id: str, stream_id: str) -> str:
    """Return the task id of the logged live work a run belongs to: its own detached stream, else the executor holding the conversation."""
    state = await runtime_ports().log.state(conversation_id, user_id)
    live = {work.task_id for work in state.work}
    if stream_id in live:
        return stream_id
    holder = await get_lock_holder(conversation_id)
    task_id = parse_lock_value(holder)[1] if holder is not None else None
    if task_id is None or task_id not in live:
        raise LookupError(f"run {stream_id} is no logged work in conversation {conversation_id}")
    return task_id


@dataclass(frozen=True)
class DecisionTaken:
    """The decision that stands for an approval, and whether it is the one just appended."""

    stands: ApprovalDecided
    taken: bool


async def record_approval_requested(
    conversation_id: str, user_id: str, request: ApprovalRequested
) -> None:
    """Append ApprovalRequested for live work waiting on the user's decision; it is the card."""
    await accept(runtime_ports(), conversation_id, user_id, request)


async def approvals_awaited_by(
    conversation_id: str, user_id: str, task_ids: Collection[str]
) -> list[str]:
    """Return the approvals the conversation's live work with these task ids waits on."""
    state = await runtime_ports().log.state(conversation_id, user_id)
    return sorted(
        approval
        for work in state.work
        if work.task_id in task_ids
        for approval in work.pending_approvals
    )


async def record_approval_decided(
    conversation_id: str,
    user_id: str,
    approval_id: str,
    outcome: ApprovalOutcome,
    decider: ApprovalDecider | None,
    *,
    feedback: str | None = None,
) -> DecisionTaken:
    """Decide the approval in the log, once: the first decision appended stands, every later one reads it back.

    The log is the approval's only truth. Appending releases live work waiting on it.
    """
    entry = ApprovalDecided(
        id=decision_entry_id(approval_id),
        approval_id=approval_id,
        outcome=outcome,
        decider=decider,
        feedback=feedback,
    )
    appended = (await accept(runtime_ports(), conversation_id, user_id, entry)).appended
    stored = appended.logged.entry
    if not isinstance(stored, ApprovalDecided):
        raise TypeError(f"entry {entry.id} holds a {stored.kind}, not a decision")
    return DecisionTaken(stands=stored, taken=not appended.duplicate)


def decision_entry_id(approval_id: str) -> str:
    """Return the id of the entry that decides approval_id; one id, so the log takes one decision."""
    return f"approval:{approval_id}:decided"


async def logged_decision(
    conversation_id: str, user_id: str, approval_id: str
) -> ApprovalDecided | None:
    """Return how the log has the approval ended, with its action's end once logged; None while it is pending."""
    logged = await conversation_log_repository.read_log(
        conversation_id,
        user_id=user_id,
        ids=[decision_entry_id(approval_id), _acted_id(approval_id)],
    )
    decisions = [item.entry for item in logged or () if isinstance(item.entry, ApprovalDecided)]
    acted = [decision for decision in decisions if decision.action is not None]
    return (acted or decisions or [None])[0]


def _acted_id(approval_id: str) -> str:
    return f"approval:{approval_id}:acted"


async def record_approved_action_ended(
    conversation_id: str, user_id: str, approval_id: str, action: ActionResult
) -> None:
    """Restate the user's approval with what its action came to, so the card keeps it after a reload."""
    entry = ApprovalDecided(
        id=_acted_id(approval_id),
        approval_id=approval_id,
        outcome=ApprovalOutcome.APPROVED,
        decider=ApprovalDecider.USER,
        action=action,
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def record_work_carried(
    conversation_id: str,
    user_id: str,
    task_id: str,
    cause: LoggedEntry | None = None,
    *,
    detached: bool = False,
    exclusive: bool = False,
) -> bool:
    """Append WorkStarted for work started outside a step, answering cause, else caused by everything logged so far.

    False when a Stop since refuses it, or other work refuses exclusive work, so nothing dispatches; the
    step narrates its WorkFinished unless the work is detached (a subagent, a browser job, a replay).
    """
    ports = runtime_ports()
    if cause is None:
        state = await ports.log.state(conversation_id, user_id)
        entry = WorkStarted(
            id=f"work:{task_id}",
            task_id=task_id,
            cause_through=state.head,
            detached=detached,
            exclusive=exclusive,
        )
    else:
        entry = WorkStarted(
            id=f"work:{task_id}",
            task_id=task_id,
            cause_through=cause.seq,
            answers=(cause.entry.id,),
            detached=detached,
            exclusive=exclusive,
        )
    try:
        await accept(ports, conversation_id, user_id, entry)
    except EntryRejected as refused:
        log.warning(
            "carried work not started: the conversation log refused its WorkStarted",
            conversation_id=conversation_id,
            task_id=task_id,
            reason=refused.reason.value,
        )
        return False
    return True


async def record_gaia_stop(
    step: StepTurnRef, conversation_id: str, user_id: str, stop_id: str
) -> WorkCancelled:
    """Log the comms model's own stop: it covers everything before the inputs it is answering; return what it cancelled."""
    ports = runtime_ports()
    claim = StepClaim(conversation_id=conversation_id, user_id=user_id, epoch=step["epoch"])
    entry = StopRequested(
        id=f"stop:{stop_id}", by=StopBy.GAIA, covers_through=step["batch_start"] - 1
    )
    appended = await ports.log.append_fenced(claim, entry)
    await publish_appended(ports.frames, conversation_id, appended)
    cancelled = WorkCancelled()
    for cancel in (e for e in appended.effects if isinstance(e, CancelWork)):
        cancelled = await ports.effects.cancel_work(conversation_id, user_id, cancel)
    return cancelled


async def record_user_stop(conversation_id: str, user_id: str, stop_id: str) -> WorkCancelled:
    """Log the user's Stop; its effects preempt the step and cancel the work it covers, which this returns.

    Raises WorkNotCancelled when the cancel failed: once logged, nothing else stops that work.
    """
    ports = runtime_ports()
    accepted = await accept(
        ports, conversation_id, user_id, StopRequested(id=f"stop:{stop_id}", by=StopBy.USER)
    )
    if stopped := stopped_waking(accepted.appended):
        logged = await ports.log.read_after(conversation_id, user_id, min(stopped) - 1)
        capture_unanswered_stop(
            ports.analytics, user_id, conversation_id, accepted.appended, logged
        )
    if any(isinstance(effect, CancelWork) for effect in accepted.failed_effects):
        raise WorkNotCancelled(conversation_id)
    return accepted.cancelled
