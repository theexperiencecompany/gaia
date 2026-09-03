"""Trigger subscriptions: the vocabulary a tracked todo uses to watch an event.

Split from ``todo_models`` because none of it is todo-specific — the matchable-field
catalog, the operator table, and the condition shape all describe triggers, and the
dispatch path needs them without importing the todo domain.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MatchableFieldType(StrEnum):
    """The payload types a condition can be written against.

    ``INTEGER`` and ``NUMBER`` share an operator set but stay distinct so the
    catalog can be checked against the payload model's real annotation.
    """

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    STRING_LIST = "string_list"


class ConditionOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    GREATER_THAN = "greater_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_THAN = "less_than"
    LESS_OR_EQUAL = "less_or_equal"


_TEXT_OPERATORS = frozenset(
    {
        ConditionOperator.EQUALS,
        ConditionOperator.NOT_EQUALS,
        ConditionOperator.CONTAINS,
        ConditionOperator.NOT_CONTAINS,
        ConditionOperator.STARTS_WITH,
        ConditionOperator.ENDS_WITH,
    }
)

_NUMERIC_OPERATORS = frozenset(
    {
        ConditionOperator.EQUALS,
        ConditionOperator.NOT_EQUALS,
        ConditionOperator.GREATER_THAN,
        ConditionOperator.GREATER_OR_EQUAL,
        ConditionOperator.LESS_THAN,
        ConditionOperator.LESS_OR_EQUAL,
    }
)

# On a list field the operators test membership, not substring.
_LIST_OPERATORS = frozenset({ConditionOperator.CONTAINS, ConditionOperator.NOT_CONTAINS})

OPERATORS_BY_FIELD_TYPE: Mapping[MatchableFieldType, frozenset[ConditionOperator]] = {
    MatchableFieldType.STRING: _TEXT_OPERATORS,
    MatchableFieldType.INTEGER: _NUMERIC_OPERATORS,
    MatchableFieldType.NUMBER: _NUMERIC_OPERATORS,
    MatchableFieldType.STRING_LIST: _LIST_OPERATORS,
}


class MatchableField(BaseModel):
    """One payload field a condition may reference, as the model will see it."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: MatchableFieldType
    description: str
    example: str


class MatchableTrigger(BaseModel):
    """A trigger's curated field set, plus why anything verified was left out.

    ``payload_model`` is the schema the fields were derived from; it is excluded
    from serialization because the catalog is handed to an LLM as data.
    """

    model_config = ConfigDict(frozen=True)

    payload_model: type[BaseModel] = Field(exclude=True)
    fields: tuple[MatchableField, ...]
    excluded: Mapping[str, str] = Field(
        default_factory=dict,
        description="Payload field name -> why it is not matchable",
    )

    def field(self, name: str) -> MatchableField | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


class SubscriptionAction(StrEnum):
    """What firing a subscription does to its todo."""

    EXECUTE = "execute"
    NOTIFY = "notify"
    COMPLETE = "complete"
    UNBLOCK = "unblock"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    # Set when the integration behind the subscription loses its connection.
    PAUSED = "paused"


class SubscriptionResolution(StrEnum):
    """How dispatch finds this subscription when its trigger fires.

    Account-level triggers (Gmail) register no per-subscriber Composio instance,
    so they can only be resolved by user and trigger name.
    """

    TRIGGER_ID = "trigger_id"
    ACCOUNT = "account"


class ConditionMatch(StrEnum):
    """How a subscription's conditions combine.

    ``ALL`` is the AND-chain default. ``ANY`` is a flat OR — one true condition
    fires it. There is deliberately no nesting: an OR-of-ANDs is expressed as
    several ``ALL`` subscriptions on the same todo, which already covers every
    boolean shape these payloads need without an expression language in the hot
    path that evaluates every webhook for every subscriber.
    """

    ALL = "all"
    ANY = "any"


class SubscriptionCondition(BaseModel):
    """One ``field op value`` test against a trigger payload."""

    model_config = ConfigDict(frozen=True)

    field_name: str = Field(description="A field name from the trigger's matchable catalog")
    operator: ConditionOperator
    value: str | int | float


class TriggerSubscription(BaseModel):
    """A tracked todo's standing interest in one trigger."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    trigger_name: str
    conditions: list[SubscriptionCondition] = Field(default_factory=list)
    match: ConditionMatch = Field(
        default=ConditionMatch.ALL,
        description="Whether all conditions must hold (AND) or any one (OR)",
    )
    action: SubscriptionAction
    cooldown_seconds: int = Field(
        default=900,
        ge=0,
        description="Minimum gap between two fires of this subscription",
    )
    resolution: SubscriptionResolution
    composio_trigger_ids: list[str] = Field(
        default_factory=list,
        description="Empty for account-level triggers, which register no instance",
    )
    trigger_data: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Registration-time knobs the payload cannot express (a calendar's "
            "minutes_before_start). Persisted so a resync rebuilds the trigger "
            "with the user's original config instead of resetting to defaults."
        ),
    )
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _persist_defaults(self) -> "TriggerSubscription":
        """Mark every field as explicitly set, so a stored subscription is whole.

        Todo updates serialize with ``model_dump(exclude_unset=True)``, which
        recurses: a nested field left at its default is dropped before it reaches
        Mongo. That silently stored subscriptions with no ``id``, no ``status``
        and no ``created_at`` — and dispatch matches on ``status``, so every one
        of them was unfindable and the watch never fired. Nothing failed; the
        subscription simply did not exist as far as the query was concerned.
        """
        self.__pydantic_fields_set__.update(type(self).model_fields.keys())
        return self


class TriggerOrigin(BaseModel):
    """Why a tracked-todo execution ran, when a subscription woke it.

    Threaded as an explicit task parameter rather than inferred: the execution
    path hardcodes ``scheduled_todo`` at four places, and the retry re-enqueue
    passes only the todo id — so without carrying this, a retried trigger run
    silently becomes an ordinary scheduled run and loses both its attribution and
    the payload the todo was woken to act on.
    """

    model_config = ConfigDict(frozen=True)

    subscription_id: str
    trigger_name: str
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="The webhook payload that matched, for the agent's context",
    )
    defer_attempts: int = Field(
        default=0,
        description="How many times this fire was re-enqueued past a held execution lock",
    )
