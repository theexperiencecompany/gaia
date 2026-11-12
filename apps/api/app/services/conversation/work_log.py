"""Background work as conversation log entries: started (fenced on the step's claim), approvals, finished.

Callers write these only for runs the conversation step started (conversation_step on their
configurable), so the legacy stream path keeps its own side channels unchanged.
"""

from app.constants.hil import ApprovalResolution
from app.models.agent_config import StepTurnRef
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    CancelWork,
    StepClaim,
    StopBy,
    StopRequested,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.log import accept, publish_appended
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.services.conversation.runtime import runs_on_step, runtime_ports
from shared.py.wide_events import log


async def record_work_started(
    step: StepTurnRef, conversation_id: str, user_id: str, task_id: str
) -> bool:
    """Append WorkStarted under the step's claim; False when a Stop or a lost claim refuses it, so nothing dispatches."""
    ports = runtime_ports()
    claim = StepClaim(conversation_id=conversation_id, user_id=user_id, epoch=step["epoch"])
    entry = WorkStarted(
        id=f"work:{task_id}",
        task_id=task_id,
        cause_through=step["cause_through"],
        answers=tuple(step["answers"]),
    )
    try:
        appended = await ports.log.append_fenced(claim, entry)
    except (ClaimLost, EntryRejected) as refused:
        log.warning(
            "work not started: the conversation log refused its WorkStarted",
            conversation_id=conversation_id,
            task_id=task_id,
            reason=type(refused).__name__,
        )
        return False
    await publish_appended(ports.frames, conversation_id, appended)
    return True


async def record_work_finished(
    conversation_id: str, user_id: str, task_id: str, outcome: WorkOutcome, report: str
) -> None:
    """Append WorkFinished; its kick wakes the step, which narrates the result in the task's own reply."""
    entry = WorkFinished(
        id=f"work:{task_id}:finished", task_id=task_id, outcome=outcome, report=report
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def record_approval_requested(
    conversation_id: str, user_id: str, task_id: str, approval_id: str
) -> None:
    """Append ApprovalRequested for live work paused on the user's decision."""
    entry = ApprovalRequested(
        id=f"approval:{approval_id}", task_id=task_id, approval_id=approval_id
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def record_approval_decided(
    conversation_id: str, user_id: str, approval_id: str, decision: ApprovalResolution
) -> None:
    """Append ApprovalDecided when the conversation's live work is waiting on approval_id; else nothing."""
    ports = runtime_ports()
    state = await ports.log.state(conversation_id, user_id)
    if not any(approval_id in work.pending_approvals for work in state.work):
        return
    entry = ApprovalDecided(
        id=f"approval:{approval_id}:decided", approval_id=approval_id, decision=decision
    )
    await accept(ports, conversation_id, user_id, entry)


async def record_gaia_stop(
    step: StepTurnRef, conversation_id: str, user_id: str, stop_id: str
) -> None:
    """Log the comms model's own stop: it covers everything before the inputs it is answering."""
    ports = runtime_ports()
    claim = StepClaim(conversation_id=conversation_id, user_id=user_id, epoch=step["epoch"])
    entry = StopRequested(
        id=f"stop:{stop_id}", by=StopBy.GAIA, covers_through=step["batch_start"] - 1
    )
    appended = await ports.log.append_fenced(claim, entry)
    await publish_appended(ports.frames, conversation_id, appended)
    for task_ids in (e.task_ids for e in appended.effects if isinstance(e, CancelWork)):
        await ports.effects.cancel_work(conversation_id, user_id, task_ids)


async def record_user_stop(conversation_id: str, user_id: str, stop_id: str) -> None:
    """Log the user's Stop on a step-run conversation; its effects preempt the step and cancel the work it covers."""
    if not await runs_on_step(conversation_id, user_id):
        return
    await accept(
        runtime_ports(),
        conversation_id,
        user_id,
        StopRequested(id=f"stop:{stop_id}", by=StopBy.USER),
    )
