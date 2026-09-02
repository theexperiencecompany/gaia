"""Fanning a fired trigger out to subscribed todos.

The account-level case is the one that matters most: Gmail registers no Composio
instance, so a webhook arrives with a user id and no trigger id. Resolving on
trigger ids alone finds nothing there — and that is the entire reply-watching
flow, failing silently.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerOrigin,
    TriggerSubscription,
)
from app.services.triggers.subscription_dispatch import (
    dispatch_to_subscribed_todos,
)
from tests.helpers import captured_wide_event

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
        patch(f"{_MOD}.RedisPoolManager.get_pool", new_callable=AsyncMock) as get_pool,
        patch(f"{_MOD}.notification_service.create_notification", new_callable=AsyncMock) as notify,
        patch(f"{_MOD}.tracked_todo_service.complete_tracked_todo", new_callable=AsyncMock) as done,
        patch(f"{_MOD}.capture_event") as capture,
    ):
        repo.find_active_by_composio_trigger = AsyncMock(return_value=[])
        repo.find_active_by_user_and_trigger = AsyncMock(return_value=[])
        repo.update = AsyncMock(return_value=None)
        redis.redis = MagicMock(set=AsyncMock(return_value=True))
        yield SimpleNamespace(
            repo=repo,
            redis=redis,
            enqueue=enqueue,
            notify=notify,
            complete=done,
            capture=capture,
            pool=get_pool.return_value,
        )


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
        # The instance id on the wire is the lookup key; passing anything else
        # (e.g. None) finds nothing for a per-resource trigger.
        deps.repo.find_active_by_composio_trigger.assert_awaited_once_with("ti_1")
        deps.repo.find_active_by_user_and_trigger.assert_not_awaited()

    async def test_a_resource_scoped_sub_ignores_another_instances_event(self, deps) -> None:
        # Two repo-scoped subs share a trigger name but watch different Composio
        # instances. The account lookup returns both; an event from instance ti_A
        # must NOT fire the sub that only watches ti_B.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(
                        trigger_name=SLACK,
                        resolution=SubscriptionResolution.TRIGGER_ID,
                        composio_trigger_ids=["ti_B"],
                    )
                ]
            )
        ]

        assert await dispatch_to_subscribed_todos(SLACK, "ti_A", USER_ID, {}) == 0
        deps.enqueue.assert_not_awaited()

    async def test_a_resource_scoped_sub_fires_on_its_own_instances_event(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(
                        trigger_name=SLACK,
                        resolution=SubscriptionResolution.TRIGGER_ID,
                        composio_trigger_ids=["ti_B"],
                    )
                ]
            )
        ]

        assert await dispatch_to_subscribed_todos(SLACK, "ti_B", USER_ID, {}) == 1

    async def test_one_failing_subscription_does_not_strand_the_rest(self, deps) -> None:
        # A queue/notification/repository failure on one todo must not skip the
        # remaining matching todos in the same fan-out, and must surface as an
        # error on the wide event carrying every field needed to attribute it:
        # which todo, which subscription, which trigger, and the failure itself.
        deps.notify.side_effect = [RuntimeError("notify boom"), None]
        sub_a = _subscription(action=SubscriptionAction.NOTIFY)
        todo_a = _todo(id="todo-a", trigger_subscriptions=[sub_a])
        todo_b = _todo(
            id="todo-b", trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)]
        )
        deps.repo.find_active_by_user_and_trigger.return_value = [todo_a, todo_b]

        async with captured_wide_event() as event:
            fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert fired == 1  # todo-b still fired despite todo-a raising
        assert deps.notify.await_count == 2
        (error,) = event["errors"]
        assert error["msg"] == "todo_subscription.fire_failed"
        assert error["todo_id"] == "todo-a"
        assert error["subscription_id"] == sub_a.id
        assert error["trigger_name"] == GMAIL
        assert error["error"] == "notify boom"
        assert error["error_type"] == "RuntimeError"

    async def test_the_fire_failure_is_logged_with_a_traceback(self, deps) -> None:
        # exc_info is popped before the wide event's errors[] entry is built, so
        # it can never be asserted through captured_wide_event — but dropping it
        # strips the stack trace an operator needs to locate the failing seam.
        # Assert it reaches the logger as True.
        deps.notify.side_effect = RuntimeError("notify boom")
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)])
        ]

        with patch(f"{_MOD}.log") as log:
            await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        log.error.assert_called_once()
        assert log.error.call_args.kwargs["exc_info"] is True

    async def test_a_todo_found_by_both_strategies_fires_once(self, deps) -> None:
        todo = _todo()
        deps.repo.find_active_by_composio_trigger.return_value = [todo]
        deps.repo.find_active_by_user_and_trigger.return_value = [todo]

        fired = await dispatch_to_subscribed_todos(GMAIL, "ti_1", USER_ID, {"thread_id": "t-1"})

        assert fired == 1

    async def test_a_duplicate_from_one_strategy_does_not_drop_later_todos(self, deps) -> None:
        # The dedupe must SKIP the repeat and keep scanning — stopping at the
        # first duplicate would silently drop every todo behind it.
        todo_a = _todo(
            id="todo-a", trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)]
        )
        todo_b = _todo(
            id="todo-b", trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)]
        )
        deps.repo.find_active_by_composio_trigger.return_value = [todo_a]
        deps.repo.find_active_by_user_and_trigger.return_value = [todo_a, todo_b]

        # Combined order is [a, a, b]: the second `a` is the duplicate to skip.
        assert await dispatch_to_subscribed_todos(GMAIL, "ti_1", USER_ID, {}) == 2
        assert deps.notify.await_count == 2

    async def test_two_subscriptions_on_one_todo_each_fire_and_stamp_the_counts(self, deps) -> None:
        # Two firing subscriptions on one todo: `fired` must accumulate to 2, and
        # the wide event must carry one subscriber but two actions.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(action=SubscriptionAction.NOTIFY),
                    _subscription(action=SubscriptionAction.NOTIFY),
                ]
            )
        ]

        async with captured_wide_event() as event:
            fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert fired == 2
        assert event["trigger"] == {"todo_subscribers": 1, "todo_actions_fired": 2}
        assert deps.notify.await_count == 2

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

    async def test_match_any_fires_when_one_condition_holds_against_the_payload(self, deps) -> None:
        # Pins that conditions_match receives the real payload AND the match mode:
        # under ANY the matching thread_id fires it; under ALL (or a dropped
        # match arg) the failing sender would veto it.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(
                        action=SubscriptionAction.NOTIFY,
                        match=ConditionMatch.ANY,
                        conditions=[
                            SubscriptionCondition(
                                field_name="thread_id",
                                operator=ConditionOperator.EQUALS,
                                value="t-1",
                            ),
                            SubscriptionCondition(
                                field_name="sender",
                                operator=ConditionOperator.EQUALS,
                                value="never@example.com",
                            ),
                        ],
                    )
                ]
            )
        ]

        fired = await dispatch_to_subscribed_todos(
            GMAIL, None, USER_ID, {"thread_id": "t-1", "sender": "real@acme.com"}
        )
        assert fired == 1

    async def test_a_held_cooldown_suppresses_the_repeat(self, deps) -> None:
        deps.redis.redis.set = AsyncMock(return_value=None)  # NX lost the race
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0
        deps.enqueue.assert_not_awaited()

    async def test_the_cooldown_is_claimed_with_set_if_absent(self, deps) -> None:
        # Read-then-write would let two events in the same second both through.
        sub = _subscription(cooldown_seconds=900)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        call = deps.redis.redis.set.await_args
        assert call.args[0] == f"todo_subscription_cooldown:{sub.id}"
        assert call.args[1] == "1"
        assert call.kwargs["nx"] is True
        assert call.kwargs["ex"] == 900

    async def test_a_zero_cooldown_never_touches_redis(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(cooldown_seconds=0)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 1
        deps.redis.redis.set.assert_not_awaited()

    async def test_a_positive_cooldown_does_claim_the_slot(self, deps) -> None:
        # The guard is `<= 0`: a one-second cooldown must still reach Redis, or a
        # duplicate in that second is never suppressed.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(cooldown_seconds=1)])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})
        assert deps.redis.redis.set.await_args.kwargs["ex"] == 1

    async def test_redis_down_fires_and_records_the_warning(self, deps) -> None:
        # A duplicate action is recoverable; a missed reply-watch is the failure
        # this whole feature exists to prevent — but the degradation must be
        # visible on the wide event, not silent.
        deps.redis.redis = None
        sub = _subscription()
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        async with captured_wide_event() as event:
            fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert fired == 1
        (warning,) = event["warnings"]
        assert warning["msg"] == "todo_subscription.cooldown_unavailable"
        assert warning["subscription_id"] == sub.id

    async def test_a_redis_error_fires_and_records_the_error(self, deps) -> None:
        # The set can raise mid-flight (connection dropped); the same fire-rather-
        # than-suppress rule holds, and the error surfaces on the wide event.
        deps.redis.redis.set = AsyncMock(side_effect=RedisError("connection reset"))
        sub = _subscription()
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        async with captured_wide_event() as event:
            fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert fired == 1
        (warning,) = event["warnings"]
        assert warning["msg"] == "todo_subscription.cooldown_unavailable"
        assert warning["subscription_id"] == sub.id
        assert warning["error"] == "connection reset"
        assert warning["error_type"] == "RedisError"


class TestActions:
    async def test_the_fire_is_stamped_onto_the_wide_event(self, deps) -> None:
        # Every field the action is dispatched under must land on the event, so a
        # fired subscription is attributable after the fact.
        sub = _subscription(action=SubscriptionAction.EXECUTE)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        async with captured_wide_event() as event:
            await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert event["component"] == "trigger_subscription"
        assert event["operation"] == "fire"
        assert event["todo_id"] == TODO_ID
        assert event["subscription_id"] == sub.id
        assert event["trigger_name"] == GMAIL
        assert event["subscription_action"] == "execute"

    async def test_execute_enqueues_with_the_origin_and_payload(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]
        payload = {"thread_id": "t-1", "sender": "alice@acme.com"}

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, payload)

        args = deps.enqueue.await_args.args
        # arg[0] is the live pool, not None — enqueueing against None loses the job.
        assert args[0] is deps.pool
        assert args[1] == "execute_tracked_todo"
        assert args[2] == TODO_ID
        origin = args[3]
        assert isinstance(origin, TriggerOrigin)
        assert origin.trigger_name == GMAIL
        assert origin.payload == payload
        assert origin.defer_attempts == 0

    async def test_notify_sends_a_deep_link_and_changes_nothing(self, deps) -> None:
        sub = _subscription(action=SubscriptionAction.NOTIFY)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        request = deps.notify.await_args.args[0]
        assert request.user_id == USER_ID
        assert request.source == NotificationSourceEnum.TODO_TRIGGER
        assert request.type == NotificationType.INFO
        assert request.content.title == "Update on: Chase Acme"
        assert request.content.body == f"An event you were watching ({GMAIL}) just fired."
        assert request.content.actions[0].label == "View todo"
        assert request.content.actions[0].config.redirect.url == f"/todos?todoId={TODO_ID}"
        assert request.metadata == {"todo_id": TODO_ID, "subscription_id": sub.id}
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
        assert (
            deps.complete.await_args.kwargs["summary"] == f"Completed automatically: {GMAIL} fired."
        )

    async def test_unblock_removes_only_the_blocking_labels(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                labels=["gaia-tracked", "waiting-for-reply", "work"],
                trigger_subscriptions=[_subscription(action=SubscriptionAction.UNBLOCK)],
            )
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        call = deps.repo.update.await_args
        assert call.args[0] == TODO_ID
        assert call.kwargs["user_id"] == USER_ID
        assert call.kwargs["update"].labels == ["gaia-tracked", "work"]
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


class TestAnalytics:
    """The webhook path has no request context, so the id must be explicit.

    Getting it wrong is silent: the event still lands, just on a fresh anonymous
    profile, so it never shows up in that user's funnel and nothing goes red.
    """

    async def test_a_fire_is_attributed_to_the_todos_owner(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        deps.capture.assert_called_once()
        assert deps.capture.call_args.args[0] == USER_ID
        assert deps.capture.call_args.args[1] == "todos:trigger_fired"

    async def test_the_event_carries_shape_not_content(self, deps) -> None:
        # Counts and enums only: no subject lines, no addresses, no payload.
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        await dispatch_to_subscribed_todos(
            GMAIL, None, USER_ID, {"subject": "Invoice 4021", "sender": "a@b.c"}
        )

        props = deps.capture.call_args.args[2]
        assert props == {
            "trigger_name": GMAIL,
            "action": "execute",
            "resolution": "account",
            "condition_count": 0,
        }

    async def test_a_suppressed_fire_is_not_counted(self, deps) -> None:
        # Counting arrivals rather than actions would make every funnel read high.
        deps.redis.redis.set = AsyncMock(return_value=None)
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        deps.capture.assert_not_called()

    async def test_a_non_matching_event_is_not_counted(self, deps) -> None:
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

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {"thread_id": "t-2"})

        deps.capture.assert_not_called()
