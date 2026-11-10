"""MCP OAuth flow: exact client_id resolution errors, scope string, DCR request and callback side effects."""

from collections.abc import Iterator
from datetime import UTC, datetime
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch
from urllib.parse import parse_qs

import httpx
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
import pytest
import respx
import time_machine

from app.constants.log_tags import LogTag
from app.constants.mcp import (
    GAIA_OAUTH_LOGO_PATH,
    GAIA_OAUTH_PRIVACY_PATH,
    GAIA_OAUTH_TOS_PATH,
)
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp import mcp_oauth
from app.services.mcp.mcp_errors import DCRNotSupportedError
from app.services.mcp.mcp_oauth import (
    _build_oauth_scope_string,
    _obtain_auth_client_id,
    _register_client,
    build_oauth_auth_url,
    handle_oauth_callback,
)
from app.services.mcp.mcp_token_store import MCPTokenStore
from shared.py.wide_events import log

AUTH = "https://auth.mcp.example"
INTEGRATION_ID = "custom_oauth"
RESOURCE = "https://mcp.example/mcp"
REDIRECT_URI = "https://gaia/callback"
REGISTRATION_ENDPOINT = f"{AUTH}/oauth/register"
TOKEN_ENDPOINT = f"{AUTH}/token"


def _metadata(
    *,
    scopes: list[str] | None = None,
    registration: bool = True,
    token_endpoint: str = TOKEN_ENDPOINT,
) -> OAuthMetadata:
    body: dict[str, object] = {
        "issuer": AUTH,
        "authorization_endpoint": f"{AUTH}/authorize",
        "token_endpoint": token_endpoint,
        "code_challenge_methods_supported": ["S256"],
    }
    if registration:
        body["registration_endpoint"] = REGISTRATION_ENDPOINT
    if scopes is not None:
        body["scopes_supported"] = scopes
    return OAuthMetadata.model_validate(body)


def _prm(scopes: list[str]) -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata.model_validate(
        {"resource": RESOURCE, "authorization_servers": [AUTH], "scopes_supported": scopes}
    )


def _discovery(
    *,
    metadata: OAuthMetadata | None = None,
    initial_scope: str | None = None,
    prm: ProtectedResourceMetadata | None = None,
) -> OAuthDiscovery:
    return OAuthDiscovery(
        as_metadata=metadata or _metadata(),
        resource=RESOURCE,
        initial_scope=initial_scope,
        discovery_method="direct",
        prm=prm,
    )


def _config(**fields: object) -> MCPConfig:
    return MCPConfig.model_validate({"server_url": RESOURCE, "requires_auth": True, **fields})


def _token_store() -> AsyncMock:
    store = AsyncMock(spec=MCPTokenStore)
    store.user_id = "user-1"
    return store


@pytest.fixture
def http_client() -> Iterator[None]:
    with patch.object(mcp_oauth, "mcp_http_client", lambda: httpx.AsyncClient()):
        yield


@pytest.mark.unit
class TestObtainAuthClientId:
    async def test_stored_dcr_client_is_looked_up_by_integration(self) -> None:
        store = _token_store()
        store.get_dcr_client.return_value = {"client_id": "stored-id"}

        client_id = await _obtain_auth_client_id(
            store, INTEGRATION_ID, _config(), _discovery(), REDIRECT_URI
        )

        assert client_id == "stored-id"
        store.get_dcr_client.assert_awaited_once_with(INTEGRATION_ID)

    async def test_no_source_of_client_id_explains_every_attempt(self) -> None:
        store = _token_store()
        store.get_dcr_client.return_value = None

        with pytest.raises(ValueError) as raised:
            await _obtain_auth_client_id(
                store,
                INTEGRATION_ID,
                _config(),
                _discovery(metadata=_metadata(registration=False)),
                REDIRECT_URI,
            )

        assert str(raised.value) == (
            f"Could not obtain client_id for {INTEGRATION_ID}. "
            "Tried: (1) pre-configured credentials, (2) stored DCR client, "
            "(3) client metadata document, (4) new DCR registration. "
            "The authorization server may require manual client pre-registration."
        )


@pytest.mark.unit
class TestBuildOauthScopeString:
    def _scope(
        self,
        discovery: OAuthDiscovery,
        mcp_config: MCPConfig | None = None,
        excluded: set[str] | None = None,
    ) -> str:
        return _build_oauth_scope_string(
            INTEGRATION_ID, mcp_config or _config(), discovery, excluded
        )

    def test_challenge_scope_wins_over_resource_and_server_scopes(self) -> None:
        discovery = _discovery(
            metadata=_metadata(scopes=["server"]), initial_scope="challenge", prm=_prm(["prm"])
        )

        assert self._scope(discovery) == "challenge"

    def test_resource_scopes_win_over_server_scopes(self) -> None:
        discovery = _discovery(metadata=_metadata(scopes=["server"]), prm=_prm(["prm1", "prm2"]))

        assert self._scope(discovery) == "prm1 prm2"

    def test_server_scopes_are_the_last_source(self) -> None:
        discovery = _discovery(metadata=_metadata(scopes=["server1", "server2"]))

        assert self._scope(discovery) == "server1 server2"

    def test_no_scope_anywhere_is_empty(self) -> None:
        assert self._scope(_discovery()) == ""

    def test_configured_scopes_apply_when_the_challenge_is_silent(self) -> None:
        config = _config(oauth_scopes=["cfg1", "cfg2"])

        assert self._scope(_discovery(metadata=_metadata(scopes=["server"])), config) == "cfg1 cfg2"

    def test_offline_access_is_added_when_advertised_and_missing(self) -> None:
        discovery = _discovery(metadata=_metadata(scopes=["offline_access"]), initial_scope="read")

        assert self._scope(discovery) == "read offline_access"

    def test_offline_access_is_not_duplicated(self) -> None:
        discovery = _discovery(
            metadata=_metadata(scopes=["offline_access"]), initial_scope="offline_access read"
        )

        assert self._scope(discovery) == "offline_access read"

    def test_offline_access_is_not_added_when_not_advertised(self) -> None:
        discovery = _discovery(metadata=_metadata(scopes=["other"]), initial_scope="read")

        assert self._scope(discovery) == "read"

    def test_rejected_scopes_are_dropped(self) -> None:
        discovery = _discovery(initial_scope="read bad write")

        assert self._scope(discovery, excluded={"bad"}) == "read write"

    def test_excluding_every_scope_leaves_none(self) -> None:
        discovery = _discovery(initial_scope="bad")

        assert self._scope(discovery, excluded={"bad"}) == ""

    def test_unrelated_exclusions_leave_scopes_untouched(self) -> None:
        discovery = _discovery(initial_scope="read write")

        assert self._scope(discovery, excluded={"other"}) == "read write"


@pytest.mark.unit
class TestBuildOauthAuthUrlNonce:
    async def test_openid_flow_stores_a_16_byte_nonce_and_sends_it(self) -> None:
        store = _token_store()
        store.create_oauth_state.return_value = "state-1"
        resolved = SimpleNamespace(mcp_config=_config(client_id="cid"))
        discovery = _discovery(initial_scope="openid")

        with (
            patch.object(IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(mcp_oauth, "discover_oauth_config", AsyncMock(return_value=discovery)),
            patch.object(secrets, "token_urlsafe", wraps=secrets.token_urlsafe) as token_urlsafe,
        ):
            url = await build_oauth_auth_url(store, INTEGRATION_ID, REDIRECT_URI)

        assert call(16) in token_urlsafe.call_args_list
        stored_nonce = store.store_oauth_nonce.await_args.args[1]
        assert store.store_oauth_nonce.await_args.args[0] == INTEGRATION_ID
        assert len(stored_nonce) == 22
        assert parse_qs(url.split("?", 1)[1])["nonce"] == [stored_nonce]


@pytest.mark.unit
class TestRegisterClient:
    @pytest.fixture(autouse=True)
    def _client(self, http_client: None) -> None:
        return None

    @respx.mock
    async def test_http_frontend_registers_without_branding(
        self, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(REGISTRATION_ENDPOINT).respond(
            201, json={"client_id": "registered", "redirect_uris": [REDIRECT_URI]}
        )
        store = _token_store()

        with patch.object(mcp_oauth, "get_frontend_url", return_value="http://localhost:3000"):
            client_id = await _register_client(store, INTEGRATION_ID, _metadata(), REDIRECT_URI)

        assert client_id == "registered"
        assert httpx.Response(200, content=route.calls.last.request.content).json() == {
            "client_name": "GAIA",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }

    @respx.mock
    async def test_https_frontend_adds_consent_screen_branding(
        self, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(REGISTRATION_ENDPOINT).respond(
            201, json={"client_id": "registered", "redirect_uris": [REDIRECT_URI]}
        )
        frontend = "https://app.gaia.example"

        with patch.object(mcp_oauth, "get_frontend_url", return_value=frontend):
            await _register_client(_token_store(), INTEGRATION_ID, _metadata(), REDIRECT_URI)

        body = httpx.Response(200, content=route.calls.last.request.content).json()
        assert body == {
            "client_name": "GAIA",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_uri": f"{frontend}/",
            "logo_uri": f"{frontend}{GAIA_OAUTH_LOGO_PATH}",
            "tos_uri": f"{frontend}{GAIA_OAUTH_TOS_PATH}",
            "policy_uri": f"{frontend}{GAIA_OAUTH_PRIVACY_PATH}",
        }

    @respx.mock
    async def test_registration_is_stored_as_json_without_unset_fields(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(REGISTRATION_ENDPOINT).respond(
            201, json={"client_id": "registered", "redirect_uris": [REDIRECT_URI]}
        )
        store = _token_store()

        with patch.object(mcp_oauth, "get_frontend_url", return_value="http://localhost:3000"):
            await _register_client(store, INTEGRATION_ID, _metadata(), REDIRECT_URI)

        store.store_dcr_client.assert_awaited_once()
        integration_id, stored = store.store_dcr_client.await_args.args
        assert integration_id == INTEGRATION_ID
        assert stored["client_id"] == "registered"
        assert stored["redirect_uris"] == [REDIRECT_URI]
        assert None not in stored.values()

    @pytest.mark.parametrize("status", [403, 404, 405])
    @respx.mock
    async def test_unsupported_registration_is_reported_with_status(
        self, respx_mock: respx.MockRouter, status: int
    ) -> None:
        respx_mock.post(REGISTRATION_ENDPOINT).respond(status)

        with (
            patch.object(mcp_oauth, "get_frontend_url", return_value="http://localhost:3000"),
            pytest.raises(DCRNotSupportedError) as raised,
        ):
            await _register_client(_token_store(), INTEGRATION_ID, _metadata(), REDIRECT_URI)

        assert str(raised.value) == (
            f"DCR not supported at {REGISTRATION_ENDPOINT} "
            f"(status {status}). Pre-registration required."
        )


class _Callback:
    """Wires handle_oauth_callback to a respx token endpoint and mocked store/status seams."""

    def __init__(self, token_json: dict[str, object] | None = None) -> None:
        self.store = _token_store()
        self.store.verify_oauth_state.return_value = (True, "verifier-1")
        self.store.get_and_delete_oauth_nonce.return_value = None
        self.connect = AsyncMock()
        self.status = AsyncMock()
        self.config = _config(client_id="cid", client_secret="secret")
        self.token_json: dict[str, object] = token_json or {
            "access_token": "opaque",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-2",
        }

    async def run(
        self,
        router: respx.MockRouter,
        *,
        discovery: OAuthDiscovery | None = None,
        issuer_ok: bool = True,
        resolved: object | None = None,
    ) -> respx.Route:
        route = router.post(TOKEN_ENDPOINT).respond(200, json=self.token_json)
        discovered = discovery or _discovery()
        with (
            patch.object(
                IntegrationResolver,
                "resolve",
                AsyncMock(return_value=resolved or SimpleNamespace(mcp_config=self.config)),
            ) as resolve,
            patch.object(mcp_oauth, "discover_oauth_config", AsyncMock(return_value=discovered)),
            patch.object(mcp_oauth, "update_user_integration_status", self.status),
            patch.object(mcp_oauth, "validate_jwt_issuer", return_value=issuer_ok) as issuer,
            patch.object(mcp_oauth, "mcp_http_client", lambda: httpx.AsyncClient()),
        ):
            await handle_oauth_callback(
                self.store, INTEGRATION_ID, "code-1", "state-1", REDIRECT_URI, self.connect
            )
        self.resolve = resolve
        self.issuer = issuer
        return route


@pytest.mark.unit
class TestHandleOauthCallback:
    @respx.mock
    @time_machine.travel(datetime(2030, 1, 1, tzinfo=UTC), tick=False)
    async def test_successful_exchange_stores_tokens_and_connects(
        self, respx_mock: respx.MockRouter
    ) -> None:
        flow = _Callback()

        route = await flow.run(respx_mock)

        flow.store.verify_oauth_state.assert_awaited_once_with(INTEGRATION_ID, "state-1")
        flow.resolve.assert_awaited_once_with(INTEGRATION_ID)
        flow.store.get_and_delete_oauth_nonce.assert_awaited_once_with(INTEGRATION_ID)
        form = parse_qs(route.calls.last.request.content.decode())
        assert form["resource"] == [RESOURCE]
        assert form["code_verifier"] == ["verifier-1"]
        flow.issuer.assert_called_once_with("opaque", AUTH + "/", INTEGRATION_ID)
        flow.store.store_oauth_tokens.assert_awaited_once_with(
            integration_id=INTEGRATION_ID,
            access_token="opaque",
            refresh_token="refresh-2",
            expires_at=datetime(2030, 1, 1, 1, 0, tzinfo=UTC),
        )
        flow.status.assert_awaited_once_with("user-1", INTEGRATION_ID, "connected")
        flow.connect.assert_awaited_once_with(INTEGRATION_ID)

    @respx.mock
    async def test_invalid_state_is_rejected_with_the_csrf_message(
        self, respx_mock: respx.MockRouter
    ) -> None:
        flow = _Callback()
        flow.store.verify_oauth_state.return_value = (False, None)

        with pytest.raises(ValueError) as raised:
            await flow.run(respx_mock)

        assert str(raised.value) == "Invalid OAuth state - possible CSRF attack or expired state"

    @respx.mock
    async def test_insecure_token_endpoint_only_warns(self, respx_mock: respx.MockRouter) -> None:
        flow = _Callback()
        insecure = "http://auth.mcp.example/token"
        respx_mock.post(insecure).respond(200, json=flow.token_json)
        discovery = _discovery(metadata=_metadata(token_endpoint=insecure))

        with patch.object(log, "warning") as warning:
            await flow.run(respx_mock, discovery=discovery)

        warning.assert_called_once_with(
            f"{LogTag.MCP} Token endpoint security warning",
            error=(
                f"OAuth endpoint must use HTTPS: {insecure}. "
                "HTTP is only allowed for localhost during development."
            ),
            error_type="OAuthSecurityError",
            integration_id=INTEGRATION_ID,
        )
        flow.connect.assert_awaited_once_with(INTEGRATION_ID)

    @respx.mock
    async def test_missing_client_id_explains_what_was_tried(
        self, respx_mock: respx.MockRouter
    ) -> None:
        flow = _Callback()
        flow.config = _config()
        flow.store.get_dcr_client.return_value = None

        with pytest.raises(ValueError) as raised:
            await flow.run(respx_mock)

        assert str(raised.value) == (
            f"Could not resolve client_id for token exchange ({INTEGRATION_ID}). "
            "No pre-configured credentials, no DCR registration, "
            "and client metadata document not applicable."
        )

    @respx.mock
    async def test_failed_issuer_check_warns_and_continues(
        self, respx_mock: respx.MockRouter
    ) -> None:
        flow = _Callback()

        with patch.object(log, "warning") as warning:
            await flow.run(respx_mock, issuer_ok=False)

        warning.assert_called_once_with(
            f"{LogTag.MCP} JWT issuer validation failed for",
            integration_id=INTEGRATION_ID,
        )
        flow.connect.assert_awaited_once_with(INTEGRATION_ID)

    @respx.mock
    async def test_tokens_without_expiry_or_rotation_store_none(
        self, respx_mock: respx.MockRouter
    ) -> None:
        flow = _Callback({"access_token": "opaque", "token_type": "Bearer"})

        await flow.run(respx_mock)

        flow.store.store_oauth_tokens.assert_awaited_once_with(
            integration_id=INTEGRATION_ID,
            access_token="opaque",
            refresh_token=None,
            expires_at=None,
        )

    @respx.mock
    async def test_status_flip_failure_is_logged_and_the_connect_still_runs(
        self, respx_mock: respx.MockRouter
    ) -> None:
        flow = _Callback()
        flow.status.side_effect = RuntimeError("mongo down")

        with patch.object(log, "warning") as warning:
            await flow.run(respx_mock)

        warning.assert_called_once_with(
            f"{LogTag.MCP} optimistic status flip failed (will retry in background connect)",
            integration_id=INTEGRATION_ID,
            error="mongo down",
            error_type="RuntimeError",
        )
        flow.connect.assert_awaited_once_with(INTEGRATION_ID)
