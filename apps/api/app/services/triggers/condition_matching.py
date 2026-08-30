"""Evaluate a subscription's conditions against a fired trigger's payload.

Deliberately boring: an AND-chain of ``field op value`` tests over the curated
matchable fields, evaluated in-process. No expression language, no sandbox, no
LLM — this runs on every webhook event for every subscriber, so it has to cost
nothing and behave the same way every time.

A condition whose field is missing from the payload does NOT match. External
webhooks omit fields routinely, and treating "absent" as "matches" would fire a
todo on an event that never carried the thing it was watching for.
"""

from typing import Any

from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    MatchableFieldType,
    SubscriptionCondition,
)
from app.services.triggers.matchable_fields import get_matchable_trigger


def resolve_payload_value(payload: dict[str, Any], field_name: str) -> object | None:
    """Read ``field_name`` (one level of dotting allowed) out of a raw payload."""
    current: object = payload
    for segment in field_name.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
        if current is None:
            return None
    return current


def _compare_text(operator: ConditionOperator, actual: str, expected: str) -> bool:
    match operator:
        case ConditionOperator.EQUALS:
            return actual == expected
        case ConditionOperator.NOT_EQUALS:
            return actual != expected
        case ConditionOperator.CONTAINS:
            return expected in actual
        case ConditionOperator.NOT_CONTAINS:
            return expected not in actual
        case ConditionOperator.STARTS_WITH:
            return actual.startswith(expected)
        case ConditionOperator.ENDS_WITH:
            return actual.endswith(expected)
        case _:
            return False


def _compare_number(operator: ConditionOperator, actual: float, expected: float) -> bool:
    match operator:
        case ConditionOperator.EQUALS:
            return actual == expected
        case ConditionOperator.NOT_EQUALS:
            return actual != expected
        case ConditionOperator.GREATER_THAN:
            return actual > expected
        case ConditionOperator.GREATER_OR_EQUAL:
            return actual >= expected
        case ConditionOperator.LESS_THAN:
            return actual < expected
        case ConditionOperator.LESS_OR_EQUAL:
            return actual <= expected
        case _:
            return False


def _compare_list(operator: ConditionOperator, actual: list[object], expected: object) -> bool:
    contains = expected in actual
    if operator is ConditionOperator.CONTAINS:
        return contains
    if operator is ConditionOperator.NOT_CONTAINS:
        return not contains
    return False


def evaluate_condition(
    condition: SubscriptionCondition, payload: dict[str, Any], field_type: MatchableFieldType
) -> bool:
    """Does one condition hold against this payload?"""
    actual = resolve_payload_value(payload, condition.field_name)
    if actual is None:
        return False

    if field_type is MatchableFieldType.STRING_LIST:
        return (
            _compare_list(condition.operator, actual, condition.value)
            if isinstance(actual, list)
            else False
        )

    if field_type in (MatchableFieldType.INTEGER, MatchableFieldType.NUMBER):
        if isinstance(actual, bool) or not isinstance(actual, int | float):
            return False
        return _compare_number(condition.operator, float(actual), float(condition.value))

    return _compare_text(condition.operator, str(actual), str(condition.value))


def conditions_match(
    trigger_name: str,
    conditions: list[SubscriptionCondition],
    payload: dict[str, Any],
    match: ConditionMatch = ConditionMatch.ALL,
) -> bool:
    """Do a subscription's conditions hold against this payload?

    ``ALL`` is the AND-chain; ``ANY`` is a flat OR. No conditions means the
    subscription fires on every event for its trigger, which is the right default
    for a per-resource trigger already scoped to one channel, calendar or
    repository at registration time — regardless of ``match``.

    A condition naming a field the catalog no longer has does NOT match. The
    alternative — ignoring it — would silently widen a subscription the moment a
    payload schema changed upstream.
    """
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        return False

    if not conditions:
        return True

    def holds(condition: SubscriptionCondition) -> bool:
        field = entry.field(condition.field_name)
        return field is not None and evaluate_condition(condition, payload, field.type)

    if match is ConditionMatch.ANY:
        return any(holds(c) for c in conditions)
    return all(holds(c) for c in conditions)
