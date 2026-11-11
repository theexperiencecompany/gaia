"""The settle job retries a referrer's rewards with backoff; the sweep queues months left pending."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, call, patch

from arq import Retry
import pytest
import time_machine

from app.constants.referrals import SETTLE_SWEEP_GRACE, SETTLE_SWEEP_MAX_REFERRALS_PER_RUN
from app.models.referral_models import ReferralRewardState
from app.services.referrals.rewards import RewardDelivery
from app.workers.task_envelope import ArqJobContext
from app.workers.tasks.referral_tasks import (
    settle_referral_rewards_task,
    sweep_unsettled_referral_rewards,
)

TASK = "app.workers.tasks.referral_tasks"
USER_ID = "64a0000000000000000000a1"
OTHER_ID = "64a0000000000000000000a2"
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


async def test_the_referrers_rewards_are_settled_and_counted() -> None:
    settled = [
        RewardDelivery(ReferralRewardState.APPLIED),
        RewardDelivery(ReferralRewardState.BANKED),
    ]
    with (
        patch(f"{TASK}.settle_rewards", AsyncMock(return_value=settled)) as settle,
        patch(f"{TASK}.log") as log,
    ):
        result = await settle_referral_rewards_task({"job_try": 1}, USER_ID)

    assert result == "settle_referral_rewards 2"
    settle.assert_awaited_once_with(USER_ID)
    log.set.assert_called_once_with(user={"id": USER_ID}, referral={"operation": "settle_rewards"})
    log.set_ns.assert_called_once_with("referral", rewards_settled=2)


@pytest.mark.parametrize(
    ("ctx", "defer"),
    [
        ({}, timedelta(minutes=2)),
        ({"job_try": 1}, timedelta(minutes=2)),
        ({"job_try": 3}, timedelta(minutes=8)),
    ],
    ids=["first-try-default", "first-try", "third-try"],
)
async def test_a_failure_is_retried_later_each_time_and_logged(
    ctx: ArqJobContext, defer: timedelta
) -> None:
    with (
        patch(f"{TASK}.settle_rewards", AsyncMock(side_effect=ConnectionError("dodo down"))),
        patch(f"{TASK}.log") as log,
        pytest.raises(Retry) as retry,
    ):
        await settle_referral_rewards_task(ctx, USER_ID)

    assert retry.value.defer_score == int(defer.total_seconds() * 1000)
    assert isinstance(retry.value.__cause__, ConnectionError)
    assert log.warning.call_args_list == [
        call(
            "[PAYMENT] Referral rewards not settled; retrying",
            error="dodo down",
            error_type="ConnectionError",
            defer_seconds=defer.total_seconds(),
        )
    ]
    log.set_ns.assert_not_called()


@time_machine.travel(NOW, tick=False)
async def test_the_sweep_queues_every_referrer_whose_month_outlived_its_job() -> None:
    with (
        patch(
            f"{TASK}.referral_repository.list_referrers_unsettled",
            AsyncMock(return_value=[USER_ID, OTHER_ID]),
        ) as unsettled,
        patch(f"{TASK}.queue_settlement", AsyncMock()) as queue,
    ):
        result = await sweep_unsettled_referral_rewards({})

    unsettled.assert_awaited_once_with(
        NOW - SETTLE_SWEEP_GRACE, limit=SETTLE_SWEEP_MAX_REFERRALS_PER_RUN
    )
    assert queue.await_args_list == [call(USER_ID), call(OTHER_ID)]
    assert result == "sweep_unsettled_referral_rewards queued 2"
