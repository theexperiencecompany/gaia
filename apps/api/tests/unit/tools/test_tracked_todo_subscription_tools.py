"""The agent-facing surface for making a tracked todo watch a trigger.

What these pin down is the failure path. A rejection that does not name the real
fields leaves the model guessing again, and guessing is what the whole
matchable-fields layer exists to stop — so the catalog rides along on every
refusal, not only on the happy path.

Split from test_tracked_todo_tools.py (already 1300 lines) because watching a
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
    _format_subscription_lines,
    _format_tracked_todo_full,
    list_trigger_fields,
    subscribe_todo_to_trigger,
    unsubscribe_todo_from_trigger,
)
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.triggers.matchable_fields import MATCHABLE_TRIGGERS
from app.services.triggers.subscription_service import (
    DEFAULT_COOLDOWN_SECONDS,
    SubscriptionError,
)
from app.services.triggers.subscription_validation import (
    ConditionRepair,
    ValidationOutcome,
    validate_conditions,
)

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

        # A standalone header line — not folded into a neighbouring token.
        assert "Not matchable:" in out.splitlines()
        assert "payload" in out

    async def test_the_field_block_is_newline_separated(self) -> None:
        # The catalog is one field per line; join them with anything but "\n" and
        # the whole block collapses into a single unreadable line.
        out = await list_trigger_fields.coroutine(trigger_name=GMAIL)

        assert f"Matchable fields for {GMAIL}:\n  thread_id (string)" in out

    async def test_it_lists_the_operators_each_type_accepts(self) -> None:
        out = await list_trigger_fields.coroutine(trigger_name="google_sheets_new_row")

        assert "greater_than" in out
        expected = "Operators by type: " + "; ".join(
            f"{field_type} -> {', '.join(sorted(ops))}"
            for field_type, ops in OPERATORS_BY_FIELD_TYPE.items()
        )
        assert expected in out.splitlines()

    async def test_it_lists_the_registration_scope_a_per_resource_trigger_needs(self) -> None:
        # Without the scope section the model cannot know a github trigger needs a
        # repo, so it subscribes with none and the registration is rejected. Both
        # lines are asserted verbatim: a garbled header or field line is useless.
        out = await list_trigger_fields.coroutine(trigger_name="github_pr_event")
        lines = out.splitlines()

        assert (
            "Scope this watch with (registration config, passed via the scope argument):" in lines
        )
        assert (
            "  repos (list of text, required): List of repositories in owner/repo format" in lines
        )

    async def test_an_account_level_trigger_shows_no_scope_section(self) -> None:
        # Gmail fires on the account itself; a scope section there would invite the
        # model to pass config the trigger has no field for.
        out = await list_trigger_fields.coroutine(trigger_name=GMAIL)

        assert "Scope this watch with" not in out

    async def test_an_optional_scope_field_renders_without_the_required_marker(self) -> None:
        # calendar_ids is optional, so its line must NOT carry ', required' — the
        # exact line guards the required/optional branch of the render.
        out = await list_trigger_fields.coroutine(trigger_name="calendar_event_starting_soon")
        lines = out.splitlines()

        assert (
            "  calendar_ids (list of text): Calendar IDs to monitor. Use ['all'] for all calendars."
            in lines
        )

    async def test_an_unknown_trigger_returns_the_available_ones(self) -> None:
        out = await list_trigger_fields.coroutine(trigger_name="nope")

        assert "not a subscribable trigger" in out
        # The available triggers are listed comma-separated, not run together.
        assert ", ".join(sorted(MATCHABLE_TRIGGERS)) in out


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
        # Every field the subscription is registered under — a swapped or dropped
        # one watches the wrong todo, user, trigger, or with the wrong policy.
        assert kwargs["todo_id"] == TODO_ID
        assert kwargs["user_id"] == USER_ID
        assert kwargs["trigger_name"] == GMAIL
        assert kwargs["action"] is SubscriptionAction.EXECUTE
        assert kwargs["match"] is ConditionMatch.ALL
        assert kwargs["cooldown_seconds"] == DEFAULT_COOLDOWN_SECONDS
        assert kwargs["trigger_data"] is None
        assert kwargs["conditions"][0].field_name == "thread_id"
        assert kwargs["conditions"][0].operator is ConditionOperator.EQUALS
        # The two output lines are newline-joined, not run together.
        assert f"\nSubscription id: {subscription.id}" in out

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
                scope={"minutes_before_start": 60},
            )

        assert register.await_args.kwargs["trigger_data"] == {"minutes_before_start": 60}

    async def test_a_boolean_scope_value_is_preserved_as_a_bool(self) -> None:
        # Calendar's include_all_day and Slack's exclude_* flags are booleans; the
        # scope type must accept bool and not coerce True to 1 (regression: bool was
        # missing from the scope union).
        register, _ = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name="calendar_event_starting_soon",
                action="notify",
                scope={"include_all_day": True},
            )

        passed = register.await_args.kwargs["trigger_data"]
        assert passed == {"include_all_day": True}
        assert passed["include_all_day"] is True

    async def test_a_github_repo_scope_is_passed_as_registration_config(self) -> None:
        # A github PR trigger registers a webhook per repo, so the repo must reach
        # registration as scope; without it the trigger matches nothing and the
        # whole subscription is rejected (regression: scope had no way in).
        register, _ = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name="github_pr_event",
                action="notify",
                scope={"repos": ["theexperiencecompany/gaia"]},
                conditions=[{"field_name": "number", "operator": "equals", "value": 1245}],
            )

        assert register.await_args.kwargs["trigger_data"] == {
            "repos": ["theexperiencecompany/gaia"]
        }

    async def test_an_empty_scope_sends_no_registration_config(self) -> None:
        # An empty scope dict must collapse to None so it is not stored as {} and
        # the account-level path stays "no trigger_data" rather than "empty config".
        register, _ = self._register()
        with patch(f"{_MOD}.register_subscription", register):
            await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                scope={},
            )

        assert register.await_args.kwargs["trigger_data"] is None

    async def test_a_missing_required_scope_is_rejected_before_registration(self) -> None:
        # github needs repos; without it the tool refuses and never calls Composio,
        # instead of registering a watch against no resource.
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, trigger_name="github_pr_event", action="notify"
            )

        assert "requires a 'repos' scope" in out
        assert "Matchable fields for github_pr_event" in out  # the catalog rides along
        register.assert_not_awaited()

    async def test_an_unknown_scope_key_is_rejected_before_registration(self) -> None:
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name="github_pr_event",
                action="notify",
                scope={"repos": ["o/n"], "branch": "main"},
            )

        assert "'branch' is not a scope field on 'github_pr_event'" in out
        register.assert_not_awaited()

    async def test_multiple_scope_errors_are_joined_by_a_single_space(self) -> None:
        # An unknown key AND the missing required repos: both errors must reach the
        # model, space-separated (not run together or padded).
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name="github_pr_event",
                action="notify",
                scope={"branch": "main"},
            )

        unknown = "'branch' is not a scope field on 'github_pr_event'. Scope fields: repos."
        missing = (
            "'github_pr_event' requires a 'repos' scope "
            "(List of repositories in owner/repo format); none was provided."
        )
        assert f"Error: {unknown} {missing}" in out
        register.assert_not_awaited()

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

    async def test_several_repairs_are_reported_on_one_line_joined_by_semicolons(self) -> None:
        # Two repairs must both surface, joined by '; ' behind the exact
        # 'Repaired automatically: ' prefix — not run together or relabelled.
        cond = SubscriptionCondition(
            field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-1"
        )
        outcome = ValidationOutcome(
            conditions=[cond],
            repairs=[
                ConditionRepair(original=cond, repaired=cond, reason="first fix"),
                ConditionRepair(original=cond, repaired=cond, reason="second fix"),
            ],
        )
        with patch(
            f"{_MOD}.register_subscription", AsyncMock(return_value=(_subscription(), outcome))
        ):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, trigger_name=GMAIL, action="execute"
            )

        (line,) = [ln for ln in out.splitlines() if ln.startswith("Repaired automatically: ")]
        assert line == "Repaired automatically: first fix; second fix"

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
        assert ", ".join(a.value for a in SubscriptionAction) in out
        register.assert_not_awaited()

    async def test_an_invalid_match_mode_is_rejected_with_the_valid_ones(self) -> None:
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                match="both",
            )

        assert "not a valid match mode" in out
        assert ", ".join(m.value for m in ConditionMatch) in out
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
        assert ", ".join(o.value for o in ConditionOperator) in out
        assert "Matchable fields" in out
        register.assert_not_awaited()

    async def test_a_condition_missing_only_its_value_is_rejected(self) -> None:
        # field_name and operator are valid strings but value is absent — the
        # 'or value is None' arm of the guard is the only thing that catches it.
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                conditions=[{"field_name": "thread_id", "operator": "equals"}],
            )

        assert "each condition needs" in out
        register.assert_not_awaited()

    async def test_a_condition_with_a_non_string_field_name_is_rejected(self) -> None:
        # field_name is not a str; the first arm of the guard must catch it before
        # it reaches typed-condition construction.
        register = AsyncMock()
        with patch(f"{_MOD}.register_subscription", register):
            out = await subscribe_todo_to_trigger.coroutine(
                config=_config(),
                todo_id=TODO_ID,
                trigger_name=GMAIL,
                action="execute",
                conditions=[{"field_name": 123, "operator": "equals", "value": "x"}],
            )

        assert "each condition needs" in out
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

    async def test_a_config_with_no_metadata_is_refused_not_crashed(self) -> None:
        # A config with no 'metadata' key must fall back to an empty dict, not
        # None — .get on None would AttributeError instead of a clean refusal.
        out = await subscribe_todo_to_trigger.coroutine(
            config={}, todo_id=TODO_ID, trigger_name=GMAIL, action="execute"
        )

        assert "user_id not found" in out


class TestUnsubscribe:
    async def test_it_reports_what_stopped_being_watched(self) -> None:
        unregister = AsyncMock(return_value=_subscription())
        with patch(f"{_MOD}.unregister_subscription", unregister):
            out = await unsubscribe_todo_from_trigger.coroutine(
                config=_config(), todo_id=TODO_ID, subscription_id="sub-1"
            )

        assert f"stopped watching {GMAIL}" in out
        # It must unregister THIS todo/user/subscription — a swapped arg drops the
        # wrong watch or none at all.
        unregister.assert_awaited_once_with(TODO_ID, USER_ID, "sub-1")

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

    async def test_a_config_with_no_metadata_is_refused_not_crashed(self) -> None:
        out = await unsubscribe_todo_from_trigger.coroutine(
            config={}, todo_id=TODO_ID, subscription_id="sub-1"
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
        doc = _todo(trigger_subscriptions=[_subscription(status=TriggerSubscriptionStatus.PAUSED)])

        assert "PAUSED" in _format_tracked_todo_full(doc, datetime.now(UTC))

    def test_a_todo_with_no_watches_renders_unchanged(self) -> None:
        assert "Watching" not in _format_tracked_todo_full(_todo(), datetime.now(UTC))


class TestFormatSubscriptionLines:
    """The exact watch line: the join word encodes AND vs OR semantics, and the paused marker tells the user their watch is dead — both must be verbatim."""

    @staticmethod
    def _two_conditions() -> list[SubscriptionCondition]:
        return [
            SubscriptionCondition(
                field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-1"
            ),
            SubscriptionCondition(
                field_name="sender", operator=ConditionOperator.EQUALS, value="a@b.c"
            ),
        ]

    def test_all_match_joins_conditions_with_and(self) -> None:
        sub = _subscription(match=ConditionMatch.ALL, conditions=self._two_conditions())
        (line,) = _format_subscription_lines(_todo(trigger_subscriptions=[sub]))

        assert line == (
            f"Watching {GMAIL} -> execute when "
            "thread_id equals t-1 AND sender equals a@b.c"
            f" (subscription: {sub.id})"
        )

    def test_any_match_joins_conditions_with_or(self) -> None:
        sub = _subscription(match=ConditionMatch.ANY, conditions=self._two_conditions())
        (line,) = _format_subscription_lines(_todo(trigger_subscriptions=[sub]))

        assert line == (
            f"Watching {GMAIL} -> execute when "
            "thread_id equals t-1 OR sender equals a@b.c"
            f" (subscription: {sub.id})"
        )

    def test_a_paused_watch_ends_with_the_disconnected_marker(self) -> None:
        sub = _subscription(status=TriggerSubscriptionStatus.PAUSED)
        (line,) = _format_subscription_lines(_todo(trigger_subscriptions=[sub]))

        assert line.endswith(" (PAUSED: integration disconnected)")

    def test_an_active_watch_ends_at_the_subscription_id_with_no_marker(self) -> None:
        sub = _subscription()
        (line,) = _format_subscription_lines(_todo(trigger_subscriptions=[sub]))

        assert line == f"Watching {GMAIL} -> execute when any event (subscription: {sub.id})"


class TestToolsAreReachable:
    """The subscription tools are always loaded, not semantically retrieved.

    A tool the model cannot see at the moment a reply-watching todo is created is
    a tool that never gets used — and retrieval only surfaces tools it was asked
    to search for.
    """

    def test_they_are_bound_to_the_executor_up_front(self) -> None:
        source = Path(build_graph.__file__).read_text()
        # Anchor on the executor's initial set directly: the builder passes it as the
        # initial_tools variable (["activate_integration", *EXECUTOR_INITIAL_TOOL_IDS]),
        # so parse that variable plus the module-level list it spreads.
        executor_fn = source.split("def build_executor_graph", 1)[1]
        initial_tools = executor_fn.split("initial_tools = [", 1)[1].split("]", 1)[0]
        module_ids = source.split("EXECUTOR_INITIAL_TOOL_IDS = [", 1)[1].split("]", 1)[0]
        executor_block = initial_tools + module_ids

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
