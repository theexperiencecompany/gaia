"""A GAIA task's app-event subscriptions: subscribe, unsubscribe, release, pause and resume.

Registration goes through the same Composio path as workflows, with the
same reference-counted deletion: owners with identical configs share one Composio trigger
instance, so a release counts every owner and excludes only the task itself. Per-resource
triggers return instance ids the subscription stores; account-level ones (Gmail) return
none and are found by user and trigger name.

An app's account dying pauses the tasks that listen to it (pause_reason integration_expired,
the app named in blocked_on_integrations), and its subscriptions are marked paused, keeping
their Composio ids. Events that still reach a paused task are kept for its resume. A
(re)connect re-registers the paused subscriptions and resumes the task once none is left
paused; a restored plan resumes the tasks it paused. Both replay the kept events.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.config.oauth_config import get_integration_by_id
from app.constants.tasks import Assignee, TaskFlag, TaskLogEvent, WhenKind
from app.constants.trigger_gates import GateOwner
from app.db.repositories.tasks import task_repository
from app.models.scheduler_models import DeactivationReason
from app.models.task_models import RepeatWhen, TaskDocument, TaskUpdate, When
from app.models.trigger_gate_models import GateEdit, TriggerGate
from app.models.trigger_subscription_models import (
    ConditionMatch,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.analytics_service import capture
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.tasks.arming import arm_task
from app.services.tasks.errors import SubscriptionNotFoundError
from app.services.tasks.event_window import release_events_kept_while_paused
from app.services.tasks.run_records import record_event
from app.services.tasks.subscription_config import (
    AccountScope,
    SubscriptionError,
    build_trigger_config,
)
from app.services.tasks.todo_rounds import first_repeat
from app.services.triggers import get_handler_by_name
from app.services.triggers.gate_edits import apply_gate_edit, report_gate_edit
from app.services.triggers.subscription_validation import ValidationOutcome, validate_conditions
from app.services.user_service import get_profile_timezone
from app.services.workflow.trigger_service import TriggerService
from app.utils.exceptions import TriggerRegistrationError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import (
    TaskSubscribed,
    TaskSubscribeFailed,
    TaskSubscribeFailureReason,
)
from shared.py.wide_events import log

#: The apps' system pauses a reconnect can lift; any other pause is not an app's to lift.
_APP_PAUSES = frozenset(
    {DeactivationReason.INTEGRATION_EXPIRED, DeactivationReason.INTEGRATION_NEVER_CONNECTED}
)


@dataclass(frozen=True)
class SubscriptionRequest:
    """What GAIA asked a task to listen for, before it is validated and registered."""

    trigger_name: str
    action: SubscriptionAction
    conditions: list[SubscriptionCondition]
    match: ConditionMatch
    cooldown_seconds: int
    trigger_data: Mapping[str, object] | None
    account_id: str | None
    gate: TriggerGate | None


@dataclass(frozen=True)
class Subscribed:
    """The subscription now on the task, how its conditions were repaired, and whether this call stored it."""

    subscription: TriggerSubscription
    outcome: ValidationOutcome
    created: bool


def _same_watch(left: TriggerSubscription, right: TriggerSubscription) -> bool:
    """Whether two active subscriptions fire on exactly the same events; mirrors the repository's dedupe."""
    return (
        left.trigger_name == right.trigger_name
        and left.account_id == right.account_id
        and left.action == right.action
        and left.match == right.match
        and set(left.conditions) == set(right.conditions)
        and left.cooldown_seconds == right.cooldown_seconds
        and left.trigger_data == right.trigger_data
        and left.status is TriggerSubscriptionStatus.ACTIVE
        and right.status is TriggerSubscriptionStatus.ACTIVE
    )


async def subscribe(task: TaskDocument, request: SubscriptionRequest) -> Subscribed:
    """Validate, register with Composio and store one subscription on a GAIA task.

    Raises SubscriptionError with a message the agent can act on. Built before Composio is
    called, so a row its own rules refuse leaves no trigger instance upstream.
    """
    name = request.trigger_name
    log.set(task={"id": task.id, "subscribe": name})

    def _fail(reason: TaskSubscribeFailureReason, message: str) -> SubscriptionError:
        capture(UserId(task.user_id), TaskSubscribeFailed(trigger_name=name, reason=reason))
        return SubscriptionError(message)

    if task.assignee is not Assignee.GAIA:
        raise _fail("not_a_gaia_task", f"{task.id} is the user's own to-do; only GAIA's run.")
    handler = get_handler_by_name(name)
    if handler is None:
        raise _fail("unknown_trigger", f"'{name}' has no trigger handler and cannot be watched.")
    outcome = validate_conditions(name, request.conditions)
    if not outcome.ok:
        raise _fail("invalid_conditions", " ".join(outcome.errors))
    try:
        config = build_trigger_config(name, request.trigger_data)
    except ValidationError as e:
        first_error: ErrorDetails = e.errors()[0]
        raise _fail(
            "invalid_config", f"Invalid configuration for '{name}': {first_error['msg']}"
        ) from e
    try:
        subscription = TriggerSubscription(
            trigger_name=name,
            account_id=request.account_id,
            conditions=outcome.conditions,
            match=request.match,
            action=request.action,
            cooldown_seconds=request.cooldown_seconds,
            resolution=(
                SubscriptionResolution.TRIGGER_ID
                if handler.registers_instances
                else SubscriptionResolution.ACCOUNT
            ),
            trigger_data=dict(request.trigger_data or {}),
            gate=request.gate,
        )
    except ValidationError as e:
        refusal: ErrorDetails = e.errors()[0]
        raise _fail("invalid_subscription", f"Invalid subscription: {refusal['msg']}") from e
    try:
        subscription.composio_trigger_ids = await TriggerService.register_triggers(
            task.user_id, task.id, name, config, raise_on_failure=True
        )
    except TriggerRegistrationError as e:
        raise _fail("registration_failed", f"Could not register '{name}': {e}") from e
    # A per-resource trigger that registered nothing could never fire.
    if handler.registers_instances and not subscription.composio_trigger_ids:
        raise _fail(
            "no_trigger_instance",
            f"Registering '{name}' returned no trigger instance, so the subscription would "
            "never fire. Check the trigger configuration.",
        )
    stored = await _store(task, subscription, outcome)
    if not stored.created:
        # A twin landed first: the instance registered for this call has no row of its own.
        await _release_unstored(task, subscription)
    return stored


async def _store(
    task: TaskDocument, subscription: TriggerSubscription, outcome: ValidationOutcome
) -> Subscribed:
    written = await task_repository.add_subscription(
        task.id, user_id=task.user_id, subscription=subscription
    )
    if written is None:
        await _release_unstored(task, subscription)
        raise SubscriptionError(f"Task {task.id} was not found.")
    if all(sub.id != subscription.id for sub in written.subscriptions):
        twin = next(s for s in written.subscriptions if _same_watch(s, subscription))
        return Subscribed(twin, outcome, created=False)
    capture(
        UserId(task.user_id),
        TaskSubscribed(
            task_id=task.id,
            trigger_name=subscription.trigger_name,
            condition_count=len(subscription.conditions),
            repaired=bool(outcome.repairs),
            has_gate=subscription.gate is not None,
        ),
    )
    await record_event(
        written,
        TaskLogEvent.SUBSCRIBED,
        f"listening for {subscription.trigger_name} "
        f"({len(subscription.conditions)} condition(s), subscription {subscription.id})",
    )
    return Subscribed(subscription, outcome, created=True)


async def _release_unstored(task: TaskDocument, subscription: TriggerSubscription) -> None:
    """Drop the Composio instance of a subscription no row holds; other owners still count."""
    if not subscription.composio_trigger_ids:
        return
    await TriggerService.unregister_triggers(
        task.user_id, subscription.trigger_name, subscription.composio_trigger_ids
    )


async def unsubscribe(task: TaskDocument, subscription_id: str) -> TriggerSubscription | None:
    """Drop one subscription from the task; None when it held none by that id.

    Written first, so a failed upstream release cannot leave the task firing on a
    subscription the user or GAIA removed. A task that comes round only on its events
    keeps its last one: it would have nothing left to wake it.
    """
    if task.when.kind is WhenKind.EVENT and [s.id for s in task.subscriptions] == [subscription_id]:
        raise SubscriptionError(
            f"Task {task.id} runs only on its app events and this is its last one; give it a "
            "schedule or complete it instead."
        )
    before = await task_repository.remove_subscriptions(
        task.id, user_id=task.user_id, subscription_ids=[subscription_id]
    )
    if before is None:
        return None
    removed = next(s for s in before.subscriptions if s.id == subscription_id)
    await TriggerService.unregister_triggers(
        task.user_id, removed.trigger_name, removed.composio_trigger_ids, task_id=task.id
    )
    await record_event(
        before, TaskLogEvent.UNSUBSCRIBED, f"stopped listening for {removed.trigger_name}"
    )
    return removed


async def edit_gate(task: TaskDocument, subscription_id: str, edit: GateEdit) -> TaskDocument:
    """Store the user's edit to the gate on one of the task's subscriptions; return the task."""
    current = next((s for s in task.subscriptions if s.id == subscription_id), None)
    if current is None:
        raise SubscriptionNotFoundError(task.id, subscription_id)
    gate = apply_gate_edit(current.gate, edit)
    written = await task_repository.set_subscription_gate(
        task.id, user_id=task.user_id, subscription_id=subscription_id, gate=gate
    )
    if written is None:
        raise SubscriptionNotFoundError(task.id, subscription_id)
    report_gate_edit(task.user_id, GateOwner.TASK, current.gate, gate)
    return written


async def release_subscriptions(task: TaskDocument) -> None:
    """Release every Composio instance a task that stops for good holds; its subscriptions stay listed.

    Called when a task is completed, marked failed or deleted: nothing would run on its
    events again, so the reference count must stop counting it. A trigger that fails to
    release is logged and the rest still go.
    """
    before = await task_repository.release_composio_ids(task.id, user_id=task.user_id)
    for subscription in before.subscriptions if before else []:
        released = await TriggerService.unregister_triggers(
            task.user_id,
            subscription.trigger_name,
            subscription.composio_trigger_ids,
            task_id=task.id,
        )
        if not released:
            log.error(
                "task_subscription.release_failed",
                task_id=task.id,
                subscription_id=subscription.id,
                trigger_name=subscription.trigger_name,
            )


def _trigger_names(integration_id: str) -> set[str]:
    """Return the GAIA trigger names an integration publishes."""
    integration = get_integration_by_id(integration_id)
    if integration is None:
        return set()
    return {
        t.workflow_trigger_schema.slug
        for t in integration.associated_triggers
        if t.workflow_trigger_schema
    }


def _app_name(integration_id: str) -> str:
    integration = get_integration_by_id(integration_id)
    return integration.name if integration else integration_id


async def pause_for_lost_account(
    user_id: str, integration_id: str, account_id: str, *, integration_expired: bool
) -> int:
    """Pause the tasks listening to an account that died; returns how many paused.

    A subscription limited to that account stops with it; one listening to every account
    stops only once the whole integration expired. The task is paused with a reason the
    user reads, unless something already paused or stopped it.
    """
    scope = AccountScope(account_id=account_id, every_account=integration_expired)
    names = _trigger_names(integration_id)
    paused = 0
    for task in await task_repository.find_listening_by_user_and_trigger(user_id, names):
        hit = [
            s
            for s in task.subscriptions
            if s.trigger_name in names
            and s.status is TriggerSubscriptionStatus.ACTIVE
            and scope.covers(s)
        ]
        if not hit:
            continue
        await task_repository.pause_subscriptions(
            task.id, user_id=user_id, subscription_ids={s.id for s in hit}
        )
        if task.active:
            await task_repository.deactivate(
                task.id,
                user_id=user_id,
                reason=DeactivationReason.INTEGRATION_EXPIRED,
                blocked_on_integrations=sorted({*task.blocked_on_integrations, integration_id}),
            )
        await record_event(
            task,
            TaskLogEvent.PAUSED,
            f"{_app_name(integration_id)} was disconnected, so "
            f"{', '.join(sorted({s.trigger_name for s in hit}))} is paused until it is reconnected",
        )
        paused += 1
    log.set_ns("task_subscription", paused_for_lost_account=paused)
    return paused


async def resume_for_connected_account(user_id: str, integration_id: str, account_id: str) -> int:
    """Revive what an account's (re)connect brings back; returns how many tasks resumed.

    The paused subscriptions limited to that account, and those listening to every account,
    are re-registered. Then each task an app's death paused resumes once none of its
    subscriptions is still paused and every app it waits on is connected.
    """
    await resync_paused_subscriptions(
        user_id,
        _trigger_names(integration_id),
        AccountScope(account_id=account_id, every_account=True),
    )
    connected = await get_connected_integration_ids(user_id)
    resumed = 0
    for reason in _APP_PAUSES:
        for task in await task_repository.find_paused_for_reason(user_id, reason):
            if integration_id in task.blocked_on_integrations and await _resume_app_pause(
                task, connected
            ):
                resumed += 1
    log.set_ns("task_subscription", resumed_for_connected_account=resumed)
    return resumed


async def resync_paused_subscriptions(
    user_id: str, trigger_names: set[str], scope: AccountScope
) -> int:
    """Re-register the user's paused subscriptions on trigger_names that scope covers; returns how many tasks.

    A reconnect may hand them a fresh Composio connected account, so ids registered on the
    old one go stale. One task failing is logged and the rest still go.
    """
    resynced = 0
    for name in trigger_names:
        for task in await task_repository.find_paused_by_user_and_trigger(user_id, name):
            due = [
                s
                for s in task.subscriptions
                if s.trigger_name == name
                and s.status is TriggerSubscriptionStatus.PAUSED
                and scope.covers(s)
            ]
            if not due:
                continue
            try:
                trigger_ids = await _reregister(task, due)
            except Exception as e:
                log.error(
                    "task_subscription.resync_failed",
                    task_id=task.id,
                    trigger_name=name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                continue
            await task_repository.resume_subscriptions(
                task.id, user_id=user_id, trigger_ids=trigger_ids
            )
            resynced += 1
    return resynced


async def _reregister(
    task: TaskDocument, subscriptions: list[TriggerSubscription]
) -> dict[str, list[str]]:
    """Re-register each subscription and map its id to the Composio ids it now fires on."""
    trigger_ids: dict[str, list[str]] = {}
    for subscription in subscriptions:
        fresh = await TriggerService.register_triggers(
            task.user_id,
            task.id,
            subscription.trigger_name,
            build_trigger_config(subscription.trigger_name, subscription.trigger_data),
            raise_on_failure=True,
        )
        stale = [i for i in subscription.composio_trigger_ids if i not in fresh]
        # Account-level triggers return no ids: the empty list stays.
        trigger_ids[subscription.id] = fresh or subscription.composio_trigger_ids
        await TriggerService.unregister_triggers(
            task.user_id, subscription.trigger_name, stale, task_id=task.id
        )
    return trigger_ids


async def _resume_app_pause(task: TaskDocument, connected: set[str]) -> bool:
    """Resume a task an app's death paused once nothing it waits on is missing; True when it resumed."""
    if any(s.status is TriggerSubscriptionStatus.PAUSED for s in task.subscriptions):
        return False
    still_blocked = [i for i in task.blocked_on_integrations if i not in connected]
    if still_blocked:
        await task_repository.update(
            task.id, user_id=task.user_id, update=TaskUpdate(blocked_on_integrations=still_blocked)
        )
        return False
    names = ", ".join(_app_name(i) for i in task.blocked_on_integrations) or "Its app"
    await _resume(task, f"{names} connected again")
    return True


async def resume_tasks_paused_for(user_id: str, reason: DeactivationReason) -> int:
    """Resume the user's GAIA tasks the system paused for reason; returns the count resumed.

    One that cannot resume does not stop the rest; their failures are raised together.
    """
    resumed = 0
    failures: list[Exception] = []
    for task in await task_repository.find_paused_for_reason(user_id, reason):
        try:
            await _resume(task, "the plan is active again")
        except Exception as e:  # the user's other tasks must still resume
            log.warning("task.resume_failed", task_id=task.id, error=str(e))
            failures.append(e)
            continue
        resumed += 1
    log.set_ns("task", resumed=resumed, resume_reason=reason.value)
    if failures:
        raise ExceptionGroup(f"{len(failures)} paused task(s) could not resume", failures)
    return resumed


async def _resume(task: TaskDocument, why: str) -> None:
    """Switch a system-paused task back on, arm its next time, and replay the events it kept."""
    resumed = await task_repository.activate(
        task.id, user_id=task.user_id, when=await _fresh_when(task)
    )
    if resumed is None:
        return
    if TaskFlag.BLOCKED in resumed.status_flags and not any(
        s.status is TriggerSubscriptionStatus.PAUSED for s in resumed.subscriptions
    ):
        await task_repository.remove_flags(
            resumed.id, user_id=resumed.user_id, flags=[TaskFlag.BLOCKED]
        )
    if resumed.blocked_on_integrations:
        await task_repository.update(
            resumed.id, user_id=resumed.user_id, update=TaskUpdate(blocked_on_integrations=[])
        )
    await record_event(resumed, TaskLogEvent.RESUMED, why)
    await arm_task(resumed)
    await release_events_kept_while_paused(resumed.id)


async def _fresh_when(task: TaskDocument) -> When:
    """Return the when a resumed task comes round on: a repeat from its next occurrence after now."""
    if not isinstance(task.when, RepeatWhen):
        return task.when
    zone = task.when.timezone or (await get_profile_timezone(task.user_id)).value
    return first_repeat(task.when.model_copy(update={"next_run": None}), zone)
