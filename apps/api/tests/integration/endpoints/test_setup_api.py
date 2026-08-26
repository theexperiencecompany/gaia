"""Setup API integration tests (A4 contract: .agents/plans/selfhost-contracts.md).

Drives the real router over ASGITransport with the parallel-agent seams
(provider credentials service, instance/local repositories) bound to the
contract fakes from conftest.py, provider probes mocked via respx, and DNS
resolution stubbed to public answers (the SSRF guard resolves hostnames itself,
outside respx's transport mock).
"""

from collections.abc import Callable, Iterator
import ipaddress
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
from app.config.settings import settings
from app.constants.llm import OPENROUTER_MODELS_URL
from app.constants.providers import CREDENTIAL_PROVIDERS
from shared.py.wide_events import log
from tests.integration.endpoints.conftest import (
    API,
    FAKE_USER_ID,
    instance_settings_repo,
    local_credentials_repo,
    provider_service,
    seed_state,
)

SECRET_KEY = "sk-live-supersecret-9876"
STORED_KEY = "sk-stored"
EVIL_BASE_URL = "https://evil.example"

# Public IP the DNS stub answers with for every hostname (the guard's
# ``is_global`` check must pass it).
STUB_PUBLIC_IP = "8.8.8.8"

# One ``socket.getaddrinfo`` record: (family, type, proto, canonname, sockaddr).
GetAddrInfoResult = list[tuple[int, int, int, str, tuple[str, int]]]


def _resolver_returning(*addresses: str) -> Callable[..., GetAddrInfoResult]:
    """Build a ``socket.getaddrinfo`` stand-in answering every host with ``addresses``."""

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
    """The dependency graph of one route: the handler itself plus every nested
    sub-dependency (per-param Depends live on ``dependant.dependencies``, so a
    flat scan misses guards wrapped inside another dependency)."""
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk_dependants(sub)


def _requires(path: str, call: Callable[..., Any]) -> bool:
    """True when EVERY route registered under ``path`` requires ``call``
    anywhere in its dependency graph."""
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
            "needs_setup",
            "billing_enabled",
            "providers",
            "plans_seeded",
        }
        assert set(body["providers"]) == {
            "openrouter",
            "gemini",
            "ollama",
            "custom",
            "tavily",
            "composio",
            "e2b",
            "openai",
            "resend",
            "cloudinary",
            "google_oauth",
            "firecrawl",
        }
        assert all(set(v) == {"configured"} for v in body["providers"].values())

    async def test_status_has_no_auth_dependency(self) -> None:
        assert not _requires("/status", get_current_user)

    async def test_status_is_not_admin_gated(self) -> None:
        assert not _requires("/status", require_instance_admin)

    async def test_status_stamps_the_request_wide_event(self, anon_client: AsyncClient) -> None:
        """Route-contract step 1: the public status probe opens its wide event
        with an operation tag (it has no user to stamp)."""
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
        assert resp.json()["billing_enabled"] is False

    async def test_billing_enabled_outside_selfhost(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "production")
        resp = await client.get(f"{API}/status")
        assert resp.json()["billing_enabled"] is True

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
            provider_service.configs["openrouter"] = {
                "api_key": SECRET_KEY,
                "base_url": None,
                "model": None,
                "preset": None,
            }
        resp = await client.get(f"{API}/status")
        assert resp.json()["needs_setup"] is expected

    async def test_tavily_alone_does_not_satisfy_llm_requirement(self, client: AsyncClient) -> None:
        provider_service.configs["tavily"] = {
            "api_key": "tvly-key",
            "base_url": None,
            "model": None,
            "preset": None,
        }
        body = (await client.get(f"{API}/status")).json()
        assert body["providers"]["tavily"]["configured"] is True
        assert body["needs_setup"] is True

    async def test_env_fallback_counts_as_configured(self, client: AsyncClient) -> None:
        # resolve() returns a config sourced from env fallbacks too — either way
        # the provider counts as configured for needs_setup.
        provider_service.configs["gemini"] = {
            "api_key": "env-key",
            "base_url": None,
            "model": None,
            "preset": None,
        }
        body = (await client.get(f"{API}/status")).json()
        assert body["providers"]["gemini"] == {"configured": True}

    async def test_seed_flags_surfaced(self, client: AsyncClient) -> None:
        body = (await client.get(f"{API}/status")).json()
        assert body["plans_seeded"] is True

        seed_state.plans_seeded = False
        body = (await client.get(f"{API}/status")).json()
        assert body["plans_seeded"] is False


class TestProviderCatalog:
    """GET /catalog serves the Python provider catalog so the web wizard and
    Settings render dynamically — adding a provider stays a Python-only change."""

    async def test_catalog_lists_every_provider_in_display_order(
        self, anon_client: AsyncClient
    ) -> None:
        resp = await anon_client.get(f"{API}/catalog")
        assert resp.status_code == 200
        body = resp.json()
        assert list(body["providers"]) == list(CREDENTIAL_PROVIDERS)

    async def test_catalog_entries_carry_display_metadata_only(
        self, anon_client: AsyncClient
    ) -> None:
        body = (await anon_client.get(f"{API}/catalog")).json()
        for spec in body["providers"].values():
            assert set(spec) == {
                "label",
                "base_url",
                "default_model",
                "favicon_domain",
                "needs_base_url",
            }
        assert body["providers"]["openrouter"]["label"] == "OpenRouter"
        assert body["providers"]["ollama"]["default_model"] == "llama3.2"

    async def test_custom_lane_presets_are_partitioned_out_of_providers(
        self, anon_client: AsyncClient
    ) -> None:
        """opencode/nous are preset gateways inside the custom card, NOT
        providers — they must never render as catalog cards."""
        body = (await anon_client.get(f"{API}/catalog")).json()
        assert set(body["custom_presets"]) == {"opencode", "nous"}
        assert "opencode" not in body["providers"]
        assert body["custom_presets"]["opencode"]["base_url"] == "https://opencode.ai/zen/go/v1"

    async def test_llm_keys_mirror_the_needs_setup_rule(self, anon_client: AsyncClient) -> None:
        body = (await anon_client.get(f"{API}/catalog")).json()
        assert body["llm_provider_keys"] == ["openrouter", "gemini", "ollama", "custom"]

    async def test_catalog_is_public_without_auth(self, anon_client: AsyncClient) -> None:
        # The wizard renders cards before an admin session exists; the catalog
        # carries display metadata only.
        assert (await anon_client.get(f"{API}/catalog")).status_code == 200

    async def test_catalog_has_no_auth_dependency(self) -> None:
        assert not _requires("/catalog", get_current_user)
        assert not _requires("/catalog", require_instance_admin)


class TestProvidersMaskedView:
    async def test_masked_output_never_contains_full_key(self, client: AsyncClient) -> None:
        await provider_service.upsert("openrouter", api_key=SECRET_KEY)
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
        }

    async def test_unconfigured_provider_is_none_everywhere(self, client: AsyncClient) -> None:
        entry = (await client.get(f"{API}/providers")).json()["providers"]["custom"]
        assert entry["configured"] is False
        assert entry["api_key_hint"] is None


class TestUpsertProvider:
    async def test_preset_fills_opencode_endpoint_and_model(self, client: AsyncClient) -> None:
        resp = await client.put(
            f"{API}/providers/custom",
            json={"preset": "opencode", "api_key": SECRET_KEY},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert provider_service.configs["custom"] == {
            "api_key": SECRET_KEY,
            "base_url": "https://opencode.ai/zen/go/v1",
            "model": "deepseek-v4-flash",
            "preset": "opencode",
        }

    async def test_explicit_base_url_wins_over_preset(self, client: AsyncClient) -> None:
        await client.put(
            f"{API}/providers/custom",
            json={"preset": "opencode", "api_key": "k", "base_url": "https://proxy.internal/v1"},
        )
        assert provider_service.configs["custom"]["base_url"] == "https://proxy.internal/v1"

    async def test_cache_invalidated_after_upsert(self, client: AsyncClient) -> None:
        await client.put(f"{API}/providers/gemini", json={"api_key": "g-key"})
        assert provider_service.invalidated == ["gemini"]

    async def test_unknown_provider_rejected(self, client: AsyncClient) -> None:
        resp = await client.put(f"{API}/providers/anthropic", json={"api_key": "k"})
        assert resp.status_code == 404
        assert provider_service.configs == {}

    async def test_put_requires_auth_dependency(self) -> None:
        assert _requires("/providers/{provider}", get_current_user)


class TestDeleteProvider:
    async def test_delete_removes_credential_and_invalidates(self, client: AsyncClient) -> None:
        await provider_service.upsert("ollama", base_url="http://localhost:11434")
        resp = await client.delete(f"{API}/providers/ollama")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert "ollama" not in provider_service.configs
        assert provider_service.invalidated == ["ollama"]

    async def test_unknown_provider_rejected(self, client: AsyncClient) -> None:
        resp = await client.delete(f"{API}/providers/bogus")
        assert resp.status_code == 404


class TestProviderProbe:
    async def test_openai_wire_lists_sorted_models(self, client: AsyncClient) -> None:
        with respx.mock:
            route = respx.get("https://gw.test/v1/models").mock(
                return_value=httpx.Response(
                    200, json={"data": [{"id": "zeta-model"}, {"id": "deepseek-v4-flash"}]}
                )
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": "https://gw.test/v1", "api_key": SECRET_KEY},
            )
        assert route.called
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {SECRET_KEY}"
        body = resp.json()
        assert body["ok"] is True
        assert body["models"] == ["deepseek-v4-flash", "zeta-model"]

    async def test_openrouter_uses_canonical_models_url(self, client: AsyncClient) -> None:
        with respx.mock:
            route = respx.get(OPENROUTER_MODELS_URL).mock(
                return_value=httpx.Response(200, json={"data": [{"id": "m"}]})
            )
            resp = await client.post(
                f"{API}/providers/openrouter/test", json={"api_key": SECRET_KEY}
            )
        assert route.called
        assert resp.json()["ok"] is True

    async def test_stored_key_never_sent_to_caller_supplied_base_url(
        self, client: AsyncClient
    ) -> None:
        """H1 exfil scenario: stored credential + caller-supplied base_url.
        The probe must hit the STORED endpoint with the STORED key and never
        contact the attacker URL."""
        await provider_service.upsert("custom", api_key=STORED_KEY, base_url="https://good.test/v1")
        with respx.mock(assert_all_called=False) as mock:
            good = mock.get("https://good.test/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            evil = mock.route(host="evil.example").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            resp = await client.post(
                f"{API}/providers/custom/test", json={"base_url": EVIL_BASE_URL}
            )
        assert evil.called is False
        assert good.called
        request = good.calls.last.request
        assert request.url.host == "good.test"
        assert request.headers["Authorization"] == f"Bearer {STORED_KEY}"
        assert resp.json()["ok"] is True

    async def test_openrouter_stored_key_goes_to_canonical_url_not_evil(
        self, client: AsyncClient
    ) -> None:
        """Same binding for openrouter: its canonical models URL is used with
        the stored key; a body base_url is never honored once a credential is
        stored."""
        await provider_service.upsert("openrouter", api_key=STORED_KEY)
        with respx.mock(assert_all_called=False) as mock:
            canonical = mock.get(OPENROUTER_MODELS_URL).mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            evil = mock.route(host="evil.example").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            resp = await client.post(
                f"{API}/providers/openrouter/test", json={"base_url": EVIL_BASE_URL}
            )
        assert evil.called is False
        assert canonical.called
        assert canonical.calls.last.request.headers["Authorization"] == f"Bearer {STORED_KEY}"
        assert resp.json()["ok"] is True

    async def test_first_time_validation_honors_body_when_nothing_stored(
        self, client: AsyncClient
    ) -> None:
        """Body base_url + key are honored only for first-time validation,
        before any credential is saved — there is no server-held key to mix
        them with."""
        with respx.mock:
            route = respx.get("https://fresh.test/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            resp = await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": "https://fresh.test/v1", "api_key": "body-key"},
            )
        assert route.called
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
        """H1 contract: once a credential exists, the probe uses the STORED
        base_url + key exclusively — a caller-supplied base_url must never be
        paired with a server-held key."""
        await provider_service.upsert("custom", api_key=STORED_KEY, base_url="https://old.test/v1")
        with respx.mock:
            route = respx.get("https://old.test/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            await client.post(
                f"{API}/providers/custom/test",
                json={"base_url": EVIL_BASE_URL, "api_key": "body-key"},
            )
        request = route.calls.last.request
        assert request.url.host == "old.test"
        assert request.headers["Authorization"] == f"Bearer {STORED_KEY}"

    async def test_http_error_reports_not_ok(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.get("https://gw.test/v1/models").mock(return_value=httpx.Response(401))
            resp = await client.post(
                f"{API}/providers/custom/test", json={"base_url": "https://gw.test/v1"}
            )
        body = resp.json()
        assert body["ok"] is False
        assert "401" in body["detail"]
        assert body["models"] == []

    async def test_unreachable_host_reports_not_ok(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.get("https://dead.test/v1/models").mock(side_effect=httpx.ConnectError("boom"))
            resp = await client.post(
                f"{API}/providers/custom/test", json={"base_url": "https://dead.test/v1"}
            )
        assert resp.json()["ok"] is False

    async def test_no_base_url_configured_is_not_ok(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/providers/custom/test", json={})
        body = resp.json()
        assert body["ok"] is False
        assert body["models"] == []

    async def test_tavily_cannot_be_probed(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/providers/tavily/test", json={"api_key": "tvly"})
        assert resp.status_code == 422

    async def test_detail_never_leaks_the_api_key(self, client: AsyncClient) -> None:
        with respx.mock:
            respx.get("https://gw.test/v1/models").mock(return_value=httpx.Response(500))
            resp = await client.post(
                f"{API}/providers/custom/test", json={"base_url": "https://gw.test/v1"}
            )
        assert SECRET_KEY not in resp.text


class TestSsrfGuard:
    """F3 regression locks: string-level checks alone missed decimal IP
    shorthands and DNS names resolving into private ranges. The guard now
    resolves every hostname (via ``app.utils.url_safety``) and validates EVERY
    answer before any request is sent — on the probe path and at save time.
    Resolution is stubbed per-test; no test touches real DNS."""

    async def test_decimal_ip_shorthand_resolving_private_is_rejected(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``http://2130706433/`` parses as a plain hostname string — only
        resolution exposes it as 127.0.0.1."""
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
        """EVERY resolved address must be public — a public record mixed with an
        internal one must not slip through."""
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

    async def test_put_rejects_local_ollama_endpoint(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No local-endpoint allow-list: LAN Ollama belongs in ``OLLAMA_BASE_URL``
        env config, which never passes through this API-side guard."""
        monkeypatch.setattr(socket, "getaddrinfo", _resolver_returning("127.0.0.1"))
        resp = await client.put(
            f"{API}/providers/ollama", json={"base_url": "http://localhost:11434"}
        )
        assert resp.status_code == 422
        assert provider_service.configs == {}

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
        """Defense in depth: configs saved before save-time validation existed
        are refused at probe time too — the guard is the last word before dialing."""
        await provider_service.upsert(
            "custom", api_key=STORED_KEY, base_url="http://169.254.169.254/latest"
        )
        with respx.mock(assert_all_called=False) as mock:
            metadata = mock.route(host="169.254.169.254").mock(
                return_value=httpx.Response(200, json={})
            )
            resp = await client.post(f"{API}/providers/custom/test", json={})
        assert resp.status_code == 422
        assert metadata.called is False


class TestInstanceAdminGuard:
    """H1: every mutating/probing /setup route is bound to THE instance admin.

    The admin is the owner of the single ``auth_credentials`` row; anyone else
    authenticated (or any non-selfhost ENV reaching these handlers) gets 403.
    """

    async def test_put_denied_for_non_admin(self, nonadmin_client: AsyncClient) -> None:
        resp = await nonadmin_client.put(
            f"{API}/providers/openrouter", json={"api_key": "attacker-key"}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "not_instance_admin"
        assert provider_service.configs == {}

    async def test_delete_denied_for_non_admin(self, nonadmin_client: AsyncClient) -> None:
        await provider_service.upsert("openrouter", api_key=STORED_KEY)
        resp = await nonadmin_client.delete(f"{API}/providers/openrouter")
        assert resp.status_code == 403
        assert provider_service.configs["openrouter"]["api_key"] == STORED_KEY

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
            "custom", api_key=STORED_KEY, base_url="https://internal.test/v1"
        )
        resp = await nonadmin_client.get(f"{API}/providers")
        assert resp.status_code == 403
        assert "internal.test" not in resp.text

    async def test_complete_denied_for_non_admin(self, nonadmin_client: AsyncClient) -> None:
        resp = await nonadmin_client.post(f"{API}/complete", json={"step": "providers"})
        assert resp.status_code == 403
        assert instance_settings_repo.docs == {}

    async def test_admin_allowed_on_every_guarded_route(self, client: AsyncClient) -> None:
        put = await client.put(f"{API}/providers/ollama", json={"base_url": "http://o"})
        assert put.status_code == 200
        assert (await client.get(f"{API}/providers")).status_code == 200
        probe = await client.post(f"{API}/providers/ollama/test", json={"api_key": "k"})
        assert probe.status_code == 200
        done = await client.post(f"{API}/complete", json={"step": "providers"})
        assert done.status_code == 200

    async def test_guard_denies_when_env_is_not_selfhost(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defensive layer: the router is unmounted outside selfhost, so a
        request reaching it under any other ENV is refused even for the
        credential owner."""
        monkeypatch.setattr(settings, "ENV", "production")
        resp = await client.put(f"{API}/providers/gemini", json={"api_key": "g"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "not_instance_admin"
        assert provider_service.configs == {}

    async def test_no_credential_row_means_no_admin(self, client: AsyncClient) -> None:
        """Pre-first-signup instance: nobody is admin yet — fail closed."""
        local_credentials_repo.admin_user_id = None
        resp = await client.get(f"{API}/providers")
        assert resp.status_code == 403


class TestCompleteStep:
    async def test_persists_step_into_instance_settings(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/complete", json={"step": "providers"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert instance_settings_repo.docs["setup"]["steps"] == {"providers": True}

    async def test_steps_merge_across_calls(self, client: AsyncClient) -> None:
        await client.post(f"{API}/complete", json={"step": "account"})
        await client.post(f"{API}/complete", json={"step": "providers"})
        assert instance_settings_repo.docs["setup"]["steps"] == {
            "account": True,
            "providers": True,
        }

    async def test_blank_step_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/complete", json={"step": ""})
        assert resp.status_code == 422
        assert instance_settings_repo.docs == {}


class TestAuthContract:
    @pytest.mark.parametrize(
        "path",
        [
            "/providers/{provider}",
            "/providers/{provider}/test",
            "/complete",
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
            "/complete",
        ],
    )
    async def test_guarded_routes_depend_on_instance_admin(self, path: str) -> None:
        assert _requires(path, require_instance_admin)

    async def test_requests_carry_the_caller_identity(self, client: AsyncClient) -> None:
        await client.put(f"{API}/providers/gemini", json={"api_key": "g"})
        assert provider_service.invalidated == ["gemini"]
