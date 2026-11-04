"""The gate a workflow or a todo subscription carries: GAIA's or the user's condition, or a code preset.

None on the owner means it never had a gate; enabled=False means the user turned it
off and its text is kept, so turning it back on restores it.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.trigger_gates import (
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_CONDITION_MAX_CHARS,
    GateAuthor,
    GateKind,
    SystemGatePreset,
)


class _StoredGate(BaseModel):
    model_config = ConfigDict(frozen=True)

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
