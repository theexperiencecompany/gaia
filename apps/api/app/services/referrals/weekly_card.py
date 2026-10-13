"""The Monday recap card in chat: last week's time saved, shared with the user's invite link."""

import asyncio
from datetime import datetime

from app.config.feature_flags import REFERRAL_COPY_FLAG
from app.constants.referrals import WEEKLY_CARD_WEEKDAY
from app.models.user_models import UserDocument
from app.schemas.referrals import ReferralWeeklyCardResponse
from app.schemas.usage import TimeSavedSummary
from app.services.feature_flags import get_variant
from app.services.referrals.codes import ensure_code, load_user, share_link
from app.services.referrals.overview import require_referrer_subscription
from app.services.time_saved import get_time_saved
from app.utils.timezone import Timezone


def weekly_card_due(user: UserDocument, stats: TimeSavedSummary, now: datetime) -> bool:
    """Whether chat shows the card now: on the user's local Monday, for a week with something in it.

    This is the one place the card's visibility is decided, so a cross-channel
    nudge cap belongs here.
    """
    local_day = now.astimezone(Timezone.parse(user.timezone).tzinfo).weekday()
    return local_day == WEEKLY_CARD_WEEKDAY and stats.minutes_saved > 0


async def get_weekly_card(user_id: str, now: datetime) -> ReferralWeeklyCardResponse:
    """Return last week's recap and the link to share it with; 403 without an active subscription."""
    user = await load_user(user_id)
    await require_referrer_subscription(user.id)
    code, stats, copy_variant = await asyncio.gather(
        ensure_code(user),
        get_time_saved(user.id, now),
        get_variant(REFERRAL_COPY_FLAG, user.id),
    )
    return ReferralWeeklyCardResponse(
        show=weekly_card_due(user, stats, now),
        stats=stats,
        code=code,
        share_link=share_link(code),
        copy_variant=copy_variant,
    )
