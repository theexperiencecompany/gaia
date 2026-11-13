"""Agent-lab idle pause: a lab sandbox stays up only while a watched run is within the cap.

Split from test_lifecycle_pause because it needs the agent_lab package; the
pause mechanics it builds on are covered there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from tests.unit.sandbox.test_lifecycle_pause import (
    LAB_TEMPLATE,
    _fire_idle_timer,
    _idle_timer_world,
    _record,
)

from app.config.settings import settings
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.agent_lab import lab_runs
from app.services.sandbox.pool import PooledSandbox


def _run_todo(started_ago_hours: float) -> TodoDocument:
    return TodoDocument(
        id="todo-lab",
        user_id="u1",
        title="Lab run",
        labels=[GAIA_TRACKED_LABEL],
        trigger_subscriptions=[
            TriggerSubscription(
                trigger_name=lab_runs.SANDBOX_RUN_TRIGGER,
                action=SubscriptionAction.EXECUTE,
                resolution=SubscriptionResolution.ACCOUNT,
                trigger_data={lab_runs.RUN_ID_KEY: "run-1"},
                created_at=datetime.now(UTC) - timedelta(hours=started_ago_hours),
            )
        ],
    )


class TestLabIdlePause:
    """An agent-lab sandbox skips the idle pause only while a watched run is within the cap."""

    async def _fire(self, todos: list[TodoDocument], *, flag_on: bool = True) -> AsyncMock:
        sbx = AsyncMock()
        entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", template_id=LAB_TEMPLATE)
        with (
            _idle_timer_world(entry, _record(template_id=LAB_TEMPLATE), todos=todos) as (
                user_id,
                _repo,
            ),
            patch.object(settings, "ENABLE_AGENT_LAB", flag_on),
        ):
            await _fire_idle_timer(entry, user_id)
        return sbx

    async def test_a_live_run_keeps_the_sandbox_from_pausing(self) -> None:
        sbx = await self._fire([_run_todo(1)])
        sbx.beta_pause.assert_not_awaited()

    async def test_a_live_run_stays_up_when_the_flag_reads_off(self) -> None:
        # The flag reads off whenever PostHog is unreachable, and
        # that paused sandboxes with a coding agent working inside.
        sbx = await self._fire([_run_todo(1)], flag_on=False)
        sbx.beta_pause.assert_not_awaited()

    async def test_no_live_run_means_it_is_idle_paused(self) -> None:
        # Every flagged user skipped the idle pause, so a sandbox
        # with nothing running billed until E2B's lifetime cap killed it.
        sbx = await self._fire([])
        sbx.beta_pause.assert_awaited_once()

    async def test_a_run_past_the_cap_no_longer_keeps_it_awake(self) -> None:
        sbx = await self._fire([_run_todo(13)])
        sbx.beta_pause.assert_awaited_once()
