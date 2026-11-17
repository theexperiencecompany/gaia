"""The work run lifecycle: running, awaiting approval or parked while live, then done, failed, stopped or lost."""

from app.models.conversation_lifecycle_models import (
    RunAwaitingApproval,
    RunDone,
    RunFailed,
    RunLost,
    RunMode,
    RunParked,
    RunRunning,
    RunStopped,
    WorkResult,
    WorkRun,
    WorkRunStatus,
)
from app.models.conversation_log_models import WorkFinished, WorkOutcome, WorkStarted

Runs = tuple[WorkRun, ...]

_ENDED: dict[WorkOutcome, WorkRunStatus] = {
    WorkOutcome.DONE: RunDone(),
    WorkOutcome.FAILED: RunFailed(),
    WorkOutcome.CANCELLED: RunStopped(),
    WorkOutcome.LOST: RunLost(),
}


def started(runs: Runs, entry: WorkStarted) -> Runs:
    """Start the run, or fold the handed-over task into the live run it joins."""
    if entry.joins is not None:
        return tuple(_joined(run, entry) if run.task_id == entry.joins else run for run in runs)
    run = WorkRun(
        task_id=entry.task_id,
        cause_from=entry.cause_from,
        cause_through=entry.cause_through,
        answers=entry.answers,
        mode=_mode(entry),
        status=RunRunning(),
    )
    return (*runs, run)


def asked(runs: Runs, task_id: str) -> Runs:
    """Have the running run wait on the approval it asked for."""
    return tuple(
        run.model_copy(update={"status": RunAwaitingApproval(carries=run.carries)})
        if run.task_id == task_id and isinstance(run.status, RunRunning)
        else run
        for run in runs
    )


def decided(
    runs: Runs, owner: str, approval_id: str, *, continued: bool, still_pending: bool
) -> Runs:
    """Release the owner of a decided approval; a decision handed on is carried by the runs executing it."""
    return tuple(
        _released(run, approval_id, continued=continued, still_pending=still_pending)
        if run.task_id == owner
        else _carrying(run, approval_id)
        if continued
        else run
        for run in runs
    )


def finished(
    runs: Runs, entry: WorkFinished, *, owns_pending: bool
) -> tuple[Runs, WorkResult | None]:
    """End the run, or park it while its approvals wait; return the result it wakes, if any."""
    run = next((run for run in runs if run.task_id == entry.task_id and run.live), None)
    if run is None:
        return runs, None
    left_to_the_user = entry.continued_by_decision and entry.outcome is WorkOutcome.DONE
    if left_to_the_user and owns_pending:
        return _replaced(runs, run, RunParked()), None
    ended = _replaced(runs, run, _ENDED[entry.outcome])
    carried = left_to_the_user and entry.awaits_decision and bool(run.carries)
    if carried or entry.outcome is WorkOutcome.CANCELLED or run.mode is RunMode.DETACHED:
        return ended, None
    result = WorkResult(
        task_id=run.task_id,
        cause_from=run.cause_from,
        cause_through=run.cause_through,
        answers=run.answers,
    )
    return ended, result


def stopped(runs: Runs, covers: int) -> Runs:
    """Stop every live run caused at or before covers."""
    return tuple(
        run.model_copy(update={"status": RunStopped()})
        if run.live and run.cause_through <= covers
        else run
        for run in runs
    )


def _mode(entry: WorkStarted) -> RunMode:
    if entry.detached:
        return RunMode.DETACHED
    return RunMode.EXCLUSIVE if entry.exclusive else RunMode.ATTACHED


def _joined(run: WorkRun, entry: WorkStarted) -> WorkRun:
    return run.model_copy(
        update={
            "answers": tuple(dict.fromkeys((*run.answers, *entry.answers))),
            "joined": (*run.joined, entry.task_id),
        }
    )


def _released(run: WorkRun, approval_id: str, *, continued: bool, still_pending: bool) -> WorkRun:
    """Release the owner: it waits on while others are pending; a parked run ends with its last decision."""
    match run.status:
        case RunParked() if not still_pending:
            return run.model_copy(update={"status": RunDone() if continued else RunStopped()})
        case RunAwaitingApproval(carries=carries):
            carried = (*carries, approval_id) if continued else carries
            status = (
                RunAwaitingApproval(carries=carried)
                if still_pending
                else RunRunning(carries=carried)
            )
            return run.model_copy(update={"status": status})
    return run


def _carrying(run: WorkRun, approval_id: str) -> WorkRun:
    """Have an attached run under way with nothing of its own to ask carry the decision it may resume."""
    if run.mode is RunMode.DETACHED or not isinstance(run.status, RunRunning):
        return run
    status = RunRunning(carries=(*run.status.carries, approval_id))
    return run.model_copy(update={"status": status})


def _replaced(runs: Runs, run: WorkRun, status: WorkRunStatus) -> Runs:
    return tuple(
        item.model_copy(update={"status": status}) if item.task_id == run.task_id else item
        for item in runs
    )
