"""The one path an app event takes to the GAIA tasks subscribed to it.

TriggerHandler.process_event calls dispatch_event_to_tasks for every event it receives.
Tasks are found both ways a subscription can be reached: per-resource triggers by the
Composio instance id on the webhook, account-level triggers (Gmail) by user and trigger
name. Each matching subscription's conditions, gate and the occurrence claim decide
whether the event is taken; a taken event runs the task now, rides the run its window
already has, waits for the user's quiet hours to end, or is kept while the system has the
task paused. A run is a run_task job carrying the events as its origin.
"""

from collections.abc import Sequence

from app.constants.integrations import EVENT_ACCOUNT_ID_KEY
from app.constants.tasks import RUN_TASK_JOB, TaskLogEvent
from app.constants.trigger_gates import GateOwner
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument
from app.models.todo_models import ExternalRefSource
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    TriggerOrigin,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.analytics_service import capture
from app.services.tasks.event_window import (
    buffer_task_event,
    buffer_task_event_until,
    claim_event_window,
    event_window,
    keep_event_while_paused,
)
from app.services.tasks.run_records import record_event
from app.services.triggers.condition_matching import conditions_match
from app.services.triggers.occurrences import claim_occurrence
from app.services.triggers.trigger_gate import (
    GateBypass,
    GatedJob,
    GateHold,
    GateRun,
    GateSkip,
    automation_text,
    decide_gate,
)
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import EventFireOutcome, TaskEventFired
from shared.py.wide_events import log

#: What each outcome of a taken event says on the task's log.
_TAKEN_NOTE: dict[EventFireOutcome, str] = {
    "ran": "runs now",
    "coalesced": "rides the task's next run",
    "held_for_quiet_hours": "held until your quiet hours end",
    "kept_while_paused": "kept until the task resumes",
}


async def dispatch_event_to_tasks(
    trigger_names: Sequence[str],
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, object],
    *,
    occurrence: str | None,
) -> int:
    """Hand one app event to every task subscribed to it; returns how many subscriptions took it.

    One subscription failing is logged and costs only its own task the event.
    """
    taken = 0
    for task in await _listeners(trigger_names, trigger_id, user_id):
        for subscription in task.subscriptions:
            if not _reaches(task, subscription, trigger_names, trigger_id, payload):
                continue
            try:
                taken += await _take(task, subscription, payload, occurrence)
            except Exception as e:
                log.error(
                    "task_event.dispatch_failed",
                    task_id=task.id,
                    subscription_id=subscription.id,
                    trigger_name=subscription.trigger_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
    log.set_ns("trigger", task_subscriptions_taken=taken)
    return taken


async def _listeners(
    trigger_names: Sequence[str], trigger_id: str | None, user_id: str | None
) -> list[TaskDocument]:
    """Both lookups, deduped: a task can be reached either way."""
    by_id = (
        await task_repository.find_listening_by_composio_trigger_all_users(trigger_id)
        if trigger_id
        else []
    )
    by_account = (
        await task_repository.find_listening_by_user_and_trigger(user_id, trigger_names)
        if user_id
        else []
    )
    return list({task.id: task for task in [*by_id, *by_account]}.values())


def _reaches(
    task: TaskDocument,
    subscription: TriggerSubscription,
    trigger_names: Sequence[str],
    trigger_id: str | None,
    payload: dict[str, object],
) -> bool:
    """Whether the event is one this subscription listens for, on its instance, account and conditions.

    A paused subscription listens only while the system has its task paused, so the event
    is kept for the resume.
    """
    if subscription.trigger_name not in trigger_names:
        return False
    # A per-resource subscription fires only for an instance it registered.
    if subscription.composio_trigger_ids and trigger_id not in subscription.composio_trigger_ids:
        return False
    if subscription.status is not TriggerSubscriptionStatus.ACTIVE and task.pause_reason is None:
        return False
    if (
        subscription.account_id is not None
        and payload.get(EVENT_ACCOUNT_ID_KEY) != subscription.account_id
    ):
        return False
    if subscription.action is not SubscriptionAction.EXECUTE:
        log.error(
            "task_event.action_unsupported",
            task_id=task.id,
            subscription_id=subscription.id,
            action=subscription.action.value,
        )
        return False
    return conditions_match(
        subscription.trigger_name, subscription.conditions, payload, subscription.match
    )


def _tracked_threads(task: TaskDocument, subscription: TriggerSubscription) -> frozenset[str]:
    """Return the Gmail threads the task owns or the subscription is pinned to."""
    pinned = {
        str(condition.value)
        for condition in subscription.conditions
        if condition.field_name == "thread_id" and condition.operator is ConditionOperator.EQUALS
    }
    ref = task.external_ref
    if ref is not None and ref.source is ExternalRefSource.GMAIL_THREAD:
        pinned.add(ref.id)
    return frozenset(pinned)


async def _take(
    task: TaskDocument,
    subscription: TriggerSubscription,
    payload: dict[str, object],
    occurrence: str | None,
) -> int:
    """Gate one matched event, claim its occurrence, then run, coalesce, hold or keep it; 1 when taken.

    The gate goes first: a skipped event must not burn the occurrence or the window slot
    the next real one needs.
    """
    verdict = await decide_gate(
        subscription.gate,
        GatedJob(
            owner=GateOwner.TASK,
            id=subscription.id,
            user_id=task.user_id,
            automation=automation_text(task.title, task.body),
            tracked_threads=_tracked_threads(task, subscription),
            task_id=task.id,
        ),
        trigger_name=subscription.trigger_name,
        payload=payload,
    )
    if isinstance(verdict, GateSkip):
        return 0
    if occurrence is not None and not await claim_occurrence(task.id, occurrence):
        log.info("task_event.occurrence_already_taken", task_id=task.id, occurrence=occurrence)
        return 0
    origin = TriggerOrigin(
        subscription_id=subscription.id,
        trigger_name=subscription.trigger_name,
        payload=payload,
        quiet_hours_bypass=verdict.stamp if isinstance(verdict, GateBypass) else None,
    )
    outcome = await _route(task, origin, verdict)
    await record_event(
        task,
        TaskLogEvent.APP_EVENT,
        f"{subscription.trigger_name} matched; {_TAKEN_NOTE[outcome]}",
    )
    capture(
        UserId(task.user_id),
        TaskEventFired(task_id=task.id, trigger_name=subscription.trigger_name, outcome=outcome),
    )
    return 1


async def _route(
    task: TaskDocument, origin: TriggerOrigin, verdict: GateRun | GateHold | GateBypass
) -> EventFireOutcome:
    """Put the event where it runs; an event that cannot be buffered runs now, since a lost reply is worse."""
    if task.pause_reason is not None:
        if await keep_event_while_paused(task.id, origin):
            return "kept_while_paused"
        await record_event(
            task,
            TaskLogEvent.APP_EVENT_DROPPED,
            f"a {origin.trigger_name} event reached the paused task and could not be kept",
        )
        raise RuntimeError(f"the event for paused task {task.id} could not be kept")
    if isinstance(verdict, GateHold):
        if await buffer_task_event_until(task.id, origin, verdict.until):
            return "held_for_quiet_hours"
    elif isinstance(verdict, GateRun) and not await claim_event_window(event_window(task)):
        if await buffer_task_event(task.id, origin):
            return "coalesced"
    await enqueue_worker_job(
        await RedisPoolManager.get_pool(), RUN_TASK_JOB, task.id, None, events=[origin]
    )
    return "ran"
