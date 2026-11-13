"""A user's own limits on how much GAIA tells them unprompted, and when."""

from datetime import time
from typing import Annotated, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.constants.outbox_attention import (
    ATTENTION_RULE_MAX_CHARS,
    ATTENTION_RULES_MAX,
    CHECKIN_DEFAULT_TIMES,
    CHECKIN_MAX_SLOTS,
    DEFAULT_UNSOLICITED_BUDGET,
    MAX_UNSOLICITED_BUDGET,
)
from app.db.repositories.base import UserScopedDocument

AttentionRule = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=ATTENTION_RULE_MAX_CHARS)
]


class AttentionSettings(BaseModel):
    """What the user chose about being told things they did not ask for.

    Quiet hours are not here: they are the user's QuietHours, shared with the trigger gate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_unsolicited_per_day: int = Field(
        default=DEFAULT_UNSOLICITED_BUDGET,
        ge=0,
        le=MAX_UNSOLICITED_BUDGET,
        description="Unsolicited routine messages per day; 0 leaves them to the check-ins.",
    )
    checkin_times: list[time] = Field(
        default=list(CHECKIN_DEFAULT_TIMES),
        max_length=CHECKIN_MAX_SLOTS,
        description="Local times of the daily check-ins, besides the one when quiet hours end.",
    )
    dnd_until: AwareDatetime | None = Field(
        default=None,
        description="Nothing but security notices and the user's own timings gets through until then.",
    )
    rules: list[AttentionRule] = Field(
        default_factory=list,
        max_length=ATTENTION_RULES_MAX,
        description="The user's own words about what to tell them, applied by the Judge.",
    )

    @model_validator(mode="after")
    def _checkin_times_are_distinct(self) -> Self:
        if len(set(self.checkin_times)) != len(self.checkin_times):
            raise ValueError("check-in times must be distinct")
        return self


class AttentionSettingsDocument(UserScopedDocument):
    """A user's stored settings: one document per user, absent until they change one."""

    max_unsolicited_per_day: int
    checkin_times: list[time]
    dnd_until: AwareDatetime | None = None
    rules: list[str]


class AttentionSettingsUpdate(BaseModel):
    """Typed $set fields of the settings."""

    model_config = ConfigDict(extra="forbid")

    max_unsolicited_per_day: int | None = None
    checkin_times: list[time] | None = None
    dnd_until: AwareDatetime | None = None
    rules: list[str] | None = None
