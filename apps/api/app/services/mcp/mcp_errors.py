"""Errors the MCP client raises, and the classifier that tells dead OAuth credentials from transient failures."""

import re

from pydantic import BaseModel, ConfigDict, JsonValue

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


class _OAuthErrorBody(BaseModel):
    """The one key of an HTTP error body that says why a grant failed (RFC 6749 §5.2)."""

    model_config = ConfigDict(extra="ignore")

    error: JsonValue = None


class DCRNotSupportedError(Exception):
    """Raised when Dynamic Client Registration is not supported by the server."""


class DCRRegistrationError(ValueError):
    """Raised when an authorization server rejects our DCR (identified rejection).

    Subclasses ValueError to preserve the existing caller contract (callers that
    catch ValueError still work), while letting callers distinguish an external
    AS rejection from an internal failure that also raises a bare ValueError.
    """


class StepUpAuthRequiredError(Exception):
    """Raised when additional scopes are required (403 insufficient_scope).

    Per MCP spec, this triggers re-authorization with additional scopes.
    """

    def __init__(self, integration_id: str, required_scopes: list[str]):
        self.integration_id = integration_id
        self.required_scopes = required_scopes
        super().__init__(f"Step-up authorization required for {integration_id}: {required_scopes}")


class MCPIntegrationNotFoundError(ValueError):
    """Raised when an integration id resolves to no MCP integration (a stale connection record).

    Subclasses ValueError to keep the existing caller contract.
    """

    def __init__(self, integration_id: str) -> None:
        self.integration_id = integration_id
        super().__init__(f"MCP integration {integration_id} not found")


class MCPAuthorizationRequiredError(ValueError):
    """Raised when an authenticated MCP has no usable access token."""

    def __init__(self, integration_id: str) -> None:
        super().__init__(
            f"No valid token for {integration_id}. "
            "OAuth authorization required - user must complete the OAuth flow."
        )


# OAuth 2.0 error codes (RFC 6749 §5.2) that mean the grant is permanently dead.
_TERMINAL_OAUTH_ERROR_CODES: frozenset[str] = frozenset(
    {"invalid_grant", "invalid_token", "revoked_token", "expired_token"}
)


def _extract_response_signal(exception: Exception) -> tuple[int | None, str | None]:
    """Return (status_code, oauth_error_code) from an exception with an HTTP response.

    (None, None) for network-layer errors that don't carry a response.
    """
    response = getattr(exception, "response", None)
    if response is None:
        return None, None

    status = getattr(response, "status_code", None)
    error_code: str | None = None
    try:
        body = response.json() if callable(getattr(response, "json", None)) else None
        if isinstance(body, dict):
            raw = _OAuthErrorBody.model_validate(body).error
            if isinstance(raw, str):
                error_code = raw.lower()
    except Exception as parse_err:
        log.debug(
            f"{LogTag.MCP} _extract_response_signal: body parse skipped",
            error=str(parse_err),
            error_type=type(parse_err).__name__,
        )
    return status, error_code


def is_terminal_auth_failure(exception: Exception, refresh_attempted: bool = False) -> bool:
    """Return True only when credentials are demonstrably dead.

    Treating every exception as terminal wipes integrations on transient
    errors (5xx, network blip, transport mismatch). Require a spec'd OAuth error
    code or a 401/403 signal after a refresh attempt.
    """
    status, error_code = _extract_response_signal(exception)

    if error_code in _TERMINAL_OAUTH_ERROR_CODES:
        return True

    if refresh_attempted and status in (401, 403):
        return True

    # No response attached (network-layer error): match a standalone status
    # token, not a port or path inside a URL (https://host:403/ must not read
    # as an authorization signal) and not a longer token like "401k".
    if getattr(exception, "response", None) is None:
        msg = str(exception).lower()
        if refresh_attempted and re.search(r"(?<![:\w/])(?:401|403)(?![\w/])", msg):
            return True
        for code in _TERMINAL_OAUTH_ERROR_CODES:
            if re.search(rf"\b{re.escape(code)}\b", msg):
                return True

    return False
