"""Unit tests for app.utils.internet_utils — URL validation, scraping, and metadata fetching."""

import ipaddress
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from bs4 import BeautifulSoup
from fastapi import HTTPException, status
import httpx
import pytest

from app.constants.log_tags import LogTag
from app.models.search_models import SearchUrlDocument, URLResponse
from app.utils.internet_utils import (
    _MAX_REDIRECTS,
    _MAX_RESPONSE_BYTES,
    _REQUEST_TIMEOUT,
    _absolute_url,
    _attr_value,
    _fetch_following_redirects,
    _is_blocked_ip,
    _parse_url_metadata,
    _resolve_and_validate,
    _validate_url_for_fetch,
    fetch_url_metadata,
    scrape_url_metadata,
)

_SCRAPED = URLResponse(
    title="Scraped Title",
    description="Scraped Desc",
    favicon="https://example.com/scraped-fav.ico",
    website_name="ScrapedSite",
    website_image="https://example.com/scraped.png",
    url="https://example.com",
)

# ---------------------------------------------------------------------------
# scrape_url_metadata
# ---------------------------------------------------------------------------


FULL_HTML = """
<html>
<head>
    <title>  Test Page  </title>
    <meta name="description" content="A test description">
    <meta property="og:site_name" content="TestSite">
    <meta property="og:image" content="https://example.com/og.png">
    <link rel="icon" href="/favicon.ico">
</head>
<body></body>
</html>
"""

HTML_RELATIVE_FAVICON = """
<html>
<head>
    <title>Relative Favicon</title>
    <link rel="icon" href="/static/icon.png">
</head>
<body></body>
</html>
"""

HTML_NO_TITLE = """
<html>
<head>
    <meta name="description" content="desc">
</head>
<body></body>
</html>
"""

HTML_OG_IMAGE_AS_WEBSITE_IMAGE = """
<html>
<head>
    <title>OG Page</title>
    <meta property="og:image" content="https://example.com/og-img.jpg">
</head>
<body></body>
</html>
"""

HTML_LOGO_TAG = """
<html>
<head>
    <title>Logo Page</title>
    <meta property="og:logo" content="/logo.svg">
    <meta property="og:image" content="https://example.com/og-img.jpg">
</head>
<body></body>
</html>
"""

HTML_OG_DESCRIPTION_ONLY = """
<html>
<head>
    <title>OG Desc</title>
    <meta property="og:description" content="OG description text">
</head>
<body></body>
</html>
"""

HTML_APPLICATION_NAME = """
<html>
<head>
    <title>App Name</title>
    <meta name="application-name" content="MyApp">
</head>
<body></body>
</html>
"""

HTML_SHORTCUT_ICON = """
<html>
<head>
    <title>Shortcut</title>
    <link rel="shortcut icon" href="/shortcut.ico">
</head>
<body></body>
</html>
"""

HTML_APPLE_TOUCH_ICON = """
<html>
<head>
    <title>Apple Touch</title>
    <link rel="apple-touch-icon" href="https://example.com/apple-touch.png">
</head>
<body></body>
</html>
"""

HTML_LOGO_LINK_TAG = """
<html>
<head>
    <title>Logo Link</title>
    <link rel="logo" href="/link-logo.png">
</head>
<body></body>
</html>
"""

HTML_EMPTY = """
<html>
<head></head>
<body></body>
</html>
"""


def _mock_response(
    text: str = "", status_code: int = 200, content: bytes | None = None
) -> MagicMock:
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.text = text
    # Production code uses response.content[:MAX] for BeautifulSoup — supply bytes.
    response.content = content if content is not None else text.encode()
    response.status_code = status_code
    # Production code uses manual redirect loop with follow_redirects=False.
    # Set is_redirect=False so the loop exits immediately on the first response.
    response.is_redirect = False
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="Error",
            request=MagicMock(spec=httpx.Request),
            response=response,
        )
    return response


def _redirect_response(location: str | None) -> MagicMock:
    """Create a mock httpx.Response that reports itself as a redirect."""
    response = MagicMock(spec=httpx.Response)
    response.is_redirect = True
    response.headers = {"location": location}
    return response


def _addrinfo_ipv4(ip: str) -> tuple:
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))


def _addrinfo_ipv6(ip: str) -> tuple:
    return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 80, 0, 0))


async def _run_resolve(hostname: str, getaddrinfo: AsyncMock) -> None:
    """Run _resolve_and_validate with loop.getaddrinfo (the DNS seam) mocked."""
    fake_loop = MagicMock()
    fake_loop.getaddrinfo = getaddrinfo
    with patch("app.utils.internet_utils.asyncio.get_running_loop", return_value=fake_loop):
        await _resolve_and_validate(hostname)


class TestScrapeUrlMetadata:
    """Tests for scrape_url_metadata."""

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_full_html_success(self, mock_client_cls: MagicMock) -> None:
        """Full HTML with title, description, favicon, og:image returns populated dict."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(FULL_HTML)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.title == "Test Page"
        assert result.description == "A test description"
        assert result.favicon == "https://example.com/favicon.ico"
        assert result.website_name == "TestSite"
        # og:image becomes website_image when no logo tag is present
        assert result.website_image == "https://example.com/og.png"
        assert result.url == "https://example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_http_error_returns_empty_metadata(self, mock_client_cls: MagicMock) -> None:
        """HTTP error (4xx/5xx) returns dict with all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response("", status_code=500)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com/fail")

        assert result.title is None
        assert result.description is None
        assert result.favicon is None
        assert result.website_name is None
        assert result.website_image is None
        assert result.url == "https://example.com/fail"

    @patch("app.utils.internet_utils.log.debug")
    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_timeout_returns_empty_metadata(
        self, mock_client_cls: MagicMock, mock_debug: MagicMock
    ) -> None:
        """Timeout during request returns dict with all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://slow.example.com")

        assert result.title is None
        assert result.description is None
        assert result.favicon is None
        assert result.website_name is None
        assert result.website_image is None
        assert result.url == "https://slow.example.com"
        mock_debug.assert_called_once_with(
            "Error fetching URL metadata", error="timed out", error_type="TimeoutException"
        )

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_connection_error_returns_empty_metadata(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Connection error returns dict with all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://down.example.com")

        assert result.title is None
        assert result.url == "https://down.example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_missing_title(self, mock_client_cls: MagicMock) -> None:
        """HTML without a <title> tag yields None title."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_NO_TITLE)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.title is None
        assert result.description == "desc"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_relative_favicon_converted_to_absolute(self, mock_client_cls: MagicMock) -> None:
        """Relative favicon href is joined with the base URL to form an absolute path."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_RELATIVE_FAVICON)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com/page")

        assert result.favicon == "https://example.com/static/icon.png"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_og_image_used_as_website_image(self, mock_client_cls: MagicMock) -> None:
        """When no logo tag is present, og:image is used as website_image."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_OG_IMAGE_AS_WEBSITE_IMAGE)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.website_image == "https://example.com/og-img.jpg"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_logo_tag_takes_precedence_over_og_image(
        self, mock_client_cls: MagicMock
    ) -> None:
        """When og:logo meta tag is present, it is used as website_image instead of og:image."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_LOGO_TAG)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.website_image == "https://example.com/logo.svg"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_og_description_fallback(self, mock_client_cls: MagicMock) -> None:
        """og:description is used when meta name=description is absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_OG_DESCRIPTION_ONLY)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.description == "OG description text"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_application_name_fallback(self, mock_client_cls: MagicMock) -> None:
        """application-name meta tag is used when og:site_name is absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_APPLICATION_NAME)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.website_name == "MyApp"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_shortcut_icon_fallback(self, mock_client_cls: MagicMock) -> None:
        """Shortcut icon link tag is used when rel=icon is absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_SHORTCUT_ICON)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.favicon == "https://example.com/shortcut.ico"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_apple_touch_icon_fallback(self, mock_client_cls: MagicMock) -> None:
        """apple-touch-icon link tag is used when other icon tags are absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_APPLE_TOUCH_ICON)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.favicon == "https://example.com/apple-touch.png"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_logo_link_tag_used_as_website_image(self, mock_client_cls: MagicMock) -> None:
        """link rel=logo tag href is used as website_image."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_LOGO_LINK_TAG)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.website_image == "https://example.com/link-logo.png"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_empty_html_returns_all_none(self, mock_client_cls: MagicMock) -> None:
        """Completely empty HTML returns all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_EMPTY)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.title is None
        assert result.description is None
        assert result.favicon is None
        assert result.website_name is None
        assert result.website_image is None
        assert result.url == "https://example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_og_image_used_as_favicon_fallback(self, mock_client_cls: MagicMock) -> None:
        """When no favicon link tag exists, og:image is used as favicon fallback."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_OG_IMAGE_AS_WEBSITE_IMAGE)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        # favicon = favicon or og_image — since no favicon link tag, og_image is used
        assert result.favicon == "https://example.com/og-img.jpg"

    @patch("app.utils.internet_utils.log.debug")
    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_unexpected_exception_returns_empty_metadata(
        self, mock_client_cls: MagicMock, mock_debug: MagicMock
    ) -> None:
        """Unexpected exceptions (e.g. parsing errors) are caught and return empty metadata."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = RuntimeError("unexpected")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.title is None
        assert result.url == "https://example.com"
        mock_debug.assert_called_once_with(
            "Unexpected error", error="unexpected", error_type="RuntimeError"
        )


# ---------------------------------------------------------------------------
# fetch_url_metadata
# ---------------------------------------------------------------------------


class TestFetchUrlMetadata:
    """Tests for fetch_url_metadata."""

    async def test_invalid_url_raises_http_exception(self) -> None:
        """Invalid URL raises HTTPException with 400 status."""
        with pytest.raises(Exception) as exc_info:
            await fetch_url_metadata("ftp://bad.example.com")

        from fastapi import HTTPException

        assert isinstance(exc_info.value, HTTPException)
        assert exc_info.value.status_code == 400
        # ftp:// triggers the scheme guard, not the parse guard
        assert "Only http(s) URLs are allowed" in exc_info.value.detail

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_hit_returns_cached_data(
        self,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        """When cache has the URL metadata, it is returned directly without DB or scrape."""
        cached_data = {
            "title": "Cached Title",
            "description": "Cached Desc",
            "favicon": "https://example.com/fav.ico",
            "website_name": "CachedSite",
            "website_image": "https://example.com/img.png",
            "url": "https://example.com",
        }
        mock_get_cache.return_value = cached_data
        mock_repo.get_by_url = AsyncMock()

        result = await fetch_url_metadata("https://example.com")

        mock_get_cache.assert_awaited_once_with("url_metadata:https://example.com")
        # DB should not be queried when cache hits.
        mock_repo.get_by_url.assert_not_awaited()
        mock_set_cache.assert_not_awaited()
        assert result == URLResponse(**cached_data)

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_db_hit_returns_db_data(
        self,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        """When cache misses but DB has the data, it is returned from the repository."""
        mock_get_cache.return_value = None

        stored = SearchUrlDocument(
            url="https://example.com",
            title="DB Title",
            description="DB Desc",
            favicon="https://example.com/db-fav.ico",
            website_name="DBSite",
            website_image=None,
        )
        mock_repo.get_by_url = AsyncMock(return_value=stored)

        result = await fetch_url_metadata("https://example.com")

        mock_get_cache.assert_awaited_once()
        mock_repo.get_by_url.assert_awaited_once_with("https://example.com")
        # Should not re-scrape or re-cache
        mock_set_cache.assert_not_awaited()
        assert result == URLResponse(**stored.model_dump())

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.scrape_url_metadata", new_callable=AsyncMock)
    async def test_cache_and_db_miss_scrapes_stores_and_caches(
        self,
        mock_scrape: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        """When both cache and DB miss, scrapes the URL, stores it, caches, and returns."""
        mock_get_cache.return_value = None
        mock_repo.get_by_url = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock()

        mock_scrape.return_value = _SCRAPED

        result = await fetch_url_metadata("https://example.com")

        mock_scrape.assert_awaited_once_with("https://example.com")
        stored = mock_repo.create.await_args.args[0]
        assert isinstance(stored, SearchUrlDocument)
        assert URLResponse(**stored.model_dump()) == _SCRAPED
        # The cached value stays the plain dict the frontend contract expects.
        mock_set_cache.assert_awaited_once_with(
            "url_metadata:https://example.com",
            {
                "title": "Scraped Title",
                "description": "Scraped Desc",
                "favicon": "https://example.com/scraped-fav.ico",
                "website_name": "ScrapedSite",
                "website_image": "https://example.com/scraped.png",
                "url": "https://example.com",
            },
            864000,
        )
        # The scraped object is returned as-is, not rebuilt
        assert result is _SCRAPED

    async def test_empty_string_url_raises_http_exception(self) -> None:
        """Empty string URL raises HTTPException."""
        with pytest.raises(Exception) as exc_info:
            await fetch_url_metadata("")

        from fastapi import HTTPException

        assert isinstance(exc_info.value, HTTPException)
        assert exc_info.value.status_code == 400

    async def test_none_url_raises_http_exception(self) -> None:
        """None URL raises HTTPException."""
        with pytest.raises(Exception) as exc_info:
            await fetch_url_metadata(None)  # type: ignore[arg-type]

        from fastapi import HTTPException

        assert isinstance(exc_info.value, HTTPException)
        assert exc_info.value.status_code == 400

    @patch("app.utils.internet_utils._validate_url_for_fetch", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_key_format(
        self,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_set_cache: AsyncMock,
        mock_validate: AsyncMock,
    ) -> None:
        """Cache key follows the 'url_metadata:{url}' format."""
        cached_data = {
            "title": "T",
            "description": None,
            "favicon": None,
            "website_name": None,
            "website_image": None,
            "url": "https://specific.example.com/path?q=1",
        }
        mock_get_cache.return_value = cached_data

        await fetch_url_metadata("https://specific.example.com/path?q=1")

        mock_get_cache.assert_awaited_once_with(
            "url_metadata:https://specific.example.com/path?q=1"
        )

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.scrape_url_metadata", new_callable=AsyncMock)
    async def test_cache_ttl_is_864000(
        self,
        mock_scrape: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        """Cache TTL is set to 864000 seconds (10 days)."""
        mock_get_cache.return_value = None
        mock_repo.get_by_url = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock()
        mock_scrape.return_value = URLResponse(url="https://example.com")

        await fetch_url_metadata("https://example.com")

        # Third positional arg to set_cache is the TTL
        call_args = mock_set_cache.call_args
        assert call_args[0][2] == 864000

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_empty_dict_cache_value_ignored(
        self,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        """A falsy non-None cache value (e.g. {}) must not short-circuit to a hit."""
        mock_get_cache.return_value = {}
        stored = SearchUrlDocument(url="https://example.com", title="DB Title")
        mock_repo.get_by_url = AsyncMock(return_value=stored)

        result = await fetch_url_metadata("https://example.com")

        mock_repo.get_by_url.assert_awaited_once_with("https://example.com")
        assert result.title == "DB Title"

    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_invalid_url_rejected_before_cache_lookup(
        self,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
    ) -> None:
        """SSRF validation runs before the cache is consulted — a cached entry
        must never let a forbidden URL through."""
        mock_get_cache.return_value = {
            "title": "Cached",
            "description": None,
            "favicon": None,
            "website_name": None,
            "website_image": None,
            "url": "http://10.0.0.1/",
        }

        with pytest.raises(HTTPException) as exc_info:
            await fetch_url_metadata("http://10.0.0.1/")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."
        mock_get_cache.assert_not_awaited()
        mock_repo.get_by_url = AsyncMock()
        mock_repo.get_by_url.assert_not_awaited()

    @patch("app.utils.internet_utils.log.set")
    @patch("app.utils.internet_utils.search_url_repository")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_wide_event_set_with_url_and_operation(
        self,
        mock_get_cache: AsyncMock,
        mock_repo: MagicMock,
        mock_log_set: MagicMock,
    ) -> None:
        """The wide-event context records the URL and operation on every fetch."""
        mock_get_cache.return_value = None
        mock_repo.get_by_url = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock()
        with patch(
            "app.utils.internet_utils.scrape_url_metadata", new_callable=AsyncMock
        ) as mock_scrape:
            mock_scrape.return_value = URLResponse(url="https://example.com/x")
            await fetch_url_metadata("https://example.com/x")

        mock_log_set.assert_called_once_with(
            url="https://example.com/x", operation="fetch_url_metadata"
        )


# ---------------------------------------------------------------------------
# _is_blocked_ip
# ---------------------------------------------------------------------------


class TestIsBlockedIp:
    """Tests for _is_blocked_ip — anything non-globally-routable is blocked."""

    @pytest.mark.parametrize(
        "ip_str",
        [
            "10.0.0.1",
            "192.168.1.1",
            "172.16.0.1",
            "172.31.255.255",
            "127.0.0.1",
            "169.254.169.254",
            "224.0.0.1",
            "240.0.0.1",
            "0.0.0.0",  # noqa: S104 - test input IP, not a server bind address
            "::1",
            "fe80::1",
            "fc00::1",
            "fd12:3456:789a::1",
            "::",
            "ff02::1",
        ],
    )
    def test_blocked(self, ip_str: str) -> None:
        assert _is_blocked_ip(ipaddress.ip_address(ip_str))

    @pytest.mark.parametrize(
        "ip_str",
        ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "2001:4860:4860::8888"],
    )
    def test_global_allowed(self, ip_str: str) -> None:
        assert not _is_blocked_ip(ipaddress.ip_address(ip_str))


# ---------------------------------------------------------------------------
# _resolve_and_validate
# ---------------------------------------------------------------------------


class TestResolveAndValidate:
    """Tests for _resolve_and_validate — the DNS-backed SSRF guard."""

    async def test_dns_failure_raises_400(self) -> None:
        getaddrinfo = AsyncMock(side_effect=socket.gaierror("no such host"))
        with pytest.raises(HTTPException) as exc_info:
            await _run_resolve("example.com", getaddrinfo)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host could not be resolved."

    async def test_no_results_raises_400(self) -> None:
        getaddrinfo = AsyncMock(return_value=[])
        with pytest.raises(HTTPException) as exc_info:
            await _run_resolve("example.com", getaddrinfo)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host could not be resolved."

    async def test_private_ip_blocked_with_warning_logged(self) -> None:
        getaddrinfo = AsyncMock(return_value=[_addrinfo_ipv4("10.0.0.5")])
        with patch("app.utils.internet_utils.log.warning") as mock_warning:
            with pytest.raises(HTTPException) as exc_info:
                await _run_resolve("example.com", getaddrinfo)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} ssrf_blocked", hostname="example.com", resolved_ip="10.0.0.5"
        )

    @pytest.mark.parametrize(
        "ip_str",
        ["127.0.0.1", "169.254.169.254", "224.0.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1"],  # noqa: S104 - test input IPs, not server bind addresses
    )
    async def test_non_global_ip_blocked(self, ip_str: str) -> None:
        addr = _addrinfo_ipv4(ip_str) if "." in ip_str else _addrinfo_ipv6(ip_str)
        getaddrinfo = AsyncMock(return_value=[addr])

        with pytest.raises(HTTPException) as exc_info:
            await _run_resolve("example.com", getaddrinfo)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."

    async def test_any_blocked_result_blocks_all(self) -> None:
        """Every resolved address must pass — a private address after a public
        one must still trip the guard."""
        getaddrinfo = AsyncMock(
            return_value=[_addrinfo_ipv4("8.8.8.8"), _addrinfo_ipv4("10.0.0.5")]
        )

        with pytest.raises(HTTPException) as exc_info:
            await _run_resolve("example.com", getaddrinfo)

        assert exc_info.value.detail == "URL host is not allowed."

    async def test_all_global_ips_allowed(self) -> None:
        getaddrinfo = AsyncMock(
            return_value=[
                _addrinfo_ipv4("8.8.8.8"),
                _addrinfo_ipv6("2606:4700:4700::1111"),
            ]
        )

        await _run_resolve("example.com", getaddrinfo)

        getaddrinfo.assert_awaited_once_with("example.com", None, proto=socket.IPPROTO_TCP)

    async def test_non_ip_sockaddr_raises_unsupported(self) -> None:
        getaddrinfo = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 80))])

        with pytest.raises(HTTPException) as exc_info:
            await _run_resolve("example.com", getaddrinfo)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host resolves to an unsupported address."


# ---------------------------------------------------------------------------
# _validate_url_for_fetch
# ---------------------------------------------------------------------------


class TestValidateUrlForFetch:
    """Tests for _validate_url_for_fetch — the pre-DNS URL guard."""

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_non_http_scheme_rejected(self, mock_resolve: AsyncMock) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch("ftp://example.com/file")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Only http(s) URLs are allowed."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_missing_hostname_rejected(self, mock_resolve: AsyncMock) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch("http:///path")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is missing."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_malformed_url_rejected(self, mock_resolve: AsyncMock) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch("http://[::1")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Invalid URL."
        mock_resolve.assert_not_awaited()

    @pytest.mark.parametrize(
        "url",
        [
            "https://localhost/x",
            "http://localhost.localdomain",
            "http://metadata.google.internal",
            "http://instance-data",
        ],
    )
    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_blocked_hostnames_rejected(self, mock_resolve: AsyncMock, url: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch(url)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_blocked_hostname_check_is_case_insensitive(
        self, mock_resolve: AsyncMock
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch("https://LOCALHOST/x")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_blocked_hostname_checked_before_single_label_rule(
        self, mock_resolve: AsyncMock
    ) -> None:
        """'metadata' is single-label AND blocked — the blocked-hostname list wins."""
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch("http://metadata")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_single_label_hostname_rejected(self, mock_resolve: AsyncMock) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch("http://rabbitmq")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not a valid public domain."
        mock_resolve.assert_not_awaited()

    @pytest.mark.parametrize(
        "url",
        ["http://10.0.0.1/", "http://127.0.0.1/", "http://169.254.169.254/", "http://[::ffff:192.168.1.1]/"],
    )
    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_blocked_ip_literal_rejected_without_dns(
        self, mock_resolve: AsyncMock, url: str
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch(url)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_global_ip_literal_allowed_without_dns(self, mock_resolve: AsyncMock) -> None:
        await _validate_url_for_fetch("http://8.8.8.8/")
        mock_resolve.assert_not_awaited()

    @pytest.mark.parametrize("url", ["http://[::1]/", "http://[2606:4700:4700::1111]/"])
    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_ipv6_literal_rejected_as_single_label(
        self, mock_resolve: AsyncMock, url: str
    ) -> None:
        """Bare IPv6 literals carry no dot, so they hit the public-domain rule
        before the IP-literal check."""
        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_fetch(url)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not a valid public domain."
        mock_resolve.assert_not_awaited()

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_dns_hostname_lowercased_before_resolve(self, mock_resolve: AsyncMock) -> None:
        await _validate_url_for_fetch("https://EXAMPLE.COM/Path")
        mock_resolve.assert_awaited_once_with("example.com")

    @patch("app.utils.internet_utils._resolve_and_validate", new_callable=AsyncMock)
    async def test_port_and_userinfo_stripped_from_hostname(self, mock_resolve: AsyncMock) -> None:
        await _validate_url_for_fetch("http://user:pass@example.com:8080/x")
        mock_resolve.assert_awaited_once_with("example.com")


# ---------------------------------------------------------------------------
# _attr_value
# ---------------------------------------------------------------------------


class TestAttrValue:
    """Tests for _attr_value — safe attribute extraction from soup tags."""

    def test_none_tag_returns_none(self) -> None:
        assert _attr_value(None, "content") is None

    def test_navigable_string_returns_none(self) -> None:
        text_node = BeautifulSoup("<p>text</p>", "html.parser").p.string
        assert _attr_value(text_node, "content") is None

    def test_missing_attr_returns_none(self) -> None:
        tag = BeautifulSoup("<meta name='description'>", "html.parser").find()
        assert _attr_value(tag, "content") is None

    def test_string_attr_stripped(self) -> None:
        tag = BeautifulSoup("<meta name='description' content='  hello  '>", "html.parser").find()
        assert _attr_value(tag, "content") == "hello"

    def test_list_attr_uses_first_element_stripped(self) -> None:
        tag = BeautifulSoup("<link rel='icon shortcut' href='/f.ico'>", "html.parser").find()
        assert _attr_value(tag, "rel") == "icon"

    def test_empty_list_returns_none(self) -> None:
        tag = BeautifulSoup("<meta name='description'>", "html.parser").find()
        tag.attrs["content"] = []
        assert _attr_value(tag, "content") is None

    def test_non_string_non_list_attr_returns_none(self) -> None:
        tag = BeautifulSoup("<meta name='description'>", "html.parser").find()
        tag.attrs["content"] = 123
        assert _attr_value(tag, "content") is None

    def test_duck_typed_tag_with_attrs_supported(self) -> None:
        """_attr_value only relies on the object exposing an attrs dict — a
        plain object with a real attrs attribute must work (bs4 Tags mask
        missing attributes via __getattr__, so a real Tag cannot exercise the
        hasattr check's False branch)."""
        fake = SimpleNamespace(attrs={"content": "  duck  "})
        assert _attr_value(fake, "content") == "duck"
        assert _attr_value(fake, "missing") is None


# ---------------------------------------------------------------------------
# _absolute_url
# ---------------------------------------------------------------------------


class TestAbsoluteUrl:
    """Tests for _absolute_url — relative URL resolution against a base."""

    def test_none_returns_none(self) -> None:
        assert _absolute_url("https://example.com/page", None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _absolute_url("https://example.com/page", "") is None

    @pytest.mark.parametrize(
        "relative_url",
        ["http://other.example.com/x", "https://other.example.com/x?a=1"],
    )
    def test_absolute_http_url_returned_unchanged(self, relative_url: str) -> None:
        assert _absolute_url("https://example.com/page", relative_url) == relative_url

    @pytest.mark.parametrize(
        ("base_url", "relative_url", "expected"),
        [
            ("https://example.com/page", "/favicon.ico", "https://example.com/favicon.ico"),
            ("https://example.com/page", "img.png", "https://example.com/img.png"),
            ("https://example.com/page", "//cdn.example.com/x.png", "https://cdn.example.com/x.png"),
        ],
    )
    def test_relative_url_joined_to_base(
        self, base_url: str, relative_url: str, expected: str
    ) -> None:
        assert _absolute_url(base_url, relative_url) == expected


# ---------------------------------------------------------------------------
# _parse_url_metadata
# ---------------------------------------------------------------------------


class TestParseUrlMetadata:
    """Tests for _parse_url_metadata — HTML-to-URLResponse extraction."""

    def _parse(self, html: str) -> URLResponse:
        return _parse_url_metadata("https://example.com", html.encode())

    def test_title_whitespace_stripped(self) -> None:
        result = self._parse("<html><head><title>  Hello  </title></head><body></body></html>")
        assert result.title == "Hello"

    def test_whitespace_only_title_stripped_to_empty(self) -> None:
        result = self._parse("<html><head><title>   </title></head><body></body></html>")
        assert result.title == ""

    def test_empty_title_tag_returns_none(self) -> None:
        result = self._parse("<html><head><title></title></head><body></body></html>")
        assert result.title is None

    def test_description_prefers_name_over_og(self) -> None:
        html = (
            "<html><head>"
            '<meta name="description" content="name-desc">'
            '<meta property="og:description" content="og-desc">'
            "</head><body></body></html>"
        )
        assert self._parse(html).description == "name-desc"

    def test_description_empty_content_is_empty_string(self) -> None:
        html = '<html><head><meta name="description" content=""></head><body></body></html>'
        assert self._parse(html).description == ""

    def test_description_whitespace_stripped(self) -> None:
        html = '<html><head><meta name="description" content="  desc  "></head><body></body></html>'
        assert self._parse(html).description == "desc"

    def test_website_name_prefers_og_over_application_name(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:site_name" content="OgSite">'
            '<meta name="application-name" content="AppSite">'
            "</head><body></body></html>"
        )
        assert self._parse(html).website_name == "OgSite"

    def test_website_name_whitespace_stripped(self) -> None:
        html = '<html><head><meta property="og:site_name" content="  Site  "></head><body></body></html>'
        assert self._parse(html).website_name == "Site"

    def test_favicon_prefers_icon_over_shortcut_and_apple(self) -> None:
        html = (
            "<html><head>"
            '<link rel="icon" href="/icon.ico">'
            '<link rel="shortcut icon" href="/shortcut.ico">'
            '<link rel="apple-touch-icon" href="/apple.png">'
            "</head><body></body></html>"
        )
        assert self._parse(html).favicon == "https://example.com/icon.ico"

    def test_favicon_absolute_href_unchanged(self) -> None:
        html = '<html><head><link rel="icon" href="https://cdn.example.com/f.ico"></head><body></body></html>'
        assert self._parse(html).favicon == "https://cdn.example.com/f.ico"

    def test_relative_og_image_absolutized(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:image" content="/img/og.png">'
            "</head><body></body></html>"
        )
        result = self._parse(html)
        assert result.favicon == "https://example.com/img/og.png"
        assert result.website_image == "https://example.com/img/og.png"

    def test_og_logo_meta_precedes_link_logo(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:logo" content="/meta.svg">'
            '<link rel="logo" href="/link.png">'
            "</head><body></body></html>"
        )
        assert self._parse(html).website_image == "https://example.com/meta.svg"

    def test_description_found_among_preceding_decoy_elements(self) -> None:
        """The description meta is located by tag AND attr — a preceding
        non-meta element with the same name attribute, or an earlier meta,
        must not be mistaken for it."""
        html = (
            "<html><head>"
            '<a name="description">anchor</a>'
            '<meta charset="utf-8">'
            '<meta name="description" content="  real desc  ">'
            "</head><body></body></html>"
        )
        assert self._parse(html).description == "real desc"

    def test_og_description_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<a property="og:description">anchor</a>'
            '<meta charset="utf-8">'
            '<meta property="og:description" content="  og desc  ">'
            "</head><body></body></html>"
        )
        assert self._parse(html).description == "og desc"

    def test_og_site_name_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<a property="og:site_name">anchor</a>'
            '<meta property="og:site_name" content="  Site  ">'
            "</head><body></body></html>"
        )
        assert self._parse(html).website_name == "Site"

    def test_application_name_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<a name="application-name">anchor</a>'
            '<meta charset="utf-8">'
            '<meta name="application-name" content="  App  ">'
            "</head><body></body></html>"
        )
        assert self._parse(html).website_name == "App"

    def test_icon_found_among_preceding_decoy_elements(self) -> None:
        """The icon link is located by tag AND rel — a preceding stylesheet
        link or a non-link element with rel=icon must not be mistaken for it."""
        html = (
            "<html><head>"
            '<link rel="stylesheet" href="/styles.css">'
            '<a rel="icon" href="/decoy.png">x</a>'
            '<link rel="icon" href="/real.ico">'
            "</head><body></body></html>"
        )
        assert self._parse(html).favicon == "https://example.com/real.ico"

    def test_apple_touch_icon_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<link rel="stylesheet" href="/styles.css">'
            '<a rel="apple-touch-icon" href="/decoy.png">x</a>'
            '<link rel="apple-touch-icon" href="/real.png">'
            "</head><body></body></html>"
        )
        assert self._parse(html).favicon == "https://example.com/real.png"

    def test_og_logo_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<a property="og:logo">anchor</a>'
            '<meta property="og:logo" content="/real.svg">'
            "</head><body></body></html>"
        )
        assert self._parse(html).website_image == "https://example.com/real.svg"

    def test_logo_link_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<a rel="logo" href="/decoy.png">x</a>'
            '<link rel="logo" href="/real.png">'
            "</head><body></body></html>"
        )
        assert self._parse(html).website_image == "https://example.com/real.png"

    def test_og_image_found_among_preceding_decoy_elements(self) -> None:
        html = (
            "<html><head>"
            '<a property="og:image" content="/decoy.png">x</a>'
            '<meta property="og:image" content="/real.png">'
            "</head><body></body></html>"
        )
        result = self._parse(html)
        assert result.favicon == "https://example.com/real.png"
        assert result.website_image == "https://example.com/real.png"


# ---------------------------------------------------------------------------
# _fetch_following_redirects
# ---------------------------------------------------------------------------


class TestFetchFollowingRedirects:
    """Tests for _fetch_following_redirects — manual redirect loop with re-validation."""

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_non_redirect_returned_immediately(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        final = _mock_response(FULL_HTML)
        mock_client.get.return_value = final
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _fetch_following_redirects("https://example.com/page")

        assert result is final
        mock_client_cls.assert_called_once_with(timeout=_REQUEST_TIMEOUT, follow_redirects=False)
        mock_client.get.assert_awaited_once_with("https://example.com/page")

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_redirect_without_location_returned(self, mock_client_cls: MagicMock) -> None:
        """A redirect response with no Location header is returned as-is."""
        mock_client = AsyncMock()
        redirected = _redirect_response(None)
        mock_client.get.return_value = redirected
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _fetch_following_redirects("https://example.com")

        assert result is redirected
        mock_client.get.assert_awaited_once_with("https://example.com")

    @patch("app.utils.internet_utils._validate_url_for_fetch", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_redirect_chain_followed_and_each_hop_validated(
        self, mock_client_cls: MagicMock, mock_validate: AsyncMock
    ) -> None:
        mock_client = AsyncMock()
        final = _mock_response(FULL_HTML)
        mock_client.get.side_effect = [
            _redirect_response("/a"),
            _redirect_response("https://other.example.com/b"),
            final,
        ]
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _fetch_following_redirects("https://example.com/page")

        assert result is final
        mock_client.get.assert_has_awaits(
            [
                call("https://example.com/page"),
                call("https://example.com/a"),
                call("https://other.example.com/b"),
            ]
        )
        mock_validate.assert_has_awaits(
            [call("https://example.com/a"), call("https://other.example.com/b")]
        )

    @patch("app.utils.internet_utils._validate_url_for_fetch", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.log.debug")
    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_redirect_budget_exhausted_returns_none(
        self, mock_client_cls: MagicMock, mock_debug: MagicMock, mock_validate: AsyncMock
    ) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            _redirect_response("/hop") for _ in range(_MAX_REDIRECTS + 1)
        ]
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _fetch_following_redirects("https://example.com")

        assert result is None
        assert mock_client.get.await_count == _MAX_REDIRECTS + 1
        mock_debug.assert_called_once_with("redirect_limit_exceeded", url="https://example.com")

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_blocked_redirect_target_propagates(self, mock_client_cls: MagicMock) -> None:
        """A redirect to a blocked address trips the real SSRF guard — no DNS
        needed because the target is an IP literal."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _redirect_response("http://10.0.0.1/")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await _fetch_following_redirects("https://example.com")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."


# ---------------------------------------------------------------------------
# scrape_url_metadata — redirects and content limits
# ---------------------------------------------------------------------------


class TestScrapeRedirectHandling:
    """Redirect-chain behaviour of scrape_url_metadata."""

    @patch("app.utils.internet_utils._validate_url_for_fetch", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_redirect_budget_exhausted_returns_empty_metadata(
        self, mock_client_cls: MagicMock, mock_validate: AsyncMock
    ) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            _redirect_response("/x") for _ in range(_MAX_REDIRECTS + 1)
        ]
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result == URLResponse(url="https://example.com")

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_redirect_to_blocked_ip_propagates_http_exception(
        self, mock_client_cls: MagicMock
    ) -> None:
        """A redirect chain that trips the SSRF guard must raise, not degrade to
        empty metadata."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _redirect_response("http://10.0.0.1/")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await scrape_url_metadata("https://example.com")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "URL host is not allowed."


class TestScrapeContentLimit:
    """The 2 MiB response cap of scrape_url_metadata."""

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_title_beyond_max_bytes_truncated(self, mock_client_cls: MagicMock) -> None:
        """Metadata is parsed from content truncated to _MAX_RESPONSE_BYTES — a
        title beyond the cap must not be visible."""
        content = (
            b"<html><head>"
            + b" " * _MAX_RESPONSE_BYTES
            + b"<title>Tail</title></head><body></body></html>"
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(content=content)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.title is None

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_title_within_max_bytes_parsed(self, mock_client_cls: MagicMock) -> None:
        content = (
            b"<html><head><title>Head</title>"
            + b" " * _MAX_RESPONSE_BYTES
            + b"</head><body></body></html>"
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(content=content)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result.title == "Head"
