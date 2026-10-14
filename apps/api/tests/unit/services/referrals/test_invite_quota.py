"""A sender's daily allowance is reserved atomically, expires with the day and gives back what a refused batch took."""

from datetime import UTC, datetime

import pytest

from app.constants.referrals import (
    INVITE_CEILING_FIX,
    INVITE_CEILING_MESSAGE,
    INVITE_CEILING_WHY,
    INVITE_DAILY_SEND_CEILING,
    INVITE_QUOTA_TTL_S,
)
from app.services.referrals.invite_quota import reserve_invites
from app.utils.errors import AppError

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


async def test_the_first_reservation_of_the_day_starts_the_expiry(fake_redis) -> None:
    reservation = await reserve_invites("u1", 3, NOW)

    assert reservation.key == "referral:invite-quota:u1:2026-10-14"
    assert reservation.count == 3
    assert int(await fake_redis.get(reservation.key)) == 3
    assert 0 < await fake_redis.ttl(reservation.key) <= INVITE_QUOTA_TTL_S


async def test_a_later_reservation_keeps_the_days_expiry(fake_redis) -> None:
    first = await reserve_invites("u1", 3, NOW)
    await fake_redis.expire(first.key, 60)

    await reserve_invites("u1", 2, NOW)

    assert await fake_redis.ttl(first.key) <= 60


async def test_a_refused_batch_takes_nothing_from_the_allowance(fake_redis) -> None:
    first = await reserve_invites("u1", INVITE_DAILY_SEND_CEILING - 1, NOW)

    with pytest.raises(AppError) as refused:
        await reserve_invites("u1", 2, NOW)

    assert refused.value.status_code == 429
    assert refused.value.message == INVITE_CEILING_MESSAGE
    assert refused.value.why == INVITE_CEILING_WHY
    assert refused.value.fix == INVITE_CEILING_FIX
    assert refused.value.meta == {
        "sent_today": INVITE_DAILY_SEND_CEILING - 1,
        "ceiling": INVITE_DAILY_SEND_CEILING,
    }
    assert int(await fake_redis.get(first.key)) == INVITE_DAILY_SEND_CEILING - 1
    await reserve_invites("u1", 1, NOW)
    assert int(await fake_redis.get(first.key)) == INVITE_DAILY_SEND_CEILING
