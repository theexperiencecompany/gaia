"""The errors a briefing run fails with, and the one a workflow meets when no brief can carry it."""

from app.constants.error_codes import BRIEFS_OFF
from app.utils.errors import AppError


class BriefingGenerationError(Exception):
    """The agent did not produce a valid brief — the run failed."""


class VoiceUnreadableError(BriefingGenerationError):
    """The voice call's reply was no whole voice; problems name why, reply is what came back."""

    def __init__(self, problems: list[str], reply: str | None = None) -> None:
        super().__init__(f"The voice reply was no whole voice: {'; '.join(problems)}")
        self.problems = problems
        self.reply = reply or "(no readable reply)"


class BriefsOffError(AppError):
    """A workflow cannot send its results to the brief while the user gets no daily brief."""

    def __init__(self) -> None:
        super().__init__(
            message="You get no daily brief, so a workflow cannot add its results to one",
            why="Results wait only for a daily brief, so they would go nowhere",
            fix="Choose Tell me now or Don't notify me, or turn on daily briefs in Settings",
            status_code=409,
            code=BRIEFS_OFF,
        )
