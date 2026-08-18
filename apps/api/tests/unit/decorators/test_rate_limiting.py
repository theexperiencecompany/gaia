"""The rate-limit card: how a blocked call is described to the frontend.

``build_rate_limit_card`` is the one payload shape every limit surface renders
(the tool decorator here, the LLM budget wall, the free memory cap), and
``with_rate_limiting`` is the caller that fills it in from a 429 the tiered
limiter raised. Both are asserted directly — the decorator's consumers only
ever exercise the pass-through path, so nothing else runs this code.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.decorators import rate_limiting as rl
from app.models.payment_models import PlanType

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
