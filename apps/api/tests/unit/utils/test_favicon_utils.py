"""Unit tests for app.utils.favicon_utils — favicon fetching with Redis caching."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.favicon_utils import (
    GOOGLE_FAVICON_URL,
    _fetch_favicon_impl,
    _get_domain_cache_key,
    _is_known_favicon_url,
    _parse_favicon_size,
    _parse_icons_from_html,
    _select_best_icon,
    _validate_favicon_url,
    fetch_favicon_from_url,
)


# ---------------------------------------------------------------------------
# _get_domain_cache_key
# ---------------------------------------------------------------------------


class TestGetDomainCacheKey:
    """Tests for _get_domain_cache_key — extracts root domain for cache key."""

    def test_simple_url(self) -> None:
        """Standard URL yields favicon:<domain> cache key."""
        key = _get_domain_cache_key("https://example.com/some/path")
        assert key == "favicon:example.com"

    def test_subdomain_url(self) -> None:
        """Subdomains are stripped to root domain."""
        key = _get_domain_cache_key("https://sub.deep.example.com")
        assert key == "favicon:example.com"

    def test_url_with_port(self) -> None:
        """Port numbers are ignored, root domain is extracted."""
        key = _get_domain_cache_key("https://app.example.org:8443/path")
        assert key == "favicon:example.org"


# ---------------------------------------------------------------------------
# _is_known_favicon_url
# ---------------------------------------------------------------------------


class TestIsKnownFaviconUrl:
    """Tests for _is_known_favicon_url — check known favicon extensions."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/favicon.ico",
            "https://example.com/icon.png",
            "https://example.com/logo.svg",
            "https://example.com/icon.webp",
        ],
        ids=["ico", "png", "svg", "webp"],
    )
    def test_known_extensions_return_true(self, url: str) -> None:
        """URLs ending in .ico/.png/.svg/.webp are recognized."""
        assert _is_known_favicon_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/favicon.ico?v=2",
            "https://example.com/icon.png?hash=abc",
        ],
        ids=["ico_with_query", "png_with_query"],
    )
    def test_known_extensions_with_query_params(self, url: str) -> None:
        """Query parameters are stripped before checking extension."""
        assert _is_known_favicon_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/logo.jpg",
            "https://example.com/image.gif",
            "https://example.com/page.html",
            "https://example.com/api/icon",
        ],
        ids=["jpg", "gif", "html", "no_extension"],
    )
    def test_unknown_extensions_return_false(self, url: str) -> None:
        """URLs with non-favicon extensions return False."""
        assert _is_known_favicon_url(url) is False

    def test_case_insensitive(self) -> None:
        """Extension matching is case-insensitive."""
        assert _is_known_favicon_url("https://example.com/ICON.PNG") is True
        assert _is_known_favicon_url("https://example.com/Favicon.ICO") is True


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
        ids=[
            "square_32",
            "square_16",
            "wider_rect",
            "taller_rect",
            "multiple_sizes_picks_max",
        ],
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
        html = """
        <html><head>
            <link rel="stylesheet" href="/style.css">
        </head><body></body></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com")
        assert icons == []

    def test_relative_urls_resolved(self) -> None:
        """Relative href values are resolved against base_url."""
        html = """
        <html><head>
            <link rel="icon" href="/assets/icon.png">
            <link rel="icon" href="icons/favicon.ico">
        </head><body></body></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com/page/")

        assert icons[0]["href"] == "https://example.com/assets/icon.png"
        assert icons[1]["href"] == "https://example.com/page/icons/favicon.ico"

    def test_data_uri_skipped(self) -> None:
        """data: URIs are filtered out (empty string after _make_absolute_url)."""
        html = """
        <html><head>
            <link rel="icon" href="data:image/png;base64,abc123">
        </head><body></body></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com")
        assert icons == []

    def test_link_without_href_skipped(self) -> None:
        """Link tags missing href attribute are skipped."""
        html = """
        <html><head>
            <link rel="icon" sizes="32x32">
        </head><body></body></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com")
        assert icons == []

    def test_unknown_format(self) -> None:
        """Extensions not matching png/svg/ico get format 'other'."""
        html = """
        <html><head>
            <link rel="icon" href="/icon.gif">
        </head><body></body></html>
        """
        icons = _parse_icons_from_html(html, "https://example.com")
        assert len(icons) == 1
        assert icons[0]["format"] == "other"

    def test_shortcut_icon_rel(self) -> None:
        """rel='shortcut icon' (contains 'icon') is also matched."""
        html = """
        <html><head>
            <link rel="shortcut icon" href="/favicon.ico">
        </head><body></body></html>
        """
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

    def test_ico_prioritized_over_svg(self) -> None:
        """ICO format has higher priority than SVG."""
        icons = [
            {"href": "https://example.com/fav.svg", "size": 64, "format": "svg"},
            {"href": "https://example.com/fav.ico", "size": 32, "format": "ico"},
        ]
        assert _select_best_icon(icons) == "https://example.com/fav.ico"

    def test_larger_size_preferred_within_same_format(self) -> None:
        """Within the same format, larger sizes are preferred (secondary sort desc)."""
        icons = [
            {"href": "https://example.com/small.png", "size": 16, "format": "png"},
            {"href": "https://example.com/large.png", "size": 256, "format": "png"},
        ]
        assert _select_best_icon(icons) == "https://example.com/large.png"

    def test_single_icon_returned(self) -> None:
        """Single icon is returned regardless of format."""
        icons = [
            {"href": "https://example.com/only.svg", "size": 0, "format": "svg"},
        ]
        assert _select_best_icon(icons) == "https://example.com/only.svg"

    def test_png_beats_svg_even_if_svg_larger(self) -> None:
        """Format priority trumps size — PNG beats SVG even if SVG is larger."""
        icons = [
            {"href": "https://example.com/huge.svg", "size": 1024, "format": "svg"},
            {"href": "https://example.com/small.png", "size": 16, "format": "png"},
        ]
        assert _select_best_icon(icons) == "https://example.com/small.png"

    def test_other_format_between_ico_and_svg(self) -> None:
        """'other' format sits between ICO and SVG in priority."""
        icons = [
            {"href": "https://example.com/icon.svg", "size": 32, "format": "svg"},
            {"href": "https://example.com/icon.gif", "size": 32, "format": "other"},
        ]
        assert _select_best_icon(icons) == "https://example.com/icon.gif"


# ---------------------------------------------------------------------------
# _validate_favicon_url
# ---------------------------------------------------------------------------


class TestValidateFaviconUrl:
    """Tests for _validate_favicon_url — HEAD request to verify favicon."""

    @patch("app.utils.favicon_utils.log")
    async def test_valid_image_returns_true(self, _mock_log: MagicMock) -> None:
        """200 response with image content-type returns True."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.favicon_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await _validate_favicon_url("https://example.com/favicon.png")
        assert result is True

    @patch("app.utils.favicon_utils.log")
    async def test_non_200_returns_false(self, _mock_log: MagicMock) -> None:
        """Non-200 status code returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"content-type": "text/html"}

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.favicon_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await _validate_favicon_url("https://example.com/favicon.png")
        assert result is False

    @patch("app.utils.favicon_utils.log")
    async def test_non_image_content_type_returns_false(
        self, _mock_log: MagicMock
    ) -> None:
        """200 response with non-image content-type returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.favicon_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await _validate_favicon_url("https://example.com/favicon.png")
        assert result is False

    @patch("app.utils.favicon_utils.log")
    async def test_http_error_returns_false(self, _mock_log: MagicMock) -> None:
        """Network error during HEAD request returns False."""
        mock_client = AsyncMock()
        mock_client.head.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.favicon_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await _validate_favicon_url("https://example.com/favicon.png")
        assert result is False

    @patch("app.utils.favicon_utils.log")
    async def test_image_x_icon_content_type(self, _mock_log: MagicMock) -> None:
        """image/x-icon content type is recognized as an image."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/x-icon"}

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.favicon_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await _validate_favicon_url("https://example.com/favicon.ico")
        assert result is True


# ---------------------------------------------------------------------------
# fetch_favicon_from_url
# ---------------------------------------------------------------------------


class TestFetchFaviconFromUrl:
    """Tests for fetch_favicon_from_url — top-level function with Redis cache."""

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_hit_returns_cached_value(
        self,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_log: MagicMock,
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
    @patch("app.utils.favicon_utils._fetch_favicon_impl", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_miss_no_result_does_not_cache(
        self,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_fetch_impl: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """When fetch returns None, nothing is cached."""
        mock_get_cache.return_value = None
        mock_fetch_impl.return_value = None

        result = await fetch_favicon_from_url("https://unknown.example.com")

        assert result is None
        mock_set_cache.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.get_cache", new_callable=AsyncMock)
    async def test_exception_returns_none(
        self, mock_get_cache: AsyncMock, _mock_log: MagicMock
    ) -> None:
        """Unexpected exception in the outer try/except returns None."""
        mock_get_cache.side_effect = RuntimeError("Redis down")

        result = await fetch_favicon_from_url("https://example.com")
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_favicon_impl
# ---------------------------------------------------------------------------


class TestFetchFaviconImpl:
    """Tests for _fetch_favicon_impl — core fetch logic with strategy cascade."""

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_non_smithery_returns_google_url_directly(
        self, mock_extract: MagicMock, _mock_log: MagicMock
    ) -> None:
        """Non-smithery domains return Google favicon URL without any HTTP calls."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "example.com"
        mock_extract.return_value = mock_result

        result = await _fetch_favicon_impl("https://example.com/path")

        expected = GOOGLE_FAVICON_URL.format(domain="example.com")
        assert result == expected

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_tries_google_first(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """For smithery.ai, Google favicon service is tried first."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = (
            "https://google.com/s2/favicons?domain=smithery.ai&sz=256"
        )

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://google.com/s2/favicons?domain=smithery.ai&sz=256"
        mock_google.assert_called_once_with("smithery.ai")
        mock_lib.assert_not_called()
        mock_standard.assert_not_called()
        mock_html.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._is_known_favicon_url")
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_falls_back_to_favicon_library(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_is_known: MagicMock,
        mock_validate: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """When Google fails for smithery, tries favicon library next."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = "https://smithery.ai/favicon.png"
        mock_is_known.return_value = True

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://smithery.ai/favicon.png"
        mock_standard.assert_not_called()
        mock_html.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_favicon_lib_result_validated_if_unknown_ext(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_validate: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """Favicon library result with unknown extension needs validation."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = "https://smithery.ai/api/icon"  # no known ext
        mock_validate.return_value = True

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://smithery.ai/api/icon"
        mock_validate.assert_called_once_with("https://smithery.ai/api/icon")

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_favicon_lib_fails_validation_falls_to_standard(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_validate: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """If favicon lib result fails validation, falls back to standard /favicon.ico."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = "https://smithery.ai/api/icon"
        mock_validate.return_value = False  # validation fails
        mock_standard.return_value = "https://smithery.ai/favicon.ico"

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://smithery.ai/favicon.ico"

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_falls_back_to_html_parsing(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        mock_validate: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """When all earlier strategies fail, falls back to HTML link parsing."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = None
        mock_standard.return_value = None
        mock_html.return_value = "https://smithery.ai/assets/icon.png"

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://smithery.ai/assets/icon.png"

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_html_result_with_known_ext_skips_validation(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        mock_validate: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """HTML parsing result with known extension skips validation."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = None
        mock_standard.return_value = None
        mock_html.return_value = "https://smithery.ai/icon.png"

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://smithery.ai/icon.png"
        mock_validate.assert_not_called()

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_html_result_unknown_ext_validated(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        mock_validate: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """HTML parsing result with unknown extension is validated."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = None
        mock_standard.return_value = None
        mock_html.return_value = "https://smithery.ai/api/icon"
        mock_validate.return_value = True

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result == "https://smithery.ai/api/icon"
        mock_validate.assert_called_once_with("https://smithery.ai/api/icon")

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_all_strategies_fail_returns_none(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        mock_validate: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """When all strategies fail for smithery, returns None."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = None
        mock_standard.return_value = None
        mock_html.return_value = None

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result is None

    @patch("app.utils.favicon_utils.log")
    @patch("app.utils.favicon_utils._validate_favicon_url", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_html_link_parsing", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_standard_favicon", new_callable=AsyncMock)
    @patch("app.utils.favicon_utils._try_favicon_library", new_callable=AsyncMock)
    @patch(
        "app.utils.favicon_utils._try_google_favicon_service", new_callable=AsyncMock
    )
    @patch("app.utils.favicon_utils.tldextract.extract")
    async def test_smithery_html_result_fails_validation_returns_none(
        self,
        mock_extract: MagicMock,
        mock_google: AsyncMock,
        mock_lib: AsyncMock,
        mock_standard: AsyncMock,
        mock_html: AsyncMock,
        mock_validate: AsyncMock,
        _mock_log: MagicMock,
    ) -> None:
        """HTML result with unknown ext that fails validation returns None."""
        mock_result = MagicMock()
        mock_result.top_domain_under_public_suffix = "smithery.ai"
        mock_extract.return_value = mock_result
        mock_google.return_value = None
        mock_lib.return_value = None
        mock_standard.return_value = None
        mock_html.return_value = "https://smithery.ai/api/icon"
        mock_validate.return_value = False

        result = await _fetch_favicon_impl("https://smithery.ai/server/test")

        assert result is None
