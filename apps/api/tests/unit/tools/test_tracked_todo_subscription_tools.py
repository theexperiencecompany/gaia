"""The agent-facing surface for making a tracked todo watch a trigger.

What these pin down is the failure path. A rejection that does not name the real
fields leaves the model guessing again, and guessing is what the whole
matchable-fields layer exists to stop — so the catalog rides along on every
refusal, not only on the happy path.

Split from ``test_tracked_todo_tools.py`` (already 1300 lines) because watching a
trigger is a separate responsibility from todo CRUD, not because it is a separate
module.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.graph_builder import build_graph
from app.agents.tools import tracked_todo_tools
from app.agents.tools.tracked_todo_tools import (
    _format_tracked_todo_full,
    list_trigger_fields,
    subscribe_todo_to_trigger,
    unsubscribe_todo_from_trigger,
)
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerSubscription,
)
from app.services.triggers.subscription_service import SubscriptionError
from app.services.triggers.subscription_validation import ValidationOutcome, validate_conditions

pytestmark = pytest.mark.unit

_MOD = "app.agents.tools.tracked_todo_tools"
USER_ID = "user-1"
TODO_ID = "todo-1"
GMAIL = "gmail_new_message"


def _config(user_id: str | None = USER_ID) -> dict:
    return {"metadata": {"user_id": user_id}} if user_id else {"metadata": {}}


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
        {"id": TODO_ID, "user_id": USER_ID, "title": "Chase Acme", **overrides}
    )


class TestListTriggerFields:
    async def test_it_lists_fields_with_types_and_examples(self) -> None:
        out = await list_trigger_fields.coroutine(trigger_name=GMAIL)

        assert "thread_id (string)" in out
        assert "Example:" in out

    async def test_it_says_what_is_not_matchable_and_why(self) -> None:
        # Without the reason an excluded field looks like an oversight, and the
        # model writes a condition against it anyway.
        out = await list_trigger_fields.coroutine(trigger_name=GMAIL)

        assert "Not matchable:" in out
        assert "payload" in out

    async def test_it_lists_the_operators_each_type_accepts(self) -> None:
        out = await list_trigger_fields.coroutine(trigger_name="google_sheets_new_row")

        assert "greater_than" in out

    async def test_an_unknown_trigger_returns_the_available_ones(self) -> None:
        out = await list_trigger_fields.coroutine(trigger_name="nope")

        assert "not a subscribable trigger" in out
        assert GMAIL in out
        assert "calendar_event_starting_soon" in out


class TestSubscribe:
    @staticmethod
    def _register() -> tuple[AsyncMock, TriggerSubscription]:
        subscription = _subscription()
        return AsyncMock(return_value=(subscription, ValidationOutcome())), subscription

    async def test_it_registers_and_reports_the_subscription_id(self) -> None:
        register, subscription = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                conditions=[{"field_name": "thread_id", "operator": "equals", "value": "t-1"}],
            )

        assert subscription.id in out
        kwargs = register.await_args.kwargs
        assert kwargs["action"] is SubscriptionAction.EXECUTE
        assert kwargs["conditions"][0].field_name == "thread_id"
        assert kwargs["conditions"][0].operator is ConditionOperator.EQUALS

    async def test_no_conditions_is_allowed(self) -> None:
        register, _ = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name="slack_new_message",
                action="notify",
            )

        assert register.await_args.kwargs["conditions"] == []

    async def test_a_calendar_window_is_passed_as_registration_config(self) -> None:
        # The reminder window is not a payload field — it decides which Composio
        # trigger is registered, so it cannot travel as a condition.
        register, _ = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name="calendar_event_starting_soon",
                action="notify",
                minutes_before_start=60,
            )

        assert register.await_args.kwargs["trigger_data"] == {"minutes_before_start": 60}

    async def test_no_calendar_window_sends_no_registration_config(self) -> None:
        register, _ = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            await subscribe_todo_to_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, trigger_name=GMAIL, action="execute"
            )

        assert register.await_args.kwargs["trigger_data"] is None

    async def test_mechanical_repairs_are_reported_back(self) -> None:
        # Repairing silently teaches the model nothing; it sends the same wrong
        # field name next time too.
        repaired = validate_conditions(
            GMAIL,
            [
                SubscriptionCondition(
                    field_name="threadId", operator=ConditionOperator.EQUALS, value="t-1"
                )
            ],
        )
        assert repaired.repairs, "fixture no longer exercises a repair"

        with patch(
            f"{_MOD}.register_subscription", AsyncMock(return_value=(_subscription(), repaired))
        ):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, trigger_name=GMAIL, action="execute"
            )

        assert "Repaired automatically" in out
        assert "thread_id" in out

    async def test_a_rejection_carries_the_catalog_so_the_retry_can_be_right(self) -> None:
        failure = SubscriptionError("'recipient_domain' is not a matchable field.")
        with patch(f"{_MOD}.register_subscription", AsyncMock(side_effect=failure)):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                conditions=[{"field_name": "recipient_domain", "operator": "equals", "value": "x"}],
            )

        assert "Could not subscribe" in out
        assert f"Matchable fields for {GMAIL}" in out
        assert "thread_id" in out

    async def test_an_invalid_action_is_rejected_with_the_valid_ones(self) -> None:
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, trigger_name=GMAIL, action="explode"
            )

        assert "not a valid action" in out
        assert "unblock" in out
        register.assert_not_awaited()

    async def test_an_invalid_operator_is_rejected_with_the_catalog(self) -> None:
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                conditions=[{"field_name": "thread_id", "operator": "is_kind_of", "value": "t-1"}],
            )

        assert "not a valid operator" in out
        assert "Matchable fields" in out
        register.assert_not_awaited()

    async def test_a_malformed_condition_is_rejected_not_raised(self) -> None:
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                conditions=[{"field": "thread_id", "op": "equals"}],
            )

        assert "each condition needs" in out
        register.assert_not_awaited()

    async def test_no_user_id_is_refused(self) -> None:
        out = await subscribe_todo_to_trigger.coroutine(
            config=_config(None), todo_id=TODO_ID, trigger_name=GMAIL, action="execute"
        )

        assert "user_id not found" in out


class TestUnsubscribe:
    async def test_it_reports_what_stopped_being_watched(self) -> None:
        with patch(f"{_MOD}.unregister_subscription", AsyncMock(return_value=_subscription())):
            out = await unsubscribe_todo_from_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, subscription_id="sub-1"
            )

        assert f"stopped watching {GMAIL}" in out

    async def test_an_unknown_subscription_says_so(self) -> None:
        with patch(f"{_MOD}.unregister_subscription", AsyncMock(return_value=None)):
            out = await unsubscribe_todo_from_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, subscription_id="nope"
            )

        assert "No subscription nope" in out

    async def test_no_user_id_is_refused(self) -> None:
        out = await unsubscribe_todo_from_trigger.coroutine(
            config=_config(None), todo_id=TODO_ID, subscription_id="sub-1"
        )

        assert "user_id not found" in out


class TestSubscriptionsAreVisibleOnTheTodo:
    def test_a_watch_is_rendered_with_the_id_unsubscribing_needs(self) -> None:
        subscription = _subscription(
            conditions=[
                SubscriptionCondition(
                    field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-1"
                )
            ]
        )
        doc = _todo(trigger_subscriptions=[subscription])

        rendered = _format_tracked_todo_full(doc, datetime.now(UTC))

        assert f"Watching {GMAIL} -> execute when thread_id equals t-1" in rendered
        assert subscription.id in rendered

    def test_a_watch_with_no_conditions_says_so(self) -> None:
        doc = _todo(trigger_subscriptions=[_subscription()])

        assert "when any event" in _format_tracked_todo_full(doc, datetime.now(UTC))

    def test_a_paused_watch_says_the_integration_is_disconnected(self) -> None:
        doc = _todo(trigger_subscriptions=[_subscription(status=SubscriptionStatus.PAUSED)])

        assert "PAUSED" in _format_tracked_todo_full(doc, datetime.now(UTC))

    def test_a_todo_with_no_watches_renders_unchanged(self) -> None:
        assert "Watching" not in _format_tracked_todo_full(_todo(), datetime.now(UTC))


class TestToolsAreReachable:
    """The subscription tools are always loaded, not semantically retrieved.

    A tool the model cannot see at the moment a reply-watching todo is created is
    a tool that never gets used — and retrieval only surfaces tools it was asked
    to search for.
    """

    def test_they_are_bound_to_the_executor_up_front(self) -> None:
        source = Path(build_graph.__file__).read_text()
        executor_block = source.split('agent_name="executor_agent"', 1)[1].split("]", 1)[0]

        for name in (
            "list_trigger_fields",
            "subscribe_todo_to_trigger",
            "unsubscribe_todo_from_trigger",
        ):
            assert f'"{name}"' in executor_block, f"{name} is not in the executor initial tool ids"

    def test_they_are_exported_from_the_tool_module(self) -> None:
        # initial_tool_ids naming a tool the registry never exports binds nothing.
        exported = {t.name for t in tracked_todo_tools.tools}

        assert {
            "list_trigger_fields",
            "subscribe_todo_to_trigger",
            "unsubscribe_todo_from_trigger",
        } <= exported
