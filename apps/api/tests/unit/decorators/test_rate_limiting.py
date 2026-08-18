"""The two limit gates nothing else drives: the origin a decorated endpoint
meters under, and the daily USD cost budget.

``origin`` is not decoration — it picks which email the upsell seam sends, so
a background workflow hit that arrives labelled INTERACTIVE tells a user who
never touched the app that *they* ran out. ``enforce_daily_cost_budget`` is
the chat path's real daily wall (``chat_messages`` has no daily count limit).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.middleware.tiered_rate_limiter import (
    CostBudgetExceededException,
    RateLimitExceededException,
)
from app.constants.llm import FREE_DAILY_COST_BUDGET_USD
from app.decorators import rate_limiting as rl
from app.models.payment_models import PlanType
from app.services.limit_upsell import LimitHitOrigin


async def _endpoint() -> dict[str, bool]:
    """A rate-limited endpoint body."""
    return {"ok": True}


class TestTieredRateLimitMetersUnderItsOrigin:
    """The decorator's ``origin`` has to survive the hop into the limiter —
    a background run metered as interactive sends the wrong upsell email."""

    @staticmethod
    async def _call(origin: LimitHitOrigin | None) -> AsyncMock:
        decorated = (
            rl.tiered_rate_limit("chat_messages", origin=origin)
            if origin is not None
            else rl.tiered_rate_limit("chat_messages")
        )(_endpoint)
        with (
            patch(
                "app.decorators.rate_limiting.get_authenticated_user",
                return_value={"user_id": "user-1"},
            ),
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=MagicMock(plan_type=PlanType.FREE),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            assert await decorated() == {"ok": True}
        return mock_check

    async def test_a_background_decorator_meters_a_background_hit(self) -> None:
        mock_check = await self._call(LimitHitOrigin.BACKGROUND)

        assert mock_check.await_args.kwargs["origin"] is LimitHitOrigin.BACKGROUND

    async def test_an_undeclared_origin_meters_as_interactive(self) -> None:
        mock_check = await self._call(None)

        assert mock_check.await_args.kwargs["origin"] is LimitHitOrigin.INTERACTIVE


@contextmanager
def _budget_of(spent: float, plan: PlanType) -> Iterator[MagicMock]:
    """Run the real budget comparison against a mocked spend, yielding the
    upsell seam so a test can assert what the wall booked."""
    with (
        patch(
            "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
            return_value=plan,
        ),
        patch(
            "app.decorators.rate_limiting.get_cost",
            new_callable=AsyncMock,
            return_value=spent,
        ),
        patch("app.decorators.rate_limiting.schedule_limit_upsell") as mock_upsell,
    ):
        yield mock_upsell


class TestDailyCostBudget:
    """The rolling USD wall: exhausted spend blocks the call with the same 429
    shape the count limiter raises, and books the upsell side effects."""

    async def test_spend_under_the_budget_passes_and_books_nothing(self) -> None:
        with _budget_of(FREE_DAILY_COST_BUDGET_USD / 2, PlanType.FREE) as mock_upsell:
            await rl.enforce_daily_cost_budget("user-1", "chat_messages")

        mock_upsell.assert_not_called()

    async def test_an_exhausted_budget_blocks_with_an_upgrade_429(self) -> None:
        with (
            _budget_of(FREE_DAILY_COST_BUDGET_USD, PlanType.FREE),
            pytest.raises(CostBudgetExceededException) as raised,
        ):
            await rl.enforce_daily_cost_budget("user-1", "chat_messages")

        assert raised.value.status_code == 429
        assert raised.value.detail["feature"] == "chat_messages"
        assert raised.value.detail["plan_required"] == PlanType.PRO.value
        assert raised.value.detail["current_plan"] == PlanType.FREE.value

    async def test_the_upsell_names_the_user_feature_plan_and_origin(self) -> None:
        """Every argument is load-bearing: the plan decides whether the seam
        fires at all, the feature names the wall, the origin picks the email."""
        with _budget_of(FREE_DAILY_COST_BUDGET_USD, PlanType.FREE) as mock_upsell:
            with pytest.raises(CostBudgetExceededException):
                await rl.enforce_daily_cost_budget(
                    "user-1", "chat_messages", origin=LimitHitOrigin.BACKGROUND
                )

        mock_upsell.assert_called_once_with(
            "user-1", "chat_messages", PlanType.FREE, LimitHitOrigin.BACKGROUND
        )

    async def test_an_undeclared_origin_books_an_interactive_hit(self) -> None:
        with _budget_of(FREE_DAILY_COST_BUDGET_USD, PlanType.FREE) as mock_upsell:
            with pytest.raises(CostBudgetExceededException):
                await rl.enforce_daily_cost_budget("user-1", "chat_messages")

        assert mock_upsell.call_args.args[3] is LimitHitOrigin.INTERACTIVE

    async def test_a_paid_plan_is_blocked_without_an_upgrade_pitch(self) -> None:
        """PRO is the top plan — there is nothing to upgrade to."""
        with (
            _budget_of(1_000.0, PlanType.PRO),
            pytest.raises(CostBudgetExceededException) as raised,
        ):
            await rl.enforce_daily_cost_budget("user-1", "chat_messages")

        assert "plan_required" not in raised.value.detail
        assert raised.value.detail["current_plan"] == PlanType.PRO.value


class TestPlanLabel:
    """One helper labels the plan on both the passing context and the refusal
    card — a PlanType carries a wire value, anything else stringifies."""

    def test_an_enum_plan_uses_its_wire_value(self) -> None:
        assert rl.plan_label(PlanType.PRO) == PlanType.PRO.value

    def test_anything_else_stringifies_itself(self) -> None:
        assert rl.plan_label("legacy_plan") == "legacy_plan"
        assert rl.plan_label(None) == "None"


async def _limited_tool(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """A rate-limited tool body."""
    return {"ran": True}


class TestToolPlanLabelling:
    """Both of ``plan_label``'s call sites: the context stashed for the
    response metadata, and the inline card a blocked call streams."""

    @staticmethod
    async def _run(plan: object, writer: MagicMock | None = None) -> None:
        decorated = rl.with_rate_limiting(feature_key="generate_image")(_limited_tool)
        exceeded = (
            RateLimitExceededException(feature="generate_image", plan_required="pro")
            if writer is not None
            else None
        )
        with (
            patch(
                "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=plan),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=AsyncMock(side_effect=exceeded, return_value={}),
            ),
            patch.object(rl, "get_stream_writer", MagicMock(return_value=writer)),
        ):
            await decorated(config={"metadata": {"user_id": "user-1"}})

    async def test_an_allowed_call_records_the_enum_plans_value(self) -> None:
        await self._run(PlanType.PRO)

        assert rl.get_current_rate_limit_info()["user_plan"] == PlanType.PRO.value

    async def test_an_allowed_call_stringifies_a_non_enum_plan(self) -> None:
        await self._run("legacy_plan")

        assert rl.get_current_rate_limit_info()["user_plan"] == "legacy_plan"

    async def test_the_refusal_card_carries_the_blocked_users_plan(self) -> None:
        writer = MagicMock()

        with pytest.raises(rl.LangChainRateLimitException):
            await self._run(PlanType.PRO, writer=writer)

        assert writer.call_args.args[0]["tool_data"]["data"]["current_plan"] == PlanType.PRO.value

    async def test_the_refusal_card_stringifies_a_non_enum_plan(self) -> None:
        writer = MagicMock()

        with pytest.raises(rl.LangChainRateLimitException):
            await self._run("legacy_plan", writer=writer)

        assert writer.call_args.args[0]["tool_data"]["data"]["current_plan"] == "legacy_plan"
