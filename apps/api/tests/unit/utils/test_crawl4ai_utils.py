"""Unit tests for app.utils.crawl4ai_utils."""

import asyncio
from collections.abc import Awaitable
from contextlib import suppress
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from crawl4ai import BrowserConfig
import pytest

from app.config.settings import settings
from app.constants.browser import BrowserEngine
from app.constants.log_tags import LogTag


def _pin_engine(monkeypatch: pytest.MonkeyPatch, engine: BrowserEngine) -> None:
    monkeypatch.setattr(settings, "BROWSER_ENGINE", engine)


def _record_wait_for_timeouts(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Record every deadline the module hands asyncio.wait_for.

    The per-crawl recovery deadline never reaches an error message or a return
    value, so the timeout argument is the only place it is observable without
    waiting out ten real seconds.
    """
    recorded: list[float | None] = []
    real_wait_for = asyncio.wait_for

    async def spy(awaitable: Awaitable[Any], timeout: float | None = None) -> Any:
        recorded.append(timeout)
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", spy)
    return recorded


def _expire_batch_deadline_once_only_a_straggler_remains(
    monkeypatch: pytest.MonkeyPatch, *, batch_timeout: float
) -> None:
    """Fire the batch deadline once exactly one fetch (the one parked on an Event) is still pending.

    Only the wait_for call matching batch_timeout is intercepted; per-URL and
    teardown waits keep the real one. Ties the outcome to task ordering, not
    machine speed, avoiding a flaky real timeout race.
    """
    real_wait_for = asyncio.wait_for

    async def wait_for(awaitable: Awaitable[Any], timeout: float | None = None) -> Any:
        if timeout != batch_timeout:
            return await real_wait_for(awaitable, timeout)
        # At this point the only other tasks on the loop are the per-URL fetches,
        # just created and not yet run.
        pending = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}
        gathered = asyncio.ensure_future(awaitable)
        while len(pending) > 1:
            _done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        gathered.cancel()
        with suppress(asyncio.CancelledError):
            await gathered
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", wait_for)


def _make_result(markdown: str = "ok", *, success: bool = True, error: str = "") -> MagicMock:
    result = MagicMock()
    result.success = success
    result.markdown = markdown
    result.error_message = error
    return result


def _warning_call(mock_log: MagicMock, needle: str) -> Any:
    """Return the single log.warning call whose message contains needle.

    warning/error both append message and kwargs to the wide event's
    warnings[], so assert the whole call, not just that something logged.
    """
    matches = [call for call in mock_log.warning.call_args_list if needle in str(call.args[0])]
    assert len(matches) == 1, f"expected exactly one {needle!r} warning, got {len(matches)}"
    return matches[0]


def _warning_kwargs(mock_log: MagicMock, needle: str) -> dict[str, Any]:
    """Return the kwargs of the single log.warning call whose message contains needle."""
    return dict(_warning_call(mock_log, needle).kwargs)


def _stub_crawler(mock_crawler_cls: MagicMock) -> AsyncMock:
    crawler_inst = AsyncMock()
    crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
    crawler_inst.__aexit__ = AsyncMock(return_value=False)
    mock_crawler_cls.return_value = crawler_inst
    return crawler_inst


class TestBatchFetchWithCrawl4ai:
    """The Chromium path: one crawler + arun_many with result matching."""

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_matches_redirected_results_to_requested_urls(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
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

        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        urls = [
            "https://example.com",
            "https://httpbin.org/redirect-to?url=https://example.com/",
        ]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                context_name="test",
            ),
        )

        assert errors == {}
        assert contents["https://example.com"] == "example content"
        assert (
            contents["https://httpbin.org/redirect-to?url=https://example.com/"]
            == "httpbin content"
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_batch_timeout_recovers_per_url(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
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

        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        urls = ["https://good.example", "https://bad.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=20.0,
                semaphore_count=5,
                context_name="test",
            ),
        )

        assert contents["https://good.example"] == "ok"
        assert errors["https://bad.example"] == "blocked"


class TestBatchFetchObscura:
    """The Obscura path: one crawler+context per URL (arun), never arun_many."""

    @patch(
        "app.utils.crawl4ai_utils.ensure_crawl_obscura",
        new_callable=AsyncMock,
        return_value="http://127.0.0.1:9223",
    )
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_obscura_fans_out_per_url(
        self,
        mock_crawler_cls: MagicMock,
        mock_ensure: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)

        def make_result(url: str) -> MagicMock:
            r = MagicMock()
            r.success = True
            r.markdown = f"content-{url}"
            r.error_message = ""
            return r

        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun = AsyncMock(side_effect=lambda url, config: make_result(url))
        mock_crawler_cls.return_value = crawler_inst

        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        urls = ["https://a.example", "https://b.example", "https://c.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls,
            CrawlBatchParams(
                page_timeout_ms=20_000,
                total_timeout_seconds=30.0,
                semaphore_count=3,
                context_name="test",
            ),
        )

        assert errors == {}
        assert contents == {u: f"content-{u}" for u in urls}
        # Obscura engine resolved (per-URL fanout), and arun_many was never used.
        mock_ensure.assert_awaited()
        crawler_inst.arun_many.assert_not_called()

    @patch(
        "app.utils.crawl4ai_utils.ensure_crawl_obscura",
        new_callable=AsyncMock,
        return_value="http://127.0.0.1:9223",
    )
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_obscura_one_url_failure_does_not_sink_the_batch(
        self,
        mock_crawler_cls: MagicMock,
        mock_ensure: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)

        async def arun(url: str, config: object) -> MagicMock:
            r = MagicMock()
            if url == "https://bad.example":
                r.success = False
                r.markdown = ""
                r.error_message = "blocked"
            else:
                r.success = True
                r.markdown = "ok"
                r.error_message = ""
            return r

        crawler_inst = AsyncMock()
        crawler_inst.__aenter__ = AsyncMock(return_value=crawler_inst)
        crawler_inst.__aexit__ = AsyncMock(return_value=False)
        crawler_inst.arun = AsyncMock(side_effect=arun)
        mock_crawler_cls.return_value = crawler_inst

        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://good.example", "https://bad.example"],
            CrawlBatchParams(
                page_timeout_ms=20_000,
                total_timeout_seconds=30.0,
                semaphore_count=3,
                context_name="test",
            ),
        )

        assert contents["https://good.example"] == "ok"
        assert errors["https://bad.example"] == "blocked"
        assert "https://good.example" not in errors


class TestBuildBrowserConfig:
    """The engine decides the whole browser config, field by field."""

    @patch(
        "app.utils.crawl4ai_utils.ensure_crawl_obscura",
        new_callable=AsyncMock,
        return_value="http://127.0.0.1:9223",
    )
    async def test_obscura_connects_over_cdp_without_closing_the_shared_engine(
        self, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        from app.utils.crawl4ai_utils import _build_browser_config

        config = await _build_browser_config()

        assert config.browser_mode == "cdp"
        assert config.cdp_url == "http://127.0.0.1:9223"
        assert config.headless is True
        assert config.verbose is False
        # A crawler's teardown must never close the shared crawl engine out
        # from under a concurrent crawl.
        assert config.cdp_cleanup_on_close is False

    async def test_chromium_launches_its_own_dedicated_browser(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        from app.utils.crawl4ai_utils import _build_browser_config

        config = await _build_browser_config()

        assert config.browser_mode == "dedicated"
        assert config.headless is True
        assert config.verbose is False
        assert config.cdp_url is None


class TestBuildRunConfig:
    """A content query is what switches the markdown generator to BM25 ranking."""

    def test_content_query_is_threaded_into_the_bm25_filter(self) -> None:
        from app.utils.crawl4ai_utils import CrawlBatchParams, _build_run_config

        config = _build_run_config(
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=3,
                content_query="quantum error correction",
            )
        )

        assert config.markdown_generator.content_filter.user_query == "quantum error correction"

    def test_no_content_query_keeps_the_full_raw_markdown(self) -> None:
        from app.utils.crawl4ai_utils import CrawlBatchParams, _build_run_config

        config = _build_run_config(
            CrawlBatchParams(page_timeout_ms=30_000, total_timeout_seconds=60.0, semaphore_count=3)
        )

        assert config.markdown_generator.content_filter is None


class TestManagedCrawler:
    """The crawler always runs on the active engine's config; nobody pre-builds one."""

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_the_crawler_is_built_on_the_engine_default(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        _stub_crawler(mock_crawler_cls)
        from app.utils.crawl4ai_utils import managed_crawler

        async with managed_crawler(context_name="test"):
            pass

        config = mock_crawler_cls.call_args.kwargs["config"]
        assert isinstance(config, BrowserConfig)
        assert config.browser_mode == "dedicated"


class TestRecoveryAfterBatchTimeout:
    """The per-URL recovery pass: its own deadline, its own single-URL config."""

    @staticmethod
    def _timed_out_batch(mock_crawler_cls: MagicMock) -> AsyncMock:
        crawler_inst = _stub_crawler(mock_crawler_cls)
        # Batch times out, then every recovery crawl comes back empty-handed.
        crawler_inst.arun_many = AsyncMock(side_effect=[TimeoutError(), []])
        return crawler_inst

    @pytest.mark.parametrize(
        ("page_timeout_ms", "total_timeout_seconds", "expected_recovery_timeout"),
        [
            # Floor: a total budget under 10s still gives each recovery crawl 10s.
            (1_000, 5.0, 10.0),
            # Page-derived: page timeout + the processing margin, under the total.
            (600_000, 1_000.0, 645.0),
        ],
    )
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_recovery_crawls_get_a_page_derived_deadline(
        self,
        mock_crawler_cls: MagicMock,
        page_timeout_ms: int,
        total_timeout_seconds: float,
        expected_recovery_timeout: float,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        self._timed_out_batch(mock_crawler_cls)
        recorded = _record_wait_for_timeouts(monkeypatch)
        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://good.example"],
            CrawlBatchParams(
                page_timeout_ms=page_timeout_ms,
                total_timeout_seconds=total_timeout_seconds,
                semaphore_count=5,
                context_name="test",
            ),
        )

        assert expected_recovery_timeout in recorded

    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_a_failed_recovery_teardown_names_the_calling_context(
        self, mock_crawler_cls: MagicMock, mock_log: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = self._timed_out_batch(mock_crawler_cls)
        crawler_inst.close = AsyncMock(side_effect=RuntimeError("driver gone"))
        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://good.example"],
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=5,
                context_name="deep_research",
            ),
        )

        # The batch crawler and then the recovery crawler both fail to close;
        # each warning names the caller, never a default.
        closes = [
            dict(call.kwargs)
            for call in mock_log.warning.call_args_list
            if "browser close failed" in str(call.args[0])
        ]
        assert (
            closes
            == [
                {
                    "context_name": "deep_research",
                    "error": "driver gone",
                    "error_type": "RuntimeError",
                }
            ]
            * 2
        )

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_recovery_errors_name_the_calling_context(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        self._timed_out_batch(mock_crawler_cls)
        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://good.example"],
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=5,
                context_name="deep_research",
            ),
        )

        assert contents == {}
        assert errors == {"https://good.example": "deep_research returned no result"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_recovery_crawls_one_url_at_a_time(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = self._timed_out_batch(mock_crawler_cls)
        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://good.example"],
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=5,
                context_name="test",
            ),
        )

        recovery_call = crawler_inst.arun_many.await_args_list[-1]
        assert recovery_call.kwargs["urls"] == ["https://good.example"]
        assert recovery_call.kwargs["config"].semaphore_count == 1


class TestPerUrlTimeout:
    """The Obscura path's per-URL deadline, as reported to the caller."""

    @pytest.mark.parametrize(
        ("page_timeout_ms", "total_timeout_seconds", "expected_message"),
        [
            # Floor: a total budget under 10s still gives each URL 10s.
            (1_000, 5.0, "test timed out after 10s"),
            # Page-derived: page timeout + the processing margin, under the total.
            (600_000, 1_000.0, "test timed out after 645s"),
            # Capped by the total budget when the page timeout exceeds it.
            (600_000, 100.0, "test timed out after 100s"),
        ],
    )
    @patch(
        "app.utils.crawl4ai_utils.ensure_crawl_obscura",
        new_callable=AsyncMock,
        return_value="http://127.0.0.1:9223",
    )
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_per_url_timeout_is_reported_in_the_error(
        self,
        mock_crawler_cls: MagicMock,
        mock_ensure: AsyncMock,
        page_timeout_ms: int,
        total_timeout_seconds: float,
        expected_message: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(side_effect=TimeoutError())
        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://slow.example"],
            CrawlBatchParams(
                page_timeout_ms=page_timeout_ms,
                total_timeout_seconds=total_timeout_seconds,
                semaphore_count=3,
                context_name="test",
            ),
        )

        assert contents == {}
        assert errors == {"https://slow.example": expected_message}


_patch_obscura_engine = patch(
    "app.utils.crawl4ai_utils.ensure_crawl_obscura",
    new_callable=AsyncMock,
    return_value="http://127.0.0.1:9223",
)


def _obscura_params(**overrides: Any) -> Any:
    from app.utils.crawl4ai_utils import CrawlBatchParams

    defaults: dict[str, Any] = {
        "page_timeout_ms": 20_000,
        "total_timeout_seconds": 30.0,
        "semaphore_count": 3,
        "context_name": "test",
    }
    return CrawlBatchParams(**{**defaults, **overrides})


class TestObscuraPerUrlFanout:
    """What each per-URL crawl is handed, and what comes back when one goes wrong."""

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_every_url_is_crawled_on_the_batch_run_config(
        self, mock_crawler_cls: MagicMock, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(return_value=_make_result())
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://a.example", "https://b.example"],
            _obscura_params(page_timeout_ms=17_000, content_query="quantum"),
        )

        crawled = {call.kwargs["url"] for call in crawler_inst.arun.await_args_list}
        assert crawled == {"https://a.example", "https://b.example"}
        for call in crawler_inst.arun.await_args_list:
            config = call.kwargs["config"]
            assert config.page_timeout == 17_000
            assert config.markdown_generator.content_filter.user_query == "quantum"

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_a_crawl_error_is_reported_against_its_own_url(
        self,
        mock_crawler_cls: MagicMock,
        mock_log: MagicMock,
        mock_ensure: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(side_effect=ValueError("boom"))
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"], _obscura_params(context_name="deep_research")
        )

        assert contents == {}
        assert errors == {"https://a.example": "deep_research error: boom"}
        assert _warning_kwargs(mock_log, "per-URL fetch failed") == {
            "context_name": "deep_research",
            "error_type": "ValueError",
        }

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_content_is_truncated_to_the_callers_limit(
        self, mock_crawler_cls: MagicMock, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(return_value=_make_result("abcdefghij"))
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        contents, _errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"], _obscura_params(max_content_chars=4)
        )

        assert contents == {"https://a.example": "abcd"}

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_an_empty_page_is_reported_against_the_calling_context(
        self, mock_crawler_cls: MagicMock, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(return_value=_make_result("   ", success=True))
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        _contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"], _obscura_params(context_name="deep_research")
        )

        assert errors == {"https://a.example": "deep_research returned empty content"}

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_semaphore_count_bounds_the_crawls_in_flight(
        self, mock_crawler_cls: MagicMock, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        in_flight = 0
        peak = 0

        async def arun(url: str, config: object) -> MagicMock:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return _make_result()

        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(side_effect=arun)
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://a.example", "https://b.example", "https://c.example"],
            _obscura_params(semaphore_count=1),
        )

        assert peak == 1

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_each_crawl_gets_its_own_page_derived_deadline(
        self, mock_crawler_cls: MagicMock, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(return_value=_make_result())
        recorded = _record_wait_for_timeouts(monkeypatch)
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://a.example"],
            _obscura_params(page_timeout_ms=20_000, total_timeout_seconds=1_000.0),
        )

        # The per-URL crawl is bounded by page timeout + processing margin; the
        # whole batch by the caller's total budget.
        assert 65.0 in recorded
        assert 1_000.0 in recorded

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_the_batch_deadline_marks_unfinished_urls_and_keeps_finished_ones(
        self, mock_crawler_cls: MagicMock, mock_ensure: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        never = asyncio.Event()

        async def arun(url: str, config: object) -> MagicMock:
            if url == "https://slow.example":
                await never.wait()
            return _make_result("fast content")

        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(side_effect=arun)
        _expire_batch_deadline_once_only_a_straggler_remains(monkeypatch, batch_timeout=0.05)
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        contents, errors = await batch_fetch_with_crawl4ai(
            ["https://fast.example", "https://slow.example"],
            _obscura_params(total_timeout_seconds=0.05),
        )

        # Never all-or-nothing: what finished is kept, only the stragglers fail.
        assert contents == {"https://fast.example": "fast content"}
        assert errors == {"https://slow.example": "test batch timed out after 0s"}

    @_patch_obscura_engine
    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_a_failed_teardown_names_the_calling_context(
        self,
        mock_crawler_cls: MagicMock,
        mock_log: MagicMock,
        mock_ensure: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.OBSCURA)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun = AsyncMock(return_value=_make_result())
        crawler_inst.close = AsyncMock(side_effect=RuntimeError("driver gone"))
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://a.example"], _obscura_params(context_name="deep_research")
        )

        assert _warning_kwargs(mock_log, "browser close failed") == {
            "context_name": "deep_research",
            "error": "driver gone",
            "error_type": "RuntimeError",
        }


class TestChromiumBatchWiring:
    """What arun_many is handed, and how its failures reach the caller."""

    @staticmethod
    def _params(**overrides: Any) -> Any:
        from app.utils.crawl4ai_utils import CrawlBatchParams

        defaults: dict[str, Any] = {
            "page_timeout_ms": 30_000,
            "total_timeout_seconds": 60.0,
            "semaphore_count": 5,
            "context_name": "test",
        }
        return CrawlBatchParams(**{**defaults, **overrides})

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_arun_many_receives_every_url_on_the_batch_run_config(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun_many = AsyncMock(return_value=[])
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        urls = ["https://a.example", "https://b.example"]
        await batch_fetch_with_crawl4ai(urls, self._params(page_timeout_ms=11_000))

        call = crawler_inst.arun_many.await_args
        assert call.kwargs["urls"] == urls
        assert call.kwargs["config"].page_timeout == 11_000
        assert call.kwargs["config"].semaphore_count == 5

    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_a_batch_error_is_reported_for_every_url(
        self, mock_crawler_cls: MagicMock, mock_log: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun_many = AsyncMock(side_effect=ValueError("boom"))
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        urls = ["https://a.example", "https://b.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls, self._params(context_name="deep_research")
        )

        assert contents == {}
        assert errors == dict.fromkeys(urls, "deep_research batch error: boom")
        call = _warning_call(mock_log, "batch error")
        assert call.args == (f"{LogTag.TOOL} batch error",)
        assert call.kwargs == {"context_name": "deep_research", "error_type": "ValueError"}

    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_urls_the_batch_returned_nothing_for_are_reported(
        self, mock_crawler_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun_many = AsyncMock(return_value=[])
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        _contents, errors = await batch_fetch_with_crawl4ai(
            ["https://a.example"], self._params(context_name="deep_research")
        )

        assert errors == {"https://a.example": "deep_research returned no result"}

    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_the_batch_deadline_falls_back_to_per_url_recovery(
        self, mock_crawler_cls: MagicMock, mock_log: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        never = asyncio.Event()

        async def arun_many(urls: list[str], config: object) -> list[MagicMock]:
            if len(urls) > 1:
                await never.wait()
            return [_make_result("recovered")]

        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun_many = AsyncMock(side_effect=arun_many)
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        urls = ["https://a.example", "https://b.example"]
        contents, errors = await batch_fetch_with_crawl4ai(
            urls, self._params(total_timeout_seconds=0.05)
        )

        assert errors == {}
        assert contents == dict.fromkeys(urls, "recovered")
        call = _warning_call(mock_log, "batch timed out")
        assert call.args == (f"{LogTag.TOOL} batch timed out ; retrying URLs individually",)
        assert call.kwargs == {"context_name": "test", "total_timeout_seconds": 0.05}

    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_a_failed_teardown_names_the_calling_context(
        self, mock_crawler_cls: MagicMock, mock_log: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun_many = AsyncMock(return_value=[_make_result()])
        crawler_inst.close = AsyncMock(side_effect=RuntimeError("driver gone"))
        from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://a.example"], self._params(context_name="deep_research")
        )

        assert _warning_kwargs(mock_log, "browser close failed") == {
            "context_name": "deep_research",
            "error": "driver gone",
            "error_type": "RuntimeError",
        }


class TestResultToUrlMapping:
    """Only results that could not be placed at all count as unmapped."""

    @staticmethod
    def _unmatchable() -> MagicMock:
        result = _make_result()
        result.url = None
        result.redirected_url = None
        return result

    def test_a_surplus_result_is_not_counted_as_unmapped(self) -> None:
        from app.utils.crawl4ai_utils import _map_results_to_urls

        matched = _make_result()
        matched.url = "https://a.example"
        matched.redirected_url = None

        matched_results, unmatched_count = _map_results_to_urls(
            ["https://a.example"], [matched, self._unmatchable()]
        )

        # Every requested URL got its result; the extra one has nowhere to go
        # but is not evidence that mapping failed.
        assert matched_results == {0: matched}
        assert unmatched_count == 0

    def test_results_left_over_after_the_fallback_are_counted(self) -> None:
        from app.utils.crawl4ai_utils import _map_results_to_urls

        urls = ["https://a.example", "https://b.example", "https://c.example"]
        results = [self._unmatchable() for _ in range(4)]

        matched_results, unmatched_count = _map_results_to_urls(urls, results)

        # The positional fallback places one result per requested URL; the
        # fourth has no home and is reported.
        assert sorted(matched_results) == [0, 1, 2]
        assert unmatched_count == 1

    @patch("app.utils.crawl4ai_utils.log")
    @patch("app.utils.crawl4ai_utils.AsyncWebCrawler")
    async def test_unmapped_results_are_reported_with_their_count(
        self, mock_crawler_cls: MagicMock, mock_log: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_engine(monkeypatch, BrowserEngine.CHROMIUM)
        crawler_inst = _stub_crawler(mock_crawler_cls)
        crawler_inst.arun_many = AsyncMock(return_value=[self._unmatchable() for _ in range(4)])
        from app.utils.crawl4ai_utils import CrawlBatchParams, batch_fetch_with_crawl4ai

        await batch_fetch_with_crawl4ai(
            ["https://a.example", "https://b.example", "https://c.example"],
            CrawlBatchParams(
                page_timeout_ms=30_000,
                total_timeout_seconds=60.0,
                semaphore_count=5,
                context_name="test",
            ),
        )

        assert _warning_kwargs(mock_log, "could not map results") == {
            "context_name": "test",
            "unmatched_count": 1,
        }
