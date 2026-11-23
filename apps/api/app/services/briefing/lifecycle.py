"""The gates a run passes before any model cost: once per day and the wind-down."""

from app.constants.briefing import BriefingKind
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefSettlement
from app.models.briefing_state_models import BriefingStateDocument, BriefingWindDown
from app.services.briefing import wind_down
from app.services.briefing.clock import UserClock
from shared.py.wide_events import log


async def settle_brief(user_id: str, settlement: BriefSettlement) -> None:
    """Settle the reader's state for a brief that went out: its goal question and goodbye."""
    if settlement.asked_goal:
        await briefing_state_repository.record_goal_question(user_id)
    if settlement.winds_down:
        await briefing_state_repository.enter_wind_down(user_id)
        log.info("briefing.wind_down_entered", user_id=user_id)


async def wake_or_skip(state: BriefingStateDocument) -> BriefingWindDown | None:
    """Wake a wound-down loop on a reactivation signal (user active, any message).

    Otherwise None means skip before any LLM cost.
    """
    user_id = state.user_id
    dstate = wind_down.ladder_state(state)
    if not dstate.wound_down_since:
        return dstate
    if await wind_down.latest_activity_since(user_id, dstate.wound_down_since) is not None:
        await briefing_state_repository.clear_wind_down(user_id)
        log.info("briefing.wind_down_cleared", user_id=user_id)
        return BriefingWindDown(goal_asked_at=dstate.goal_asked_at)
    log.info("briefing.wound_down_skip", user_id=user_id)
    return None


async def already_delivered(user_id: str, clock: UserClock, kind: BriefingKind) -> bool:
    """One brief per user, local date and kind: a second run that day sends nothing."""
    if await briefing_repository.was_delivered(user_id, clock.date_str, kind):
        log.info("briefing.already_delivered_skip", user_id=user_id, kind=kind)
        return True
    return False


async def left_undelivered(user_id: str, clock: UserClock, kind: BriefingKind) -> bool:
    """Whether today's brief of kind is stored but its delivery never completed."""
    stored = await briefing_repository.find_for_date(user_id, clock.date_str, kind)
    return stored is not None and (stored.delivery is None or stored.delivery.completed_at is None)
