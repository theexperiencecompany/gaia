"""ARQ task: fan a fired trigger out to the tracked todos subscribed to it.

The fan-out runs here, not inline in TriggerHandler.process_event, for a load-bearing
dependency reason: dispatch needs the todo completion path, whose lifecycle service
imports the trigger stack back (to tear subscriptions down) — calling it from base.py
would close a real import cycle. Handing the work to a task cuts it, since the handler
only needs a task name.

It also keeps the webhook path fast (a Mongo scan across every subscriber can't delay
the workflow queueing that follows) and lands failures in their own wide-event boundary
instead of a handler's.

This is not the endpoint-level second task the design rejected — it is enqueued from
inside process_event, after handler normalization, with the trigger names handler owns.
"""

import asyncio
from typing import Any

from app.services.triggers.subscription_dispatch import dispatch_to_subscribed_todos
from shared.py.wide_events import log


async def dispatch_todo_subscriptions(
    ctx: dict[str, Any],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    trigger_names: list[str],
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, Any],
) -> str:
    """Run every subscribed todo's action for one fired trigger.

    One handler can serve several GAIA trigger names (Gmail's account-level and
    poll variants share an event type); each is resolved and dispatched
    concurrently, and one name failing must not cancel or strand the others.
    """
    log.set(
        component="trigger_subscription",
        operation="dispatch",
        trigger_id=trigger_id,
        user_id=user_id,
        trigger_names=trigger_names,
    )

    results = await asyncio.gather(
        *(
            dispatch_to_subscribed_todos(trigger_name, trigger_id, user_id, payload)
            for trigger_name in trigger_names
        ),
        return_exceptions=True,
    )

    fired = 0
    # strict= is a documented invariant, not observable behaviour: gather over N
    # coroutines always returns N results, so it can never trip — mutating it is a
    # provably-equivalent mutation with no possible killing test.
    for trigger_name, result in zip(trigger_names, results, strict=True):  # pragma: no mutate
        if isinstance(result, BaseException):
            log.error(
                "todo_subscription.dispatch_failed",
                trigger_name=trigger_name,
                trigger_id=trigger_id,
                error=str(result),
                error_type=type(result).__name__,
            )
        else:
            fired += result

    log.info("todo_subscription.dispatch_complete", fired=fired)
    return f"fired:{fired}"
