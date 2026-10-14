"""A sender's daily invite allowance, reserved in one Redis INCR so concurrent batches cannot overshoot it."""

from dataclasses import dataclass
from datetime import datetime

from app.constants.referrals import (
    INVITE_CEILING_FIX,
    INVITE_CEILING_MESSAGE,
    INVITE_CEILING_WHY,
    INVITE_DAILY_SEND_CEILING,
    INVITE_QUOTA_KEY_TEMPLATE,
    INVITE_QUOTA_TTL_S,
)
from app.db.redis import redis_cache
from app.utils.errors import AppError


@dataclass(frozen=True)
class InviteQuotaReservation:
    """Invites a batch may send, held against one UTC day's allowance until released."""

    key: str
    count: int


async def reserve_invites(sender_user_id: str, count: int, now: datetime) -> InviteQuotaReservation:
    """Take count invites from today's allowance, or raise a 429 and take nothing."""
    key = INVITE_QUOTA_KEY_TEMPLATE.format(user_id=sender_user_id, day=now.date().isoformat())
    client = redis_cache.client
    reserved = await client.incr(key, count)
    if reserved == count:
        await client.expire(key, INVITE_QUOTA_TTL_S)
    if reserved > INVITE_DAILY_SEND_CEILING:
        await client.incr(key, -count)
        raise AppError(
            message=INVITE_CEILING_MESSAGE,
            why=INVITE_CEILING_WHY,
            fix=INVITE_CEILING_FIX,
            status_code=429,
            meta={"sent_today": reserved - count, "ceiling": INVITE_DAILY_SEND_CEILING},
        )
    return InviteQuotaReservation(key=key, count=count)


async def release_invites(reservation: InviteQuotaReservation, sent: int) -> None:
    """Hand back the part of a reservation that was not sent."""
    unused = reservation.count - sent
    if unused:
        await redis_cache.client.incr(reservation.key, -unused)
