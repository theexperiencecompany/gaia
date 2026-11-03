"""The single place a model gets chosen.

Everything model-selection used to spread across six files of in-place mutation
now resolves here, so these tests are the contract: what each tier gets, what the
economic guard does, what a dev override wins over, and what survives a
serialization round trip.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.llm import client as client_module, dev_lane as dev_lane_module, lane as lane_module
from app.agents.llm.lane import (
    AgentRole,
    ModelLane,
    dev_option,
    dev_option_for,
    inherits_lane,
    resolve_lane,
)
from app.config.settings import settings
from app.constants.llm import (
    COMMS_MODEL_NAME,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_OPTIONS,
    OPENROUTER_REASONING,
    PAID_COMMS_REASONING,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
    LLMProviderName,
    OpenRouterModelKwargs,
)
from app.constants.log_tags import LogTag
from app.constants.providers import CredentialProviderName
from app.models.payment_models import PlanType
from app.services.payments.payment_service import payment_service
from app.services.providers.provider_credentials_service import ProviderConfig, resolved_configs


def _custom_config(model: str | None) -> ProviderConfig:
    """Return a stored custom-endpoint credential, as the resolver returns it."""
    return ProviderConfig(
        api_key="sk-custom", base_url="https://llm.example.com/v1", model=model, preset=None
    )


#: The user every test resolves for; fakes below are keyed on it and raise on anything else.
USER = "u1"

#: A provider-routing pin, in the shape a DEV_MODEL_OPTIONS entry carries one.
_A_ROUTING_PIN: OpenRouterModelKwargs = {"provider": {"only": ["minimax"]}}


def _plan(plan: PlanType) -> Any:
    """Patch the plan read resolve_lane makes, keyed by user id."""

    async def _cached_plan_type(user_id: str) -> PlanType:
        return {USER: plan}[user_id]

    return patch.object(payment_service, "get_cached_plan_type", _cached_plan_type)


@contextmanager
def _distinct_reasoning_knobs() -> Iterator[None]:
    """Give the two reasoning knobs different values so which one a role is routed to is observable.

    PAID_COMMS_REASONING and OPENROUTER_REASONING are both {"effort": "medium"}
    right now, so an assertion on their real values would pass either way.
    """
    with (
        patch.object(lane_module, "PAID_COMMS_REASONING", {"effort": "comms-only"}),
        patch.object(lane_module, "OPENROUTER_REASONING", {"effort": "everyone-else"}),
    ):
        yield


async def _resolve(plan: PlanType, role: AgentRole = AgentRole.COMMS) -> ModelLane:
    with _plan(plan):
        resolved, _ = await resolve_lane(USER, role)
    return resolved


class TestPlanRouting:
    async def test_free_gets_the_default_model_unpinned(self) -> None:
        resolved = await _resolve(PlanType.FREE)

        assert resolved.provider == DEFAULT_LLM_PROVIDER
        assert resolved.model == DEFAULT_MODEL_NAME
        assert resolved.provider_pin is None

    async def test_paid_gets_the_paid_model_with_no_routing_pin(self) -> None:
        """No pin: an explicit pin fought sticky routing (64% cache hits vs 83-91%); key must be ABSENT, not None."""
        resolved = await _resolve(PlanType.PRO)

        assert resolved.provider == PAID_MODEL_PROVIDER
        assert resolved.model == PAID_MODEL_NAME
        assert resolved.provider_pin is None
        assert "model_kwargs" not in resolved.binding_keys()

    async def test_a_paid_lane_routes_each_role_to_its_own_reasoning_knob(self) -> None:
        """Routed to one shared knob, raising comms would silently raise every background turn's spend too."""
        with _distinct_reasoning_knobs():
            comms = await _resolve(PlanType.PRO, AgentRole.COMMS)
            executor = await _resolve(PlanType.PRO, AgentRole.EXECUTOR)

        assert comms.reasoning == {"effort": "comms-only"}
        assert executor.reasoning == {"effort": "everyone-else"}

    async def test_every_lane_carries_the_context_window(self) -> None:
        """A lane with no budget silently uncaps the summarization middleware."""
        for plan in (PlanType.FREE, PlanType.PRO):
            assert (await _resolve(plan)).max_input_tokens == DEFAULT_MAX_TOKENS

    async def test_self_host_serves_its_configured_lane_not_the_hosted_paid_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every self-host user resolves to Pro; that must not route them to the hosted paid model."""
        monkeypatch.setattr(settings, "ENV", "selfhost")
        resolved, plan = await resolve_lane(USER, AgentRole.EXECUTOR)

        assert plan is PlanType.PRO
        assert resolved == lane_module._default_lane()

    async def test_no_user_id_resolves_the_default_lane_and_no_plan(self) -> None:
        resolved, plan = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert resolved.max_input_tokens == DEFAULT_MAX_TOKENS
        assert plan is None

    async def test_a_plan_lookup_failure_keeps_the_default_lane(self) -> None:
        """A Redis hiccup must not fail the user's turn."""
        with patch.object(
            payment_service,
            "get_cached_plan_type",
            AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            resolved, plan = await resolve_lane(USER, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert plan is None

    async def test_a_plan_lookup_failure_is_reported_on_the_wide_event(self) -> None:
        """Degrading a paying user to the free model must be visible in the event, with the cause attached."""
        with (
            patch.object(
                payment_service,
                "get_cached_plan_type",
                AsyncMock(side_effect=ConnectionError("redis down")),
            ),
            patch.object(lane_module, "log") as log,
        ):
            await resolve_lane(USER, AgentRole.COMMS)

        assert log.warning.call_args.args == (
            f"{LogTag.AGENT} plan lookup failed; keeping the default lane",
        )
        assert log.warning.call_args.kwargs == {"error": "redis down"}

    async def test_the_resolved_plan_is_returned_for_the_budget_wall(self) -> None:
        plan_patch = _plan(PlanType.PRO)
        with plan_patch:
            _, plan = await resolve_lane(USER, AgentRole.COMMS)

        assert plan == PlanType.PRO


class TestReasoningPerRole:
    """The per-tier effort policy, asserted on the literal effort strings.

    Paid comms ran at low while free comms inherited the client default
    medium, so a paying user's front-door agent thought LESS than a free
    one's. These assert the values, not the constants: a test that reads the
    constant back cannot catch the constant being wrong.
    """

    async def test_paid_comms_is_never_thinner_than_free_comms(self) -> None:
        paid = await _resolve(PlanType.PRO, AgentRole.COMMS)
        free = await _resolve(PlanType.FREE, AgentRole.COMMS)

        assert paid.reasoning == {"effort": "medium"}
        assert free.reasoning == {"effort": "medium"}

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

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.reasoning is None

    async def test_a_reasoning_dev_model_gets_the_asking_roles_effort(self) -> None:
        """A dev pick is a PAID lane by definition, so comms and executor route to their own effort knob."""
        option = dev_option_for("minimax-m3", use_defaults=False)
        assert option is not None

        with _distinct_reasoning_knobs():
            comms, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)
            executor, _ = await resolve_lane(USER, AgentRole.EXECUTOR, dev_option=option)

        assert comms.reasoning == {"effort": "comms-only"}
        assert executor.reasoning == {"effort": "everyone-else"}

    async def test_a_dev_model_keeps_its_own_provider_routing_pin(self) -> None:
        option = dev_option_for("minimax-m3", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider_pin == option.provider_pin
        assert resolved.max_input_tokens == DEFAULT_MAX_TOKENS

    @pytest.mark.usefixtures("stored_credentials")
    async def test_the_custom_endpoint_resolves_the_model_the_client_would_serve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Leaving the lane's model None left LLMAccountingMiddleware pricing against DEFAULT_PRICING, ~11x the real rate."""
        monkeypatch.setitem(
            resolved_configs,
            CredentialProviderName.CUSTOM,
            _custom_config(model="nous/deepseek-v4-flash-cheap"),
        )
        option = dev_option_for("custom", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.CUSTOM
        assert resolved.model == "nous/deepseek-v4-flash-cheap"

    @pytest.mark.usefixtures("stored_credentials")
    async def test_the_custom_endpoint_pins_no_model_when_none_is_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """None is still right; the client raises its own unconfigured-endpoint error rather than being priced against a made-up name."""
        monkeypatch.setitem(
            resolved_configs, CredentialProviderName.CUSTOM, _custom_config(model=None)
        )
        option = dev_option_for("custom", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.CUSTOM
        assert resolved.model is None

    def test_an_unknown_dev_id_selects_nothing(self) -> None:
        assert dev_option_for("no-such-model", use_defaults=False) is None

    async def test_a_run_with_no_selection_starts_on_the_env_configured_dev_default(self) -> None:
        """Every top-level run, not only chat: a background narration picked nothing either."""
        with patch.object(settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            resolved, plan = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.model == "deepseek/deepseek-v4-pro"
        assert plan is None

    async def test_an_explicit_choice_wins_over_the_env_default(self) -> None:
        option = dev_option_for("minimax-m3", use_defaults=False)

        with patch.object(settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            resolved, _ = await resolve_lane(None, AgentRole.COMMS, dev_option=option)

        assert resolved.model == "minimax/minimax-m3"

    def test_a_request_that_keeps_the_defaults_selects_the_env_default(self) -> None:
        with patch.object(settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            option = dev_option_for("minimax-m3", use_defaults=True)

        assert option == DEV_MODEL_OPTIONS["deepseek-v4"]

    async def test_the_env_default_never_applies_outside_development(self) -> None:
        with (
            patch.object(settings, "DEV_DEFAULT_MODEL", "deepseek-v4"),
            patch.object(settings, "ENV", "production"),
        ):
            resolved, _ = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME

    async def test_a_bogus_env_dev_default_keeps_the_plan_lane(self) -> None:
        with patch.object(settings, "DEV_DEFAULT_MODEL", "not-a-real-id"):
            resolved, _ = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME

    async def test_a_bogus_env_dev_default_says_so_naming_the_value(self) -> None:
        """Silence here would look to a developer like the selector simply not working."""
        with (
            patch.object(settings, "DEV_DEFAULT_MODEL", "not-a-real-id"),
            patch.object(dev_lane_module, "log") as log,
        ):
            await resolve_lane(None, AgentRole.COMMS)

        assert log.warning.call_args.args == (
            (
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan-resolved lane"
            ),
        )
        assert log.warning.call_args.kwargs == {"dev_default": "not-a-real-id"}

    def test_the_stashed_executor_id_is_looked_up_without_the_env_default(self) -> None:
        """dev_option takes an id comms already resolved; the env default must not get a second chance."""
        with patch.object(settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            option = dev_option("minimax-m3")

        assert option is not None
        assert option.model == "minimax/minimax-m3"

    def test_no_stashed_id_selects_nothing(self) -> None:
        assert dev_option(None) is None


class TestSerializationRoundTrip:
    def test_a_lane_survives_the_configurable_round_trip_intact(self) -> None:
        original = ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model="vendor/model",
            reasoning={"effort": "low"},
            provider_pin={"provider": {"only": ["vendor"]}},
            max_input_tokens=131_072,
        )

        assert ModelLane.from_configurable(original.to_configurable()) == original

    def test_a_bag_written_before_lanes_existed_yields_none(self) -> None:
        """In-flight queue items and stored HIL resume_items predate the lane key."""
        assert ModelLane.from_configurable(None) is None
        assert ModelLane.from_configurable({}) is None

    def test_a_lane_is_immutable(self) -> None:
        resolved = ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model="m",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

        field = "model"
        with pytest.raises((AttributeError, TypeError)):
            setattr(resolved, field, "something-else")


class TestFallback:
    def test_the_fallback_lane_switches_provider_and_drops_the_pin(self) -> None:
        """A pin names providers on the lane being left; carrying it to a different provider turns one failure into two."""
        paid = ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model=PAID_MODEL_NAME,
            reasoning=PAID_COMMS_REASONING,
            provider_pin=_A_ROUTING_PIN,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

        with patch.object(
            lane_module,
            "chat_route",
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
            provider=LLMProviderName.OPENROUTER,
            model="m",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

        with patch.object(lane_module, "chat_route", lambda _current: None):
            assert only.fallback() is None


class TestRebindOntoAFallbackLane:
    """The other half of the provider-failover fix.

    fallback() picks the next lane; rebind() is what makes the run actually
    use it. It was untested — the regression test covered only that ainvoke_llm
    honours a fallback_config, not that the config handed to it was right.
    """

    @staticmethod
    def _paid() -> ModelLane:
        return ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model=PAID_MODEL_NAME,
            reasoning=PAID_COMMS_REASONING,
            provider_pin=_A_ROUTING_PIN,
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
        """A merge would leave the dead provider's routing pin attached, silently retrying the lane that just failed."""
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


@contextmanager
def _openai_configured(available: bool = True) -> Iterator[None]:
    """Switch the comms lane on or off: it exists only with an OpenAI key, and tests blank every key."""
    with patch.object(
        lane_module,
        "provider_configured",
        lambda provider: available and provider is LLMProviderName.OPENAI,
    ):
        yield


def _lane(provider: LLMProviderName, model: str) -> ModelLane:
    return ModelLane(
        provider=provider,
        model=model,
        reasoning=None,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


class TestCommsLane:
    @pytest.mark.parametrize("plan", [PlanType.FREE, PlanType.PRO])
    async def test_comms_runs_its_own_openai_lane_on_every_plan(self, plan: PlanType) -> None:
        with _openai_configured():
            resolved = await _resolve(plan, AgentRole.COMMS)

        assert resolved.provider == LLMProviderName.OPENAI
        assert resolved.model == COMMS_MODEL_NAME
        assert resolved.max_input_tokens == DEFAULT_MAX_TOKENS
        # The effort is pinned on the client; a reasoning key would switch ChatOpenAI's wire.
        assert "reasoning" not in resolved.binding_keys()

    async def test_the_plan_is_still_resolved_for_the_budget_wall(self) -> None:
        plan_patch = _plan(PlanType.PRO)
        with plan_patch, _openai_configured():
            _, plan = await resolve_lane(USER, AgentRole.COMMS)

        assert plan == PlanType.PRO

    async def test_no_user_still_gets_the_comms_lane(self) -> None:
        with _openai_configured():
            resolved, plan = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.provider == LLMProviderName.OPENAI
        assert plan is None

    @pytest.mark.parametrize("role", [AgentRole.EXECUTOR, AgentRole.SUBAGENT])
    async def test_the_work_tiers_keep_the_plan_lane(self, role: AgentRole) -> None:
        with _openai_configured():
            resolved = await _resolve(PlanType.PRO, role)

        assert resolved.provider == PAID_MODEL_PROVIDER
        assert resolved.model == PAID_MODEL_NAME

    async def test_without_an_openai_key_comms_runs_the_plan_lane(self) -> None:
        with _openai_configured(available=False):
            resolved = await _resolve(PlanType.FREE, AgentRole.COMMS)

        assert resolved.provider == DEFAULT_LLM_PROVIDER
        assert resolved.model == DEFAULT_MODEL_NAME

    @pytest.mark.parametrize("role", [AgentRole.EXECUTOR, AgentRole.SUBAGENT])
    def test_the_comms_lane_is_never_inherited_by_a_work_tier(self, role: AgentRole) -> None:
        assert not inherits_lane(_lane(LLMProviderName.OPENAI, COMMS_MODEL_NAME), role)

    def test_an_openrouter_parent_lane_is_still_inherited(self) -> None:
        parent = _lane(LLMProviderName.OPENROUTER, PAID_MODEL_NAME)

        assert inherits_lane(parent, AgentRole.EXECUTOR)
        assert inherits_lane(parent, AgentRole.SUBAGENT)

    def test_a_failed_comms_call_falls_back_to_openrouters_default(self) -> None:
        available = {LLMProviderName.OPENROUTER: object(), LLMProviderName.OPENAI: object()}
        with patch.object(client_module, "_get_available_providers", lambda: available):
            fallback = _lane(LLMProviderName.OPENAI, COMMS_MODEL_NAME).fallback()

        assert fallback is not None
        assert fallback.provider == LLMProviderName.OPENROUTER
        assert fallback.model == DEFAULT_MODEL_NAME
