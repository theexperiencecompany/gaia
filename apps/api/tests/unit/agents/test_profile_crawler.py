"""Behavior tests for app.agents.memory.profile_crawler.

Locks: a successful crawl returns markdown content under the concurrency
semaphore, and every failure shape — crawler returning None, missing/empty
markdown, provider exceptions — comes back as a ``ProfileCrawlResult`` with
``content=None`` and a named error, never a raise.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.memory.profile_crawler import crawl_profile_url

MODULE = "app.agents.memory.profile_crawler"

URL = "https://github.com/gaia"
PLATFORM = "github"


def _patch_crawl(fake_crawler: object) -> MagicMock:
    """Patch the two async context-manager seams used by a profile crawl."""
    crawler_cm = MagicMock()
    crawler_cm.__aenter__ = AsyncMock(return_value=fake_crawler)
    crawler_cm.__aexit__ = AsyncMock(return_value=False)

    browser_cm = MagicMock()
    browser_cm.__aenter__ = AsyncMock(return_value=None)
    browser_cm.__aexit__ = AsyncMock(return_value=False)

    return patch.multiple(
        MODULE,
        managed_crawler=MagicMock(return_value=crawler_cm),
        get_browser_semaphore=MagicMock(return_value=browser_cm),
    )


class TestCrawlProfileUrl:
    async def test_success_returns_markdown_content(self) -> None:
        crawler = MagicMock()
        crawler.arun = AsyncMock(return_value=MagicMock(markdown="## Profile\nbio here"))
        semaphore = AsyncMock()

        with _patch_crawl(crawler):
            result = await crawl_profile_url(URL, PLATFORM, semaphore)

        assert result["url"] == URL
        assert result["platform"] == PLATFORM
        assert result["content"] == "## Profile\nbio here"
        assert result["error"] is None
        crawler.arun.assert_awaited_once_with(url=URL)

    async def test_none_result_is_reported_as_an_error(self) -> None:
        crawler = MagicMock()
        crawler.arun = AsyncMock(return_value=None)
        semaphore = AsyncMock()

        with _patch_crawl(crawler):
            result = await crawl_profile_url(URL, PLATFORM, semaphore)

        assert result["content"] is None
        assert "Crawler returned None" in result["error"]

    async def test_missing_markdown_attribute_is_an_error(self) -> None:
        crawler = MagicMock()
        crawler.arun = AsyncMock(return_value=MagicMock(markdown=object()))
        del crawler.arun.return_value.markdown
        semaphore = AsyncMock()

        with _patch_crawl(crawler):
            result = await crawl_profile_url(URL, PLATFORM, semaphore)

        assert result["content"] is None
        assert "missing markdown attribute" in result["error"]

    async def test_empty_markdown_is_an_error(self) -> None:
        crawler = MagicMock()
        crawler.arun = AsyncMock(return_value=MagicMock(markdown=""))
        semaphore = AsyncMock()

        with _patch_crawl(crawler):
            result = await crawl_profile_url(URL, PLATFORM, semaphore)

        assert result["content"] is None
        assert "No markdown content" in result["error"]

    async def test_crawl_exception_is_captured_not_raised(self) -> None:
        crawler = MagicMock()
        crawler.arun = AsyncMock(side_effect=TimeoutError("timed out"))
        semaphore = AsyncMock()

        with _patch_crawl(crawler):
            result = await crawl_profile_url(URL, PLATFORM, semaphore)

        assert result["content"] is None
        assert result["error"] == "TimeoutError: timed out"

    async def test_exception_without_a_message_names_the_type(self) -> None:
        crawler = MagicMock()
        crawler.arun = AsyncMock(side_effect=RuntimeError(""))
        semaphore = AsyncMock()

        with _patch_crawl(crawler):
            result = await crawl_profile_url(URL, PLATFORM, semaphore)

        assert result["content"] is None
        assert result["error"].startswith("RuntimeError:")
