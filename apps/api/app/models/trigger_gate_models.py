"""The gate a workflow or a todo subscription carries: GAIA's or the user's condition, or a code preset.

None on the owner means it never had a gate; enabled=False means the user turned it
off and its text is kept, so turning it back on restores it.
"""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

from app.constants.trigger_gates import (
    ENFORCED_GATE_KINDS,
    QUIET_HOURS_BYPASS_SUMMARY,
    QUIET_HOURS_HELD_SUMMARY,
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_CONDITION_MAX_CHARS,
    GateAuthor,
    GateKind,
    GateOutcome,
    SystemGatePreset,
)
from app.schemas.common import ResponseModel

# The one shape of a condition: what GAIA drafts, what the user edits, what a gate stores.
GateCondition = Annotated[
    str, StringConstraints(min_length=1, max_length=TRIGGER_GATE_CONDITION_MAX_CHARS)
]


class GateSkipRecord(BaseModel):
    """One event a gate kept from running its job, as the gate's panel lists it."""

    model_config = ConfigDict(frozen=True)

    event: str = Field(
        description="The skipped event as a person reads it: an email's sender and subject"
    )
    at: datetime


class _StoredGate(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: GateKind
    # Newest last; a new condition starts with none, since the old skips do not describe it.
    recent_skips: list[GateSkipRecord] = Field(default_factory=list)

    @property
    def enforced(self) -> bool:
        """Whether this kind of gate may skip a run yet; any other kind is decided and still runs."""
        return self.kind in ENFORCED_GATE_KINDS

    @model_validator(mode="after")
    def _persist_defaults(self) -> Self:
        # Owners are written with exclude_unset, which recurses: a defaulted kind
        # left unset is dropped, and the stored gate no longer loads.
        self.__pydantic_fields_set__.update(type(self).model_fields.keys())
        return self


class AuthoredGate(_StoredGate):
    """A plain-text condition, shown to the user as "Runs only when: <condition>"."""

    kind: Literal[GateKind.AUTHORED] = GateKind.AUTHORED
    condition: GateCondition
    author: GateAuthor
    enabled: bool = True

    @property
    def display_condition(self) -> str:
        return self.condition


class SystemGate(_StoredGate):
    """A preset owned by code; its question and wording are read from the preset table."""

    kind: Literal[GateKind.SYSTEM] = GateKind.SYSTEM
    preset: SystemGatePreset
    enabled: bool = True

    @property
    def display_condition(self) -> str:
        return SYSTEM_GATE_PRESETS[self.preset].condition


TriggerGate = Annotated[AuthoredGate | SystemGate, Field(discriminator="kind")]


# The display text and enforced flag are read from code at the API edge, never stored:
# a stored gate serialised through a TriggerGate field drops both.
class AuthoredGateView(AuthoredGate, ResponseModel):
    """An authored gate as the API returns it, with what the user reads about it."""

    @computed_field  # type: ignore[prop-decorator]  # pydantic's computed_field over @property trips mypy's prop-decorator check
    @property
    def display_condition(self) -> str:
        return super().display_condition

    @computed_field  # type: ignore[prop-decorator]  # pydantic's computed_field over @property trips mypy's prop-decorator check
    @property
    def enforced(self) -> bool:
        return super().enforced


class SystemGateView(SystemGate, ResponseModel):
    """A system gate as the API returns it: its preset's wording, which the user cannot rewrite."""

    @computed_field  # type: ignore[prop-decorator]  # pydantic's computed_field over @property trips mypy's prop-decorator check
    @property
    def display_condition(self) -> str:
        return super().display_condition

    @computed_field  # type: ignore[prop-decorator]  # pydantic's computed_field over @property trips mypy's prop-decorator check
    @property
    def enforced(self) -> bool:
        return super().enforced


TriggerGateView = Annotated[AuthoredGateView | SystemGateView, Field(discriminator="kind")]


class GateEdit(BaseModel):
    """A gate as a client edits it: a new condition, or the current gate turned on or off.

    The server decides who wrote a condition. No condition keeps the current one,
    a system preset included, so turning a gate off never loses its text.
    """

    model_config = ConfigDict(frozen=True)

    condition: GateCondition | None = None
    enabled: bool = True


class QuietHoursBypass(BaseModel):
    """A run let through the user's quiet hours, with the reason it says it interrupts them."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[GateOutcome.BYPASS] = GateOutcome.BYPASS
    reason: str = Field(min_length=1)

    @property
    def summary(self) -> str:
        return QUIET_HOURS_BYPASS_SUMMARY.format(reason=self.reason)


class QuietHoursHold(BaseModel):
    """A run held until the user's quiet hours ended."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[GateOutcome.HOLD] = GateOutcome.HOLD

    @property
    def summary(self) -> str:
        return QUIET_HOURS_HELD_SUMMARY


# What a workflow run's context says quiet hours did to it.
QuietHoursStamp = Annotated[QuietHoursBypass | QuietHoursHold, Field(discriminator="kind")]
