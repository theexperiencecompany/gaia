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
import json
import re
import time
from typing import Any, Optional, Protocol
import ipaddress
from urllib.parse import urlparse

import httpx

from app.config.loggers import langchain_logger as logger

# MCP Protocol Version header value per MCP spec.
#
# Per MCP Authorization Specification, OAuth discovery requests SHOULD include
# the MCP-Protocol-Version header for protocol version negotiation.
#
# This value is sent in:
# - Protected Resource Metadata requests (RFC 9728)
# - Authorization Server Metadata requests (RFC 8414)
# - Dynamic Client Registration requests (RFC 7591)
# - Token requests and revocations
#
# Version: 2025-11-25 is the current stable MCP specification.
# See: https://modelcontextprotocol.io/specification/versioning
MCP_PROTOCOL_VERSION = "2025-11-25"

# Timeout constants for OAuth operations
# TLS handshakes can take 2-5 seconds on slow connections, so we use generous timeouts
OAUTH_PROBE_TIMEOUT = 10  # seconds - for initial server probe
OAUTH_DISCOVERY_TIMEOUT = 15  # seconds - for metadata discovery
OAUTH_TOKEN_TIMEOUT = 30  # seconds - for token operations


class OAuthSecurityError(Exception):
    """Raised when OAuth security requirements are not met."""

    pass


class OAuthDiscoveryError(Exception):
    """Raised when OAuth discovery fails."""

    pass


class TokenOperationError(Exception):
    """Raised when token operations (revocation, introspection) fail."""

    pass


def validate_https_url(url: str, allow_localhost: bool = True) -> None:
    """
    Validate that a URL uses HTTPS for security.

    Per OAuth 2.1 and MCP spec, all OAuth endpoints MUST use HTTPS
    except for localhost during development.

    Args:
        url: The URL to validate
        allow_localhost: Whether to allow HTTP for localhost (development)

    Raises:
        OAuthSecurityError: If URL is not HTTPS and not allowed localhost
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
            logger.debug(f"Allowing HTTP for localhost URL: {url}")
            return

    raise OAuthSecurityError(
        f"OAuth endpoint must use HTTPS: {url}. "
        "HTTP is only allowed for localhost during development."
    )


def is_localhost_url(url: str) -> bool:
    """
    Check if URL points to localhost or loopback address.

    Handles:
    - localhost (case-insensitive)
    - 127.0.0.0/8 (all IPv4 loopback addresses)
    - ::1 (IPv6 loopback)
    - 0.0.0.0 (all interfaces)

    Args:
        url: The URL to check

    Returns:
        True if URL points to localhost/loopback, False otherwise
    """
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


def validate_oauth_endpoints(oauth_config: dict, allow_localhost: bool = True) -> None:
    """
    Validate all OAuth endpoints use HTTPS.

    Args:
        oauth_config: OAuth configuration dict with endpoint URLs
        allow_localhost: Whether to allow HTTP for localhost

    Raises:
        OAuthSecurityError: If any endpoint is not HTTPS
    """
    endpoint_keys = [
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "revocation_endpoint",
        "introspection_endpoint",
        "issuer",
    ]

    for key in endpoint_keys:
        url = oauth_config.get(key)
        if url:
            try:
                validate_https_url(url, allow_localhost=allow_localhost)
            except OAuthSecurityError as e:
                raise OAuthSecurityError(f"Invalid {key}: {e}")


async def extract_auth_challenge(server_url: str) -> dict:
    """
    Probe MCP server and parse full WWW-Authenticate challenge per MCP spec.

    Per MCP Authorization spec Phase 1:
    - Server returns 401 with WWW-Authenticate header
    - Header may contain: resource_metadata, scope, error, error_description

    Returns dict with extracted fields (empty dict if no 401 or parse fails).
    """
    # Include MCP protocol version header per MCP spec
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    start_time = time.perf_counter()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                server_url, headers=headers, timeout=OAUTH_PROBE_TIMEOUT
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 401:
                www_auth = response.headers.get("WWW-Authenticate", "")
                result = {"raw": www_auth}

                # Regex pattern handles escaped quotes within quoted values
                # Matches: key="value" or key="value with \" escaped"
                def extract_quoted_value(key: str, header: str) -> Optional[str]:
                    # Match key="..." handling escaped quotes
                    pattern = rf'{key}="((?:[^"\\]|\\.)*)"'
                    match = re.search(pattern, header)
                    if match:
                        # Unescape any escaped quotes
                        return match.group(1).replace('\\"', '"')
                    return None

                rm_value = extract_quoted_value("resource_metadata", www_auth)
                if rm_value:
                    result["resource_metadata"] = rm_value

                scope_value = extract_quoted_value("scope", www_auth)
                if scope_value:
                    result["scope"] = scope_value

                error_value = extract_quoted_value("error", www_auth)
                if error_value:
                    result["error"] = error_value

                error_desc_value = extract_quoted_value("error_description", www_auth)
                if error_desc_value:
                    result["error_description"] = error_desc_value

                logger.info(
                    f"[TIMING] Probe {server_url}: 401 OAuth required, {elapsed_ms:.0f}ms"
                )
                logger.debug(f"Parsed WWW-Authenticate for {server_url}: {result}")
                return result

            logger.info(
                f"[TIMING] Probe {server_url}: {response.status_code} (no auth), {elapsed_ms:.0f}ms"
            )
            return {}

    except httpx.ConnectError as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        # Re-raise connection errors so caller can handle them appropriately
        logger.warning(
            f"[TIMING] Probe {server_url}: ConnectError after {elapsed_ms:.0f}ms - {e}"
        )
        raise

    except httpx.TimeoutException as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            f"[TIMING] Probe {server_url}: Timeout after {elapsed_ms:.0f}ms - {e}"
        )
        return {}

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            f"[TIMING] Probe {server_url}: Error after {elapsed_ms:.0f}ms - {type(e).__name__}: {e}"
        )
        return {}


async def find_protected_resource_metadata(server_url: str) -> Optional[str]:
    """
    Find Protected Resource Metadata via well-known URIs per RFC 9728 Section 5.2.

    Per MCP spec Phase 2b, when no resource_metadata in WWW-Authenticate header,
    try well-known URIs in order:
    1. Path-aware: {origin}/.well-known/oauth-protected-resource{path}
    2. Root: {origin}/.well-known/oauth-protected-resource

    Returns the URL that responds with valid JSON, or None.
    """
    parsed = urlparse(server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    candidates = []
    if path:
        candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    candidates.append(f"{origin}/.well-known/oauth-protected-resource")

    # Include MCP protocol version header per MCP spec
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    start_time = time.perf_counter()

    async with httpx.AsyncClient() as client:
        for url in candidates:
            try:
                response = await client.get(
                    url, headers=headers, timeout=OAUTH_DISCOVERY_TIMEOUT
                )
                if response.status_code == 200:
                    data = response.json()
                    if "authorization_servers" in data or "resource" in data:
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        logger.info(
                            f"[TIMING] Found PRM at {url} in {elapsed_ms:.0f}ms"
                        )
                        return url
            except Exception as e:
                logger.debug(f"PRM not found at {url}: {e}")

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.debug(
        f"[TIMING] PRM discovery failed for {server_url} after {elapsed_ms:.0f}ms"
    )
    return None


async def fetch_protected_resource_metadata(prm_url: str) -> dict:
    """
    Fetch Protected Resource Metadata (RFC 9728).

    Returns dict with 'authorization_servers', 'scopes_supported', etc.
    """
    # Include MCP protocol version header per MCP spec
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    start_time = time.perf_counter()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            prm_url, headers=headers, timeout=OAUTH_DISCOVERY_TIMEOUT
        )
        response.raise_for_status()
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"[TIMING] Fetched PRM from {prm_url} in {elapsed_ms:.0f}ms")
        return response.json()


async def fetch_auth_server_metadata(auth_server_url: str) -> dict:
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
    path = parsed.path.rstrip("/")

    candidate_urls = []

    # For issuer URLs with path components, try all discovery variants per MCP spec:
    # 1. OAuth 2.0 path insertion (RFC 8414 Section 3.1)
    # 2. OpenID Connect path insertion (RFC 8414 Section 5)
    # 3. OpenID Connect path appending (OIDC Discovery 1.0)
    if path:
        candidate_urls.append(f"{origin}/.well-known/oauth-authorization-server{path}")
        candidate_urls.append(f"{origin}/.well-known/openid-configuration{path}")
        candidate_urls.append(
            f"{auth_server_url.rstrip('/')}/.well-known/openid-configuration"
        )

    # For all URLs (with or without path), try standard root locations
    candidate_urls.append(f"{origin}/.well-known/oauth-authorization-server")
    candidate_urls.append(f"{origin}/.well-known/openid-configuration")

    # Include MCP protocol version header per MCP spec
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    start_time = time.perf_counter()

    async with httpx.AsyncClient() as client:
        for url in candidate_urls:
            try:
                response = await client.get(
                    url, headers=headers, timeout=OAUTH_DISCOVERY_TIMEOUT
                )
                if response.status_code == 200:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    logger.info(
                        f"[TIMING] Found auth server metadata at {url} in {elapsed_ms:.0f}ms"
                    )
                    return response.json()
            except Exception as e:
                logger.debug(f"Auth metadata not found at {url}: {e}")

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
    logger.info(
        f"[TIMING] Metadata discovery failed for {auth_server_url} after {elapsed_ms:.0f}ms, "
        "using MCP spec fallback URLs (origin-only, per spec)"
    )

    return {
        "authorization_endpoint": f"{origin}/authorize",
        "token_endpoint": f"{origin}/token",
        "registration_endpoint": f"{origin}/register",
        "issuer": origin,
        "fallback": True,  # Flag indicating these are fallback URLs, not discovered
    }


async def revoke_token(
    revocation_endpoint: str,
    token: str,
    token_type_hint: str = "access_token",
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    timeout: int = 10,
) -> bool:
    """
    Revoke an OAuth token per RFC 7009.

    Args:
        revocation_endpoint: The revocation endpoint URL
        token: The token to revoke
        token_type_hint: Either "access_token" or "refresh_token"
        client_id: Optional client ID for authentication
        client_secret: Optional client secret for authentication
        timeout: Request timeout in seconds

    Returns:
        True if revocation succeeded or token was already invalid,
        False if revocation failed due to server error.

    Note:
        Per RFC 7009, a successful response (200) indicates the token
        has been revoked or was already invalid. The server SHOULD
        respond with 200 even if the token was already revoked.
    """
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
                logger.info(f"Token revoked successfully at {revocation_endpoint}")
                return True

            # Log error but don't raise - revocation is best-effort
            logger.warning(
                f"Token revocation returned {response.status_code}: {response.text}"
            )
            return False

    except httpx.TimeoutException:
        logger.warning(f"Token revocation timed out at {revocation_endpoint}")
        return False
    except Exception as e:
        logger.warning(f"Token revocation failed: {e}")
        return False


async def introspect_token(
    introspection_endpoint: str,
    token: str,
    token_type_hint: str = "access_token",
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    timeout: int = 10,
) -> Optional[dict]:
    """
    Introspect an OAuth token per RFC 7662.

    Args:
        introspection_endpoint: The introspection endpoint URL
        token: The token to introspect
        token_type_hint: Either "access_token" or "refresh_token"
        client_id: Client ID for authentication (usually required)
        client_secret: Client secret for authentication
        timeout: Request timeout in seconds

    Returns:
        Token introspection response dict with 'active' field,
        or None if introspection failed.

    Example response:
        {
            "active": true,
            "scope": "read write",
            "client_id": "...",
            "exp": 1234567890,
            "iat": 1234567800,
            "sub": "user123"
        }
    """
    validate_https_url(introspection_endpoint)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
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
                logger.debug(
                    f"Token introspection result: active={result.get('active')}"
                )
                return result

            logger.warning(
                f"Token introspection returned {response.status_code}: {response.text}"
            )
            return None

    except httpx.TimeoutException:
        logger.warning(f"Token introspection timed out at {introspection_endpoint}")
        return None
    except Exception as e:
        logger.warning(f"Token introspection failed: {e}")
        return None


class HTTPResponseProtocol(Protocol):
    """Protocol for HTTP response objects (supports httpx.Response and mocks)."""

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Any: ...

    @property
    def text(self) -> str: ...

    def json(self) -> dict[str, Any]: ...


def parse_oauth_error_response(response: Any) -> dict:
    """
    Parse OAuth error response per RFC 6749 Section 5.2.

    Args:
        response: The HTTP response object

    Returns:
        Dict with 'error', 'error_description', and 'error_uri' fields
    """
    result = {
        "error": "unknown_error",
        "error_description": None,
        "error_uri": None,
        "status_code": response.status_code,
    }

    content_type = response.headers.get("content-type", "")

    try:
        if "application/json" in content_type:
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
                result["error_description"] = response.text[
                    :500
                ]  # Truncate long errors
    except Exception as e:
        logger.debug(f"Failed to parse OAuth error response: {e}")
        result["error_description"] = str(e)

    return result


def get_client_metadata_document_url(base_url: str) -> str:
    """
    Get the client metadata document URL.

    Per draft-ietf-oauth-client-id-metadata-document, the client_id
    can be a URL pointing to the client metadata document.

    Args:
        base_url: The API base URL (e.g., https://api.heygaia.com)

    Returns:
        The full URL to the client metadata document
    """
    return f"{base_url.rstrip('/')}/api/v1/oauth/client-metadata.json"


def validate_token_response(tokens: dict, integration_id: str) -> None:
    """
    Validate OAuth token response per OAuth 2.1 spec.

    Args:
        tokens: The token response dict
        integration_id: Integration ID for logging

    Raises:
        ValueError: If response is invalid
    """
    # access_token is REQUIRED
    if not tokens.get("access_token"):
        raise ValueError(
            f"Token response missing required 'access_token' for {integration_id}"
        )

    # token_type is REQUIRED and MUST be "Bearer" for MCP
    token_type = tokens.get("token_type", "")
    if not token_type:
        raise ValueError(
            f"Token response missing required 'token_type' for {integration_id}"
        )

    if token_type.lower() != "bearer":
        raise ValueError(
            f"Unsupported token_type '{token_type}' for {integration_id}. "
            "MCP requires Bearer tokens."
        )


def validate_pkce_support(oauth_config: dict, integration_id: str) -> None:
    """
    Validate PKCE support per MCP spec.

    Per MCP Authorization Spec:
    "MCP clients MUST verify PKCE support before proceeding. If
    code_challenge_methods_supported is absent, the authorization server
    does not support PKCE and MCP clients MUST refuse to proceed."

    Args:
        oauth_config: OAuth configuration with code_challenge_methods_supported
        integration_id: Integration ID for error messages

    Raises:
        ValueError: If PKCE requirements are not met
    """
    pkce_methods = oauth_config.get("code_challenge_methods_supported", [])

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
    """
    Validate JWT issuer claim matches expected authorization server.

    Args:
        access_token: The JWT access token
        expected_issuer: Expected issuer from OAuth discovery
        integration_id: Integration ID for logging

    Returns:
        True if issuer matches or token is not a JWT,
        False if issuer mismatch detected
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
                logger.warning(
                    f"JWT issuer mismatch for {integration_id}: "
                    f"expected '{expected_issuer}', got '{token_issuer}'"
                )
                return False

        return True

    except Exception as e:
        logger.debug(f"Could not validate JWT issuer for {integration_id}: {e}")
        # Don't fail on validation errors - token may be opaque
        return True


async def select_authorization_server(
    servers: list[str],
    preferred_server: Optional[str] = None,
) -> str:
    """
    Select an authorization server from available options.

    Per MCP spec, when Protected Resource Metadata returns multiple
    authorization_servers, the client MAY select one.

    Args:
        servers: List of authorization server URLs
        preferred_server: Optional preferred server URL

    Returns:
        Selected authorization server URL
    """
    if not servers:
        raise OAuthDiscoveryError("No authorization servers available")

    if len(servers) == 1:
        return servers[0]

    # Check for preferred server
    if preferred_server and preferred_server in servers:
        logger.info(f"Using preferred authorization server: {preferred_server}")
        return preferred_server

    # Default to first server
    logger.info(
        f"Multiple auth servers available ({len(servers)}), using first: {servers[0]}"
    )
    return servers[0]
