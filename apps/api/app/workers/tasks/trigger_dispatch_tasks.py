"""ARQ task: hand a fired trigger to the GAIA tasks subscribed to it.

The fan-out runs here, not inline in TriggerHandler.process_event, for a load-bearing
dependency reason: the task stack imports the trigger stack back (to register and
release subscriptions), and the trigger package imports every handler, so calling it
from base.py would close a real import cycle. Handing the work to a task cuts it,
since the handler only needs a task name.

It also keeps the webhook path fast (a Mongo scan across every subscriber can't delay
the workflow queueing that follows) and lands failures in their own wide-event boundary
instead of a handler's.
"""

from typing import Any

from app.services.tasks.event_dispatch import dispatch_event_to_tasks
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log


async def dispatch_to_subscribers(
    ctx: dict[str, Any],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    trigger_names: list[str],
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, Any],
    occurrence: str | None = None,
) -> str:
    """Hand the event to every subscribed task.

    One handler can serve several GAIA trigger names (Gmail's account-level and poll
    variants share an event type). occurrence names the real-world occurrence the
    event reports, so a task runs once for it.
    """
    log.set(
        component="trigger_subscription",
        operation="dispatch",
        trigger_id=trigger_id,
        user_id=user_id,
        trigger_names=trigger_names,
    )

    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        fired = await dispatch_event_to_tasks(
            trigger_names, trigger_id, user_id, payload, occurrence=occurrence
        )

    log.info("subscriber_dispatch.complete", fired=fired)
    return f"fired:{fired}"
