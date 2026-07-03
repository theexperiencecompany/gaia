"""SSRF guard behaviour for ``app.utils.url_safety``.

These tests are the regression fence for the SSRF policy: if a future edit
loosens the scheme allowlist, drops one of the reserved-range checks, or stops
rejecting a resolved private address, one of these assertions must fail loudly.
"""

from unittest.mock import patch

import pytest

from app.utils.url_safety import assert_public_http_url, assert_safe_url_shape

# Addresses that must always be refused, by category. 169.254.169.254 is the
# cloud metadata endpoint — the single most important target to keep blocked.
BLOCKED_LITERAL_HOSTS = [
    "http://127.0.0.1/",  # loopback v4
    "http://[::1]/",  # loopback v6
    "http://10.0.0.5/",  # private v4
    "http://192.168.1.1/",  # private v4
    "http://172.16.0.1/",  # private v4
    "http://169.254.169.254/",  # link-local / cloud metadata
    "http://0.0.0.0/",  # unspecified
    "http://[fe80::1]/",  # link-local v6
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


def test_shape_allows_public_literal_ip() -> None:
    # A public literal IP is fine — no DNS needed.
    assert_safe_url_shape("http://93.184.216.34/")


def test_shape_allows_https_public_literal_ip() -> None:
    assert_safe_url_shape("https://1.1.1.1/")


def test_shape_defers_hostnames_without_resolving() -> None:
    # The shape check must NOT resolve DNS (it runs in a sync pydantic
    # validator). A hostname — even a suspicious internal-looking one — is
    # allowed here; the resolving guard rejects it later at connect time.
    assert_safe_url_shape("https://example.com/mcp")
    assert_safe_url_shape("http://metadata.google.internal/")


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
