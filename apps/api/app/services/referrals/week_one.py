"""The one bot DM after a user's first good week: their gift link, ready to forward.

Driven hourly by the ARQ cron so each user is reached at 10am their time on
days 7-9 after signup, once they used GAIA on most of the last seven days.
The DM goes to the user's one chat platform and draws on the referral nudge
budget, so it never lands the same week as another pitch.
"""

from datetime import UTC, datetime, timedelta

from app.constants.referrals import (
    SHARE_TEXT_TEMPLATE,
    WEEK_ONE_DM_DAY,
    WEEK_ONE_DM_GRACE_DAYS,
    WEEK_ONE_DM_HOUR_LOCAL,
    WEEK_ONE_DM_PITCH,
    WEEK_ONE_LOOKBACK_DAYS,
    WEEK_ONE_MIN_ACTIVE_DAYS,
    ReferralNudge,
)
from app.db.repositories.usage_daily import usage_daily_repository
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.services.delivery.chat_channel import ChatChannel, resolve_chat_channel
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.services.payments.payment_service import payment_service
from app.services.referrals.codes import ensure_code, share_link
from app.services.referrals.invites import friend_price_line, price_lines
from app.services.referrals.nudges import send_pitch
from app.services.referrals.offer import build_offer
from app.utils.timezone import as_utc, is_within_local_daytime
from shared.py.wide_events import log

_DAY_FORMAT = "%Y-%m-%d"


def _in_week_one(user: UserDocument, now: datetime) -> bool:
    created_at = as_utc(user.created_at)
    if created_at is None:
        return False
    return WEEK_ONE_DM_DAY <= (now - created_at).days <= WEEK_ONE_DM_DAY + WEEK_ONE_DM_GRACE_DAYS


async def _had_a_good_week(user_id: str, now: datetime) -> bool:
    since = (now - timedelta(days=WEEK_ONE_LOOKBACK_DAYS - 1)).strftime(_DAY_FORMAT)
    counts = await usage_daily_repository.counts_since(user_id, since)
    return sum(1 for count in counts.values() if count > 0) >= WEEK_ONE_MIN_ACTIVE_DAYS


async def _send_dm(user: UserDocument, channel: ChatChannel) -> bool:
    """Send the pitch and, as its own bubble, the message to forward; True once it is queued."""
    offer = build_offer(await payment_service.get_pro_plans())
    intro, _ = price_lines(offer)
    share_text = SHARE_TEXT_TEMPLATE.format(
        price_line=intro, link=share_link(await ensure_code(user))
    )
    pitch = WEEK_ONE_DM_PITCH.format(price_line=friend_price_line(offer))
    result = await publish_outbound_message(channel.source, user.id, [pitch, share_text])
    return result is OutboundResult.PUBLISHED


async def _offer_week_one_dm(user: UserDocument, now: datetime) -> bool:
    if not is_within_local_daytime(
        now, user.timezone, WEEK_ONE_DM_HOUR_LOCAL, WEEK_ONE_DM_HOUR_LOCAL + 1
    ):
        return False
    if not _in_week_one(user, now) or not await _had_a_good_week(user.id, now):
        return False
    channel = await resolve_chat_channel(user.id)
    if channel is None:
        return False
    return await send_pitch(user.id, ReferralNudge.WEEK_ONE_DM, lambda: _send_dm(user, channel))


async def send_week_one_dms() -> str:
    """DM every user at 10am local who just had a good first week; one send per user, ever."""
    now = datetime.now(UTC)
    # Naive cutoff: created_at is stored naive-UTC by signup, as the nurture sweep reads it.
    cutoff = (now - timedelta(days=WEEK_ONE_DM_DAY + WEEK_ONE_DM_GRACE_DAYS + 1)).replace(
        tzinfo=None
    )
    sent = checked = 0
    for user in await user_repository.find_nurture_candidates(cutoff):
        checked += 1
        try:
            sent += await _offer_week_one_dm(user, now)
        except Exception as e:
            # One user's failure must not starve the rest of the cohort.
            log.error(
                "Week-one referral DM failed for user",
                user_id=user.id,
                error=str(e),
                error_type=type(e).__name__,
            )
    log.set(referral={"operation": "week_one_dms", "checked": checked, "sent": sent})
    return f"week-one referral dms: sent {sent} of {checked} candidates"
