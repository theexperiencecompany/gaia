"""The banked-months job: applies a resubscribed referrer's months, and retries with backoff when Dodo fails."""

from datetime import timedelta
from unittest.mock import AsyncMock, call, patch

from arq import Retry
import pytest

from app.workers.tasks.referral_tasks import apply_banked_referral_months_task

TASK = "app.workers.tasks.referral_tasks"
USER_ID = "64a0000000000000000000a1"


async def test_the_users_banked_months_are_applied_and_counted() -> None:
    with (
        patch(f"{TASK}.apply_banked_months", AsyncMock(return_value=2)) as apply,
        patch(f"{TASK}.log") as log,
    ):
        result = await apply_banked_referral_months_task({"job_try": 1}, USER_ID)

    assert result == "apply_banked_referral_months 2"
    apply.assert_awaited_once_with(USER_ID)
    log.set.assert_called_once_with(
        user={"id": USER_ID}, referral={"operation": "apply_banked_months"}
    )
    log.set_ns.assert_called_once_with("referral", months_applied=2)


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
    ctx: dict[str, int], defer: timedelta
) -> None:
    with (
        patch(f"{TASK}.apply_banked_months", AsyncMock(side_effect=ConnectionError("dodo down"))),
        patch(f"{TASK}.log") as log,
        pytest.raises(Retry) as retry,
    ):
        await apply_banked_referral_months_task(ctx, USER_ID)

    assert retry.value.defer_score == int(defer.total_seconds() * 1000)
    assert isinstance(retry.value.__cause__, ConnectionError)
    assert log.warning.call_args_list == [
        call(
            "[PAYMENT] Banked referral months not applied; retrying",
            error="dodo down",
            error_type="ConnectionError",
            defer_seconds=defer.total_seconds(),
        )
    ]
    log.set_ns.assert_not_called()
