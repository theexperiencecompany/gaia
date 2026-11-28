"""SSRF guard behaviour for app.utils.url_safety.

These tests are the regression fence for the SSRF policy: if a future edit
loosens the scheme allowlist, drops one of the reserved-range checks, or stops
rejecting a resolved private address, one of these assertions must fail loudly.
"""

from unittest.mock import patch

import pytest

from app.utils.url_safety import (
    CredentialsNeedHttpsError,
    assert_endpoint_url_allowed,
    assert_endpoint_url_shape,
    assert_may_carry_credentials,
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


PRIVATE_ENDPOINTS = [
    "http://127.0.0.1:8931/mcp",
    "http://[::1]:8931/mcp",
    "http://192.168.1.20/mcp",
    "http://10.0.0.5:3000/sse",
]

ALWAYS_REFUSED_ENDPOINTS = [
    "http://169.254.169.254/latest/meta-data",
    "http://[fe80::1]/mcp",
    "http://[::ffff:169.254.169.254]/",
    "http://0.0.0.0:8000/mcp",
    "http://metadata.google.internal/computeMetadata/v1",
    "http://user:pass@192.168.1.20/mcp",
    "file:///etc/passwd",
]


@pytest.mark.parametrize("url", PRIVATE_ENDPOINTS)
def test_endpoint_shape_allows_a_private_host_only_when_allowed(url: str) -> None:
    assert_endpoint_url_shape(url, allow_private=True)
    with pytest.raises(ValueError):
        assert_endpoint_url_shape(url, allow_private=False)


@pytest.mark.parametrize("url", ALWAYS_REFUSED_ENDPOINTS)
def test_endpoint_shape_refuses_metadata_link_local_and_credentials_even_when_allowed(
    url: str,
) -> None:
    with pytest.raises(ValueError):
        assert_endpoint_url_shape(url, allow_private=True)


async def test_endpoint_allows_a_name_resolving_to_a_lan_address_only_when_allowed() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["192.168.65.254"]) as resolve:
        await assert_endpoint_url_allowed(
            "http://host.docker.internal:8931/mcp", allow_private=True
        )
        resolve.assert_called_once_with("host.docker.internal", 8931)
        with pytest.raises(ValueError):
            await assert_endpoint_url_allowed(
                "http://host.docker.internal:8931/mcp", allow_private=False
            )


async def test_endpoint_refuses_a_name_resolving_to_the_metadata_address_even_when_allowed() -> (
    None
):
    with patch("app.utils.url_safety._resolve", return_value=["169.254.169.254"]):
        with pytest.raises(ValueError):
            await assert_endpoint_url_allowed("http://rebind.example.com/", allow_private=True)


async def test_endpoint_wraps_dns_failure_as_value_error() -> None:
    with patch("app.utils.url_safety._resolve", side_effect=OSError("nxdomain")):
        with pytest.raises(ValueError, match=r"^DNS resolution failed: nxdomain$"):
            await assert_endpoint_url_allowed("http://nope.invalid/", allow_private=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://user@192.168.1.20/mcp",
        "http://:secret@192.168.1.20/mcp",
        "http://user:secret@192.168.1.20/mcp",
    ],
)
def test_endpoint_refuses_a_username_or_a_password_on_its_own(url: str) -> None:
    with pytest.raises(ValueError, match=r"^URL must not embed credentials$"):
        assert_endpoint_url_shape(url, allow_private=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal./computeMetadata/v1",
        "http://METADATA/",
        "http://metadata../",
    ],
)
def test_endpoint_refuses_a_metadata_hostname_written_with_trailing_dots_or_capitals(
    url: str,
) -> None:
    with pytest.raises(ValueError, match=r"^refusing to connect to metadata host metadata"):
        assert_endpoint_url_shape(url, allow_private=True)


def test_endpoint_names_the_link_local_address_it_refuses() -> None:
    with pytest.raises(
        ValueError,
        match=r"^refusing to connect to link-local or reserved address 169\.254\.169\.254$",
    ):
        assert_endpoint_url_shape("http://169.254.169.254/latest/meta-data", allow_private=True)


# --- a token only travels over https, or plain http inside the local network ---

LAN_HTTP_URLS = [
    "http://localhost:8080/mcp",
    "http://LOCALHOST./mcp",
    "http://127.0.0.1/mcp",
    "http://127.8.9.10/mcp",
    "http://[::1]:9000/mcp",
    "http://10.1.2.3/mcp",
    "http://172.16.0.1/mcp",
    "http://172.31.255.254/mcp",
    "http://192.168.1.20/mcp",
    "http://169.254.10.10/mcp",
    "http://[fe80::1]/mcp",
    "http://[fd12:3456::1]/mcp",
    "http://[::ffff:192.168.1.20]/mcp",
    "http://printer.local/mcp",
    "http://100.64.0.1/mcp",  # Tailscale / WireGuard CGNAT
    "http://100.127.255.254/mcp",
]

PUBLIC_HTTP_URLS = [
    "http://93.184.216.34/mcp",
    "http://172.32.0.1/mcp",  # just past 172.16.0.0/12
    "http://100.128.0.1/mcp",  # just past 100.64.0.0/10
    "http://100.63.255.255/mcp",  # just before it
    "http://[2606:4700::1111]/mcp",
    "http://[::ffff:93.184.216.34]/mcp",
]


@pytest.mark.parametrize("url", LAN_HTTP_URLS)
async def test_plain_http_to_the_local_network_may_carry_a_token(url: str) -> None:
    await assert_may_carry_credentials(url)


@pytest.mark.parametrize("url", PUBLIC_HTTP_URLS)
async def test_plain_http_to_a_public_host_may_not_carry_a_token(url: str) -> None:
    with pytest.raises(CredentialsNeedHttpsError) as raised:
        await assert_may_carry_credentials(url)
    assert str(raised.value) == (
        "This server needs a sign-in, so its URL has to start with https://. "
        "Plain http works only for a server on this machine or your local network."
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/mcp",
        "http://LOCALHOST./mcp",
        "http://printer.local./mcp",
        "http://10.1.2.3/mcp",
        "http://[::1]/mcp",
    ],
)
async def test_local_names_and_literal_addresses_are_judged_without_a_lookup(url: str) -> None:
    with patch("app.utils.url_safety._resolve", return_value=["93.184.216.34"]) as resolve:
        await assert_may_carry_credentials(url)
    resolve.assert_not_called()


async def test_https_carries_a_token_without_a_lookup() -> None:
    with patch("app.utils.url_safety._resolve") as resolve:
        await assert_may_carry_credentials("https://mcp.resend.com/mcp")
    resolve.assert_not_called()


async def test_a_tailnet_name_carries_a_token_because_it_resolves_into_the_tailnet() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["100.101.102.103"]):
        await assert_may_carry_credentials("http://gaia-home-server.taila76294.ts.net:8000/mcp")


async def test_a_hostname_is_judged_by_every_address_it_resolves_to() -> None:
    with patch("app.utils.url_safety._resolve", return_value=["192.168.1.5"]) as resolve:
        await assert_may_carry_credentials("http://nas.lan:8123/mcp")
    resolve.assert_called_once_with("nas.lan", 8123)

    with (
        patch("app.utils.url_safety._resolve", return_value=["192.168.1.5", "93.184.216.34"]),
        pytest.raises(CredentialsNeedHttpsError),
    ):
        await assert_may_carry_credentials("http://nas.lan/mcp")


async def test_an_unresolvable_host_is_a_lookup_failure_not_a_policy_refusal() -> None:
    with (
        patch("app.utils.url_safety._resolve", side_effect=OSError("no such host")),
        pytest.raises(ValueError, match="DNS resolution failed: no such host") as raised,
    ):
        await assert_may_carry_credentials("http://nowhere.example/mcp")
    assert not isinstance(raised.value, CredentialsNeedHttpsError)
