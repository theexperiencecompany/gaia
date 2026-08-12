"""Behavior tests for app.agents.llm.plan_model (per-plan LLM routing).

Locks: free -> default Concentrate pin, any paid plan -> the paid Concentrate
model (with comms reasoning effort), a lookup failure keeps the default model,
and the dev-only overrides pin/stash/clear model fields exactly.
"""

from unittest.mock import AsyncMock, patch

from app.agents.llm.plan_model import (
    apply_dev_executor_model,
    apply_dev_model_override,
    apply_plan_model,
)
from app.config.settings import settings
from app.constants.llm import (
    COMMS_REASONING_EFFORT,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_OPTIONS,
    EXECUTOR_REASONING_EFFORT,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
)
from app.models.agent_models import AgentConfigurable
from app.models.payment_models import PlanType


def _configurable() -> AgentConfigurable:
    return {"provider": "unset", "model": "unset", "model_name": "unset"}


class TestApplyPlanModel:
    async def test_no_user_id_is_a_no_op(self) -> None:
        configurable = _configurable()
        with patch(
            "app.services.payments.payment_service.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
        ) as mock_plan:
            await apply_plan_model(configurable, None)

        mock_plan.assert_not_called()
        assert configurable == {"provider": "unset", "model": "unset", "model_name": "unset"}

    async def test_free_plan_pins_the_default_model(self) -> None:
        configurable = _configurable()
        with patch(
            "app.services.payments.payment_service.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
            return_value=PlanType.FREE,
        ):
            await apply_plan_model(configurable, "user-1")

        assert configurable["provider"] == DEFAULT_LLM_PROVIDER
        assert configurable["model"] == DEFAULT_MODEL_NAME
        assert configurable["model_name"] == DEFAULT_MODEL_NAME
        # Free tier gets no reasoning-effort pin.
        assert "reasoning_effort" not in configurable

    async def test_paid_plan_pins_the_paid_model_with_reasoning(self) -> None:
        configurable = _configurable()
        with (
            patch(
                "app.services.payments.payment_service.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.PRO,
            ),
            patch(
                "app.agents.llm.plan_model._pro_monthly_budget_exhausted",
                AsyncMock(return_value=False),
            ),
        ):
            await apply_plan_model(configurable, "user-1")

        assert configurable["provider"] == PAID_MODEL_PROVIDER
        assert configurable["model"] == PAID_MODEL_NAME
        assert configurable["model_name"] == PAID_MODEL_NAME
        assert configurable["reasoning_effort"] == COMMS_REASONING_EFFORT

    async def test_lookup_failure_keeps_the_default_model(self) -> None:
        configurable = _configurable()
        with patch(
            "app.services.payments.payment_service.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis down"),
        ):
            await apply_plan_model(configurable, "user-1")

        assert configurable == {"provider": "unset", "model": "unset", "model_name": "unset"}


class TestApplyDevModelOverride:
    def _config(self) -> AgentConfigurable:
        return {
            "provider": DEFAULT_LLM_PROVIDER,
            "model": DEFAULT_MODEL_NAME,
            "model_name": DEFAULT_MODEL_NAME,
        }

    async def test_explicit_comms_selection_wins_over_plan_pin(self) -> None:
        option = DEV_MODEL_OPTIONS["glm-5.2"]
        configurable = self._config()
        apply_dev_model_override(
            configurable, comms_model="glm-5.2", executor_model=None, use_defaults=False
        )

        assert configurable["provider"] == option["provider"]
        assert configurable["model"] == option["model"]
        assert configurable["model_name"] == option["model"]
        assert configurable["reasoning_effort"] == COMMS_REASONING_EFFORT
        assert "__dev_executor_model__" not in configurable

    async def test_executor_model_is_stashed_for_later_inheritance(self) -> None:
        configurable = self._config()
        apply_dev_model_override(
            configurable, comms_model=None, executor_model="deepseek-v4", use_defaults=False
        )

        assert configurable["__dev_executor_model__"] == "deepseek-v4"
        # Comms itself is untouched when only the executor model was chosen.
        assert configurable["provider"] == DEFAULT_LLM_PROVIDER

    async def test_use_defaults_pins_dev_default_for_both_roles(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "DEV_DEFAULT_MODEL", "gemini-3.5-flash")
        option = DEV_MODEL_OPTIONS["gemini-3.5-flash"]
        configurable = self._config()
        apply_dev_model_override(
            configurable, comms_model=None, executor_model=None, use_defaults=True
        )

        assert configurable["model"] == option["model"]
        assert configurable["provider"] == option["provider"]
        assert configurable["__dev_executor_model__"] == "gemini-3.5-flash"
        # Gemini entries carry no reasoning effort — and any prior pin is cleared.
        assert "reasoning_effort" not in configurable

    async def test_invalid_dev_default_keeps_the_plan_model(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "DEV_DEFAULT_MODEL", "not-a-real-key")
        configurable = self._config()
        apply_dev_model_override(
            configurable, comms_model=None, executor_model=None, use_defaults=True
        )

        assert configurable == self._config()

    async def test_unknown_ids_are_ignored(self) -> None:
        configurable = self._config()
        apply_dev_model_override(
            configurable, comms_model="nope", executor_model="nope", use_defaults=False
        )

        assert configurable == self._config()

    async def test_non_reasoning_option_clears_a_prior_reasoning_pin(self) -> None:
        configurable = self._config()
        configurable["reasoning_effort"] = COMMS_REASONING_EFFORT
        apply_dev_model_override(
            configurable, comms_model="deepseek-v4-flash", executor_model=None, use_defaults=False
        )

        assert configurable["model"] == DEV_MODEL_OPTIONS["deepseek-v4-flash"]["model"]
        assert "reasoning_effort" not in configurable


class TestApplyDevExecutorModel:
    async def test_applies_the_stashed_executor_model_with_executor_reasoning(self) -> None:
        option = DEV_MODEL_OPTIONS["glm-5.2"]
        parent: AgentConfigurable = {"__dev_executor_model__": "glm-5.2"}
        executor: AgentConfigurable = {
            "provider": "inherited",
            "model": "inherited",
            "model_name": "inherited",
            "reasoning_effort": COMMS_REASONING_EFFORT,
        }
        apply_dev_executor_model(parent, executor)

        assert executor["provider"] == option["provider"]
        assert executor["model"] == option["model"]
        assert executor["reasoning_effort"] == EXECUTOR_REASONING_EFFORT

    async def test_non_reasoning_stashed_option_clears_inherited_reasoning(self) -> None:
        parent: AgentConfigurable = {"__dev_executor_model__": "deepseek-v4"}
        executor: AgentConfigurable = {
            "provider": "inherited",
            "model": "inherited",
            "model_name": "inherited",
            "reasoning_effort": COMMS_REASONING_EFFORT,
        }
        apply_dev_executor_model(parent, executor)

        assert "reasoning_effort" not in executor

    async def test_no_stash_is_a_no_op(self) -> None:
        parent: AgentConfigurable = {}
        executor: AgentConfigurable = {"provider": "inherited", "model_name": "inherited"}
        apply_dev_executor_model(parent, executor)

        assert executor == {"provider": "inherited", "model_name": "inherited"}

    async def test_unknown_stash_id_is_a_no_op(self) -> None:
        parent: AgentConfigurable = {"__dev_executor_model__": "bogus"}
        executor: AgentConfigurable = {"provider": "inherited", "model_name": "inherited"}
        apply_dev_executor_model(parent, executor)

        assert executor == {"provider": "inherited", "model_name": "inherited"}
