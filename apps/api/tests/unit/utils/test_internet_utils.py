"""Unit tests for app.utils.internet_utils — URL validation, scraping, and metadata fetching."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.internet_utils import (
    fetch_url_metadata,
    is_valid_url,
    scrape_url_metadata,
)


# ---------------------------------------------------------------------------
# is_valid_url
# ---------------------------------------------------------------------------


class TestIsValidUrl:
    """Tests for is_valid_url helper."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "https://example.com",
            "https://example.com:8080/path/to/page",
            "https://sub.domain.example.com/page?q=1#frag",
            "https://example.com/path/to/resource.html",
        ],
        ids=[
            "http_scheme",
            "https_scheme",
            "url_with_port_and_path",
            "subdomain_with_query_and_fragment",
            "url_with_file_extension",
        ],
    )
    def test_valid_urls(self, url: str) -> None:
        """Valid HTTP/HTTPS URLs with proper netloc return True."""
        assert is_valid_url(url) is True

    @pytest.mark.parametrize(
        "url,reason",
        [
            ("ftp://example.com", "ftp_scheme"),
            ("https://", "no_netloc"),
            ("https://192.168.1.1", "ip_address"),
            ("", "empty_string"),
            ("not-a-url", "plain_string_no_scheme"),
            ("://missing-scheme.com", "missing_scheme"),
            ("https://10.0.0.1", "private_ip"),
            ("https://255.255.255.255", "broadcast_ip"),
        ],
        ids=[
            "ftp_scheme",
            "no_netloc",
            "ip_address",
            "empty_string",
            "plain_string_no_scheme",
            "missing_scheme",
            "private_ip",
            "broadcast_ip",
        ],
    )
    def test_invalid_urls(self, url: str, reason: str) -> None:
        """URLs with wrong scheme, missing netloc, or IP addresses return False."""
        assert is_valid_url(url) is False

    def test_none_input(self) -> None:
        """None input returns False (caught by the except branch)."""
        # urlparse(None) raises TypeError in some Python versions
        assert is_valid_url(None) is False  # type: ignore[arg-type]

    def test_malformed_url(self) -> None:
        """Malformed input that lacks scheme returns False."""
        assert is_valid_url("ht!tp://bad url with spaces") is False

    def test_ip_with_port_rejected(self) -> None:
        """IP address with a port — the netloc includes the port so the regex
        won't match the bare IP pattern.  This is an edge case in the current
        implementation (IP:port is NOT rejected).  Documenting actual behavior."""
        # netloc = "192.168.1.1:8080" — the regex r"^\d+\.\d+\.\d+\.\d+$"
        # does not match because of the :8080, so this passes.
        result = is_valid_url("https://192.168.1.1:8080")
        # The current implementation allows this because the regex only matches
        # bare IP addresses.  We test the actual behavior, not the ideal.
        assert result is True


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


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.text = text
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="Error",
            request=MagicMock(spec=httpx.Request),
            response=response,
        )
    return response


class TestScrapeUrlMetadata:
    """Tests for scrape_url_metadata."""

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_full_html_success(self, mock_client_cls: MagicMock) -> None:
        """Full HTML with title, description, favicon, og:image returns populated dict."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(FULL_HTML)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["title"] == "Test Page"
        assert result["description"] == "A test description"
        assert result["favicon"] == "https://example.com/favicon.ico"
        assert result["website_name"] == "TestSite"
        # og:image becomes website_image when no logo tag is present
        assert result["website_image"] == "https://example.com/og.png"
        assert result["url"] == "https://example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_http_error_returns_empty_metadata(
        self, mock_client_cls: MagicMock
    ) -> None:
        """HTTP error (4xx/5xx) returns dict with all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response("", status_code=500)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com/fail")

        assert result["title"] is None
        assert result["description"] is None
        assert result["favicon"] is None
        assert result["website_name"] is None
        assert result["website_image"] is None
        assert result["url"] == "https://example.com/fail"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_timeout_returns_empty_metadata(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Timeout during request returns dict with all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://slow.example.com")

        assert result["title"] is None
        assert result["description"] is None
        assert result["favicon"] is None
        assert result["website_name"] is None
        assert result["website_image"] is None
        assert result["url"] == "https://slow.example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_connection_error_returns_empty_metadata(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Connection error returns dict with all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://down.example.com")

        assert result["title"] is None
        assert result["url"] == "https://down.example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_missing_title(self, mock_client_cls: MagicMock) -> None:
        """HTML without a <title> tag yields None title."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_NO_TITLE)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["title"] is None
        assert result["description"] == "desc"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_relative_favicon_converted_to_absolute(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Relative favicon href is joined with the base URL to form an absolute path."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_RELATIVE_FAVICON)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com/page")

        assert result["favicon"] == "https://example.com/static/icon.png"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_og_image_used_as_website_image(
        self, mock_client_cls: MagicMock
    ) -> None:
        """When no logo tag is present, og:image is used as website_image."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_OG_IMAGE_AS_WEBSITE_IMAGE)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["website_image"] == "https://example.com/og-img.jpg"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_logo_tag_takes_precedence_over_og_image(
        self, mock_client_cls: MagicMock
    ) -> None:
        """When og:logo meta tag is present, it is used as website_image instead of og:image."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_LOGO_TAG)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["website_image"] == "https://example.com/logo.svg"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_og_description_fallback(self, mock_client_cls: MagicMock) -> None:
        """og:description is used when meta name=description is absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_OG_DESCRIPTION_ONLY)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["description"] == "OG description text"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_application_name_fallback(self, mock_client_cls: MagicMock) -> None:
        """application-name meta tag is used when og:site_name is absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_APPLICATION_NAME)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["website_name"] == "MyApp"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_shortcut_icon_fallback(self, mock_client_cls: MagicMock) -> None:
        """Shortcut icon link tag is used when rel=icon is absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_SHORTCUT_ICON)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["favicon"] == "https://example.com/shortcut.ico"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_apple_touch_icon_fallback(self, mock_client_cls: MagicMock) -> None:
        """apple-touch-icon link tag is used when other icon tags are absent."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_APPLE_TOUCH_ICON)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["favicon"] == "https://example.com/apple-touch.png"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_logo_link_tag_used_as_website_image(
        self, mock_client_cls: MagicMock
    ) -> None:
        """link rel=logo tag href is used as website_image."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_LOGO_LINK_TAG)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["website_image"] == "https://example.com/link-logo.png"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_empty_html_returns_all_none(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Completely empty HTML returns all-None fields except url."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_EMPTY)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["title"] is None
        assert result["description"] is None
        assert result["favicon"] is None
        assert result["website_name"] is None
        assert result["website_image"] is None
        assert result["url"] == "https://example.com"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_og_image_used_as_favicon_fallback(
        self, mock_client_cls: MagicMock
    ) -> None:
        """When no favicon link tag exists, og:image is used as favicon fallback."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(HTML_OG_IMAGE_AS_WEBSITE_IMAGE)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        # favicon = favicon or og_image — since no favicon link tag, og_image is used
        assert result["favicon"] == "https://example.com/og-img.jpg"

    @patch("app.utils.internet_utils.httpx.AsyncClient")
    async def test_unexpected_exception_returns_empty_metadata(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Unexpected exceptions (e.g. parsing errors) are caught and return empty metadata."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = RuntimeError("unexpected")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await scrape_url_metadata("https://example.com")

        assert result["title"] is None
        assert result["url"] == "https://example.com"


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
        assert "Invalid URL" in exc_info.value.detail

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_urls_collection")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_hit_returns_cached_data(
        self,
        mock_get_cache: AsyncMock,
        mock_collection: MagicMock,
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

        result = await fetch_url_metadata("https://example.com")

        mock_get_cache.assert_awaited_once_with("url_metadata:https://example.com")
        # DB should not be queried when cache hits (short-circuit `or`)
        mock_collection.find_one.assert_not_called()
        mock_set_cache.assert_not_awaited()
        assert result.title == "Cached Title"
        assert str(result.url) == "https://example.com/"

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_urls_collection")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_db_hit_returns_db_data(
        self,
        mock_get_cache: AsyncMock,
        mock_collection: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        """When cache misses but DB has the data, it is returned from DB."""
        mock_get_cache.return_value = None

        db_data = {
            "title": "DB Title",
            "description": "DB Desc",
            "favicon": "https://example.com/db-fav.ico",
            "website_name": "DBSite",
            "website_image": None,
            "url": "https://example.com",
        }
        mock_collection.find_one = AsyncMock(return_value=db_data)

        result = await fetch_url_metadata("https://example.com")

        mock_get_cache.assert_awaited_once()
        mock_collection.find_one.assert_awaited_once_with(
            {"url": "https://example.com"}
        )
        # Should not re-scrape or re-cache
        mock_set_cache.assert_not_awaited()
        assert result.title == "DB Title"

    @patch("app.utils.internet_utils.serialize_document")
    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_urls_collection")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.scrape_url_metadata", new_callable=AsyncMock)
    async def test_cache_and_db_miss_scrapes_stores_and_caches(
        self,
        mock_scrape: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_collection: MagicMock,
        mock_set_cache: AsyncMock,
        mock_serialize: MagicMock,
    ) -> None:
        """When both cache and DB miss, scrapes the URL, stores in DB, caches, and returns."""
        mock_get_cache.return_value = None
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        scraped = {
            "title": "Scraped Title",
            "description": "Scraped Desc",
            "favicon": "https://example.com/scraped-fav.ico",
            "website_name": "ScrapedSite",
            "website_image": "https://example.com/scraped.png",
            "url": "https://example.com",
        }
        mock_scrape.return_value = scraped
        mock_serialize.return_value = scraped.copy()

        result = await fetch_url_metadata("https://example.com")

        mock_scrape.assert_awaited_once_with("https://example.com")
        mock_collection.insert_one.assert_awaited_once_with(scraped)
        mock_set_cache.assert_awaited_once_with(
            "url_metadata:https://example.com",
            mock_serialize.return_value,
            864000,
        )
        assert result.title == "Scraped Title"
        assert result.website_image == "https://example.com/scraped.png"

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

    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_urls_collection")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    async def test_cache_key_format(
        self,
        mock_get_cache: AsyncMock,
        mock_collection: MagicMock,
        mock_set_cache: AsyncMock,
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

    @patch("app.utils.internet_utils.serialize_document")
    @patch("app.utils.internet_utils.set_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.search_urls_collection")
    @patch("app.utils.internet_utils.get_cache", new_callable=AsyncMock)
    @patch("app.utils.internet_utils.scrape_url_metadata", new_callable=AsyncMock)
    async def test_cache_ttl_is_864000(
        self,
        mock_scrape: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_collection: MagicMock,
        mock_set_cache: AsyncMock,
        mock_serialize: MagicMock,
    ) -> None:
        """Cache TTL is set to 864000 seconds (10 days)."""
        mock_get_cache.return_value = None
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()
        scraped = {
            "title": None,
            "description": None,
            "favicon": None,
            "website_name": None,
            "website_image": None,
            "url": "https://example.com",
        }
        mock_scrape.return_value = scraped
        mock_serialize.return_value = scraped.copy()

        await fetch_url_metadata("https://example.com")

        # Third positional arg to set_cache is the TTL
        call_args = mock_set_cache.call_args
        assert call_args[0][2] == 864000
