"""The rate-limit card payload, and the tool decorator that streams it.

``build_rate_limit_card`` is the one shape three emitters share (this decorator,
the LLM budget wall, the free memory cap) and the frontend's ``RateLimitCard``
parses. Nothing else executes it: every other test of this module goes through
a tool that never hits its limit, so a silently reshaped payload would reach the
frontend as a card that renders empty.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.runnables import RunnableConfig
import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.decorators.rate_limiting import (
    LangChainRateLimitException,
    build_rate_limit_card,
    with_rate_limiting,
)
from app.models.payment_models import PlanType


class TestBuildRateLimitCard:
    def test_the_frame_names_the_card_the_frontend_looks_up(self) -> None:
        """``tool_name`` is the renderer key — a different string renders nothing."""
        card = build_rate_limit_card(
            feature="mail_send",
            plan_required="pro",
            reset_time="2026-01-01T00:00:00+00:00",
            current_plan="free",
        )

        assert card["tool_data"]["tool_name"] == "rate_limit_data"
        assert card["tool_data"]["tool_category"] == "system"
        assert card["tool_data"]["data"] == {
            "feature": "mail_send",
            "plan_required": "pro",
            "reset_time": "2026-01-01T00:00:00+00:00",
            "current_plan": "free",
        }

    def test_the_frame_is_timestamped_in_utc_iso(self) -> None:
        """The chat transcript orders entries by this stamp."""
        card = build_rate_limit_card(
            feature="mail_send", plan_required=None, reset_time=None, current_plan="free"
        )

        stamped = datetime.fromisoformat(card["tool_data"]["timestamp"])
        assert stamped.tzinfo is not None
        assert (datetime.now(UTC) - stamped).total_seconds() < 60

    def test_a_message_is_carried_only_when_one_was_given(self) -> None:
        """An always-present ``message: None`` would render an empty line under
        every card; the frontend falls back to its own copy when the key is
        absent."""
        without = build_rate_limit_card(
            feature="mail_send", plan_required=None, reset_time=None, current_plan="free"
        )
        with_message = build_rate_limit_card(
            feature="mail_send",
            plan_required=None,
            reset_time=None,
            current_plan="free",
            message="Daily budget spent",
        )

        assert "message" not in without["tool_data"]["data"]
        assert with_message["tool_data"]["data"]["message"] == "Daily budget spent"


@pytest.fixture
def limited_tool(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A decorated tool whose limiter always refuses, on a paid-plan user."""
    monkeypatch.setattr(
        "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
        AsyncMock(return_value=PlanType.PRO),
    )
    monkeypatch.setattr(
        "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
        AsyncMock(
            side_effect=RateLimitExceededException(
                feature="mail_send",
                plan_required="pro",
                reset_time=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ),
    )

    @with_rate_limiting("mail_send")
    async def send_mail(*, config: RunnableConfig) -> str:
        raise AssertionError("the tool body must not run once the limit binds")

    return send_mail


_CALLER = RunnableConfig(metadata={"user_id": "u-1"})


class TestRateLimitedToolStreamsTheCard:
    async def test_the_refusal_is_streamed_as_a_card_before_it_is_raised(
        self, limited_tool: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exception reaches the agent, not the user; this card is the only
        thing the user sees, so it carries the plan and the reset time."""
        writer = MagicMock()
        monkeypatch.setattr(
            "app.decorators.rate_limiting.get_stream_writer", MagicMock(return_value=writer)
        )

        with pytest.raises(LangChainRateLimitException):
            await limited_tool(config=_CALLER)

        streamed = writer.call_args.args[0]["tool_data"]["data"]
        assert streamed == {
            "feature": "mail_send",
            "plan_required": "pro",
            "reset_time": "2026-01-01T00:00:00+00:00",
            "current_plan": PlanType.PRO.value,
        }

    async def test_the_refusal_still_raises_outside_a_streaming_context(
        self, limited_tool: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Workflows and background tasks have no stream writer. The card is
        decoration; swallowing the refusal with it would let the call through."""
        monkeypatch.setattr(
            "app.decorators.rate_limiting.get_stream_writer",
            MagicMock(side_effect=RuntimeError("not in a streaming context")),
        )

        with pytest.raises(LangChainRateLimitException) as raised:
            await limited_tool(config=_CALLER)

        assert raised.value.feature == "mail_send"
        assert raised.value.reset_time == "2026-01-01T00:00:00+00:00"
