"""Background work as conversation log entries: started (fenced on the step's claim), approvals, finished."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.agents.core.background.executor_queue import get_lock_holder, parse_lock_value
from app.constants.hil import ApprovalResolution
from app.models.agent_config import StepTurnRef
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    CancelWork,
    LoggedEntry,
    RejectReason,
    StepClaim,
    StopBy,
    StopRequested,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.tool_data_models import ToolDataEntry
from app.models.work_cancel_models import WorkCancelled
from app.services.conversation.log import accept, publish_appended
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.services.conversation.reply_analytics import capture_unanswered_stop, stopped_waking
from app.services.conversation.runtime import runtime_ports
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
) -> bool:
    """Append WorkStarted under the step's claim; False when a Stop or a lost claim refuses it, so nothing dispatches.

    joins names the running task the work is handed to; when that run is not on the log (one
    the step did not start), the hand-over goes ahead unlogged and that run delivers it.
    """
    ports = runtime_ports()
    claim = StepClaim(conversation_id=conversation_id, user_id=user_id, epoch=step["epoch"])
    entry = WorkStarted(
        id=f"work:{task_id}",
        task_id=task_id,
        cause_through=step["cause_through"],
        answers=tuple(step["answers"]),
        joins=joins,
    )
    try:
        appended = await ports.log.append_fenced(claim, entry)
    except (ClaimLost, EntryRejected) as refused:
        unlogged_run = (
            joins is not None
            and isinstance(refused, EntryRejected)
            and refused.reason is RejectReason.TASK_NOT_LIVE
        )
        log.warning(
            "work not started: the conversation log refused its WorkStarted",
            conversation_id=conversation_id,
            task_id=task_id,
            joins=joins,
            reason=type(refused).__name__,
            handed_over_unlogged=unlogged_run,
        )
        return unlogged_run
    await publish_appended(ports.frames, conversation_id, appended)
    return True


@dataclass(frozen=True)
class WorkReport:
    """What finished work hands its reply: the report, the cards it showed, the review's note and its own declaration."""

    text: str
    tool_data: Sequence[ToolDataEntry] = ()
    note: str = ""
    nothing_for_user: bool = False


async def record_work_finished(
    conversation_id: str, user_id: str, task_id: str, outcome: WorkOutcome, report: WorkReport
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
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def running_step_task(conversation_id: str, user_id: str) -> str | None:
    """Return the task id of the executor running in the conversation when the step started it; else None."""
    holder = await get_lock_holder(conversation_id)
    if holder is None:
        return None
    task_id = parse_lock_value(holder)[1]
    state = await runtime_ports().log.state(conversation_id, user_id)
    return task_id if any(work.task_id == task_id for work in state.work) else None


async def record_approval_requested(
    conversation_id: str,
    user_id: str,
    task_id: str,
    approval_id: str,
    *,
    summary: str,
    expires_at: datetime | None,
) -> None:
    """Append ApprovalRequested for live work waiting on the user's decision, as its card reads."""
    entry = ApprovalRequested(
        id=f"approval:{approval_id}",
        task_id=task_id,
        approval_id=approval_id,
        summary=summary,
        expires_at=expires_at,
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def approval_is_logged(conversation_id: str, user_id: str, approval_id: str) -> bool:
    """Return whether the conversation's live work is waiting on approval_id in the log."""
    state = await runtime_ports().log.state(conversation_id, user_id)
    return any(approval_id in work.pending_approvals for work in state.work)


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
    conversation_id: str, user_id: str, approval_id: str, decision: ApprovalResolution
) -> None:
    """Append ApprovalDecided: it releases live work waiting on it, and causes the work a decision starts later."""
    entry = ApprovalDecided(
        id=f"approval:{approval_id}:decided", approval_id=approval_id, decision=decision
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def record_work_carried(
    conversation_id: str,
    user_id: str,
    task_id: str,
    cause: LoggedEntry | None = None,
    *,
    detached: bool = False,
) -> bool:
    """Append WorkStarted for work started outside a step, answering cause, else caused by everything logged so far.

    False when a Stop since refuses it, so nothing dispatches; the step narrates its WorkFinished
    unless the work is detached (a background subagent, a browser job), whose result lands elsewhere.
    """
    ports = runtime_ports()
    if cause is None:
        state = await ports.log.state(conversation_id, user_id)
        entry = WorkStarted(
            id=f"work:{task_id}", task_id=task_id, cause_through=state.head, detached=detached
        )
    else:
        entry = WorkStarted(
            id=f"work:{task_id}",
            task_id=task_id,
            cause_through=cause.seq,
            answers=(cause.entry.id,),
            detached=detached,
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
        capture_unanswered_stop(user_id, conversation_id, accepted.appended, logged)
    if any(isinstance(effect, CancelWork) for effect in accepted.failed_effects):
        raise WorkNotCancelled(conversation_id)
    return accepted.cancelled
