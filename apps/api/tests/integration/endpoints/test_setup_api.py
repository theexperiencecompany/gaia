"""Setup API integration tests (A4 contract: .agents/plans/selfhost-contracts.md).

Drives the real router over ASGITransport with the parallel-agent seams
(provider credentials service, instance/local repositories) bound to the
contract fakes from conftest.py, provider probes mocked via respx, and DNS
resolution stubbed to public answers (the SSRF guard resolves hostnames itself,
outside respx's transport mock).
"""

from collections.abc import Callable, Iterator
import ipaddress
import json
import socket
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
import httpx
from httpx import AsyncClient
import pytest
import respx

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints.setup import router as setup_router
from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.constants.llm import LLMProviderName
from app.constants.providers import (
    LLM_MODEL_PROFILES,
    LLM_PROVIDER_PRIORITY,
    CredentialProviderName,
    ProviderFeature,
)
from app.services.providers import provider_probe_service, provider_setup_service
from app.services.providers.provider_credentials_service import ProviderConfig
from shared.py.wide_events import log
from tests.helpers import captured_wide_event
from tests.integration.endpoints.conftest import (
    API,
    FAKE_USER_ID,
    _client,
    local_credentials_repo,
    provider_service,
    seed_state,
)

SECRET_KEY = "sk-live-supersecret-9876"
STORED_KEY = "sk-stored"
EVIL_BASE_URL = "https://evil.example"
CHAT_COMPLETION = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
CUSTOM_PROBE_BODY = {"base_url": "https://gw.test/v1", "model": "m-1"}

# Public IP the DNS stub answers with for every hostname (the guard's
# ``is_global`` check must pass it).
STUB_PUBLIC_IP = "8.8.8.8"

# One ``socket.getaddrinfo`` record: (family, type, proto, canonname, sockaddr).
GetAddrInfoResult = list[tuple[int, int, int, str, tuple[str, int]]]


def _resolver_returning(*addresses: str) -> Callable[..., GetAddrInfoResult]:
    """Build a socket.getaddrinfo stand-in answering every host with the given addresses."""

    def fake_getaddrinfo(
        host: str, port: int | None, *args: int, **kwargs: int
    ) -> GetAddrInfoResult:
        # A literal IP resolves to itself, as real getaddrinfo does; only
        # names are answered with the configured addresses.
        try:
            resolved = [str(ipaddress.ip_address(host))]
        except ValueError:
            resolved = list(addresses)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 0))
            for address in resolved
        ]

    return fake_getaddrinfo


@pytest.fixture(autouse=True)
def _stub_dns_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer every hostname with a public IP so no test touches real DNS.

    The SSRF guard resolves hostnames itself — outside respx, which only mocks
    the httpx transport — so without this stub every probe test would depend on
    live resolver behavior. Guard tests override per-test with their own
    resolver answers.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning(STUB_PUBLIC_IP))


def _routes(path: str) -> list[APIRoute]:
    routes = [r for r in setup_router.routes if isinstance(r, APIRoute) and r.path == path]
    assert routes, f"no route mounted for {path}"
    return routes


def _walk_dependants(dependant: Dependant) -> Iterator[Dependant]:
    """Walk the dependency graph of one route: handler plus every nested sub-dependency.

    Per-param Depends live on the dependant dependencies list, so a flat scan
    misses guards wrapped inside another dependency.
    """
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk_dependants(sub)


def _requires(path: str, call: Callable[..., Any]) -> bool:
    """Report whether every route under the path requires the given dependency call."""
    return all(
        any(dep.call is call for dep in _walk_dependants(route.dependant))
        for route in _routes(path)
    )


class TestStatus:
    async def test_public_without_auth(self, anon_client: AsyncClient) -> None:
        resp = await anon_client.get(f"{API}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {
            "auth_mode",
            "has_admin_account",
            "registration_policy",
            "needs_setup",
            "wizard_dismissed",
            "deployment",
            "providers",
            "features",
            "plans_seeded",
            "bots",
        }
        assert set(body["bots"]) == {
            "telegram_username",
            "discord_client_id",
            "slack_workspace_url",
        }
        assert set(body["deployment"]) == {
            "kind",
            "bills",
            "local_code_sandbox",
            "blob_store",
            "gaia_support",
            "instance_toolkits",
            "private_network_endpoints",
        }
        assert body["registration_policy"] == "invite_only"
        assert set(body["providers"]) == {
            "openrouter",
            "gemini",
            "ollama",
            "custom",
            "tavily",
            "exa",
            "brave",
            "searxng",
            "composio",
            "e2b",
            "openai",
            "resend",
            "cloudinary",
            "google_oauth",
            "firecrawl",
            "openweather",
            "llamaparse",
            "github",
        }
        assert all(
            set(v) == {"configured", "source", "env_shadowed"} for v in body["providers"].values()
        )
        assert set(body["features"]) == set(ProviderFeature)
        assert body["features"]["web_search"] == {
            "available": True,
            "working": True,
            "in_use": ["duckduckgo"],
        }

    @pytest.mark.parametrize("blob_store", list(BlobStoreKind))
    async def test_status_reports_the_instances_blob_store(
        self, anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, blob_store: BlobStoreKind
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "BLOB_STORE", blob_store)

        resp = await anon_client.get(f"{API}/status")

        assert resp.json()["deployment"]["blob_store"] == blob_store.value

    @pytest.mark.parametrize(("env", "gaia_support"), [("selfhost", False), ("development", True)])
    async def test_status_says_whether_support_requests_reach_gaia(
        self,
        anon_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        env: str,
        gaia_support: bool,
    ) -> None:
        monkeypatch.setattr(settings, "ENV", env)

        resp = await anon_client.get(f"{API}/status")

        assert resp.json()["deployment"]["gaia_support"] is gaia_support

    async def test_status_names_the_bots_this_instance_runs(
        self, anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "my_gaia_bot")
        monkeypatch.setattr(settings, "DISCORD_CLIENT_ID", "1234567890")
        monkeypatch.setattr(settings, "SLACK_WORKSPACE_URL", "https://acme.slack.com/")

        resp = await anon_client.get(f"{API}/status")

        assert resp.json()["bots"] == {
            "telegram_username": "my_gaia_bot",
            "discord_client_id": "1234567890",
            "slack_workspace_url": "https://acme.slack.com/",
        }

    async def test_a_selfhost_instance_without_bots_never_points_at_gaia_clouds(
        self, anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", None)
        monkeypatch.setattr(settings, "DISCORD_CLIENT_ID", None)
        monkeypatch.setattr(settings, "SLACK_WORKSPACE_URL", None)

        resp = await anon_client.get(f"{API}/status")

        assert resp.json()["bots"] == {
            "telegram_username": None,
            "discord_client_id": None,
            "slack_workspace_url": None,
        }

    async def test_status_has_no_auth_dependency(self) -> None:
        assert not _requires("/status", get_current_user)

    async def test_status_is_not_admin_gated(self) -> None:
        assert not _requires("/status", require_instance_admin)

    async def test_status_stamps_the_request_wide_event(self, anon_client: AsyncClient) -> None:
        """Open the public status probe wide event with an operation tag; no user to stamp."""
        log.reset()
        try:
            resp = await anon_client.get(f"{API}/status")
            assert resp.status_code == 200
            event = log.get()
            assert event["operation"] == "setup_status"
            assert event["auth_mode"] == settings.AUTH_MODE
        finally:
            log.reset()

    async def test_billing_disabled_under_selfhost(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        resp = await client.get(f"{API}/status")
        assert resp.json()["deployment"]["bills"] is False

    async def test_billing_enabled_outside_selfhost(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        resp = await client.get(f"{API}/status")
        assert resp.json()["deployment"]["bills"] is True

    @pytest.mark.parametrize(
        ("auth_mode", "admin_exists", "llm_configured", "expected"),
        [
            ("local", False, False, True),  # nothing configured at all
            ("local", False, True, True),  # LLM works but no admin account yet
            ("local", True, False, True),  # admin exists but no working LLM lane
            ("local", True, True, False),  # fully set up
            ("workos", False, True, False),  # hosted auth ignores the admin account
            ("workos", True, False, True),
        ],
    )
    async def test_needs_setup_matrix(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        auth_mode: str,
        admin_exists: bool,
        llm_configured: bool,
        expected: bool,
    ) -> None:
        monkeypatch.setattr(settings, "AUTH_MODE", auth_mode)
        local_credentials_repo.admin_user_id = FAKE_USER_ID if admin_exists else None
        if llm_configured:
            provider_service.configs["openrouter"] = ProviderConfig(
                api_key=SECRET_KEY,
            )
        resp = await client.get(f"{API}/status")
        assert resp.json()["needs_setup"] is expected

    async def test_openai_alone_satisfies_llm_requirement(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        provider_service.configs["openai"] = ProviderConfig(
            api_key=SECRET_KEY,
        )
        resp = await client.get(f"{API}/status")
        assert resp.json()["needs_setup"] is False

    async def test_tavily_alone_does_not_satisfy_llm_requirement(self, client: AsyncClient) -> None:
        provider_service.configs["tavily"] = ProviderConfig(
            api_key="tvly-key",
        )
        body = (await client.get(f"{API}/status")).json()
        assert body["providers"]["tavily"]["configured"] is True
        assert body["needs_setup"] is True

    async def test_env_fallback_counts_as_configured_from_env(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "GOOGLE_API_KEY", "env-key")
        body = (await client.get(f"{API}/status")).json()
        assert body["providers"]["gemini"] == {
            "configured": True,
            "source": "env",
            "env_shadowed": False,
        }

    async def test_a_saved_credential_reports_it_overrides_env(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "GOOGLE_API_KEY", "env-key")
        provider_service.configs["gemini"] = ProviderConfig(
            api_key="saved-key",
        )
        body = (await client.get(f"{API}/status")).json()
        assert body["providers"]["gemini"] == {
            "configured": True,
            "source": "stored",
            "env_shadowed": True,
        }

    @pytest.mark.parametrize(
        ("provider", "body"),
        [
            (
                "cloudinary",
                {"api_key": STORED_KEY, "account_id": "my-cloud", "api_secret": "cl-secret"},
            ),
            ("google_oauth", {"api_key": STORED_KEY, "account_id": "id.apps.example"}),
        ],
    )
    async def test_a_card_saved_account_is_configured_with_no_env(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        provider: str,
        body: dict[str, str],
    ) -> None:
        for name in (
            "CLOUDINARY_CLOUD_NAME",
            "CLOUDINARY_API_KEY",
            "CLOUDINARY_API_SECRET",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.setattr(settings, name, None)

        assert (await client.put(f"{API}/providers/{provider}", json=body)).status_code == 200
        status = (await client.get(f"{API}/status")).json()["providers"][provider]
        listed = (await client.get(f"{API}/providers")).json()["providers"][provider]

        assert status == {"configured": True, "source": "stored", "env_shadowed": False}
        assert listed["configured"] is True
        assert listed["account_id"] == body["account_id"]

    @pytest.mark.parametrize("provider", ["cloudinary", "google_oauth"])
    async def test_a_saved_key_alone_is_not_configured(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, provider: str
    ) -> None:
        for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_SECRET", "GOOGLE_CLIENT_ID"):
            monkeypatch.setattr(settings, name, "env-value")

        await client.put(f"{API}/providers/{provider}", json={"api_key": STORED_KEY})

        status = (await client.get(f"{API}/status")).json()["providers"][provider]
        assert status["configured"] is False

    async def test_an_unconfigured_provider_reports_unset(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "FIRECRAWL_API_KEY", None)
        body = (await client.get(f"{API}/status")).json()
        assert body["providers"]["firecrawl"] == {
            "configured": False,
            "source": "unset",
            "env_shadowed": False,
        }

    async def test_seed_flags_surfaced(self, client: AsyncClient) -> None:
        body = (await client.get(f"{API}/status")).json()
        assert body["plans_seeded"] is True

        seed_state.plans_seeded = False
        body = (await client.get(f"{API}/status")).json()
        assert body["plans_seeded"] is False


class TestSetupWizardDismissal:
    async def test_wizard_is_owed_until_the_admin_dismisses_it(
        self, client: AsyncClient, anon_client: AsyncClient
    ) -> None:
        assert (await anon_client.get(f"{API}/status")).json()["wizard_dismissed"] is False

        resp = await client.post(f"{API}/wizard/dismiss")

        assert resp.status_code == 200
        assert resp.json() == {"wizard_dismissed": True}
        assert (await anon_client.get(f"{API}/status")).json()["wizard_dismissed"] is True

    async def test_a_member_cannot_dismiss_the_wizard(
        self, nonadmin_client: AsyncClient, anon_client: AsyncClient
    ) -> None:
        resp = await nonadmin_client.post(f"{API}/wizard/dismiss")

        assert resp.status_code == 403
        assert (await anon_client.get(f"{API}/status")).json()["wizard_dismissed"] is False

    async def test_dismissal_leaves_needs_setup_to_the_providers(self, client: AsyncClient) -> None:
        await client.post(f"{API}/wizard/dismiss")

        assert (await client.get(f"{API}/status")).json()["needs_setup"] is True

    async def test_dismissal_stamps_the_admin_on_the_wide_event(self, client: AsyncClient) -> None:
        async with captured_wide_event() as event:
            assert (await client.post(f"{API}/wizard/dismiss")).status_code == 200

        assert event["user"] == {"id": FAKE_USER_ID}
        assert event["operation"] == "setup_wizard_dismiss"


class TestProviderCatalog:
    """Serve the Python provider catalog so the wizard and Settings render dynamically.

    Adding a provider therefore stays a Python-only change.
    """

    async def test_catalog_lists_every_provider_in_display_order(
        self, anon_client: AsyncClient
    ) -> None:
        resp = await anon_client.get(f"{API}/catalog")
        assert resp.status_code == 200
        body = resp.json()
        assert list(body["providers"]) == list(CredentialProviderName)

    async def test_catalog_entries_carry_display_metadata_only(
        self, anon_client: AsyncClient
    ) -> None:
        body = (await anon_client.get(f"{API}/catalog")).json()
        for spec in body["providers"].values():
            assert set(spec) == {
                "label",
                "description",
                "key_url",
                "base_url",
                "default_model",
                "favicon_url",
                "needs_base_url",
                "api_key_label",
                "account_id_label",
                "second_key_label",
                "takes_key",
                "takes_model",
                "managed_at",
            }
        assert body["providers"]["openrouter"]["label"] == "OpenRouter"
        assert body["providers"]["ollama"]["default_model"] == "llama3.2"

    async def test_custom_lane_presets_are_partitioned_out_of_providers(
        self, anon_client: AsyncClient
    ) -> None:
        """Keep preset gateways inside the custom card, never as provider cards."""
        body = (await anon_client.get(f"{API}/catalog")).json()
        assert set(body["custom_presets"]) == {"opencode", "nous"}
        assert "opencode" not in body["providers"]
        assert body["custom_presets"]["opencode"]["base_url"] == "https://opencode.ai/zen/go/v1"

    async def test_llm_keys_mirror_the_needs_setup_rule(self, anon_client: AsyncClient) -> None:
        body = (await anon_client.get(f"{API}/catalog")).json()
        assert body["llm_provider_keys"] == ["openrouter", "gemini", "openai", "ollama", "custom"]

    async def test_catalog_groups_every_provider_under_a_feature(
        self, anon_client: AsyncClient
    ) -> None:
        body = (await anon_client.get(f"{API}/catalog")).json()
        assert list(body["features"]) == [f.value for f in ProviderFeature]
        assert body["features"]["web_search"]["built_in"]["engine"] == "duckduckgo"
        assert body["features"]["web_search"]["providers"] == ["tavily", "exa", "brave", "searxng"]
        assert body["features"]["email"]["built_in"] is None
        grouped = [p for spec in body["features"].values() for p in spec["providers"]]
        assert sorted(grouped) == sorted(CredentialProviderName)

    async def test_catalog_is_public_without_auth(self, anon_client: AsyncClient) -> None:
        # The wizard renders cards before an admin session exists; the catalog
        # carries display metadata only.
        assert (await anon_client.get(f"{API}/catalog")).status_code == 200

    async def test_catalog_has_no_auth_dependency(self) -> None:
        assert not _requires("/catalog", get_current_user)
        assert not _requires("/catalog", require_instance_admin)

    async def test_catalog_stamps_the_request_wide_event(self, anon_client: AsyncClient) -> None:
        async with captured_wide_event() as event:
            assert (await anon_client.get(f"{API}/catalog")).status_code == 200

        assert event["operation"] == "setup_catalog"
        assert event["auth_mode"] == settings.AUTH_MODE


class TestProvidersMaskedView:
    async def test_masked_output_never_contains_full_key(self, client: AsyncClient) -> None:
        await provider_service.upsert("openrouter", ProviderConfig(api_key=SECRET_KEY))
        resp = await client.get(f"{API}/providers")
        assert resp.status_code == 200
        text = resp.text
        assert SECRET_KEY not in text
        entry = resp.json()["providers"]["openrouter"]
        assert entry == {
            "provider": "openrouter",
            "configured": True,
            "base_url": None,
            "model": None,
            "api_key_hint": f"...{SECRET_KEY[-4:]}",
            "account_id": None,
            "api_secret_hint": None,
        }

    async def test_a_second_secret_is_masked_like_the_key(self, client: AsyncClient) -> None:
        await provider_service.upsert(
            "cloudinary",
            ProviderConfig(api_key="cl-key", account_id="my-cloud", api_secret=SECRET_KEY),
        )

        resp = await client.get(f"{API}/providers")

        assert SECRET_KEY not in resp.text
        assert resp.json()["providers"]["cloudinary"]["api_secret_hint"] == f"...{SECRET_KEY[-4:]}"

    async def test_unconfigured_provider_is_none_everywhere(self, client: AsyncClient) -> None:
        entry = (await client.get(f"{API}/providers")).json()["providers"]["custom"]
        assert entry["configured"] is False
        assert entry["api_key_hint"] is None

    async def test_an_endpoint_and_model_are_shown_unmasked(self, client: AsyncClient) -> None:
        await provider_service.upsert(
            "custom",
            ProviderConfig(api_key=SECRET_KEY, base_url="https://gw.test/v1", model="m-1"),
        )

        entry = (await client.get(f"{API}/providers")).json()["providers"]["custom"]

        assert (entry["configured"], entry["base_url"], entry["model"]) == (
            True,
            "https://gw.test/v1",
            "m-1",
        )

    async def test_a_custom_endpoint_without_a_model_is_not_configured(
        self, client: AsyncClient
    ) -> None:
        await provider_service.upsert(
            "custom", ProviderConfig(api_key=SECRET_KEY, base_url="https://gw.test/v1")
        )

        entry = (await client.get(f"{API}/providers")).json()["providers"]["custom"]

        assert entry["configured"] is False


class TestUpsertProvider:
    async def test_preset_fills_opencode_endpoint_and_model(self, client: AsyncClient) -> None:
        resp = await client.put(
            f"{API}/providers/custom",
            json={"preset": "opencode", "api_key": SECRET_KEY},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert provider_service.configs["custom"] == ProviderConfig(
            api_key=SECRET_KEY,
            base_url="https://opencode.ai/zen/go/v1",
            model="deepseek-v4-flash",
            preset="opencode",
        )

    async def test_explicit_base_url_wins_over_preset(self, client: AsyncClient) -> None:
        await client.put(
            f"{API}/providers/custom",
            json={"preset": "opencode", "api_key": "k", "base_url": "https://proxy.internal/v1"},
        )
        assert provider_service.configs["custom"].base_url == "https://proxy.internal/v1"

    async def test_cache_invalidated_after_upsert(self, client: AsyncClient) -> None:
        await client.put(f"{API}/providers/gemini", json={"api_key": "g-key"})
        assert provider_service.invalidated == ["gemini"]

    async def test_unknown_provider_rejected(self, client: AsyncClient) -> None:
        resp = await client.put(f"{API}/providers/anthropic", json={"api_key": "k"})
        assert resp.status_code == 422
        assert provider_service.configs == {}

    async def test_an_empty_body_is_refused_and_stores_nothing(self, client: AsyncClient) -> None:
        resp = await client.put(f"{API}/providers/gemini", json={})

        assert resp.status_code == 422
        assert resp.json()["message"] == "No fields to update"
        assert provider_service.configs == {}

    async def test_a_partial_update_keeps_every_stored_field_it_omits(
        self, client: AsyncClient
    ) -> None:
        await provider_service.upsert(
            "custom",
            ProviderConfig(
                api_key=STORED_KEY,
                base_url="https://gw.test/v1",
                model="m-1",
                preset="opencode",
                account_id="acct",
                api_secret="second-secret",
            ),
        )

        resp = await client.put(f"{API}/providers/custom", json={"model": "m-2"})

        assert resp.status_code == 200
        assert provider_service.configs["custom"] == ProviderConfig(
            api_key=STORED_KEY,
            base_url="https://gw.test/v1",
            model="m-2",
            preset="opencode",
            account_id="acct",
            api_secret="second-secret",
        )

    async def test_rotating_the_key_keeps_the_stored_model(self, client: AsyncClient) -> None:
        await provider_service.upsert(
            "custom",
            ProviderConfig(api_key=STORED_KEY, base_url="https://gw.test/v1", model="m-1"),
        )

        await client.put(f"{API}/providers/custom", json={"api_key": "rotated-key"})

        stored = provider_service.configs["custom"]
        assert (stored.api_key, stored.model) == ("rotated-key", "m-1")

    async def test_a_given_field_replaces_the_stored_one(self, client: AsyncClient) -> None:
        await provider_service.upsert(
            "cloudinary",
            ProviderConfig(api_key="old-key", account_id="old-cloud", api_secret="old-secret"),
        )

        await client.put(
            f"{API}/providers/cloudinary",
            json={"api_key": "new-key", "account_id": "new-cloud", "api_secret": "new-secret"},
        )

        stored = provider_service.configs["cloudinary"]
        assert (stored.api_key, stored.account_id, stored.api_secret) == (
            "new-key",
            "new-cloud",
            "new-secret",
        )

    async def test_put_requires_auth_dependency(self) -> None:
        assert _requires("/providers/{provider}", get_current_user)


class TestProviderAudit:
    async def test_saving_a_credential_is_audited_without_the_key(
        self, client: AsyncClient
    ) -> None:
        log.reset()
        try:
            await client.put(f"{API}/providers/gemini", json={"api_key": SECRET_KEY})
            [entry] = log.get()["audit"]
        finally:
            log.reset()

        assert entry == {
            "msg": "provider credential saved",
            "actor": FAKE_USER_ID,
            "provider": "gemini",
            "api_key_changed": True,
        }

    async def test_removing_a_credential_is_audited(self, client: AsyncClient) -> None:
        log.reset()
        try:
            await client.delete(f"{API}/providers/gemini")
            [entry] = log.get()["audit"]
        finally:
            log.reset()

        assert entry == {
            "msg": "provider credential removed",
            "actor": FAKE_USER_ID,
            "provider": "gemini",
        }

    async def test_an_update_without_a_key_is_audited_as_keeping_it(
        self, client: AsyncClient
    ) -> None:
        await provider_service.upsert("gemini", ProviderConfig(api_key=SECRET_KEY))
        async with captured_wide_event() as event:
            await client.put(f"{API}/providers/gemini", json={"model": "gemini-2.5-pro"})

        [entry] = event["audit"]
        assert entry["api_key_changed"] is False


class TestDeleteProvider:
    async def test_delete_removes_credential_and_invalidates(self, client: AsyncClient) -> None:
        await provider_service.upsert("ollama", ProviderConfig(base_url="http://localhost:11434"))
        resp = await client.delete(f"{API}/providers/ollama")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert "ollama" not in provider_service.configs
        assert provider_service.invalidated == ["ollama"]

    async def test_unknown_provider_rejected(self, client: AsyncClient) -> None:
        resp = await client.delete(f"{API}/providers/bogus")
        assert resp.status_code == 422


class TestProviderProbe:
    async def test_custom_probes_a_chat_completion_against_its_model(
        self, client: AsyncClient
    ) -> None:
        with respx.mock:
            route = respx.post("https://gw.test/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": "https://gw.test/v1", "api_key": SECRET_KEY, "model": "m-1"},
            )
        request = route.calls.last.request
        assert (b"Authorization", f"Bearer {SECRET_KEY}".encode()) in request.headers.raw
        assert set(request.extensions["timeout"].values()) == {
            provider_probe_service._PROBE_TIMEOUT_SECONDS
        }
        assert json.loads(request.content) == {
            "model": "m-1",
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_completion_tokens": provider_probe_service._PROBE_MAX_COMPLETION_TOKENS,
        }
        assert resp.json() == {
            "ok": True,
            "detail": "Connected to Custom",
            "failure": None,
            "models": [],
        }

    async def test_custom_without_a_model_is_not_ok(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"{API}/providers/custom/test", json={"base_url": "https://gw.test/v1"}
        )
        assert resp.json() == {
            "ok": False,
            "detail": "No model configured for Custom",
            "failure": "not_configured",
            "models": [],
        }

    async def test_openrouter_probes_its_catalog_chat_model(self, client: AsyncClient) -> None:
        with respx.mock:
            route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/openrouter/test", json={"api_key": SECRET_KEY}
            )
        assert json.loads(route.calls.last.request.content)["model"] == (
            LLM_MODEL_PROFILES[LLMProviderName.OPENROUTER].chat
        )
        assert resp.json()["ok"] is True

    async def test_openai_key_without_model_read_scope_passes(self, client: AsyncClient) -> None:
        """Regression: a restricted key 403s on /v1/models yet runs chat completions."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://api.openai.com/v1/models").mock(
                return_value=httpx.Response(403, json={"error": "Missing scopes: api.model.read."})
            )
            chat = mock.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert json.loads(chat.calls.last.request.content)["model"] == (
            LLM_MODEL_PROFILES[LLMProviderName.OPENAI].chat
        )
        assert resp.json() == {
            "ok": True,
            "detail": "Connected to OpenAI",
            "failure": None,
            "models": [],
        }

    async def test_a_rejected_key_reads_the_providers_reason_without_the_key(
        self, client: AsyncClient
    ) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(
                    401,
                    json={
                        "error": {
                            "message": f"Incorrect API key provided: {SECRET_KEY}.",
                            "code": "invalid_api_key",
                        }
                    },
                )
            )
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert resp.json()["detail"] == (
            "OpenAI rejected the key: Incorrect API key provided: [redacted]."
        )

    async def test_a_scope_error_names_the_missing_scope(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": "Missing scopes: model.request."})
            )
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert resp.json() == {
            "ok": False,
            "detail": "OpenAI rejected the key: Missing scopes: model.request.",
            "failure": "auth_rejected",
            "models": [],
        }

    @pytest.mark.parametrize(
        ("status", "failure"),
        [(401, "auth_rejected"), (403, "auth_rejected"), (429, "rate_limited"), (500, "refused")],
    )
    async def test_a_failed_probe_names_why_by_code(
        self, client: AsyncClient, status: int, failure: str
    ) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(status, json={"error": {"message": "Nope"}})
            )
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert resp.json()["failure"] == failure

    @pytest.mark.parametrize(
        ("error", "failure"),
        [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("refused"), "unreachable")],
    )
    async def test_a_probe_that_never_answers_names_why_by_code(
        self, client: AsyncClient, error: httpx.HTTPError, failure: str
    ) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=error)
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert resp.json()["ok"] is False
        assert resp.json()["failure"] == failure

    async def test_a_passing_probe_has_no_failure(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert resp.json()["failure"] is None

    async def test_stored_key_never_sent_to_caller_supplied_base_url(
        self, client: AsyncClient
    ) -> None:
        """Hit the stored endpoint with the stored key, never the attacker URL."""
        await provider_service.upsert(
            "custom",
            ProviderConfig(api_key=STORED_KEY, base_url="https://good.test/v1", model="m-1"),
        )
        with respx.mock(assert_all_called=False) as mock:
            good = mock.post("https://good.test/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            evil = mock.route(host="evil.example").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/custom/test", json={"base_url": EVIL_BASE_URL}
            )
        assert evil.called is False
        request = good.calls.last.request
        assert request.url.host == "good.test"
        assert request.headers["Authorization"] == f"Bearer {STORED_KEY}"
        assert resp.json()["ok"] is True

    async def test_openrouter_stored_key_goes_to_canonical_url_not_evil(
        self, client: AsyncClient
    ) -> None:
        """Use the canonical chat URL with a stored key; a body base_url is never honored."""
        await provider_service.upsert("openrouter", ProviderConfig(api_key=STORED_KEY))
        with respx.mock(assert_all_called=False) as mock:
            canonical = mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            evil = mock.route(host="evil.example").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/openrouter/test", json={"base_url": EVIL_BASE_URL}
            )
        assert evil.called is False
        assert canonical.calls.last.request.headers["Authorization"] == f"Bearer {STORED_KEY}"
        assert resp.json()["ok"] is True

    async def test_first_time_validation_honors_body_when_nothing_stored(
        self, client: AsyncClient
    ) -> None:
        """Honor body base_url plus key only for first-time validation; nothing stored yet."""
        with respx.mock:
            route = respx.post("https://fresh.test/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": "https://fresh.test/v1", "api_key": "body-key", "model": "m"},
            )
        request = route.calls.last.request
        assert request.url.host == "fresh.test"
        assert request.headers["Authorization"] == "Bearer body-key"
        assert resp.json()["ok"] is True

    async def test_gemini_lists_and_strips_model_prefix(self, client: AsyncClient) -> None:
        with respx.mock:
            route = respx.get(
                "https://generativelanguage.googleapis.com/v1beta/models", params={"key": "g-key"}
            ).mock(
                return_value=httpx.Response(
                    200, json={"models": [{"name": "models/gemini-b"}, {"name": "models/gemini-a"}]}
                )
            )
            resp = await client.post(f"{API}/providers/gemini/test", json={"api_key": "g-key"})
        assert route.called
        body = resp.json()
        assert body["ok"] is True
        assert body["models"] == ["gemini-a", "gemini-b"]

    async def test_ollama_reads_tags_names(self, client: AsyncClient) -> None:
        with respx.mock:
            route = respx.get("http://localhost:11434/api/tags").mock(
                return_value=httpx.Response(
                    200, json={"models": [{"name": "llama3.2:latest"}, {"name": "qwen3"}]}
                )
            )
            resp = await client.post(
                f"{API}/providers/ollama/test", json={"base_url": "http://localhost:11434"}
            )
        assert route.called
        body = resp.json()
        assert body["ok"] is True
        assert body["models"] == ["llama3.2:latest", "qwen3"]

    async def test_stored_config_used_exclusively_when_present(self, client: AsyncClient) -> None:
        """Use stored base_url plus key exclusively; caller base_url never pairs with a held key."""
        await provider_service.upsert(
            "custom",
            ProviderConfig(api_key=STORED_KEY, base_url="https://old.test/v1", model="m-1"),
        )
        with respx.mock:
            route = respx.post("https://old.test/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": EVIL_BASE_URL, "api_key": "body-key", "model": "body-model"},
            )
        request = route.calls.last.request
        assert request.url.host == "old.test"
        assert request.headers["Authorization"] == f"Bearer {STORED_KEY}"
        assert json.loads(request.content)["model"] == "m-1"

    async def test_http_error_reports_not_ok(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.post("https://gw.test/v1/chat/completions").mock(
                return_value=httpx.Response(500, text="upstream down")
            )
            resp = await client.post(f"{API}/providers/custom/test", json={**CUSTOM_PROBE_BODY})
        assert resp.json() == {
            "ok": False,
            "detail": "Custom refused the test request: HTTP 500",
            "failure": "refused",
            "models": [],
        }

    async def test_unreachable_host_reports_not_ok(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.post("https://dead.test/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("boom")
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": "https://dead.test/v1", "model": "m"},
            )
        assert resp.json() == {
            "ok": False,
            "detail": "Could not reach custom: ConnectError",
            "failure": "unreachable",
            "models": [],
        }

    async def test_no_base_url_configured_is_not_ok(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/providers/custom/test", json={})
        body = resp.json()
        assert body["ok"] is False
        assert body["models"] == []

    async def test_a_preset_fills_the_endpoint_and_model_before_anything_is_saved(
        self, client: AsyncClient
    ) -> None:
        with respx.mock:
            route = respx.post("https://opencode.ai/zen/go/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/custom/test", json={"preset": "opencode", "api_key": "k"}
            )
        assert json.loads(route.calls.last.request.content)["model"] == "deepseek-v4-flash"
        assert resp.json()["ok"] is True

    async def test_a_trailing_slash_on_the_base_url_is_not_doubled(
        self, client: AsyncClient
    ) -> None:
        with respx.mock:
            route = respx.post("https://gw.test/proxyX/chat/completions").mock(
                return_value=httpx.Response(200, json=CHAT_COMPLETION)
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": "https://gw.test/proxyX/", "model": "m"},
            )
        assert route.called
        assert resp.json()["ok"] is True

    async def test_a_canonical_provider_without_a_key_is_not_ok(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/providers/openai/test", json={})
        assert resp.json() == {
            "ok": False,
            "detail": "No OpenAI API key configured",
            "failure": "not_configured",
            "models": [],
        }

    async def test_any_key_shaped_token_in_the_reason_is_redacted(
        self, client: AsyncClient
    ) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(
                    401, json={"error": {"message": "Key sk-proj-ab12****cd34 was revoked."}}
                )
            )
            resp = await client.post(f"{API}/providers/openai/test", json={"api_key": SECRET_KEY})
        assert resp.json()["detail"] == "OpenAI rejected the key: Key [redacted] was revoked."

    async def test_gemini_reports_its_connection(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
                return_value=httpx.Response(200, json={})
            )
            resp = await client.post(f"{API}/providers/gemini/test", json={"api_key": "g-key"})
        assert resp.json() == {
            "ok": True,
            "detail": "Connected to Google Gemini",
            "failure": None,
            "models": [],
        }

    async def test_gemini_without_a_key_is_not_ok(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/providers/gemini/test", json={})
        assert resp.json() == {
            "ok": False,
            "detail": "No Gemini API key configured",
            "failure": "not_configured",
            "models": [],
        }

    async def test_gemini_refusing_the_key_is_not_ok(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
                return_value=httpx.Response(400, json={})
            )
            resp = await client.post(f"{API}/providers/gemini/test", json={"api_key": "g-key"})
        assert resp.json() == {
            "ok": False,
            "detail": "Gemini returned HTTP 400",
            "failure": "refused",
            "models": [],
        }

    async def test_ollama_reports_its_connection_past_a_trailing_slash(
        self, client: AsyncClient
    ) -> None:
        with respx.mock:
            respx.get("http://localhost:11434/ollamaX/api/tags").mock(
                return_value=httpx.Response(200, json={})
            )
            resp = await client.post(
                f"{API}/providers/ollama/test", json={"base_url": "http://localhost:11434/ollamaX/"}
            )
        assert resp.json() == {
            "ok": True,
            "detail": "Connected to Ollama",
            "failure": None,
            "models": [],
        }

    async def test_ollama_without_a_base_url_is_not_ok(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/providers/ollama/test", json={})
        assert resp.json() == {
            "ok": False,
            "detail": "No Ollama base URL configured",
            "failure": "not_configured",
            "models": [],
        }

    async def test_ollama_answering_an_error_is_not_ok(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.get("http://localhost:11434/api/tags").mock(
                return_value=httpx.Response(404, json={})
            )
            resp = await client.post(
                f"{API}/providers/ollama/test", json={"base_url": "http://localhost:11434"}
            )
        assert resp.json() == {
            "ok": False,
            "detail": "Ollama returned HTTP 404",
            "failure": "refused",
            "models": [],
        }

    @pytest.mark.parametrize(
        "provider", sorted(set(CredentialProviderName) - set(LLM_PROVIDER_PRIORITY))
    )
    async def test_only_chat_providers_can_be_probed(
        self, client: AsyncClient, provider: str
    ) -> None:
        resp = await client.post(f"{API}/providers/{provider}/test", json={"api_key": "k"})
        assert resp.status_code == 422
        assert resp.json()["message"] == (
            f"Only chat providers can be connection-tested, not {provider}"
        )

    async def test_detail_never_leaks_the_api_key(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.post("https://gw.test/v1/chat/completions").mock(
                return_value=httpx.Response(500, json={"error": {"message": SECRET_KEY}})
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={**CUSTOM_PROBE_BODY, "api_key": SECRET_KEY},
            )
        assert SECRET_KEY not in resp.text


class TestSsrfGuard:
    """Resolve every hostname then validate every answer; string checks alone missed shorthands."""

    @pytest.fixture(autouse=True)
    def _public_only_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Apply production's policy: the routes 403 in production, so the guard is driven under it here."""
        monkeypatch.setattr(
            provider_setup_service, "allows_private_endpoint", lambda provider: provider == "ollama"
        )

    @pytest.mark.parametrize("provider", ["custom", "openrouter"])
    def test_production_keeps_non_ollama_endpoints_public(
        self, monkeypatch: pytest.MonkeyPatch, provider: str
    ) -> None:
        monkeypatch.undo()
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")

        assert provider_setup_service.allows_private_endpoint(provider) is False
        assert provider_setup_service.allows_private_endpoint("ollama") is True

    async def test_decimal_ip_shorthand_resolving_private_is_rejected(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reject a decimal IP shorthand that resolution exposes as loopback."""
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning("127.0.0.1"))
        resp = await client.post(
            f"{API}/providers/custom/test", json={"base_url": "http://2130706433/"}
        )
        assert resp.status_code == 422

    async def test_name_resolving_loopback_is_rejected_on_probe(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nip.io-style bypass: public-looking name, private answer."""
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning("127.0.0.1"))
        resp = await client.post(
            f"{API}/providers/custom/test",
            json={"base_url": "https://metadata.example.nip.io/v1"},
        )
        assert resp.status_code == 422

    async def test_one_private_answer_among_several_is_rejected(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Require every resolved address to be public; one internal answer rejects."""
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning(STUB_PUBLIC_IP, "10.0.0.5"))
        resp = await client.post(
            f"{API}/providers/custom/test", json={"base_url": "https://mixed.test/v1"}
        )
        assert resp.status_code == 422

    async def test_unresolvable_host_fails_closed(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unresolvable(
            _host: str, _port: int | None, *args: int, **kwargs: int
        ) -> GetAddrInfoResult:
            raise socket.gaierror("nodename nor servname provided")

        monkeypatch.setattr(socket, "getaddrinfo", unresolvable)
        resp = await client.post(
            f"{API}/providers/custom/test", json={"base_url": "https://blackhole.test/v1"}
        )
        assert resp.status_code == 422

    async def test_literal_private_ip_is_fast_failed_without_resolving(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(_host: str, _port: int | None, *args: int, **kwargs: int) -> GetAddrInfoResult:
            raise AssertionError("resolver must not be reached for literal private IPs")

        monkeypatch.setattr(socket, "getaddrinfo", explode)
        resp = await client.post(
            f"{API}/providers/custom/test", json={"base_url": "http://127.0.0.1:9200"}
        )
        assert resp.status_code == 422

    async def test_put_rejects_private_base_url_and_stores_nothing(
        self, client: AsyncClient
    ) -> None:
        resp = await client.put(
            f"{API}/providers/custom",
            json={"api_key": SECRET_KEY, "base_url": "http://192.168.1.10/v1"},
        )
        assert resp.status_code == 422
        assert provider_service.configs == {}

    async def test_put_allows_local_ollama_endpoint(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Allow private addresses for the local LLM lane; the provider skips the public-IP check."""
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning("127.0.0.1"))
        resp = await client.put(
            f"{API}/providers/ollama",
            json={"base_url": "http://localhost:11434", "model": "llama3.2"},
        )
        assert resp.status_code == 200
        assert provider_service.configs["ollama"].base_url == "http://localhost:11434"

    async def test_probe_allows_a_local_ollama_endpoint(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning("127.0.0.1"))
        with respx.mock:
            respx.get("http://localhost:11434/api/tags").mock(
                return_value=httpx.Response(200, json={"models": [{"name": "qwen3"}]})
            )
            resp = await client.post(
                f"{API}/providers/ollama/test", json={"base_url": "http://localhost:11434"}
            )
        assert resp.json()["ok"] is True

    async def test_put_rejects_name_resolving_private(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning("192.168.0.2"))
        resp = await client.put(
            f"{API}/providers/custom",
            json={"api_key": SECRET_KEY, "base_url": "https://lan.example.nip.io/v1"},
        )
        assert resp.status_code == 422

    async def test_probe_refuses_legacy_stored_private_endpoint(self, client: AsyncClient) -> None:
        """Refuse legacy private-endpoint configs at probe time too, not just save time."""
        await provider_service.upsert(
            "custom",
            ProviderConfig(api_key=STORED_KEY, base_url="http://169.254.169.254/latest"),
        )
        with respx.mock(assert_all_called=False) as mock:
            metadata = mock.route(host="169.254.169.254").mock(
                return_value=httpx.Response(200, json={})
            )
            resp = await client.post(f"{API}/providers/custom/test", json={})
        assert resp.status_code == 422
        assert metadata.called is False


class TestPrivateEndpointsOffProduction:
    """A home-lab vLLM or LM Studio on the LAN is a normal self-host setup; metadata stays refused."""

    @pytest.fixture(autouse=True)
    def _selfhost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")

    async def test_put_allows_a_lan_custom_endpoint(self, client: AsyncClient) -> None:
        resp = await client.put(
            f"{API}/providers/custom",
            json={"api_key": SECRET_KEY, "base_url": "http://192.168.1.10:8000/v1", "model": "m"},
        )
        assert resp.status_code == 200
        assert provider_service.configs["custom"].base_url == "http://192.168.1.10:8000/v1"

    @pytest.mark.parametrize("provider", ["custom", "ollama"])
    @pytest.mark.parametrize("host", ["169.254.10.10", "[fe80::1]"])
    async def test_link_local_stays_refused(
        self, client: AsyncClient, provider: str, host: str
    ) -> None:
        resp = await client.put(
            f"{API}/providers/{provider}",
            json={"api_key": SECRET_KEY, "base_url": f"http://{host}/v1", "model": "m"},
        )
        assert resp.status_code == 422
        assert provider not in provider_service.configs


class TestInstanceAdminGuard:
    """Every mutating and probing setup route is bound to the single instance admin."""

    async def test_put_denied_for_non_admin(self, nonadmin_client: AsyncClient) -> None:
        resp = await nonadmin_client.put(
            f"{API}/providers/openrouter", json={"api_key": "attacker-key"}
        )
        assert resp.status_code == 403
        assert resp.json()["message"] == "not_instance_admin"
        assert provider_service.configs == {}

    async def test_delete_denied_for_non_admin(self, nonadmin_client: AsyncClient) -> None:
        await provider_service.upsert("openrouter", ProviderConfig(api_key=STORED_KEY))
        resp = await nonadmin_client.delete(f"{API}/providers/openrouter")
        assert resp.status_code == 403
        assert provider_service.configs["openrouter"].api_key == STORED_KEY

    async def test_probe_denied_for_non_admin_and_never_fires(
        self, nonadmin_client: AsyncClient
    ) -> None:
        with respx.mock:
            evil = respx.route(host="evil.example").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            resp = await nonadmin_client.post(
                f"{API}/providers/custom/test", json={"base_url": EVIL_BASE_URL}
            )
        assert resp.status_code == 403
        assert evil.called is False

    async def test_list_providers_denied_for_non_admin(self, nonadmin_client: AsyncClient) -> None:
        await provider_service.upsert(
            "custom", ProviderConfig(api_key=STORED_KEY, base_url="https://internal.test/v1")
        )
        resp = await nonadmin_client.get(f"{API}/providers")
        assert resp.status_code == 403
        assert "internal.test" not in resp.text

    async def test_admin_allowed_on_every_guarded_route(self, client: AsyncClient) -> None:
        put = await client.put(f"{API}/providers/ollama", json={"base_url": "http://o"})
        assert put.status_code == 200
        assert (await client.get(f"{API}/providers")).status_code == 200
        probe = await client.post(f"{API}/providers/ollama/test", json={"api_key": "k"})
        assert probe.status_code == 200

    async def test_guard_denies_without_local_auth(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refuse the router without local auth, even for the credential owner."""
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        resp = await client.put(f"{API}/providers/gemini", json={"api_key": "g"})
        assert resp.status_code == 403
        assert resp.json()["message"] == "not_instance_admin"
        assert provider_service.configs == {}

    async def test_admin_allowed_in_development_with_local_auth(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the guard demanded ENV selfhost, locking dev+local contributors out."""
        monkeypatch.setattr(settings, "ENV", "development")
        resp = await client.put(f"{API}/providers/ollama", json={"base_url": "http://o"})
        assert resp.status_code == 200

    async def test_an_account_without_a_role_is_not_admin(self) -> None:
        """A user row predating roles (or a hosted user) administers nothing — fail closed."""
        async with _client(authenticated=True, role=None) as roleless:
            resp = await roleless.get(f"{API}/providers")
        assert resp.status_code == 403


class TestAuthContract:
    @pytest.mark.parametrize(
        "path",
        [
            "/providers/{provider}",
            "/providers/{provider}/test",
        ],
    )
    async def test_protected_routes_depend_on_get_current_user(self, path: str) -> None:
        assert _requires(path, get_current_user)

    @pytest.mark.parametrize(
        "path",
        [
            "/providers",
            "/providers/{provider}",
            "/providers/{provider}/test",
        ],
    )
    async def test_guarded_routes_depend_on_instance_admin(self, path: str) -> None:
        assert _requires(path, require_instance_admin)

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("GET", "/providers", None),
            ("PUT", "/providers/gemini", {"api_key": "g"}),
            ("DELETE", "/providers/gemini", None),
            ("POST", "/providers/ollama/test", {}),
        ],
    )
    async def test_admin_routes_stamp_the_caller_on_the_wide_event(
        self, client: AsyncClient, method: str, path: str, body: dict[str, str] | None
    ) -> None:
        async with captured_wide_event() as event:
            resp = await client.request(method, f"{API}{path}", json=body)

        assert resp.status_code == 200
        assert event["user"] == {"id": FAKE_USER_ID}

    async def test_requests_carry_the_caller_identity(self, client: AsyncClient) -> None:
        await client.put(f"{API}/providers/gemini", json={"api_key": "g"})
        assert provider_service.invalidated == ["gemini"]
