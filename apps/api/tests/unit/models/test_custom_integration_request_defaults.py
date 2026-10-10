"""Default and constraint coverage for the custom-integration request model.

These fields are declared optional (default=) so callers such as the
add_custom_mcp_server tool can omit them; the defaults are load-bearing (a
missing bearer_token must stay None, a new server must default to private), so
they are pinned here.
"""

from pydantic import ValidationError
import pytest

from app.models.integration_models import CreateCustomIntegrationRequest


def test_optional_fields_default_to_safe_values() -> None:
    req = CreateCustomIntegrationRequest(name="Sentry", server_url="https://mcp.sentry.dev/mcp")

    assert req.description is None
    assert req.requires_auth is False
    assert req.auth_type is None
    assert req.is_public is False  # a freshly-added server is private by default
    assert req.bearer_token is None  # no secret unless one is explicitly supplied
    assert req.category == "custom"


def test_description_over_the_length_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateCustomIntegrationRequest(
            name="Sentry", server_url="https://mcp.sentry.dev/mcp", description="x" * 501
        )
