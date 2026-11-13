"""Production-isolation regression suite for the self-host additions.

Proves two invariants. First, production behavior is unchanged by the
self-host profile: same dev-override hard blocks, the same warn-and-boot
on a missing key (WorkOS credentials included), same Infisical-mandatory boot. Second,
every self-host-only knob is gated out of production: AUTH_MODE local refuses
ENV production, self-host public surfaces stay out of other modes, and ENV
selfhost never contacts Infisical.
"""

from typing import Any

from pydantic import ValidationError
import pytest

from app.config.capability_requirements import required_keys
from app.config.deployment import BlobStoreKind, DeploymentKind, baseline_profile
from app.config.settings import Settings
from app.constants.files import BlobKind


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


def _required_dummies(kind: DeploymentKind) -> dict[str, Any]:
    """Stub every key the kind's baseline profile requires, plus ENV itself.

    Init kwargs win over ambient env, so the built object depends only on
    what this suite passes in.
    """
    dummies: dict[str, Any] = {"ENV": kind}
    for name in required_keys(baseline_profile(kind)):
        dummies[name] = 0 if Settings.model_fields[name].annotation == int | None else "x"
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


def test_a_local_blob_store_blocks_production_boot(monkeypatch):
    """Hosted files never land on a container disk, whatever BLOB_STORE says."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    monkeypatch.setenv("BLOB_STORE", "local")

    with pytest.raises(RuntimeError, match=r"BLOB_STORE=local.*ENV=production"):
        get_settings()


def test_selfhost_env_is_the_escaped_hatch(monkeypatch):
    """Boot the same configuration under its intended environment; the gate blocks the mode."""
    from app.config.settings import get_settings

    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    for name, value in _SELFHOST_INFRA_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)
    monkeypatch.setenv("ENV", "selfhost")
    monkeypatch.setenv("AUTH_MODE", "local")

    settings_obj = get_settings()

    assert settings_obj.ENV == DeploymentKind.SELFHOST
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
# Case 3 — production: workos defaults + credential requirements
# ---------------------------------------------------------------------------


def test_production_from_env_full_valid_env_defaults_to_workos(monkeypatch):
    """Construct a fully provisioned production env; AUTH_MODE defaults to workos."""

    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("AUTH_MODE", raising=False)

    kwargs = _required_dummies(DeploymentKind.PRODUCTION)
    kwargs.update(
        WORKOS_API_KEY="sk_test_fake",
        WORKOS_CLIENT_ID="client_fake",
        WORKOS_COOKIE_PASSWORD="a" * 32,
    )

    settings_obj = Settings(**kwargs)

    assert settings_obj.ENV == DeploymentKind.PRODUCTION
    assert settings_obj.AUTH_MODE == "workos"
    assert settings_obj.WORKOS_API_KEY == "sk_test_fake"


@pytest.mark.parametrize("field", ["WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"])
def test_empty_workos_credential_rejected_under_workos_mode(field):
    """Require WorkOS credentials in hosted mode; empty fails though the field is optional for local."""

    kwargs = _required_dummies(DeploymentKind.PRODUCTION)
    kwargs[field] = ""

    with pytest.raises(ValidationError, match=f"{field} is required when AUTH_MODE=workos"):
        Settings(_env_file=None, **kwargs)


def test_local_mode_releases_workos_credentials():
    """Release every WorkOS credential requirement under AUTH_MODE local."""

    kwargs = _required_dummies(DeploymentKind.SELFHOST)
    kwargs["AUTH_MODE"] = "local"

    settings_obj = Settings(_env_file=None, **kwargs)

    assert settings_obj.AUTH_MODE == "local"


def test_development_boots_with_local_auth(monkeypatch):
    """Let contributors run development without WorkOS: local auth is allowed there."""
    from app.config.settings import get_settings

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local")
    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)

    settings_obj = get_settings()

    assert settings_obj.ENV == DeploymentKind.DEVELOPMENT
    assert settings_obj.deployment.local_auth is True
    assert settings_obj.deployment.runtime_credentials is True
    assert settings_obj.deployment.bills is False


# ---------------------------------------------------------------------------
# Case 4 — development dummy-ok semantics are unchanged
# ---------------------------------------------------------------------------


def test_development_boots_without_workos_credentials(monkeypatch):
    """Keep development boots dummy-ok with no WorkOS config."""
    from app.config.settings import get_settings

    monkeypatch.setenv("ENV", "development")
    for var in ("WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)

    settings_obj = get_settings()

    assert settings_obj.ENV == DeploymentKind.DEVELOPMENT
    assert settings_obj.WORKOS_API_KEY is None
    assert settings_obj.AUTH_MODE == "workos"


# ---------------------------------------------------------------------------
# Case 5 — the self-host profile contract
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


def test_selfhost_minimal_infra_only_construct():
    """Construct from infra material alone; SaaS integrations stay optional and disable gracefully."""

    kwargs: dict[str, Any] = dict.fromkeys(_SELFHOST_INFRA_FIELDS, "x")
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"

    settings_obj = Settings(_env_file=None, **kwargs)

    assert settings_obj.ENV == "selfhost"
    assert settings_obj.MONGO_DB == "x"


def test_selfhost_minimal_construct_with_local_auth():
    """AUTH_MODE=local needs no WorkOS credentials on the self-host profile."""

    kwargs = dict.fromkeys(_SELFHOST_INFRA_FIELDS, "x")
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"
    kwargs["AUTH_MODE"] = "local"

    settings_obj = Settings(_env_file=None, **kwargs)

    # No WorkOS credential was passed in, yet construction succeeds — the
    # validator releases the requirement under AUTH_MODE=local.
    assert settings_obj.AUTH_MODE == "local"


def test_selfhost_missing_mongo_db_raises(monkeypatch):
    """Refuse to construct without MONGO_DB; it is the one infra value with no default."""

    monkeypatch.delenv("MONGO_DB", raising=False)
    kwargs = {name: "x" for name in _SELFHOST_INFRA_FIELDS if name != "MONGO_DB"}
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"

    with pytest.raises(ValidationError, match="MONGO_DB"):
        Settings(_env_file=None, **kwargs)


def test_selfhost_has_no_telegram_bot_until_one_is_added(monkeypatch):
    """GAIA Cloud's @heygaia_bot never answers a self-hosted instance's users."""
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    kwargs: dict[str, Any] = dict.fromkeys(_SELFHOST_INFRA_FIELDS, "x")
    kwargs["CHROMADB_PORT"] = 0
    kwargs["ENV"] = "selfhost"

    assert Settings(_env_file=None, **kwargs).telegram_bot_username is None
    kwargs["TELEGRAM_BOT_USERNAME"] = "my_gaia_bot"
    assert Settings(_env_file=None, **kwargs).telegram_bot_username == "my_gaia_bot"


def test_gaia_cloud_falls_back_to_its_own_telegram_bot(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    settings_obj = Settings(_env_file=None, **_required_dummies(DeploymentKind.PRODUCTION))

    assert settings_obj.telegram_bot_username == "heygaia_bot"


def test_ollama_has_no_endpoint_until_one_is_set():
    """No guessed Ollama endpoint: the setup preset suggests one, the admin saves it."""

    assert Settings.model_fields["OLLAMA_BASE_URL"].default is None


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
# Case 9 — hosted boot: production + workos warns about missing WorkOS credentials
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


def _production_boot_env(kind: DeploymentKind) -> dict[str, str]:
    """Render every required field of the settings class as an env value.

    A full get_settings boot then succeeds regardless of ambient dot-env
    contents.
    """
    return {name: str(value) for name, value in _required_dummies(kind).items()}


def _missing_groups_named(key: str) -> list[list[str]]:
    from app.config.settings_validator import settings_validator

    return [keys for _, keys in settings_validator.missing_groups if key in keys]


@pytest.mark.parametrize("missing_var", _WORKOS_CREDENTIAL_VARS)
def test_production_boot_without_a_workos_credential_boots_and_flags_it(monkeypatch, missing_var):
    """Boot hosted production with a WorkOS credential unset, as master did, and flag the gap."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    for name, value in _production_boot_env(DeploymentKind.PRODUCTION).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing_var)

    settings_obj = get_settings()

    assert getattr(settings_obj, missing_var) is None
    assert _missing_groups_named(missing_var)


def test_production_boot_with_all_workos_credentials_succeeds(monkeypatch):
    """Complete the hosted boot through get_settings with all three credentials present."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    for name, value in _production_boot_env(DeploymentKind.PRODUCTION).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client_fake")
    monkeypatch.setenv("WORKOS_COOKIE_PASSWORD", "a" * 32)

    settings_obj = get_settings()

    assert settings_obj.ENV == DeploymentKind.PRODUCTION
    assert settings_obj.AUTH_MODE == "workos"
    assert settings_obj.WORKOS_API_KEY == "sk_test_fake"


def test_production_boot_with_a_missing_capability_key_boots_and_flags_it(monkeypatch):
    """An unset integration key degrades that integration; it never takes GAIA Cloud down."""
    from app.config.settings import get_settings

    _isolate_boot_env(monkeypatch)
    for name, value in _production_boot_env(DeploymentKind.PRODUCTION).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LLAMA_INDEX_KEY")

    settings_obj = get_settings()

    assert settings_obj.LLAMA_INDEX_KEY is None
    assert _missing_groups_named("LLAMA_INDEX_KEY")


def test_selfhost_boot_with_a_missing_required_setting_refuses(monkeypatch):
    """A self-hosted instance without MONGO_DB fails at boot, not at its first query."""
    from pydantic import ValidationError

    from app.config.settings import get_settings

    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    for name, value in _SELFHOST_INFRA_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MONGO_DB")
    monkeypatch.setenv("ENV", "selfhost")

    with pytest.raises(ValidationError, match="MONGO_DB"):
        get_settings()


def test_development_boot_still_dummy_ok_with_workos_mode(monkeypatch):
    """Keep dev dummy-ok: the credential guard is production-only."""
    from app.config.settings import get_settings

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "workos")
    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    _unset_workos_credentials(monkeypatch)

    settings_obj = get_settings()

    assert settings_obj.ENV == DeploymentKind.DEVELOPMENT
    assert settings_obj.AUTH_MODE == "workos"
    assert settings_obj.WORKOS_API_KEY is None


def test_selfhost_unset_auth_mode_defaults_to_local(monkeypatch):
    """Boot local auth when ENV selfhost leaves AUTH_MODE unset; never the workos default."""
    from app.config.settings import get_settings

    for var in _DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    _unset_workos_credentials(monkeypatch)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    for name, value in _SELFHOST_INFRA_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ENV", "selfhost")

    settings_obj = get_settings()

    assert settings_obj.ENV == DeploymentKind.SELFHOST
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
    assert config.api_key == "env-resend-key"
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
    assert config.api_key == "env-composio-key"


async def test_production_refuses_to_store_a_credential(production_profile: None) -> None:
    """Production has no runtime credential store to write to."""
    from app.services.providers import provider_credentials_service as service

    with pytest.raises(RuntimeError, match="environment only"):
        await service.upsert(
            "resend",
            service.ProviderConfig(
                api_key="k",
                base_url=None,
                model=None,
                preset=None,
                account_id=None,
                api_secret=None,
            ),
        )


async def test_production_comms_uses_the_env_openai_key_over_a_stored_one(
    monkeypatch: pytest.MonkeyPatch, production_profile: None
) -> None:
    """Comms in production runs on env OPENAI_API_KEY; a stored OpenAI row is never seen."""
    from unittest.mock import AsyncMock

    from app.config.settings import settings
    from app.services.providers import provider_credentials_service as service

    store_read = AsyncMock(side_effect=AssertionError("production read the stored OpenAI key"))
    monkeypatch.setattr(service.provider_credentials_repository, "find_by_provider", store_read)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "env-openai-key")
    monkeypatch.setitem(
        service.resolved_configs,
        "openai",
        service.ProviderConfig(api_key="stored-openai-key", base_url=None, model=None, preset=None),
    )
    service._cache.clear()

    resolved = await service.resolve("openai")

    assert resolved is not None
    assert resolved.api_key == "env-openai-key"
    # The LLM client reads this same snapshot when it builds the comms client.
    snapshot = service.resolved_configs["openai"]
    assert snapshot is not None
    assert snapshot.api_key == "env-openai-key"
    store_read.assert_not_awaited()


async def test_production_stores_blobs_in_cloudinary_never_on_local_disk(
    monkeypatch: pytest.MonkeyPatch, production_profile: None, tmp_path
) -> None:
    """Hosted uploads keep their public Cloudinary URL; the self-host volume is never written."""
    from unittest.mock import patch

    from app.config.settings import settings
    from app.services.blob_store import CloudinaryBlobStore, blob_store

    monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))
    assert settings.deployment.blob_store is BlobStoreKind.CLOUDINARY
    store = blob_store()
    assert isinstance(store, CloudinaryBlobStore)

    with patch("app.services.blob_store.cloudinary.uploader.upload") as upload:
        upload.return_value = {"secure_url": "https://res.cloudinary.com/x/file.pdf"}
        url = await store.put(
            "u1", "file_1", b"b", resource_type="raw", kind=BlobKind.CHAT_UPLOAD, content_type="x/y"
        )

    assert url == "https://res.cloudinary.com/x/file.pdf"
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Case 11 — CORS origins and the session cookie's Secure flag per deployment
# ---------------------------------------------------------------------------

_DESKTOP_ORIGINS = [f"http://localhost:{port}" for port in range(5174, 5181)]


def _http_request(headers: dict[str, str] | None = None) -> Any:
    from starlette.requests import Request

    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {"type": "http", "scheme": "http", "path": "/", "headers": raw_headers, "server": ("h", 80)}
    )


def test_production_cors_trusts_exactly_gaias_origins(production_profile: None) -> None:
    from app.config.settings import settings
    from app.core.middleware import get_allowed_origin_regex, get_allowed_origins

    assert get_allowed_origins() == [
        settings.FRONTEND_URL,
        "https://heygaia.io",
        "https://www.heygaia.io",
        "https://heygaia.app",
        *_DESKTOP_ORIGINS,
    ]
    assert get_allowed_origin_regex() is None


def test_selfhost_cors_trusts_only_its_own_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    """A self-hosted instance never trusts *.localhost or GAIA's dev LAN addresses."""
    from app.config.settings import settings
    from app.core.middleware import get_allowed_origin_regex, get_allowed_origins

    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "AUTH_MODE", "local")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://gaia.example.com")

    assert get_allowed_origins() == ["https://gaia.example.com"]
    assert get_allowed_origin_regex() is None


def test_production_session_cookie_is_secure_even_on_a_plain_http_hop(
    production_profile: None,
) -> None:
    """TLS ends at the edge in production, so the cookie is Secure whatever the last hop says."""
    from app.utils.auth_utils import session_cookie_secure

    assert session_cookie_secure(_http_request()) is True


@pytest.mark.parametrize(
    ("headers", "secure"),
    [({}, False), ({"X-Forwarded-Proto": "https"}, True), ({"X-Forwarded-Proto": "http"}, False)],
)
def test_selfhost_session_cookie_follows_the_request_transport(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], secure: bool
) -> None:
    from app.config.settings import settings
    from app.utils.auth_utils import session_cookie_secure

    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "AUTH_MODE", "local")

    assert session_cookie_secure(_http_request(headers)) is secure


def test_production_exposes_no_developer_tooling(production_profile: None) -> None:
    from app.config.settings import settings

    profile = settings.deployment
    assert profile.dev_tools is False
    assert profile.private_network_endpoints is False
    assert profile.https_only is True
