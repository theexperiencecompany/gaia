"""The errors a briefing run fails with, and the guard on sending results to a brief the user lacks."""

from app.constants.briefing import BRIEF_RUN_DAYS, DAILY_BRIEFING_WORKFLOW_KEY
from app.constants.error_codes import BRIEFS_OFF
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefing_state import briefing_state_repository
from app.utils.errors import AppError


class BriefingGenerationError(Exception):
    """The agent did not produce a valid brief — the run failed."""


class BriefsOffError(AppError):
    """A workflow or todo cannot send its results to the brief while the user gets no daily brief."""

    def __init__(self) -> None:
        super().__init__(
            message="You get no daily brief, so results cannot be added to one",
            why="Results wait only for a daily brief, so they would go nowhere",
            fix="Choose Tell me now or Don't notify me, or turn on daily briefs in Settings",
            status_code=409,
            code=BRIEFS_OFF,
        )


async def refuse_a_missing_brief(user_id: str, delivery: WorkflowDelivery | None) -> None:
    """Raise BriefsOffError when delivery is the brief and the user gets no daily brief to carry it."""
    if delivery is not WorkflowDelivery.BRIEF:
        return
    schedule = (await briefing_state_repository.state_for(user_id)).schedule
    if DAILY_BRIEFING_WORKFLOW_KEY not in BRIEF_RUN_DAYS[schedule.frequency]:
        raise BriefsOffError()
