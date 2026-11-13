from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class NurtureStepStatus(StrEnum):
    """What happened to a nurture step for one user."""

    SENT = "sent"
    SKIPPED = "skipped"


class NurtureHistoryEntry(BaseModel):
    """One recorded step outcome, as UserRepository.record_nurture_step writes it."""

    step: str
    at: datetime
    status: NurtureStepStatus


class NurtureState(BaseModel):
    """The users.nurture subdocument: steps done for good, plus the send history the caps read."""

    completed_steps: list[str] = Field(default_factory=list)
    history: list[NurtureHistoryEntry] = Field(default_factory=list)
