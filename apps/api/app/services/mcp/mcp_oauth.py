"""The MCP OAuth 2.1 authorization flow: authorization URL, client registration, and code exchange.

See: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Covers Dynamic Client Registration (RFC 7591), Resource Indicators (RFC 8707),
PKCE with S256, Client Metadata Document client ids, OIDC nonce, JWT issuer
validation and the HTTPS check on the token endpoint. Discovery (RFC 9728 /
RFC 8414) lives in oauth_discovery; refresh and revocation (RFC 7009) in
token_management.
"""

import base64
from collections.abc import Awaitable, Callable
import secrets
from typing import TypedDict
import urllib.parse

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, ConfigDict, JsonValue

from app.constants.log_tags import LogTag
from app.constants.mcp import (
    GAIA_OAUTH_CLIENT_NAME,
    GAIA_OAUTH_LOGO_PATH,
    GAIA_OAUTH_PRIVACY_PATH,
    GAIA_OAUTH_TOS_PATH,
    MAX_OAUTH_INVALID_SCOPE_DROPS,
)
from app.helpers.mcp_helpers import get_api_base_url, get_frontend_url
from app.models.mcp_config import (
    DCRClientRegistration,
    McpAuthChallenge,
    MCPConfig,
    OAuthDiscovery,
    OAuthErrorResponse,
    OidcTokenResponse,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.mcp.mcp_errors import DCRNotSupportedError, DCRRegistrationError
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.oauth_discovery import discover_oauth_config
from app.services.mcp.token_management import resolve_client_credentials
from app.utils.mcp_oauth_utils import (
    MCP_PROTOCOL_VERSION,
    OAuthSecurityError,
    basic_auth_header,
    get_client_metadata_document_url,
    is_localhost_url,
    mcp_http_client,
    oauth_token_expiry,
    parse_oauth_error_response,
    parse_rejected_scopes,
    validate_https_url,
    validate_jwt_issuer,
    validate_pkce_support,
)
from mcp.client.auth.exceptions import OAuthRegistrationError
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.client.auth.utils import (
    create_client_registration_request,
    get_client_metadata_scopes,
    handle_registration_response,
)
from mcp.shared.auth import OAuthClientMetadata, OAuthMetadata
from shared.py.wide_events import log


class _IdTokenClaims(BaseModel):
    """The id_token claim the OIDC nonce check reads."""

    model_config = ConfigDict(extra="ignore")

    nonce: JsonValue = None


class _TokenExchangeRequest(TypedDict):
    """RFC 6749 authorization-code grant parameters posted to the token endpoint."""

    code: str
    redirect_uri: str
    resource: str
    client_id: str
    client_secret: str | None
    code_verifier: str | None


class _ClientBranding(TypedDict, total=False):
    """Optional consent-screen branding URIs for Dynamic Client Registration."""

    client_uri: AnyHttpUrl
    logo_uri: AnyHttpUrl
    tos_uri: AnyHttpUrl
    policy_uri: AnyHttpUrl


def _metadata_document_candidate() -> tuple[str, bool, str]:
    """Compute (api_base, is_localhost, client metadata document URL).

    Shared by auth-URL building and token exchange so client_id can't
    drift between them. Per draft-ietf-oauth-client-id-metadata-document,
    client_id can be that document's URL, but only when the auth server
    can fetch it (non-localhost API base).
    """
    api_base = get_api_base_url()
    return api_base, is_localhost_url(api_base), get_client_metadata_document_url(api_base)


async def _client_id_from_metadata_or_dcr(
    token_store: MCPTokenStore,
    integration_id: str,
    oauth_config: OAuthDiscovery,
    redirect_uri: str,
) -> str | None:
    """Fallback client_id sources: metadata document URL (priority 3) or fresh DCR (priority 4)."""
    _, is_localhost, metadata_doc_url = _metadata_document_candidate()

    if oauth_config.as_metadata.client_id_metadata_document_supported and not is_localhost:
        log.info(
            f"{LogTag.MCP} Using client metadata document URL as client_id for",
            integration_id=integration_id,
            client_id=metadata_doc_url,
        )
        return metadata_doc_url

    # Fall back to Dynamic Client Registration (DCR). Also required when
    # running locally since the auth server cannot reach localhost to
    # validate the client metadata document.
    if oauth_config.as_metadata.registration_endpoint:
        client_id = await _register_client(
            token_store,
            integration_id,
            oauth_config.as_metadata,
            redirect_uri,
        )
        log.info(f"{LogTag.MCP} Registered new client via DCR for", integration_id=integration_id)
        return client_id

    return None


async def _obtain_auth_client_id(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    oauth_config: OAuthDiscovery,
    redirect_uri: str,
) -> str:
    """Resolve client_id per MCP spec priority: configured creds → stored DCR → metadata doc → DCR."""
    # Priority order per MCP spec: pre-configured credentials, then stored
    # DCR client, then Client Metadata Document URL (non-localhost only),
    # then Dynamic Client Registration (DCR) as last resort.
    client_id, _ = resolve_client_credentials(mcp_config)

    if not client_id:
        # Priority 2: Check for stored DCR client from a previous registration.
        # This is effectively "pre-registered" for this specific integration.
        dcr_data: DCRClientRegistration | None = await token_store.get_dcr_client(integration_id)
        if dcr_data:
            client_id = dcr_data.get("client_id")
            log.debug(f"{LogTag.MCP} Using stored DCR client for", integration_id=integration_id)

    if not client_id:
        client_id = await _client_id_from_metadata_or_dcr(
            token_store, integration_id, oauth_config, redirect_uri
        )

    if not client_id:
        raise ValueError(
            f"Could not obtain client_id for {integration_id}. "
            "Tried: (1) pre-configured credentials, (2) stored DCR client, "
            "(3) client metadata document, (4) new DCR registration. "
            "The authorization server may require manual client pre-registration."
        )

    log.info(f"{LogTag.MCP} client_id resolved for auth URL", integration_id=integration_id)
    return client_id


def _build_oauth_scope_string(
    integration_id: str,
    mcp_config: MCPConfig,
    oauth_config: OAuthDiscovery,
    excluded_scopes: set[str] | None,
) -> str:
    """Resolve the authorization request scope string, injecting offline_access and dropping rejected scopes."""
    # Scope selection per MCP spec (WWW-Authenticate > PRM > AS scopes); a
    # configured override (oauth_scopes) wins only when the 401 challenge
    # didn't dictate a scope — GAIA-specific behavior the SDK doesn't cover.
    if not oauth_config.initial_scope and mcp_config.oauth_scopes:
        scope_str = " ".join(mcp_config.oauth_scopes)
    else:
        scope_str = (
            get_client_metadata_scopes(
                oauth_config.initial_scope,
                oauth_config.prm,
                oauth_config.as_metadata,
            )
            or ""
        )

    # Inject offline_access when the server supports it and it's missing:
    # without it many OAuth servers issue short-lived refresh tokens,
    # breaking "connect once, stay forever". Only added when advertised.
    scopes_supported = oauth_config.scopes_supported
    scope_parts = scope_str.split() if scope_str else []
    if "offline_access" in scopes_supported and "offline_access" not in scope_parts:
        scope_parts.append("offline_access")
        log.info(
            f"{LogTag.MCP} Added offline_access scope for long-lived refresh token",
            integration_id=integration_id,
        )

    # Drop scopes the auth server previously rejected with invalid_scope so a
    # retry can converge (e.g. agentmail's "user:org:read", which a
    # dynamically registered client isn't actually permitted to request).
    if excluded_scopes:
        dropped = [s for s in scope_parts if s in excluded_scopes]
        if dropped:
            scope_parts = [s for s in scope_parts if s not in excluded_scopes]
            log.info(
                f"{LogTag.MCP} Dropping previously-rejected scopes on retry",
                integration_id=integration_id,
                dropped=dropped,
            )

    return " ".join(scope_parts)


async def build_oauth_auth_url(
    token_store: MCPTokenStore,
    integration_id: str,
    redirect_uri: str,
    redirect_path: str = "/integrations",
    challenge_data: McpAuthChallenge | None = None,
    excluded_scopes: set[str] | None = None,
) -> str:
    """Build OAuth authorization URL using MCP spec discovery.

    Supports platform and custom integrations. challenge_data is an
    optional pre-fetched WWW-Authenticate challenge, passed to avoid
    duplicate discovery HTTP calls.
    """
    # Resolve integration from platform config or MongoDB
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved or not resolved.mcp_config:
        raise ValueError(f"Integration {integration_id} not found")

    mcp_config = resolved.mcp_config
    # Full MCP OAuth discovery - pass challenge_data to avoid re-probe
    oauth_config = await discover_oauth_config(
        token_store, integration_id, mcp_config, challenge_data=challenge_data
    )

    # Priority order per MCP spec: pre-configured credentials, then stored
    # DCR client, then Client Metadata Document URL (non-localhost only),
    # then Dynamic Client Registration (DCR) as last resort.
    client_id = await _obtain_auth_client_id(
        token_store, integration_id, mcp_config, oauth_config, redirect_uri
    )

    # Verify PKCE support per MCP spec using centralized validation
    validate_pkce_support(oauth_config.as_metadata, integration_id)

    # Generate PKCE pair (required for OAuth 2.1)
    pkce = PKCEParameters.generate()

    # Create OAuth state (stores code_verifier for token exchange)
    state = await token_store.create_oauth_state(integration_id, pkce.code_verifier)
    state_data = f"{state}:{integration_id}:{redirect_path}"

    # Build authorization URL
    auth_endpoint = str(oauth_config.as_metadata.authorization_endpoint)

    scope_str = _build_oauth_scope_string(integration_id, mcp_config, oauth_config, excluded_scopes)

    # Get resource URL for token binding (RFC 8707)
    # This ensures the token is bound to the specific MCP server
    resource = oauth_config.resource

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state_data,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
        "resource": resource,  # CRITICAL: Binds token to MCP server (RFC 8707)
    }
    if scope_str:
        params["scope"] = scope_str

    # NEW: Add nonce for OpenID Connect flows to prevent replay attacks
    if scope_str and "openid" in scope_str.lower():
        nonce = secrets.token_urlsafe(16)
        params["nonce"] = nonce
        # Store nonce for validation in callback
        await token_store.store_oauth_nonce(integration_id, nonce)
        log.debug(f"{LogTag.MCP} Added OIDC nonce for", integration_id=integration_id)

    return f"{auth_endpoint}?{urllib.parse.urlencode(params)}"


async def build_scope_retry_url(
    token_store: MCPTokenStore,
    integration_id: str,
    error_description: str | None,
    redirect_uri: str,
    redirect_path: str,
) -> str | None:
    """Re-issue the authorization URL after an invalid_scope rejection, or None if pointless.

    Drops the rejected scope(s) and rebuilds the URL, retrying only when a
    genuinely new scope was named so the loop converges.
    """
    rejected = parse_rejected_scopes(error_description)
    excluded = await token_store.get_excluded_scopes(integration_id)
    if not rejected - excluded or len(excluded) >= MAX_OAUTH_INVALID_SCOPE_DROPS:
        return None

    excluded = await token_store.add_excluded_scopes(integration_id, rejected)
    log.info(
        f"{LogTag.MCP} invalid_scope — retrying authorization without excluded scopes",
        integration_id=integration_id,
        excluded_scopes=sorted(excluded),
    )
    return await build_oauth_auth_url(
        token_store, integration_id, redirect_uri, redirect_path, excluded_scopes=excluded
    )


async def _register_client(
    token_store: MCPTokenStore, integration_id: str, as_metadata: OAuthMetadata, redirect_uri: str
) -> str | None:
    """
    Perform Dynamic Client Registration (RFC 7591) on the authorization server.

    Raises:
        DCRNotSupportedError: If server returns 403/404/405 (DCR not supported)
        ValueError: For other registration failures
    """
    registration_endpoint = str(as_metadata.registration_endpoint)
    # Branding on the consent screen is optional cosmetics; some RFC 7591
    # servers (e.g. granola) reject non-HTTPS branding URIs with 400
    # invalid_client_metadata — redirect_uri itself may stay http://localhost.
    frontend = get_frontend_url()
    branding: _ClientBranding = {}
    if frontend.startswith("https://"):
        branding = {
            "client_uri": AnyHttpUrl(frontend),
            "logo_uri": AnyHttpUrl(f"{frontend}{GAIA_OAUTH_LOGO_PATH}"),
            "tos_uri": AnyHttpUrl(f"{frontend}{GAIA_OAUTH_TOS_PATH}"),
            "policy_uri": AnyHttpUrl(f"{frontend}{GAIA_OAUTH_PRIVACY_PATH}"),
        }
    client_metadata = OAuthClientMetadata(
        client_name=GAIA_OAUTH_CLIENT_NAME,
        redirect_uris=[AnyUrl(redirect_uri)],
        token_endpoint_auth_method="none",  # nosec B106 - OAuth spec literal, not a secret
        **branding,
    )
    request = create_client_registration_request(  # pragma: no mutate — registration_endpoint is a dead fallback; URL and body pinned by tests
        as_metadata, client_metadata, registration_endpoint
    )
    try:
        async with mcp_http_client() as http_client:
            response = await http_client.send(request)

            # Check for DCR not supported (403/404/405) before the SDK parser,
            # which would otherwise raise a generic OAuthRegistrationError and
            # lose the "pre-registration required" signal the caller acts on.
            if response.status_code in (403, 404, 405):
                raise DCRNotSupportedError(
                    f"DCR not supported at {registration_endpoint} "
                    f"(status {response.status_code}). Pre-registration required."
                )

            # Parse + validate the RFC 7591 response via the SDK, symmetric with
            # create_client_registration_request above — keeps DCR handling
            # spec-aligned in one place instead of hand-rolling status/body checks.
            client_info = await handle_registration_response(response)
            await token_store.store_dcr_client(
                integration_id, client_info.model_dump(mode="json", exclude_none=True)
            )
            log.info(
                f"{LogTag.MCP} DCR successful for at",
                integration_id=integration_id,
                registration_endpoint=registration_endpoint,
            )
            return client_info.client_id
    except DCRNotSupportedError:
        raise  # Re-raise without wrapping
    except OAuthRegistrationError as e:
        # An external AS rejecting our DCR (4xx body, invalid response) is its
        # policy, not a GAIA fault; the caller surfaces it to the user, so warn
        # to keep it out of Sentry's High queue.
        log.warning(
            f"{LogTag.MCP} DCR rejected by authorization server",
            integration_id=integration_id,
            registration_endpoint=registration_endpoint,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise DCRRegistrationError(f"Dynamic Client Registration failed: {e}") from e
    except Exception as e:
        # Transport, parsing, or store_dcr_client failures are internal and
        # may silently block OAuth, so keep error-level monitoring on them.
        log.error(
            f"{LogTag.MCP} DCR failed unexpectedly",
            integration_id=integration_id,
            registration_endpoint=registration_endpoint,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise ValueError(f"Dynamic Client Registration failed: {e}") from e


async def _resolve_token_exchange_credentials(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    oauth_config: OAuthDiscovery,
) -> tuple[str | None, str | None]:
    """Resolve client credentials using the same priority as build_oauth_auth_url."""
    # 1. Pre-configured credentials
    resolved_id, resolved_secret = resolve_client_credentials(mcp_config)
    if resolved_id:
        return resolved_id, resolved_secret

    # 2. Stored DCR client
    dcr_data: DCRClientRegistration | None = await token_store.get_dcr_client(integration_id)
    if dcr_data:
        return dcr_data.get("client_id"), dcr_data.get("client_secret")

    # 3. Client Metadata Document URL (must match build_oauth_auth_url logic)
    _, is_localhost, metadata_doc_url = _metadata_document_candidate()
    if oauth_config.as_metadata.client_id_metadata_document_supported and not is_localhost:
        log.info(
            f"{LogTag.MCP} Using client metadata document URL as client_id for token exchange",
            client_id=metadata_doc_url,
        )
        return metadata_doc_url, None

    return None, None


async def _exchange_code_for_tokens(
    integration_id: str,
    token_endpoint: str,
    exchange: _TokenExchangeRequest,
) -> OidcTokenResponse:
    """POST the RFC 6749 authorization-code grant to token_endpoint and return the parsed response."""
    token_data: dict[str, str] = {
        "grant_type": "authorization_code",
        # Always include client_id in body for PKCE compatibility
        # Some OAuth servers require client_id in body for PKCE validation
        "client_id": exchange["client_id"],
        "code": exchange["code"],
        "redirect_uri": exchange["redirect_uri"],
        "resource": exchange["resource"],  # CRITICAL: Bind token to MCP server (RFC 8707)
    }

    # Include PKCE code_verifier if we have it (required for OAuth 2.1)
    if code_verifier := exchange["code_verifier"]:
        token_data["code_verifier"] = code_verifier

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if exchange["client_secret"]:
        headers["Authorization"] = basic_auth_header(
            exchange["client_id"], exchange["client_secret"]
        )

    async with mcp_http_client() as http_client:
        response = await http_client.post(
            token_endpoint, data=token_data, headers=headers, timeout=30
        )

    # Handle error responses with structured parsing
    # Accept any 2xx status code as success (OAuth servers vary: 200, 201, etc.)
    if not (200 <= response.status_code < 300):
        error_info: OAuthErrorResponse = parse_oauth_error_response(response)
        log.error(
            f"{LogTag.MCP} Token exchange failed",
            integration_id=integration_id,
            oauth_error=error_info["error"],
            oauth_error_description=error_info.get("error_description"),
        )
        raise ValueError(
            f"Token exchange failed: {error_info['error']} - "
            f"{error_info.get('error_description', 'Unknown error')}"
        )

    # OAuthToken requires access_token and normalizes token_type to Bearer (OAuth 2.1).
    return OidcTokenResponse.model_validate(response.json())


def _validate_oidc_nonce(
    integration_id: str,
    stored_nonce: str,
    id_token: str | None,
) -> None:
    """Compare the id_token nonce against the value stored during auth URL build."""
    if not id_token:
        raise ValueError(
            f"OIDC nonce validation failed for {integration_id}: "
            "token response contained no id_token"
        )

    try:
        # Decode JWT payload without verification (nonce is for replay protection).
        # Fixed three "=" padding: base64 needs at most two, and the decoder
        # ignores the surplus, so this is always enough and never wrong.
        payload_b64 = id_token.split(".")[1] + "==="
        claims = _IdTokenClaims.model_validate_json(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        raise ValueError(
            f"OIDC nonce validation failed for {integration_id}: could not decode id_token"
        ) from e

    token_nonce = claims.nonce
    if token_nonce is None:
        raise ValueError(
            f"OIDC nonce validation failed for {integration_id}: id_token carries no nonce claim"
        )

    if token_nonce != stored_nonce:
        raise ValueError(f"OIDC nonce mismatch for {integration_id}: possible replay attack")

    log.debug(f"{LogTag.MCP} OIDC nonce validated for", integration_id=integration_id)


async def handle_oauth_callback(
    token_store: MCPTokenStore,
    integration_id: str,
    code: str,
    state: str,
    redirect_uri: str,
    connect_after_oauth: Callable[[str], Awaitable[None]],
) -> None:
    """Exchange authorization code for tokens, then hand the integration to connect_after_oauth.

    Implements RFC 6749 token exchange with PKCE (RFC 7636), resource
    binding (RFC 8707), structured error parsing, response validation,
    and JWT issuer validation when applicable.
    """
    is_valid, code_verifier = await token_store.verify_oauth_state(integration_id, state)
    if not is_valid:
        raise ValueError("Invalid OAuth state - possible CSRF attack or expired state")

    # Resolve integration from platform config or MongoDB
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved or not resolved.mcp_config:
        raise ValueError(f"Integration {integration_id} not found")

    mcp_config = resolved.mcp_config

    # Get OAuth config (should be cached from build_oauth_auth_url)
    oauth_config = await discover_oauth_config(token_store, integration_id, mcp_config)
    token_endpoint = str(oauth_config.as_metadata.token_endpoint)

    # Validate token endpoint uses HTTPS
    try:
        validate_https_url(token_endpoint)
    except OAuthSecurityError as e:
        log.warning(
            f"{LogTag.MCP} Token endpoint security warning",
            error=str(e),
            error_type=type(e).__name__,
            integration_id=integration_id,
        )

    # Resolve client credentials using same priority as build_oauth_auth_url
    # to ensure the same client_id is used for both authorization and token exchange.
    client_id, client_secret = await _resolve_token_exchange_credentials(
        token_store, integration_id, mcp_config, oauth_config
    )
    if not client_id:
        raise ValueError(
            f"Could not resolve client_id for token exchange ({integration_id}). "
            "No pre-configured credentials, no DCR registration, "
            "and client metadata document not applicable."
        )

    log.info(
        f"{LogTag.MCP} client_id resolved for token exchange",
        integration_id=integration_id,
        has_secret=client_secret is not None,
    )

    # Get resource for token binding (RFC 8707)
    resource = oauth_config.resource

    token = await _exchange_code_for_tokens(
        integration_id=integration_id,
        token_endpoint=token_endpoint,
        exchange={
            "code": code,
            "redirect_uri": redirect_uri,
            "resource": resource,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
    )

    access_token = token.access_token

    # Validate JWT issuer if applicable
    issuer = str(oauth_config.as_metadata.issuer)
    if not validate_jwt_issuer(access_token, issuer, integration_id):
        log.warning(f"{LogTag.MCP} JWT issuer validation failed for", integration_id=integration_id)
        # Continue anyway - some tokens are opaque, not JWTs

    # Validate OIDC nonce if one was stored during auth URL build
    stored_nonce = await token_store.get_and_delete_oauth_nonce(integration_id)
    if stored_nonce:
        _validate_oidc_nonce(integration_id, stored_nonce, token.id_token)

    expires_at = oauth_token_expiry(token.expires_in)

    # Handle refresh token rotation (new refresh_token may be issued)
    new_refresh_token = token.refresh_token

    log.info(
        f"{LogTag.MCP} OAuth callback - token exchange successful",
        integration_id=integration_id,
        access_token_length=len(access_token),
        has_refresh_token=new_refresh_token is not None,
        expires_at=expires_at,
    )

    # Store tokens (~20ms) — required before redirect so reconnect can use them.
    log.info(f"{LogTag.MCP} Storing OAuth tokens to PostgreSQL", integration_id=integration_id)
    await token_store.store_oauth_tokens(
        integration_id=integration_id,
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_at=expires_at,
    )

    # Optimistically flip status to connected so the redirect fires
    # immediately; connect_after_oauth reconciles (resets to disconnected)
    # if credentials prove dead.
    try:
        await update_user_integration_status(token_store.user_id, integration_id, "connected")
    except Exception as status_err:
        log.warning(
            f"{LogTag.MCP} optimistic status flip failed (will retry in background connect)",
            integration_id=integration_id,
            error=str(status_err),
            error_type=type(status_err).__name__,
        )

    await connect_after_oauth(integration_id)
