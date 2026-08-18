"""The single place a model gets chosen.

Everything model-selection used to spread across six files of in-place mutation
now resolves here, so these tests are the contract: what each tier gets, what the
economic guard does, what a dev override wins over, and what survives a
serialization round trip.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import DataError

from app.agents.llm import lane as lane_module
from app.agents.llm.client import PROVIDER_MODELS
from app.agents.llm.lane import (
    AgentRole,
    ModelLane,
    _notify_degrade_once,
    _pro_monthly_budget_exhausted,
    dev_option,
    dev_option_for,
    resolve_lane,
)
from app.agents.llm.types import LLMProviderName
from app.config.rate_limits import RateLimitPeriod
from app.constants.cache import COST_BUDGET_NOTIFIED_KEY
from app.constants.llm import (
    COMMS_REASONING,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    MONTHLY_BUDGET_TTL_SECONDS,
    OPENROUTER_REASONING,
    PAID_MODEL_MODEL_KWARGS,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
    PRO_MONTHLY_COST_BUDGET_USD,
)
from app.constants.log_tags import LogTag
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.payment_models import PlanType

#: The user every test resolves for. The fakes below are keyed on it and raise on
#: anything else, so "the right user's plan/spend" is asserted by construction —
#: a lookup for the wrong user (or for ``None``) fails instead of quietly
#: answering.
USER = "u1"


def _plan(plan: PlanType, *, over_budget: bool = False) -> Any:
    """Patch the two external reads resolve_lane makes, keyed by user id."""

    async def _cached_plan_type(user_id: str) -> PlanType:
        return {USER: plan}[user_id]

    async def _exhausted(user_id: str) -> bool:
        return {USER: over_budget}[user_id]

    return (
        patch.object(lane_module.payment_service, "get_cached_plan_type", _cached_plan_type),
        patch.object(lane_module, "_pro_monthly_budget_exhausted", _exhausted),
        patch.object(lane_module, "spawn_background_task", lambda coro: coro.close()),
    )


async def _resolve(
    plan: PlanType, role: AgentRole = AgentRole.COMMS, *, over_budget: bool = False
) -> ModelLane:
    a, b, c = _plan(plan, over_budget=over_budget)
    with a, b, c:
        resolved, _ = await resolve_lane(USER, role)
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

        assert resolved.provider == PAID_MODEL_PROVIDER
        assert resolved.model == PAID_MODEL_NAME
        assert resolved.provider_pin == PAID_MODEL_MODEL_KWARGS

    async def test_every_lane_carries_the_context_window(self) -> None:
        """A lane with no budget silently uncaps the summarization middleware."""
        for plan in (PlanType.FREE, PlanType.PRO):
            assert (await _resolve(plan)).max_input_tokens == DEFAULT_MAX_TOKENS

    async def test_no_user_id_resolves_the_default_lane_and_no_plan(self) -> None:
        resolved, plan = await resolve_lane(None, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert resolved.max_input_tokens == DEFAULT_MAX_TOKENS
        assert plan is None

    async def test_a_plan_lookup_failure_keeps_the_default_lane(self) -> None:
        """A Redis hiccup must not fail the user's turn."""
        with patch.object(
            lane_module.payment_service,
            "get_cached_plan_type",
            AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            resolved, plan = await resolve_lane(USER, AgentRole.COMMS)

        assert resolved.model == DEFAULT_MODEL_NAME
        assert plan is None

    async def test_a_plan_lookup_failure_is_reported_on_the_wide_event(self) -> None:
        """Degrading a paying user to the free model is exactly the kind of silent
        downgrade that must be visible in the event, with the cause attached."""
        with (
            patch.object(
                lane_module.payment_service,
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
        a, b, c = _plan(PlanType.PRO)
        with a, b, c:
            _, plan = await resolve_lane(USER, AgentRole.COMMS)

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
            _, plan = await resolve_lane(USER, AgentRole.COMMS)

        assert plan == PlanType.PRO

    async def test_the_degrade_is_a_named_event_carrying_who_and_which_tier(self) -> None:
        """``pro_model_degraded`` is the queryable signal that the economic guard
        fired. Without the user and tier on it, nobody can tell who it hit."""
        a, b, c = _plan(PlanType.PRO, over_budget=True)
        with a, b, c, patch.object(lane_module, "log") as log:
            await resolve_lane(USER, AgentRole.COMMS)

        assert log.warning.call_args.args == ("pro_model_degraded",)
        assert log.warning.call_args.kwargs == {
            "event_name": "pro_model_degraded",
            "user_id": USER,
            "plan": PlanType.PRO.value,
        }

    async def test_a_user_under_the_guard_is_never_degraded(self) -> None:
        assert (await _resolve(PlanType.PRO, over_budget=False)).model == PAID_MODEL_NAME


def _spend(amount: float) -> Any:
    """Patch the spend read with THIS month's cost for THIS user.

    Keyed rather than a blanket return: the guard must read the right user's
    month, and a lookup for anyone (or any window) else has to fail rather than
    answer.
    """

    async def _get_cost(user_id: str, period: RateLimitPeriod) -> float:
        return {(USER, RateLimitPeriod.MONTH): amount}[(user_id, period)]

    return patch.object(lane_module, "get_cost", _get_cost)


class TestTheMonthlySpendRead:
    """The guard's own read. ``TestMonthlyEconomicGuard`` patches it out to test
    routing, so without these the read itself never runs."""

    async def test_spend_at_the_budget_crosses_the_guard(self) -> None:
        with _spend(PRO_MONTHLY_COST_BUDGET_USD):
            assert await _pro_monthly_budget_exhausted(USER) is True

    async def test_spend_below_the_budget_keeps_the_paid_lane(self) -> None:
        with _spend(PRO_MONTHLY_COST_BUDGET_USD - 0.01):
            assert await _pro_monthly_budget_exhausted(USER) is False

    async def test_a_read_failure_fails_open_and_keeps_the_paid_lane(self) -> None:
        """A paying user is never degraded because the spend read broke."""
        with patch.object(
            lane_module, "get_cost", AsyncMock(side_effect=ConnectionError("redis down"))
        ):
            assert await _pro_monthly_budget_exhausted(USER) is False

    async def test_the_read_failure_is_reported_with_its_cause(self) -> None:
        with (
            patch.object(
                lane_module, "get_cost", AsyncMock(side_effect=ConnectionError("redis down"))
            ),
            patch.object(lane_module, "log") as log,
        ):
            await _pro_monthly_budget_exhausted(USER)

        assert log.warning.call_args.args == (
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
        )
        assert log.warning.call_args.kwargs == {
            "error": "redis down",
            "error_type": "ConnectionError",
        }


class _FakeRedisSetNX:
    """SET NX semantics, faithful on the two points this gate rests on.

    A non-str value raises the way redis-py does (``DataError``) rather than
    being stored: the marker has to be something Redis can actually hold, and a
    fake that swallows anything would call a broken write a success. The TTL is
    recorded because the notice is once *a month*, not once *ever*.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if not isinstance(value, str | bytes | int | float):
            raise DataError(f"Invalid input of type {type(value).__name__}")
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.ttl[key] = ex
        return True


#: A fixed month window, so the copy and the gate key are asserted against a
#: value rather than against whatever the wall clock says today.
WINDOW = "209901"
RESET = datetime(2099, 2, 1, tzinfo=UTC)


def _month_window() -> Any:
    """Pin the two period-derived reads to the MONTH window.

    Keyed on the period rather than a blanket return: both helpers treat every
    non-DAY period as MONTH, so a blanket fake cannot tell "asked for the month"
    from "asked for nothing" — and this notice is once a MONTH, named after the
    month's reset date.
    """
    return (
        patch.object(
            lane_module,
            "get_time_window_key",
            lambda period: {RateLimitPeriod.MONTH: WINDOW}[period],
        ),
        patch.object(
            lane_module, "get_reset_time", lambda period: {RateLimitPeriod.MONTH: RESET}[period]
        ),
    )


class _Notice:
    """Every patch the notice needs, as one context manager."""

    def __init__(self, client: _FakeRedisSetNX | None = None, notify: Any = None) -> None:
        self.client = _FakeRedisSetNX() if client is None else client
        self.created = AsyncMock() if notify is None else notify
        self._patches = [
            patch.object(lane_module.redis_cache, "redis", self.client),
            patch.object(lane_module.notification_service, "create_notification", self.created),
            *_month_window(),
        ]

    def __enter__(self) -> "_Notice":
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self._patches):
            p.stop()

    @property
    def request(self) -> Any:
        return self.created.await_args_list[0].args[0]


class TestDegradeNotice:
    async def test_the_notice_fires_once_a_month_not_every_degraded_turn(self) -> None:
        with _Notice() as notice:
            await _notify_degrade_once(USER)
            await _notify_degrade_once(USER)

        assert notice.created.await_count == 1

    async def test_the_gate_is_keyed_to_this_user_and_this_month(self) -> None:
        """A key missing either part is a notice that fires for the wrong person
        or never fires again."""
        with _Notice() as notice:
            await _notify_degrade_once(USER)

        assert list(notice.client.store) == [
            COST_BUDGET_NOTIFIED_KEY.format(user_id=USER, window=WINDOW)
        ]

    async def test_the_gate_holds_a_marker_redis_can_actually_store(self) -> None:
        with _Notice() as notice:
            await _notify_degrade_once(USER)

        assert list(notice.client.store.values()) == ["1"]

    async def test_the_gate_expires_so_next_month_notifies_again(self) -> None:
        with _Notice() as notice:
            await _notify_degrade_once(USER)

        assert list(notice.client.ttl.values()) == [MONTHLY_BUDGET_TTL_SECONDS]

    async def test_each_user_gets_their_own_notice(self) -> None:
        with _Notice() as notice:
            await _notify_degrade_once(USER)
            await _notify_degrade_once("u2")

        assert [call.args[0].user_id for call in notice.created.await_args_list] == [USER, "u2"]

    async def test_the_notice_is_an_informational_usage_limit_message(self) -> None:
        with _Notice() as notice:
            await _notify_degrade_once(USER)

        assert notice.request.source == NotificationSourceEnum.USAGE_LIMIT
        assert notice.request.type == NotificationType.INFO

    async def test_the_notice_tells_the_user_what_happened_and_until_when(self) -> None:
        """The whole point of the notice: a paying user's model just changed under
        them, so the copy has to say so and name the date it comes back."""
        with _Notice() as notice:
            await _notify_degrade_once(USER)

        assert notice.request.content.title == "Priority compute used for this month"
        assert notice.request.content.body == (
            "You've used this month's priority AI compute. GAIA keeps "
            f"working on the standard model until {RESET:%b %d}."
        )

    async def test_no_redis_client_sends_nothing(self) -> None:
        """Without the SET NX gate there is no once-a-month guarantee, so the
        notice is skipped rather than sent on every degraded turn."""
        with _Notice() as notice, patch.object(lane_module.redis_cache, "redis", None):
            await _notify_degrade_once(USER)

        notice.created.assert_not_awaited()

    async def test_a_failed_notice_never_reaches_the_degraded_turn(self) -> None:
        """The lane already degraded successfully; the notice is best-effort."""
        with _Notice(notify=AsyncMock(side_effect=RuntimeError("mongo down"))):
            await _notify_degrade_once(USER)

    async def test_a_failed_notice_is_reported_with_its_cause(self) -> None:
        with (
            _Notice(notify=AsyncMock(side_effect=RuntimeError("mongo down"))),
            patch.object(lane_module, "log") as log,
        ):
            await _notify_degrade_once(USER)

        assert log.warning.call_args.args == (f"{LogTag.AGENT} Degrade notice failed",)
        assert log.warning.call_args.kwargs == {
            "error": "mongo down",
            "error_type": "RuntimeError",
        }

    async def test_the_degraded_turn_notifies_the_user_it_degraded(self) -> None:
        """resolve_lane spawns the notice rather than awaiting it, so the user's
        turn is not held up by a notification write. The spawned work still has to
        be the notice for THIS user."""
        spawned: list[Any] = []
        plan, budget, _ = _plan(PlanType.PRO, over_budget=True)
        with (
            plan,
            budget,
            patch.object(lane_module, "spawn_background_task", spawned.append),
            _Notice() as notice,
        ):
            await resolve_lane(USER, AgentRole.COMMS)
            assert len(spawned) == 1
            await spawned[0]

        assert notice.request.user_id == USER


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

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.reasoning is None

    async def test_a_reasoning_dev_model_gets_the_asking_roles_effort(self) -> None:
        """A dev pick is a PAID lane by definition — it is an explicit choice, not
        plan routing — so comms gets the lower comms effort and the executor the
        client default, exactly as a paid turn does."""
        option = dev_option_for("minimax-m3", use_defaults=False)
        assert option is not None

        comms, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)
        executor, _ = await resolve_lane(USER, AgentRole.EXECUTOR, dev_option=option)

        assert comms.reasoning == COMMS_REASONING
        assert executor.reasoning == OPENROUTER_REASONING

    async def test_a_dev_model_keeps_its_own_provider_routing_pin(self) -> None:
        option = dev_option_for("minimax-m3", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider_pin == option["model_kwargs"]
        assert resolved.max_input_tokens == DEFAULT_MAX_TOKENS

    async def test_the_custom_endpoint_resolves_the_model_the_client_would_have_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEV_MODEL_OPTIONS["custom"] carries no model. Leaving the lane's model
        None priced the call as "unknown", which falls through to DEFAULT_PRICING
        (~11x our default model's real rate) and undercharges the budget. The
        client binds PROVIDER_MODELS[CUSTOM] (resolved once at import from
        DEV_LLM_MODEL) whenever the lane pins no model, so resolving that same
        name here does not change which model runs — it makes it visible."""
        monkeypatch.setitem(PROVIDER_MODELS, LLMProviderName.CUSTOM, "nous/deepseek-v4-cheap")
        option = dev_option_for("custom", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.CUSTOM
        assert resolved.model == "nous/deepseek-v4-cheap"

    async def test_an_unconfigured_custom_endpoint_pins_no_model_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEV_LLM_MODEL unset makes PROVIDER_MODELS[CUSTOM] the empty string, so
        the name is genuinely unknown ahead of the call. None is still right: a
        placeholder would price the call against a model that does not exist, and
        the client fails on its own unconfigured endpoint instead."""
        monkeypatch.setitem(PROVIDER_MODELS, LLMProviderName.CUSTOM, "")
        option = dev_option_for("custom", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.CUSTOM
        assert resolved.model is None

    async def test_a_lane_missing_from_the_client_map_entirely_pins_no_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sibling above configures the lane to an empty string. Absent from
        PROVIDER_MODELS altogether there is no resolved name at all, and the
        fallback has to stay falsy rather than inventing one."""
        monkeypatch.delitem(PROVIDER_MODELS, LLMProviderName.CUSTOM, raising=False)
        option = dev_option_for("custom", use_defaults=False)
        assert option is not None

        resolved, _ = await resolve_lane(USER, AgentRole.COMMS, dev_option=option)

        assert resolved.provider == LLMProviderName.CUSTOM
        assert resolved.model is None

    def test_an_unknown_dev_id_selects_nothing(self) -> None:
        assert dev_option_for("no-such-model", use_defaults=False) is None

    def test_no_selection_falls_back_to_the_env_configured_dev_default(self) -> None:
        with patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            option = dev_option_for(None, use_defaults=True)

        assert option is not None
        assert option["model"] == "deepseek/deepseek-v4-pro"

    def test_an_explicit_choice_wins_over_the_env_default(self) -> None:
        with patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            option = dev_option_for("minimax-m3", use_defaults=False)

        assert option is not None
        assert option["model"] == "minimax/minimax-m3"

    def test_a_bogus_env_dev_default_selects_nothing(self) -> None:
        with patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "not-a-real-id"):
            assert dev_option_for(None, use_defaults=True) is None

    def test_a_bogus_env_dev_default_says_so_naming_the_value(self) -> None:
        """Silence here is a developer whose DEV_DEFAULT_MODEL typo looks like the
        selector simply not working."""
        with (
            patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "not-a-real-id"),
            patch.object(lane_module, "log") as log,
        ):
            dev_option_for(None, use_defaults=True)

        assert log.warning.call_args.args == (
            (
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan-resolved lane"
            ),
        )
        assert log.warning.call_args.kwargs == {"dev_default": "not-a-real-id"}

    def test_the_stashed_executor_id_is_looked_up_without_the_env_default(self) -> None:
        """``dev_option`` takes an id comms already resolved, so the env default
        must not get a second chance to override it here."""
        with patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", "deepseek-v4"):
            option = dev_option("minimax-m3")

        assert option is not None
        assert option["model"] == "minimax/minimax-m3"

    def test_no_stashed_id_selects_nothing(self) -> None:
        assert dev_option(None) is None


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
