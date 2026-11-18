"""Where the reader stands as a brief runs: the part of a run that differs by kind in behaviour, not data.

The daily brief knows the reader's idle ladder, winback and first brief, and looks back since
the last one; the weekly digest looks back over the week and says the same to every reader.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.agents.prompts.briefing_prompts import RecentLines
from app.models.brief_payload_models import BriefingMood, BriefingPayload, BriefVoice
from app.services.briefing.calendar_read import CalendarRead
from app.services.briefing.candidates.pool import GatheredCandidates
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.facts import Facts
from app.services.briefing.goals import StatedGoal
from app.services.briefing.prose import Writing
from app.services.briefing.sections import Laid
from app.services.briefing.work import BriefReads


@dataclass(frozen=True)
class VoiceInputs:
    """What the voice prompt is written from, beside what the standing holds itself."""

    reads: BriefReads
    facts: Facts
    #: The app signals the brief placed, as the voice reads them.
    signals: str
    recent: RecentLines


@dataclass(frozen=True)
class VoiceRequest:
    """The voice prompt, and what the written brief is held to."""

    prompt: str
    writing: Writing


class Standing(Protocol):
    """Where the reader stands this run, and what of the brief depends on it."""

    @property
    def since(self) -> datetime:
        """When the run's look-back starts: what counts as done since."""
        ...

    goals: list[StatedGoal]

    async def climbed(self, gathered: GatheredCandidates, pool: FactPool) -> "Standing":
        """Return the standing once the run knows whether it has news."""
        ...

    def quiet_before_composing(self, pool: FactPool) -> bool:
        """Say whether the pool alone makes this run a quiet note."""
        ...

    def quiet_after_composing(self, laid: Laid, calendar: CalendarRead) -> bool:
        """Say whether what the composition placed makes this run a quiet note."""
        ...

    async def voice(self, inputs: VoiceInputs) -> VoiceRequest: ...

    def mood(self, draft: BriefVoice) -> BriefingMood: ...

    def pushes(self, payload: BriefingPayload) -> bool:
        """Say whether the brief goes beyond in-app."""
        ...

    async def settle(self) -> None:
        """Close a run that sent something."""
        ...
