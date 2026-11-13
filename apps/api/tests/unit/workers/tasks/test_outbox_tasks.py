"""The outbox jobs retry a failed attempt a bounded number of times, then fail loud."""

from unittest.mock import AsyncMock, patch

from arq import Retry
import pytest

from app.constants.outbox import OUTBOX_TASK_MAX_TRIES
from app.workers.tasks.outbox_tasks import outbox_flush, outbox_intake
from tests._harness.judge import notice

pytestmark = pytest.mark.unit

_MOD = "app.workers.tasks.outbox_tasks"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
REPORT = notice()


class TestIntakeRetries:
    async def test_a_failed_attempt_asks_arq_for_another_try_each_one_later(self) -> None:
        failure = ConnectionError("mongo down")
        defers = []
        for job_try in (1, 2):
            with (
                patch(f"{_MOD}.process_report", AsyncMock(side_effect=failure)),
                pytest.raises(Retry) as caught,
            ):
                await outbox_intake({"job_try": job_try}, REPORT.model_dump(mode="json"))
            assert caught.value.__cause__ is failure
            defers.append(caught.value.defer_score)

        assert defers[1] == 2 * defers[0]

    async def test_the_last_try_fails_with_the_error_itself(self) -> None:
        failure = ConnectionError("mongo down")
        with (
            patch(f"{_MOD}.process_report", AsyncMock(side_effect=failure)),
            pytest.raises(ConnectionError, match="mongo down"),
        ):
            await outbox_intake({"job_try": OUTBOX_TASK_MAX_TRIES}, REPORT.model_dump(mode="json"))


class TestFlushRetries:
    async def test_a_failed_flush_asks_arq_for_another_try(self) -> None:
        failure = ConnectionError("rabbit down")
        with (
            patch(f"{_MOD}.flush_due", AsyncMock(side_effect=failure)),
            pytest.raises(Retry) as caught,
        ):
            await outbox_flush({"job_try": 1}, USER_ID)

        assert caught.value.__cause__ is failure

    async def test_the_last_try_fails_with_the_error_itself(self) -> None:
        with (
            patch(f"{_MOD}.flush_due", AsyncMock(side_effect=ConnectionError("rabbit down"))),
            pytest.raises(ConnectionError),
        ):
            await outbox_flush({"job_try": OUTBOX_TASK_MAX_TRIES}, USER_ID)
