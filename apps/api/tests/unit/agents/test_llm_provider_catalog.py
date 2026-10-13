"""Every LLM role on a single configured provider, and production's routing pinned verbatim.

A self-hosted instance configured with only OpenAI, Gemini, Ollama or a custom
endpoint must run comms, the executor and every one-shot role on it — and fail
loud, naming the role, when none of them can. Production must not move at all.
"""

from collections.abc import Iterator
from typing import cast

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
import pytest

from app.agents.llm import client as client_module
from app.agents.llm.client import (
    _build_default_llm,
    _build_gemini_one_shot,
    _build_openai_wire_one_shot,
    _get_ordered_providers,
    one_shot_route,
    resolve_model,
)
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.llm.lane import AgentRole, resolve_lane
from app.agents.llm.types import ProviderLLM
from app.constants.llm import LLMProviderName, ModelUse
from app.constants.providers import CREDENTIAL_PROVIDERS
from app.services.providers.provider_credentials_service import ProviderConfig

_LLM_REGISTRY_KEYS = {
    LLMProviderName.OPENROUTER: "openrouter_llm",
    LLMProviderName.GEMINI: "gemini_llm",
    LLMProviderName.OPENAI: "openai_llm",
    LLMProviderName.OLLAMA: "ollama_llm",
    LLMProviderName.CUSTOM: "custom_llm",
}


def _config(
    api_key: str | None = None, base_url: str | None = None, model: str | None = None
) -> ProviderConfig:
    return ProviderConfig(api_key=api_key, base_url=base_url, model=model, preset=None)


_OPENROUTER = _config(api_key="sk-or")
_GEMINI = _config(api_key="g-key")
_OPENAI = _config(api_key="sk-openai")
_OLLAMA = _config(base_url="http://127.0.0.1:11434", model="qwen3:8b")
_CUSTOM = _config(api_key="sk-custom", base_url="https://llm.example.com/v1", model="my-model")


class _Registry:
    """The lazy-provider registry: one placeholder client per registered LLM name."""

    def get(self, key: str) -> object:
        if key not in _LLM_REGISTRY_KEYS.values():
            raise KeyError(key)
        return object()


@pytest.fixture(autouse=True)
def _instance(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Resolve every credential to nothing, so each test configures exactly what it names."""
    monkeypatch.setattr(client_module.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client_module.settings, "DEV_DEFAULT_MODEL", None)
    monkeypatch.setattr(client_module, "providers", _Registry())
    client_module._runtime_configs.clear()
    client_module._runtime_configs.update(dict.fromkeys(CREDENTIAL_PROVIDERS))
    for builder in (_build_default_llm, _build_gemini_one_shot, _build_openai_wire_one_shot):
        builder.cache_clear()
    yield
    client_module._runtime_configs.clear()


def _configure(env: str, monkeypatch: pytest.MonkeyPatch, **configs: ProviderConfig) -> None:
    monkeypatch.setattr(client_module.settings, "ENV", env)
    client_module._runtime_configs.update(configs)


class TestProductionRoutingIsPinned:
    """The hosted routing, spelled as literals so a catalog edit cannot move it silently."""

    @pytest.fixture(autouse=True)
    def _hosted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Production reads keys from the environment only, never the snapshot.
        monkeypatch.setattr(client_module.settings, "ENV", "production")
        monkeypatch.setattr(client_module.settings, "AUTH_MODE", "workos")
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-or")
        monkeypatch.setattr(client_module.settings, "OPENROUTER_BASE_URL", None)
        monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", "g-key")
        monkeypatch.setattr(client_module.settings, "OPENAI_API_KEY", "sk-openai")

    async def test_comms_runs_openai_gpt_5_6_luna(self) -> None:
        lane, _ = await resolve_lane(None, AgentRole.COMMS)

        assert (lane.provider, lane.model, lane.reasoning) == ("openai", "gpt-5.6-luna", None)

    async def test_executor_runs_openrouter_deepseek_at_medium_reasoning(self) -> None:
        lane, _ = await resolve_lane(None, AgentRole.EXECUTOR)

        assert (lane.provider, lane.model, lane.reasoning) == (
            "openrouter",
            "deepseek/deepseek-v4-flash-0731",
            {"effort": "medium"},
        )

    async def test_executor_falls_back_to_gemini_flash_lite(self) -> None:
        lane, _ = await resolve_lane(None, AgentRole.EXECUTOR)
        fallback = lane.fallback()

        assert fallback is not None
        assert (fallback.provider, fallback.model) == ("gemini", "gemini-3.1-flash-lite")

    async def test_comms_falls_back_to_openrouter(self) -> None:
        lane, _ = await resolve_lane(None, AgentRole.COMMS)
        fallback = lane.fallback()

        assert fallback is not None
        assert (fallback.provider, fallback.model) == (
            "openrouter",
            "deepseek/deepseek-v4-flash-0731",
        )

    @pytest.mark.parametrize(
        ("use", "expected"),
        [
            (ModelUse.HELPER, ("openrouter", "deepseek/deepseek-v4-flash-0731")),
            (ModelUse.JUDGE, ("openrouter", "google/gemini-3.5-flash-lite")),
            (ModelUse.MEMORY, ("gemini", "gemini-3.1-flash-lite")),
            (ModelUse.VISION, ("gemini", "gemini-3.1-flash-lite")),
        ],
    )
    def test_one_shot_routes(self, use: ModelUse, expected: tuple[str, str]) -> None:
        assert one_shot_route(use) == expected

    def test_judge_keeps_its_openrouter_fallback_models(self) -> None:
        judge = resolve_model(ModelUse.JUDGE)

        assert isinstance(judge, ChatOpenRouter)
        assert (judge.model_kwargs or {})["models"] == [
            "google/gemini-3.5-flash-lite",
            "deepseek/deepseek-v4-flash-0731",
        ]

    async def test_without_gemini_openai_is_never_the_executors_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", None)
        lane, _ = await resolve_lane(None, AgentRole.EXECUTOR)

        assert lane.fallback() is None

    async def test_without_openrouter_or_gemini_the_default_lane_stays_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI is comms-only in production; a missing OpenRouter key fails loud at load time."""
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", None)
        monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", None)

        lane, _ = await resolve_lane(None, AgentRole.EXECUTOR)

        assert (lane.provider, lane.model) == ("openrouter", "deepseek/deepseek-v4-flash-0731")

    def test_openai_is_registered_last_as_a_by_name_alternative(self) -> None:
        available = {
            LLMProviderName(name): cast(ProviderLLM, object())
            for name in ("openai", "gemini", "openrouter")
        }

        ordered = _get_ordered_providers(available, None, True)

        assert [p.name for p in ordered] == ["openrouter", "gemini", "openai"]

    async def test_comms_ignores_a_stored_openai_model(self) -> None:
        client_module._runtime_configs["openai"] = _config(api_key="sk-openai", model="gpt-4o")

        lane, _ = await resolve_lane(None, AgentRole.COMMS)
        llm = client_module.init_openai_llm().loader_func()

        assert lane.model == "gpt-5.6-luna"
        assert llm.default.model_name == "gpt-5.6-luna"

    def test_a_missing_hosted_key_is_never_routed_around(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", None)

        assert one_shot_route(ModelUse.MEMORY) is None
        with pytest.raises(LLMNotConfiguredError, match="memory"):
            resolve_model(ModelUse.MEMORY)


class TestOpenAIOnly:
    @pytest.fixture(autouse=True)
    def _openai_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A credential-store key, not settings.OPENAI_API_KEY: the store must count.
        monkeypatch.setattr(client_module.settings, "OPENAI_API_KEY", None)
        _configure("selfhost", monkeypatch, openai=_OPENAI)

    @pytest.mark.parametrize("role", [AgentRole.COMMS, AgentRole.EXECUTOR, AgentRole.SUBAGENT])
    async def test_every_agent_tier_runs_on_openai(self, role: AgentRole) -> None:
        lane, _ = await resolve_lane(None, role)

        assert (lane.provider, lane.model) == ("openai", "gpt-5.6-luna")

    @pytest.mark.parametrize("use", list(ModelUse))
    def test_every_one_shot_role_runs_on_openai(self, use: ModelUse) -> None:
        model = resolve_model(use)

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "gpt-5.6-luna"
        assert model.openai_api_base is None

    async def test_a_configured_model_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client_module._runtime_configs["openai"] = _config(api_key="sk-openai", model="gpt-5.4")

        lane, _ = await resolve_lane(None, AgentRole.COMMS)

        assert lane.model == "gpt-5.4"
        assert one_shot_route(ModelUse.HELPER) == ("openai", "gpt-5.4")


class TestGeminiOnly:
    @pytest.fixture(autouse=True)
    def _gemini_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _configure("selfhost", monkeypatch, gemini=_GEMINI)

    @pytest.mark.parametrize("role", [AgentRole.COMMS, AgentRole.EXECUTOR])
    async def test_agent_tiers_run_on_gemini(self, role: AgentRole) -> None:
        lane, _ = await resolve_lane(None, role)

        assert (lane.provider, lane.model) == ("gemini", "gemini-3.1-flash-lite")

    @pytest.mark.parametrize("use", list(ModelUse))
    def test_every_one_shot_role_runs_on_gemini(self, use: ModelUse) -> None:
        assert isinstance(resolve_model(use), ChatGoogleGenerativeAI)


class TestOllamaOnly:
    @pytest.fixture(autouse=True)
    def _ollama_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _configure("selfhost", monkeypatch, ollama=_OLLAMA)

    async def test_executor_runs_the_configured_local_model(self) -> None:
        lane, _ = await resolve_lane(None, AgentRole.EXECUTOR)

        assert (lane.provider, lane.model) == ("ollama", "qwen3:8b")

    @pytest.mark.parametrize("use", [ModelUse.HELPER, ModelUse.JUDGE, ModelUse.MEMORY])
    def test_text_roles_run_on_the_configured_local_model(self, use: ModelUse) -> None:
        model = resolve_model(use)

        assert isinstance(model, ChatOpenAI)
        assert (model.model_name, model.openai_api_base) == (
            "qwen3:8b",
            "http://127.0.0.1:11434/v1",
        )

    def test_vision_fails_loud_naming_the_role(self) -> None:
        with pytest.raises(LLMNotConfiguredError, match="vision"):
            resolve_model(ModelUse.VISION)


class TestCustomOnly:
    @pytest.fixture(autouse=True)
    def _custom_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _configure("selfhost", monkeypatch, custom=_CUSTOM)

    async def test_executor_runs_the_endpoint_model(self) -> None:
        lane, _ = await resolve_lane(None, AgentRole.EXECUTOR)

        assert (lane.provider, lane.model) == ("custom", "my-model")

    @pytest.mark.parametrize("use", [ModelUse.HELPER, ModelUse.JUDGE, ModelUse.MEMORY])
    def test_text_roles_run_on_the_endpoint(self, use: ModelUse) -> None:
        model = resolve_model(use)

        assert isinstance(model, ChatOpenAI)
        assert (model.model_name, model.openai_api_base) == (
            "my-model",
            "https://llm.example.com/v1",
        )

    def test_an_endpoint_saved_without_a_model_serves_nothing(self) -> None:
        client_module._runtime_configs["custom"] = _config(
            api_key="sk-custom", base_url="https://llm.example.com/v1"
        )

        with pytest.raises(LLMNotConfiguredError, match="helper"):
            resolve_model(ModelUse.HELPER)


class TestNothingConfigured:
    def test_every_one_shot_role_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _configure("selfhost", monkeypatch)

        for use in ModelUse:
            with pytest.raises(LLMNotConfiguredError, match=use.value):
                resolve_model(use)
