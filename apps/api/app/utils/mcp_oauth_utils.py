"""
MCP OAuth Discovery Utilities.

Contains functions for OAuth discovery per MCP specification:
- WWW-Authenticate challenge extraction
- Protected Resource Metadata (RFC 9728) discovery
- Authorization Server Metadata (RFC 8414) discovery
- HTTPS validation for security
- Token revocation support (RFC 7009)
- Token introspection support (RFC 7662)
"""

import base64
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    extract_field_from_www_auth,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
)
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCRequest,
)
from pydantic import AnyHttpUrl

from shared.py.wide_events import log

# Sent in the MCP-Protocol-Version header on OAuth discovery/token requests for
# protocol version negotiation. Sourced from the SDK so it tracks the spec on
# upgrade. See https://modelcontextprotocol.io/specification/versioning
MCP_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION

# Generous timeouts since TLS handshakes can take 2-5s on slow connections.
OAUTH_PROBE_TIMEOUT = 10  # seconds - for initial server probe
OAUTH_DISCOVERY_TIMEOUT = 15  # seconds - for metadata discovery
OAUTH_TOKEN_TIMEOUT = 30  # seconds - for token operations

_CONTENT_TYPE_JSON = "application/json"
_ACCEPT_JSON_SSE = f"{_CONTENT_TYPE_JSON}, text/event-stream"

# Minimal MCP `initialize` request used to probe a server's auth requirement.
# Per the MCP Authorization spec the 401 + WWW-Authenticate challenge is returned
# in response to an actual MCP request, so the probe POSTs this rather than
# issuing a bare GET — a GET only opens the optional server->client SSE stream
# and may be rejected (405/406) before auth is ever evaluated.
_MCP_INITIALIZE_PROBE_REQUEST: dict[str, Any] = JSONRPCRequest(
    jsonrpc="2.0",
    id=1,
    method="initialize",
    params=InitializeRequestParams(
        protocolVersion=MCP_PROTOCOL_VERSION,
        capabilities=ClientCapabilities(),
        clientInfo=Implementation(name="gaia", version="1.0"),
    ).model_dump(by_alias=True, exclude_none=True, mode="json"),
).model_dump(by_alias=True, exclude_none=True, mode="json")


def oauth_token_expiry(expires_in: int | None) -> datetime | None:
    """Absolute tz-aware UTC expiry for an OAuth token's ``expires_in`` seconds.

    Single source of truth for token-expiry so the callback and refresh paths
    can't drift. Returns None when the server omits ``expires_in``.
    """
    if not expires_in:
        return None
    return datetime.now(UTC) + timedelta(seconds=expires_in)


class OAuthSecurityError(Exception):
    """Raised when OAuth security requirements are not met."""

    pass


class OAuthDiscoveryError(Exception):
    """Raised when OAuth discovery fails."""

    pass


def validate_https_url(url: str, allow_localhost: bool = True) -> None:
    """Require HTTPS for an OAuth endpoint.

    Per OAuth 2.1 and the MCP spec, OAuth endpoints MUST use HTTPS, except
    localhost during development. Raises OAuthSecurityError otherwise.
    """
    parsed = urlparse(url)

    if parsed.scheme == "https":
        return  # Valid HTTPS

    if allow_localhost and parsed.scheme == "http":
        # Allow HTTP only for localhost/127.0.0.1/[::1] in development
        # Handle IPv6 addresses enclosed in brackets
        hostname = parsed.hostname or ""
        hostname_lower = hostname.lower()
        if hostname_lower in ("localhost", "127.0.0.1", "::1"):
            log.debug(f"Allowing HTTP for localhost URL: {url}")
            return

    raise OAuthSecurityError(
        f"OAuth endpoint must use HTTPS: {url}. "
        "HTTP is only allowed for localhost during development."
    )


def is_localhost_url(url: str) -> bool:
    """Return True if the URL points to localhost or a loopback/unspecified address."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            return False

        # Check hostname string (case-insensitive)
        hostname_lower = hostname.lower()
        if hostname_lower in ("localhost", ""):
            return True

        # Check if it's a loopback IP address
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_loopback or ip.is_unspecified
        except ValueError:
            return False

    except Exception:
        return False


def validate_oauth_endpoints(as_metadata: OAuthMetadata, allow_localhost: bool = True) -> None:
    """Validate that every OAuth endpoint in ``as_metadata`` uses HTTPS."""
    endpoints = {
        "authorization_endpoint": as_metadata.authorization_endpoint,
        "token_endpoint": as_metadata.token_endpoint,
        "registration_endpoint": as_metadata.registration_endpoint,
        "revocation_endpoint": as_metadata.revocation_endpoint,
        "introspection_endpoint": as_metadata.introspection_endpoint,
        "issuer": as_metadata.issuer,
    }

    for key, url in endpoints.items():
        if url:
            try:
                validate_https_url(str(url), allow_localhost=allow_localhost)
            except OAuthSecurityError as e:
                raise OAuthSecurityError(f"Invalid {key}: {e}")


def parse_rejected_scopes(error_description: str | None) -> set[str]:
    """Extract the scope names an auth server rejected with ``invalid_scope``.

    OAuth servers are inconsistent in how they report the offending scope, so we
    prefer quoted tokens (e.g. ``... not allowed to request scope 'user:org:read'``)
    and fall back to the single scope-like token following the word "scope".
    Returns an empty set when nothing parseable is found.
    """
    if not error_description:
        return set()
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", error_description)
    if quoted:
        return {s.strip() for s in quoted if s.strip()}
    match = re.search(r"scopes?[:=\s]+([a-z0-9_:./-]+)", error_description, re.IGNORECASE)
    return {match.group(1)} if match else set()


async def extract_auth_challenge(server_url: str) -> dict:
    """
    Probe MCP server and parse full WWW-Authenticate challenge per MCP spec.

    Per MCP Authorization spec Phase 1:
    - Client issues an MCP `initialize` POST to the server
    - Server returns 401 with WWW-Authenticate header when auth is required
    - Header may contain: resource_metadata, scope, error, error_description

    Returns dict with extracted fields (empty dict if no 401 or parse fails).
    """
    # Per the MCP Authorization spec, the 401 + WWW-Authenticate challenge is
    # returned in response to an MCP request (an `initialize` POST). A bare GET
    # only opens the optional server->client SSE stream, which spec-compliant
    # servers may reject with 405/406 before evaluating auth — making a GET probe
    # miss the auth requirement entirely (e.g. granola returns 405 to a GET but
    # 401 + resource_metadata to the initialize POST).
    headers = {
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Accept": _ACCEPT_JSON_SSE,
        "Content-Type": _CONTENT_TYPE_JSON,
    }
    log.set(operation="extract_auth_challenge", server_url=server_url)
    start_time = time.perf_counter()

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                server_url,
                json=_MCP_INITIALIZE_PROBE_REQUEST,
                headers=headers,
                timeout=OAUTH_PROBE_TIMEOUT,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 401:
                result: dict[str, str] = {"raw": response.headers.get("WWW-Authenticate", "")}

                rm_value = extract_resource_metadata_from_www_auth(response)
                if rm_value:
                    result["resource_metadata"] = rm_value

                scope_value = extract_scope_from_www_auth(response)
                if scope_value:
                    result["scope"] = scope_value

                error_value = extract_field_from_www_auth(response, "error")
                if error_value:
                    result["error"] = error_value

                error_desc_value = extract_field_from_www_auth(response, "error_description")
                if error_desc_value:
                    result["error_description"] = error_desc_value

                log.info(f"[TIMING] Probe {server_url}: 401 OAuth required, {elapsed_ms:.0f}ms")
                log.debug(f"Parsed WWW-Authenticate for {server_url}: {result}")
                return result

            log.info(
                f"[TIMING] Probe {server_url}: {response.status_code} (no auth), {elapsed_ms:.0f}ms"
            )
            return {}

    except httpx.ConnectError as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        # Re-raise connection errors so caller can handle them appropriately
        log.warning(f"[TIMING] Probe {server_url}: ConnectError after {elapsed_ms:.0f}ms - {e}")
        raise

    except httpx.TimeoutException as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.warning(f"[TIMING] Probe {server_url}: Timeout after {elapsed_ms:.0f}ms - {e}")
        return {}

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.warning(
            f"[TIMING] Probe {server_url}: Error after {elapsed_ms:.0f}ms - {type(e).__name__}: {e}"
        )
        return {}


async def find_protected_resource_metadata(server_url: str) -> str | None:
    """
    Find Protected Resource Metadata via well-known URIs per RFC 9728 Section 5.2.

    Per MCP spec Phase 2b, when no resource_metadata in WWW-Authenticate header,
    try well-known URIs in order:
    1. Path-aware: {origin}/.well-known/oauth-protected-resource{path}
    2. Root: {origin}/.well-known/oauth-protected-resource

    Returns the URL that responds with valid JSON, or None.
    """
    candidates = build_protected_resource_metadata_discovery_urls(None, server_url)

    # Include MCP protocol version header per MCP spec
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    start_time = time.perf_counter()

    async with httpx.AsyncClient() as client:
        for url in candidates:
            try:
                response = await client.get(url, headers=headers, timeout=OAUTH_DISCOVERY_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    if "authorization_servers" in data or "resource" in data:
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        log.info(f"[TIMING] Found PRM at {url} in {elapsed_ms:.0f}ms")
                        return url
            except Exception as e:
                log.debug(f"PRM not found at {url}: {e}")

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    log.debug(f"[TIMING] PRM discovery failed for {server_url} after {elapsed_ms:.0f}ms")
    return None


async def fetch_protected_resource_metadata(prm_url: str) -> ProtectedResourceMetadata:
    """
    Fetch and parse Protected Resource Metadata (RFC 9728).

    Returns the validated :class:`ProtectedResourceMetadata` model.
    """
    # Include MCP protocol version header per MCP spec
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    start_time = time.perf_counter()

    async with httpx.AsyncClient() as client:
        response = await client.get(prm_url, headers=headers, timeout=OAUTH_DISCOVERY_TIMEOUT)
        response.raise_for_status()
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.info(f"[TIMING] Fetched PRM from {prm_url} in {elapsed_ms:.0f}ms")
        return ProtectedResourceMetadata.model_validate(response.json())


async def fetch_auth_server_metadata(auth_server_url: str) -> OAuthMetadata:
    """
    Fetch Authorization Server Metadata (RFC 8414).

    Per RFC 8414, for an issuer URL like https://auth.example.com/tenant1:
    - Path-aware: https://auth.example.com/.well-known/oauth-authorization-server/tenant1
    - Root: https://auth.example.com/.well-known/oauth-authorization-server

    Tries multiple discovery patterns and both OAuth and OIDC endpoints.

    Per MCP spec, if metadata discovery fails, falls back to default URLs:
    - {base}/authorize
    - {base}/token
    - {base}/register
    """
    parsed = urlparse(auth_server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    candidate_urls = build_oauth_authorization_server_metadata_discovery_urls(
        auth_server_url, auth_server_url
    )

    start_time = time.perf_counter()

    async with httpx.AsyncClient() as client:
        for url in candidate_urls:
            try:
                response = await client.send(create_oauth_metadata_request(url))
                if response.status_code == 200:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    log.info(f"[TIMING] Found auth server metadata at {url} in {elapsed_ms:.0f}ms")
                    return OAuthMetadata.model_validate(response.json())
            except Exception as e:
                log.debug(f"Auth metadata not found at {url}: {e}")

    # MCP Spec Fallback: If metadata discovery fails, use default URL pattern
    # Per MCP Authorization spec (2025-03-26): fallback URLs use the
    # "authorization base URL" which is the server URL with path removed.
    # Per MCP draft spec: fallback endpoints are removed entirely.
    #
    # We use origin-only (no path) per the 2025-03-26 spec since the auth
    # server URL represents the authorization server, and its authorization/
    # token/registration endpoints are typically at the root, not nested
    # under the MCP resource path (e.g., /excalidraw/token is wrong,
    # /token is correct for server.smithery.ai/excalidraw).
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    log.info(
        f"[TIMING] Metadata discovery failed for {auth_server_url} after {elapsed_ms:.0f}ms, "
        "using MCP spec fallback URLs (origin-only, per spec)"
    )

    return OAuthMetadata(
        issuer=AnyHttpUrl(origin),
        authorization_endpoint=AnyHttpUrl(f"{origin}/authorize"),
        token_endpoint=AnyHttpUrl(f"{origin}/token"),
        registration_endpoint=AnyHttpUrl(f"{origin}/register"),
    )


async def revoke_token(
    revocation_endpoint: str,
    token: str,
    token_type_hint: str = "access_token",
    client_id: str | None = None,
    client_secret: str | None = None,
    timeout: int = 10,
) -> bool:
    """Revoke an OAuth token per RFC 7009.

    Returns True if revocation succeeded or the token was already invalid
    (per RFC 7009 the server returns 200 in both cases), False on server error.
    """
    log.set(
        operation="revoke_token",
        revocation_endpoint=revocation_endpoint,
        token_type_hint=token_type_hint,
        client_id=client_id,
    )
    validate_https_url(revocation_endpoint)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }

    data = {
        "token": token,
        "token_type_hint": token_type_hint,
    }

    # Add client authentication if provided
    if client_id:
        if client_secret:
            # Use HTTP Basic auth for confidential clients
            credentials = f"{client_id}:{client_secret}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        else:
            # Public client - include client_id in body
            data["client_id"] = client_id

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                revocation_endpoint,
                data=data,
                headers=headers,
                timeout=timeout,
            )

            # Per RFC 7009 Section 2.2:
            # - 200: Token revoked successfully (or was already invalid)
            # - 400: Invalid request (e.g., unsupported token_type_hint)
            # - 503: Service unavailable
            if response.status_code == 200:
                log.info(f"Token revoked successfully at {revocation_endpoint}")
                return True

            # Log error but don't raise - revocation is best-effort
            log.warning(f"Token revocation returned {response.status_code}: {response.text}")
            return False

    except httpx.TimeoutException:
        log.warning(f"Token revocation timed out at {revocation_endpoint}")
        return False
    except Exception as e:
        log.warning(f"Token revocation failed: {e}")
        return False


async def introspect_token(
    introspection_endpoint: str,
    token: str,
    token_type_hint: str = "access_token",
    client_id: str | None = None,
    client_secret: str | None = None,
    timeout: int = 10,
) -> dict | None:
    """Introspect an OAuth token per RFC 7662.

    Returns the introspection response dict (with an ``active`` field), or None
    if introspection failed.
    """
    log.set(
        operation="introspect_token",
        introspection_endpoint=introspection_endpoint,
        token_type_hint=token_type_hint,
        client_id=client_id,
    )
    validate_https_url(introspection_endpoint)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": _CONTENT_TYPE_JSON,
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }

    data = {
        "token": token,
        "token_type_hint": token_type_hint,
    }

    # Add client authentication (usually required for introspection)
    if client_id:
        if client_secret:
            credentials = f"{client_id}:{client_secret}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        else:
            data["client_id"] = client_id

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                introspection_endpoint,
                data=data,
                headers=headers,
                timeout=timeout,
            )

            if response.status_code == 200:
                result = response.json()
                log.debug(f"Token introspection result: active={result.get('active')}")
                return result

            log.warning(f"Token introspection returned {response.status_code}: {response.text}")
            return None

    except httpx.TimeoutException:
        log.warning(f"Token introspection timed out at {introspection_endpoint}")
        return None
    except Exception as e:
        log.warning(f"Token introspection failed: {e}")
        return None


def parse_oauth_error_response(response: Any) -> dict:
    """Parse an OAuth error response per RFC 6749 Section 5.2."""
    result = {
        "error": "unknown_error",
        "error_description": None,
        "error_uri": None,
        "status_code": response.status_code,
    }

    content_type = response.headers.get("content-type", "")

    try:
        if _CONTENT_TYPE_JSON in content_type:
            data = response.json()
            result["error"] = data.get("error", "unknown_error")
            result["error_description"] = data.get("error_description")
            result["error_uri"] = data.get("error_uri")
        else:
            # Try to parse as JSON anyway (some servers don't set content-type)
            try:
                data = response.json()
                result["error"] = data.get("error", "unknown_error")
                result["error_description"] = data.get("error_description")
                result["error_uri"] = data.get("error_uri")
            except Exception:
                # Fall back to raw text
                result["error_description"] = response.text[:500]  # Truncate long errors
    except Exception as e:
        log.debug(f"Failed to parse OAuth error response: {e}")
        result["error_description"] = str(e)

    return result


def get_client_metadata_document_url(base_url: str) -> str:
    """Build the client metadata document URL from ``base_url``.

    Per draft-ietf-oauth-client-id-metadata-document, the client_id can be a
    URL pointing to this document.
    """
    return f"{base_url.rstrip('/')}/api/v1/oauth/client-metadata.json"


def validate_pkce_support(as_metadata: OAuthMetadata, integration_id: str) -> None:
    """Validate S256 PKCE support per MCP spec.

    The MCP Authorization spec requires clients to refuse to proceed if the
    server doesn't advertise S256 PKCE. Raises ValueError if requirements
    aren't met.
    """
    pkce_methods = as_metadata.code_challenge_methods_supported or []

    if not pkce_methods:
        raise ValueError(
            f"Server {integration_id} does not advertise PKCE support "
            "(code_challenge_methods_supported field is missing from OAuth metadata). "
            "MCP requires explicit PKCE support with S256 method."
        )

    if "S256" not in pkce_methods:
        if "plain" in pkce_methods:
            raise ValueError(
                f"Server {integration_id} only supports PKCE 'plain' method which is insecure. "
                "MCP requires S256 PKCE. Plain PKCE is not allowed."
            )
        raise ValueError(
            f"Server {integration_id} does not support S256 PKCE method. "
            f"Supported methods: {pkce_methods}. MCP requires S256."
        )


def validate_jwt_issuer(
    access_token: str,
    expected_issuer: str,
    integration_id: str,
) -> bool:
    """Validate a JWT's issuer claim against the expected authorization server.

    Returns True if the issuer matches or the token isn't a JWT, False on mismatch.
    """
    # Check if it looks like a JWT (3 dot-separated parts)
    parts = access_token.split(".")
    if len(parts) != 3:
        # Not a JWT, can't validate issuer
        return True

    try:
        # Decode payload (middle part)
        payload_b64 = parts[1]
        # Add padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)

        token_issuer = payload.get("iss")

        # Normalize URLs by removing trailing slashes for comparison
        # Per OAuth 2.0 spec, issuer URLs should be compared case-sensitively
        # but trailing slashes should be normalized
        if token_issuer:
            normalized_token = token_issuer.rstrip("/")
            normalized_expected = expected_issuer.rstrip("/")

            if normalized_token != normalized_expected:
                log.warning(
                    f"JWT issuer mismatch for {integration_id}: "
                    f"expected '{expected_issuer}', got '{token_issuer}'"
                )
                return False

        return True

    except Exception as e:
        log.debug(f"Could not validate JWT issuer for {integration_id}: {e}")
        # Don't fail on validation errors - token may be opaque
        return True


async def select_authorization_server(servers: list[str]) -> str:
    """Select an authorization server.

    Per MCP spec, Protected Resource Metadata may list multiple
    authorization_servers; defaults to the first.
    """
    if not servers:
        raise OAuthDiscoveryError("No authorization servers available")

    if len(servers) == 1:
        return servers[0]

    log.info(f"Multiple auth servers available ({len(servers)}), using first: {servers[0]}")
    return servers[0]
