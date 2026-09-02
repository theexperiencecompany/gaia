"""Validate subscription conditions against a trigger's matchable-field catalog.

This is the deterministic first stage. It fixes what can be fixed without asking a
model — a camelCased field name, an operator that is a category error for the
field's type, a number arriving as a string — and rejects everything else loudly,
naming the fields that do exist. Only genuinely ambiguous failures are worth an
LLM repair pass, and that pass is the caller's decision, not this module's.

Nothing here approximates. A repair either preserves the condition's meaning or it
does not happen: a subscription that "nearly" matches executes todos on the wrong
event, which is worse than refusing to store it.
"""

from difflib import get_close_matches

from pydantic import BaseModel, Field

from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionOperator,
    MatchableField,
    MatchableFieldType,
    MatchableTrigger,
    SubscriptionCondition,
)
from app.services.triggers.matchable_fields import get_matchable_trigger

# Below this ratio a "close" name is a different field, and picking it would
# silently rewrite what the user asked to watch.
_FUZZY_CUTOFF = 0.8

_NUMERIC_TYPES = frozenset({MatchableFieldType.INTEGER, MatchableFieldType.NUMBER})

# Operator category errors with exactly one faithful reading. Anything not listed
# is a rejection, not a guess — see the module docstring.
_OPERATOR_CORRECTIONS: dict[
    tuple[MatchableFieldType, ConditionOperator], tuple[ConditionOperator, str]
] = {
    (MatchableFieldType.STRING_LIST, ConditionOperator.EQUALS): (
        ConditionOperator.CONTAINS,
        "equality on a list field means membership",
    ),
    (MatchableFieldType.STRING_LIST, ConditionOperator.NOT_EQUALS): (
        ConditionOperator.NOT_CONTAINS,
        "inequality on a list field means non-membership",
    ),
    (MatchableFieldType.INTEGER, ConditionOperator.CONTAINS): (
        ConditionOperator.EQUALS,
        "a number has no substring to contain",
    ),
    (MatchableFieldType.NUMBER, ConditionOperator.CONTAINS): (
        ConditionOperator.EQUALS,
        "a number has no substring to contain",
    ),
    (MatchableFieldType.INTEGER, ConditionOperator.NOT_CONTAINS): (
        ConditionOperator.NOT_EQUALS,
        "a number has no substring to contain",
    ),
    (MatchableFieldType.NUMBER, ConditionOperator.NOT_CONTAINS): (
        ConditionOperator.NOT_EQUALS,
        "a number has no substring to contain",
    ),
}


class ConditionRepair(BaseModel):
    """One mechanical fix, recorded so the wide event can show what changed."""

    model_config = {"frozen": True}

    original: SubscriptionCondition
    repaired: SubscriptionCondition
    reason: str


class ValidationOutcome(BaseModel):
    """Validated conditions, what was repaired to get them, and what could not be."""

    conditions: list[SubscriptionCondition] = Field(default_factory=list)
    repairs: list[ConditionRepair] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _normalize(name: str) -> str:
    """``threadId``, ``thread-id`` and ``Thread Id`` all collapse to ``threadid``."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _resolve_field(entry: MatchableTrigger, name: str) -> tuple[MatchableField | None, str | None]:
    """The catalog field ``name`` refers to, plus a reason when it had to be repaired."""
    exact = entry.field(name)
    if exact is not None:
        return exact, None

    normalized = _normalize(name)
    for candidate in entry.fields:
        if _normalize(candidate.name) == normalized:
            return candidate, f"'{name}' is '{candidate.name}' in this trigger's payload"

    close = get_close_matches(name, list(entry.field_names), n=1, cutoff=_FUZZY_CUTOFF)
    if close:
        matched = entry.field(close[0])
        if matched is not None:
            return matched, f"'{name}' looks like '{matched.name}'"
    return None, None


def _coerce_value(
    value: str | int | float, field: MatchableField
) -> tuple[str | int | float | None, str | None]:
    """Fit ``value`` to the field's type, or return None when it cannot be."""
    if field.type is MatchableFieldType.INTEGER:
        if isinstance(value, int):
            return value, None
        try:
            return int(str(value)), f"'{value}' coerced to an integer for '{field.name}'"
        except ValueError:
            return None, None
    if field.type is MatchableFieldType.NUMBER:
        if isinstance(value, int | float):
            return float(value), None
        try:
            return float(str(value)), f"'{value}' coerced to a number for '{field.name}'"
        except ValueError:
            return None, None
    # STRING and STRING_LIST both compare against text.
    if isinstance(value, str):
        return value, None
    return str(value), f"'{value}' rendered as text for '{field.name}'"


def _unknown_field_error(entry: MatchableTrigger, trigger_name: str, name: str) -> str:
    return (
        f"'{name}' is not a matchable field on '{trigger_name}'. "
        f"Available fields: {', '.join(entry.field_names)}."
    )


def _bad_operator_error(field: MatchableField, operator: ConditionOperator) -> str:
    allowed = sorted(OPERATORS_BY_FIELD_TYPE[field.type])
    return (
        f"'{operator}' does not apply to '{field.name}', which is a {field.type}. "
        f"Valid operators: {', '.join(allowed)}."
    )


def _validate_one(
    entry: MatchableTrigger, trigger_name: str, condition: SubscriptionCondition
) -> tuple[SubscriptionCondition | None, list[str], str | None]:
    """Validate and mechanically repair one condition.

    Returns the usable condition (or None), any errors, and a repair reason when
    the returned condition differs from the input.
    """
    field, name_reason = _resolve_field(entry, condition.field_name)
    if field is None:
        return None, [_unknown_field_error(entry, trigger_name, condition.field_name)], None

    reasons = [name_reason] if name_reason else []

    operator = condition.operator
    if operator not in OPERATORS_BY_FIELD_TYPE[field.type]:
        correction = _OPERATOR_CORRECTIONS.get((field.type, operator))
        if correction is None:
            return None, [_bad_operator_error(field, operator)], None
        operator, operator_reason = correction
        reasons.append(f"'{condition.operator}' became '{operator}' — {operator_reason}")

    value, value_reason = _coerce_value(condition.value, field)
    if value is None:
        return (
            None,
            [f"'{condition.value}' is not a valid {field.type} for '{field.name}'."],
            None,
        )
    if value_reason:
        reasons.append(value_reason)

    repaired = SubscriptionCondition(field_name=field.name, operator=operator, value=value)
    return repaired, [], "; ".join(reasons) if reasons else None


def validate_conditions(
    trigger_name: str, conditions: list[SubscriptionCondition]
) -> ValidationOutcome:
    """Check ``conditions`` against ``trigger_name``'s catalog, repairing what is safe.

    A subscription with no conditions is valid — it fires on every event for that
    trigger, which is the right default for a narrowly-scoped per-resource trigger.
    """
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        return ValidationOutcome(
            errors=[f"'{trigger_name}' is not a subscribable trigger."],
        )

    outcome = ValidationOutcome()
    for condition in conditions:
        repaired, errors, reason = _validate_one(entry, trigger_name, condition)
        if errors:
            outcome.errors.extend(errors)
            continue
        if repaired is None:
            continue
        outcome.conditions.append(repaired)
        if reason:
            outcome.repairs.append(
                ConditionRepair(original=condition, repaired=repaired, reason=reason)
            )
    return outcome
