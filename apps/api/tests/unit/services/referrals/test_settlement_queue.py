"""The settle job's ARQ id: one per referrer, or one per friend for a payment or refund."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.referrals import SETTLE_REWARDS_TASK
from app.services.referrals.settlement_queue import queue_settlement

QUEUE = "app.services.referrals.settlement_queue"
REFERRER_ID = "64a0000000000000000000a1"
FRIEND_ID = "64a0000000000000000000f1"


@pytest.mark.parametrize(
    ("friend_user_id", "job_id"),
    [
        (None, f"{SETTLE_REWARDS_TASK}:{REFERRER_ID}"),
        (FRIEND_ID, f"{SETTLE_REWARDS_TASK}:{REFERRER_ID}:{FRIEND_ID}"),
    ],
    ids=["per-referrer", "per-friend"],
)
async def test_the_settle_job_is_queued_for_the_referrer_under_its_job_id(
    friend_user_id: str | None, job_id: str
) -> None:
    pool = MagicMock()
    with (
        patch(f"{QUEUE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        patch(f"{QUEUE}.enqueue_worker_job", AsyncMock()) as enqueue,
    ):
        await queue_settlement(REFERRER_ID, friend_user_id=friend_user_id)

    enqueue.assert_awaited_once_with(pool, SETTLE_REWARDS_TASK, REFERRER_ID, _job_id=job_id)


async def test_a_refused_enqueue_raises_to_the_caller() -> None:
    with (
        patch(f"{QUEUE}.RedisPoolManager.get_pool", AsyncMock(return_value=MagicMock())),
        patch(f"{QUEUE}.enqueue_worker_job", AsyncMock(side_effect=ConnectionError("redis down"))),
        pytest.raises(ConnectionError, match="redis down"),
    ):
        await queue_settlement(REFERRER_ID)
