"""Unit tests for app.services.limit_upsell.

The limit-hit side effects must pick the email by origin: an interactive wall
(the user acted and was blocked) sends the upsell pitch; a background wall (a
workflow run the user never initiated) sends the workflows-paused note. Both
carry the origin on the analytics event, and paid plans get no side effects.
"""

from unittest.mock import AsyncMock, patch

from app.models.payment_models import PlanType
from app.services.limit_upsell import LimitHitOrigin, _run, schedule_limit_upsell

MODULE = "app.services.limit_upsell"


class TestOriginRouting:
    async def test_interactive_sends_upsell_email(self) -> None:
        with (
            patch(f"{MODULE}.capture_event") as capture,
            patch(f"{MODULE}.send_limit_reached_email", new_callable=AsyncMock) as upsell,
            patch(f"{MODULE}.send_workflows_paused_email", new_callable=AsyncMock) as paused,
        ):
            await _run("user-1", "chat_messages", LimitHitOrigin.INTERACTIVE)

        upsell.assert_awaited_once_with("user-1", "chat_messages")
        paused.assert_not_awaited()
        capture.assert_called_once_with(
            "user-1", "rate_limit_hit", {"feature": "chat_messages", "origin": "interactive"}
        )

    async def test_background_sends_workflows_paused_email(self) -> None:
        with (
            patch(f"{MODULE}.capture_event") as capture,
            patch(f"{MODULE}.send_limit_reached_email", new_callable=AsyncMock) as upsell,
            patch(f"{MODULE}.send_workflows_paused_email", new_callable=AsyncMock) as paused,
        ):
            await _run("user-1", "trigger_workflow_executions", LimitHitOrigin.BACKGROUND)

        paused.assert_awaited_once_with("user-1")
        upsell.assert_not_awaited()
        capture.assert_called_once_with(
            "user-1",
            "rate_limit_hit",
            {"feature": "trigger_workflow_executions", "origin": "background"},
        )

    async def test_email_failure_is_swallowed(self) -> None:
        with (
            patch(f"{MODULE}.capture_event"),
            patch(
                f"{MODULE}.send_workflows_paused_email",
                new_callable=AsyncMock,
                side_effect=RuntimeError("smtp down"),
            ),
        ):
            # Must not raise: losing a marketing email can't affect the 429.
            await _run("user-1", "trigger_workflow_executions", LimitHitOrigin.BACKGROUND)


class TestScheduleGate:
    def test_paid_plan_schedules_nothing(self) -> None:
        with patch(f"{MODULE}.spawn_background_task") as spawn:
            schedule_limit_upsell(
                "user-1", "chat_messages", PlanType.PRO, LimitHitOrigin.INTERACTIVE
            )
        spawn.assert_not_called()

    def test_free_plan_schedules(self) -> None:
        with patch(f"{MODULE}.spawn_background_task") as spawn:
            schedule_limit_upsell(
                "user-1", "chat_messages", PlanType.FREE, LimitHitOrigin.BACKGROUND
            )
        spawn.assert_called_once()
        # The spawned coroutine must be closed to avoid an un-awaited warning.
        spawn.call_args.args[0].close()
