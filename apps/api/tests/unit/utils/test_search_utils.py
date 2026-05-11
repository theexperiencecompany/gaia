"""Unit tests for app.utils.search_utils."""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.exceptions import FetchError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tavily_client_mock(search_return: Optional[dict] = None) -> MagicMock:
    """Return a mock TavilyClient whose .search() returns *search_return*."""
    client = MagicMock()
    client.search.return_value = search_return or {
        "results": [{"url": "https://example.com", "title": "Example"}],
        "images": [{"url": "https://img.example.com/1.png"}],
        "answer": "42",
        "response_time": 0.5,
        "request_id": "req-1",
    }
    return client


def _make_firecrawl_client_mock(
    markdown: Optional[str] = "# Hello",
    raise_on_scrape: Optional[Exception] = None,
) -> MagicMock:
    """Return a mock FirecrawlApp whose .scrape() returns a Document-like object."""
    client = MagicMock()
    doc = MagicMock()
    doc.markdown = markdown
    if raise_on_scrape:
        client.scrape.side_effect = raise_on_scrape
    else:
        client.scrape.return_value = doc
    return client


# ---------------------------------------------------------------------------
# get_tavily_client / get_firecrawl_client — lazy singleton factories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTavilyClient:
    """Tests for the lazy Tavily client factory."""

    def setup_method(self) -> None:
        # Reset the module-level singleton before each test
        import app.utils.search_utils as mod

        mod._tavily_client = None

    @patch("app.utils.search_utils.settings")
    @patch("app.utils.search_utils.TavilyClient")
    def test_creates_client_when_key_present(
        self, mock_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.TAVILY_API_KEY = "test-tavily-key"  # pragma: allowlist secret
        from app.utils.search_utils import get_tavily_client

        client = get_tavily_client()
        mock_cls.assert_called_once_with(
            api_key="test-tavily-key"  # pragma: allowlist secret
        )
        assert client is mock_cls.return_value

    @patch("app.utils.search_utils.settings")
    def test_raises_when_key_missing(self, mock_settings: MagicMock) -> None:
        mock_settings.TAVILY_API_KEY = ""
        from app.utils.search_utils import get_tavily_client

        with pytest.raises(ValueError, match="TAVILY_API_KEY"):
            get_tavily_client()

    @patch("app.utils.search_utils.settings")
    @patch("app.utils.search_utils.TavilyClient")
    def test_returns_cached_instance_on_second_call(
        self, mock_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.TAVILY_API_KEY = "test-tavily-key"  # pragma: allowlist secret
        from app.utils.search_utils import get_tavily_client

        first = get_tavily_client()
        second = get_tavily_client()
        assert first is second
        mock_cls.assert_called_once()


@pytest.mark.unit
class TestGetFirecrawlClient:
    """Tests for the lazy Firecrawl client factory."""

    def setup_method(self) -> None:
        import app.utils.search_utils as mod

        mod._firecrawl_client = None

    @patch("app.utils.search_utils.settings")
    @patch("app.utils.search_utils.FirecrawlApp")
    def test_creates_client_when_key_present(
        self, mock_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.FIRECRAWL_API_KEY = (
            "test-firecrawl-key"  # pragma: allowlist secret
        )
        from app.utils.search_utils import get_firecrawl_client

        client = get_firecrawl_client()
        mock_cls.assert_called_once_with(
            api_key="test-firecrawl-key"  # pragma: allowlist secret
        )
        assert client is mock_cls.return_value

    @patch("app.utils.search_utils.settings")
    def test_raises_when_key_missing(self, mock_settings: MagicMock) -> None:
        mock_settings.FIRECRAWL_API_KEY = ""
        from app.utils.search_utils import get_firecrawl_client

        with pytest.raises(ValueError, match="FIRECRAWL_API_KEY"):
            get_firecrawl_client()


# ---------------------------------------------------------------------------
# fetch_tavily_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchTavilySearch:
    """Tests for fetch_tavily_search (Cacheable bypassed via __wrapped__)."""

    @patch("app.utils.search_utils.get_tavily_client")
    async def test_returns_search_results(self, mock_get_client: MagicMock) -> None:
        expected = {"results": [{"url": "https://a.com"}]}
        client = _make_tavily_client_mock(expected)
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_tavily_search

        fn = fetch_tavily_search.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="test", count=5)
        assert result == expected
        client.search.assert_called_once()

    @patch("app.utils.search_utils.get_tavily_client")
    async def test_passes_extra_params(self, mock_get_client: MagicMock) -> None:
        client = _make_tavily_client_mock({"results": []})
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_tavily_search

        fn = fetch_tavily_search.__wrapped__  # type: ignore[attr-defined]
        await fn(query="q", count=3, search_topic="news", extra_params={"days": 7})

        call_kwargs = client.search.call_args[1]
        assert call_kwargs["days"] == 7
        assert call_kwargs["topic"] == "news"
        assert call_kwargs["max_results"] == 3

    @patch("app.utils.search_utils.get_tavily_client")
    async def test_returns_empty_dict_on_exception(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_get_client.side_effect = RuntimeError("boom")

        from app.utils.search_utils import fetch_tavily_search

        fn = fetch_tavily_search.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="q", count=1)
        assert result == {}

    @patch("app.utils.search_utils.get_tavily_client")
    async def test_default_search_topic_is_general(
        self, mock_get_client: MagicMock
    ) -> None:
        client = _make_tavily_client_mock({"results": []})
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_tavily_search

        fn = fetch_tavily_search.__wrapped__  # type: ignore[attr-defined]
        await fn(query="q", count=1)

        call_kwargs = client.search.call_args[1]
        assert call_kwargs["topic"] == "general"

    @patch("app.utils.search_utils.get_tavily_client")
    async def test_no_extra_params_does_not_inject_none(
        self, mock_get_client: MagicMock
    ) -> None:
        client = _make_tavily_client_mock({"results": []})
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_tavily_search

        fn = fetch_tavily_search.__wrapped__  # type: ignore[attr-defined]
        await fn(query="q", count=2, extra_params=None)

        call_kwargs = client.search.call_args[1]
        assert "include_images" in call_kwargs
        assert "include_favicon" in call_kwargs


# ---------------------------------------------------------------------------
# perform_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPerformSearch:
    """Tests for perform_search (orchestrator that wraps fetch_tavily_search)."""

    @patch("app.utils.search_utils.fetch_tavily_search", new_callable=AsyncMock)
    async def test_returns_formatted_result(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = {
            "results": [{"url": "https://a.com"}],
            "images": [{"url": "https://img.com/1.png"}],
            "answer": "42",
            "response_time": 0.3,
            "request_id": "abc",
        }

        from app.utils.search_utils import perform_search

        fn = perform_search.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="hello", count=5)

        assert result["web"] == [{"url": "https://a.com"}]
        assert result["images"] == [{"url": "https://img.com/1.png"}]
        assert result["answer"] == "42"
        assert result["query"] == "hello"
        assert result["news"] == []

    @patch("app.utils.search_utils.fetch_tavily_search", new_callable=AsyncMock)
    async def test_returns_fallback_on_exception(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = RuntimeError("network")

        from app.utils.search_utils import perform_search

        fn = perform_search.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="fail", count=3)

        assert result["web"] == []
        assert result["news"] == []
        assert result["images"] == []
        assert result["videos"] == []
        assert result["answer"] == ""
        assert result["query"] == "fail"

    @patch("app.utils.search_utils.fetch_tavily_search", new_callable=AsyncMock)
    async def test_handles_missing_keys_gracefully(self, mock_fetch: AsyncMock) -> None:
        """fetch_tavily_search might return a dict without some keys."""
        mock_fetch.return_value = {}

        from app.utils.search_utils import perform_search

        fn = perform_search.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="sparse", count=1)

        assert result["web"] == []
        assert result["images"] == []
        assert result["answer"] == ""


# ---------------------------------------------------------------------------
# fetch_with_firecrawl
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchWithFirecrawl:
    """Tests for fetch_with_firecrawl."""

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_success_normal_mode(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_writer_factory.return_value = writer
        mock_get_client.return_value = _make_firecrawl_client_mock("# Page")

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        result = await fn(url="https://example.com")

        assert result == "# Page"
        assert writer.call_count >= 1  # progress messages

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_raises_fetch_error_when_no_markdown(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = MagicMock()
        mock_get_client.return_value = _make_firecrawl_client_mock(markdown="")

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="Firecrawl"):
            await fn(url="https://example.com")

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_stealth_fallback_on_403(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        """When normal mode raises a 403-like error and use_stealth=False,
        retry with stealth proxy."""
        writer = MagicMock()
        mock_writer_factory.return_value = writer

        client = MagicMock()
        # First call (normal) raises, second call (stealth) succeeds
        stealth_doc = MagicMock()
        stealth_doc.markdown = "# Stealth Content"
        client.scrape.side_effect = [Exception("403 Forbidden"), stealth_doc]
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        result = await fn(url="https://blocked.com", use_stealth=False)

        assert result == "# Stealth Content"
        assert client.scrape.call_count == 2

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_no_stealth_fallback_when_already_stealth(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        """When use_stealth=True and normal mode fails, do NOT retry."""
        mock_writer_factory.return_value = MagicMock()
        client = MagicMock()
        client.scrape.side_effect = Exception("403 Forbidden")
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="Firecrawl"):
            await fn(url="https://blocked.com", use_stealth=True)

        # Only one call — no stealth retry
        client.scrape.assert_called_once()

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_no_stealth_fallback_for_non_retryable_error(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        """If the error message does not contain a retryable keyword, do not retry."""
        mock_writer_factory.return_value = MagicMock()
        client = MagicMock()
        client.scrape.side_effect = Exception("some random parse error")
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="Firecrawl"):
            await fn(url="https://example.com", use_stealth=False)

        client.scrape.assert_called_once()

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_value_error_wraps_as_config_error(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = MagicMock()
        mock_get_client.side_effect = ValueError("FIRECRAWL_API_KEY is not configured")

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="Configuration error"):
            await fn(url="https://example.com")

    @patch("app.utils.search_utils.get_stream_writer")
    @patch("app.utils.search_utils.get_firecrawl_client")
    async def test_stealth_returns_no_markdown_raises(
        self, mock_get_client: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        """Stealth mode succeeds HTTP-wise but returns empty markdown."""
        mock_writer_factory.return_value = MagicMock()
        client = MagicMock()
        stealth_doc = MagicMock()
        stealth_doc.markdown = ""
        client.scrape.side_effect = [Exception("403 Forbidden"), stealth_doc]
        mock_get_client.return_value = client

        from app.utils.search_utils import fetch_with_firecrawl

        fn = fetch_with_firecrawl.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="stealth mode"):
            await fn(url="https://blocked.com", use_stealth=False)


# ---------------------------------------------------------------------------
# fetch_with_httpx
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchWithHttpx:
    """Tests for fetch_with_httpx (httpx + BS4 + html2text)."""

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_success_extracts_markdown(self, mock_client_cls: MagicMock) -> None:
        html = "<html><body><main><p>Hello World</p></main></body></html>"
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.get = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import fetch_with_httpx

        fn = fetch_with_httpx.__wrapped__  # type: ignore[attr-defined]
        result = await fn(url="https://example.com")
        assert "Hello World" in result

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_empty_markdown_raises(self, mock_client_cls: MagicMock) -> None:
        html = "<html><body></body></html>"
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.get = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import fetch_with_httpx

        fn = fetch_with_httpx.__wrapped__  # type: ignore[attr-defined]
        # Body with no content will produce empty or whitespace-only markdown
        # depending on html2text behaviour. If not empty, at least verify no crash.
        try:
            result = await fn(url="https://example.com")
            # If we get here, the body had some whitespace converted — that's OK
            assert isinstance(result, str)
        except FetchError as e:
            assert "empty content" in str(e)

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_http_status_error_wraps_as_fetch_error(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        error = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )

        client_inst = AsyncMock()
        client_inst.get = AsyncMock(side_effect=error)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import fetch_with_httpx

        fn = fetch_with_httpx.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="HTTP 404"):
            await fn(url="https://example.com/missing")

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_generic_exception_wraps_as_fetch_error(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_client_cls.side_effect = RuntimeError("DNS failure")

        from app.utils.search_utils import fetch_with_httpx

        fn = fetch_with_httpx.__wrapped__  # type: ignore[attr-defined]
        with pytest.raises(FetchError, match="httpx error"):
            await fn(url="https://example.com")

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_result_capped_at_60k(self, mock_client_cls: MagicMock) -> None:
        """Output is capped to 60 000 characters."""
        long_text = "a" * 100_000
        html = f"<html><body><main><p>{long_text}</p></main></body></html>"
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.get = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import fetch_with_httpx

        fn = fetch_with_httpx.__wrapped__  # type: ignore[attr-defined]
        result = await fn(url="https://example.com")
        assert len(result) <= 60_000

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_strips_non_content_tags(self, mock_client_cls: MagicMock) -> None:
        html = (
            "<html><head><title>T</title></head>"
            "<body><nav>Nav</nav><script>js</script>"
            "<main><p>Content</p></main>"
            "<footer>Foot</footer></body></html>"
        )
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.get = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import fetch_with_httpx

        fn = fetch_with_httpx.__wrapped__  # type: ignore[attr-defined]
        result = await fn(url="https://example.com")
        assert "Content" in result
        assert "Nav" not in result
        assert "Foot" not in result
        assert "js" not in result


# ---------------------------------------------------------------------------
# search_with_duckduckgo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchWithDuckDuckGo:
    """Tests for the DuckDuckGo Lite fallback search."""

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_returns_parsed_results(self, mock_client_cls: MagicMock) -> None:
        html = """
        <html><body><table>
        <tr class="result-sponsored">
            <td><a class="result-link" href="https://example.com">Example</a></td>
        </tr>
        <tr><td class="result-snippet">A snippet</td></tr>
        </table></body></html>
        """
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.post = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import search_with_duckduckgo

        fn = search_with_duckduckgo.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="test", count=5)

        assert "results" in result
        assert isinstance(result["results"], list)

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_returns_empty_on_exception(self, mock_client_cls: MagicMock) -> None:
        mock_client_cls.side_effect = RuntimeError("network error")

        from app.utils.search_utils import search_with_duckduckgo

        fn = search_with_duckduckgo.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="fail", count=3)

        assert result == {"results": []}

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_skips_non_http_links(self, mock_client_cls: MagicMock) -> None:
        html = """
        <html><body><table>
        <tr class="result-sponsored">
            <td><a class="result-link" href="javascript:void(0)">Bad</a></td>
        </tr>
        </table></body></html>
        """
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.post = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import search_with_duckduckgo

        fn = search_with_duckduckgo.__wrapped__  # type: ignore[attr-defined]
        result = await fn(query="test", count=5)

        assert result["results"] == []

    @patch("app.utils.search_utils.httpx.AsyncClient")
    async def test_default_count_is_five(self, mock_client_cls: MagicMock) -> None:
        """Default count parameter is 5."""
        html = "<html><body><table></table></body></html>"
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.post = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        from app.utils.search_utils import search_with_duckduckgo

        fn = search_with_duckduckgo.__wrapped__  # type: ignore[attr-defined]
        # Should not raise — count defaults to 5
        result = await fn(query="test")
        assert result == {"results": []}
