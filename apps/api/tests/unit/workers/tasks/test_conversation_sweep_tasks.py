"""The cron task that finishes what dead processes left on step conversations."""

from unittest.mock import AsyncMock, patch

from app.services.conversation.sweeper import SweepReport
from app.workers.tasks.conversation_sweep_tasks import sweep_step_conversations


async def test_the_sweep_reports_what_it_flushed_lost_and_kicked() -> None:
    report = SweepReport(flushed=2, lost_work=1, undecidable_approvals=4, kicked=3)
    with patch(
        "app.workers.tasks.conversation_sweep_tasks.sweep_conversations",
        AsyncMock(return_value=report),
    ):
        assert await sweep_step_conversations({}) == "flushed=2 lost=1 kicked=3"
