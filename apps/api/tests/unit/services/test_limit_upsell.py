"""Unit tests for app.services.limit_upsell.

The limit-hit side effects must pick the email by origin: an interactive wall
(the user acted and was blocked) sends the upsell pitch; a background wall (a
workflow run the user never initiated) sends the workflows-paused note. Both
carry the origin on the analytics event, and paid plans get no side effects.
"""

from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.payment_models import PlanType
from app.services.limit_upsell import LimitHitOrigin, schedule_limit_upsell

MODULE = "app.services.limit_upsell"


@dataclass
class _Seams:
    """The mocked side-effect seams plus the coroutine the scheduler spawned."""

    capture: MagicMock
    upsell: AsyncMock
    paused: AsyncMock
    spawn: MagicMock

    @property
    def scheduled(self) -> Coroutine[Any, Any, None]:
        return self.spawn.call_args.args[0]


@asynccontextmanager
async def _patched_seams() -> AsyncIterator[_Seams]:
    with (
        patch(f"{MODULE}.capture_event") as capture,
        patch(f"{MODULE}.send_limit_reached_email", new_callable=AsyncMock) as upsell,
        patch(f"{MODULE}.send_workflows_paused_email", new_callable=AsyncMock) as paused,
        patch(f"{MODULE}.spawn_background_task") as spawn,
    ):
        yield _Seams(capture=capture, upsell=upsell, paused=paused, spawn=spawn)


class TestOriginRouting:
    async def test_interactive_sends_upsell_email(self) -> None:
        async with _patched_seams() as seams:
            schedule_limit_upsell(
                "user-1", "chat_messages", PlanType.FREE, LimitHitOrigin.INTERACTIVE
            )
            await seams.scheduled

        seams.upsell.assert_awaited_once_with("user-1", "chat_messages")
        seams.paused.assert_not_awaited()
        seams.capture.assert_called_once_with(
            "user-1", "rate_limit_hit", {"feature": "chat_messages", "origin": "interactive"}
        )

    async def test_background_sends_workflows_paused_email(self) -> None:
        async with _patched_seams() as seams:
            schedule_limit_upsell(
                "user-2", "trigger_workflow_executions", PlanType.FREE, LimitHitOrigin.BACKGROUND
            )
            await seams.scheduled

        seams.paused.assert_awaited_once_with("user-2")
        seams.upsell.assert_not_awaited()
        seams.capture.assert_called_once_with(
            "user-2",
            "rate_limit_hit",
            {"feature": "trigger_workflow_executions", "origin": "background"},
        )

    async def test_email_failure_is_swallowed(self) -> None:
        async with _patched_seams() as seams:
            seams.paused.side_effect = RuntimeError("smtp down")
            schedule_limit_upsell(
                "user-3", "trigger_workflow_executions", PlanType.FREE, LimitHitOrigin.BACKGROUND
            )
            # Must not raise: losing a marketing email can't affect the 429.
            await seams.scheduled


class TestScheduleGate:
    def test_paid_plan_schedules_nothing(self) -> None:
        with patch(f"{MODULE}.spawn_background_task") as spawn:
            schedule_limit_upsell(
                "user-1", "chat_messages", PlanType.PRO, LimitHitOrigin.INTERACTIVE
            )
        spawn.assert_not_called()
