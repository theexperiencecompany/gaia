"""Condition evaluation against a raw webhook payload.

The absent-field cases carry the weight. External webhooks omit fields routinely,
so a missing field that counted as a match would fire a todo on an event that
never carried the thing it was watching for — and nothing downstream could tell.
"""

import pytest

from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    MatchableFieldType,
    SubscriptionCondition,
)
from app.services.triggers.condition_matching import (
    conditions_match,
    evaluate_condition,
    resolve_payload_value,
)

pytestmark = pytest.mark.unit

GMAIL = "gmail_new_message"
SHEETS = "google_sheets_new_row"
DOCS = "google_docs_document_updated"


def _c(field_name: str, operator: ConditionOperator, value: str | int | float):
    return SubscriptionCondition(field_name=field_name, operator=operator, value=value)


class TestResolvePayloadValue:
    def test_reads_a_top_level_field(self) -> None:
        assert resolve_payload_value({"thread_id": "t-1"}, "thread_id") == "t-1"

    def test_reads_one_level_of_dotting(self) -> None:
        assert resolve_payload_value({"document": {"id": "d-1"}}, "document.id") == "d-1"

    def test_missing_field_is_none(self) -> None:
        assert resolve_payload_value({}, "thread_id") is None

    def test_missing_nested_parent_is_none(self) -> None:
        assert resolve_payload_value({}, "document.id") is None

    def test_non_dict_parent_is_none(self) -> None:
        assert resolve_payload_value({"document": "not-an-object"}, "document.id") is None


class TestStringConditions:
    @pytest.mark.parametrize(
        ("operator", "value", "expected"),
        [
            (ConditionOperator.EQUALS, "t-1", True),
            (ConditionOperator.EQUALS, "t-2", False),
            (ConditionOperator.NOT_EQUALS, "t-2", True),
            (ConditionOperator.CONTAINS, "-", True),
            (ConditionOperator.NOT_CONTAINS, "zz", True),
            (ConditionOperator.STARTS_WITH, "t-", True),
            (ConditionOperator.STARTS_WITH, "x", False),
            (ConditionOperator.ENDS_WITH, "1", True),
        ],
    )
    def test_operators(self, operator: ConditionOperator, value: str, expected: bool) -> None:
        assert (
            conditions_match(GMAIL, [_c("thread_id", operator, value)], {"thread_id": "t-1"})
            is expected
        )

    def test_an_absent_field_never_matches(self) -> None:
        assert (
            conditions_match(GMAIL, [_c("thread_id", ConditionOperator.EQUALS, "t-1")], {}) is False
        )

    def test_an_absent_field_does_not_satisfy_a_negative_operator(self) -> None:
        # The tempting reading is "the payload does not contain 'spam', so
        # not_contains holds". It does not: the event never carried the field, so
        # there is nothing to have judged.
        assert (
            conditions_match(GMAIL, [_c("subject", ConditionOperator.NOT_CONTAINS, "spam")], {})
            is False
        )


class TestNumericConditions:
    @pytest.mark.parametrize(
        ("operator", "value", "expected"),
        [
            (ConditionOperator.EQUALS, 42, True),
            (ConditionOperator.NOT_EQUALS, 41, True),
            (ConditionOperator.GREATER_THAN, 41, True),
            (ConditionOperator.GREATER_THAN, 42, False),
            (ConditionOperator.GREATER_OR_EQUAL, 42, True),
            (ConditionOperator.LESS_THAN, 43, True),
            (ConditionOperator.LESS_OR_EQUAL, 42, True),
        ],
    )
    def test_operators(self, operator: ConditionOperator, value: int, expected: bool) -> None:
        payload = {"row_number": 42}
        assert conditions_match(SHEETS, [_c("row_number", operator, value)], payload) is expected

    def test_a_non_numeric_payload_value_does_not_match(self) -> None:
        payload = {"row_number": "not-a-number"}
        assert (
            conditions_match(SHEETS, [_c("row_number", ConditionOperator.EQUALS, 42)], payload)
            is False
        )

    def test_a_boolean_is_not_a_number(self) -> None:
        # bool is an int subclass in Python, so True would otherwise equal 1.
        payload = {"row_number": True}
        assert (
            conditions_match(SHEETS, [_c("row_number", ConditionOperator.EQUALS, 1)], payload)
            is False
        )

    def test_less_than_is_strict_at_the_boundary(self) -> None:
        # actual == expected must NOT satisfy LESS_THAN (a `<=` here fires the
        # subscription on the exact boundary value it was meant to exclude).
        payload = {"row_number": 42}
        assert (
            conditions_match(SHEETS, [_c("row_number", ConditionOperator.LESS_THAN, 42)], payload)
            is False
        )


class TestListConditions:
    def test_contains_is_membership_not_substring(self) -> None:
        payload = {"label_ids": ["INBOX", "UNREAD"]}
        assert conditions_match(
            GMAIL, [_c("label_ids", ConditionOperator.CONTAINS, "INBOX")], payload
        )
        # "INBO" is a substring of a member but not a member.
        assert not conditions_match(
            GMAIL, [_c("label_ids", ConditionOperator.CONTAINS, "INBO")], payload
        )

    def test_not_contains(self) -> None:
        payload = {"label_ids": ["INBOX"]}
        assert conditions_match(
            GMAIL, [_c("label_ids", ConditionOperator.NOT_CONTAINS, "SPAM")], payload
        )

    def test_a_non_list_payload_value_does_not_match(self) -> None:
        payload = {"label_ids": "INBOX"}
        assert (
            conditions_match(GMAIL, [_c("label_ids", ConditionOperator.CONTAINS, "INBOX")], payload)
            is False
        )

    def test_a_non_membership_operator_never_matches_a_list(self) -> None:
        # Only CONTAINS / NOT_CONTAINS have meaning on a list; anything else
        # (here EQUALS) must fall through to no-match, not accidentally fire.
        payload = {"label_ids": ["INBOX"]}
        assert (
            conditions_match(GMAIL, [_c("label_ids", ConditionOperator.EQUALS, "INBOX")], payload)
            is False
        )


class TestChainSemantics:
    def test_no_conditions_matches_every_event(self) -> None:
        assert conditions_match(GMAIL, [], {"thread_id": "anything"}) is True

    def test_every_condition_must_hold(self) -> None:
        payload = {"thread_id": "t-1", "sender": "alice@acme.com"}
        both = [
            _c("thread_id", ConditionOperator.EQUALS, "t-1"),
            _c("sender", ConditionOperator.EQUALS, "alice@acme.com"),
        ]
        assert conditions_match(GMAIL, both, payload) is True

    def test_one_failing_condition_fails_the_chain(self) -> None:
        payload = {"thread_id": "t-1", "sender": "bob@acme.com"}
        both = [
            _c("thread_id", ConditionOperator.EQUALS, "t-1"),
            _c("sender", ConditionOperator.EQUALS, "alice@acme.com"),
        ]
        assert conditions_match(GMAIL, both, payload) is False

    def test_a_field_no_longer_in_the_catalog_does_not_match(self) -> None:
        # Ignoring it would silently widen the subscription the moment a payload
        # schema changed upstream — the todo would start firing on everything.
        payload = {"retired_field": "x"}
        assert (
            conditions_match(GMAIL, [_c("retired_field", ConditionOperator.EQUALS, "x")], payload)
            is False
        )

    def test_an_unknown_trigger_never_matches(self) -> None:
        assert conditions_match("not_a_trigger", [], {"anything": 1}) is False

    def test_dotted_field_matches_through_a_nested_payload(self) -> None:
        payload = {"document": {"id": "d-1", "name": "Q3"}, "event_type": "document.updated"}
        assert conditions_match(DOCS, [_c("document.id", ConditionOperator.EQUALS, "d-1")], payload)


class TestAnyMatch:
    """`match=ANY` is a flat OR — one true condition fires it.

    This is how a single subscription watches "from acme.com OR from northwind.com"
    without splitting into two. The ALL default is exercised throughout
    TestChainSemantics; here we pin that ANY genuinely diverges from it.
    """

    def _senders(self) -> list[SubscriptionCondition]:
        return [
            _c("sender", ConditionOperator.CONTAINS, "acme.com"),
            _c("sender", ConditionOperator.CONTAINS, "northwind.com"),
        ]

    def test_any_fires_when_only_the_second_condition_holds(self) -> None:
        payload = {"sender": "ap@northwind.com"}
        # ALL would reject this (acme.com is absent); ANY must accept it.
        assert conditions_match(GMAIL, self._senders(), payload, ConditionMatch.ALL) is False
        assert conditions_match(GMAIL, self._senders(), payload, ConditionMatch.ANY) is True

    def test_any_fires_when_the_first_condition_holds(self) -> None:
        payload = {"sender": "billing@acme.com"}
        assert conditions_match(GMAIL, self._senders(), payload, ConditionMatch.ANY) is True

    def test_any_rejects_when_no_condition_holds(self) -> None:
        payload = {"sender": "someone@else.com"}
        assert conditions_match(GMAIL, self._senders(), payload, ConditionMatch.ANY) is False

    def test_any_with_no_conditions_still_fires_on_every_event(self) -> None:
        # Empty conditions mean "any event" regardless of the mode.
        assert conditions_match(GMAIL, [], {"sender": "x"}, ConditionMatch.ANY) is True

    def test_any_ignores_a_field_missing_from_the_catalog(self) -> None:
        # A retired field can never contribute a True, even under ANY — the same
        # anti-silent-widening rule the AND chain enforces.
        conditions = [
            _c("retired_field", ConditionOperator.EQUALS, "x"),
            _c("sender", ConditionOperator.CONTAINS, "acme.com"),
        ]
        assert (
            conditions_match(
                GMAIL,
                conditions,
                {"sender": "a@acme.com", "retired_field": "x"},
                ConditionMatch.ANY,
            )
            is True
        )
        assert (
            conditions_match(
                GMAIL,
                conditions,
                {"sender": "a@else.com", "retired_field": "x"},
                ConditionMatch.ANY,
            )
            is False
        )


class TestComparatorFallthrough:
    """An operator no comparator branch handles must return exactly ``False`` —
    never ``None`` or ``True``.

    A ``None`` collapses to falsy in the AND/OR chain, so ``conditions_match``
    alone cannot tell it apart from a real no-match; asserting on
    ``evaluate_condition`` directly is what pins the wildcard default. A ``True``
    default would fire a subscription on an operator that was never meant to
    apply to the field's type.
    """

    def test_a_string_field_with_a_numeric_operator_is_exactly_false(self) -> None:
        cond = _c("subject", ConditionOperator.GREATER_THAN, "x")
        assert evaluate_condition(cond, {"subject": "hello"}, MatchableFieldType.STRING) is False

    def test_a_numeric_field_with_a_membership_operator_is_exactly_false(self) -> None:
        cond = _c("row_number", ConditionOperator.CONTAINS, 42)
        assert evaluate_condition(cond, {"row_number": 42}, MatchableFieldType.INTEGER) is False
