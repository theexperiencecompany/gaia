"""The gates a run passes before any model cost: once per day, the bootstrap hold and dormancy."""

from datetime import UTC, datetime, timedelta

from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
    BriefingKind,
)
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_state_models import BriefingDormancy, BriefingStateDocument
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


async def clear_bootstrap(state: BriefingStateDocument) -> None:
    if state.bootstrap is not None:
        await briefing_state_repository.clear_bootstrap(state.user_id)


async def wake_or_skip(state: BriefingStateDocument) -> BriefingDormancy | None:
    """Wake a dormant loop on a reactivation signal (user active, any message).

    Otherwise None means skip before any LLM cost.
    """
    user_id = state.user_id
    dstate = wind_down.ladder_state(state)
    if not dstate.dormant_since:
        return dstate
    if await wind_down.latest_activity_since(user_id, dstate.dormant_since) is not None:
        await briefing_state_repository.clear_dormancy(user_id)
        log.info("briefing.dormancy_cleared", user_id=user_id)
        return BriefingDormancy(
            idle_days=0, date=None, dormant_since=None, goal_asked_at=dstate.goal_asked_at
        )
    log.info("briefing.dormant_skip", user_id=user_id)
    return None


async def already_delivered(user_id: str, clock: UserClock, kind: BriefingKind) -> bool:
    """One brief per user, local date and kind: a second run that day sends nothing."""
    if await briefing_repository.was_delivered(user_id, clock.date_str, kind):
        log.info("briefing.already_delivered_skip", user_id=user_id, kind=kind)
        return True
    return False
