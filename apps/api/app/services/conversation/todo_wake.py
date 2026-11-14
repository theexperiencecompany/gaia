"""The tracked todo run that finished work reports: the TodoWoke its WorkStarted answered."""

from app.models.conversation_log_models import (
    Batch,
    ConversationState,
    FinishedWork,
    TodoReportForm,
    TodoRun,
    TodoWoke,
    WorkFinished,
)
from app.services.conversation.ports import ConversationLog


async def reported_todo_run(
    log: ConversationLog, conversation_id: str, user_id: str, finished: FinishedWork
) -> TodoRun | None:
    """Return the todo run the finished work answers; None for work no todo woke."""
    entries = await log.read_after(conversation_id, user_id, finished.cause_through - 1)
    cause = entries[0].entry if entries else None
    return cause.run if isinstance(cause, TodoWoke) and cause.id in finished.answers else None


async def todo_runs_reported(
    log: ConversationLog, conversation_id: str, user_id: str, batch: Batch
) -> list[tuple[WorkFinished, TodoRun]]:
    """Return each finished work in batch that reports a todo run, with that run."""
    works = [logged for logged in batch.waking if isinstance(logged.entry, WorkFinished)]
    if not works:
        return []
    state = await log.state(conversation_id, user_id)
    reported: list[tuple[WorkFinished, TodoRun]] = []
    for logged in works:
        finished = _finished(state, logged.seq)
        if not isinstance(logged.entry, WorkFinished) or finished is None:
            continue
        run = await reported_todo_run(log, conversation_id, user_id, finished)
        if run is not None:
            reported.append((logged.entry, run))
    return reported


async def nothing_to_report(
    log: ConversationLog, conversation_id: str, user_id: str, batch: Batch
) -> bool:
    """Return whether batch is only todo runs that found nothing for the user, in a form that lets them say so.

    Only a report written as the todo's guidance forms it can declare that; any other input needs a reply.
    """
    reported = await todo_runs_reported(log, conversation_id, user_id, batch)
    return len(reported) == len(batch.waking) and all(
        work.nothing_for_user and run.report_form is TodoReportForm.AS_WRITTEN
        for work, run in reported
    )


def _finished(state: ConversationState, seq: int) -> FinishedWork | None:
    return next((item for item in state.finished_work if item.seq == seq), None)
