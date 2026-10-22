"""Production boot-guards and the OpenRouter base-URL passthrough.

Dev-only overrides (DEV_AUTH_BYPASS_EMAIL, OPENROUTER_BASE_URL) must make
get_settings refuse to start under ENV production, and an explicitly set base
URL flows through the resolved provider config into init_openrouter_llm;
production is protected by the boot guard, not by a silent client-side drop.
"""

from types import SimpleNamespace

from pydantic import SecretStr, ValidationError
import pytest

from app.agents.llm import client, dev_lane
from app.config.browser_host_settings import BrowserHostSettings
from app.config.capability_requirements import required_keys
from app.config.deployment import DeploymentKind, baseline_profile, deployment_profile
from app.config.settings import Settings, get_settings
from app.config.settings_validator import settings_validator
from app.constants.execute import SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS
from app.constants.llm import (
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEV_LLM_MAX_OUTPUT_TOKENS,
    OPENROUTER_APP_CATEGORIES,
    OPENROUTER_DEV_APP_TITLE,
    OPENROUTER_DEV_APP_URL,
    OPENROUTER_MAX_OUTPUT_TOKENS,
    OPENROUTER_REASONING,
    DevLLMApi,
    LLMProviderName,
)
from app.constants.providers import LLM_MODEL_PROFILES
from app.services.providers.provider_credentials_service import ProviderConfig, resolved_configs


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Every var the production guard rejects; the list must stay complete or a
# missing entry lets an ambient .env fire the wrong guard's assertion
# (DEV_UNLIMITED_RATE_LIMITS did exactly that).
DEV_OVERRIDE_VARS = (
    "DEV_AUTH_BYPASS_EMAIL",
    "DEV_UNLIMITED_RATE_LIMITS",
    "OPENROUTER_BASE_URL",
    "GAIA_SIM_MODE",
    "COMPOSIO_AUTH_CONFIG_OVERRIDES",
    "BROWSER_HOST_ALLOW_PRIVATE_ORIGINS",
    "OBSCURA_ALLOW_PRIVATE_NETWORK",
    "BROWSER_HOST_TEST_CA_FILE",
)


def _fake_chat_openrouter(captured: dict[str, object]) -> type:
    """Build a ChatOpenRouter double that records its construction kwargs.

    Carries a client.sdk_configuration because the real class does and
    without_sdk_retry writes the SDK's retry config there.
    """

    class _FakeChatOpenRouter:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.client = SimpleNamespace(sdk_configuration=SimpleNamespace(retry_config=None))

        def configurable_fields(self, **kwargs: object) -> "_FakeChatOpenRouter":
            captured.update({f"cf_{k}": v for k, v in kwargs.items()})
            return self

    return _FakeChatOpenRouter


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("DEV_AUTH_BYPASS_EMAIL", "dev@gaia.local"),
        ("DEV_UNLIMITED_RATE_LIMITS", "1"),
        ("OPENROUTER_BASE_URL", "http://localhost:9797"),
        ("GAIA_SIM_MODE", "1"),
    ],
)
def test_dev_overrides_block_production_boot(monkeypatch, env_var, value):
    monkeypatch.setenv("ENV", "production")
    # Isolate from the developer's ambient .env: only the override under test
    # may be present, or an earlier guard fires first and the match fails.
    for var in DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(env_var, value)

    with pytest.raises(RuntimeError) as refused:
        get_settings()

    assert str(refused.value) == (
        f"{env_var} is set but ENV is not 'development' — "
        "development overrides must never run in a real deployment."
    )


def test_composio_overrides_refuse_production_and_say_why(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    for var in DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COMPOSIO_AUTH_CONFIG_OVERRIDES", '{"gmail": "ac_dev"}')

    with pytest.raises(RuntimeError) as exc:
        get_settings()

    assert str(exc.value) == (
        "COMPOSIO_AUTH_CONFIG_OVERRIDES is set but ENV=production — "
        "it points integrations at a non-production Composio project."
    )


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("BROWSER_HOST_ALLOW_PRIVATE_ORIGINS", "http://localhost:8123"),
        ("OBSCURA_ALLOW_PRIVATE_NETWORK", "1"),
        ("BROWSER_HOST_TEST_CA_FILE", "/stack/ca.pem"),
    ],
)
def test_private_browsing_blocks_production_boot_of_the_host_and_the_api(
    monkeypatch, env_var, value
):
    """One validator on the host's settings, which the API's production settings inherit, refuses both."""
    monkeypatch.setenv("ENV", "production")
    for var in DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(env_var, value)
    refusal = f"Value error, {env_var} is set but ENV=production"

    with pytest.raises(ValidationError) as host_refused:
        BrowserHostSettings()
    with pytest.raises(ValidationError) as api_refused:
        _prod_settings()
    assert host_refused.value.errors()[0]["msg"] == refusal
    assert [e["msg"] for e in api_refused.value.errors()] == [refusal]


def test_a_host_with_no_private_reach_boots_in_production_and_one_with_it_in_development(
    monkeypatch,
):
    monkeypatch.setenv("ENV", "production")
    for var in DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    assert not BrowserHostSettings().BROWSER_HOST_ALLOW_PRIVATE_ORIGINS

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("OBSCURA_ALLOW_PRIVATE_NETWORK", "1")
    assert BrowserHostSettings().ENV == "development"


def test_private_origins_are_read_as_exact_origins_in_development(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv(
        "BROWSER_HOST_ALLOW_PRIVATE_ORIGINS", "http://localhost:8123, http://127.0.0.1:8124,"
    )

    assert {
        "http://localhost:8123",
        "http://127.0.0.1:8124",
    } == BrowserHostSettings().BROWSER_HOST_ALLOW_PRIVATE_ORIGINS


@pytest.mark.parametrize(
    "origin", ["http://localhost", "http://localhost:8123/form", "localhost:8123"]
)
def test_a_private_origin_that_is_not_exact_refuses_to_load(monkeypatch, origin):
    """A path or a missing port would widen or miss the origin the list means."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("BROWSER_HOST_ALLOW_PRIVATE_ORIGINS", origin)

    with pytest.raises(ValidationError, match="is not an exact origin|unsupported URL scheme"):
        BrowserHostSettings()


def test_openrouter_base_url_allowed_in_development(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://localhost:9797")

    settings_obj = get_settings()

    assert settings_obj.ENV == "development"
    assert settings_obj.OPENROUTER_BASE_URL == "http://localhost:9797"


def test_init_openrouter_forwards_explicit_base_url(monkeypatch):
    from app.agents.llm import client

    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "ChatOpenRouter", _fake_chat_openrouter(captured))
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client.settings, "OPENROUTER_API_KEY", "sk-stub-not-used")
    # The shared settings object feeds the credential service's env fallback,
    # which is where the base-URL policy lives since the F5 convergence.
    monkeypatch.setattr(client.settings, "OPENROUTER_BASE_URL", "http://localhost:9797")

    client.init_openrouter_llm().loader_func()

    # An explicitly-set base URL rides the resolved config into construction —
    # the unset case still forwards NO kwarg (see test_llm_runtime_config), so
    # ChatOpenRouter's OPENROUTER_API_BASE default keeps applying there.
    assert captured["base_url"] == "http://localhost:9797"


def test_init_openrouter_base_url_enforcement_is_the_boot_guard(monkeypatch):
    """Pin the layering: no silent base-URL drop; protection is the loud boot guard."""
    from app.agents.llm import client

    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "ChatOpenRouter", _fake_chat_openrouter(captured))
    monkeypatch.setattr(client.settings, "ENV", "production")
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    # A leaked-in override (unreachable via get_settings in real production).
    monkeypatch.setattr(
        client.settings, "OPENROUTER_BASE_URL", "http://localhost:9797", raising=False
    )
    monkeypatch.setattr(client.settings, "OPENROUTER_API_KEY", "sk-real")

    client.init_openrouter_llm().loader_func()

    assert captured["base_url"] == "http://localhost:9797"


def _prod_settings(**overrides):
    """Build production settings with every required key stubbed.

    Direct construction (not get_settings()) so the test exercises only the
    validators — no ambient .env, no missing-key noise.
    """
    dummies: dict[str, object] = {"ENV": DeploymentKind.PRODUCTION}
    for name in required_keys(baseline_profile(DeploymentKind.PRODUCTION)):
        dummies[name] = 0 if Settings.model_fields[name].annotation == int | None else "x"
    dummies.update(overrides)
    return Settings(_env_file=None, **dummies)


def test_production_rejects_http_dodo_base_url():
    """A plain-http DODO_PAYMENTS_BASE_URL would send the API key in cleartext; production must reject it."""
    with pytest.raises(ValidationError) as refused:
        _prod_settings(DODO_PAYMENTS_BASE_URL="http://localhost:8899")

    assert [e["msg"] for e in refused.value.errors()] == [
        "Value error, DODO_PAYMENTS_BASE_URL must use https:// in production"
    ]


def test_production_allows_https_dodo_base_url():
    settings_obj = _prod_settings(DODO_PAYMENTS_BASE_URL="https://dodo.example.com")

    assert settings_obj.DODO_PAYMENTS_BASE_URL == "https://dodo.example.com"


def test_production_allows_unset_dodo_base_url():
    """Leaving DODO_PAYMENTS_BASE_URL unset stays valid — production uses the real Dodo endpoint by default."""
    settings_obj = _prod_settings(DODO_PAYMENTS_BASE_URL=None)

    assert settings_obj.DODO_PAYMENTS_BASE_URL is None


def test_development_allows_http_dodo_base_url(monkeypatch):
    """The stub/sandbox override is a dev concern — local mirrors are http."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DODO_PAYMENTS_BASE_URL", "http://localhost:8899")

    settings_obj = get_settings()

    assert settings_obj.DODO_PAYMENTS_BASE_URL == "http://localhost:8899"


def test_short_sandbox_execute_secret_refuses_to_boot():
    """A sandbox execute token names whose tools the host runs, and nothing else binds that claim — a guessable signing secret means running any user's tools."""
    with pytest.raises(
        ValidationError, match="SANDBOX_EXECUTE_TOKEN_SECRET must be at least 32 characters"
    ):
        _prod_settings(SANDBOX_EXECUTE_TOKEN_SECRET="dev")


def test_a_long_enough_sandbox_execute_secret_is_accepted():
    secret = "x" * SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS
    assert (
        secret == _prod_settings(SANDBOX_EXECUTE_TOKEN_SECRET=secret).SANDBOX_EXECUTE_TOKEN_SECRET
    )


def test_unset_sandbox_execute_secret_stays_valid():
    """Both code-mode vars unset means code mode ships dark — not a misconfig."""
    assert _prod_settings(SANDBOX_EXECUTE_TOKEN_SECRET=None).SANDBOX_EXECUTE_TOKEN_SECRET is None


def test_a_blank_sandbox_execute_secret_reads_as_unset():
    """KEY= with nothing after it is how a templated compose/Infisical/k8s env renders an unfilled optional secret — the same shape .env.example uses for every other one."""
    assert _prod_settings(SANDBOX_EXECUTE_TOKEN_SECRET="").SANDBOX_EXECUTE_TOKEN_SECRET is None


def test_init_openrouter_llm_pins_context_window_profile(monkeypatch):
    """Every chat LLM must carry its context-window profile: fractional-token middleware reads it at graph build and raises otherwise."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(client, "ChatOpenRouter", _fake_chat_openrouter(captured))
    monkeypatch.setattr(client.settings, "ENV", "development")
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client.settings, "OPENROUTER_API_KEY", "sk-test")

    llm = client.init_openrouter_llm().loader_func()

    assert captured["model"] == LLM_MODEL_PROFILES[LLMProviderName.OPENROUTER].chat
    assert captured["temperature"] == DEFAULT_LLM_TEMPERATURE
    assert captured["max_tokens"] == OPENROUTER_MAX_OUTPUT_TOKENS
    # ENV is development here, so attribution must be the fixed dev identity —
    # a localhost FRONTEND_URL referer lands in OpenRouter's "unknown app" bucket.
    assert captured["app_url"] == OPENROUTER_DEV_APP_URL
    assert captured["app_title"] == OPENROUTER_DEV_APP_TITLE
    assert captured["app_categories"] == OPENROUTER_APP_CATEGORIES
    assert captured["reasoning"] == OPENROUTER_REASONING
    assert captured["streaming"] is True
    assert captured["stream_usage"] is True
    assert llm.profile == {"max_input_tokens": DEFAULT_MAX_TOKENS}


def test_init_gemini_llm_pins_context_window_profile(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeChatGoogle:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def configurable_fields(self, **kwargs: object) -> "_FakeChatGoogle":
            captured.update({f"cf_{k}": v for k, v in kwargs.items()})
            return self

    monkeypatch.setattr(client, "ChatGoogleGenerativeAI", _FakeChatGoogle)
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client.settings, "GOOGLE_API_KEY", "g-test", raising=False)

    llm = client.init_gemini_llm().loader_func()

    assert captured["model"] == LLM_MODEL_PROFILES[LLMProviderName.GEMINI].chat
    # the model field must stay wired through configurable_fields — dropping
    # it silently breaks per-request model selection
    assert captured["cf_model"] is client._MODEL_FIELD
    assert llm.profile == {"max_input_tokens": DEFAULT_MAX_TOKENS}


def test_init_custom_llm_wires_every_kwarg_and_profile(monkeypatch):
    """Wire every construction kwarg of a stored custom endpoint via the shared dev-lane build site."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(dev_lane, "ChatOpenAI", _fake_chat_openrouter(captured))
    dev_lane.build_custom_chat_model.cache_clear()
    # Runtime-stored credentials only exist on a self-hosted instance.
    monkeypatch.setattr(client.settings, "ENV", "selfhost")
    monkeypatch.setattr(client.settings, "AUTH_MODE", "local")
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client.settings, "DEV_LLM_API", DevLLMApi.CHAT_COMPLETIONS)
    monkeypatch.setitem(
        resolved_configs,
        "custom",
        ProviderConfig(
            api_key="sk-dev",
            base_url="http://localhost:9999/v1",
            model="deepseek-v4-flash",
        ),
    )

    llm = client.init_custom_llm().loader_func()

    assert captured["model"] == "deepseek-v4-flash"
    assert captured["temperature"] == DEFAULT_LLM_TEMPERATURE
    assert str(captured["base_url"]) == "http://localhost:9999/v1"
    api_key = captured["api_key"]
    assert isinstance(api_key, SecretStr) and api_key.get_secret_value() == "sk-dev"
    # ChatOpenAI aliases max_tokens to max_completion_tokens at construction
    # (still sent as max_tokens on the wire) — assert what is passed.
    assert captured["max_completion_tokens"] == DEV_LLM_MAX_OUTPUT_TOKENS
    assert captured["streaming"] is True
    assert captured["stream_usage"] is True
    # The OpenAI SDK's own retry loop would nest under with_llm_retry's.
    assert captured["max_retries"] == 0
    assert captured["use_responses_api"] is False
    assert captured["reasoning"] is None
    assert llm.profile == {"max_input_tokens": DEFAULT_MAX_TOKENS}
    assert captured["cf_model_name"] is client._MODEL_FIELD


def test_the_custom_endpoint_reads_the_dev_settings_when_nothing_is_stored(monkeypatch):
    """With no store entry the env fallback yields the DEV_LLM endpoint at the same build site."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(dev_lane, "ChatOpenAI", _fake_chat_openrouter(captured))
    dev_lane.build_custom_chat_model.cache_clear()
    monkeypatch.setattr(client.settings, "ENV", "development")
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client.settings, "DEV_LLM_API", DevLLMApi.CHAT_COMPLETIONS)
    monkeypatch.setattr(client.settings, "DEV_LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setattr(client.settings, "DEV_LLM_API_KEY", "sk-dev")
    monkeypatch.setattr(client.settings, "DEV_LLM_MODEL", "gpt-6-luna")

    llm = client.init_custom_llm().loader_func()

    assert captured["model"] == "gpt-6-luna"
    assert captured["max_completion_tokens"] == DEV_LLM_MAX_OUTPUT_TOKENS
    assert llm.profile == {"max_input_tokens": DEFAULT_MAX_TOKENS}


def test_the_custom_endpoint_defaults_to_chat_completions(monkeypatch):
    """Nous-style endpoints predate the setting and speak chat completions only."""
    monkeypatch.delenv("DEV_LLM_API", raising=False)

    assert (
        Settings(_env_file=None, ENV=DeploymentKind.DEVELOPMENT).DEV_LLM_API
        is DevLLMApi.CHAT_COMPLETIONS
    )


def test_the_custom_endpoint_can_be_switched_to_the_responses_api(monkeypatch):
    monkeypatch.setenv("DEV_LLM_API", "responses")

    assert (
        Settings(_env_file=None, ENV=DeploymentKind.DEVELOPMENT).DEV_LLM_API is DevLLMApi.RESPONSES
    )


def test_an_unknown_custom_endpoint_api_refuses_to_load(monkeypatch):
    """A typo must not quietly fall back to chat completions, where gpt-6-luna rejects tools."""
    monkeypatch.setenv("DEV_LLM_API", "response")

    with pytest.raises(ValidationError, match="DEV_LLM_API"):
        Settings(_env_file=None, ENV=DeploymentKind.DEVELOPMENT)


def _clear_required_env(monkeypatch: pytest.MonkeyPatch, kind: DeploymentKind) -> None:
    for name in required_keys(baseline_profile(kind)):
        monkeypatch.delenv(name, raising=False)


def test_production_boots_with_only_the_datastores_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Master warned and booted on a missing production key; refusing would take
    # GAIA Cloud down on deploy for one unset integration id.
    _clear_required_env(monkeypatch, DeploymentKind.PRODUCTION)

    settings_obj = Settings(
        _env_file=None,
        ENV="production",
        AUTH_MODE="workos",
        MONGO_DB="mongodb://mongo:27017",
        REDIS_URL="redis://redis:6379",
    )

    assert settings_obj.deployment.kind is DeploymentKind.PRODUCTION
    assert settings_obj.FIGMA_MCP_CLIENT_ID is None


def test_selfhost_refuses_to_boot_without_its_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_required_env(monkeypatch, DeploymentKind.SELFHOST)

    with pytest.raises(RuntimeError, match="POSTGRES_URL"):
        Settings(
            _env_file=None,
            ENV="selfhost",
            MONGO_DB="mongodb://mongo:27017",
            REDIS_URL="redis://redis:6379",
        )


def test_an_env_with_no_deployment_kind_is_refused_by_name_at_boot() -> None:
    # The shared settings base admits ENV=staging; the API's ENV field is the
    # DeploymentKind enum, so it fails as a field error, never inside the profile.
    with pytest.raises(ValidationError) as refused:
        _prod_settings(ENV="staging")

    [error] = refused.value.errors()
    assert error["loc"] == ("ENV",)
    assert "'production', 'development' or 'selfhost'" in error["msg"]


def _selfhost_settings(auth_mode: str, **overrides: object) -> Settings:
    """Build self-host settings with every key the profile requires stubbed."""
    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "workos" if auth_mode == "workos" else "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )
    dummies: dict[str, object] = {
        name: 0 if Settings.model_fields[name].annotation == int | None else "x"
        for name in required_keys(profile)
    }
    return Settings(
        _env_file=None, ENV=DeploymentKind.SELFHOST, AUTH_MODE=auth_mode, **{**dummies, **overrides}
    )


def test_selfhost_keeps_an_explicit_workos_sign_in() -> None:
    assert _selfhost_settings("workos").AUTH_MODE == "workos"


def test_selfhost_names_every_missing_key_in_one_refusal() -> None:
    # The keys that may be left unset; MONGO_DB and REDIS_URL fail type validation first.
    unsettable = sorted(
        name
        for name in required_keys(baseline_profile(DeploymentKind.SELFHOST))
        if Settings.model_fields[name].default is None
    )
    assert len(unsettable) > 1

    with pytest.raises(RuntimeError) as refused:
        _selfhost_settings("local", **dict.fromkeys(unsettable))

    assert str(refused.value) == (
        f"{', '.join(unsettable)} must be set for ENV=selfhost with AUTH_MODE=local "
        "— see app/config/capability_requirements.py."
    )


@pytest.mark.parametrize(
    ("env", "redirect"),
    [
        (
            DeploymentKind.DEVELOPMENT,
            "https://redirectmeto.com/http://localhost:8000/api/v1/platform-auth/slack/callback",
        ),
        (DeploymentKind.SELFHOST, "https://gaia.example.com/api/v1/platform-auth/slack/callback"),
    ],
)
def test_only_development_routes_slack_through_the_localhost_proxy(
    env: DeploymentKind, redirect: str
) -> None:
    if env is DeploymentKind.SELFHOST:
        settings_obj = _selfhost_settings("local", HOST="https://gaia.example.com")
    else:
        settings_obj = Settings(_env_file=None, ENV=env, HOST="https://gaia.example.com")

    assert redirect == settings_obj.SLACK_OAUTH_REDIRECT_URI


def test_boot_judges_the_configuration_against_its_own_deployment(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("SHOW_MISSING_KEY_WARNINGS", "true")
    monkeypatch.setenv("MONGO_DB", "mongodb://localhost:27017/gaia")

    settings_obj = get_settings()

    assert settings_validator.show_warnings is True
    assert settings_validator.profile == settings_obj.deployment
    assert "MongoDB Connection" not in {
        group.name for group, _ in settings_validator.missing_groups
    }
