"""The rate-limit card: how a blocked call is described to the frontend.

``build_rate_limit_card`` is the one payload shape every limit surface renders
(the tool decorator here, the LLM budget wall, the free memory cap), and
``with_rate_limiting`` is the caller that fills it in from a 429 the tiered
limiter raised. Both are asserted directly — the decorator's consumers only
ever exercise the pass-through path, so nothing else runs this code.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
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

RESET_AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


class TestBuildRateLimitCard:
    """The stream-card payload the frontend's RateLimitCard renders."""

    def test_the_card_is_a_system_rate_limit_tool_payload(self) -> None:
        card = rl.build_rate_limit_card(
            feature="generate_image",
            plan_required="pro",
            reset_time="2026-03-01T12:00:00+00:00",
            current_plan="free",
        )

        assert card["tool_data"]["tool_name"] == "rate_limit_data"
        assert card["tool_data"]["tool_category"] == "system"
        assert card["tool_data"]["data"] == {
            "feature": "generate_image",
            "plan_required": "pro",
            "reset_time": "2026-03-01T12:00:00+00:00",
            "current_plan": "free",
        }

    def test_the_card_is_stamped_with_a_utc_timestamp(self) -> None:
        card = rl.build_rate_limit_card(
            feature="generate_image",
            plan_required=None,
            reset_time=None,
            current_plan="free",
        )

        stamped = datetime.fromisoformat(card["tool_data"]["timestamp"])
        assert stamped.utcoffset() is not None  # never a naive local time
        assert stamped.utcoffset().total_seconds() == 0

    def test_an_explicit_message_travels_with_the_card(self) -> None:
        card = rl.build_rate_limit_card(
            feature="memory",
            plan_required="pro",
            reset_time=None,
            current_plan="free",
            message="You have reached the free memory cap.",
        )

        assert card["tool_data"]["data"]["message"] == "You have reached the free memory cap."

    def test_no_message_means_no_message_key(self) -> None:
        """The frontend renders its own default copy — an empty string would
        override it with a blank line."""
        card = rl.build_rate_limit_card(
            feature="memory",
            plan_required=None,
            reset_time=None,
            current_plan="free",
        )

        assert "message" not in card["tool_data"]["data"]


async def _limited_tool(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """A rate-limited tool body; never reached once the limiter raises."""
    return {"ran": True}


async def _call_blocked_tool(
    exceeded: RateLimitExceededException,
    *,
    plan: PlanType | str = PlanType.FREE,
    writer: MagicMock | None = None,
    stream_writer_error: Exception | None = None,
) -> None:
    """Drive the decorated tool with the limiter refusing the call."""
    decorated = rl.with_rate_limiting(feature_key="generate_image")(_limited_tool)
    get_writer = MagicMock(side_effect=stream_writer_error, return_value=writer or MagicMock())
    with (
        patch(
            "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
            new=AsyncMock(return_value=plan),
        ),
        patch(
            "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
            new=AsyncMock(side_effect=exceeded),
        ),
        patch.object(rl, "get_stream_writer", new=get_writer),
    ):
        await decorated(config={"metadata": {"user_id": "user-1"}})


class TestBlockedToolStreamsItsCard:
    """A tool refused by the tiered limiter emits the inline card, then raises."""

    async def test_the_card_describes_the_blocked_feature_and_the_users_plan(self) -> None:
        writer = MagicMock()

        with pytest.raises(rl.LangChainRateLimitException):
            await _call_blocked_tool(
                RateLimitExceededException(
                    feature="generate_image",
                    plan_required="pro",
                    reset_time=RESET_AT,
                ),
                plan=PlanType.PRO,
                writer=writer,
            )

        card = writer.call_args.args[0]
        assert card["tool_data"]["data"] == {
            "feature": "generate_image",
            "plan_required": "pro",
            "reset_time": RESET_AT.isoformat(),
            "current_plan": "pro",
        }

    async def test_a_plain_count_limit_offers_no_upgrade(self) -> None:
        """Nothing to upsell when the feature is in the plan and only the
        count ran out — an invented plan_required would pitch a pointless
        upgrade."""
        writer = MagicMock()

        with pytest.raises(rl.LangChainRateLimitException):
            await _call_blocked_tool(
                RateLimitExceededException(feature="generate_image", reset_time=RESET_AT),
                writer=writer,
            )

        card = writer.call_args.args[0]
        assert card["tool_data"]["data"]["plan_required"] is None
        assert card["tool_data"]["data"]["current_plan"] == "free"

    async def test_the_raised_exception_carries_the_limit_details(self) -> None:
        with pytest.raises(rl.LangChainRateLimitException) as raised:
            await _call_blocked_tool(
                RateLimitExceededException(
                    feature="generate_image",
                    plan_required="pro",
                    reset_time=RESET_AT,
                )
            )

        assert raised.value.feature == "generate_image"
        assert raised.value.reset_time == RESET_AT.isoformat()
        assert raised.value.detail["plan_required"] == "pro"

    async def test_the_agent_facing_message_is_pinned_exactly(self) -> None:
        """The message is the agent's whole instruction sheet — every clause
        (base line, reset, upsell) is pinned so the mutation gate notices if
        any of them stops reaching the model."""
        exc = rl.LangChainRateLimitException(
            feature="generate_image",
            detail={"plan_required": "pro", "current_plan": "free"},
            reset_time=RESET_AT.isoformat(),
        )

        assert str(exc) == (
            "Rate limit exceeded for generate_image."
            f" Resets at {RESET_AT.isoformat()}."
            " Upgrade to PRO for higher limits."
            " This user is on the free plan: offer to upgrade them and call"
            " `create_upgrade_link` for a checkout link if they want it."
        )

    async def test_a_free_user_is_pointed_at_the_upgrade_tool(self) -> None:
        """A wall with no way past it reads as a dead end, so the agent-facing
        message names the tool that mints a checkout link."""
        with pytest.raises(rl.LangChainRateLimitException) as raised:
            await _call_blocked_tool(
                RateLimitExceededException(
                    feature="generate_image", reset_time=RESET_AT, current_plan="free"
                )
            )

        assert str(raised.value) == (
            "Rate limit exceeded for generate_image."
            f" Resets at {RESET_AT.isoformat()}."
            " This user is on the free plan: offer to upgrade them and call"
            " `create_upgrade_link` for a checkout link if they want it."
        )

    async def test_a_pro_user_is_not_pitched_an_upgrade(self) -> None:
        with pytest.raises(rl.LangChainRateLimitException) as raised:
            await _call_blocked_tool(
                RateLimitExceededException(
                    feature="generate_image", reset_time=RESET_AT, current_plan="pro"
                )
            )

        assert str(raised.value) == (
            f"Rate limit exceeded for generate_image. Resets at {RESET_AT.isoformat()}."
        )

    async def test_no_streaming_context_still_blocks_the_call(self) -> None:
        """The card is decoration; outside a LangGraph run there is no writer
        and the refusal must still reach the agent."""
        with pytest.raises(rl.LangChainRateLimitException):
            await _call_blocked_tool(
                RateLimitExceededException(feature="generate_image", reset_time=RESET_AT),
                stream_writer_error=RuntimeError("not in a streaming context"),
            )


class TestAllowedCallRecordsTheContext:
    """The passing path stashes the plan for the response metadata. Plans
    normally arrive as a PlanType, but the fallback branch stringifies
    whatever else the cache hands back — and it must stringify THAT value,
    not a placeholder."""

    @staticmethod
    async def _run_allowed(plan: object) -> dict[str, object]:
        decorated = rl.with_rate_limiting(feature_key="generate_image")(_limited_tool)
        with (
            patch(
                "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=plan),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=AsyncMock(
                    return_value={"day": SimpleNamespace(used=1, limit=5, reset_time=RESET_AT)}
                ),
            ),
        ):
            await decorated(config={"metadata": {"user_id": "user-1"}})
        return rl.rate_limit_context.get()

    async def test_a_non_enum_plan_is_stringified_into_the_context(self) -> None:
        context = await self._run_allowed("legacy_plan")

        assert context["user_plan"] == "legacy_plan"
        assert context["feature_key"] == "generate_image"

    async def test_an_enum_plan_records_its_value(self) -> None:
        context = await self._run_allowed(PlanType.PRO)

        assert context["user_plan"] == PlanType.PRO.value


class TestPlanLabel:
    """One helper feeds both the passing context and the refusal card."""

    def test_an_enum_plan_uses_its_wire_value(self) -> None:
        assert rl.plan_label(PlanType.PRO) == PlanType.PRO.value

    def test_anything_else_stringifies_itself(self) -> None:
        assert rl.plan_label("legacy_plan") == "legacy_plan"
        assert rl.plan_label(None) == "None"


class TestBlockedCallLabelsANonEnumPlan:
    async def test_the_card_carries_the_stringified_plan(self) -> None:
        writer = MagicMock()

        with pytest.raises(rl.LangChainRateLimitException):
            await _call_blocked_tool(
                RateLimitExceededException(
                    feature="generate_image",
                    plan_required="pro",
                    reset_time=RESET_AT,
                ),
                plan="legacy_plan",
                writer=writer,
            )

        assert writer.call_args.args[0]["tool_data"]["data"]["current_plan"] == "legacy_plan"


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
