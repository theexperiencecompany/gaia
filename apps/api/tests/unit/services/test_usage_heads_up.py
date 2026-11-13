"""The heads-up before a pro user's monthly allowance runs out.

The outbox submit is the boundary that is stubbed; the report id it is filed under is what keeps
a month's heads-up to one.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services import usage_heads_up
from app.services.outbox.models import NoticeOutcome, NoticeReport, ProducerKind, SubjectKind
from app.services.usage_heads_up import notify_monthly_heads_up_once

USER = "u-heads-up"
WINDOW = "20990115"
RESET = datetime(2099, 2, 15, tzinfo=UTC)


@pytest.fixture
def created() -> Iterator[AsyncMock]:
    """Stub the outbox submit and answer the allowance window for known users only."""
    notify = AsyncMock()
    with (
        patch.object(usage_heads_up, "submit", notify),
        patch.object(
            usage_heads_up,
            "monthly_allowance_window",
            AsyncMock(
                side_effect=lambda user_id: {USER: (WINDOW, RESET), "u2": (WINDOW, RESET)}[user_id]
            ),
        ),
    ):
        yield notify


@pytest.mark.unit
class TestMonthlyHeadsUp:
    async def test_a_month_files_one_report_id_however_often_it_is_asked(
        self, created: AsyncMock
    ) -> None:
        await notify_monthly_heads_up_once(USER)
        await notify_monthly_heads_up_once(USER)

        first, second = (call.args[0].report_id for call in created.await_args_list)
        assert first == second == f"sys:usage_heads_up:{USER}:{WINDOW}"

    async def test_files_what_stops_and_when_it_comes_back(self, created: AsyncMock) -> None:
        await notify_monthly_heads_up_once(USER)

        notice = created.await_args.args[0]
        assert isinstance(notice, NoticeReport)
        assert notice.recipient == USER
        assert notice.producer is ProducerKind.ACCOUNT
        assert notice.subject.kind is SubjectKind.ACCOUNT
        assert notice.outcome is NoticeOutcome.INFO
        assert notice.report_id == f"sys:usage_heads_up:{USER}:{WINDOW}"
        assert notice.facts == [
            "Most of the user's monthly usage allowance is used.",
            "When it runs out, chat, workflows and tracked todos pause "
            "until February 15, when it resets.",
        ]

    async def test_each_user_gets_their_own(self, created: AsyncMock) -> None:
        await notify_monthly_heads_up_once(USER)
        await notify_monthly_heads_up_once("u2")

        assert [c.args[0].recipient for c in created.await_args_list] == [USER, "u2"]

    async def test_a_failed_submit_raises_and_the_next_call_files_it_again(
        self, created: AsyncMock
    ) -> None:
        """Regression: a gate taken before the submit lost the month's heads-up when the submit failed."""
        created.side_effect = [RuntimeError("redis down"), None]

        with pytest.raises(RuntimeError, match="redis down"):
            await notify_monthly_heads_up_once(USER)
        await notify_monthly_heads_up_once(USER)

        assert created.await_count == 2
