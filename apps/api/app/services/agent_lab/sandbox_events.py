"""Tell the tasks watching a user's sandbox runs what happened to the sandbox itself.

Every event lands in each watching task's log, so the run's history shows it. The ones
that need action, because the agent's process is gone or its work may not be saved, also
run the task with the event.
"""

from enum import StrEnum
from typing import Final

from app.constants.tasks import TaskLogEvent
from app.services.agent_lab.lab_runs import run_subscriptions, watching_tasks
from app.services.tasks.event_dispatch import take_event
from app.services.tasks.run_records import record_event


class SandboxEventKind(StrEnum):
    """What happened to the sandbox; the value is the event kind the woken task sees."""

    RENEWED = "sandbox_renewed"
    REPLACED = "sandbox_replaced"
    SAVE_FAILED = "save_failed"


_WAKES: Final[frozenset[SandboxEventKind]] = frozenset(
    {SandboxEventKind.REPLACED, SandboxEventKind.SAVE_FAILED}
)


async def report_sandbox_event(user_id: str, kind: SandboxEventKind, detail: str) -> int:
    """Log the event on every task watching a run and wake those it needs; returns how many tasks saw it."""
    tasks = await watching_tasks(user_id)
    for task in tasks:
        await record_event(task, TaskLogEvent.SANDBOX_EVENT, f"{kind.value}: {detail}")
        if kind in _WAKES:
            # One wake per task, on its newest run: the task reads every run's state itself.
            await take_event(
                task,
                run_subscriptions(task)[-1],
                {"kind": kind.value, "event": {"detail": detail}},
                None,
            )
    return len(tasks)
