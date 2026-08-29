"""Fanning a fired trigger out to subscribed todos.

The account-level case is the one that matters most: Gmail registers no Composio
instance, so a webhook arrives with a user id and no trigger id. Resolving on
trigger ids alone finds nothing there — and that is the entire reply-watching
flow, failing silently.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerOrigin,
    TriggerSubscription,
)
from app.services.triggers.subscription_dispatch import dispatch_to_subscribed_todos

pytestmark = pytest.mark.unit

_MOD = "app.services.triggers.subscription_dispatch"
USER_ID = "user-1"
TODO_ID = "todo-1"
GMAIL = "gmail_new_message"
SLACK = "slack_new_message"


def _subscription(**overrides: object) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "trigger_name": GMAIL,
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.ACCOUNT,
            **overrides,
        }
    )


def _todo(**overrides: object) -> TodoDocument:
    return TodoDocument.model_validate(
        {
            "id": TODO_ID,
            "user_id": USER_ID,
            "title": "Chase Acme",
            "trigger_subscriptions": [_subscription()],
            **overrides,
        }
    )


@pytest.fixture
def deps():
    """Patch the seams dispatch writes through; condition matching stays real."""
    with (
        patch(f"{_MOD}.todo_repository") as repo,
        patch(f"{_MOD}.redis_cache") as redis,
        patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue,
        patch(f"{_MOD}.RedisPoolManager.get_pool", new_callable=AsyncMock),
        patch(f"{_MOD}.notification_service.create_notification", new_callable=AsyncMock) as notify,
        patch(f"{_MOD}.tracked_todo_service.complete_tracked_todo", new_callable=AsyncMock) as done,
    ):
        repo.find_active_by_composio_trigger = AsyncMock(return_value=[])
        repo.find_active_by_user_and_trigger = AsyncMock(return_value=[])
        repo.update = AsyncMock(return_value=None)
        redis.redis = MagicMock(set=AsyncMock(return_value=True))
        yield SimpleNamespace(repo=repo, redis=redis, enqueue=enqueue, notify=notify, complete=done)


class TestResolution:
    async def test_account_level_event_resolves_by_user_and_trigger(self, deps) -> None:
        # No trigger id on the wire — the whole Gmail case.
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {"thread_id": "t-1"})

        assert fired == 1
        deps.repo.find_active_by_user_and_trigger.assert_awaited_once_with(USER_ID, GMAIL)
        deps.repo.find_active_by_composio_trigger.assert_not_awaited()

    async def test_per_resource_event_resolves_by_trigger_id_without_a_user(self, deps) -> None:
        # Poll webhooks frequently arrive with no user id; gating on one drops them.
        deps.repo.find_active_by_composio_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(
                        trigger_name=SLACK,
                        resolution=SubscriptionResolution.TRIGGER_ID,
                        composio_trigger_ids=["ti_1"],
                    )
                ]
            )
        ]

        fired = await dispatch_to_subscribed_todos(SLACK, "ti_1", None, {"channel": "C1"})

        assert fired == 1
        deps.repo.find_active_by_user_and_trigger.assert_not_awaited()

    async def test_a_todo_found_by_both_strategies_fires_once(self, deps) -> None:
        todo = _todo()
        deps.repo.find_active_by_composio_trigger.return_value = [todo]
        deps.repo.find_active_by_user_and_trigger.return_value = [todo]

        fired = await dispatch_to_subscribed_todos(GMAIL, "ti_1", USER_ID, {"thread_id": "t-1"})

        assert fired == 1

    async def test_no_subscribers_is_a_clean_zero(self, deps) -> None:
        assert await dispatch_to_subscribed_todos(GMAIL, "ti_1", USER_ID, {}) == 0
        deps.enqueue.assert_not_awaited()


class TestGating:
    async def test_a_subscription_for_another_trigger_does_not_fire(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(trigger_name=SLACK)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0

    async def test_a_paused_subscription_does_not_fire(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(status=SubscriptionStatus.PAUSED)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0

    async def test_failing_conditions_do_not_fire(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(
                        conditions=[
                            SubscriptionCondition(
                                field_name="thread_id",
                                operator=ConditionOperator.EQUALS,
                                value="t-1",
                            )
                        ]
                    )
                ]
            )
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {"thread_id": "t-2"}) == 0

    async def test_a_held_cooldown_suppresses_the_repeat(self, deps) -> None:
        deps.redis.redis.set = AsyncMock(return_value=None)  # NX lost the race
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0
        deps.enqueue.assert_not_awaited()

    async def test_the_cooldown_is_claimed_with_set_if_absent(self, deps) -> None:
        # Read-then-write would let two events in the same second both through.
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert deps.redis.redis.set.await_args.kwargs["nx"] is True

    async def test_a_zero_cooldown_never_touches_redis(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(cooldown_seconds=0)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 1
        deps.redis.redis.set.assert_not_awaited()

    async def test_redis_down_fires_rather_than_suppresses(self, deps) -> None:
        # A duplicate action is recoverable; a missed reply-watch is the failure
        # this whole feature exists to prevent.
        deps.redis.redis = None
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 1


class TestActions:
    async def test_execute_enqueues_with_the_origin_and_payload(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]
        payload = {"thread_id": "t-1", "sender": "alice@acme.com"}

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, payload)

        args = deps.enqueue.await_args.args
        assert args[1] == "execute_tracked_todo"
        assert args[2] == TODO_ID
        origin = args[3]
        assert isinstance(origin, TriggerOrigin)
        assert origin.trigger_name == GMAIL
        assert origin.payload == payload
        assert origin.defer_attempts == 0

    async def test_notify_sends_a_deep_link_and_changes_nothing(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        request = deps.notify.await_args.args[0]
        assert request.user_id == USER_ID
        assert request.content.actions[0].config.redirect.url == f"/todos?todoId={TODO_ID}"
        deps.enqueue.assert_not_awaited()
        deps.repo.update.assert_not_awaited()

    async def test_complete_goes_through_the_idempotent_completion_path(self, deps) -> None:
        # Not a direct repository write: completion also archives the canvas and
        # tears the subscriptions down, and skipping that leaks the trigger.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.COMPLETE)])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        deps.complete.assert_awaited_once()
        assert deps.complete.await_args.args[:2] == (TODO_ID, USER_ID)

    async def test_unblock_removes_only_the_blocking_labels(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                labels=["gaia-tracked", "waiting-for-reply", "work"],
                trigger_subscriptions=[_subscription(action=SubscriptionAction.UNBLOCK)],
            )
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        update = deps.repo.update.await_args.kwargs["update"]
        assert update.labels == ["gaia-tracked", "work"]
        deps.notify.assert_not_awaited()

    async def test_unblock_with_no_blocking_label_degrades_to_notify(self, deps) -> None:
        # Silently doing nothing would look identical to the subscription never
        # having fired at all.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                labels=["gaia-tracked"],
                trigger_subscriptions=[_subscription(action=SubscriptionAction.UNBLOCK)],
            )
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        deps.notify.assert_awaited_once()
        deps.repo.update.assert_not_awaited()
