"""Production-isolation regression suite for the self-host additions.

Proves two invariants. First, production behavior is unchanged by the
self-host profile: same dev-override hard blocks, same WorkOS credential
requirements under AUTH_MODE workos, same Infisical-mandatory boot. Second,
every self-host-only knob is gated out of production: AUTH_MODE local refuses
ENV production, self-host public surfaces stay out of other modes, and ENV
selfhost never contacts Infisical.
"""

from typing import Any

from pydantic import ValidationError
import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """get_settings() is lru_cached; every test must resolve fresh env."""
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Cleared in every boot test so only the override under test is present — a
# developer's ambient .env must not fire an earlier guard and fail the wrong
# assertion (see the matching list in test_settings_guards.py).
_DEV_OVERRIDE_VARS = (
    "DEV_AUTH_BYPASS_EMAIL",
    "DEV_UNLIMITED_RATE_LIMITS",
    "OPENROUTER_BASE_URL",
    "GAIA_SIM_MODE",
    "COMPOSIO_AUTH_CONFIG_OVERRIDES",
)


def _isolate_boot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENV=production with every guard variable unset except what the test sets."""
    monkeypatch.setenv("ENV", "production")
    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)


def _required_dummies(settings_cls: type) -> dict[str, Any]:
    """Stub every required field of the settings class with a dummy value.

    Init kwargs win over ambient env, so the built object depends only on
    what this suite passes in.
    """
    dummies: dict[str, Any] = {}
    for name, field_info in settings_cls.model_fields.items():
        if not field_info.is_required():
            continue
        if field_info.annotation is bool:
            dummies[name] = False
        elif field_info.annotation is int:
            dummies[name] = 0
        else:
            dummies[name] = "x"
    return dummies


# ---------------------------------------------------------------------------
# Case 1 — AUTH_MODE=local must refuse to boot in production
# ---------------------------------------------------------------------------


def test_local_auth_blocks_production_boot(monkeypatch):
    """Refuse to boot with AUTH_MODE local; open registration must never face the hosted base."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local")

    with pytest.raises(RuntimeError, match="self-host"):
        get_settings()


def test_local_auth_error_names_the_misconfiguration(monkeypatch):
    """The error must tell the operator both halves of the conflict."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local")

    with pytest.raises(RuntimeError, match=r"AUTH_MODE=local.*ENV=production"):
        get_settings()


def test_selfhost_env_is_the_escaped_hatch(monkeypatch):
    """Boot the same configuration under its intended environment; the gate blocks the mode."""
    from app.config.settings import SelfHostSettings, get_settings

    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    for name, value in _SELFHOST_INFRA_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)
    monkeypatch.setenv("ENV", "selfhost")
    monkeypatch.setenv("AUTH_MODE", "local")

    settings_obj = get_settings()

    assert isinstance(settings_obj, SelfHostSettings)
    assert settings_obj.AUTH_MODE == "local"


# ---------------------------------------------------------------------------
# Case 2 — pre-existing production guards are untouched
# ---------------------------------------------------------------------------


def test_dev_auth_bypass_still_blocks_production_boot(monkeypatch):
    """Behavior from before the self-host branch, preserved byte-for-byte."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    monkeypatch.setenv("DEV_AUTH_BYPASS_EMAIL", "dev@gaia.local")

    with pytest.raises(RuntimeError, match="DEV_AUTH_BYPASS_EMAIL"):
        get_settings()


# ---------------------------------------------------------------------------
# Case 3 — ProductionSettings: workos defaults + credential requirements
# ---------------------------------------------------------------------------


def test_production_from_env_full_valid_env_defaults_to_workos(monkeypatch):
    """Construct a fully provisioned production env via from_env; AUTH_MODE defaults to workos."""
    from app.config.settings import ProductionSettings

    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("AUTH_MODE", raising=False)

    kwargs = _required_dummies(ProductionSettings)
    kwargs.update(
        WORKOS_API_KEY="sk_test_fake",
        WORKOS_CLIENT_ID="client_fake",
        WORKOS_COOKIE_PASSWORD="a" * 32,
    )

    settings_obj = ProductionSettings.from_env(**kwargs)

    assert isinstance(settings_obj, ProductionSettings)
    assert settings_obj.AUTH_MODE == "workos"
    assert settings_obj.WORKOS_API_KEY == "sk_test_fake"


@pytest.mark.parametrize("field", ["WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"])
def test_empty_workos_credential_rejected_under_workos_mode(field):
    """Require WorkOS credentials in hosted mode; empty fails though the field is optional for local."""
    from app.config.settings import ProductionSettings

    kwargs = _required_dummies(ProductionSettings)
    kwargs[field] = ""

    with pytest.raises(ValidationError, match=f"{field} is required when AUTH_MODE=workos"):
        ProductionSettings(_env_file=None, **kwargs)


def test_local_mode_releases_workos_credentials():
    """Release every WorkOS credential requirement under AUTH_MODE local."""
    from app.config.settings import ProductionSettings

    kwargs = _required_dummies(ProductionSettings)
    kwargs["AUTH_MODE"] = "local"

    settings_obj = ProductionSettings(_env_file=None, **kwargs)

    assert settings_obj.AUTH_MODE == "local"


def test_development_boots_with_local_auth(monkeypatch):
    """Let contributors run development without WorkOS: local auth is allowed there."""
    from app.config.settings import DevelopmentSettings, get_settings

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local")
    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)

    settings_obj = get_settings()

    assert isinstance(settings_obj, DevelopmentSettings)
    assert settings_obj.deployment.local_auth is True
    assert settings_obj.deployment.runtime_credentials is True
    assert settings_obj.deployment.bills is False


# ---------------------------------------------------------------------------
# Case 4 — development dummy-ok semantics are unchanged
# ---------------------------------------------------------------------------


def test_development_boots_without_workos_credentials(monkeypatch):
    """Keep development boots dummy-ok with no WorkOS config."""
    from app.config.settings import DevelopmentSettings, get_settings

    monkeypatch.setenv("ENV", "development")
    for var in ("WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)

    settings_obj = get_settings()

    assert isinstance(settings_obj, DevelopmentSettings)
    assert settings_obj.WORKOS_API_KEY is None
    assert settings_obj.AUTH_MODE == "workos"


# ---------------------------------------------------------------------------
# Case 5 — SelfHostSettings profile contract
# ---------------------------------------------------------------------------


_SELFHOST_INFRA_FIELDS = {
    # The required set must stay infra connection material plus machine-local
    # secrets — anything else sneaking back into the required set breaks the
    # minimal `gaia up` boot.
    "MONGO_DB",
    "REDIS_URL",
    "CHROMADB_HOST",
    "CHROMADB_PORT",
    "POSTGRES_URL",
    "RABBITMQ_URL",
    "AGENT_SECRET",
    "BOT_SESSION_TOKEN_SECRET",
    "EMAIL_UNSUBSCRIBE_SECRET",
}

# String form for provisioning via monkeypatch.setenv (get_settings path).
_SELFHOST_INFRA_ENV: dict[str, str] = {
    name: "x" for name in _SELFHOST_INFRA_FIELDS if name != "CHROMADB_PORT"
} | {"CHROMADB_PORT": "0"}


def test_selfhost_required_set_is_infra_only():
    """Pin the exact required-field contract of the relaxed profile."""
    from app.config.settings import SelfHostSettings

    required = {name for name, f in SelfHostSettings.model_fields.items() if f.is_required()}

    assert required == _SELFHOST_INFRA_FIELDS


def test_selfhost_minimal_infra_only_construct():
    """Construct from infra material alone; SaaS integrations stay optional and disable gracefully."""
    from app.config.settings import SelfHostSettings

    kwargs: dict[str, Any] = dict.fromkeys(_SELFHOST_INFRA_FIELDS, "x")
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"

    settings_obj = SelfHostSettings(_env_file=None, **kwargs)

    assert settings_obj.ENV == "selfhost"
    assert settings_obj.MONGO_DB == "x"


def test_selfhost_minimal_construct_with_local_auth():
    """AUTH_MODE=local needs no WorkOS credentials on the self-host profile."""
    from app.config.settings import SelfHostSettings

    kwargs = dict.fromkeys(_SELFHOST_INFRA_FIELDS, "x")
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"
    kwargs["AUTH_MODE"] = "local"

    settings_obj = SelfHostSettings(_env_file=None, **kwargs)

    # No WorkOS credential was passed in, yet construction succeeds — the
    # validator releases the requirement under AUTH_MODE=local.
    assert settings_obj.AUTH_MODE == "local"


def test_selfhost_missing_mongo_db_raises(monkeypatch):
    """Refuse to construct without MONGO_DB; it is the one infra value with no default."""
    from app.config.settings import SelfHostSettings

    monkeypatch.delenv("MONGO_DB", raising=False)
    kwargs = {name: "x" for name in _SELFHOST_INFRA_FIELDS if name != "MONGO_DB"}
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"

    with pytest.raises(ValidationError, match="MONGO_DB"):
        SelfHostSettings(_env_file=None, **kwargs)


def test_selfhost_has_ollama_base_url_default():
    """Default the Ollama base URL so an unconfigured install still resolves one."""
    from app.config.settings import SelfHostSettings

    assert SelfHostSettings.model_fields["OLLAMA_BASE_URL"].default == (
        "http://host.docker.internal:11434"
    )


# ---------------------------------------------------------------------------
# Case 6 — middleware exclude gating follows AUTH_MODE
# ---------------------------------------------------------------------------


_LOCAL_ONLY_PUBLIC_PATHS = (
    "/api/v1/auth/signup",
    "/api/v1/auth/login",
    "/api/v1/setup/status",
)


def test_workos_mode_does_not_exclude_selfhost_public_surfaces(monkeypatch):
    """Exclude no local-mode path under AUTH_MODE workos; hosted exposes no password surface."""
    from unittest.mock import MagicMock

    from app.api.v1.middleware.auth import WorkOSAuthMiddleware
    from app.config.settings import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    middleware = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())

    for path in _LOCAL_ONLY_PUBLIC_PATHS:
        assert path not in middleware.exclude_paths


def test_local_mode_excludes_selfhost_public_surfaces(monkeypatch):
    """Add all three local-mode paths to the exclude list only in local mode."""
    from unittest.mock import MagicMock

    from app.api.v1.middleware.auth import WorkOSAuthMiddleware
    from app.config.settings import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "local")
    middleware = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())

    for path in _LOCAL_ONLY_PUBLIC_PATHS:
        assert path in middleware.exclude_paths
    # The standard public surface survives untouched in both modes.
    assert "/health" in middleware.exclude_paths


# ---------------------------------------------------------------------------
# Case 8 — Infisical fence: selfhost skips the vault, production needs identity
# ---------------------------------------------------------------------------


_INFISICAL_IDENTITY_VARS = (
    "INFISICAL_PROJECT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
)


def _real_infisical_inject() -> tuple[Any, Any]:
    """Recover the real Infisical pair beneath the suite-wide fence without mutating fenced modules."""
    import importlib
    import sys

    import shared.py.secrets as shared_secrets

    module_name = shared_secrets.__name__
    saved = sys.modules.pop(module_name)
    try:
        fresh = importlib.import_module(module_name)
        return fresh.inject_infisical_secrets, fresh.InfisicalConfigError
    finally:
        sys.modules[module_name] = saved


def test_selfhost_never_calls_infisical(monkeypatch):
    """Skip the vault entirely under ENV selfhost, even with identity vars present."""
    import sys
    from unittest.mock import MagicMock

    from app.config import settings as settings_module

    real_inject, _ = _real_infisical_inject()
    sdk_client = MagicMock()
    monkeypatch.setitem(sys.modules, "infisical_sdk", MagicMock(InfisicalSDKClient=sdk_client))
    monkeypatch.setattr(settings_module, "inject_infisical_secrets", real_inject)
    monkeypatch.setattr(settings_module, "_infisical_secrets_loaded", False)
    for var in _INFISICAL_IDENTITY_VARS:
        monkeypatch.setenv(var, "fake-identity-value")
    monkeypatch.setenv("ENV", "selfhost")

    settings_module._ensure_infisical_loaded()

    sdk_client.assert_not_called()
    assert settings_module._infisical_secrets_loaded is True


def test_production_without_identity_vars_still_raises(monkeypatch):
    """Propagate InfisicalConfigError when no identity is set; no swallow, no fallback."""
    from app.config import settings as settings_module

    real_inject, real_error = _real_infisical_inject()
    monkeypatch.setattr(settings_module, "inject_infisical_secrets", real_inject)
    monkeypatch.setattr(settings_module, "_infisical_secrets_loaded", False)
    for var in _INFISICAL_IDENTITY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ENV", "production")

    with pytest.raises(real_error):
        settings_module._ensure_infisical_loaded()


# ---------------------------------------------------------------------------
# Case 9 — hosted boot guard: production + workos requires WorkOS credentials
# ---------------------------------------------------------------------------


_WORKOS_CREDENTIAL_VARS = (
    "WORKOS_API_KEY",
    "WORKOS_CLIENT_ID",
    "WORKOS_COOKIE_PASSWORD",
)


def _unset_workos_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every WorkOS credential so only a test's explicit sets count."""
    for var in _WORKOS_CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)


def _production_boot_env(settings_cls: type) -> dict[str, str]:
    """Render every required field of the settings class as an env value.

    A full get_settings boot then succeeds regardless of ambient dot-env
    contents.
    """
    return {name: str(value) for name, value in _required_dummies(settings_cls).items()}


@pytest.mark.parametrize("missing_var", _WORKOS_CREDENTIAL_VARS)
def test_production_boot_without_workos_credential_refuses(monkeypatch, missing_var):
    """Refuse hosted boot when a WorkOS credential is missing; the error names every missing var."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    _unset_workos_credentials(monkeypatch)
    for var in _WORKOS_CREDENTIAL_VARS:
        if var != missing_var:
            monkeypatch.setenv(var, f"dummy-{var.lower()}")

    with pytest.raises(RuntimeError, match=missing_var) as exc_info:
        get_settings()

    message = str(exc_info.value)
    assert missing_var in message
    # Only the actually-missing variables are blamed — none of the others
    # (no name is a substring of another) appear in the error.
    for present_var in _WORKOS_CREDENTIAL_VARS:
        if present_var != missing_var:
            assert present_var not in message
    assert "hosted" in message


def test_production_boot_with_all_workos_credentials_succeeds(monkeypatch):
    """Complete the hosted boot through get_settings with all three credentials present."""
    from app.config.settings import ProductionSettings, get_settings

    _isolate_boot_env(monkeypatch)
    _unset_workos_credentials(monkeypatch)
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client_fake")
    monkeypatch.setenv("WORKOS_COOKIE_PASSWORD", "a" * 32)
    for name, value in _production_boot_env(ProductionSettings).items():
        monkeypatch.setenv(name, value)

    settings_obj = get_settings()

    assert isinstance(settings_obj, ProductionSettings)
    assert settings_obj.AUTH_MODE == "workos"
    assert settings_obj.WORKOS_API_KEY == "sk_test_fake"


def test_development_boot_still_dummy_ok_with_workos_mode(monkeypatch):
    """Keep dev dummy-ok: the credential guard is production-only."""
    from app.config.settings import DevelopmentSettings, get_settings

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "workos")
    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    _unset_workos_credentials(monkeypatch)

    settings_obj = get_settings()

    assert isinstance(settings_obj, DevelopmentSettings)
    assert settings_obj.AUTH_MODE == "workos"
    assert settings_obj.WORKOS_API_KEY is None


def test_selfhost_unset_auth_mode_defaults_to_local(monkeypatch):
    """Boot local auth when ENV selfhost leaves AUTH_MODE unset; never the workos default."""
    from app.config.settings import SelfHostSettings, get_settings

    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    _unset_workos_credentials(monkeypatch)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    for name, value in _SELFHOST_INFRA_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ENV", "selfhost")

    settings_obj = get_settings()

    assert isinstance(settings_obj, SelfHostSettings)
    assert settings_obj.AUTH_MODE == "local"
    assert settings_obj.WORKOS_API_KEY is None


def test_production_local_auth_still_blocked_before_workos_guard(monkeypatch):
    """Keep the local-auth hard block ahead of the WorkOS credential guard in production."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local")

    with pytest.raises(RuntimeError, match="self-host"):
        get_settings()


# ---------------------------------------------------------------------------
# Case 10 — production reads provider credentials from env only
# ---------------------------------------------------------------------------


@pytest.fixture
def production_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the shared settings object as hosted production with WorkOS auth."""
    from app.config.settings import settings

    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    monkeypatch.setattr(settings, "DEV_UNLIMITED_RATE_LIMITS", False)


async def test_production_resolve_never_reads_the_credential_store(
    monkeypatch: pytest.MonkeyPatch, production_profile: None
) -> None:
    """A stored row must never override env in production; the store is not even queried."""
    from unittest.mock import AsyncMock

    from app.config.settings import settings
    from app.services.providers import provider_credentials_service as service

    store_read = AsyncMock(side_effect=AssertionError("production read the credential store"))
    monkeypatch.setattr(service.provider_credentials_repository, "find_by_provider", store_read)
    monkeypatch.setattr(settings, "RESEND_API_KEY", "env-resend-key")
    service._cache.clear()

    config = await service.resolve("resend")

    assert config is not None
    assert config["api_key"] == "env-resend-key"
    store_read.assert_not_awaited()


def test_production_snapshot_ignores_a_stored_credential(
    monkeypatch: pytest.MonkeyPatch, production_profile: None
) -> None:
    """The sync read serves env even when a stored credential sits in the snapshot."""
    from app.config.settings import settings
    from app.services.providers import provider_credentials_service as service

    monkeypatch.setattr(settings, "COMPOSIO_KEY", "env-composio-key")
    monkeypatch.setitem(
        service.resolved_configs,
        "composio",
        service.ProviderConfig(api_key="stored-key", base_url=None, model=None, preset=None),
    )

    config = service.resolved_config("composio")

    assert config is not None
    assert config["api_key"] == "env-composio-key"


async def test_production_refuses_to_store_a_credential(production_profile: None) -> None:
    """Production has no runtime credential store to write to."""
    from app.services.providers import provider_credentials_service as service

    with pytest.raises(RuntimeError, match="environment only"):
        await service.upsert("resend", api_key="k")
