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
    _notify_degrade_once,
    _pro_monthly_budget_exhausted,
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
    PRO_MONTHLY_COST_BUDGET_USD,
)
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
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


class TestTheMonthlySpendRead:
    """The guard's own read. ``TestMonthlyEconomicGuard`` patches it out to test
    routing, so without these the read itself never runs."""

    async def test_spend_at_the_budget_crosses_the_guard(self) -> None:
        with patch.object(
            lane_module, "get_cost", AsyncMock(return_value=PRO_MONTHLY_COST_BUDGET_USD)
        ):
            assert await _pro_monthly_budget_exhausted("u1") is True

    async def test_spend_below_the_budget_keeps_the_paid_lane(self) -> None:
        with patch.object(
            lane_module, "get_cost", AsyncMock(return_value=PRO_MONTHLY_COST_BUDGET_USD - 0.01)
        ):
            assert await _pro_monthly_budget_exhausted("u1") is False

    async def test_a_read_failure_fails_open_and_keeps_the_paid_lane(self) -> None:
        """A paying user is never degraded because the spend read broke."""
        with patch.object(
            lane_module, "get_cost", AsyncMock(side_effect=ConnectionError("redis down"))
        ):
            assert await _pro_monthly_budget_exhausted("u1") is False


class _FakeRedisSetNX:
    """Just enough SET NX semantics to prove the notice fires once."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class TestDegradeNotice:
    async def test_the_notice_fires_once_a_month_not_every_degraded_turn(self) -> None:
        created = AsyncMock()
        with (
            patch.object(lane_module.redis_cache, "redis", _FakeRedisSetNX()),
            patch.object(lane_module.notification_service, "create_notification", created),
        ):
            await _notify_degrade_once("u1")
            await _notify_degrade_once("u1")

        assert created.await_count == 1

    async def test_each_user_gets_their_own_notice(self) -> None:
        created = AsyncMock()
        with (
            patch.object(lane_module.redis_cache, "redis", _FakeRedisSetNX()),
            patch.object(lane_module.notification_service, "create_notification", created),
        ):
            await _notify_degrade_once("u1")
            await _notify_degrade_once("u2")

        assert [call.args[0].user_id for call in created.await_args_list] == ["u1", "u2"]

    async def test_the_notice_is_an_informational_usage_limit_message(self) -> None:
        created = AsyncMock()
        with (
            patch.object(lane_module.redis_cache, "redis", _FakeRedisSetNX()),
            patch.object(lane_module.notification_service, "create_notification", created),
        ):
            await _notify_degrade_once("u1")

        request = created.await_args_list[0].args[0]
        assert request.source == NotificationSourceEnum.USAGE_LIMIT
        assert request.type == NotificationType.INFO

    async def test_no_redis_client_sends_nothing(self) -> None:
        """Without the SET NX gate there is no once-a-month guarantee, so the
        notice is skipped rather than sent on every degraded turn."""
        created = AsyncMock()
        with (
            patch.object(lane_module.redis_cache, "redis", None),
            patch.object(lane_module.notification_service, "create_notification", created),
        ):
            await _notify_degrade_once("u1")

        created.assert_not_awaited()

    async def test_a_failed_notice_never_reaches_the_degraded_turn(self) -> None:
        """The lane already degraded successfully; the notice is best-effort."""
        with (
            patch.object(lane_module.redis_cache, "redis", _FakeRedisSetNX()),
            patch.object(
                lane_module.notification_service,
                "create_notification",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
        ):
            await _notify_degrade_once("u1")


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

        field = "model"
        with pytest.raises((AttributeError, TypeError)):
            setattr(resolved, field, "something-else")


class TestRebind:
    """A plain merge is what made provider failover a silent no-op: LangChain
    merges a passed config OVER a ``with_config`` one, so an un-cleared key put
    the just-failed provider straight back."""

    def _gemini(self) -> ModelLane:
        return ModelLane(
            provider=LLMProviderName.GEMINI,
            model="gemini-x",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

    def test_the_previous_lanes_binding_keys_are_removed_not_overwritten(self) -> None:
        rebound = self._gemini().rebind(
            {
                "provider": LLMProviderName.OPENROUTER,
                "model": PAID_MODEL_NAME,
                "reasoning": COMMS_REASONING,
                "model_kwargs": PAID_MODEL_MODEL_KWARGS,
            }
        )

        assert rebound["provider"] == LLMProviderName.GEMINI
        assert rebound["model"] == "gemini-x"
        # Both are OpenRouter-wire concepts; carrying either onto Gemini is how a
        # fallback turns one failure into two.
        assert "reasoning" not in rebound
        assert "model_kwargs" not in rebound

    def test_everything_the_lane_does_not_own_survives(self) -> None:
        rebound = self._gemini().rebind({"user_id": "u1", "thread_id": "t1"})

        assert rebound["user_id"] == "u1"
        assert rebound["thread_id"] == "t1"


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
        # reasoning is an OpenRouter-wire concept like the pin; it must not ride
        # onto a Gemini lane that never declared the field.
        assert fallback.reasoning is None

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


class TestRebindOntoAFallbackLane:
    """The other half of the provider-failover fix.

    ``fallback()`` picks the next lane; ``rebind()`` is what makes the run actually
    use it. It was untested — the regression test covered only that ainvoke_llm
    honours a fallback_config, not that the config handed to it was right.
    """

    @staticmethod
    def _paid() -> ModelLane:
        return ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model=PAID_MODEL_NAME,
            reasoning=COMMS_REASONING,
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

    @staticmethod
    def _gemini() -> ModelLane:
        return ModelLane(
            provider=LLMProviderName.GEMINI,
            model="gemini-probe",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

    def test_the_failed_lanes_keys_are_removed_not_merged_over(self) -> None:
        """A merge would leave the dead provider's routing pin attached — which is
        exactly how the failover silently retried the lane that had just failed."""
        rebound = self._gemini().rebind({"user_id": "u1", **self._paid().binding_keys()})

        assert rebound["provider"] == LLMProviderName.GEMINI
        assert rebound["model"] == "gemini-probe"
        # ABSENT, not None: an explicit None would clobber the client's own
        # default instead of letting it serve the request.
        assert "model_kwargs" not in rebound
        assert "reasoning" not in rebound

    def test_keys_that_are_not_the_lanes_business_survive(self) -> None:
        rebound = self._gemini().rebind(
            {"user_id": "u1", "thread_id": "t", "plan_type": "pro", **self._paid().binding_keys()}
        )

        assert rebound["user_id"] == "u1"
        assert rebound["thread_id"] == "t"
        assert rebound["plan_type"] == "pro"

    def test_rebinding_onto_the_same_lane_is_a_no_op_for_its_own_keys(self) -> None:
        paid = self._paid()

        assert paid.rebind(dict(paid.binding_keys())) == dict(paid.binding_keys())
