"""The single place a model gets chosen.

Everything model-selection used to spread across six files of in-place mutation
now resolves here, so these tests are the contract: what each tier gets, what the
economic guard does, what a dev override wins over, and what survives a
serialization round trip.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.llm import lane as lane_module
from app.agents.llm.lane import (
    AgentRole,
    ModelLane,
    dev_option_for,
    resolve_lane,
)
from app.agents.llm.types import LLMProviderName
from app.constants.llm import (
    COMMS_REASONING,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    OPENROUTER_REASONING,
    PAID_MODEL_MODEL_KWARGS,
    PAID_MODEL_NAME,
)
from app.models.payment_models import PlanType


def _plan(plan: PlanType, *, over_budget: bool = False) -> Any:
    """Patch the two external reads resolve_lane makes."""
    return (
        patch.object(
            lane_module.payment_service, "get_cached_plan_type", AsyncMock(return_value=plan)
        ),
        patch.object(
            lane_module, "_pro_monthly_budget_exhausted", AsyncMock(return_value=over_budget)
        ),
        patch.object(lane_module, "spawn_background_task", lambda coro: coro.close()),
    )


async def _resolve(
    plan: PlanType, role: AgentRole = AgentRole.COMMS, *, over_budget: bool = False
) -> ModelLane:
    a, b, c = _plan(plan, over_budget=over_budget)
    with a, b, c:
        resolved, _ = await resolve_lane("u1", role)
    return resolved


class TestPlanRouting:
    async def test_free_gets_the_default_model_unpinned(self) -> None:
        resolved = await _resolve(PlanType.FREE)

        assert resolved.provider == DEFAULT_LLM_PROVIDER
        assert resolved.model == DEFAULT_MODEL_NAME
        assert resolved.provider_pin is None

    async def test_paid_gets_the_paid_model_on_the_first_party_lane(self) -> None:
        """Without the pin, OpenRouter load-balances across resellers whose shared
        pools get rate-limited upstream."""
        resolved = await _resolve(PlanType.PRO)

        assert resolved.model == PAID_MODEL_NAME
        assert resolved.provider_pin == PAID_MODEL_MODEL_KWARGS

    async def test_no_user_id_resolves_the_default_lane_and_no_plan(self) -> None:
        resolved, plan = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert plan is None

    async def test_a_plan_lookup_failure_keeps_the_default_lane(self) -> None:
        """A Redis hiccup must not fail the user's turn."""
        with patch.object(
            lane_module.payment_service,
            "get_cached_plan_type",
            AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            resolved, plan = await resolve_lane("u1", AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert plan is None

    async def test_the_resolved_plan_is_returned_for_the_budget_wall(self) -> None:
        a, b, c = _plan(PlanType.PRO)
        with a, b, c:
            _, plan = await resolve_lane("u1", AgentRole.COMMS)

        assert plan == PlanType.PRO


class TestMonthlyEconomicGuard:
    async def test_an_over_budget_paid_user_is_degraded_not_blocked(self) -> None:
        resolved = await _resolve(PlanType.PRO, over_budget=True)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert resolved.provider_pin is None

    async def test_the_degraded_user_keeps_their_paid_tier(self) -> None:
        """Only the model degrades — every other pro entitlement stays intact, so
        the budget wall must still see PRO."""
        a, b, c = _plan(PlanType.PRO, over_budget=True)
        with a, b, c:
            _, plan = await resolve_lane("u1", AgentRole.COMMS)

        assert plan == PlanType.PRO


class TestReasoningPerRole:
    """Characterization of today's effort split, NOT an endorsement.

    A free comms turn resolves ``medium`` because it never set the key and
    inherited the client default; a paid comms turn explicitly set ``low``. Free
    therefore out-thinks pro. That is a deliberate open non-decision — these
    tests exist so the refactor cannot change it by accident. If tier policy is
    revisited, change them consciously.
    """

    async def test_paid_comms_uses_the_lower_comms_effort(self) -> None:
        assert (await _resolve(PlanType.PRO, AgentRole.COMMS)).reasoning == COMMS_REASONING

    async def test_paid_executor_keeps_the_client_default_effort(self) -> None:
        assert (await _resolve(PlanType.PRO, AgentRole.EXECUTOR)).reasoning == OPENROUTER_REASONING

    @pytest.mark.parametrize("role", list(AgentRole))
    async def test_free_keeps_the_client_default_effort_on_every_role(
        self, role: AgentRole
    ) -> None:
        assert (await _resolve(PlanType.FREE, role)).reasoning == OPENROUTER_REASONING


class TestDevOverride:
    async def test_a_dev_option_wins_over_the_plan_lane(self) -> None:
        option = dev_option_for("gemini-3.1-flash-lite", use_defaults=False)
        assert option is not None

        resolved, plan = await resolve_lane("u1", AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.GEMINI
        assert resolved.model == "gemini-3.1-flash-lite"
        assert plan is None

    async def test_a_non_reasoning_dev_model_carries_no_reasoning_config(self) -> None:
        """Otherwise an OpenRouter reasoning pin leaks onto a Gemini-routed model."""
        option = dev_option_for("gemini-3.1-flash-lite", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane("u1", AgentRole.COMMS, dev_option=option)

        assert resolved.reasoning is None

    async def test_the_custom_endpoint_pins_no_model_so_the_client_default_serves_it(
        self,
    ) -> None:
        option = dev_option_for("custom", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane("u1", AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.CUSTOM
        assert resolved.model is None

    def test_an_unknown_dev_id_selects_nothing(self) -> None:
        assert dev_option_for("no-such-model", use_defaults=False) is None

    def test_no_selection_falls_back_to_the_env_configured_dev_default(self) -> None:
        with patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            option = dev_option_for(None, use_defaults=True)

        assert option is not None
        assert option["model"] == "deepseek/deepseek-v4-pro"

    def test_a_bogus_env_dev_default_selects_nothing(self) -> None:
        with patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "not-a-real-id"):
            assert dev_option_for(None, use_defaults=True) is None


class TestSerializationRoundTrip:
    def test_a_lane_survives_the_configurable_round_trip_intact(self) -> None:
        original = ModelLane(
            provider="openrouter",
            model="vendor/model",
            reasoning={"effort": "low"},
            provider_pin={"provider": {"only": ["vendor"]}},
            max_input_tokens=131_072,
        )

        assert ModelLane.from_configurable(original.to_configurable()) == original

    def test_a_bag_written_before_lanes_existed_yields_none(self) -> None:
        """In-flight queue items and stored HIL resume_items predate the lane key;
        the caller resolves a fresh lane rather than crashing on them."""
        assert ModelLane.from_configurable(None) is None
        assert ModelLane.from_configurable({}) is None

    def test_a_lane_is_immutable(self) -> None:
        resolved = ModelLane(
            provider="openrouter",
            model="m",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

        with pytest.raises((AttributeError, TypeError)):
            resolved.model = "something-else"  # type: ignore[misc]


class TestFallback:
    def test_the_fallback_lane_switches_provider_and_drops_the_pin(self) -> None:
        """A pin names providers on the lane being left; carrying it to a different
        provider turns one failure into two."""
        paid = ModelLane(
            provider="openrouter",
            model=PAID_MODEL_NAME,
            reasoning=COMMS_REASONING,
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

        with patch.object(
            lane_module,
            "next_fallback_provider",
            lambda _current: (LLMProviderName.GEMINI, "gemini-x"),
        ):
            fallback = paid.fallback()

        assert fallback is not None
        assert fallback.provider == LLMProviderName.GEMINI
        assert fallback.model == "gemini-x"
        assert fallback.provider_pin is None
        assert fallback.reasoning == COMMS_REASONING

    def test_no_other_configured_provider_yields_no_fallback(self) -> None:
        only = ModelLane(
            provider="openrouter",
            model="m",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

        with patch.object(lane_module, "next_fallback_provider", lambda _current: None):
            assert only.fallback() is None
