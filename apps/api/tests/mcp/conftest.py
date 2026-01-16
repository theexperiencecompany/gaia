"""
Shared fixtures and mocks for MCP OAuth testing.

Provides mock OAuth servers, token responses, and discovery metadata
for comprehensive testing of the MCP OAuth implementation.
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock

import httpx
import pytest


# ==============================================================================
# Mock Data Constants
# ==============================================================================

MOCK_SERVER_URL = "https://mcp.example.com"
MOCK_AUTH_SERVER_URL = "https://auth.example.com"
MOCK_CLIENT_ID = "test-client-id"
MOCK_CLIENT_SECRET = "test-client-secret"
MOCK_ACCESS_TOKEN = "test-access-token-12345"
MOCK_REFRESH_TOKEN = "test-refresh-token-67890"
MOCK_AUTHORIZATION_CODE = "test-auth-code-abcde"
MOCK_USER_ID = "test-user-123"
MOCK_INTEGRATION_ID = "test-mcp-integration"


# ==============================================================================
# Mock OAuth Metadata
# ==============================================================================


def get_mock_authorization_server_metadata(
    issuer: str = MOCK_AUTH_SERVER_URL,
    supports_pkce: bool = True,
    supports_dcr: bool = True,
    supports_revocation: bool = True,
    supports_introspection: bool = True,
    supports_client_metadata_doc: bool = False,
) -> dict:
    """Generate mock OAuth Authorization Server Metadata (RFC 8414)."""
    metadata = {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "scopes_supported": ["read", "write", "admin"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
    }

    if supports_pkce:
        metadata["code_challenge_methods_supported"] = ["S256"]

    if supports_dcr:
        metadata["registration_endpoint"] = f"{issuer}/register"

    if supports_revocation:
        metadata["revocation_endpoint"] = f"{issuer}/revoke"

    if supports_introspection:
        metadata["introspection_endpoint"] = f"{issuer}/introspect"

    if supports_client_metadata_doc:
        metadata["client_id_metadata_document_supported"] = True

    return metadata


def get_mock_protected_resource_metadata(
    resource: str = MOCK_SERVER_URL,
    auth_servers: Optional[list[str]] = None,
) -> dict:
    """Generate mock Protected Resource Metadata (RFC 9728)."""
    return {
        "resource": resource,
        "authorization_servers": auth_servers or [MOCK_AUTH_SERVER_URL],
        "scopes_supported": ["read", "write"],
    }


def get_mock_token_response(
    access_token: str = MOCK_ACCESS_TOKEN,
    refresh_token: Optional[str] = MOCK_REFRESH_TOKEN,
    token_type: str = "Bearer",
    expires_in: int = 3600,
) -> dict:
    """Generate mock OAuth token response."""
    response = {
        "access_token": access_token,
        "token_type": token_type,
        "expires_in": expires_in,
    }
    if refresh_token:
        response["refresh_token"] = refresh_token
    return response


def get_mock_dcr_response(
    client_id: str = MOCK_CLIENT_ID,
    client_secret: Optional[str] = None,
) -> dict:
    """Generate mock Dynamic Client Registration response (RFC 7591)."""
    response = {
        "client_id": client_id,
        "client_id_issued_at": int(datetime.now(timezone.utc).timestamp()),
        "registration_access_token": f"reg-token-{secrets.token_hex(8)}",
    }
    if client_secret:
        response["client_secret"] = client_secret
        response["client_secret_expires_at"] = 0  # Never expires
    return response


def get_mock_introspection_response(
    active: bool = True,
    scope: str = "read write",
    client_id: str = MOCK_CLIENT_ID,
    exp: Optional[int] = None,
) -> dict:
    """Generate mock token introspection response (RFC 7662)."""
    response: dict[str, Any] = {"active": active}
    if active:
        response["scope"] = scope
        response["client_id"] = client_id
        response["token_type"] = "Bearer"
        response["exp"] = exp or int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )
        response["iat"] = int(datetime.now(timezone.utc).timestamp())
    return response


def get_mock_www_authenticate_header(
    resource_metadata_url: Optional[str] = None,
    scope: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> str:
    """Generate mock WWW-Authenticate header."""
    parts = ["Bearer"]

    if resource_metadata_url:
        parts.append(f'resource_metadata="{resource_metadata_url}"')

    if scope:
        parts.append(f'scope="{scope}"')

    if error:
        parts.append(f'error="{error}"')

    if error_description:
        parts.append(f'error_description="{error_description}"')

    return " ".join(parts) if len(parts) == 1 else f"{parts[0]} {', '.join(parts[1:])}"


def generate_mock_jwt(
    issuer: str = MOCK_AUTH_SERVER_URL,
    subject: str = MOCK_USER_ID,
    audience: str = MOCK_SERVER_URL,
    exp_hours: int = 1,
) -> str:
    """Generate a mock JWT token (not cryptographically valid, for testing structure only)."""
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "exp": int(
            (datetime.now(timezone.utc) + timedelta(hours=exp_hours)).timestamp()
        ),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }

    def b64_encode(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    # Mock signature (not valid, just for structure)
    signature = base64.urlsafe_b64encode(b"mock-signature").decode().rstrip("=")

    return f"{b64_encode(header)}.{b64_encode(payload)}.{signature}"


# ==============================================================================
# Mock HTTP Responses
# ==============================================================================


@dataclass
class MockResponse:
    """Mock httpx.Response for testing."""

    status_code: int = 200
    content: bytes = b""
    headers: dict = field(default_factory=dict)
    _json_data: Optional[dict] = None

    def json(self) -> dict:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def raise_for_status(self) -> None:
        """Raise httpx.HTTPStatusError for 4xx/5xx responses."""
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                message=f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://test"),
                response=self,  # type: ignore
            )

    @classmethod
    def success(cls, data: dict) -> "MockResponse":
        return cls(
            status_code=200,
            content=json.dumps(data).encode(),
            headers={"content-type": "application/json"},
            _json_data=data,
        )

    @classmethod
    def unauthorized(
        cls,
        www_authenticate: Optional[str] = None,
    ) -> "MockResponse":
        headers = {}
        if www_authenticate:
            headers["WWW-Authenticate"] = www_authenticate
        return cls(status_code=401, content=b"Unauthorized", headers=headers)

    @classmethod
    def forbidden(
        cls,
        error: str = "insufficient_scope",
        scope: str = "admin",
    ) -> "MockResponse":
        www_auth = f'Bearer error="{error}", scope="{scope}"'
        return cls(
            status_code=403,
            content=b"Forbidden",
            headers={"WWW-Authenticate": www_auth},
        )

    @classmethod
    def error(
        cls,
        status_code: int,
        error: str,
        error_description: Optional[str] = None,
    ) -> "MockResponse":
        data = {"error": error}
        if error_description:
            data["error_description"] = error_description
        return cls(
            status_code=status_code,
            content=json.dumps(data).encode(),
            headers={"content-type": "application/json"},
            _json_data=data,
        )


# ==============================================================================
# Mock OAuth Server
# ==============================================================================


class MockOAuthServer:
    """
    Mock OAuth server for integration testing.

    Simulates a complete OAuth 2.1 authorization server with:
    - Authorization Server Metadata discovery
    - Protected Resource Metadata discovery
    - Dynamic Client Registration
    - Token endpoint (authorization_code + refresh_token grants)
    - Token revocation
    - Token introspection
    """

    def __init__(
        self,
        server_url: str = MOCK_SERVER_URL,
        auth_server_url: str = MOCK_AUTH_SERVER_URL,
        requires_auth: bool = True,
        supports_pkce: bool = True,
        supports_dcr: bool = True,
        supports_revocation: bool = True,
        supports_introspection: bool = True,
        supports_client_metadata_doc: bool = False,
    ):
        self.server_url = server_url
        self.auth_server_url = auth_server_url
        self.requires_auth = requires_auth
        self.supports_pkce = supports_pkce
        self.supports_dcr = supports_dcr
        self.supports_revocation = supports_revocation
        self.supports_introspection = supports_introspection
        self.supports_client_metadata_doc = supports_client_metadata_doc

        # State tracking
        self.registered_clients: dict[str, dict] = {}
        self.issued_tokens: dict[str, dict] = {}
        self.revoked_tokens: set[str] = set()
        self.authorization_codes: dict[str, dict] = {}

        # Request tracking for assertions
        self.requests: list[dict] = []

    def get_auth_server_metadata(self) -> dict:
        """Get authorization server metadata."""
        return get_mock_authorization_server_metadata(
            issuer=self.auth_server_url,
            supports_pkce=self.supports_pkce,
            supports_dcr=self.supports_dcr,
            supports_revocation=self.supports_revocation,
            supports_introspection=self.supports_introspection,
            supports_client_metadata_doc=self.supports_client_metadata_doc,
        )

    def get_protected_resource_metadata(self) -> dict:
        """Get protected resource metadata."""
        return get_mock_protected_resource_metadata(
            resource=self.server_url,
            auth_servers=[self.auth_server_url],
        )

    def register_client(self, client_name: str, redirect_uris: list[str]) -> dict:
        """Perform dynamic client registration."""
        client_id = f"client-{secrets.token_hex(8)}"
        dcr_response = get_mock_dcr_response(client_id=client_id)
        self.registered_clients[client_id] = {
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            **dcr_response,
        }
        return dcr_response

    def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str = "read write",
    ) -> str:
        """Create an authorization code."""
        code = f"code-{secrets.token_hex(16)}"
        self.authorization_codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "scope": scope,
            "created_at": datetime.now(timezone.utc),
        }
        return code

    def exchange_code(
        self,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict:
        """Exchange authorization code for tokens."""
        if code not in self.authorization_codes:
            raise ValueError("invalid_grant: Code not found")

        code_data = self.authorization_codes[code]

        # Validate client_id
        if code_data["client_id"] != client_id:
            raise ValueError("invalid_grant: Client ID mismatch")

        # Validate redirect_uri
        if code_data["redirect_uri"] != redirect_uri:
            raise ValueError("invalid_grant: Redirect URI mismatch")

        # Validate PKCE
        if self.supports_pkce:
            expected_challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(code_verifier.encode()).digest()
                )
                .decode()
                .rstrip("=")
            )
            if code_data["code_challenge"] != expected_challenge:
                raise ValueError("invalid_grant: PKCE verification failed")

        # Delete used code (single use)
        del self.authorization_codes[code]

        # Issue tokens
        token_response = get_mock_token_response()
        self.issued_tokens[token_response["access_token"]] = {
            "client_id": client_id,
            "scope": code_data["scope"],
            "created_at": datetime.now(timezone.utc),
        }

        return token_response

    def refresh_token(self, refresh_token: str, client_id: str) -> dict:
        """Refresh tokens using refresh_token grant."""
        if refresh_token in self.revoked_tokens:
            raise ValueError("invalid_grant: Token has been revoked")

        # Issue new tokens (with new refresh token for rotation)
        new_access = f"access-{secrets.token_hex(16)}"
        new_refresh = f"refresh-{secrets.token_hex(16)}"

        token_response = get_mock_token_response(
            access_token=new_access,
            refresh_token=new_refresh,
        )

        self.issued_tokens[new_access] = {
            "client_id": client_id,
            "created_at": datetime.now(timezone.utc),
        }

        return token_response

    def revoke_token(self, token: str) -> bool:
        """Revoke a token."""
        self.revoked_tokens.add(token)
        if token in self.issued_tokens:
            del self.issued_tokens[token]
        return True

    def introspect_token(self, token: str) -> dict:
        """Introspect a token."""
        if token in self.revoked_tokens:
            return {"active": False}

        if token in self.issued_tokens:
            token_data = self.issued_tokens[token]
            return get_mock_introspection_response(
                active=True,
                scope=token_data.get("scope", "read write"),
                client_id=token_data["client_id"],
            )

        return {"active": False}

    def handle_request(self, method: str, url: str, **kwargs) -> MockResponse:
        """Handle incoming request and return appropriate mock response."""
        self.requests.append({"method": method, "url": url, **kwargs})

        # Parse URL path
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path

        # Authorization Server Metadata discovery
        if "/.well-known/oauth-authorization-server" in path:
            return MockResponse.success(self.get_auth_server_metadata())

        if "/.well-known/openid-configuration" in path:
            return MockResponse.success(self.get_auth_server_metadata())

        # Protected Resource Metadata discovery
        if "/.well-known/oauth-protected-resource" in path:
            return MockResponse.success(self.get_protected_resource_metadata())

        # MCP server probe (returns 401 if auth required)
        if url == self.server_url and method.upper() == "GET":
            if self.requires_auth:
                www_auth = get_mock_www_authenticate_header(
                    resource_metadata_url=f"{self.server_url}/.well-known/oauth-protected-resource",
                    scope="read write",
                )
                return MockResponse.unauthorized(www_authenticate=www_auth)
            return MockResponse.success({"status": "ok"})

        # Dynamic Client Registration
        if path == "/register" and method.upper() == "POST":
            if not self.supports_dcr:
                return MockResponse.error(404, "not_found", "DCR not supported")

            data = kwargs.get("json", {})
            dcr_response = self.register_client(
                client_name=data.get("client_name", "Unknown"),
                redirect_uris=data.get("redirect_uris", []),
            )
            return MockResponse.success(dcr_response)

        # Token endpoint
        if path == "/token" and method.upper() == "POST":
            data = kwargs.get("data", {})
            grant_type = data.get("grant_type")

            try:
                if grant_type == "authorization_code":
                    token_response = self.exchange_code(
                        code=data.get("code", ""),
                        client_id=data.get("client_id", ""),
                        redirect_uri=data.get("redirect_uri", ""),
                        code_verifier=data.get("code_verifier", ""),
                    )
                    return MockResponse.success(token_response)

                elif grant_type == "refresh_token":
                    token_response = self.refresh_token(
                        refresh_token=data.get("refresh_token", ""),
                        client_id=data.get("client_id", ""),
                    )
                    return MockResponse.success(token_response)

                else:
                    return MockResponse.error(400, "unsupported_grant_type")

            except ValueError as e:
                error_msg = str(e)
                error_code = (
                    error_msg.split(":")[0] if ":" in error_msg else "invalid_request"
                )
                error_desc = (
                    error_msg.split(":")[1].strip() if ":" in error_msg else error_msg
                )
                return MockResponse.error(400, error_code, error_desc)

        # Token revocation
        if path == "/revoke" and method.upper() == "POST":
            if not self.supports_revocation:
                return MockResponse.error(404, "not_found", "Revocation not supported")

            data = kwargs.get("data", {})
            token = data.get("token", "")
            self.revoke_token(token)
            return MockResponse(status_code=200, content=b"")

        # Token introspection
        if path == "/introspect" and method.upper() == "POST":
            if not self.supports_introspection:
                return MockResponse.error(
                    404, "not_found", "Introspection not supported"
                )

            data = kwargs.get("data", {})
            token = data.get("token", "")
            result = self.introspect_token(token)
            return MockResponse.success(result)

        # Default: 404
        return MockResponse.error(404, "not_found", f"Unknown endpoint: {path}")


# ==============================================================================
# Pytest Fixtures
# ==============================================================================


@pytest.fixture
def mock_oauth_server():
    """Create a mock OAuth server with default settings."""
    return MockOAuthServer()


@pytest.fixture
def mock_oauth_server_no_auth():
    """Create a mock OAuth server that doesn't require authentication."""
    return MockOAuthServer(requires_auth=False)


@pytest.fixture
def mock_oauth_server_no_dcr():
    """Create a mock OAuth server without DCR support."""
    return MockOAuthServer(supports_dcr=False)


@pytest.fixture
def mock_oauth_server_client_metadata():
    """Create a mock OAuth server with client metadata document support."""
    return MockOAuthServer(supports_client_metadata_doc=True)


@pytest.fixture
def mock_http_client(mock_oauth_server):
    """
    Create a mock httpx.AsyncClient that routes requests to the mock server.

    Usage:
        async with mock_http_client as client:
            response = await client.get("https://mcp.example.com")
    """

    class MockAsyncClient:
        def __init__(self, server: MockOAuthServer):
            self.server = server

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url: str, **kwargs) -> MockResponse:
            return self.server.handle_request("GET", url, **kwargs)

        async def post(self, url: str, **kwargs) -> MockResponse:
            return self.server.handle_request("POST", url, **kwargs)

    return MockAsyncClient(mock_oauth_server)


@pytest.fixture
def mock_mcp_config():
    """Create a mock MCPConfig for testing."""
    from app.models.oauth_models import MCPConfig

    return MCPConfig(
        server_url=MOCK_SERVER_URL,
        requires_auth=True,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
    )


@pytest.fixture
def mock_mcp_config_no_auth():
    """Create a mock MCPConfig without authentication."""
    from app.models.oauth_models import MCPConfig

    return MCPConfig(
        server_url=MOCK_SERVER_URL,
        requires_auth=False,
    )


@pytest.fixture
def mock_token_store():
    """Create a mock MCPTokenStore."""
    store = AsyncMock()

    # Default return values
    store.get_oauth_discovery.return_value = None
    store.get_oauth_token.return_value = MOCK_ACCESS_TOKEN
    store.get_refresh_token.return_value = MOCK_REFRESH_TOKEN
    store.get_dcr_client.return_value = None
    store.is_token_expiring_soon.return_value = False
    store.has_credentials.return_value = True
    store.verify_oauth_state.return_value = (True, "test-code-verifier")

    # Methods that return None
    store.store_oauth_tokens.return_value = None
    store.store_oauth_discovery.return_value = None
    store.store_dcr_client.return_value = None
    store.store_oauth_nonce.return_value = None
    store.delete_credentials.return_value = None
    store.create_oauth_state.return_value = "test-state-token"

    return store


@pytest.fixture
def pkce_pair():
    """Generate a PKCE code_verifier and code_challenge pair."""
    from app.utils.mcp_utils import generate_pkce_pair

    return generate_pkce_pair()
