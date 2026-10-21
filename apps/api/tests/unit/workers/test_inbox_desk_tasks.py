"""The worker job that provisions an Inbox desk, retried until the desk is armed."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from arq import Retry
import pytest

from app.constants.log_tags import LogTag
from app.constants.todos import INBOX_DESK_PROVISION_RETRY_DELAY
from app.workers.tasks.inbox_desk_tasks import provision_inbox_desk_task
from tests.helpers import captured_wide_event

_MOD = "app.workers.tasks.inbox_desk_tasks"
USER_ID = "507f1f77bcf86cd799439011"


@pytest.mark.unit
class TestProvisionInboxDeskTask:
    async def test_it_provisions_the_users_desk(self) -> None:
        with patch(f"{_MOD}.provision_inbox_desk", AsyncMock()) as provision:
            result = await provision_inbox_desk_task({}, USER_ID)

        provision.assert_awaited_once_with(USER_ID)
        assert result == f"provision_inbox_desk {USER_ID}"

    async def test_a_failure_asks_arq_for_another_try_each_further_one_later(self) -> None:
        """Regression: a failed provisioning was only logged, and nothing came back for the desk."""
        failure = ConnectionError("mongo down")
        defers = []
        for job_try in (1, 2, 3):
            with (
                patch(f"{_MOD}.provision_inbox_desk", AsyncMock(side_effect=failure)),
                pytest.raises(Retry) as caught,
            ):
                await provision_inbox_desk_task({"job_try": job_try}, USER_ID)
            assert caught.value.__cause__ is failure
            defers.append(caught.value.defer_score)

        first = INBOX_DESK_PROVISION_RETRY_DELAY / timedelta(milliseconds=1)
        assert defers == [first, first * 2, first * 4]

    async def test_a_bare_context_counts_as_the_first_try(self) -> None:
        with (
            patch(f"{_MOD}.provision_inbox_desk", AsyncMock(side_effect=ConnectionError("down"))),
            pytest.raises(Retry) as caught,
        ):
            await provision_inbox_desk_task({}, USER_ID)

        assert caught.value.defer_score == INBOX_DESK_PROVISION_RETRY_DELAY / timedelta(
            milliseconds=1
        )

    async def test_each_retry_is_on_the_wide_event_with_its_cause_and_delay(self) -> None:
        with (
            patch(f"{_MOD}.provision_inbox_desk", AsyncMock(side_effect=ConnectionError("down"))),
            pytest.raises(Retry),
        ):
            async with captured_wide_event() as event:
                await provision_inbox_desk_task({"job_try": 2}, USER_ID)

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.TODO} Inbox desk provisioning failed; retrying",
                "user_id": USER_ID,
                "error": "down",
                "error_type": "ConnectionError",
                "defer_seconds": INBOX_DESK_PROVISION_RETRY_DELAY.total_seconds() * 2,
            }
        ]
