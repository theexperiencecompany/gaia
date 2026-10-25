"""The custom MCP URL a user types becomes the URL this process stores and dials."""

import pytest

from app.config.settings import settings
from app.helpers.mcp_helpers import dialable_mcp_server_url

ALIAS = "host.docker.internal"


@pytest.fixture
def in_a_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOOPBACK_HOST_ALIAS", ALIAS)


@pytest.mark.usefixtures("in_a_container")
@pytest.mark.parametrize(
    ("url", "dialed"),
    [
        ("http://localhost:8931/mcp", f"http://{ALIAS}:8931/mcp"),
        ("http://LOCALHOST:8931/mcp", f"http://{ALIAS}:8931/mcp"),
        ("http://localhost.:8931/mcp", f"http://{ALIAS}:8931/mcp"),
        ("http://localhost.localdomain/sse", f"http://{ALIAS}/sse"),
        ("http://127.0.0.2:3000/mcp?token=a", f"http://{ALIAS}:3000/mcp?token=a"),
        ("http://[::1]:3000/mcp", f"http://{ALIAS}:3000/mcp"),
    ],
)
def test_a_loopback_host_is_pointed_at_the_host_alias(url: str, dialed: str) -> None:
    assert dialable_mcp_server_url(url) == dialed


@pytest.mark.usefixtures("in_a_container")
@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:3000/mcp",
        "http://localhost-proxy.lan/mcp",
        "https://mcp.example.com/sse",
    ],
)
def test_a_host_that_is_not_loopback_is_kept(url: str) -> None:
    assert dialable_mcp_server_url(url) == url


def test_without_an_alias_a_loopback_url_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOOPBACK_HOST_ALIAS", None)

    assert dialable_mcp_server_url("http://localhost:8931/mcp") == "http://localhost:8931/mcp"


def test_gaia_cloud_refuses_a_loopback_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "LOOPBACK_HOST_ALIAS", None)

    with pytest.raises(
        ValueError, match=r"^refusing to connect to non-public address 127\.0\.0\.1$"
    ):
        dialable_mcp_server_url("http://127.0.0.1:8931/mcp")


@pytest.mark.usefixtures("in_a_container")
def test_the_aliased_url_is_still_checked_against_the_metadata_service() -> None:
    with pytest.raises(ValueError, match=r"^refusing to connect to metadata host"):
        dialable_mcp_server_url("http://metadata.google.internal/computeMetadata/v1")


@pytest.mark.usefixtures("in_a_container")
def test_a_malformed_url_is_refused_as_malformed() -> None:
    with pytest.raises(ValueError, match=r"^malformed URL: "):
        dialable_mcp_server_url("http://[::1/mcp")
