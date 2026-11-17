"""What every reader derives from the lifecycles: the one place each view is computed."""

from app.models.conversation_lifecycle_models import (
    InputOrigin,
    Lifecycles,
    MessageOpen,
    WorkResult,
)
from app.models.conversation_log_models import DisplayState


def display(lifecycles: Lifecycles) -> DisplayState:
    """Return the status to show: an open reply or input first, then approvals, then work."""
    if lifecycles.attempt is not None or unsettled_waking(lifecycles):
        return DisplayState.THINKING
    if asking(lifecycles):
        return DisplayState.AWAITING_APPROVAL
    return DisplayState.WORKING if lifecycles.runs else DisplayState.IDLE


def asking(lifecycles: Lifecycles) -> tuple[str, ...]:
    """Return the pending approvals in the one order every surface numbers them: by run, then as asked."""
    return tuple(
        approval.approval_id
        for run in lifecycles.runs
        for approval in lifecycles.approvals
        if approval.owner == run.task_id and approval.pending
    )


def unsettled_waking(lifecycles: Lifecycles) -> tuple[int, ...]:
    """Return the seqs of the open inputs a step still has to answer, ascending."""
    return tuple(
        message.seq for message in lifecycles.messages if isinstance(message.status, MessageOpen)
    )


def finished_work(lifecycles: Lifecycles) -> tuple[WorkResult, ...]:
    """Return the results of finished work no reply has reported yet."""
    return tuple(
        message.result
        for message in lifecycles.messages
        if message.origin is InputOrigin.WORK_RESULT and message.result is not None
    )


def owed_answers(lifecycles: Lifecycles) -> frozenset[str]:
    """Return the ids of the inputs whose work, running or finished, no reply has answered yet."""
    running = (entry_id for run in lifecycles.runs for entry_id in run.answers)
    finished = (entry_id for result in finished_work(lifecycles) for entry_id in result.answers)
    return frozenset((*running, *finished))
