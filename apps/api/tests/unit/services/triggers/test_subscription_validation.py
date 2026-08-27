"""Condition validation: what it repairs mechanically, and what it refuses to.

The refusals matter more than the repairs. A condition that is silently widened to
make it fit will fire a todo on the wrong event, and nothing downstream can tell.
"""

import pytest

from app.models.trigger_subscription_models import (
    ConditionOperator,
    MatchableFieldType,
    SubscriptionCondition,
)
from app.services.triggers.subscription_validation import validate_conditions

pytestmark = pytest.mark.unit

GMAIL = "gmail_new_message"
SHEETS = "google_sheets_new_row"


def _condition(
    field_name: str, operator: ConditionOperator, value: str | int | float
) -> SubscriptionCondition:
    return SubscriptionCondition(field_name=field_name, operator=operator, value=value)


class TestValidConditions:
    def test_a_correct_condition_passes_untouched(self) -> None:
        condition = _condition("thread_id", ConditionOperator.EQUALS, "18c9f0a1")
        outcome = validate_conditions(GMAIL, [condition])

        assert outcome.ok
        assert outcome.conditions == [condition]
        # The repair loop must not run when validation already passes.
        assert outcome.repairs == []

    def test_no_conditions_is_valid(self) -> None:
        outcome = validate_conditions(GMAIL, [])

        assert outcome.ok
        assert outcome.conditions == []

    def test_every_operator_valid_for_the_type_is_accepted(self) -> None:
        for operator in (
            ConditionOperator.EQUALS,
            ConditionOperator.NOT_EQUALS,
            ConditionOperator.CONTAINS,
            ConditionOperator.NOT_CONTAINS,
            ConditionOperator.STARTS_WITH,
            ConditionOperator.ENDS_WITH,
        ):
            outcome = validate_conditions(GMAIL, [_condition("subject", operator, "Invoice")])
            assert outcome.ok, f"{operator} rejected on a string field"

    def test_conditions_are_validated_independently(self) -> None:
        outcome = validate_conditions(
            GMAIL,
            [
                _condition("thread_id", ConditionOperator.EQUALS, "abc"),
                _condition("nonsense", ConditionOperator.EQUALS, "x"),
            ],
        )

        assert not outcome.ok
        # The good condition is not thrown away by the bad one's failure.
        assert [c.field_name for c in outcome.conditions] == ["thread_id"]


class TestMechanicalRepair:
    def test_camel_case_field_name_is_repaired_without_an_llm(self) -> None:
        outcome = validate_conditions(
            GMAIL, [_condition("threadId", ConditionOperator.EQUALS, "18c9f0a1")]
        )

        assert outcome.ok
        assert outcome.conditions[0].field_name == "thread_id"
        assert len(outcome.repairs) == 1
        assert "thread_id" in outcome.repairs[0].reason

    @pytest.mark.parametrize("written", ["thread-id", "Thread Id", "THREAD_ID"])
    def test_field_name_spelling_variants_normalize(self, written: str) -> None:
        outcome = validate_conditions(GMAIL, [_condition(written, ConditionOperator.EQUALS, "x")])

        assert outcome.ok
        assert outcome.conditions[0].field_name == "thread_id"

    def test_a_typo_is_repaired_by_fuzzy_match(self) -> None:
        outcome = validate_conditions(GMAIL, [_condition("subjekt", ConditionOperator.EQUALS, "x")])

        assert outcome.ok
        assert outcome.conditions[0].field_name == "subject"

    def test_equality_on_a_list_field_becomes_membership(self) -> None:
        outcome = validate_conditions(
            GMAIL, [_condition("label_ids", ConditionOperator.EQUALS, "INBOX")]
        )

        assert outcome.ok
        assert outcome.conditions[0].operator is ConditionOperator.CONTAINS
        assert "membership" in outcome.repairs[0].reason

    def test_contains_on_a_number_becomes_equality(self) -> None:
        outcome = validate_conditions(
            SHEETS, [_condition("row_number", ConditionOperator.CONTAINS, 42)]
        )

        assert outcome.ok
        assert outcome.conditions[0].operator is ConditionOperator.EQUALS

    def test_a_numeric_string_is_coerced_for_an_integer_field(self) -> None:
        outcome = validate_conditions(
            SHEETS, [_condition("row_number", ConditionOperator.EQUALS, "42")]
        )

        assert outcome.ok
        assert outcome.conditions[0].value == 42
        assert isinstance(outcome.conditions[0].value, int)

    def test_a_number_is_rendered_as_text_for_a_string_field(self) -> None:
        outcome = validate_conditions(GMAIL, [_condition("subject", ConditionOperator.EQUALS, 42)])

        assert outcome.ok
        assert outcome.conditions[0].value == "42"

    def test_repairs_record_the_original_condition(self) -> None:
        original = _condition("threadId", ConditionOperator.EQUALS, "abc")
        outcome = validate_conditions(GMAIL, [original])

        assert outcome.repairs[0].original == original
        assert outcome.repairs[0].repaired == outcome.conditions[0]


class TestRejection:
    def test_unknown_field_is_rejected_and_alternatives_are_named(self) -> None:
        outcome = validate_conditions(
            GMAIL, [_condition("recipient_domain", ConditionOperator.EQUALS, "acme.com")]
        )

        assert not outcome.ok
        assert outcome.conditions == []
        # The rejection must be actionable — it names the fields that do exist.
        assert "thread_id" in outcome.errors[0]
        assert "sender" in outcome.errors[0]

    def test_an_excluded_payload_field_is_not_matchable(self) -> None:
        # 'payload' is a real Gmail payload field, deliberately excluded from the
        # catalog. Accepting it would let a condition reference an unverified blob.
        outcome = validate_conditions(GMAIL, [_condition("payload", ConditionOperator.EQUALS, "x")])

        assert not outcome.ok

    def test_ordering_operator_on_a_string_is_rejected_not_guessed(self) -> None:
        outcome = validate_conditions(
            GMAIL, [_condition("subject", ConditionOperator.GREATER_THAN, "x")]
        )

        assert not outcome.ok
        assert "greater_than" in outcome.errors[0]
        assert str(MatchableFieldType.STRING) in outcome.errors[0]

    def test_substring_operator_on_a_list_is_rejected(self) -> None:
        outcome = validate_conditions(
            GMAIL, [_condition("label_ids", ConditionOperator.STARTS_WITH, "IN")]
        )

        assert not outcome.ok

    def test_non_numeric_value_for_an_integer_field_is_rejected(self) -> None:
        outcome = validate_conditions(
            SHEETS, [_condition("row_number", ConditionOperator.EQUALS, "not-a-number")]
        )

        assert not outcome.ok
        assert outcome.conditions == []

    def test_a_distant_name_is_rejected_rather_than_fuzzy_matched(self) -> None:
        # 'to' and 'from' are both short; a loose cutoff would rewrite one as the
        # other and watch the wrong side of the conversation.
        outcome = validate_conditions(
            GMAIL, [_condition("from", ConditionOperator.EQUALS, "a@b.c")]
        )

        assert not outcome.ok

    def test_unsubscribable_trigger_is_rejected(self) -> None:
        outcome = validate_conditions(
            "not_a_trigger", [_condition("thread_id", ConditionOperator.EQUALS, "x")]
        )

        assert not outcome.ok
        assert "not_a_trigger" in outcome.errors[0]
