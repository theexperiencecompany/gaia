"""SSRF shape validation on custom-integration request schemas.

The server_url field validator is the first SSRF gate for user-supplied MCP
endpoints. On GAIA Cloud a create/update pointing at the cloud-metadata endpoint
or a private host must be rejected at parse time; a self-hosted instance may
reach its own network, but never the metadata service.
"""

from pydantic import ValidationError
import pytest

from app.config.settings import settings
from app.schemas.integrations.requests import (
    CreateCustomIntegrationRequest,
    UpdateCustomIntegrationRequest,
)

PRIVATE_URLS = [
    "https://127.0.0.1:8000/mcp",  # loopback
    "https://10.0.0.5/mcp",  # private
    "https://192.168.1.10/mcp",  # private
    "https://[::1]/mcp",  # loopback v6
]

ALWAYS_BLOCKED_URLS = [
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://metadata.google.internal/computeMetadata/v1",  # cloud metadata by name
    "ftp://example.com/mcp",  # non-http scheme
    "file:///etc/passwd",  # non-http scheme
]


@pytest.fixture
def gaia_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "LOOPBACK_HOST_ALIAS", None)


@pytest.fixture
def selfhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOOPBACK_HOST_ALIAS", None)


@pytest.mark.parametrize("url", PRIVATE_URLS + ALWAYS_BLOCKED_URLS)
def test_gaia_cloud_create_rejects_unsafe_server_url(url: str, gaia_cloud: None) -> None:
    with pytest.raises(ValidationError):
        CreateCustomIntegrationRequest(name="evil", server_url=url)


@pytest.mark.parametrize("url", PRIVATE_URLS + ALWAYS_BLOCKED_URLS)
def test_gaia_cloud_update_rejects_unsafe_server_url(url: str, gaia_cloud: None) -> None:
    with pytest.raises(ValidationError):
        UpdateCustomIntegrationRequest(server_url=url)


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_selfhost_accepts_a_private_server_url(url: str, selfhost: None) -> None:
    assert CreateCustomIntegrationRequest(name="lan", server_url=url).server_url == url
    assert UpdateCustomIntegrationRequest(server_url=url).server_url == url


@pytest.mark.parametrize("url", ALWAYS_BLOCKED_URLS)
def test_selfhost_still_rejects_metadata_and_non_http_urls(url: str, selfhost: None) -> None:
    with pytest.raises(ValidationError):
        CreateCustomIntegrationRequest(name="evil", server_url=url)


@pytest.mark.parametrize(
    ("url", "dialed"),
    [
        ("http://localhost:8931/mcp", "http://host.docker.internal:8931/mcp"),
        ("http://127.0.0.1:8931/sse", "http://host.docker.internal:8931/sse"),
        ("http://[::1]:3000/mcp", "http://host.docker.internal:3000/mcp"),
        ("http://192.168.1.10:3000/mcp", "http://192.168.1.10:3000/mcp"),
    ],
)
def test_a_loopback_url_is_stored_as_the_host_alias_in_a_container(
    url: str, dialed: str, selfhost: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "LOOPBACK_HOST_ALIAS", "host.docker.internal")

    assert CreateCustomIntegrationRequest(name="local", server_url=url).server_url == dialed
    assert UpdateCustomIntegrationRequest(server_url=url).server_url == dialed


def test_create_request_accepts_public_https_url(gaia_cloud: None) -> None:
    req = CreateCustomIntegrationRequest(
        name="hackernews", server_url="https://mcp.example.com/sse"
    )
    assert req.server_url == "https://mcp.example.com/sse"


def test_update_request_allows_omitting_server_url() -> None:
    # server_url is optional on update; None must skip the guard, not crash.
    req = UpdateCustomIntegrationRequest(name="renamed")
    assert req.server_url is None
