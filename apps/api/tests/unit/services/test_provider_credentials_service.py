"""Unit tests for the provider credentials service (app.services.providers).

Covers the contract: Fernet-encrypted JSON payloads in Mongo, DB credential →
env fallback → None resolution with a 60s TTL cache, and invalidate() clearing
the cache + resetting the LLM registry + aux LLM caches + Redis publish.
invalidate_locally is the shared pod-local half of that fan-out — it is what
the runtime-config subscriber runs when another pod's update arrives.
"""

import json
import time
from typing import Any

from cryptography.fernet import Fernet
import pytest

from app.agents.llm.client import reset_aux_llm_caches
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.providers import CREDENTIAL_PROVIDERS, CredentialSource
from app.core.lazy_loader import providers as provider_registry
from app.db.redis import redis_cache
import app.services.providers.provider_credentials_service as service_module
from app.services.providers.provider_credentials_service import (
    CloudinaryAccount,
    CredentialResolution,
    GoogleOAuthClient,
    cloudinary_account,
    delete,
    env_config,
    google_oauth_client,
    inspect_credential,
    invalidate,
    is_usable,
    resolve,
    upsert,
)
from app.services.runtime.config_updates import RUNTIME_CONFIG_CHANNEL
from app.services.runtime.secrets_store import fernet_key_from
from tests.helpers import captured_wide_event

INSTANCE_SECRET = "test-instance-secret"


class _FakeDoc:
    """Minimal stand-in for ProviderCredentialDocument."""

    def __init__(self, provider: str, data_encrypted: str) -> None:
        self.provider = provider
        self.data_encrypted = data_encrypted


class FakeCredentialsRepo:
    """In-memory fake of the three repository methods the service uses."""

    def __init__(self) -> None:
        self.ciphertexts: dict[str, str] = {}
        self.find_calls = 0
        self.upsert_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    async def find_by_provider(self, provider: str) -> _FakeDoc | None:
        self.find_calls += 1
        if provider in self.ciphertexts:
            return _FakeDoc(provider, self.ciphertexts[provider])
        return None

    async def upsert_encrypted(self, provider: str, data_encrypted: str) -> None:
        self.upsert_calls.append((provider, data_encrypted))
        self.ciphertexts[provider] = data_encrypted

    async def delete(self, provider: str) -> bool:
        self.delete_calls.append(provider)
        return self.ciphertexts.pop(provider, None) is not None


class FakeRedis:
    """Records publishes; can be told to fail them (Redis outage mid-call)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail_publish = False

    async def publish(self, channel: str, message: str) -> int:
        if self.fail_publish:
            raise ConnectionError("redis down")
        self.published.append((channel, message))
        return 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Isolate every test: empty cache, neutral env fields, fixed instance secret."""
    service_module._cache.clear()
    for field in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "GOOGLE_API_KEY",
        "TAVILY_API_KEY",
        "DEV_LLM_BASE_URL",
        "DEV_LLM_API_KEY",
        "DEV_LLM_MODEL",
        "COMPOSIO_KEY",
        "E2B_API_KEY",
        "OPENAI_API_KEY",
        "RESEND_API_KEY",
        "CLOUDINARY_CLOUD_NAME",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "FIRECRAWL_API_KEY",
        "INSTANCE_SECRET",
    ):
        monkeypatch.setattr(settings, field, None)
    # The store is live only where runtime credentials are; production is
    # pinned env-only in test_prod_isolation.
    monkeypatch.setattr(settings, "ENV", "selfhost")
    # The snapshot is one dict shared with the LLM client; restore it in place
    # so resolves here never leak stored configs into later test modules.
    saved_snapshot = dict(service_module.resolved_configs)
    yield
    service_module._cache.clear()
    service_module.resolved_configs.clear()
    service_module.resolved_configs.update(saved_snapshot)


@pytest.fixture(autouse=True)
def _stub_aux_llm_reset(monkeypatch):
    """Drop the registered invalidation hooks so no test rebuilds real LLM clients.

    Tests asserting on the hook run override this with their own recorder (aux_cache_calls).
    """
    monkeypatch.setattr(service_module, "_local_invalidation_hooks", [])


@pytest.fixture
def repo(monkeypatch) -> FakeCredentialsRepo:
    fake = FakeCredentialsRepo()
    monkeypatch.setattr(service_module, "provider_credentials_repository", fake)
    return fake


@pytest.fixture
def fixed_secret(monkeypatch):
    """Stub get_instance_secret so no Mongo is touched by these tests."""

    async def _fake_get_instance_secret() -> str:
        return INSTANCE_SECRET

    monkeypatch.setattr(service_module, "get_instance_secret", _fake_get_instance_secret)


@pytest.fixture
def redis_fake(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "redis", fake)
    return fake


@pytest.fixture
def registry_reset_calls(monkeypatch) -> list[str]:
    """Replace ProviderRegistry.reset with a recorder (same singleton the service uses)."""
    calls: list[str] = []

    def _record(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(provider_registry, "reset", _record)
    return calls


@pytest.fixture
def aux_cache_calls(monkeypatch) -> list[int]:
    """Record every pod-local invalidation hook run."""
    calls: list[int] = []
    monkeypatch.setattr(service_module, "_local_invalidation_hooks", [lambda: calls.append(1)])
    return calls


def test_the_llm_client_rebuilds_its_caches_on_every_invalidation(monkeypatch) -> None:
    monkeypatch.undo()  # see the real hook list, not the autouse stub
    assert reset_aux_llm_caches in service_module._local_invalidation_hooks


@pytest.fixture
def clock(monkeypatch):
    """Provide a controllable monotonic clock for TTL-cache assertions."""

    class FakeClock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

        def advance(self, seconds: float) -> None:
            self.now += seconds

    fake_clock = FakeClock()
    monkeypatch.setattr(service_module, "monotonic", fake_clock)
    return fake_clock


def decrypt_payload(ciphertext: str) -> dict[str, Any]:
    plaintext = Fernet(fernet_key_from(INSTANCE_SECRET)).decrypt(ciphertext.encode())
    result: dict[str, Any] = json.loads(plaintext)
    return result


# ---------------------------------------------------------------------------
# upsert / resolve — roundtrip + secrecy
# ---------------------------------------------------------------------------


class TestUpsertResolveRoundtrip:
    async def test_stored_config_resolves_back(self, repo, fixed_secret) -> None:
        await upsert(
            "openrouter",
            api_key="sk-or-live-1",
            base_url="https://or.example/v1",
            model="m1",
            preset=None,
            account_id=None,
            api_secret=None,
        )

        config = await resolve("openrouter")

        assert config == {
            "api_key": "sk-or-live-1",
            "base_url": "https://or.example/v1",
            "model": "m1",
            "preset": None,
            "account_id": None,
            "api_secret": None,
        }

    async def test_preset_only_config_roundtrips(self, repo, fixed_secret) -> None:
        await upsert("custom", preset="opencode")

        config = await resolve("custom")

        assert config == {
            "api_key": None,
            "base_url": None,
            "model": None,
            "preset": "opencode",
            "account_id": None,
            "api_secret": None,
        }

    async def test_ciphertext_never_contains_raw_api_key(self, repo, fixed_secret) -> None:
        await upsert("gemini", api_key="AIzaSUPERSECRET-VALUE")

        ciphertext = repo.ciphertexts["gemini"]
        assert "AIzaSUPERSECRET-VALUE" not in ciphertext
        # And what is stored decrypts back to exactly the configured payload.
        assert decrypt_payload(ciphertext)["api_key"] == "AIzaSUPERSECRET-VALUE"

    async def test_upsert_overwrites_previous_value(self, repo, fixed_secret) -> None:
        await upsert("tavily", api_key="tvly-old")
        await upsert("tavily", api_key="tvly-new")

        assert len(repo.upsert_calls) == 2
        assert decrypt_payload(repo.ciphertexts["tavily"])["api_key"] == "tvly-new"


# ---------------------------------------------------------------------------
# resolve — DB vs env precedence and per-provider fallbacks
# ---------------------------------------------------------------------------


class TestResolvePrecedenceAndFallbacks:
    async def test_db_credential_beats_env(self, repo, fixed_secret) -> None:
        settings.OPENROUTER_API_KEY = "sk-env-key"
        await upsert("openrouter", api_key="sk-db-key")

        config = await resolve("openrouter")

        assert config is not None and config["api_key"] == "sk-db-key"

    async def test_openrouter_env_fallback_includes_base_url(self, repo) -> None:
        settings.OPENROUTER_API_KEY = "sk-env-key"
        settings.OPENROUTER_BASE_URL = "http://localhost:9999/v1"

        config = await resolve("openrouter")

        assert config == {
            "api_key": "sk-env-key",
            "base_url": "http://localhost:9999/v1",
            "model": None,
            "preset": None,
            "account_id": None,
            "api_secret": None,
        }

    async def test_gemini_env_fallback(self, repo) -> None:
        settings.GOOGLE_API_KEY = "g-emini-key"

        config = await resolve("gemini")

        assert config is not None and config["api_key"] == "g-emini-key"

    async def test_ollama_env_fallback_returns_base_url(self, repo, monkeypatch) -> None:
        monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        config = await resolve("ollama")

        assert config == {
            "api_key": None,
            "base_url": "http://localhost:11434",
            "model": None,
            "preset": None,
            "account_id": None,
            "api_secret": None,
        }

    async def test_ollama_without_an_endpoint_is_not_configured(self, repo, monkeypatch) -> None:
        """A guessed default endpoint would die on connect from a bare instance."""
        monkeypatch.setattr(settings, "OLLAMA_BASE_URL", None)
        assert await resolve("ollama") is None

    async def test_tavily_env_fallback(self, repo) -> None:
        settings.TAVILY_API_KEY = "tvly-env-key"

        config = await resolve("tavily")

        assert config is not None and config["api_key"] == "tvly-env-key"

    async def test_custom_dev_env_fallback(self, repo) -> None:
        settings.ENV = "development"
        settings.DEV_LLM_BASE_URL = "http://llm.example/v1"
        settings.DEV_LLM_API_KEY = "sk-dev"
        settings.DEV_LLM_MODEL = "deepseek-x"

        config = await resolve("custom")

        assert config == {
            "api_key": "sk-dev",
            "base_url": "http://llm.example/v1",
            "model": "deepseek-x",
            "preset": None,
            "account_id": None,
            "api_secret": None,
        }

    async def test_custom_outside_development_is_none(self, repo) -> None:
        assert await resolve("custom") is None

    async def test_unconfigured_provider_is_none(self, repo) -> None:
        assert await resolve("openrouter") is None

    async def test_unknown_provider_is_none(self, repo) -> None:
        assert await resolve("not-a-provider") is None


class TestToolProviderEnvFallbacks:
    """Resolve tool/integration lanes all-or-nothing.

    Single-key providers resolve from their one env var; the multi-variable pairs
    (cloudinary, google_oauth) resolve ONLY when every variable is present, so a
    half-set env must never report the provider as configured.
    """

    @pytest.mark.parametrize(
        ("provider", "field", "value"),
        [
            ("composio", "COMPOSIO_KEY", "ck-test"),
            ("e2b", "E2B_API_KEY", "e2b-test"),
            ("openai", "OPENAI_API_KEY", "sk-oai-test"),
            ("resend", "RESEND_API_KEY", "re-test"),
            ("firecrawl", "FIRECRAWL_API_KEY", "fc-test"),
        ],
    )
    async def test_single_key_env_fallback(self, repo, provider, field, value) -> None:
        setattr(settings, field, value)

        config = await resolve(provider)

        assert config is not None and config["api_key"] == value

    async def test_cloudinary_resolves_with_all_three_fields(self, repo) -> None:
        settings.CLOUDINARY_CLOUD_NAME = "my-cloud"
        settings.CLOUDINARY_API_KEY = "cl-key"
        settings.CLOUDINARY_API_SECRET = "cl-secret"

        config = await resolve("cloudinary")

        assert config is not None and config["api_key"] == "cl-key"

    @pytest.mark.parametrize(
        ("cloud_name", "key", "secret"),
        [
            (None, "cl-key", "cl-secret"),
            ("my-cloud", None, "cl-secret"),
            ("my-cloud", "cl-key", None),
        ],
    )
    async def test_cloudinary_partial_env_is_not_configured(
        self, repo, cloud_name, key, secret
    ) -> None:
        settings.CLOUDINARY_CLOUD_NAME = cloud_name
        settings.CLOUDINARY_API_KEY = key
        settings.CLOUDINARY_API_SECRET = secret

        assert await resolve("cloudinary") is None

    async def test_google_oauth_pair_resolves_secret_as_key(self, repo) -> None:
        settings.GOOGLE_CLIENT_ID = "client-id.apps.googleusercontent.com"
        settings.GOOGLE_CLIENT_SECRET = "GOCSPID-test"

        config = await resolve("google_oauth")

        assert config is not None and config["api_key"] == "GOCSPID-test"

    @pytest.mark.parametrize(
        ("client_id", "client_secret"),
        [(None, "GOCSPID-test"), ("client-id", None)],
    )
    async def test_google_oauth_half_pair_is_not_configured(
        self, repo, client_id, client_secret
    ) -> None:
        settings.GOOGLE_CLIENT_ID = client_id
        settings.GOOGLE_CLIENT_SECRET = client_secret

        assert await resolve("google_oauth") is None


# ---------------------------------------------------------------------------
# resolve — 60s TTL cache
# ---------------------------------------------------------------------------


class TestCardSavedAccounts:
    """Cloudinary and Google OAuth work from what their Settings card saves, with no .env."""

    @pytest.fixture(autouse=True)
    def _no_env_halves(self) -> None:
        for name in (
            "CLOUDINARY_CLOUD_NAME",
            "CLOUDINARY_API_KEY",
            "CLOUDINARY_API_SECRET",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
        ):
            setattr(settings, name, None)

    async def test_a_saved_cloudinary_account_works_without_env(self, repo, fixed_secret) -> None:
        await upsert(
            "cloudinary",
            api_key="cl-key",
            account_id="my-cloud",
            api_secret="cl-secret",  # pragma: allowlist secret
        )

        config = await resolve("cloudinary")

        assert is_usable("cloudinary", config)
        assert cloudinary_account(config) == CloudinaryAccount(
            cloud_name="my-cloud", api_key="cl-key", api_secret="cl-secret"
        )

    async def test_a_saved_google_client_works_without_env(self, repo, fixed_secret) -> None:
        await upsert("google_oauth", api_key="GOCSPX-secret", account_id="id.apps.example")

        config = await resolve("google_oauth")

        assert google_oauth_client(config) == GoogleOAuthClient(
            client_id="id.apps.example", client_secret="GOCSPX-secret"
        )

    @pytest.mark.parametrize(
        ("provider", "fields"),
        [
            ("cloudinary", {"api_key": "k", "account_id": "c"}),
            ("cloudinary", {"api_key": "k", "api_secret": "s"}),
            ("google_oauth", {"api_key": "s"}),
        ],
    )
    async def test_a_partial_saved_account_is_not_usable(
        self, repo, fixed_secret, provider: str, fields: dict[str, str]
    ) -> None:
        await upsert(provider, **fields)

        assert not is_usable(provider, await resolve(provider))


class TestResolveCache:
    async def test_hits_within_ttl_and_expires_after(self, repo, fixed_secret, clock) -> None:
        await upsert("tavily", api_key="tvly-key")

        await resolve("tavily")
        await resolve("tavily")
        assert repo.find_calls == 1  # second read served from cache

        clock.advance(61)
        await resolve("tavily")
        assert repo.find_calls == 2  # entry expired → DB re-read

    async def test_negative_result_cached_too(self, repo, clock) -> None:
        await resolve("gemini")  # unconfigured → None
        await resolve("gemini")
        assert repo.find_calls == 1

    async def test_unknown_provider_not_cached(self, repo) -> None:
        assert await resolve("bogus") is None
        assert "bogus" not in service_module._cache


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    async def test_clears_cache_and_fans_out(
        self, repo, fixed_secret, redis_fake, registry_reset_calls, aux_cache_calls, clock
    ) -> None:
        await resolve("openrouter")  # populate the cache from env fallback
        assert "openrouter" in service_module._cache

        await invalidate("openrouter")

        assert "openrouter" not in service_module._cache
        assert registry_reset_calls == ["openrouter_llm"]
        assert aux_cache_calls == [1]
        assert redis_fake.published == [
            (RUNTIME_CONFIG_CHANNEL, json.dumps({"scope": "provider:openrouter"}))
        ]

    async def test_non_llm_provider_skips_registry_reset_but_still_fans_out(
        self, redis_fake, registry_reset_calls, aux_cache_calls
    ) -> None:
        await invalidate("tavily")

        assert registry_reset_calls == []  # tavily has no LLM loader
        assert aux_cache_calls == [1]
        assert len(redis_fake.published) == 1

    async def test_missing_registry_entry_is_handled(
        self, monkeypatch, fixed_secret, redis_fake, aux_cache_calls
    ) -> None:
        """Handle an unregistered registry key and keep going; the fan-out still runs."""

        def _missing(_name: str) -> None:
            raise KeyError(_name)

        monkeypatch.setattr(provider_registry, "reset", _missing)

        await invalidate("ollama")  # must not raise

        assert aux_cache_calls == [1]
        assert len(redis_fake.published) == 1

    async def test_redis_publish_failure_does_not_break_invalidation(
        self, redis_fake, registry_reset_calls, aux_cache_calls
    ) -> None:
        """Cross-pod refresh degrades loudly; local consistency work already done."""
        redis_fake.fail_publish = True

        async with captured_wide_event() as event:
            await invalidate("gemini")

        assert "gemini" not in service_module._cache
        assert aux_cache_calls == [1]
        assert event["errors"] == [
            {
                "msg": f"{LogTag.API} Failed to publish runtime-config update",
                "channel": RUNTIME_CONFIG_CHANNEL,
                "scope": "provider:gemini",
                "error": "redis down",
                "error_type": "ConnectionError",
            }
        ]

    async def test_without_redis_the_update_stays_local(self, monkeypatch) -> None:
        monkeypatch.setattr(redis_cache, "redis", None)

        async with captured_wide_event() as event:
            await invalidate("gemini")

        assert "errors" not in event

    async def test_upsert_invalidates_its_own_cache(
        self, repo, fixed_secret, redis_fake, registry_reset_calls, aux_cache_calls
    ) -> None:
        """A save warms the snapshot with the value just written, not empty."""
        stale_at = time.monotonic()
        service_module._cache["openrouter"] = (
            stale_at - 3600,
            {
                "api_key": "sk-stale",
                "base_url": None,
                "model": None,
                "preset": None,
                "account_id": None,
                "api_secret": None,
            },
        )

        await upsert("openrouter", api_key="sk-v1")

        assert registry_reset_calls == ["openrouter_llm"]
        _, cached = service_module._cache["openrouter"]
        assert cached["api_key"] == "sk-v1"

    async def test_delete_invalidates_too(
        self, repo, fixed_secret, redis_fake, registry_reset_calls, aux_cache_calls, monkeypatch
    ) -> None:
        await upsert("ollama", base_url="http://o/v1")
        registry_reset_calls.clear()
        aux_cache_calls.clear()

        await delete("ollama")

        assert repo.delete_calls == ["ollama"]
        # After deletion: no store row AND no explicit OLLAMA_BASE_URL env →
        # the code default must NOT masquerade as a working endpoint.
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        assert await resolve("ollama") is None
        assert registry_reset_calls == ["ollama_llm"]


# ---------------------------------------------------------------------------
# invalidate_locally — the pod-local half shared with the remote subscriber
# ---------------------------------------------------------------------------


class TestInvalidateLocally:
    async def test_drops_caches_and_fans_out_without_publishing(
        self, repo, fixed_secret, redis_fake, registry_reset_calls, aux_cache_calls
    ) -> None:
        """Run a remote pod update with no publish; publishing would echo the update forever."""
        await resolve("openrouter")
        assert "openrouter" in service_module._cache

        service_module.invalidate_locally("openrouter")

        assert "openrouter" not in service_module._cache
        assert registry_reset_calls == ["openrouter_llm"]
        assert aux_cache_calls == [1]
        assert redis_fake.published == []

    def test_unknown_provider_is_a_harmless_noop(
        self, redis_fake, registry_reset_calls, aux_cache_calls
    ) -> None:
        """Clear what it can for an unknown provider without raising."""
        service_module.invalidate_locally("not-a-provider")

        assert registry_reset_calls == []
        assert aux_cache_calls == [1]
        assert redis_fake.published == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.parametrize("provider", ["not-a-provider", "", "OpenRouter"])
    async def test_upsert_rejects_unknown_providers(self, repo, fixed_secret, provider) -> None:
        with pytest.raises(ValueError):
            await upsert(provider, api_key="sk-x")
        assert repo.upsert_calls == []

    @pytest.mark.parametrize("provider", ["not-a-provider", "", "OpenRouter"])
    async def test_delete_rejects_unknown_providers(self, repo, fixed_secret, provider) -> None:
        with pytest.raises(ValueError):
            await delete(provider)
        assert repo.delete_calls == []


# ---------------------------------------------------------------------------
# inspect_credential — where the active credential comes from
# ---------------------------------------------------------------------------


class TestInspectCredential:
    async def test_a_stored_key_over_a_different_env_key_is_flagged(
        self, repo, fixed_secret
    ) -> None:
        settings.GOOGLE_API_KEY = "env-key"
        await upsert("gemini", api_key="saved-key")

        async with captured_wide_event() as event:
            resolution = await inspect_credential("gemini")

        assert resolution.source is CredentialSource.STORED
        assert resolution.shadows_env is True
        assert [w["provider"] for w in event["warnings"]] == ["gemini"]

    async def test_a_stored_key_equal_to_the_env_key_is_not_flagged(
        self, repo, fixed_secret
    ) -> None:
        settings.GOOGLE_API_KEY = "same-key"
        await upsert("gemini", api_key="same-key")

        resolution = await inspect_credential("gemini")

        assert resolution == CredentialResolution(
            config=resolution.config, source=CredentialSource.STORED, shadows_env=False
        )

    async def test_an_undecryptable_row_reports_the_env_key_that_actually_serves(
        self, repo, fixed_secret
    ) -> None:
        settings.GOOGLE_API_KEY = "env-key"
        repo.ciphertexts["gemini"] = "not-a-fernet-token"

        resolution = await inspect_credential("gemini")

        assert resolution.source is CredentialSource.ENV
        assert resolution.config is not None and resolution.config["api_key"] == "env-key"

    async def test_without_runtime_credentials_the_store_is_never_reported(
        self, repo, fixed_secret, monkeypatch
    ) -> None:
        settings.GOOGLE_API_KEY = "env-key"
        await upsert("gemini", api_key="saved-key")
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        repo.find_calls = 0

        resolution = await inspect_credential("gemini")

        assert resolution.source is CredentialSource.ENV
        assert resolution.shadows_env is False
        assert repo.find_calls == 0


# ---------------------------------------------------------------------------
# Exact shapes, refusals and the warnings an operator reads
# ---------------------------------------------------------------------------


def _config(**fields: str | None) -> dict[str, str | None]:
    return {
        "api_key": None,
        "base_url": None,
        "model": None,
        "preset": None,
        "account_id": None,
        "api_secret": None,
        **fields,
    }


class TestEnvConfigShapes:
    """Every env fallback is the full config the consumers index into."""

    def test_searxng(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://searx:8080")

        assert env_config("searxng") == _config(base_url="http://searx:8080")

    def test_cloudinary(self) -> None:
        settings.CLOUDINARY_CLOUD_NAME = "cloud"
        settings.CLOUDINARY_API_KEY = "ck"
        settings.CLOUDINARY_API_SECRET = "cs"  # pragma: allowlist secret

        assert env_config("cloudinary") == _config(
            api_key="ck",
            account_id="cloud",
            api_secret="cs",  # pragma: allowlist secret
        )

    def test_google_oauth(self) -> None:
        settings.GOOGLE_CLIENT_ID = "gid"
        settings.GOOGLE_CLIENT_SECRET = "gsecret"  # pragma: allowlist secret

        assert env_config("google_oauth") == _config(api_key="gsecret", account_id="gid")

    def test_a_single_key_tool(self) -> None:
        settings.TAVILY_API_KEY = "tvly"

        assert env_config("tavily") == _config(api_key="tvly")

    @pytest.mark.parametrize(
        "present",
        [("DEV_LLM_BASE_URL",), ("DEV_LLM_BASE_URL", "DEV_LLM_API_KEY"), ("DEV_LLM_MODEL",)],
    )
    def test_the_custom_lane_needs_all_three_of_its_settings(
        self, present: tuple[str, ...]
    ) -> None:
        settings.ENV = "development"
        for field in present:
            setattr(settings, field, "set")

        assert env_config("custom") is None


class TestOperatorFacingFailures:
    async def test_a_shadowed_env_key_warning_names_the_fix(self, repo, fixed_secret) -> None:
        settings.GOOGLE_API_KEY = "env-key"
        await upsert("gemini", api_key="saved-key")

        async with captured_wide_event() as event:
            await inspect_credential("gemini")

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.API} A stored provider credential overrides a different env value",
                "provider": "gemini",
                "fix": "delete the stored credential in Settings to use the env value, "
                "or remove the env value",
            }
        ]

    async def test_an_undecryptable_row_is_an_error_naming_the_fix(
        self, repo, fixed_secret
    ) -> None:
        repo.ciphertexts["gemini"] = "not-a-fernet-token"

        async with captured_wide_event() as event:
            await inspect_credential("gemini")

        [error] = event["errors"]
        assert error["msg"] == f"{LogTag.API} Stored provider credential cannot be decrypted"
        assert error["reason"].startswith("instance secret mismatch (InvalidToken(")
        assert error["fix"] == "re-enter the provider credentials; the old ciphertext is unreadable"

    async def test_a_decrypted_payload_that_is_not_an_object_is_refused(
        self, repo, fixed_secret
    ) -> None:
        repo.ciphertexts["gemini"] = (
            Fernet(fernet_key_from(INSTANCE_SECRET)).encrypt(b'["not", "an", "object"]').decode()
        )

        with pytest.raises(ValueError) as refused:
            await inspect_credential("gemini")

        assert str(refused.value) == "decrypted provider credential payload is not a JSON object"

    async def test_an_unknown_provider_is_refused_listing_the_known_ones(
        self, repo, fixed_secret
    ) -> None:
        with pytest.raises(ValueError) as refused:
            await upsert("bogus", api_key="sk-x")

        assert str(refused.value) == (
            f"Unknown provider 'bogus' — expected one of {', '.join(CREDENTIAL_PROVIDERS)}"
        )

    async def test_an_env_only_deployment_refuses_writes(
        self, repo, fixed_secret, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")

        with pytest.raises(RuntimeError) as refused:
            await upsert("gemini", api_key="sk-x")

        assert str(refused.value) == (
            "This deployment reads provider credentials from the environment only; "
            "the credential store is not writable here"
        )


class TestCacheLifecycle:
    async def test_an_entry_expires_at_exactly_the_ttl(self, repo, fixed_secret, clock) -> None:
        await resolve("tavily")
        clock.advance(service_module._CACHE_TTL_SECONDS)
        await resolve("tavily")

        assert repo.find_calls == 2

    async def test_a_delete_leaves_the_cache_warm(self, repo, fixed_secret, redis_fake) -> None:
        await upsert("tavily", api_key="tvly-key")
        await delete("tavily")
        reads = repo.find_calls

        assert await resolve("tavily") is None
        assert repo.find_calls == reads

    def test_a_registered_hook_runs_on_every_local_invalidation(self) -> None:
        runs: list[str] = []
        service_module.on_local_invalidation(lambda: runs.append("ran"))

        service_module.invalidate_locally("gemini")

        assert runs == ["ran"]
