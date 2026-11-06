"""The gate a workflow or a todo subscription carries: GAIA's or the user's condition, or a code preset.

None on the owner means it never had a gate; enabled=False means the user turned it
off and its text is kept, so turning it back on restores it.
"""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.trigger_gates import (
    QUIET_HOURS_BYPASS_SUMMARY,
    QUIET_HOURS_HELD_SUMMARY,
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_CONDITION_MAX_CHARS,
    GateAuthor,
    GateKind,
    GateOutcome,
    SystemGatePreset,
)


class GateSkipRecord(BaseModel):
    """One event a gate kept from running its job."""

    model_config = ConfigDict(frozen=True)

    event: str = Field(
        description="The skipped event as a person reads it: an email's sender and subject"
    )
    reason: str = Field(description="The condition the event missed and how sure the gate was")
    at: datetime


class _StoredGate(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Newest last, at most GATE_RECENT_SKIPS_KEPT; skipped_count counts every skip ever.
    recent_skips: list[GateSkipRecord] = Field(default_factory=list)
    skipped_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _persist_defaults(self) -> Self:
        # Owners are written with exclude_unset, which recurses: a defaulted kind
        # left unset is dropped, and the stored gate no longer loads.
        self.__pydantic_fields_set__.update(type(self).model_fields.keys())
        return self


class AuthoredGate(_StoredGate):
    """A plain-text condition, shown to the user as "Runs only when: <condition>"."""

    kind: Literal[GateKind.AUTHORED] = GateKind.AUTHORED
    condition: str = Field(min_length=1, max_length=TRIGGER_GATE_CONDITION_MAX_CHARS)
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


class AuthoredGateEdit(BaseModel):
    """A condition as a client sends it; the server decides who wrote it."""

    model_config = ConfigDict(frozen=True)

    condition: str = Field(min_length=1, max_length=TRIGGER_GATE_CONDITION_MAX_CHARS)
    enabled: bool = True

    def applied_to(self, current: AuthoredGate | SystemGate | None) -> AuthoredGate:
        """Return the stored gate: an unchanged condition keeps its author, a new one is the user's."""
        if isinstance(current, AuthoredGate) and current.condition == self.condition:
            author = current.author
        else:
            author = GateAuthor.USER
        return AuthoredGate(condition=self.condition, author=author, enabled=self.enabled)


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
