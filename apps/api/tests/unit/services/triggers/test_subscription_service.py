"""Registration and teardown of a todo's trigger subscriptions.

The two registration shapes are the point: Gmail is account-level and returns no
Composio instance id, which is success; a per-resource trigger returning none
registered nothing and would be a watch that silently never fires. The real
handler registry is used rather than a mock, because which shape a trigger has is
exactly what these tests are asserting.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.constants.todos import BLOCKING_LABEL
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerSubscription,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.triggers.subscription_service import (
    SubscriptionError,
    build_trigger_config,
    register_subscription,
    resync_subscriptions_for_trigger_names,
    teardown_subscriptions,
)
from app.services.triggers.subscription_validation import validate_conditions
from app.utils.exceptions import TriggerRegistrationError
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

USER_ID = "user-1"
TODO_ID = "todo-1"
ACCOUNT_TRIGGER = "gmail_new_message"
INSTANCE_TRIGGER = "slack_new_message"


def _todo(**overrides: object) -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": TODO_ID, "user_id": USER_ID, "title": "Chase Acme", **overrides}
    )


def _subscription(**overrides: object) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "trigger_name": INSTANCE_TRIGGER,
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.TRIGGER_ID,
            "composio_trigger_ids": ["ti_1"],
            **overrides,
        }
    )


class _Harness:
    """Patches the two collaborators registration touches, and records the write."""

    def __init__(self, todo: TodoDocument | None, trigger_ids: list[str] | Exception):
        self.todo = todo
        self.trigger_ids = trigger_ids
        self.get = AsyncMock(return_value=todo)
        self.register = AsyncMock()
        self.unregister = AsyncMock(return_value=True)
        self.update = AsyncMock(return_value=None)
        self.capture = Mock()

    def __enter__(self) -> "_Harness":
        if isinstance(self.trigger_ids, Exception):
            self.register.side_effect = self.trigger_ids
        else:
            self.register.return_value = self.trigger_ids
        self._repo = patch(
            "app.services.triggers.subscription_service.todo_repository",
            get=self.get,
            update=self.update,
        )
        self._svc = patch(
            "app.services.triggers.subscription_service.TriggerService",
            register_triggers=self.register,
            unregister_triggers=self.unregister,
        )
        self._analytics = patch(
            "app.services.triggers.subscription_service.capture_event", self.capture
        )
        self._repo.start()
        self._svc.start()
        self._analytics.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._analytics.stop()
        self._svc.stop()
        self._repo.stop()

    @property
    def written_subscriptions(self) -> list[TriggerSubscription]:
        return self.update.await_args.kwargs["update"].trigger_subscriptions


class TestRegisterSubscription:
    async def test_account_level_trigger_stores_with_no_instance_ids(self) -> None:
        # Gmail's register() returns [] by design. Treating that as a failure
        # would make the whole reply-watching flow impossible.
        with _Harness(_todo(), []) as h:
            subscription, outcome = await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=ACCOUNT_TRIGGER,
                conditions=[
                    SubscriptionCondition(
                        field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-1"
                    )
                ],
                action=SubscriptionAction.EXECUTE,
            )

        assert outcome.ok
        assert subscription.resolution is SubscriptionResolution.ACCOUNT
        assert subscription.composio_trigger_ids == []
        assert h.written_subscriptions == [subscription]

    async def test_per_resource_trigger_stores_its_instance_ids(self) -> None:
        with _Harness(_todo(), ["ti_9"]) as h:
            subscription, _ = await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=INSTANCE_TRIGGER,
                conditions=[],
                action=SubscriptionAction.NOTIFY,
            )

        assert subscription.resolution is SubscriptionResolution.TRIGGER_ID
        assert subscription.composio_trigger_ids == ["ti_9"]
        assert h.written_subscriptions[0].action is SubscriptionAction.NOTIFY

    async def test_per_resource_trigger_with_no_instance_is_rejected(self) -> None:
        # Nothing was registered, so the subscription could never fire. Storing it
        # would be a watch that does nothing, forever, silently.
        with _Harness(_todo(), []) as h:
            with pytest.raises(SubscriptionError) as excinfo:
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name=INSTANCE_TRIGGER,
                    conditions=[],
                    action=SubscriptionAction.EXECUTE,
                )
        assert str(excinfo.value) == (
            f"Registering '{INSTANCE_TRIGGER}' returned no trigger instance, so the "
            "subscription would never fire. Check the trigger configuration."
        )
        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": INSTANCE_TRIGGER, "reason": "no_trigger_instance"},
        )

    async def test_conditions_are_stored_repaired(self) -> None:
        with _Harness(_todo(), []) as h:
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=ACCOUNT_TRIGGER,
                conditions=[
                    SubscriptionCondition(
                        field_name="threadId", operator=ConditionOperator.EQUALS, value="t-1"
                    )
                ],
                action=SubscriptionAction.EXECUTE,
            )

        assert h.written_subscriptions[0].conditions[0].field_name == "thread_id"

    async def test_appends_to_existing_subscriptions(self) -> None:
        existing = _subscription()
        with _Harness(_todo(trigger_subscriptions=[existing]), []) as h:
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=ACCOUNT_TRIGGER,
                conditions=[],
                action=SubscriptionAction.EXECUTE,
            )

        assert len(h.written_subscriptions) == 2
        assert h.written_subscriptions[0].id == existing.id

    async def test_register_stamps_the_wide_event(self) -> None:
        # A watch registered under the wrong operation/component/ids cannot be
        # found in the wide event when it later misbehaves.
        with _Harness(_todo(), ["ti_9"]):
            async with captured_wide_event() as event:
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name=INSTANCE_TRIGGER,
                    conditions=[],
                    action=SubscriptionAction.EXECUTE,
                )

        assert event["component"] == "trigger_subscription"
        assert event["operation"] == "register"
        assert event["user_id"] == USER_ID
        assert event["todo_id"] == TODO_ID
        assert event["trigger_name"] == INSTANCE_TRIGGER

    async def test_register_captures_the_registered_analytics_event(self) -> None:
        # A camelCased field is repaired, so repaired must read True; the funnel
        # needs the real action/resolution/cooldown, not a fresh anonymous event.
        with _Harness(_todo(), []) as h:
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=ACCOUNT_TRIGGER,
                conditions=[
                    SubscriptionCondition(
                        field_name="threadId", operator=ConditionOperator.EQUALS, value="t-1"
                    )
                ],
                action=SubscriptionAction.NOTIFY,
                cooldown_seconds=1234,
            )

        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_REGISTERED,
            {
                "trigger_name": ACCOUNT_TRIGGER,
                "action": "notify",
                "resolution": "account",
                "condition_count": 1,
                "repaired": True,
                "cooldown_seconds": 1234,
            },
        )

    async def test_register_calls_composio_with_the_todos_identity(self) -> None:
        with _Harness(_todo(), ["ti_9"]) as h:
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=INSTANCE_TRIGGER,
                conditions=[],
                action=SubscriptionAction.EXECUTE,
            )

        # The todo is read for THIS user, and Composio is told whose todo and which
        # trigger to register — a swapped arg registers the wrong watch.
        h.get.assert_awaited_once_with(TODO_ID, user_id=USER_ID)
        args, kwargs = h.register.await_args
        assert args[0] == USER_ID
        assert args[1] == TODO_ID
        assert args[2] == INSTANCE_TRIGGER
        assert kwargs["raise_on_failure"] is True
        # The subscription is persisted against THIS todo and user — a swapped id
        # writes the watch onto the wrong document.
        assert h.update.await_args.args[0] == TODO_ID
        assert h.update.await_args.kwargs["user_id"] == USER_ID

    async def test_match_and_cooldown_are_stored_on_the_subscription(self) -> None:
        # Both are registration-time knobs the payload cannot express; dropping
        # either silently falls back to the ALL/default watch the user did not ask
        # for.
        with _Harness(_todo(), ["ti_9"]) as h:
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=INSTANCE_TRIGGER,
                conditions=[],
                action=SubscriptionAction.NOTIFY,
                match=ConditionMatch.ANY,
                cooldown_seconds=1234,
            )

        stored = h.written_subscriptions[0]
        assert stored.match is ConditionMatch.ANY
        assert stored.cooldown_seconds == 1234

    async def test_invalid_condition_rejects_before_registering(self) -> None:
        with _Harness(_todo(), []) as h:
            with pytest.raises(SubscriptionError, match="not a matchable field"):
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name=ACCOUNT_TRIGGER,
                    conditions=[
                        SubscriptionCondition(
                            field_name="nope", operator=ConditionOperator.EQUALS, value="x"
                        )
                    ],
                    action=SubscriptionAction.EXECUTE,
                )
            # Registering upstream state we then refuse to store would orphan it.
            h.register.assert_not_awaited()
        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": ACCOUNT_TRIGGER, "reason": "invalid_conditions"},
        )

    async def test_multiple_condition_errors_are_joined_with_spaces(self) -> None:
        # Two bad fields, two error sentences. Joined by " ", the SubscriptionError
        # message stays one readable string; drop the separator and the sentences
        # run together into an unreadable blob the agent cannot parse.
        conditions = [
            SubscriptionCondition(field_name="nope", operator=ConditionOperator.EQUALS, value="x"),
            SubscriptionCondition(field_name="zilch", operator=ConditionOperator.EQUALS, value="y"),
        ]
        expected = " ".join(validate_conditions(ACCOUNT_TRIGGER, conditions).errors)
        with _Harness(_todo(), []):
            with pytest.raises(SubscriptionError) as excinfo:
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name=ACCOUNT_TRIGGER,
                    conditions=conditions,
                    action=SubscriptionAction.EXECUTE,
                )
        assert str(excinfo.value) == expected
        assert "'nope'" in expected and "'zilch'" in expected

    async def test_missing_todo_rejects_before_registering(self) -> None:
        with _Harness(None, []) as h:
            with pytest.raises(SubscriptionError, match="was not found"):
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name=ACCOUNT_TRIGGER,
                    conditions=[],
                    action=SubscriptionAction.EXECUTE,
                )
            h.register.assert_not_awaited()
        # The todo was resolved for THIS user, or a leak reads another user's doc.
        h.get.assert_awaited_once_with(TODO_ID, user_id=USER_ID)
        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": ACCOUNT_TRIGGER, "reason": "todo_not_found"},
        )

    async def test_unknown_trigger_rejects(self) -> None:
        with _Harness(_todo(), []) as h:
            with pytest.raises(SubscriptionError, match="no trigger handler"):
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name="not_a_trigger",
                    conditions=[],
                    action=SubscriptionAction.EXECUTE,
                )
        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": "not_a_trigger", "reason": "unknown_trigger"},
        )

    async def test_registration_failure_surfaces_as_subscription_error(self) -> None:
        failure = TriggerRegistrationError("composio said no", INSTANCE_TRIGGER)
        with _Harness(_todo(), failure) as h:
            with pytest.raises(SubscriptionError, match="composio said no"):
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name=INSTANCE_TRIGGER,
                    conditions=[],
                    action=SubscriptionAction.EXECUTE,
                )
            h.update.assert_not_awaited()
        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": INSTANCE_TRIGGER, "reason": "registration_failed"},
        )


class TestTeardown:
    async def test_unregisters_each_subscription_excluding_this_todo(self) -> None:
        todo = _todo(trigger_subscriptions=[_subscription(composio_trigger_ids=["ti_1", "ti_2"])])
        with _Harness(todo, []) as h:
            count = await teardown_subscriptions(TODO_ID, USER_ID, reason="completed")

        assert count == 1
        # The todo is read for THIS user and cleared for THIS user — a swapped id
        # tears down (or fails to) the wrong person's watches.
        h.get.assert_awaited_once_with(TODO_ID, user_id=USER_ID)
        h.unregister.assert_awaited_once()
        args, kwargs = h.unregister.await_args
        assert args[0] == USER_ID
        assert args[1] == INSTANCE_TRIGGER
        assert args[2] == ["ti_1", "ti_2"]
        # Excluded from its own refcount, or the last reference never releases.
        assert kwargs["todo_id"] == TODO_ID
        update_call = h.update.await_args
        assert update_call.args[0] == TODO_ID
        assert update_call.kwargs["user_id"] == USER_ID

    async def test_teardown_stamps_the_wide_event(self) -> None:
        todo = _todo(trigger_subscriptions=[_subscription()])
        with _Harness(todo, []):
            async with captured_wide_event() as event:
                await teardown_subscriptions(TODO_ID, USER_ID, reason="completed")

        assert event["component"] == "trigger_subscription"
        assert event["operation"] == "teardown"
        assert event["todo_id"] == TODO_ID

    async def test_a_stuck_unregister_is_recorded_on_the_wide_event(self) -> None:
        # A stuck trigger is a real leak; swallowing it silently is the failure.
        # It must land on the event's errors[] with the ids to find it by.
        sub = _subscription(composio_trigger_ids=["ti_1"])
        todo = _todo(trigger_subscriptions=[sub])
        with _Harness(todo, []) as h:
            h.unregister.side_effect = RuntimeError("composio down")
            async with captured_wide_event() as event:
                await teardown_subscriptions(TODO_ID, USER_ID, reason="completed")

        (error,) = event["errors"]
        assert error["msg"] == "todo_subscription.teardown_failed"
        assert error["todo_id"] == TODO_ID
        assert error["subscription_id"] == sub.id
        assert error["trigger_name"] == INSTANCE_TRIGGER
        assert error["error"] == "composio down"
        assert error["error_type"] == "RuntimeError"

    async def test_an_account_level_subscription_is_skipped_but_later_ones_run(self) -> None:
        # The account-level sub has no ids and must be skipped with `continue`, not
        # `break` — a break would strand every watch registered after it.
        account = _subscription(
            trigger_name=ACCOUNT_TRIGGER,
            resolution=SubscriptionResolution.ACCOUNT,
            composio_trigger_ids=[],
        )
        per_resource = _subscription(composio_trigger_ids=["ti_9"])
        todo = _todo(trigger_subscriptions=[account, per_resource])
        with _Harness(todo, []) as h:
            count = await teardown_subscriptions(TODO_ID, USER_ID, reason="deleted")

        assert count == 2
        h.unregister.assert_awaited_once()
        assert h.unregister.await_args.args[2] == ["ti_9"]

    async def test_clears_the_subscriptions_from_the_document(self) -> None:
        todo = _todo(trigger_subscriptions=[_subscription()])
        with _Harness(todo, []) as h:
            await teardown_subscriptions(TODO_ID, USER_ID, reason="completed")

        assert h.update.await_args.kwargs["update"].trigger_subscriptions == []

    async def test_account_level_subscription_needs_no_unregister(self) -> None:
        todo = _todo(
            trigger_subscriptions=[
                _subscription(
                    trigger_name=ACCOUNT_TRIGGER,
                    resolution=SubscriptionResolution.ACCOUNT,
                    composio_trigger_ids=[],
                )
            ]
        )
        with _Harness(todo, []) as h:
            count = await teardown_subscriptions(TODO_ID, USER_ID, reason="deleted")

        assert count == 1
        h.unregister.assert_not_awaited()
        assert h.update.await_args.kwargs["update"].trigger_subscriptions == []

    async def test_a_stuck_unregister_still_clears_the_rest(self) -> None:
        todo = _todo(
            trigger_subscriptions=[
                _subscription(composio_trigger_ids=["ti_1"]),
                _subscription(composio_trigger_ids=["ti_2"]),
            ]
        )
        with _Harness(todo, []) as h:
            h.unregister.side_effect = [Exception("composio down"), True]
            count = await teardown_subscriptions(TODO_ID, USER_ID, reason="completed")

        assert count == 2
        assert h.unregister.await_count == 2
        assert h.update.await_args.kwargs["update"].trigger_subscriptions == []

    async def test_paused_subscriptions_are_torn_down_too(self) -> None:
        todo = _todo(trigger_subscriptions=[_subscription(status=SubscriptionStatus.PAUSED)])
        with _Harness(todo, []) as h:
            assert await teardown_subscriptions(TODO_ID, USER_ID, reason="deleted") == 1
            h.unregister.assert_awaited_once()

    async def test_no_subscriptions_is_a_no_op(self) -> None:
        with _Harness(_todo(), []) as h:
            assert await teardown_subscriptions(TODO_ID, USER_ID, reason="completed") == 0
            h.unregister.assert_not_awaited()
            h.update.assert_not_awaited()

    async def test_missing_todo_is_a_no_op(self) -> None:
        with _Harness(None, []) as h:
            assert await teardown_subscriptions(TODO_ID, USER_ID, reason="deleted") == 0
            h.update.assert_not_awaited()


class TestBuildTriggerConfig:
    def test_registration_knobs_reach_the_handler_config(self) -> None:
        # A calendar reminder window is registration config, not a payload
        # condition — it has to survive into trigger_data or the reminder fires
        # at the default 10 minutes instead of the hour the user asked for.
        config = build_trigger_config("calendar_event_starting_soon", {"minutes_before_start": 60})

        assert config.trigger_name == "calendar_event_starting_soon"
        assert config.trigger_data is not None
        assert config.trigger_data.minutes_before_start == 60

    def test_absent_trigger_data_still_builds_a_valid_config(self) -> None:
        config = build_trigger_config(ACCOUNT_TRIGGER, None)

        assert config.trigger_name == ACCOUNT_TRIGGER
        assert config.trigger_data is not None

    def test_an_omitted_window_falls_back_to_the_trigger_default(self) -> None:
        config = build_trigger_config("calendar_event_starting_soon", None)

        assert config.trigger_data is not None
        assert config.trigger_data.minutes_before_start == 10


class TestCalendarReminders:
    """The reminder window is registration config, not a payload condition.

    Distinct windows are therefore distinct Composio trigger instances, and two
    todos wanting the same window share one — which is exactly the sharing the
    todo refcount protects.
    """

    async def test_a_window_reaches_the_handler_config(self) -> None:
        with _Harness(_todo(), ["ti_cal"]) as h:
            subscription, _ = await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name="calendar_event_starting_soon",
                conditions=[
                    SubscriptionCondition(
                        field_name="event_id", operator=ConditionOperator.EQUALS, value="evt-1"
                    )
                ],
                action=SubscriptionAction.NOTIFY,
                trigger_data={"minutes_before_start": 60},
            )

        registered_config = h.register.await_args.args[3]
        assert registered_config.trigger_data.minutes_before_start == 60
        assert subscription.resolution is SubscriptionResolution.TRIGGER_ID
        # The window is persisted on the subscription so a later resync can replay
        # it instead of resetting to the trigger's default window.
        assert subscription.trigger_data == {"minutes_before_start": 60}

    async def test_resync_replays_the_persisted_window_not_the_default(self) -> None:
        # A reconnect re-registers the trigger; the user's custom window must
        # survive rather than resetting to the 10-minute default.
        paused = _subscription(
            trigger_name="calendar_event_starting_soon",
            action=SubscriptionAction.NOTIFY,
            composio_trigger_ids=["ti_old"],
            trigger_data={"minutes_before_start": 60},
            status=SubscriptionStatus.PAUSED,
        )
        todo = _todo(trigger_subscriptions=[paused])
        register = AsyncMock(return_value=["ti_new"])
        with (
            patch(
                "app.services.triggers.subscription_service.todo_repository",
                find_paused_by_user_and_trigger=AsyncMock(return_value=[todo]),
                update=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.triggers.subscription_service.TriggerService",
                register_triggers=register,
                unregister_triggers=AsyncMock(return_value=True),
            ),
        ):
            resynced = await resync_subscriptions_for_trigger_names(
                USER_ID, {"calendar_event_starting_soon"}
            )

        assert resynced == 1
        replayed_config = register.await_args.args[3]
        assert replayed_config.trigger_data.minutes_before_start == 60

    async def test_two_windows_are_two_subscriptions(self) -> None:
        # One subscription cannot carry two windows: the window decides which
        # Composio trigger gets registered.
        todo = _todo()
        windows = []
        for minutes in (60, 10):
            with _Harness(todo, [f"ti_{minutes}"]) as h:
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name="calendar_event_starting_soon",
                    conditions=[],
                    action=SubscriptionAction.NOTIFY,
                    trigger_data={"minutes_before_start": minutes},
                )
                windows.append(h.written_subscriptions[-1])

        assert [w.composio_trigger_ids for w in windows] == [["ti_60"], ["ti_10"]]

    async def test_an_out_of_range_window_is_refused_with_a_readable_reason(self) -> None:
        # A raw pydantic traceback is not something the agent can correct from.
        with _Harness(_todo(), ["ti_cal"]) as h:
            with pytest.raises(SubscriptionError, match="Invalid configuration"):
                await register_subscription(
                    todo_id=TODO_ID,
                    user_id=USER_ID,
                    trigger_name="calendar_event_starting_soon",
                    conditions=[],
                    action=SubscriptionAction.NOTIFY,
                    trigger_data={"minutes_before_start": 5000},
                )
            h.register.assert_not_awaited()
        h.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.TODO_SUBSCRIPTION_FAILED,
            {"trigger_name": "calendar_event_starting_soon", "reason": "invalid_config"},
        )


class _ResyncHarness:
    """Patches the repo + Composio seams a resync sweep touches, and records writes."""

    def __init__(self, todos: list[TodoDocument], register: list[str] | Exception):
        self.todos = todos
        self.register_result = register
        self.find_paused = AsyncMock(return_value=todos)
        self.register = AsyncMock()
        self.unregister = AsyncMock(return_value=True)
        self.update = AsyncMock(return_value=None)

    def __enter__(self) -> "_ResyncHarness":
        if isinstance(self.register_result, Exception):
            self.register.side_effect = self.register_result
        else:
            self.register.return_value = self.register_result
        self._repo = patch(
            "app.services.triggers.subscription_service.todo_repository",
            find_paused_by_user_and_trigger=self.find_paused,
            update=self.update,
        )
        self._svc = patch(
            "app.services.triggers.subscription_service.TriggerService",
            register_triggers=self.register,
            unregister_triggers=self.unregister,
        )
        self._repo.start()
        self._svc.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._svc.stop()
        self._repo.stop()


def _paused_sub(**overrides: object) -> TriggerSubscription:
    return _subscription(status=SubscriptionStatus.PAUSED, **overrides)


class TestResyncSubscriptions:
    async def test_resyncs_each_paused_todo_and_repoints_its_ids(self) -> None:
        # A reconnect makes the old Composio instance ids stale. Every paused todo
        # on the trigger is re-registered, unblocked, and its stored ids repointed.
        todo_a = _todo(
            id="todo-a",
            labels=[BLOCKING_LABEL, "keepme"],
            trigger_subscriptions=[_paused_sub(composio_trigger_ids=["ti_a_old"])],
        )
        todo_b = _todo(
            id="todo-b",
            labels=[BLOCKING_LABEL],
            trigger_subscriptions=[_paused_sub(composio_trigger_ids=["ti_b_old"])],
        )
        with _ResyncHarness([todo_a, todo_b], ["ti_new"]) as h:
            resynced = await resync_subscriptions_for_trigger_names(USER_ID, {INSTANCE_TRIGGER})

        assert resynced == 2
        # Paused todos were looked up for THIS user on THIS trigger — a swapped arg
        # resyncs the wrong person or the wrong trigger.
        assert h.find_paused.await_args.args == (USER_ID, INSTANCE_TRIGGER)

        # Both todos were written back, each under its own id and user.
        assert [c.args[0] for c in h.update.await_args_list] == ["todo-a", "todo-b"]
        for call in h.update.await_args_list:
            assert call.kwargs["user_id"] == USER_ID

        first = h.update.await_args_list[0].kwargs["update"]
        # The blocking label is stripped; every other label survives.
        assert first.labels == ["keepme"]
        # The refreshed subscription is active again and points at the new instance.
        refreshed = first.trigger_subscriptions[0]
        assert refreshed.status is SubscriptionStatus.ACTIVE
        assert refreshed.composio_trigger_ids == ["ti_new"]

        # Re-registration is for THIS todo's identity, and must raise on failure so a
        # broken re-register is caught, not silently stored.
        assert h.register.await_count == 2
        reg = h.register.await_args_list[0]
        assert reg.args[0] == USER_ID
        assert reg.args[1] == "todo-a"
        assert reg.args[2] == INSTANCE_TRIGGER
        assert reg.kwargs["raise_on_failure"] is True

        # The now-stale old id is released, excluded from its own refcount via todo_id.
        un = h.unregister.await_args_list[0]
        assert un.args[0] == USER_ID
        assert un.args[1] == INSTANCE_TRIGGER
        assert un.args[2] == ["ti_a_old"]
        assert un.kwargs["todo_id"] == "todo-a"

    async def test_a_trigger_with_no_handler_is_skipped(self) -> None:
        # An unknown trigger name has no handler; the sweep must skip it rather than
        # query for paused todos and try to re-register a watch nothing can service.
        with _ResyncHarness([_todo(id="todo-x")], ["ti_new"]) as h:
            resynced = await resync_subscriptions_for_trigger_names(USER_ID, {"not_a_trigger"})

        assert resynced == 0
        h.find_paused.assert_not_awaited()
        h.register.assert_not_awaited()
        h.update.assert_not_awaited()

    async def test_an_unknown_trigger_skips_but_the_sweep_continues(self) -> None:
        # A handlerless trigger must be skipped with `continue`, not `break` — a
        # `break` would abandon every trigger the user reconnected after it. Ordering
        # is pinned by call order (first lookup handlerless, second real) so the set's
        # iteration order can never mask a `break`.
        todo = _todo(id="todo-ok", labels=[BLOCKING_LABEL], trigger_subscriptions=[_paused_sub()])
        with (
            _ResyncHarness([todo], ["ti_new"]) as h,
            patch(
                "app.services.triggers.subscription_service.get_handler_by_name",
                side_effect=[None, Mock()],
            ),
        ):
            resynced = await resync_subscriptions_for_trigger_names(
                USER_ID, {"unknown_trigger", INSTANCE_TRIGGER}
            )

        # The second (real) trigger was still reached and its todo resynced.
        assert resynced == 1
        h.update.assert_awaited_once()
        assert h.update.await_args.args[0] == "todo-ok"

    async def test_a_todo_without_an_id_is_skipped(self) -> None:
        # A document with no id cannot be updated; it is skipped and the rest run.
        no_id = TodoDocument.model_construct(
            id=None,
            user_id=USER_ID,
            title="ghost",
            labels=[BLOCKING_LABEL],
            trigger_subscriptions=[_paused_sub()],
        )
        real = _todo(
            id="todo-real",
            labels=[BLOCKING_LABEL],
            trigger_subscriptions=[_paused_sub()],
        )
        with _ResyncHarness([no_id, real], ["ti_new"]) as h:
            resynced = await resync_subscriptions_for_trigger_names(USER_ID, {INSTANCE_TRIGGER})

        assert resynced == 1
        h.update.assert_awaited_once()
        # The write is for the real todo, never the id-less one.
        assert h.update.await_args.args[0] == "todo-real"

    async def test_one_todos_failure_is_logged_and_the_rest_still_resync(self) -> None:
        # One broken re-register must not strand the others or the OAuth flow behind
        # them. The failure lands on the wide event with everything needed to find it.
        failing = _todo(id="todo-fail", trigger_subscriptions=[_paused_sub()])
        surviving = _todo(
            id="todo-ok",
            labels=[BLOCKING_LABEL],
            trigger_subscriptions=[_paused_sub()],
        )
        with _ResyncHarness([failing, surviving], ["ti_new"]) as h:
            h.register.side_effect = [RuntimeError("composio exploded"), ["ti_new"]]
            async with captured_wide_event() as event:
                resynced = await resync_subscriptions_for_trigger_names(USER_ID, {INSTANCE_TRIGGER})

        assert resynced == 1
        # The failed todo was NOT written (its labels/subscriptions never updated);
        # only the surviving one was.
        h.update.assert_awaited_once()
        assert h.update.await_args.args[0] == "todo-ok"

        (error,) = event["errors"]
        assert error["msg"] == "todo_subscription.resync_failed"
        assert error["todo_id"] == "todo-fail"
        assert error["trigger_name"] == INSTANCE_TRIGGER
        assert error["error"] == "composio exploded"
        assert error["error_type"] == "RuntimeError"

    async def test_only_subscriptions_on_the_reconnected_trigger_are_touched(self) -> None:
        # A todo can watch several triggers. A reconnect of one must repoint only that
        # trigger's subscription and pass every other through byte-for-byte.
        other = _paused_sub(
            trigger_name=ACCOUNT_TRIGGER,
            resolution=SubscriptionResolution.ACCOUNT,
            composio_trigger_ids=[],
        )
        target = _paused_sub(trigger_name=INSTANCE_TRIGGER, composio_trigger_ids=["ti_old"])
        todo = _todo(
            id="todo-multi", labels=[BLOCKING_LABEL], trigger_subscriptions=[other, target]
        )
        with _ResyncHarness([todo], ["ti_new"]) as h:
            resynced = await resync_subscriptions_for_trigger_names(USER_ID, {INSTANCE_TRIGGER})

        assert resynced == 1
        written = h.update.await_args.kwargs["update"].trigger_subscriptions
        # The unrelated trigger is untouched — same id, ids, still paused.
        assert written[0].id == other.id
        assert written[0].composio_trigger_ids == []
        assert written[0].status is SubscriptionStatus.PAUSED
        # The reconnected trigger is refreshed and active.
        assert written[1].id == target.id
        assert written[1].composio_trigger_ids == ["ti_new"]
        assert written[1].status is SubscriptionStatus.ACTIVE
        # Only the reconnected trigger was re-registered.
        h.register.assert_awaited_once()
        assert h.register.await_args.args[2] == INSTANCE_TRIGGER

    async def test_nothing_paused_writes_nothing(self) -> None:
        with _ResyncHarness([], ["ti_new"]) as h:
            resynced = await resync_subscriptions_for_trigger_names(USER_ID, {INSTANCE_TRIGGER})

        assert resynced == 0
        h.register.assert_not_awaited()
        h.update.assert_not_awaited()
