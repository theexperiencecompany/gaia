"""The one budget every referral nudge draws on, whatever channel it rides.

A pitch (nurture email, week-one DM, chat card) claims the user's weekly slot
before it goes out and gives it back if it did not; two dismissals pause every
pitch for a month. A reward note is never held back, but it starts the week.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.constants.referrals import (
    NUDGE_CAP_WINDOW,
    NUDGE_DISMISSALS_TO_PAUSE,
    NUDGE_PAUSE,
    ONCE_ONLY_NUDGES,
    PITCH_NUDGES,
    ReferralNudge,
)
from app.db.repositories.referral_nudges import referral_nudge_repository
from app.db.repositories.subscriptions import subscription_repository
from app.services.analytics_service import capture
from shared.py.analytics import UserId
from shared.py.analytics.catalog.referrals import ReferralNudgeDismissed, ReferralNudgeSent
from shared.py.wide_events import log


def _now() -> datetime:
    """Return now at Mongo's millisecond precision, so a stored stamp matches it exactly."""
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond - now.microsecond % 1000)


def _counted(user_id: str, nudge: ReferralNudge) -> None:
    capture(UserId(user_id), ReferralNudgeSent(nudge=nudge.value))
    log.set_ns("referral", nudge=nudge.value, nudge_sent=True)


async def send_pitch(
    user_id: str, nudge: ReferralNudge, deliver: Callable[[], Awaitable[bool]]
) -> bool:
    """Deliver a pitch if the user's weekly slot is free; True only when deliver reports it went out."""
    if nudge not in PITCH_NUDGES:
        raise ValueError(f"{nudge.value} is a reward note, not a pitch; record_announcement it")
    if await subscription_repository.get_active_for_user(user_id) is None:
        log.set_ns("referral", nudge=nudge.value, nudge_skipped="not_subscribed")
        return False
    now = _now()
    prior = await referral_nudge_repository.get(user_id)
    claimed = await referral_nudge_repository.claim(
        user_id, nudge, now, window_start=now - NUDGE_CAP_WINDOW, once=nudge in ONCE_ONLY_NUDGES
    )
    if claimed is None:
        log.set_ns("referral", nudge=nudge.value, nudge_skipped="capped")
        return False
    try:
        delivered = await deliver()
    except Exception:
        await referral_nudge_repository.release(user_id, nudge, now, prior=prior)
        raise
    if not delivered:
        await referral_nudge_repository.release(user_id, nudge, now, prior=prior)
        log.set_ns("referral", nudge=nudge.value, nudge_skipped="undelivered")
        return False
    _counted(user_id, nudge)
    return True


async def rendered_by_client() -> bool:
    """Deliver a pitch the client draws itself (the chat card): granting the claim is the delivery."""
    return True


async def record_announcement(user_id: str, nudge: ReferralNudge) -> None:
    """Record a reward note that already went out; it is never capped but it starts the week."""
    if nudge in PITCH_NUDGES:
        raise ValueError(f"{nudge.value} is a pitch; send it through send_pitch")
    await referral_nudge_repository.stamp(user_id, nudge, _now())
    _counted(user_id, nudge)


async def dismiss_nudge(user_id: str, nudge: ReferralNudge) -> bool:
    """Count the user dismissing a nudge; True when this dismissal paused every pitch."""
    now = _now()
    state = await referral_nudge_repository.record_dismissal(
        user_id, now, dismissals_to_pause=NUDGE_DISMISSALS_TO_PAUSE, pause=NUDGE_PAUSE
    )
    paused = state.dismissals == 0 and state.paused_until is not None and state.paused_until > now
    capture(UserId(user_id), ReferralNudgeDismissed(nudge=nudge.value, paused=paused))
    log.set_ns("referral", nudge=nudge.value, nudge_dismissed=True, nudges_paused=paused)
    return paused
