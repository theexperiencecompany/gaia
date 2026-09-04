"""SSRF guard behaviour for ``app.utils.url_safety``.

These tests are the regression fence for the SSRF policy: if a future edit
loosens the scheme allowlist, drops one of the reserved-range checks, or stops
rejecting a resolved private address, one of these assertions must fail loudly.
"""

from unittest.mock import patch

import pytest

from app.utils.url_safety import (
    assert_public_http_url,
    assert_public_http_url_sync,
    assert_safe_url_shape,
)

# Addresses that must always be refused, by category. 169.254.169.254 is the
# cloud metadata endpoint — the single most important target to keep blocked.
BLOCKED_LITERAL_HOSTS = [
    "https://127.0.0.1/",  # loopback v4
    "https://[::1]/",  # loopback v6
    "https://10.0.0.5/",  # private v4
    "https://192.168.1.1/",  # private v4
    "https://172.16.0.1/",  # private v4
    "https://169.254.169.254/",  # link-local / cloud metadata
    "https://0.0.0.0/",  # unspecified
    "https://[fe80::1]/",  # link-local v6
    "https://100.64.0.1/",  # CGNAT / shared address space (RFC 6598)
    "https://198.18.0.1/",  # benchmarking (RFC 2544)
]

BAD_SCHEME_URLS = [
    "ftp://example.com/",
    "file:///etc/passwd",
    "gopher://example.com/",
    "data:text/html,<script>alert(1)</script>",
]


# ---------------------------------------------------------------------------
# assert_safe_url_shape — synchronous, non-resolving pre-check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", BLOCKED_LITERAL_HOSTS)
def test_shape_rejects_literal_private_and_reserved_hosts(url: str) -> None:
    with pytest.raises(ValueError):
        assert_safe_url_shape(url)


@pytest.mark.parametrize("url", BAD_SCHEME_URLS)
def test_shape_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(ValueError):
        assert_safe_url_shape(url)


def test_shape_rejects_missing_host() -> None:
    with pytest.raises(ValueError):
        assert_safe_url_shape("https://")


def test_shape_rejects_malformed_url() -> None:
    # httpx.URL rejects a malformed authority (bad port) that urllib.parse would
    # silently accept.
    with pytest.raises(ValueError):
        assert_safe_url_shape("https://example.com:80x/")


def test_shape_validates_the_real_host_not_the_userinfo() -> None:
    # `user@host` — the guard must classify the true host (after @), so a public
    # -looking userinfo can't smuggle a request to an internal address.
    with pytest.raises(ValueError):
        assert_safe_url_shape("https://example.com@169.254.169.254/")


def test_shape_allows_public_literal_ip() -> None:
    # A public literal IP is fine — no DNS needed.
    assert_safe_url_shape("https://93.184.216.34/")


def test_shape_allows_https_public_literal_ip() -> None:
    assert_safe_url_shape("https://1.1.1.1/")


def test_shape_defers_hostnames_without_resolving() -> None:
    # The shape check must NOT resolve DNS (it runs in a sync pydantic
    # validator). A hostname — even a suspicious internal-looking one — is
    # allowed here; the resolving guard rejects it later at connect time.
    assert_safe_url_shape("https://example.com/mcp")
    assert_safe_url_shape("https://metadata.google.internal/")


# ---------------------------------------------------------------------------
# assert_public_http_url_sync — same policy for callers that cannot await
# ---------------------------------------------------------------------------


def test_sync_guard_allows_public_resolution() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["93.184.216.34"]):
        assert_public_http_url_sync("https://example.com/")  # must not raise


@pytest.mark.parametrize(
    "resolved_ip",
    ["169.254.169.254", "127.0.0.1", "10.0.0.5", "::1"],
)
def test_sync_guard_rejects_private_resolution(resolved_ip: str) -> None:
    # The sync guard exists for Composio's hook chain, which fetches
    # model-supplied URLs — it must enforce exactly the async policy.
    with (
        patch("app.utils.url_safety._resolve", return_value=[resolved_ip]),
        pytest.raises(ValueError, match="non-public"),
    ):
        assert_public_http_url_sync("https://rebind.example.com/")


def test_sync_guard_resolves_the_host_and_port_it_parsed() -> None:
    # The whole anti-rebinding property is that we validate the very endpoint
    # the caller is about to dial; resolving a different host:port would grade
    # an address nobody connects to.
    with patch("app.utils.url_safety._resolve", return_value=["93.184.216.34"]) as resolve:
        assert_public_http_url_sync("https://example.com/download?x=1")
    assert resolve.call_args.args == ("example.com", 443)


def test_sync_guard_defaults_the_port_from_the_scheme() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["93.184.216.34"]) as resolve:
        assert_public_http_url_sync("http://example.com/")
    assert resolve.call_args.args == ("example.com", 80)


def test_sync_guard_keeps_an_explicit_port() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["93.184.216.34"]) as resolve:
        assert_public_http_url_sync("https://example.com:8443/")
    assert resolve.call_args.args == ("example.com", 8443)


def test_sync_guard_rejects_bad_scheme_before_resolving() -> None:
    with patch("app.utils.url_safety._resolve") as mock_resolve:
        with pytest.raises(ValueError, match="scheme"):
            assert_public_http_url_sync("file:///etc/passwd")
        mock_resolve.assert_not_called()


def test_sync_guard_wraps_dns_failure_as_value_error() -> None:
    with (
        patch("app.utils.url_safety._resolve", side_effect=OSError("nxdomain")),
        pytest.raises(ValueError, match="DNS resolution failed"),
    ):
        assert_public_http_url_sync("https://does-not-resolve.example.com/")


# ---------------------------------------------------------------------------
# assert_public_http_url — async, resolves DNS then re-checks every address
# ---------------------------------------------------------------------------


async def test_public_url_allows_public_resolution() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["93.184.216.34"]):
        await assert_public_http_url("https://example.com/")  # must not raise


@pytest.mark.parametrize(
    "resolved_ip",
    ["169.254.169.254", "127.0.0.1", "10.0.0.5", "192.168.0.10", "::1", "fe80::1"],
)
async def test_public_url_rejects_private_resolution(resolved_ip: str) -> None:
    # DNS-rebinding defence: a public-looking hostname that resolves to an
    # internal address must be rejected.
    with patch("app.utils.url_safety._resolve", return_value=[resolved_ip]):
        with pytest.raises(ValueError):
            await assert_public_http_url("https://rebind.example.com/")


async def test_public_url_rejects_when_any_address_is_private() -> None:
    # getaddrinfo may return several records; a single internal answer must
    # sink the whole URL, not be masked by a public sibling.
    with patch(
        "app.utils.url_safety._resolve",
        return_value=["93.184.216.34", "169.254.169.254"],
    ):
        with pytest.raises(ValueError):
            await assert_public_http_url("https://mixed.example.com/")


async def test_public_url_rejects_bad_scheme_before_resolving() -> None:
    with patch("app.utils.url_safety._resolve") as mock_resolve:
        with pytest.raises(ValueError):
            await assert_public_http_url("ftp://example.com/")
        mock_resolve.assert_not_called()


async def test_public_url_wraps_dns_failure_as_value_error() -> None:
    with patch("app.utils.url_safety._resolve", side_effect=OSError("nxdomain")):
        with pytest.raises(ValueError):
            await assert_public_http_url("https://does-not-resolve.example.com/")
