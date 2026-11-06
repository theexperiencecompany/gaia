"""Fanning a fired trigger out to subscribed todos.

The account-level case is the one that matters most: Gmail registers no Composio
instance, so a webhook arrives with a user id and no trigger id. Resolving on
trigger ids alone finds nothing there — and that is the entire reply-watching
flow, failing silently.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from redis.exceptions import RedisError
import respx
import time_machine

from app.constants.todos import TodoActivityEvent
from app.constants.trigger_gates import GateAuthor
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.trigger_gate_models import AuthoredGate
from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerOrigin,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.triggers.subscription_dispatch import (
    dispatch_to_subscribed_todos,
    fire_subscription,
)
from app.services.triggers.todo_trigger_window import TODO_TRIGGER_WINDOW_CLAIMED
from app.utils.timezone import Timezone
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.catalog.todos import TodosTriggerFired
from shared.py.analytics.context import (
    AnalyticsContext,
    current_analytics_context,
    worker_context,
)
from tests.helpers import captured_wide_event, trigger_gate_seams

_DISPATCH = "app.services.triggers.subscription_dispatch"

pytestmark = pytest.mark.unit

_MOD = "app.services.triggers.subscription_dispatch"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
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
        patch(f"{_MOD}.capture") as capture,
        patch(f"{_MOD}.record_activity", new_callable=AsyncMock) as activity,
        patch(f"{_MOD}.buffer_todo_trigger_event", new_callable=AsyncMock) as hold,
        patch(f"{_MOD}.buffer_todo_trigger_event_until", new_callable=AsyncMock) as hold_until,
    ):
        repo.find_active_by_composio_trigger = AsyncMock(return_value=[])
        repo.find_active_by_user_and_trigger = AsyncMock(return_value=[])
        repo.update = AsyncMock(return_value=None)
        redis.redis = MagicMock(set=AsyncMock(return_value=True))
        hold.return_value = True
        hold_until.return_value = True
        yield SimpleNamespace(
            hold_until=hold_until,
            repo=repo,
            redis=redis,
            enqueue=enqueue,
            notify=notify,
            complete=done,
            capture=capture,
            pool=get_pool.return_value,
            activity=activity,
            hold=hold,
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
        # A failure on one todo must not skip the rest of the fan-out, and must surface as a wide-event
        # error carrying which todo, which subscription, which trigger, and the failure itself.
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
        # exc_info is popped before the wide event's errors[] entry is built, so it can't be asserted through
        # captured_wide_event; assert it reaches the logger as True instead, or the stack trace is lost.
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
            _todo(trigger_subscriptions=[_subscription(status=TriggerSubscriptionStatus.PAUSED)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0

    @pytest.mark.parametrize(
        ("event_account", "fired"),
        [("acct_work", 1), ("acct_home", 0), (None, 0)],
        ids=["its_account", "another_account", "no_account"],
    )
    async def test_a_watch_on_one_account_fires_only_for_that_accounts_events(
        self, deps, event_account: str | None, fired: int
    ) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(action=SubscriptionAction.NOTIFY, account_id="acct_work")
                ]
            )
        ]
        payload: dict[str, object] = {"gaia_account_id": event_account} if event_account else {}

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, payload) == fired

    async def test_a_watch_on_every_account_fires_for_any_of_them(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)])
        ]

        payload: dict[str, object] = {"gaia_account_id": "acct_home"}
        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, payload) == 1

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
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0
        deps.notify.assert_not_awaited()

    async def test_a_held_trigger_window_holds_the_repeat_for_the_next_run(self, deps) -> None:
        """A second reply inside the window used to be dropped; it must ride the todo's next run."""
        deps.redis.redis.set = AsyncMock(return_value=None)  # the window is already open
        sub = _subscription()
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]
        payload: dict[str, object] = {"thread_id": "t-1", "message_id": "m-2"}

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, payload) == 1

        deps.hold.assert_awaited_once_with(
            TODO_ID, TriggerOrigin(subscription_id=sub.id, trigger_name=GMAIL, payload=payload)
        )
        deps.enqueue.assert_not_awaited()
        detail = deps.activity.await_args.args[3]
        assert detail == f"{GMAIL} matched; action: execute; held for the todo's next run"

    async def test_a_repeat_that_cannot_be_held_runs_now_rather_than_vanish(self, deps) -> None:
        deps.redis.redis.set = AsyncMock(return_value=None)
        deps.hold.return_value = False
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 1
        assert deps.enqueue.await_args.args[1:3] == ("execute_tracked_todo", TODO_ID)

    async def test_execute_claims_the_todos_trigger_window(self, deps) -> None:
        # One window per todo, so its subscriptions share one run per window.
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                trigger_subscriptions=[
                    _subscription(cooldown_seconds=300),
                    _subscription(trigger_name=SLACK, cooldown_seconds=900),
                ]
            )
        ]
        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        call = deps.redis.redis.set.await_args
        assert call.args[0] == f"todo_trigger_window:{TODO_ID}"
        # A claim, not an end: only the run, once it starts, says when its window ends.
        assert call.args[1] == TODO_TRIGGER_WINDOW_CLAIMED
        assert call.kwargs["nx"] is True
        assert call.kwargs["ex"] == 900
        deps.hold.assert_not_awaited()

    async def test_the_cooldown_is_claimed_with_set_if_absent(self, deps) -> None:
        # Read-then-write would let two events in the same second both through.
        sub = _subscription(action=SubscriptionAction.NOTIFY, cooldown_seconds=900)
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

    @pytest.mark.parametrize("action", [SubscriptionAction.EXECUTE, SubscriptionAction.NOTIFY])
    async def test_redis_down_fires_and_records_the_warning(
        self, deps, action: SubscriptionAction
    ) -> None:
        # A duplicate action is recoverable; a missed reply-watch is the failure
        # this whole feature exists to prevent — but the degradation must be
        # visible on the wide event, not silent.
        deps.redis.redis = None
        sub = _subscription(action=action)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        async with captured_wide_event() as event:
            fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert fired == 1
        (warning,) = event["warnings"]
        assert warning["msg"] == "todo_subscription.cooldown_unavailable"
        assert warning["subscription_id"] == sub.id

    @pytest.mark.parametrize("action", [SubscriptionAction.EXECUTE, SubscriptionAction.NOTIFY])
    async def test_a_redis_error_fires_and_records_the_error(
        self, deps, action: SubscriptionAction
    ) -> None:
        # The set can raise mid-flight (connection dropped); the same fire-rather-
        # than-suppress rule holds, and the error surfaces on the wide event.
        deps.redis.redis.set = AsyncMock(side_effect=RedisError("connection reset"))
        sub = _subscription(action=action)
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
    async def test_a_fire_is_on_the_todos_timeline(self, deps) -> None:
        sub = _subscription()
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        todo_id, user_id, event, detail = deps.activity.await_args.args
        assert (todo_id, user_id, event) == (TODO_ID, USER_ID, TodoActivityEvent.TRIGGER_FIRED)
        assert detail == f"{GMAIL} matched; action: {sub.action.value}"

    async def test_an_action_that_fails_is_on_the_timeline_after_the_fire(self, deps) -> None:
        """Regression: a failed action left only "trigger_fired", reading as if it had run."""
        sub = _subscription(action=SubscriptionAction.NOTIFY)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]
        deps.notify.side_effect = RuntimeError("push service down")

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {}) == 0

        assert [c.args for c in deps.activity.await_args_list] == [
            (TODO_ID, USER_ID, TodoActivityEvent.TRIGGER_FIRED, f"{GMAIL} matched; action: notify"),
            (
                TODO_ID,
                USER_ID,
                TodoActivityEvent.TRIGGER_ACTION_FAILED,
                "notify failed: RuntimeError",
            ),
        ]

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
        payload: dict[str, object] = {"thread_id": "t-1", "sender": "alice@acme.com"}

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
        assert deps.capture.call_args.args[0] == UserId(USER_ID)
        assert isinstance(deps.capture.call_args.args[1], TodosTriggerFired)

    async def test_the_event_carries_shape_not_content(self, deps) -> None:
        # Counts and enums only: no subject lines, no addresses, no payload.
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        await dispatch_to_subscribed_todos(
            GMAIL, None, USER_ID, {"subject": "Invoice 4021", "sender": "a@b.c"}
        )

        assert deps.capture.call_args.args[1] == TodosTriggerFired(
            trigger_name=GMAIL,
            action="execute",
            resolution="account",
            condition_count=0,
            coalesced=False,
        )

    async def test_a_suppressed_fire_is_not_counted(self, deps) -> None:
        # Counting arrivals rather than actions would make every funnel read high.
        deps.redis.redis.set = AsyncMock(return_value=None)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        deps.capture.assert_not_called()

    async def test_a_notify_fire_is_never_counted_as_coalesced(self, deps) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(action=SubscriptionAction.NOTIFY)])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert deps.capture.call_args.args[1].coalesced is False

    async def test_a_held_execute_fire_is_counted_as_coalesced(self, deps) -> None:
        # It will run, with the todo's next run, so it is a fire, marked as held.
        deps.redis.redis.set = AsyncMock(return_value=None)
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert deps.capture.call_args.args[1].coalesced is True

    async def test_a_direct_fire_is_counted_as_not_coalesced(self, deps) -> None:
        subscription = _subscription(action=SubscriptionAction.NOTIFY)

        await fire_subscription(_todo(trigger_subscriptions=[subscription]), subscription, {})

        assert deps.capture.call_args.args[1] == TodosTriggerFired(
            trigger_name=GMAIL,
            action="notify",
            resolution="account",
            condition_count=0,
            coalesced=False,
        )

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


class TestDispatchAttribution:
    async def test_the_fan_out_is_integration_triggered_agent_work(self) -> None:
        """Whatever request delivered the webhook, the todos it wakes are the trigger's."""
        seen: list[AnalyticsContext] = []

        async def _record(*_args: object) -> list[TodoDocument]:
            seen.append(current_analytics_context())
            return []

        with patch(f"{_DISPATCH}._resolve_subscribers", _record):
            await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, {})

        assert seen == [worker_context(Trigger.INTEGRATION_TRIGGER)]


CONDITION = "the reply is from Acme about the pilot"
KOLKATA = Timezone.parse("Asia/Kolkata")
# 02:30 on the user's clock in Kolkata; their quiet hours end at 08:00.
NIGHT = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
MORNING = datetime(2026, 10, 2, 8, 0, tzinfo=KOLKATA.tzinfo)
MEETING = "someone is waiting on you for a meeting happening soon"
_GATE = AuthoredGate(condition=CONDITION, author=GateAuthor.GAIA)
# A first message on its own thread: the only Gmail mail a gate asks JEV about.
_NEW_THREAD: dict[str, object] = {"thread_id": "m-1", "message_id": "m-1", "subject": "Sale!"}


def _gate_answer(not_needed: float) -> dict[str, object]:
    return {
        "type": "choice",
        "choice": "not_needed" if not_needed >= 0.5 else "needed",
        "confidence": max(not_needed, 1 - not_needed),
        "probabilities": {"not_needed": not_needed, "needed": 1 - not_needed},
    }


def _jev_body(not_needed: float) -> dict[str, object]:
    return {"answers": {"gate": _gate_answer(not_needed)}}


@pytest.fixture
def jev() -> Iterator[respx.Route]:
    with trigger_gate_seams(KOLKATA, now=datetime(2026, 10, 2, 9, 0, tzinfo=UTC)) as gate:
        yield gate.jev


class TestTriggerGate:
    async def test_a_skip_runs_nothing_claims_no_window_and_says_why(
        self, deps, jev: respx.Route
    ) -> None:
        jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))
        subscription = _subscription(gate=_GATE)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[subscription])
        ]

        async with captured_wide_event() as event:
            fired = await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD))

        assert fired == 0
        deps.enqueue.assert_not_awaited()
        deps.hold.assert_not_awaited()
        # No window slot taken: the next real event must still wake the todo at once.
        deps.redis.redis.set.assert_not_awaited()
        deps.activity.assert_awaited_once_with(
            TODO_ID,
            USER_ID,
            TodoActivityEvent.RUN_SKIPPED,
            f'Skipped: "Sale!". Not a match for "{CONDITION}" (99% sure).',
        )
        assert list(event["trigger_gate"]) == [subscription.id]

    @pytest.mark.parametrize(
        "response",
        [httpx.Response(200, json=_jev_body(0.94)), httpx.Response(503, text="down")],
        ids=["unsure", "jev-down"],
    )
    async def test_an_unsure_or_failing_gate_runs_as_today(
        self, deps, jev: respx.Route, response: httpx.Response
    ) -> None:
        jev.mock(return_value=response)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(gate=_GATE)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD)) == 1
        deps.enqueue.assert_awaited_once()

    async def test_the_gate_reads_the_todo_as_its_job(self, deps, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_jev_body(0.1)))
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(
                description="Reply to Acme about the pilot",
                trigger_subscriptions=[_subscription(gate=_GATE)],
            )
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD))

        body = json.loads(jev.calls.last.request.content)
        assert body["state"]["automation"] == "Chase Acme: Reply to Acme about the pilot"

    async def test_conditions_still_decide_first(self, deps, jev: respx.Route) -> None:
        sub = _subscription(
            gate=_GATE,
            conditions=[
                SubscriptionCondition(
                    field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-9"
                )
            ],
        )
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD)) == 0
        assert not jev.called


def _night_body(*, can_wait: float, not_needed: float = 0.1) -> dict[str, object]:
    """Answer both questions; what is not can_wait leans to a meeting."""
    urgent = {"incident": 0.0, "service_down": 0.0, "meeting": 1 - can_wait, "can_wait": can_wait}
    return {
        "answers": {
            "gate": _gate_answer(not_needed),
            "urgent": {"type": "choice", "choice": "can_wait", "probabilities": urgent},
        }
    }


@pytest.fixture
def night(jev: respx.Route) -> Iterator[respx.Route]:
    with time_machine.travel(NIGHT, tick=False):
        yield jev


class TestQuietHours:
    async def test_a_held_event_waits_for_the_morning_and_claims_no_window(
        self, deps, night: respx.Route
    ) -> None:
        night.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(gate=_GATE)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD)) == 1

        deps.enqueue.assert_not_awaited()
        deps.redis.redis.set.assert_not_awaited()
        todo_id, origin, until = deps.hold_until.await_args.args
        assert (todo_id, until) == (TODO_ID, MORNING)
        assert origin.payload == _NEW_THREAD
        event, detail = deps.activity.await_args.args[2:]
        assert event is TodoActivityEvent.TRIGGER_FIRED
        assert detail.endswith("; held until your quiet hours end")

    async def test_a_held_event_that_cannot_be_kept_runs_rather_than_drop(
        self, deps, night: respx.Route
    ) -> None:
        night.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))
        deps.hold_until.return_value = False
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(gate=_GATE)])
        ]

        await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD))

        deps.enqueue.assert_awaited_once()

    async def test_an_urgent_event_runs_now_carrying_why(self, deps, night: respx.Route) -> None:
        night.mock(return_value=httpx.Response(200, json=_night_body(can_wait=0.0)))
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(gate=_GATE)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD)) == 1

        # Not held behind the todo's window: an urgent email runs at once.
        deps.redis.redis.set.assert_not_awaited()
        deps.hold.assert_not_awaited()
        origin = deps.enqueue.await_args.args[3]
        assert isinstance(origin, TriggerOrigin)
        assert origin.quiet_hours_bypass is not None
        assert origin.quiet_hours_bypass.reason == MEETING
        _, detail = deps.activity.await_args.args[2:]
        assert detail.endswith(f". Ran during quiet hours: {MEETING}")

    async def test_a_confident_skip_at_night_still_skips(self, deps, night: respx.Route) -> None:
        body = _night_body(can_wait=1.0, not_needed=0.99)
        night.mock(return_value=httpx.Response(200, json=body))
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[_subscription(gate=_GATE)])
        ]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD)) == 0
        deps.enqueue.assert_not_awaited()
        deps.hold_until.assert_not_awaited()

    async def test_an_ungated_watch_runs_at_night_as_by_day(self, deps, night: respx.Route) -> None:
        deps.repo.find_active_by_user_and_trigger.return_value = [_todo()]

        assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, dict(_NEW_THREAD)) == 1

        assert not night.called
        deps.enqueue.assert_awaited_once()
        deps.hold_until.assert_not_awaited()

    @pytest.mark.parametrize(
        ("conditions", "external_ref"),
        [
            (
                [
                    SubscriptionCondition(
                        field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-9"
                    )
                ],
                None,
            ),
            ([], ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="t-9")),
        ],
        ids=["pinned-by-condition", "the-todos-own-thread"],
    )
    async def test_a_reply_on_a_thread_the_todo_tracks_runs_without_asking(
        self,
        deps,
        jev: respx.Route,
        conditions: list[SubscriptionCondition],
        external_ref: ExternalRef | None,
    ) -> None:
        sub = _subscription(gate=_GATE, conditions=conditions)
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub], external_ref=external_ref)
        ]
        reply: dict[str, object] = {"thread_id": "t-9", "message_id": "m-2", "subject": "Re: pilot"}

        wrote = AsyncMock(return_value=False)
        with patch("app.services.triggers.trigger_gate.user_wrote_in_thread", wrote):
            async with captured_wide_event() as event:
                assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, reply) == 1

        wrote.assert_not_awaited()
        assert not jev.called
        assert event["trigger_gate"][sub.id]["reason"] == "free_run"

    async def test_a_condition_on_another_field_does_not_track_the_thread(
        self, deps, jev: respx.Route
    ) -> None:
        jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))
        # Only thread_id equals tracks a thread: not another field holding its id, nor not_equals.
        on_subject = SubscriptionCondition(
            field_name="subject", operator=ConditionOperator.EQUALS, value="t-8"
        )
        not_this_thread = SubscriptionCondition(
            field_name="thread_id", operator=ConditionOperator.NOT_EQUALS, value="t-9"
        )
        sub = _subscription(gate=_GATE, conditions=[on_subject, not_this_thread])
        deps.repo.find_active_by_user_and_trigger.return_value = [
            _todo(trigger_subscriptions=[sub])
        ]
        reply: dict[str, object] = {"thread_id": "t-8", "message_id": "m-2", "subject": "t-8"}

        wrote = AsyncMock(return_value=False)
        with patch("app.services.triggers.trigger_gate.user_wrote_in_thread", wrote):
            assert await dispatch_to_subscribed_todos(GMAIL, None, USER_ID, reply) == 0

        assert jev.called
