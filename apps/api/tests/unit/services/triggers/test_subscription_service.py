"""Registration and teardown of a todo's trigger subscriptions.

The two registration shapes are the point: Gmail is account-level and returns no
Composio instance id, which is success; a per-resource trigger returning none
registered nothing and would be a watch that silently never fires. The real
handler registry is used rather than a mock, because which shape a trigger has is
exactly what these tests are asserting.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerSubscription,
)
from app.services.triggers.subscription_service import (
    SubscriptionError,
    build_trigger_config,
    register_subscription,
    teardown_subscriptions,
)
from app.utils.exceptions import TriggerRegistrationError

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
        self.register = AsyncMock()
        self.unregister = AsyncMock(return_value=True)
        self.update = AsyncMock(return_value=None)

    def __enter__(self) -> "_Harness":
        if isinstance(self.trigger_ids, Exception):
            self.register.side_effect = self.trigger_ids
        else:
            self.register.return_value = self.trigger_ids
        self._repo = patch(
            "app.services.triggers.subscription_service.todo_repository",
            get=AsyncMock(return_value=self.todo),
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
        with _Harness(_todo(), []), pytest.raises(SubscriptionError, match="never fire"):
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name=INSTANCE_TRIGGER,
                conditions=[],
                action=SubscriptionAction.EXECUTE,
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

    async def test_unknown_trigger_rejects(self) -> None:
        with _Harness(_todo(), []), pytest.raises(SubscriptionError, match="no trigger handler"):
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name="not_a_trigger",
                conditions=[],
                action=SubscriptionAction.EXECUTE,
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


class TestTeardown:
    async def test_unregisters_each_subscription_excluding_this_todo(self) -> None:
        todo = _todo(trigger_subscriptions=[_subscription(composio_trigger_ids=["ti_1", "ti_2"])])
        with _Harness(todo, []) as h:
            count = await teardown_subscriptions(TODO_ID, USER_ID, reason="completed")

        assert count == 1
        h.unregister.assert_awaited_once()
        args, kwargs = h.unregister.await_args
        assert args[2] == ["ti_1", "ti_2"]
        # Excluded from its own refcount, or the last reference never releases.
        assert kwargs["todo_id"] == TODO_ID

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
        with (
            _Harness(_todo(), ["ti_cal"]) as h,
            pytest.raises(SubscriptionError, match="Invalid configuration"),
        ):
            await register_subscription(
                todo_id=TODO_ID,
                user_id=USER_ID,
                trigger_name="calendar_event_starting_soon",
                conditions=[],
                action=SubscriptionAction.NOTIFY,
                trigger_data={"minutes_before_start": 5000},
            )
        h.register.assert_not_awaited()
