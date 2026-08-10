"""SSRF shape validation on custom-integration request schemas.

The ``server_url`` field validator is the first SSRF gate for user-supplied MCP
endpoints. If it is removed or weakened, a create/update request pointing at the
cloud-metadata endpoint or a private host must still be rejected at parse time.
"""

from pydantic import ValidationError
import pytest

from app.schemas.integrations.requests import (
    CreateCustomIntegrationRequest,
    UpdateCustomIntegrationRequest,
)

BLOCKED_URLS = [
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata
    "https://127.0.0.1:8000/mcp",  # loopback
    "https://10.0.0.5/mcp",  # private
    "https://192.168.1.10/mcp",  # private
    "https://[::1]/mcp",  # loopback v6
    "ftp://example.com/mcp",  # non-http scheme
    "file:///etc/passwd",  # non-http scheme
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_create_request_rejects_unsafe_server_url(url: str) -> None:
    with pytest.raises(ValidationError):
        CreateCustomIntegrationRequest(name="evil", server_url=url)


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_update_request_rejects_unsafe_server_url(url: str) -> None:
    with pytest.raises(ValidationError):
        UpdateCustomIntegrationRequest(server_url=url)


def test_create_request_accepts_public_https_url() -> None:
    req = CreateCustomIntegrationRequest(
        name="hackernews", server_url="https://mcp.example.com/sse"
    )
    assert req.server_url == "https://mcp.example.com/sse"


def test_update_request_allows_omitting_server_url() -> None:
    # server_url is optional on update; None must skip the guard, not crash.
    req = UpdateCustomIntegrationRequest(name="renamed")
    assert req.server_url is None
