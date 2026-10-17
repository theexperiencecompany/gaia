"""The Monday recap card in chat: last week's time saved, shared with the user's invite link."""

import asyncio
from datetime import date, datetime

from app.config.feature_flags import REFERRAL_COPY_FLAG
from app.constants.referrals import WEEKLY_CARD_WEEKDAY, ReferralNudge
from app.schemas.referrals import ReferralWeeklyCardResponse
from app.schemas.usage import TimeSavedSummary
from app.services.feature_flags import get_variant
from app.services.referrals.codes import ensure_code, load_user, share_link
from app.services.referrals.nudges import rendered_by_client, send_pitch
from app.services.referrals.overview import require_referrer_subscription
from app.services.time_saved import get_time_saved
from app.utils.timezone import Timezone


def weekly_card_due(local_today: date, stats: TimeSavedSummary) -> bool:
    """Whether the card is worth showing: the user's local Monday, for a week with something in it."""
    return local_today.weekday() == WEEKLY_CARD_WEEKDAY and stats.minutes_saved > 0


async def claim_weekly_card(user_id: str, now: datetime) -> ReferralWeeklyCardResponse:
    """Return last week's recap; show is true only when it is due and wins this week's referral nudge.

    403 without an active subscription, since only subscribers have a link to share.
    """
    user = await load_user(user_id)
    await require_referrer_subscription(user.id)
    # One local date drives both the Monday check and the week recapped, whatever UTC day it is.
    local_today = now.astimezone(Timezone.parse(user.timezone).tzinfo).date()
    code, stats, copy_variant = await asyncio.gather(
        ensure_code(user),
        get_time_saved(user.id, local_today),
        get_variant(REFERRAL_COPY_FLAG, user.id),
    )
    # The weekly slot is spent only when the card would actually appear.
    show = weekly_card_due(local_today, stats) and await send_pitch(
        user.id, ReferralNudge.WEEKLY_STATS_CARD, rendered_by_client
    )
    return ReferralWeeklyCardResponse(
        show=show,
        stats=stats,
        code=code,
        share_link=share_link(code),
        copy_variant=copy_variant,
    )
