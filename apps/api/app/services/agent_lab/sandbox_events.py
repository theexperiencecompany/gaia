"""Tell the todos watching a user's sandbox runs what happened to the sandbox itself.

Every event lands in each watching todo's activity log, so the run's history
shows it. The ones that need action, because the agent's process is gone or its
work may not be saved, also run the todo with the event.
"""

from enum import StrEnum
from typing import Final

from app.constants.todos import TodoActivityEvent
from app.db.repositories.todos import todo_repository
from app.services.agent_lab.lab_runs import SANDBOX_RUN_TRIGGER, run_subscriptions
from app.services.todo_activity import record_activity
from app.services.triggers.subscription_dispatch import fire_subscription


class SandboxEventKind(StrEnum):
    """What happened to the sandbox; the value is the event kind the woken todo sees."""

    RENEWED = "sandbox_renewed"
    REPLACED = "sandbox_replaced"
    SAVE_FAILED = "save_failed"


_WAKES: Final[frozenset[SandboxEventKind]] = frozenset(
    {SandboxEventKind.REPLACED, SandboxEventKind.SAVE_FAILED}
)


async def report_sandbox_event(user_id: str, kind: SandboxEventKind, detail: str) -> int:
    """Log the event on every todo watching a run and wake those it needs; returns how many todos saw it."""
    todos = await todo_repository.find_active_by_user_and_trigger(user_id, SANDBOX_RUN_TRIGGER)
    seen = 0
    for todo in todos:
        subscriptions = run_subscriptions(todo)
        if not subscriptions:
            continue
        seen += 1
        await record_activity(
            todo.id, todo.user_id, TodoActivityEvent.SANDBOX_EVENT, f"{kind.value}: {detail}"
        )
        if kind in _WAKES:
            # One wake per todo, on its newest run: the todo reads every run's state itself.
            await fire_subscription(
                todo, subscriptions[-1], {"kind": kind.value, "event": {"detail": detail}}
            )
    return seen
