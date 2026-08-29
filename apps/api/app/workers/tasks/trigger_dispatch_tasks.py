"""ARQ task: fan a fired trigger out to the tracked todos subscribed to it.

The fan-out runs here rather than inline in ``TriggerHandler.process_event`` for a
dependency reason that is load-bearing, not cosmetic. Dispatch needs the todo
completion path for its ``complete`` action, and that lifecycle service imports
the trigger stack back (to tear subscriptions down) — so calling it from
``base.py`` closes a real import cycle, one mypy passes clean straight through.
Handing the work to a task cuts it: the handler only needs a task *name*.

It buys two things beyond that. The webhook path stays fast, so a Mongo scan
across every subscriber cannot delay the workflow queueing that follows it; and a
failure lands in its own wide-event boundary instead of a handler's.

This is not the endpoint-level second task the design rejected — it is enqueued
from inside ``process_event``, after handler normalization, with the trigger names
that handler owns.
"""

from typing import Any

from app.services.triggers.subscription_dispatch import dispatch_to_subscribed_todos
from shared.py.wide_events import log


async def dispatch_todo_subscriptions(
    _ctx: dict[str, Any],
    trigger_names: list[str],
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, Any],
) -> str:
    """Run every subscribed todo's action for one fired trigger.

    One handler can serve several GAIA trigger names (Gmail's account-level and
    poll variants share an event type), so each is resolved separately — a todo
    subscribed to one must not be woken by the other.
    """
    log.set(
        component="trigger_subscription",
        operation="dispatch",
        trigger_id=trigger_id,
        user_id=user_id,
        trigger_names=trigger_names,
    )

    fired = 0
    for trigger_name in trigger_names:
        try:
            fired += await dispatch_to_subscribed_todos(trigger_name, trigger_id, user_id, payload)
        except Exception as e:
            # One broken trigger name must not strand the others in this event.
            log.error(
                "todo_subscription.dispatch_failed",
                trigger_name=trigger_name,
                trigger_id=trigger_id,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

    log.info("todo_subscription.dispatch_complete", fired=fired)
    return f"fired:{fired}"
