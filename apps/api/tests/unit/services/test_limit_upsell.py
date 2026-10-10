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

import pytest

from app.models.payment_models import PlanType
from app.services.limit_upsell import (
    LimitHitOrigin,
    current_limit_origin,
    schedule_limit_upsell,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.billing import RateLimitHit
from shared.py.analytics.context import AnalyticsContext, analytics_context, worker_context

MODULE = "app.services.limit_upsell"
USER_1 = "6812f0b3c9a14e2b7d5a91c1"
USER_2 = "6812f0b3c9a14e2b7d5a91c2"
USER_3 = "6812f0b3c9a14e2b7d5a91c3"


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
        patch(f"{MODULE}.capture") as capture,
        patch(f"{MODULE}.send_limit_reached_email", new_callable=AsyncMock) as upsell,
        patch(f"{MODULE}.send_workflows_paused_email", new_callable=AsyncMock) as paused,
        patch(f"{MODULE}.spawn_background_task") as spawn,
    ):
        yield _Seams(capture=capture, upsell=upsell, paused=paused, spawn=spawn)


class TestOriginRouting:
    async def test_interactive_sends_upsell_email(self) -> None:
        async with _patched_seams() as seams:
            schedule_limit_upsell(
                USER_1, "chat_messages", PlanType.FREE, LimitHitOrigin.INTERACTIVE
            )
            await seams.scheduled

        seams.upsell.assert_awaited_once_with(USER_1, "chat_messages")
        seams.paused.assert_not_awaited()
        seams.capture.assert_called_once_with(
            UserId(USER_1),
            RateLimitHit(feature="chat_messages", origin="interactive", plan="free"),
        )

    async def test_background_sends_workflows_paused_email(self) -> None:
        async with _patched_seams() as seams:
            schedule_limit_upsell(
                USER_2, "trigger_workflow_executions", PlanType.FREE, LimitHitOrigin.BACKGROUND
            )
            await seams.scheduled

        seams.paused.assert_awaited_once_with(USER_2)
        seams.upsell.assert_not_awaited()
        seams.capture.assert_called_once_with(
            UserId(USER_2),
            RateLimitHit(feature="trigger_workflow_executions", origin="background", plan="free"),
        )

    async def test_email_failure_is_swallowed(self) -> None:
        async with _patched_seams() as seams:
            seams.paused.side_effect = RuntimeError("smtp down")
            schedule_limit_upsell(
                USER_3, "trigger_workflow_executions", PlanType.FREE, LimitHitOrigin.BACKGROUND
            )
            # Must not raise: losing a marketing email can't affect the 429.
            await seams.scheduled


class TestScheduleGate:
    def test_free_plan_schedules(self) -> None:
        """The gate's other side: a FREE hit is the case that must reach the seam."""
        with patch(f"{MODULE}.spawn_background_task") as spawn:
            schedule_limit_upsell(USER_1, "chat_messages", PlanType.FREE, LimitHitOrigin.BACKGROUND)
        spawn.assert_called_once()
        # Close the spawned coroutine so it is not reported as never awaited.
        spawn.call_args.args[0].close()

    def test_paid_plan_schedules_nothing(self) -> None:
        with patch(f"{MODULE}.spawn_background_task") as spawn:
            schedule_limit_upsell(USER_1, "chat_messages", PlanType.PRO, LimitHitOrigin.INTERACTIVE)
        spawn.assert_not_called()


class TestTheRunOrigin:
    """The bound analytics trigger decides which email a limit hit sends: only an interactive run is the user standing there."""

    def test_a_users_own_turn_is_interactive(self) -> None:
        with analytics_context(
            AnalyticsContext(
                attribution=Attribution(
                    actor=Actor.AGENT, trigger=Trigger.INTERACTIVE, surface=EntrySurface.BOT
                )
            )
        ):
            assert current_limit_origin() is LimitHitOrigin.INTERACTIVE

    @pytest.mark.parametrize(
        "trigger",
        [Trigger.SCHEDULE, Trigger.INTEGRATION_TRIGGER, Trigger.WEBHOOK, Trigger.SYSTEM],
    )
    def test_any_run_the_user_did_not_start_is_background(self, trigger: Trigger) -> None:
        with analytics_context(worker_context(trigger)):
            assert current_limit_origin() is LimitHitOrigin.BACKGROUND
