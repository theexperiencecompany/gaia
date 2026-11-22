"""What the agent reads and writes about an app event's fields when it subscribes to one.

The catalog of a trigger's matchable fields and scope, and the parsing of the loose
condition arguments a subscribe tool takes, shared by every tool that subscribes.
"""

from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionArgs,
    ConditionMatch,
    ConditionOperator,
    SubscriptionCondition,
)
from app.services.triggers.matchable_fields import MATCHABLE_TRIGGERS, get_matchable_trigger
from app.services.triggers.scope_catalog import scope_fields_for


def render_catalog(trigger_name: str) -> str:
    """The matchable fields for a trigger, as the model should see them."""
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        available = ", ".join(sorted(MATCHABLE_TRIGGERS))
        return f"'{trigger_name}' is not a subscribable trigger. Available triggers: {available}"

    lines = [f"Matchable fields for {trigger_name}:"]
    lines.extend(
        f"  {f.name} ({f.type}): {f.description}. Example: {f.example}" for f in entry.fields
    )
    scope = scope_fields_for(trigger_name)
    if scope:
        lines.append("Scope this watch with (registration config, passed via the scope argument):")
        lines.extend(
            f"  {s.name} ({s.type}{', required' if s.required else ''}): {s.description}"
            for s in scope
        )
    if entry.excluded:
        lines.append("Not matchable:")
        lines.extend(f"  {name}: {reason}" for name, reason in sorted(entry.excluded.items()))
    lines.append(
        "Operators by type: "
        + "; ".join(
            f"{field_type} -> {', '.join(sorted(ops))}"
            for field_type, ops in OPERATORS_BY_FIELD_TYPE.items()
        )
    )
    return "\n".join(lines)


def parse_match(match: str) -> ConditionMatch | None:
    try:
        return ConditionMatch(match.strip().lower())
    except ValueError:
        return None


def parse_conditions(
    raw: list[dict[str, str | int | float]],
) -> tuple[list[SubscriptionCondition], str | None]:
    """Turn the tool's loose condition dicts into typed conditions.

    Shape errors are caught here and reported with the catalog rather than raising
    a validation traceback the model cannot read.
    """
    parsed: list[SubscriptionCondition] = []
    for item in raw:
        args = ConditionArgs.model_validate(item)
        field_name, operator, value = args.field_name, args.operator, args.value
        if not isinstance(field_name, str) or not isinstance(operator, str) or value is None:
            return [], (f"each condition needs 'field_name', 'operator' and 'value'; got {item!r}")
        try:
            parsed_operator = ConditionOperator(operator.strip().lower())
        except ValueError:
            valid = ", ".join(o.value for o in ConditionOperator)
            return [], f"'{operator}' is not a valid operator. Valid operators: {valid}."
        parsed.append(
            SubscriptionCondition(field_name=field_name, operator=parsed_operator, value=value)
        )
    return parsed, None
