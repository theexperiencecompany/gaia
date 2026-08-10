"""Unit tests for app.utils.crawl4ai_utils."""

import asyncio
from collections import defaultdict, deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.search import CRAWL4AI_CLOSE_TIMEOUT_SECONDS, CRAWL4AI_WAIT_UNTIL
from app.utils.crawl4ai_utils import (
    _EXCLUDED_TAGS,
    _build_markdown_generator,
    _build_run_config,
    _close_crawler,
    _extract_content_or_error,
    _match_result_to_request_index,
    _normalize_url,
    _recover_with_single_url_crawls,
    _spawn_shielded_close,
    batch_fetch_with_crawl4ai,
    get_browser_semaphore,
    managed_crawler,
)


class TestNormalizeUrl:
    def test_lowercases_scheme_and_netloc(self) -> None:
        assert (
            _normalize_url("HTTPS://Example.COM:8443/Search/Query")
            == "https://example.com:8443/Search/Query"
        )

    def test_keeps_root_trailing_slash(self) -> None:
        assert _normalize_url("https://example.com/") == "https://example.com/"

    def test_strips_trailing_slash_from_non_root_path(self) -> None:
        assert _normalize_url("https://example.com/a/b/") == "https://example.com/a/b"

    def test_preserves_query_and_drops_fragment(self) -> None:
        assert (
            _normalize_url("https://example.com/a?x=1&y=2#frag") == "https://example.com/a?x=1&y=2"
        )

    def test_empty_path_has_no_trailing_slash(self) -> None:
        assert _normalize_url("https://example.com") == "https://example.com"

    def test_does_not_strip_non_slash_suffix(self) -> None:
        assert _normalize_url("https://example.com/a/b/X") == "https://example.com/a/b/X"


class TestBuildMarkdownGenerator:
    def _expected_options(self) -> dict[str, object]:
        return {
            "ignore_links": False,
            "ignore_images": True,
            "skip_internal_links": True,
            "body_width": 0,
            "escape_html": False,
        }

    @patch("app.utils.crawl4ai_utils.DefaultMarkdownGenerator")
    @patch("app.utils.crawl4ai_utils.BM25ContentFilter")
    def test_plain_fetch_builds_generator_without_filter(
        self, mock_filter: MagicMock, mock_generator_cls: MagicMock
    ) -> None:
        generator = _build_markdown_generator()

        mock_filter.assert_not_called()
        mock_generator_cls.assert_called_once_with(
            content_source="cleaned_html",
            content_filter=None,
            options=self._expected_options(),
        )
        assert generator is mock_generator_cls.return_value

    @patch("app.utils.crawl4ai_utils.DefaultMarkdownGenerator")
    @patch("app.utils.crawl4ai_utils.BM25ContentFilter")
    def test_content_query_builds_bm25_filter(
        self, mock_filter: MagicMock, mock_generator_cls: MagicMock
    ) -> None:
        generator = _build_markdown_generator(content_query="quantum computing")

        mock_filter.assert_called_once_with(user_query="quantum computing", bm25_threshold=1.0)
        mock_generator_cls.assert_called_once_with(
            content_source="cleaned_html",
            content_filter=mock_filter.return_value,
            options=self._expected_options(),
        )
        assert generator is mock_generator_cls.return_value


class TestBuildRunConfig:
    @patch("app.utils.crawl4ai_utils.CrawlerRunConfig")
    @patch("app.utils.crawl4ai_utils._build_markdown_generator")
    def test_standard_fetch_kwargs(
        self, mock_generator: MagicMock, mock_config_cls: MagicMock
    ) -> None:
        generator = mock_generator.return_value

        _build_run_config(
            page_timeout_ms=30_000, semaphore_count=3, content_query=None, thorough=False
        )

        mock_generator.assert_called_once_with(None)
        assert mock_config_cls.call_args.kwargs == {
            "page_timeout": 30_000,
            "wait_until": CRAWL4AI_WAIT_UNTIL,
            "semaphore_count": 3,
            "markdown_generator": generator,
            "excluded_tags": _EXCLUDED_TAGS,
            "word_count_threshold": 10,
            "remove_overlay_elements": True,
            "verbose": False,
        }
        assert "scan_full_page" not in mock_config_cls.call_args.kwargs
        assert "magic" not in mock_config_cls.call_args.kwargs
        assert "delay_before_return_html" not in mock_config_cls.call_args.kwargs

    @patch("app.utils.crawl4ai_utils.CrawlerRunConfig")
    @patch("app.utils.crawl4ai_utils._build_markdown_generator")
    def test_thorough_fetch_adds_scan_magic_and_delay(
        self, mock_generator: MagicMock, mock_config_cls: MagicMock
    ) -> None:
        generator = mock_generator.return_value

        _build_run_config(
            page_timeout_ms=15_000, semaphore_count=1, content_query="topic", thorough=True
        )

        mock_generator.assert_called_once_with("topic")
        assert mock_config_cls.call_args.kwargs == {
            "page_timeout": 15_000,
            "wait_until": CRAWL4AI_WAIT_UNTIL,
            "semaphore_count": 1,
            "markdown_generator": generator,
            "excluded_tags": _EXCLUDED_TAGS,
            "word_count_threshold": 10,
            "remove_overlay_elements": True,
            "verbose": False,
            "scan_full_page": True,
            "magic": True,
            "delay_before_return_html": 1.0,
        }


class TestCloseCrawler:
    async def test_awaits_close_without_logging_on_success(self) -> None:
        crawler = AsyncMock()

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            await _close_crawler(crawler, "ctx")

        crawler.close.assert_awaited_once()
        mock_warning.assert_not_called()

    async def test_logs_warning_when_close_fails(self) -> None:
        crawler = AsyncMock()
        crawler.close = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            await _close_crawler(crawler, "ctx")

        crawler.close.assert_awaited_once()
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} browser close failed",
            context_name="ctx",
            error="boom",
            error_type="RuntimeError",
        )


class TestSpawnShieldedClose:
    async def test_spawns_close_crawler_that_closes_with_context(self) -> None:
        crawler = AsyncMock()
        crawler.close = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("app.utils.crawl4ai_utils.spawn_background_task") as mock_spawn,
            patch("app.utils.crawl4ai_utils.log.warning") as mock_warning,
        ):
            result = _spawn_shielded_close(crawler, "ctx")
            assert result is mock_spawn.return_value
            mock_spawn.assert_called_once()
            coro = mock_spawn.call_args.args[0]
            assert asyncio.iscoroutine(coro)
            await coro

        crawler.close.assert_awaited_once()
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} browser close failed",
            context_name="ctx",
            error="boom",
            error_type="RuntimeError",
        )


class TestGetBrowserSemaphore:
    def test_returns_loop_bound_semaphore_for_crawl4ai_key(self) -> None:
        semaphore = MagicMock()

        with patch(
            "app.utils.crawl4ai_utils.loop_bound_semaphore", return_value=semaphore
        ) as mock_lbs:
            result = get_browser_semaphore()

        assert result is semaphore
        mock_lbs.assert_called_once_with("crawl4ai_browser", settings.CRAWL4AI_MAX_BROWSERS)


class TestManagedCrawler:
    def _crawler_inst(self) -> AsyncMock:
        crawler = AsyncMock()
        crawler.close = AsyncMock()
        return crawler

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    async def test_default_config_starts_yields_and_closes(
        self, mock_browser_config: MagicMock, mock_crawler_cls: MagicMock
    ) -> None:
        crawler = self._crawler_inst()
        mock_crawler_cls.return_value = crawler
        spawned_coros: list[object] = []

        def fake_spawn(coro: object) -> asyncio.Task[None]:
            spawned_coros.append(coro)
            assert asyncio.iscoroutine(coro)
            return asyncio.ensure_future(coro)

        real_wait_for = asyncio.wait_for

        async def capturing_wait_for(coro: object, **kwargs: object) -> object:
            return await real_wait_for(coro, **kwargs)

        with (
            patch("app.utils.crawl4ai_utils.spawn_background_task", side_effect=fake_spawn),
            patch("asyncio.wait_for", side_effect=capturing_wait_for) as mock_wait_for,
        ):
            async with managed_crawler() as crawler_from_cm:
                assert crawler_from_cm is crawler

        mock_browser_config.assert_called_once_with(headless=True, verbose=False)
        mock_crawler_cls.assert_called_once_with(config=mock_browser_config.return_value)
        crawler.start.assert_awaited_once()
        assert len(spawned_coros) == 1
        crawler.close.assert_awaited_once()
        mock_wait_for.assert_called_once()
        assert mock_wait_for.call_args.kwargs["timeout"] == CRAWL4AI_CLOSE_TIMEOUT_SECONDS

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    async def test_custom_config_passed_through_without_default(
        self, mock_browser_config: MagicMock, mock_crawler_cls: MagicMock
    ) -> None:
        custom_config = MagicMock()
        crawler = self._crawler_inst()
        mock_crawler_cls.return_value = crawler

        async with managed_crawler(custom_config):
            pass

        mock_browser_config.assert_not_called()
        mock_crawler_cls.assert_called_once_with(config=custom_config)

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_start_failure_still_spawns_close_and_propagates(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        crawler = self._crawler_inst()
        crawler.start = AsyncMock(side_effect=RuntimeError("no browser"))
        crawler.close = AsyncMock(side_effect=RuntimeError("boom"))
        mock_crawler_cls.return_value = crawler
        spawned_tasks: list[asyncio.Task[None]] = []

        def fake_spawn(coro: object) -> asyncio.Task[None]:
            task = asyncio.ensure_future(coro)
            spawned_tasks.append(task)
            return task

        with (
            patch("app.utils.crawl4ai_utils.spawn_background_task", side_effect=fake_spawn),
            patch("app.utils.crawl4ai_utils.log.warning") as mock_warning,
        ):
            with pytest.raises(RuntimeError, match="no browser"):
                async with managed_crawler():
                    pytest.fail("body must not run")
            assert len(spawned_tasks) == 1
            await spawned_tasks[0]

        crawler.close.assert_awaited_once()
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} browser close failed",
            context_name="crawl4ai",
            error="boom",
            error_type="RuntimeError",
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_start_cancellation_still_spawns_close(self, mock_crawler_cls: MagicMock) -> None:
        crawler = self._crawler_inst()
        crawler.start = AsyncMock(side_effect=asyncio.CancelledError())
        mock_crawler_cls.return_value = crawler
        spawned_tasks: list[asyncio.Task[None]] = []

        def fake_spawn(coro: object) -> asyncio.Task[None]:
            task = asyncio.ensure_future(coro)
            spawned_tasks.append(task)
            return task

        with patch("app.utils.crawl4ai_utils.spawn_background_task", side_effect=fake_spawn):
            with pytest.raises(asyncio.CancelledError):
                async with managed_crawler():
                    pytest.fail("body must not run")

        assert len(spawned_tasks) == 1
        await spawned_tasks[0]
        crawler.close.assert_awaited_once()

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_close_failure_warns_with_context_name(self, mock_crawler_cls: MagicMock) -> None:
        crawler = self._crawler_inst()
        crawler.close = AsyncMock(side_effect=RuntimeError("boom"))
        mock_crawler_cls.return_value = crawler

        def fake_spawn(coro: object) -> asyncio.Task[None]:
            return asyncio.ensure_future(coro)

        with (
            patch("app.utils.crawl4ai_utils.spawn_background_task", side_effect=fake_spawn),
            patch("app.utils.crawl4ai_utils.log.warning") as mock_warning,
        ):
            async with managed_crawler(context_name="deep"):
                pass

        crawler.close.assert_awaited_once()
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} browser close failed",
            context_name="deep",
            error="boom",
            error_type="RuntimeError",
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_close_timeout_warns_and_does_not_raise(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        crawler = self._crawler_inst()
        mock_crawler_cls.return_value = crawler

        def fake_spawn(coro: object) -> asyncio.Task[None]:
            return asyncio.ensure_future(coro)

        with (
            patch("app.utils.crawl4ai_utils.spawn_background_task", side_effect=fake_spawn),
            patch("asyncio.wait_for", side_effect=TimeoutError()) as mock_wait_for,
            patch("app.utils.crawl4ai_utils.log.warning") as mock_warning,
        ):
            async with managed_crawler():
                pass

        await asyncio.sleep(0)
        mock_wait_for.assert_called_once()
        assert mock_wait_for.call_args.kwargs["timeout"] == CRAWL4AI_CLOSE_TIMEOUT_SECONDS
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} browser close still running ; leaving it to finish in background",
            context_name="crawl4ai",
            crawl4ai_close_timeout_seconds=CRAWL4AI_CLOSE_TIMEOUT_SECONDS,
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_close_survives_cancellation_while_awaiting_close(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        crawler = self._crawler_inst()
        close_gate = asyncio.Event()
        crawler.close = AsyncMock(side_effect=close_gate.wait)
        mock_crawler_cls.return_value = crawler
        spawned_tasks: list[asyncio.Task[None]] = []

        def fake_spawn(coro: object) -> asyncio.Task[None]:
            task = asyncio.ensure_future(coro)
            spawned_tasks.append(task)
            return task

        async def drive() -> None:
            async with managed_crawler() as crawler_from_cm:
                assert crawler_from_cm is crawler
                task = asyncio.current_task()
                asyncio.get_running_loop().call_soon(task.cancel)

        with patch("app.utils.crawl4ai_utils.spawn_background_task", side_effect=fake_spawn):
            try:
                with pytest.raises(asyncio.CancelledError):
                    await drive()
            finally:
                close_gate.set()

        assert len(spawned_tasks) == 1
        close_task = spawned_tasks[0]
        await close_task
        assert close_task.done()
        assert not close_task.cancelled()
        crawler.close.assert_awaited_once()


class TestExtractContentOrError:
    def test_str_markdown_with_success_returns_text(self) -> None:
        result = SimpleNamespace(success=True, markdown="page content", error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == ("page content", None)

    def test_str_markdown_truncated_to_max_content_chars(self) -> None:
        result = SimpleNamespace(success=True, markdown="x" * 100, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=20
        )

        assert (content, error) == ("x" * 20, None)

    def test_text_is_not_stripped(self) -> None:
        result = SimpleNamespace(success=True, markdown="  padded  ", error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == ("  padded  ", None)

    def test_whitespace_only_text_falls_back_to_error_message(self) -> None:
        result = SimpleNamespace(success=True, markdown="   ", error_message="empty page")

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "empty page")

    def test_whitespace_only_text_uses_default_error(self) -> None:
        result = SimpleNamespace(success=True, markdown="   ", error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_failed_result_returns_error_message_even_with_text(self) -> None:
        result = SimpleNamespace(success=False, markdown="ignored", error_message="blocked")

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "blocked")

    def test_missing_success_flag_is_failure(self) -> None:
        result = SimpleNamespace(markdown="no success attr")

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_missing_markdown_attribute_is_error(self) -> None:
        result = SimpleNamespace(success=True)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_no_error_message_uses_default(self) -> None:
        result = SimpleNamespace(success=False, markdown="", error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_markdown_generation_result_prefers_fit_markdown(self) -> None:
        markdown = SimpleNamespace(fit_markdown="fit text", raw_markdown="raw text")
        result = SimpleNamespace(success=True, markdown=markdown, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == ("fit text", None)

    def test_markdown_generation_result_falls_back_to_raw_markdown(self) -> None:
        markdown = SimpleNamespace(fit_markdown="", raw_markdown="raw text")
        result = SimpleNamespace(success=True, markdown=markdown, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == ("raw text", None)

    def test_markdown_generation_result_fit_none_falls_back_to_raw(self) -> None:
        markdown = SimpleNamespace(fit_markdown=None, raw_markdown="raw text")
        result = SimpleNamespace(success=True, markdown=markdown, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == ("raw text", None)

    def test_fit_markdown_truncated_by_max_content_chars(self) -> None:
        markdown = SimpleNamespace(fit_markdown="x" * 100, raw_markdown="y" * 100)
        result = SimpleNamespace(success=True, markdown=markdown, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=5
        )

        assert (content, error) == ("x" * 5, None)

    def test_markdown_object_without_fit_or_raw_is_error(self) -> None:
        markdown = SimpleNamespace(other="value")
        result = SimpleNamespace(success=True, markdown=markdown, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_none_markdown_with_success_is_error(self) -> None:
        result = SimpleNamespace(success=True, markdown=None, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_non_string_markdown_is_error(self) -> None:
        result = SimpleNamespace(success=True, markdown=123, error_message=None)

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == (None, "test returned empty content")

    def test_success_wins_over_error_message(self) -> None:
        result = SimpleNamespace(success=True, markdown="ok", error_message="stale error")

        content, error = _extract_content_or_error(
            result=result, context_name="test", max_content_chars=None
        )

        assert (content, error) == ("ok", None)


class TestMatchResultToRequestIndex:
    def _match(
        self,
        result: object,
        remaining: set[int] | None = None,
        exact: dict[str, deque[int]] | None = None,
        normalized: dict[str, deque[int]] | None = None,
    ) -> int | None:
        return _match_result_to_request_index(
            result,
            remaining_indices=remaining if remaining is not None else {0},
            requested_by_exact=exact if exact is not None else defaultdict(deque),
            requested_by_normalized=normalized if normalized is not None else defaultdict(deque),
        )

    def test_exact_match_by_url(self) -> None:
        result = SimpleNamespace(url="https://example.com/a")

        assert (
            self._match(
                result,
                exact={"https://example.com/a": deque([0])},
                normalized={"https://example.com/a": deque([0])},
            )
            == 0
        )

    def test_exact_match_by_redirected_url(self) -> None:
        result = SimpleNamespace(
            url="https://original.example", redirected_url="https://target.example"
        )

        assert (
            self._match(
                result,
                exact=defaultdict(deque, {"https://target.example": deque([0])}),
            )
            == 0
        )

    def test_exact_url_match_preferred_over_redirected(self) -> None:
        result = SimpleNamespace(
            url="https://example.com/a", redirected_url="https://example.com/b"
        )

        assert (
            self._match(
                result,
                remaining={0, 1},
                exact={
                    "https://example.com/a": deque([0]),
                    "https://example.com/b": deque([1]),
                },
            )
            == 0
        )

    def test_normalized_fallback_when_no_exact_match(self) -> None:
        result = SimpleNamespace(url="https://example.com/a")

        assert self._match(result, normalized={"https://example.com/a": deque([0])}) == 0

    def test_exact_match_preferred_over_normalized(self) -> None:
        result = SimpleNamespace(url="https://example.com/a")

        assert (
            self._match(
                result,
                remaining={0, 1},
                exact={"https://example.com/a": deque([1])},
                normalized={"https://example.com/a": deque([0])},
            )
            == 1
        )

    def test_consumed_index_falls_through_to_next_candidate(self) -> None:
        result = SimpleNamespace(url="https://example.com/a")

        assert (
            self._match(
                result,
                remaining={1},
                exact={"https://example.com/a": deque([0])},
                normalized={"https://example.com/a": deque([1])},
            )
            == 1
        )

    def test_no_url_fields_returns_none(self) -> None:
        assert self._match(SimpleNamespace()) is None

    def test_non_string_url_skipped_redirected_used(self) -> None:
        result = SimpleNamespace(url=123, redirected_url="https://example.com/a")

        assert self._match(result, exact={"https://example.com/a": deque([0])}) == 0

    def test_all_consumed_indices_returns_none(self) -> None:
        result = SimpleNamespace(url="https://example.com/a")

        assert (
            self._match(
                result,
                remaining={2},
                exact={"https://example.com/a": deque([0, 1])},
                normalized={"https://example.com/a": deque([0, 1])},
            )
            is None
        )

    def test_duplicate_requested_urls_consume_in_order(self) -> None:
        result = SimpleNamespace(url="https://example.com/a")
        exact = {"https://example.com/a": deque([0, 1])}
        normalized = {"https://example.com/a": deque([0, 1])}
        remaining = {0, 1}

        assert self._match(result, remaining=remaining, exact=exact, normalized=normalized) == 0
        remaining.discard(0)
        assert self._match(result, remaining=remaining, exact=exact, normalized=normalized) == 1


class TestRecoverWithSingleUrlCrawls:
    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_successful_recovery_crawls_each_url(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        run_config = mock_build_config.return_value
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        first = MagicMock(success=True, markdown="first content", url="https://a.example")
        second = MagicMock(success=True, markdown="second content", url="https://b.example")
        crawler.arun_many = AsyncMock(side_effect=[[first], [second]])

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example", "https://b.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {
            "https://a.example": "first content",
            "https://b.example": "second content",
        }
        assert errors == {}
        mock_build_config.assert_called_once_with(
            page_timeout_ms=30_000, semaphore_count=1, content_query=None, thorough=False
        )
        mock_browser_config.assert_called_once_with(
            headless=True, browser_mode="dedicated", verbose=False
        )
        mock_managed.assert_called_once_with(mock_browser_config.return_value, context_name="test")
        mock_semaphore.return_value.__aenter__.assert_awaited()
        assert crawler.arun_many.await_count == 2
        crawler.arun_many.assert_any_await(urls=["https://a.example"], config=run_config)
        crawler.arun_many.assert_any_await(urls=["https://b.example"], config=run_config)

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_passes_through_thorough_and_content_query(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        good = MagicMock(success=True, markdown="content", url="https://a.example")
        crawler.arun_many = AsyncMock(return_value=[good])

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=15_000,
            total_timeout_seconds=30.0,
            context_name="deep",
            max_content_chars=50,
            content_query="topic",
            thorough=True,
        )

        assert contents == {"https://a.example": "content"}
        assert errors == {}
        mock_build_config.assert_called_once_with(
            page_timeout_ms=15_000, semaphore_count=1, content_query="topic", thorough=True
        )
        mock_managed.assert_called_once_with(mock_browser_config.return_value, context_name="deep")

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_recovery_timeout_is_clamped(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        good = MagicMock(success=True, markdown="content", url="https://a.example")
        crawler.arun_many = AsyncMock(return_value=[good])
        captured_timeouts: list[float] = []
        real_wait_for = asyncio.wait_for

        async def capturing_wait_for(coro: object, **kwargs: object) -> object:
            captured_timeouts.append(float(kwargs["timeout"]))
            return await real_wait_for(coro, **kwargs)

        with patch("asyncio.wait_for", side_effect=capturing_wait_for):
            await _recover_with_single_url_crawls(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                context_name="test",
                max_content_chars=None,
            )
            await _recover_with_single_url_crawls(
                ["https://a.example"],
                page_timeout_ms=3_000,
                total_timeout_seconds=2.0,
                context_name="test",
                max_content_chars=None,
            )
            await _recover_with_single_url_crawls(
                ["https://a.example"],
                page_timeout_ms=3_000,
                total_timeout_seconds=40.0,
                context_name="test",
                max_content_chars=None,
            )

        # min(total, page/1000 + 10), floored at 10
        assert captured_timeouts == [40.0, 10.0, 13.0]

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_per_url_timeout_records_error(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        crawler.arun_many = AsyncMock(side_effect=TimeoutError())

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {}
        assert errors == {
            "https://a.example": "test timed out after 20s (recovery: single URL timeout)"
        }

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_per_url_exception_records_error(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        crawler.arun_many = AsyncMock(side_effect=RuntimeError("boom"))

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {}
        assert errors == {"https://a.example": "test recovery error: boom"}

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_empty_single_result_records_error(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        crawler.arun_many = AsyncMock(return_value=[])

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {}
        assert errors == {"https://a.example": "test returned no result"}

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_failed_result_records_error_message(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        bad = MagicMock(success=False, markdown="", error_message="blocked")
        crawler.arun_many = AsyncMock(return_value=[bad])

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {}
        assert errors == {"https://a.example": "blocked"}

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_max_content_chars_truncates_recovered_content(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        good = MagicMock(success=True, markdown="x" * 100, url="https://a.example")
        crawler.arun_many = AsyncMock(return_value=[good])

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=20,
        )

        assert contents == {"https://a.example": "x" * 20}
        assert errors == {}

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_continues_with_next_url_after_per_url_failures(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        good = MagicMock(success=True, markdown="second content", url="https://b.example")
        scenarios: list[list[object]] = [
            [TimeoutError(), [good]],
            [RuntimeError("boom"), [good]],
            [[], [good]],
        ]
        expected_errors = [
            "test timed out after 20s (recovery: single URL timeout)",
            "test recovery error: boom",
            "test returned no result",
        ]
        for failure, expected_error in zip(scenarios, expected_errors):
            crawler = AsyncMock()
            mock_managed.return_value.__aenter__.return_value = crawler
            crawler.arun_many = AsyncMock(side_effect=failure)

            contents, errors = await _recover_with_single_url_crawls(
                ["https://a.example", "https://b.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=20.0,
                context_name="test",
                max_content_chars=None,
            )

            assert contents == {"https://b.example": "second content"}
            assert errors == {"https://a.example": expected_error}

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_default_error_message_uses_context_name(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        crawler = AsyncMock()
        mock_managed.return_value.__aenter__.return_value = crawler
        bad = MagicMock(success=False, markdown="", error_message=None)
        crawler.arun_many = AsyncMock(return_value=[bad])

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {}
        assert errors == {"https://a.example": "test returned empty content"}

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_outer_failure_returns_fallback_error_for_all_urls(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        mock_semaphore.side_effect = RuntimeError("no semaphore")

        contents, errors = await _recover_with_single_url_crawls(
            ["https://a.example", "https://b.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            context_name="test",
            max_content_chars=None,
        )

        assert contents == {}
        assert errors == {
            "https://a.example": "test timed out after 20s and recovery failed: no semaphore",
            "https://b.example": "test timed out after 20s and recovery failed: no semaphore",
        }

    @patch("app.utils.crawl4ai_utils.managed_crawler")
    @patch("app.utils.crawl4ai_utils.get_browser_semaphore")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    @patch("app.utils.crawl4ai_utils._build_run_config")
    async def test_outer_cancellation_propagates(
        self,
        mock_build_config: MagicMock,
        mock_browser_config: MagicMock,
        mock_semaphore: MagicMock,
        mock_managed: MagicMock,
    ) -> None:
        mock_semaphore.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await _recover_with_single_url_crawls(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=20.0,
                context_name="test",
                max_content_chars=None,
            )


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
        crawler_inst.arun_many = AsyncMock(return_value=[result_httpbin, result_example])
        mock_crawler_cls.return_value = crawler_inst

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
        assert contents == {
            "https://example.com": "example content",
            "https://httpbin.org/redirect-to?url=https://example.com/": "httpbin content",
        }

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_batch_timeout_recovers_per_url(self, mock_crawler_cls: MagicMock) -> None:
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
            side_effect=[TimeoutError(), [success_result], [fail_result]]
        )
        mock_crawler_cls.return_value = crawler_inst

        urls = ["https://good.example", "https://bad.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            page_timeout_ms=30_000,
            total_timeout_seconds=20.0,
            semaphore_count=5,
            context_name="test",
        )

        assert contents == {"https://good.example": "ok"}
        assert errors == {"https://bad.example": "blocked"}

    async def test_empty_urls_returns_empty_dicts(self) -> None:
        contents, errors = await batch_fetch_with_crawl4ai(
            [],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
        )

        assert contents == {}
        assert errors == {}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    @patch("app.utils.crawl4ai_utils.BrowserConfig")
    async def test_run_config_and_browser_config_exact(
        self, mock_browser_config: MagicMock, mock_crawler_cls: MagicMock
    ) -> None:
        result = MagicMock(success=True, markdown="content", url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result])
        mock_crawler_cls.return_value = crawler_inst
        real_wait_for = asyncio.wait_for
        captured_timeouts: list[float] = []

        async def capturing_wait_for(coro: object, **kwargs: object) -> object:
            captured_timeouts.append(float(kwargs["timeout"]))
            return await real_wait_for(coro, **kwargs)

        with patch("asyncio.wait_for", side_effect=capturing_wait_for):
            contents, errors = await batch_fetch_with_crawl4ai(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
                content_query="quantum computing",
                thorough=True,
            )

        assert contents == {"https://a.example": "content"}
        assert errors == {}
        assert captured_timeouts[0] == 60.0
        mock_browser_config.assert_called_once_with(
            headless=True, browser_mode="dedicated", verbose=False
        )
        crawler_inst.arun_many.assert_awaited_once()
        assert crawler_inst.arun_many.await_args.kwargs["urls"] == ["https://a.example"]
        config = crawler_inst.arun_many.await_args.kwargs["config"]
        assert config.page_timeout == 30_000
        assert config.semaphore_count == 3
        assert config.wait_until == "domcontentloaded"
        assert config.word_count_threshold == 10
        assert config.remove_overlay_elements is True
        assert config.verbose is False
        assert config.excluded_tags == [
            "nav",
            "header",
            "footer",
            "aside",
            "form",
            "script",
            "style",
            "noscript",
        ]
        assert config.scan_full_page is True
        assert config.magic is True
        assert config.delay_before_return_html == 1.0
        assert config.markdown_generator.content_filter.user_query == "quantum computing"
        assert config.markdown_generator.content_filter.bm25_threshold == 1.0

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_normalized_matching_when_exact_url_differs(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        result = MagicMock(success=True, markdown="content", url="https://EXAMPLE.com/a/")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result])
        mock_crawler_cls.return_value = crawler_inst

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://example.com/a"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {"https://example.com/a": "content"}
        assert errors == {}
        config = crawler_inst.arun_many.await_args.kwargs["config"]
        assert config.scan_full_page is False
        assert config.magic is False
        assert config.delay_before_return_html == 0.1

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_unmatched_results_fall_back_positionally(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        anonymous1 = MagicMock(success=True, markdown="anon one")
        anonymous2 = MagicMock(success=True, markdown="anon two")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[anonymous1, anonymous2])
        mock_crawler_cls.return_value = crawler_inst

        urls = ["https://a.example", "https://b.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {"https://a.example": "anon one", "https://b.example": "anon two"}
        assert errors == {}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_missing_results_error_out_per_url(self, mock_crawler_cls: MagicMock) -> None:
        good = MagicMock(success=True, markdown="a content", url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[good])
        mock_crawler_cls.return_value = crawler_inst

        urls = ["https://a.example", "https://b.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {"https://a.example": "a content"}
        assert errors == {"https://b.example": "test returned no result"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_duplicate_urls_consume_results_in_order(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        first = MagicMock(success=True, markdown="first", url="https://a.example")
        second = MagicMock(success=True, markdown="second", url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[first, second])
        mock_crawler_cls.return_value = crawler_inst

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example", "https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {"https://a.example": "second"}
        assert errors == {}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_cancelled_batch_propagates(self, mock_crawler_cls: MagicMock) -> None:
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(side_effect=asyncio.CancelledError())
        mock_crawler_cls.return_value = crawler_inst

        with pytest.raises(asyncio.CancelledError):
            await batch_fetch_with_crawl4ai(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_generic_batch_error_returns_error_per_url(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(side_effect=RuntimeError("boom"))
        mock_crawler_cls.return_value = crawler_inst

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            contents, errors = await batch_fetch_with_crawl4ai(
                ["https://a.example", "https://b.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            )

        assert contents == {}
        assert errors == {
            "https://a.example": "test batch error: boom",
            "https://b.example": "test batch error: boom",
        }
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} batch error", context_name="test", error_type="RuntimeError"
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_extra_results_warn_and_are_ignored(self, mock_crawler_cls: MagicMock) -> None:
        result = MagicMock(success=True, markdown="a", url="https://a.example")
        extra = MagicMock(success=True, markdown="extra", url="https://extra.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result, extra])
        mock_crawler_cls.return_value = crawler_inst

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            contents, errors = await batch_fetch_with_crawl4ai(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            )

        assert contents == {"https://a.example": "a"}
        assert errors == {}
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} returned results for URLs; ignoring extras",
            context_name="test",
            results_count=2,
            urls_count=1,
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_unmatched_surplus_results_warn(self, mock_crawler_cls: MagicMock) -> None:
        result_a = MagicMock(success=True, markdown="a", url="https://a.example")
        result_b = MagicMock(success=True, markdown="b", url="https://b.example")
        anonymous = MagicMock(success=True, markdown="anon")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result_a, result_b] + [anonymous] * 5)
        mock_crawler_cls.return_value = crawler_inst

        urls = ["https://a.example", "https://b.example", "https://c.example", "https://d.example"]
        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            contents, errors = await batch_fetch_with_crawl4ai(
                urls,
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            )

        assert contents == {
            "https://a.example": "a",
            "https://b.example": "b",
            "https://c.example": "anon",
            "https://d.example": "anon",
        }
        assert errors == {}
        mock_warning.assert_any_call(
            f"{LogTag.TOOL} returned results for URLs; ignoring extras",
            context_name="test",
            results_count=7,
            urls_count=4,
        )
        mock_warning.assert_any_call(
            f"{LogTag.TOOL} could not map results to requested URLs",
            context_name="test",
            unmatched_count=1,
        )
        assert mock_warning.call_count == 2

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_failed_result_error_in_batch(self, mock_crawler_cls: MagicMock) -> None:
        bad = MagicMock(
            success=False, markdown="", error_message="blocked", url="https://a.example"
        )
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[bad])
        mock_crawler_cls.return_value = crawler_inst

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {}
        assert errors == {"https://a.example": "blocked"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_max_content_chars_truncates_in_batch(self, mock_crawler_cls: MagicMock) -> None:
        good = MagicMock(success=True, markdown="x" * 100, url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[good])
        mock_crawler_cls.return_value = crawler_inst

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
            max_content_chars=20,
        )

        assert contents == {"https://a.example": "x" * 20}
        assert errors == {}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_timeout_recovery_warns_and_passes_query_and_thorough(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        good = MagicMock(success=True, markdown="x" * 100, url="https://b.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(side_effect=[TimeoutError(), TimeoutError(), [good]])
        mock_crawler_cls.return_value = crawler_inst

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            contents, errors = await batch_fetch_with_crawl4ai(
                ["https://a.example", "https://b.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
                max_content_chars=20,
                content_query="topic",
                thorough=True,
            )

        assert contents == {"https://b.example": "x" * 20}
        assert errors == {
            "https://a.example": "test timed out after 60s (recovery: single URL timeout)"
        }
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} batch timed out ; retrying URLs individually",
            context_name="test",
            total_timeout_seconds=60.0,
        )
        recovery_call = crawler_inst.arun_many.await_args_list[1]
        assert recovery_call.kwargs["urls"] == ["https://a.example"]
        recovery_config = recovery_call.kwargs["config"]
        assert recovery_config.semaphore_count == 1
        assert recovery_config.scan_full_page is True
        assert recovery_config.magic is True
        assert recovery_config.delay_before_return_html == 1.0
        assert recovery_config.markdown_generator.content_filter.user_query == "topic"

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_missing_middle_url_still_returns_later_results(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        result_b = MagicMock(success=True, markdown="b content", url="https://b.example")
        result_c = MagicMock(success=True, markdown="c content", url="https://c.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result_b, result_c])
        mock_crawler_cls.return_value = crawler_inst

        urls = ["https://a.example", "https://b.example", "https://c.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {
            "https://b.example": "b content",
            "https://c.example": "c content",
        }
        assert errors == {"https://a.example": "test returned no result"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_default_context_name_used_in_errors(self, mock_crawler_cls: MagicMock) -> None:
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[])
        mock_crawler_cls.return_value = crawler_inst

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
        )

        assert contents == {}
        assert errors == {"https://a.example": "crawl4ai returned no result"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_extraction_default_error_message_in_batch(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        bad = MagicMock(success=False, markdown="", error_message=None, url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[bad])
        mock_crawler_cls.return_value = crawler_inst

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"],
            page_timeout_ms=30_000,
            total_timeout_seconds=60.0,
            semaphore_count=3,
            context_name="test",
        )

        assert contents == {}
        assert errors == {"https://a.example": "test returned empty content"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_close_failure_warns_with_context_name_in_batch(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        result = MagicMock(success=True, markdown="content", url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result])
        crawler_inst.close = AsyncMock(side_effect=RuntimeError("boom"))
        mock_crawler_cls.return_value = crawler_inst

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            contents, errors = await batch_fetch_with_crawl4ai(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            )

        assert contents == {"https://a.example": "content"}
        assert errors == {}
        mock_warning.assert_called_once_with(
            f"{LogTag.TOOL} browser close failed",
            context_name="test",
            error="boom",
            error_type="RuntimeError",
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_no_extras_warning_when_results_match_count(
        self, mock_crawler_cls: MagicMock
    ) -> None:
        result = MagicMock(success=True, markdown="content", url="https://a.example")
        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun_many = AsyncMock(return_value=[result])
        mock_crawler_cls.return_value = crawler_inst

        with patch("app.utils.crawl4ai_utils.log.warning") as mock_warning:
            contents, errors = await batch_fetch_with_crawl4ai(
                ["https://a.example"],
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            )

        assert contents == {"https://a.example": "content"}
        assert errors == {}
        mock_warning.assert_not_called()
