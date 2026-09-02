"""Register, tear down, pause and resume a tracked todo's trigger subscriptions.

Subscriptions go through the same Composio registration path as workflows, and the
same reference-counted deletion: two owners with identical configs share one
Composio trigger instance, so a teardown that counted only its own kind would
delete the other's live trigger.

Two registration shapes exist and the handler decides which (see
``TriggerHandler.registers_instances``). Per-resource triggers return instance ids
we store and later refcount. Account-level triggers (Gmail) fire on the connected
account itself: registration returns nothing, there is nothing to refcount, and
dispatch finds the subscription by user and trigger name instead. Conflating the
two is how a reply-watching todo silently never fires.
"""

from typing import Any

from pydantic import ValidationError

from app.constants.todos import BLOCKING_LABEL
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoUpdate
from app.models.trigger_subscription_models import (
    ConditionMatch,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerSubscription,
)
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.triggers import get_handler_by_name
from app.services.triggers.subscription_validation import (
    ValidationOutcome,
    validate_conditions,
)
from app.services.workflow.trigger_service import TriggerService
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import log

DEFAULT_COOLDOWN_SECONDS = 900


class SubscriptionError(Exception):
    """A subscription could not be registered, with a message the agent can act on."""


def build_trigger_config(trigger_name: str, trigger_data: dict[str, Any] | None) -> TriggerConfig:
    """The ``TriggerConfig`` a handler expects, for a todo rather than a workflow.

    ``trigger_data`` carries the registration-time knobs the payload cannot express
    — a calendar's ``minutes_before_start``, a Slack channel id. The discriminated
    union keys on ``trigger_name``, so it is stamped into both halves.
    """
    return TriggerConfig.model_validate(
        {
            "type": TriggerType.INTEGRATION.value,
            "trigger_name": trigger_name,
            "trigger_data": {**(trigger_data or {}), "trigger_name": trigger_name},
        }
    )


async def register_subscription(
    *,
    todo_id: str,
    user_id: str,
    trigger_name: str,
    conditions: list[SubscriptionCondition],
    action: SubscriptionAction,
    match: ConditionMatch = ConditionMatch.ALL,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    trigger_data: dict[str, Any] | None = None,
) -> tuple[TriggerSubscription, ValidationOutcome]:
    """Validate, register with Composio, and store one subscription on ``todo_id``.

    Returns the stored subscription and the validation outcome, so the caller can
    surface what was mechanically repaired. Raises ``SubscriptionError`` when the
    conditions cannot be made valid or the trigger cannot be registered — a
    subscription that cannot fire must never be stored.
    """
    log.set(
        component="trigger_subscription",
        operation="register",
        user_id=user_id,
        todo_id=todo_id,
        trigger_name=trigger_name,
    )

    def _fail(reason: str, message: str) -> SubscriptionError:
        # A webhook/worker path has no request context, so the id is explicit.
        capture_event(
            user_id,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": trigger_name, "reason": reason},
        )
        return SubscriptionError(message)

    handler = get_handler_by_name(trigger_name)
    if handler is None:
        raise _fail(
            "unknown_trigger",
            f"'{trigger_name}' has no trigger handler and cannot be watched.",
        )

    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None:
        raise _fail("todo_not_found", f"Tracked todo {todo_id} was not found.")

    outcome = validate_conditions(trigger_name, conditions)
    if not outcome.ok:
        raise _fail("invalid_conditions", " ".join(outcome.errors))

    # Registration config (a calendar's reminder window, a channel id) is validated
    # by the discriminated union, and an out-of-range value must come back as
    # something the caller can act on rather than a raw pydantic traceback.
    try:
        config = build_trigger_config(trigger_name, trigger_data)
    except ValidationError as e:
        raise _fail(
            "invalid_config",
            f"Invalid configuration for '{trigger_name}': {e.errors()[0]['msg']}",
        ) from e

    try:
        trigger_ids = await TriggerService.register_triggers(
            user_id, todo_id, trigger_name, config, raise_on_failure=True
        )
    except TriggerRegistrationError as e:
        raise _fail("registration_failed", f"Could not register '{trigger_name}': {e}") from e

    # An account-level trigger returning nothing is success. A per-resource one
    # returning nothing registered nothing, so the subscription could never fire —
    # storing it would be a watch that silently does nothing forever.
    if handler.registers_instances and not trigger_ids:
        raise _fail(
            "no_trigger_instance",
            f"Registering '{trigger_name}' returned no trigger instance, so the "
            "subscription would never fire. Check the trigger configuration.",
        )

    subscription = TriggerSubscription(
        trigger_name=trigger_name,
        conditions=outcome.conditions,
        match=match,
        action=action,
        cooldown_seconds=cooldown_seconds,
        resolution=(
            SubscriptionResolution.TRIGGER_ID
            if handler.registers_instances
            else SubscriptionResolution.ACCOUNT
        ),
        composio_trigger_ids=trigger_ids,
        trigger_data=trigger_data or {},
    )

    await todo_repository.update(
        todo_id,
        user_id=user_id,
        update=TodoUpdate(trigger_subscriptions=[*todo.trigger_subscriptions, subscription]),
    )
    capture_event(
        user_id,
        AnalyticsEvents.TODO_SUBSCRIPTION_REGISTERED,
        {
            "trigger_name": trigger_name,
            "action": action.value,
            "resolution": subscription.resolution.value,
            "condition_count": len(outcome.conditions),
            "repaired": bool(outcome.repairs),
            "cooldown_seconds": cooldown_seconds,
        },
    )
    log.info(
        "todo_subscription.registered",
        todo_id=todo_id,
        subscription_id=subscription.id,
        trigger_name=trigger_name,
        action=action.value,
        resolution=subscription.resolution.value,
        condition_count=len(outcome.conditions),
        repair_count=len(outcome.repairs),
    )
    return subscription, outcome


async def unregister_subscription(
    todo_id: str, user_id: str, subscription_id: str
) -> TriggerSubscription | None:
    """Drop one subscription from a todo. Returns it, or None if it was not there.

    The refcount decides whether the Composio trigger actually goes: another todo
    or workflow may share the instance, and this todo is excluded from its own
    count so the last reference does release it.
    """
    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None:
        return None

    target = next((s for s in todo.trigger_subscriptions if s.id == subscription_id), None)
    if target is None:
        return None

    remaining = [s for s in todo.trigger_subscriptions if s.id != subscription_id]
    # Write first: if unregistering upstream fails, the stored subscription is
    # already gone, so the todo cannot keep firing on a watch the user removed.
    await todo_repository.update(
        todo_id, user_id=user_id, update=TodoUpdate(trigger_subscriptions=remaining)
    )

    if target.composio_trigger_ids:
        try:
            await TriggerService.unregister_triggers(
                user_id, target.trigger_name, target.composio_trigger_ids, todo_id=todo_id
            )
        except Exception as e:
            log.error(
                "todo_subscription.unregister_failed",
                todo_id=todo_id,
                subscription_id=subscription_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    log.info(
        "todo_subscription.unregistered",
        todo_id=todo_id,
        subscription_id=subscription_id,
        trigger_name=target.trigger_name,
    )
    return target


async def teardown_subscriptions(todo_id: str, user_id: str, *, reason: str) -> int:
    """Unregister every subscription on ``todo_id`` and clear them from the document.

    Called on every path that ends a todo's life — completion, archival, failure and
    deletion. Deletion matters most: once the document is gone nothing names the
    Composio trigger any more, so it would leak with no way to find it.

    Composio deletion is reference-counted, and this todo is excluded from its own
    count so the last reference actually releases the trigger.
    """
    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None or not todo.trigger_subscriptions:
        return 0

    log.set(component="trigger_subscription", operation="teardown", todo_id=todo_id)
    for subscription in todo.trigger_subscriptions:
        if not subscription.composio_trigger_ids:
            continue
        try:
            await TriggerService.unregister_triggers(
                user_id,
                subscription.trigger_name,
                subscription.composio_trigger_ids,
                todo_id=todo_id,
            )
        except Exception as e:
            # One stuck trigger must not strand the others or block the todo from
            # completing — but it is a real leak, so it is an error, not a warning.
            log.error(
                "todo_subscription.teardown_failed",
                todo_id=todo_id,
                subscription_id=subscription.id,
                trigger_name=subscription.trigger_name,
                error=str(e),
                error_type=type(e).__name__,
            )

    count = len(todo.trigger_subscriptions)
    await todo_repository.update(
        todo_id, user_id=user_id, update=TodoUpdate(trigger_subscriptions=[])
    )
    log.info("todo_subscription.torn_down", todo_id=todo_id, count=count, reason=reason)
    return count


async def pause_subscriptions_for_trigger_names(user_id: str, trigger_names: set[str]) -> int:
    """Mark subscriptions on ``trigger_names`` paused and flag their todos.

    Called when the integration behind them loses its connection. The subscription
    keeps its stored Composio ids so the refcount still protects the trigger while
    it is paused, and the todo gains the blocking label the maintenance sweep
    already understands — a dead watch the user cannot see is the failure this
    avoids.
    """
    paused = 0
    for trigger_name in trigger_names:
        for todo in await todo_repository.find_active_by_user_and_trigger(user_id, trigger_name):
            if todo.id is None:
                continue
            labels = (
                todo.labels if BLOCKING_LABEL in todo.labels else [*todo.labels, BLOCKING_LABEL]
            )
            await todo_repository.update(
                todo.id,
                user_id=user_id,
                update=TodoUpdate(
                    labels=labels,
                    trigger_subscriptions=_with_status(
                        todo.trigger_subscriptions, trigger_names, SubscriptionStatus.PAUSED
                    ),
                ),
            )
            paused += 1
    if paused:
        log.info("todo_subscription.paused", user_id=user_id, todo_count=paused)
    return paused


async def resync_subscriptions_for_trigger_names(user_id: str, trigger_names: set[str]) -> int:
    """Re-register a user's subscriptions after a (re)connect, and unpause them.

    A reconnect creates a fresh Composio connected account, so instance ids
    registered against the old one go permanently stale. Mirrors
    ``resync_user_workflow_triggers``: failures are logged per todo so one broken
    subscription cannot block the rest, or the OAuth flow this runs behind.
    """
    resynced = 0
    for trigger_name in trigger_names:
        handler = get_handler_by_name(trigger_name)
        if handler is None:
            continue
        for todo in await todo_repository.find_paused_by_user_and_trigger(user_id, trigger_name):
            if todo.id is None:
                continue
            try:
                updated = await _resync_one(
                    user_id, todo.id, todo.trigger_subscriptions, trigger_name
                )
            except Exception as e:
                log.error(
                    "todo_subscription.resync_failed",
                    todo_id=todo.id,
                    trigger_name=trigger_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                continue
            labels = [label for label in todo.labels if label != BLOCKING_LABEL]
            await todo_repository.update(
                todo.id,
                user_id=user_id,
                update=TodoUpdate(labels=labels, trigger_subscriptions=updated),
            )
            resynced += 1
    if resynced:
        log.info("todo_subscription.resynced", user_id=user_id, todo_count=resynced)
    return resynced


async def _resync_one(
    user_id: str,
    todo_id: str,
    subscriptions: list[TriggerSubscription],
    trigger_name: str,
) -> list[TriggerSubscription]:
    """Re-register every subscription on ``trigger_name`` and repoint its ids."""
    refreshed: list[TriggerSubscription] = []
    for subscription in subscriptions:
        if subscription.trigger_name != trigger_name:
            refreshed.append(subscription)
            continue
        new_ids = await TriggerService.register_triggers(
            user_id,
            todo_id,
            trigger_name,
            build_trigger_config(trigger_name, subscription.trigger_data),
            raise_on_failure=True,
        )
        stale = [i for i in subscription.composio_trigger_ids if i not in new_ids]
        refreshed.append(
            subscription.model_copy(
                update={
                    "status": SubscriptionStatus.ACTIVE,
                    # Account-level triggers return no ids — keep the empty list.
                    "composio_trigger_ids": new_ids or subscription.composio_trigger_ids,
                }
            )
        )
        if stale:
            await TriggerService.unregister_triggers(user_id, trigger_name, stale, todo_id=todo_id)
    return refreshed


def _with_status(
    subscriptions: list[TriggerSubscription],
    trigger_names: set[str],
    status: SubscriptionStatus,
) -> list[TriggerSubscription]:
    return [
        s.model_copy(update={"status": status}) if s.trigger_name in trigger_names else s
        for s in subscriptions
    ]
