"""Unit tests for app.utils.favicon_utils — favicon fetching with Redis caching."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.favicon_utils import (
    _fetch_favicon_impl,
    _fetch_smithery_icon,
    _get_domain_cache_key,
    _get_host_url,
    _parse_favicon_size,
    _parse_icons_from_html,
    _select_best_icon,
    _smithery_qualified_name,
    _validate_favicon_url,
    fetch_favicon_from_url,
    legacy_favicon_url,
)

# ---------------------------------------------------------------------------
# _get_domain_cache_key / _get_host_url — keyed by full host
# ---------------------------------------------------------------------------


class TestGetDomainCacheKey:
    """Tests for _get_domain_cache_key — caches per full host."""

    def test_simple_url(self) -> None:
        """Standard URL yields favicon:<host> cache key."""
        assert _get_domain_cache_key("https://example.com/some/path") == "favicon:example.com"

    def test_subdomain_is_kept(self) -> None:
        """Subdomains are preserved so co-hosted MCP servers don't collide."""
        key = _get_domain_cache_key("https://sub.deep.example.com")
        assert key == "favicon:sub.deep.example.com"

    def test_url_with_port_kept(self) -> None:
        """Host (with port) is used verbatim."""
        key = _get_domain_cache_key("https://app.example.org:8443/path")
        assert key == "favicon:app.example.org:8443"

    def test_host_url_includes_scheme_and_full_host(self) -> None:
        """_get_host_url returns scheme + full host, no path."""
        assert _get_host_url("https://sub.example.com/a/b") == "https://sub.example.com"


# ---------------------------------------------------------------------------
# legacy_favicon_url — Google S2 on the registered domain
# ---------------------------------------------------------------------------


class TestLegacyFaviconUrl:
    """Tests for legacy_favicon_url — the default fallback."""

    def test_uses_registered_domain(self) -> None:
        """The fallback keys Google's service by the registered domain."""
        url = legacy_favicon_url("https://sub.deep.example.com/path")
        assert url == "https://www.google.com/s2/favicons?domain=example.com&sz=256"


# ---------------------------------------------------------------------------
# _smithery_qualified_name
# ---------------------------------------------------------------------------


class TestSmitheryQualifiedName:
    """Tests for _smithery_qualified_name — extract qualified name from URL."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://server.smithery.ai/@owner/name", "@owner/name"),
            ("https://server.smithery.ai/brave", "brave"),
            ("https://server.smithery.ai/google/scholar/mcp", "google/scholar"),
            ("https://server.smithery.ai/@owner/name/sse", "@owner/name"),
            ("https://smithery.ai/@owner/name", "@owner/name"),
        ],
        ids=["owner_name", "slug", "strips_mcp", "strips_sse", "apex_host"],
    )
    def test_smithery_hosts(self, url: str, expected: str) -> None:
        """Smithery hosts yield the path as the qualified name (transport stripped)."""
        assert _smithery_qualified_name(url) == expected

    @pytest.mark.parametrize(
        "url",
        ["https://example.com/foo", "https://mcp.notsmithery.io/x"],
        ids=["other_host", "lookalike"],
    )
    def test_non_smithery_returns_none(self, url: str) -> None:
        """Non-Smithery hosts return None."""
        assert _smithery_qualified_name(url) is None


# ---------------------------------------------------------------------------
# _parse_favicon_size
# ---------------------------------------------------------------------------


class TestParseFaviconSize:
    """Tests for _parse_favicon_size — parse sizes attribute from link tags."""

    @pytest.mark.parametrize(
        "sizes_attr,expected",
        [
            ("32x32", 32),
            ("16x16", 16),
            ("256x128", 256),
            ("128x256", 256),
            ("48x48 96x96", 96),
        ],
        ids=["square_32", "square_16", "wider_rect", "taller_rect", "multiple_sizes_picks_max"],
    )
    def test_valid_sizes(self, sizes_attr: str, expected: int) -> None:
        """Valid NxN or WxH size strings are parsed correctly."""
        assert _parse_favicon_size(sizes_attr) == expected

    def test_empty_string_returns_zero(self) -> None:
        """Empty sizes attribute returns 0."""
        assert _parse_favicon_size("") == 0

    def test_none_returns_zero(self) -> None:
        """None sizes attribute returns 0 (falsy check)."""
        assert _parse_favicon_size(None) == 0  # type: ignore[arg-type]

    def test_invalid_format_returns_zero(self) -> None:
        """Non-numeric size string returns 0."""
        assert _parse_favicon_size("any") == 0

    def test_partially_invalid_returns_zero_for_bad_part(self) -> None:
        """Invalid dimension parts (non-numeric) are skipped via ValueError."""
        assert _parse_favicon_size("abcxdef") == 0


# ---------------------------------------------------------------------------
# _parse_icons_from_html
# ---------------------------------------------------------------------------


class TestParseIconsFromHtml:
    """Tests for _parse_icons_from_html — extract link[rel=icon] from HTML."""

    def test_extracts_icons_from_valid_html(self) -> None:
        """Standard link[rel=icon] tags are extracted with correct format/size."""
        html = """
        <html><head>
            <link rel="icon" href="/favicon.ico" sizes="16x16">
            <link rel="icon" href="/icon-192.png" sizes="192x192">
            <link rel="icon" href="/icon.svg" type="image/svg+xml">
        </head><body></body></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com")

        assert len(icons) == 3
        assert icons[0]["href"] == "https://example.com/favicon.ico"
        assert icons[0]["format"] == "ico"
        assert icons[0]["size"] == 16
        assert icons[1]["href"] == "https://example.com/icon-192.png"
        assert icons[1]["format"] == "png"
        assert icons[1]["size"] == 192
        assert icons[2]["href"] == "https://example.com/icon.svg"
        assert icons[2]["format"] == "svg"
        assert icons[2]["size"] == 0

    def test_no_icon_links(self) -> None:
        """HTML without any link[rel=icon] yields empty list."""
        html = """<html><head><link rel="stylesheet" href="/style.css"></head></html>"""
        assert _parse_icons_from_html(html, "https://example.com") == []

    def test_relative_urls_resolved(self) -> None:
        """Relative href values are resolved against base_url."""
        html = """
        <html><head>
            <link rel="icon" href="/assets/icon.png">
            <link rel="icon" href="icons/favicon.ico">
        </head></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com/page/")
        assert icons[0]["href"] == "https://example.com/assets/icon.png"
        assert icons[1]["href"] == "https://example.com/page/icons/favicon.ico"

    def test_data_uri_skipped(self) -> None:
        """data: URIs are filtered out (empty string after _make_absolute_url)."""
        html = """<html><head><link rel="icon" href="data:image/png;base64,abc123"></head></html>"""
        assert _parse_icons_from_html(html, "https://example.com") == []

    def test_link_without_href_skipped(self) -> None:
        """Link tags missing href attribute are skipped."""
        html = """<html><head><link rel="icon" sizes="32x32"></head></html>"""
        assert _parse_icons_from_html(html, "https://example.com") == []

    def test_unknown_format(self) -> None:
        """Extensions not matching png/svg/ico get format 'other'."""
        html = """<html><head><link rel="icon" href="/icon.gif"></head></html>"""
        icons = _parse_icons_from_html(html, "https://example.com")
        assert len(icons) == 1
        assert icons[0]["format"] == "other"

    def test_shortcut_icon_rel(self) -> None:
        """rel='shortcut icon' (contains 'icon') is also matched."""
        html = """<html><head><link rel="shortcut icon" href="/favicon.ico"></head></html>"""
        icons = _parse_icons_from_html(html, "https://example.com")
        assert len(icons) == 1
        assert icons[0]["href"] == "https://example.com/favicon.ico"


# ---------------------------------------------------------------------------
# _select_best_icon
# ---------------------------------------------------------------------------


class TestSelectBestIcon:
    """Tests for _select_best_icon — picks best favicon from list."""

    def test_empty_list_returns_none(self) -> None:
        """No icons available returns None."""
        assert _select_best_icon([]) is None

    def test_png_prioritized_over_ico(self) -> None:
        """PNG format has higher priority than ICO."""
        icons = [
            {"href": "https://example.com/fav.ico", "size": 32, "format": "ico"},
            {"href": "https://example.com/fav.png", "size": 32, "format": "png"},
        ]
        assert _select_best_icon(icons) == "https://example.com/fav.png"

    def test_larger_size_preferred_within_same_format(self) -> None:
        """Within the same format, larger sizes are preferred (secondary sort desc)."""
        icons = [
            {"href": "https://example.com/small.png", "size": 16, "format": "png"},
            {"href": "https://example.com/large.png", "size": 256, "format": "png"},
        ]
        assert _select_best_icon(icons) == "https://example.com/large.png"

    def test_png_beats_svg_even_if_svg_larger(self) -> None:
        """Format priority trumps size — PNG beats SVG even if SVG is larger."""
        icons = [
            {"href": "https://example.com/huge.svg", "size": 1024, "format": "svg"},
            {"href": "https://example.com/small.png", "size": 16, "format": "png"},
        ]
        assert _select_best_icon(icons) == "https://example.com/small.png"


# ---------------------------------------------------------------------------
# _validate_favicon_url
# ---------------------------------------------------------------------------


def _mock_async_client(response: MagicMock | None = None, head_side_effect=None) -> AsyncMock:
    client = AsyncMock()
    if head_side_effect is not None:
        client.head.side_effect = head_side_effect
    else:
        client.head.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestValidateFaviconUrl:
    """Tests for _validate_favicon_url — HEAD request to verify favicon."""

    @patch("app.utils.favicon_utils.log")
    async def test_valid_image_returns_true(self, _mock_log: MagicMock) -> None:
        """200 response with image content-type returns True."""
        response = MagicMock(status_code=200, headers={"content-type": "image/png"})
        client = _mock_async_client(response)
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            assert await _validate_favicon_url("https://example.com/favicon.png") is True

    @patch("app.utils.favicon_utils.log")
    async def test_non_200_returns_false(self, _mock_log: MagicMock) -> None:
        """Non-200 status code returns False."""
        response = MagicMock(status_code=404, headers={"content-type": "text/html"})
        client = _mock_async_client(response)
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            assert await _validate_favicon_url("https://example.com/favicon.png") is False

    @patch("app.utils.favicon_utils.log")
    async def test_non_image_content_type_returns_false(self, _mock_log: MagicMock) -> None:
        """200 response with non-image content-type returns False."""
        response = MagicMock(status_code=200, headers={"content-type": "text/html"})
        client = _mock_async_client(response)
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            assert await _validate_favicon_url("https://example.com/favicon.png") is False

    @patch("app.utils.favicon_utils.log")
    async def test_http_error_returns_false(self, _mock_log: MagicMock) -> None:
        """Network error during HEAD request returns False."""
        client = _mock_async_client(head_side_effect=httpx.ConnectError("refused"))
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            assert await _validate_favicon_url("https://example.com/favicon.png") is False


# ---------------------------------------------------------------------------
# _fetch_smithery_icon
# ---------------------------------------------------------------------------


class TestFetchSmitheryIcon:
    """Tests for _fetch_smithery_icon — Smithery registry iconUrl lookup."""

    async def test_non_smithery_returns_none_without_http(self) -> None:
        """A non-Smithery URL short-circuits to None (no registry call)."""
        with patch("app.utils.favicon_utils.httpx.AsyncClient") as mock_client:
            assert await _fetch_smithery_icon("https://example.com/x") is None
            mock_client.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    async def test_returns_registry_icon_url(self, _mock_log: MagicMock) -> None:
        """A 200 registry response yields its iconUrl."""
        response = MagicMock(status_code=200)
        response.json.return_value = {"iconUrl": "https://api.smithery.ai/servers/brave/icon"}
        client = _mock_async_client()
        client.get.return_value = response
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            result = await _fetch_smithery_icon("https://server.smithery.ai/brave")
        assert result == "https://api.smithery.ai/servers/brave/icon"

    @patch("app.utils.favicon_utils.log")
    async def test_non_200_returns_none(self, _mock_log: MagicMock) -> None:
        """A non-200 registry response yields None."""
        response = MagicMock(status_code=403)
        client = _mock_async_client()
        client.get.return_value = response
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            assert await _fetch_smithery_icon("https://server.smithery.ai/brave") is None

    @patch("app.utils.favicon_utils.log")
    async def test_missing_icon_url_returns_none(self, _mock_log: MagicMock) -> None:
        """A registry response without an iconUrl yields None."""
        response = MagicMock(status_code=200)
        response.json.return_value = {"iconUrl": None}
        client = _mock_async_client()
        client.get.return_value = response
        with patch("app.utils.favicon_utils.httpx.AsyncClient", return_value=client):
            assert await _fetch_smithery_icon("https://server.smithery.ai/brave") is None


# ---------------------------------------------------------------------------
# fetch_favicon_from_url (Redis cache wrapper)
# ---------------------------------------------------------------------------


class TestFetchFaviconFromUrl:
    """Tests for fetch_favicon_from_url — top-level function with Redis cache."""

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_hit_returns_cached_value(
        self, mock_get_cache: AsyncMock, mock_set_cache: AsyncMock, _mock_log: MagicMock
    ) -> None:
        """When Redis cache has a value, return it without fetching."""
        mock_get_cache.return_value = "https://cached.example.com/favicon.png"
        result = await fetch_favicon_from_url("https://example.com/page")
        assert result == "https://cached.example.com/favicon.png"
        mock_get_cache.assert_called_once()
        mock_set_cache.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._fetch_favicon_impl", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_miss_fetches_and_caches(
        self,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_fetch_impl: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """Cache miss triggers _fetch_favicon_impl and caches the result."""
        mock_get_cache.return_value = None
        mock_fetch_impl.return_value = "https://example.com/favicon.ico"
        result = await fetch_favicon_from_url("https://example.com/page")
        assert result == "https://example.com/favicon.ico"
        mock_fetch_impl.assert_called_once_with("https://example.com/page")
        mock_set_cache.assert_called_once()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.get_cache", new_callable=AsyncMock)
    async def test_exception_returns_none(
        self, mock_get_cache: AsyncMock, _mock_log: MagicMock
    ) -> None:
        """Unexpected exception in the outer try/except returns None."""
        mock_get_cache.side_effect = RuntimeError("Redis down")
        assert await fetch_favicon_from_url("https://example.com") is None


# ---------------------------------------------------------------------------
# _fetch_favicon_impl — Smithery icon -> host <link> -> legacy fallback
# ---------------------------------------------------------------------------


class TestFetchFaviconImpl:
    """Tests for _fetch_favicon_impl — validated per-host resolution cascade."""

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._fetch_smithery_icon", new_callable=AsyncMock)
    async def test_smithery_icon_used_when_valid(
        self,
        mock_smithery: AsyncMock,
        mock_validate: AsyncMock,
        mock_html: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """A valid Smithery registry icon is returned without parsing HTML."""
        mock_smithery.return_value = "https://api.smithery.ai/servers/brave/icon"
        mock_validate.return_value = True
        result = await _fetch_favicon_impl("https://server.smithery.ai/brave")
        assert result == "https://api.smithery.ai/servers/brave/icon"
        mock_html.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._fetch_smithery_icon", new_callable=AsyncMock)
    async def test_declared_link_used_when_no_smithery_icon(
        self,
        mock_smithery: AsyncMock,
        mock_validate: AsyncMock,
        mock_html: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """The host's declared <link> icon is used when valid."""
        mock_smithery.return_value = None
        mock_html.return_value = "https://example.com/mcp-use/public/favicon.png"
        mock_validate.return_value = True
        result = await _fetch_favicon_impl("https://example.com/mcp")
        assert result == "https://example.com/mcp-use/public/favicon.png"

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.legacy_favicon_url")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._fetch_smithery_icon", new_callable=AsyncMock)
    async def test_falls_back_to_legacy(
        self,
        mock_smithery: AsyncMock,
        mock_validate: AsyncMock,
        mock_html: AsyncMock,
        mock_legacy: MagicMock,
        _mock_log: MagicMock,
    ) -> None:
        """With no specific icon, the legacy Google-S2 favicon is returned."""
        mock_smithery.return_value = None
        mock_html.return_value = None
        mock_legacy.return_value = "https://www.google.com/s2/favicons?domain=example.com&sz=256"
        result = await _fetch_favicon_impl("https://example.com/mcp")
        assert result == "https://www.google.com/s2/favicons?domain=example.com&sz=256"
        mock_validate.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.legacy_favicon_url")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._fetch_smithery_icon", new_callable=AsyncMock)
    async def test_invalid_candidates_fall_through_to_legacy(
        self,
        mock_smithery: AsyncMock,
        mock_validate: AsyncMock,
        mock_html: AsyncMock,
        mock_legacy: MagicMock,
        _mock_log: MagicMock,
    ) -> None:
        """Smithery + <link> candidates that fail validation fall back to legacy."""
        mock_smithery.return_value = "https://api.smithery.ai/servers/x/icon"
        mock_html.return_value = "https://example.com/favicon.png"
        mock_validate.return_value = False  # both candidates invalid
        mock_legacy.return_value = "https://www.google.com/s2/favicons?domain=example.com&sz=256"
        result = await _fetch_favicon_impl("https://example.com/mcp")
        assert result == "https://www.google.com/s2/favicons?domain=example.com&sz=256"
