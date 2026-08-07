"""The ARQ cron that drives the HIL approval sweep.

The task body is three lines, which is exactly why it was never tested — and why it is
worth testing. The sweep is the ONLY thing that resolves an approval nobody answered: a
gated action whose user walked away stays pending forever if this never fires, holding the
conversation's executor lock and hijacking every later message via the conversational
resolver. A cron that quietly stops calling its own service fails silently, on a schedule,
in production only.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.hil_sweep_tasks import sweep_hil_approvals

MODULE = "app.workers.tasks.hil_sweep_tasks"

pytestmark = pytest.mark.unit


class TestTheCronRunsTheSweep:
    async def test_the_sweep_is_actually_invoked(self) -> None:
        with patch(
            f"{MODULE}.sweep_approvals",
            new=AsyncMock(return_value={"expired": 0, "redispatched": 0}),
        ) as sweep:
            await sweep_hil_approvals({})

        sweep.assert_awaited_once()

    async def test_the_counts_reach_the_worker_log_line(self) -> None:
        # The return value is the only visibility an operator has into whether the sweep
        # is doing anything. Hardcoded or dropped, a stalled sweep looks identical to a
        # quiet one.
        with patch(
            f"{MODULE}.sweep_approvals",
            new=AsyncMock(return_value={"expired": 3, "redispatched": 2}),
        ):
            result = await sweep_hil_approvals({})

        assert result == "expired=3 redispatched=2"
