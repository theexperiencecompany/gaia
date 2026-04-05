"""Unit tests for app.utils.crawl4ai_utils."""

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestBatchFetchWithCrawl4ai:
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_matches_redirected_results_to_requested_urls(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        result_example = MagicMock()
        result_example.success = True
        result_example.markdown = "example content"
        result_example.url = "https://example.com"
        result_example.redirected_url = "https://example.com/"

        result_httpbin = MagicMock()
        result_httpbin.success = True
        result_httpbin.markdown = "httpbin content"
        result_httpbin.url = "https://httpbin.org/redirect-to?url=https://example.com/"
        result_httpbin.redirected_url = "https://example.com/"

        # Deliberately reversed order to validate URL-based matching.
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(
            return_value=[result_httpbin, result_example]
        )
        mock_crawler_cls.return_value = crawler_inst

        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        urls = [
            "https://example.com",
            "https://httpbin.org/redirect-to?url=https://example.com/",
        ]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert errors == {}
        assert contents["https://example.com"] == "example content"
        assert (
            contents["https://httpbin.org/redirect-to?url=https://example.com/"]
            == "httpbin content"
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_batch_timeout_recovers_per_url(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        success_result = MagicMock()
        success_result.success = True
        success_result.markdown = "ok"
        success_result.error_message = ""

        fail_result = MagicMock()
        fail_result.success = False
        fail_result.markdown = ""
        fail_result.error_message = "blocked"

        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(
            side_effect=[asyncio.TimeoutError(), [success_result], [fail_result]]
        )
        mock_crawler_cls.return_value = crawler_inst

        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        urls = ["https://good.example", "https://bad.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            semaphore_count=5,
            context_name="test",
        )

        assert contents["https://good.example"] == "ok"
        assert errors["https://bad.example"] == "blocked"
