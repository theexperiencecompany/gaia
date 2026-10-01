"""The worker job that provisions an Inbox desk, retried until the desk is armed."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from arq import Retry
import pytest

from app.constants.todos import INBOX_DESK_PROVISION_RETRY_DELAY
from app.workers.tasks.inbox_desk_tasks import provision_inbox_desk_task

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
