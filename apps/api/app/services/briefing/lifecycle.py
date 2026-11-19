"""The gates a run passes before any model cost: once per day, the bootstrap hold and dormancy."""

from datetime import UTC, datetime, timedelta

from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.models.briefing_models import (
    BriefingKind,
)
from app.models.user_models import UserDocument
from app.services.briefing import dormancy
from app.services.briefing.context import UserClock
from shared.py.wide_events import log


def bootstrap_should_skip(user: UserDocument, has_goal: bool) -> bool:
    """Existing-user rollout gate: hold the first briefing until a goal is known.

    Returns True to skip this run entirely. Once a goal memory arrives OR the
    grace window elapses, the run proceeds (best-effort, re-asking on grace).
    """
    marker = user.briefing_bootstrap
    if marker is None or not marker.pending:
        return False
    if has_goal:
        return False  # goal arrived — proceed and clear the marker after sending
    since = marker.since if marker.since.tzinfo else marker.since.replace(tzinfo=UTC)
    # Inside the interview grace window: hold. Past it: a best-effort briefing.
    return datetime.now(UTC) - since < timedelta(days=BOOTSTRAP_GRACE_DAYS)


async def clear_bootstrap(user: UserDocument) -> None:
    if user.briefing_bootstrap is not None:
        await user_repository.clear_briefing_bootstrap(user.id)


async def wake_or_skip(user: UserDocument) -> dormancy.DormancyState | None:
    """Wake a dormant loop on a reactivation signal (user active, any message).

    Otherwise None means skip before any LLM cost. The daily run is the only writer of
    dormancy state.
    """
    dstate = dormancy.state_from_user(user)
    if not dstate.dormant_since:
        return dstate
    if await dormancy.latest_activity_since(user.id, dstate.dormant_since) is not None:
        await dormancy.clear_dormancy(user.id)
        log.info("briefing.dormancy_cleared", user_id=user.id)
        return dormancy.DormancyState(idle_days=0, date=None, dormant_since=None)
    log.info("briefing.dormant_skip", user_id=user.id)
    return None


async def already_delivered(user_id: str, clock: UserClock, kind: BriefingKind) -> bool:
    """One brief per user, local date and kind: a second run that day sends nothing."""
    if await briefing_repository.was_delivered(user_id, clock.date_str, kind):
        log.info("briefing.already_delivered_skip", user_id=user_id, kind=kind)
        return True
    return False
