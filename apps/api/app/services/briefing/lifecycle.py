"""The gates a run passes before any model cost: once per day, the bootstrap hold and the wind-down."""

from datetime import UTC, datetime, timedelta

from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
    BriefingKind,
)
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefSettlement
from app.models.briefing_state_models import BriefingStateDocument, BriefingWindDown
from app.services.briefing import wind_down
from app.services.briefing.clock import UserClock
from app.utils.timezone import as_utc
from shared.py.wide_events import log


def bootstrap_holds(state: BriefingStateDocument) -> bool:
    """Whether an existing user's first brief is held for a goal: marked, inside the grace window."""
    marker = state.bootstrap
    if marker is None or not marker.pending:
        return False
    return datetime.now(UTC) - as_utc(marker.since) < timedelta(days=BOOTSTRAP_GRACE_DAYS)


def bootstrap_should_skip(state: BriefingStateDocument, has_goal: bool) -> bool:
    """Existing-user rollout gate: skip the run while the hold stands and no goal has arrived.

    Past the grace window the run proceeds as a best-effort brief, re-asking for a goal.
    """
    return not has_goal and bootstrap_holds(state)


async def settle_brief(user_id: str, settlement: BriefSettlement) -> None:
    """Settle the reader's state for a brief that went out: its bootstrap hold, goal question and goodbye."""
    if settlement.clears_bootstrap:
        await briefing_state_repository.clear_bootstrap(user_id)
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
        return BriefingWindDown(
            idle_days=0, date=None, wound_down_since=None, goal_asked_at=dstate.goal_asked_at
        )
    log.info("briefing.wound_down_skip", user_id=user_id)
    return None


async def already_delivered(user_id: str, clock: UserClock, kind: BriefingKind) -> bool:
    """One brief per user, local date and kind: a second run that day sends nothing."""
    if await briefing_repository.was_delivered(user_id, clock.date_str, kind):
        log.info("briefing.already_delivered_skip", user_id=user_id, kind=kind)
        return True
    return False
