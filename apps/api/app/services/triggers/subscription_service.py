"""Register, tear down, pause and resume a tracked todo's trigger subscriptions.

Subscriptions go through the same Composio registration path as workflows, and the
same reference-counted deletion: two owners with identical configs share one
Composio trigger instance, so a teardown that counted only its own kind would
delete the other's live trigger.

Two registration shapes exist and the handler decides which (see
TriggerHandler.registers_instances). Per-resource triggers return instance ids
we store and later refcount. Account-level triggers (Gmail) fire on the connected
account itself: registration returns nothing, there is nothing to refcount, and
dispatch finds the subscription by user and trigger name instead. Conflating the
two is how a reply-watching todo silently never fires.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.constants.todos import TodoActivityEvent
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    ConditionMatch,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.analytics_service import capture
from app.services.todo_activity import record_activity
from app.services.triggers import get_handler_by_name
from app.services.triggers.subscription_validation import (
    ValidationOutcome,
    validate_conditions,
)
from app.services.workflow.trigger_service import TriggerService
from app.utils.exceptions import TriggerRegistrationError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import (
    SubscriptionFailureReason,
    TodosSubscriptionFailed,
    TodosSubscriptionRegistered,
)
from shared.py.wide_events import log

DEFAULT_COOLDOWN_SECONDS = 900


class SubscriptionError(Exception):
    """A subscription could not be registered, with a message the agent can act on."""


def build_trigger_config(
    trigger_name: str, trigger_data: Mapping[str, object] | None
) -> TriggerConfig:
    """Build the TriggerConfig a handler expects, for a todo rather than a workflow.

    trigger_data carries the registration-time knobs the payload cannot express
    — a calendar's minutes_before_start, a Slack channel id. The discriminated
    union keys on trigger_name, so it is stamped into both halves.
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
    trigger_data: Mapping[str, object] | None = None,
    account_id: str | None = None,
) -> tuple[TriggerSubscription, ValidationOutcome, bool]:
    """Validate, register with Composio, and store one subscription on todo_id.

    Returns the stored row, the validation outcome, and whether this call stored
    it — a concurrent winner's row must not be treated as this call's own.
    """
    log.set(
        component="trigger_subscription",
        operation="register",
        user_id=user_id,
        todo_id=todo_id,
        trigger_name=trigger_name,
    )

    def _fail(reason: SubscriptionFailureReason, message: str) -> SubscriptionError:
        capture(UserId(user_id), TodosSubscriptionFailed(trigger_name=trigger_name, reason=reason))
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
        first_error: ErrorDetails = e.errors()[0]
        raise _fail(
            "invalid_config",
            f"Invalid configuration for '{trigger_name}': {first_error['msg']}",
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
        account_id=account_id,
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
        trigger_data=dict(trigger_data or {}),
    )

    stored = await store_subscription(
        todo,
        subscription,
        repaired=bool(outcome.repairs),
        activity=(
            f"watching {trigger_name} ({len(outcome.conditions)} condition(s)) to {action.value}"
        ),
    )
    if stored is None:
        # The Composio instance registered above has no stored row: without a
        # release it lives upstream forever, firing for a watch nobody can see.
        await _release_unstored_registration(todo_id, user_id, subscription)
        raise _fail("todo_not_found", f"Tracked todo {todo_id} was not found.")
    row, created = stored
    if not created:
        # A concurrent registration of the same watch landed first: its row is
        # the one on the todo, and the trigger instance registered for ours is
        # redundant.
        await _release_unstored_registration(todo_id, user_id, subscription)
    return row, outcome, created


def _same_watch(left: TriggerSubscription, right: TriggerSubscription) -> bool:
    """Whether two watches would fire on exactly the same events, with the same settings.

    Mirrored in Mongo by the todo repository's _same_active_watch, which dedupes the append.
    """
    return (
        left.trigger_name == right.trigger_name
        and left.account_id == right.account_id
        and left.action == right.action
        and left.match == right.match
        and set(left.conditions) == set(right.conditions)
        and left.cooldown_seconds == right.cooldown_seconds
        and left.trigger_data == right.trigger_data
        # A paused row is resync-owned: returning it as the duplicate would hand
        # back a watch that cannot fire, so only active rows dedupe.
        and left.status is TriggerSubscriptionStatus.ACTIVE
        and right.status is TriggerSubscriptionStatus.ACTIVE
    )


async def _release_unstored_registration(
    todo_id: str, user_id: str, subscription: TriggerSubscription
) -> None:
    """Drop a Composio instance whose watch was never stored.

    The todo_id is error-log context only: it is NOT passed to
    unregister_triggers, so a concurrent winner's live reference still counts.
    """
    if not subscription.composio_trigger_ids:
        return
    try:
        await TriggerService.unregister_triggers(
            user_id, subscription.trigger_name, subscription.composio_trigger_ids
        )
    except Exception as e:
        log.error(
            "todo_subscription.unregister_failed",
            todo_id=todo_id,
            subscription_id=subscription.id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def store_subscription(
    todo: TodoDocument, subscription: TriggerSubscription, *, repaired: bool, activity: str
) -> tuple[TriggerSubscription, bool] | None:
    """Append a ready subscription to the todo; count it and put it on the timeline if stored.

    The one write path for every subscription, Composio-backed or not (a sandbox
    run's has no trigger to register). Returns the row now on the todo and whether
    this call stored it, or None when the todo is gone.
    """
    written = await todo_repository.add_trigger_subscription(
        todo.id, user_id=todo.user_id, subscription=subscription
    )
    if written is None:
        return None
    if all(sub.id != subscription.id for sub in written.trigger_subscriptions):
        duplicate, *_ = [s for s in written.trigger_subscriptions if _same_watch(s, subscription)]
        return duplicate, False
    capture(
        UserId(todo.user_id),
        TodosSubscriptionRegistered(
            trigger_name=subscription.trigger_name,
            action=subscription.action.value,
            resolution=subscription.resolution.value,
            condition_count=len(subscription.conditions),
            repaired=repaired,
            cooldown_seconds=subscription.cooldown_seconds,
        ),
    )
    await record_activity(todo.id, todo.user_id, TodoActivityEvent.WATCH_ADDED, activity)
    log.info(
        "todo_subscription.registered",
        todo_id=todo.id,
        subscription_id=subscription.id,
        trigger_name=subscription.trigger_name,
        action=subscription.action.value,
        resolution=subscription.resolution.value,
        condition_count=len(subscription.conditions),
        repaired=repaired,
    )
    return subscription, True


async def unregister_subscription(
    todo_id: str, user_id: str, subscription_id: str
) -> TriggerSubscription | None:
    """Drop one subscription from a todo. Returns it, or None if it was not there.

    The refcount decides whether the Composio trigger actually goes: another todo
    or workflow may share the instance, and this todo is excluded from its own
    count so the last reference does release it.
    """
    # Write first: if unregistering upstream fails, the stored subscription is
    # already gone, so the todo cannot keep firing on a watch the user removed.
    before = await todo_repository.remove_trigger_subscriptions(
        todo_id, user_id=user_id, subscription_ids=[subscription_id]
    )
    if before is None:
        return None
    (target,) = [s for s in before.trigger_subscriptions if s.id == subscription_id]

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

    await record_activity(
        todo_id, user_id, TodoActivityEvent.WATCH_REMOVED, f"stopped watching {target.trigger_name}"
    )
    log.info(
        "todo_subscription.unregistered",
        todo_id=todo_id,
        subscription_id=subscription_id,
        trigger_name=target.trigger_name,
    )
    return target


async def teardown_subscriptions(todo_id: str, user_id: str, *, reason: str) -> int:
    """Unregister every subscription on todo_id and clear them from the document.

    Called on every path that ends a todo's life — completion, archival, failure
    and deletion — since once the document is gone nothing names the Composio
    trigger any more. Composio deletion is reference-counted, and this todo is
    excluded from its own count so the last reference actually releases the trigger.
    """
    # Cleared first, so a watch added meanwhile is torn down with the rest, not left stored.
    before = await todo_repository.clear_trigger_subscriptions(todo_id, user_id=user_id)
    if before is None:
        return 0

    log.set(component="trigger_subscription", operation="teardown", todo_id=todo_id)
    for subscription in before.trigger_subscriptions:
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

    count = len(before.trigger_subscriptions)
    names = ", ".join(sorted({sub.trigger_name for sub in before.trigger_subscriptions}))
    await record_activity(
        todo_id, user_id, TodoActivityEvent.WATCH_REMOVED, f"stopped watching {names} ({reason})"
    )
    log.info("todo_subscription.torn_down", todo_id=todo_id, count=count, reason=reason)
    return count


@dataclass(frozen=True)
class AccountScope:
    """The subscriptions one account's change reaches.

    Those limited to that account, and, when the change holds for the whole
    integration, those watching every account.
    """

    account_id: str | None
    every_account: bool

    def covers(self, subscription: TriggerSubscription) -> bool:
        """Whether this change reaches the subscription."""
        if subscription.account_id is None:
            return self.every_account
        return subscription.account_id == self.account_id


async def pause_subscriptions_for_trigger_names(
    user_id: str, trigger_names: set[str], scope: AccountScope
) -> int:
    """Mark the subscriptions scope covers on trigger_names paused and flag their todos.

    Called when an account behind them loses its connection. The subscription
    keeps its stored Composio ids so the refcount still protects the trigger
    while paused, and the todo gains the blocking label the maintenance sweep
    already understands.
    """
    paused = 0
    for trigger_name in trigger_names:
        for todo in await todo_repository.find_active_by_user_and_trigger(user_id, trigger_name):
            hit = [
                s
                for s in todo.trigger_subscriptions
                if s.trigger_name == trigger_name
                and s.status is TriggerSubscriptionStatus.ACTIVE
                and scope.covers(s)
            ]
            if not hit:
                continue
            await todo_repository.pause_trigger_subscriptions(
                todo.id, user_id=user_id, subscription_ids={s.id for s in hit}
            )
            await record_activity(
                todo.id,
                user_id,
                TodoActivityEvent.WATCH_PAUSED,
                f"{trigger_name} paused: the account it watches was disconnected",
            )
            paused += 1
    if paused:
        log.info("todo_subscription.paused", user_id=user_id, todo_count=paused)
    return paused


async def resync_subscriptions_for_trigger_names(
    user_id: str, trigger_names: set[str], scope: AccountScope
) -> int:
    """Re-register the paused subscriptions scope covers after a (re)connect, and unpause them.

    A reconnect may hand them a fresh Composio connected account, so instance ids
    registered against the old one go stale. Mirrors resync_user_workflow_triggers:
    failures are logged per todo so one broken subscription cannot block the rest,
    or the OAuth flow this runs behind.
    """
    resynced = 0
    for trigger_name in trigger_names:
        handler = get_handler_by_name(trigger_name)
        if handler is None:
            continue
        for todo in await todo_repository.find_paused_by_user_and_trigger(user_id, trigger_name):
            due = {
                s.id
                for s in todo.trigger_subscriptions
                if s.trigger_name == trigger_name
                and s.status is TriggerSubscriptionStatus.PAUSED
                and scope.covers(s)
            }
            if not due:
                continue
            try:
                trigger_ids = await _reregister(
                    user_id, todo.id, [s for s in todo.trigger_subscriptions if s.id in due]
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
            await todo_repository.resume_trigger_subscriptions(
                todo.id, user_id=user_id, trigger_ids=trigger_ids
            )
            await record_activity(
                todo.id,
                user_id,
                TodoActivityEvent.WATCH_RESUMED,
                f"{trigger_name} resumed: the account it watches was reconnected",
            )
            resynced += 1
    if resynced:
        log.info("todo_subscription.resynced", user_id=user_id, todo_count=resynced)
    return resynced


async def _reregister(
    user_id: str, todo_id: str, subscriptions: list[TriggerSubscription]
) -> dict[str, list[str]]:
    """Re-register each subscription and map its id to the Composio ids it now fires on."""
    trigger_ids: dict[str, list[str]] = {}
    for subscription in subscriptions:
        new_ids = await TriggerService.register_triggers(
            user_id,
            todo_id,
            subscription.trigger_name,
            build_trigger_config(subscription.trigger_name, subscription.trigger_data),
            raise_on_failure=True,
        )
        stale = [i for i in subscription.composio_trigger_ids if i not in new_ids]
        # Account-level triggers return no ids — keep the empty list.
        trigger_ids[subscription.id] = new_ids or subscription.composio_trigger_ids
        if stale:
            await TriggerService.unregister_triggers(
                user_id, subscription.trigger_name, stale, todo_id=todo_id
            )
    return trigger_ids
