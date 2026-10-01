"""The crawl Obscura: shared by every crawl, replaced once it bloats, never under a crawl.

Launching and stopping are faked at the process primitives, so the engine's
lifecycle across crawls is what these assert.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser_host.obscura_launch import LaunchedEngine
from app.utils import crawl4ai_utils, crawl_obscura

pytestmark = pytest.mark.unit


class _Proc:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None


class _Engines:
    """Launches numbered fake engines and records which were stopped."""

    def __init__(self) -> None:
        self.launched: list[LaunchedEngine] = []
        self.stopped: list[int] = []
        self.rss: dict[int, float] = {}

    async def launch(self) -> LaunchedEngine:
        port = 9000 + len(self.launched)
        engine = LaunchedEngine(proc=cast(Any, _Proc(port)), port=port, ws_url=f"ws://{port}")
        self.launched.append(engine)
        return engine

    async def stop(self, proc: Any) -> None:
        self.stopped.append(proc.pid)


@pytest.fixture
def engines(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Engines]:
    fake = _Engines()
    monkeypatch.setattr(crawl_obscura, "launch_obscura", fake.launch)
    monkeypatch.setattr(crawl_obscura, "stop_process", fake.stop)
    monkeypatch.setattr(crawl_obscura, "process_tree_rss_mb", lambda pid: fake.rss.get(pid, 100.0))
    monkeypatch.setattr(crawl_obscura.settings, "BROWSER_ENGINE_RECYCLE_MB", 1000)
    monkeypatch.setattr(crawl_obscura, "_current", None)
    monkeypatch.setattr(crawl_obscura, "_draining", set())
    return fake


async def test_crawls_share_one_engine_by_its_http_endpoint(engines: _Engines) -> None:
    async with crawl_obscura.crawl_obscura() as first, crawl_obscura.crawl_obscura() as second:
        assert first == second == "http://127.0.0.1:9000"

    assert len(engines.launched) == 1
    assert engines.stopped == []


async def test_an_engine_that_died_is_replaced_for_the_next_crawl(engines: _Engines) -> None:
    async with crawl_obscura.crawl_obscura():
        pass
    cast(Any, engines.launched[0].proc).returncode = -9

    async with crawl_obscura.crawl_obscura() as url:
        assert url == "http://127.0.0.1:9001"


async def test_a_bloated_engine_drains_its_crawls_while_a_fresh_one_takes_new_ones(
    engines: _Engines,
) -> None:
    async with crawl_obscura.crawl_obscura():
        long_crawl = crawl_obscura.crawl_obscura()
        assert await long_crawl.__aenter__() == "http://127.0.0.1:9000"
        engines.rss[9000] = 1500.0

    assert engines.stopped == []
    async with crawl_obscura.crawl_obscura() as fresh:
        assert fresh == "http://127.0.0.1:9001"
    await long_crawl.__aexit__(None, None, None)

    assert engines.stopped == [9000]


@pytest.mark.parametrize(("limit", "rss"), [(1000, 1000.0), (None, 9000.0), (1000, None)])
async def test_an_engine_within_its_limit_or_unmeasured_keeps_serving(
    engines: _Engines, monkeypatch: pytest.MonkeyPatch, limit: int | None, rss: float | None
) -> None:
    monkeypatch.setattr(crawl_obscura.settings, "BROWSER_ENGINE_RECYCLE_MB", limit)
    monkeypatch.setattr(crawl_obscura, "process_tree_rss_mb", lambda pid: rss)

    async with crawl_obscura.crawl_obscura():
        pass
    async with crawl_obscura.crawl_obscura():
        pass

    assert len(engines.launched) == 1
    assert engines.stopped == []


async def test_a_failed_launch_leaves_no_engine_for_the_next_crawl(
    engines: _Engines, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crawl_obscura, "launch_obscura", AsyncMock(side_effect=RuntimeError("x")))
    with pytest.raises(RuntimeError):
        async with crawl_obscura.crawl_obscura():
            pass

    assert crawl_obscura._current is None


async def test_shutdown_stops_the_serving_and_the_draining_engines(engines: _Engines) -> None:
    async with crawl_obscura.crawl_obscura():
        held = crawl_obscura.crawl_obscura()
        await held.__aenter__()
        engines.rss[9000] = 5000.0
    async with crawl_obscura.crawl_obscura():
        pass

    await crawl_obscura.shutdown_crawl_obscura()

    assert sorted(engines.stopped) == [9000, 9001]
    assert crawl_obscura._current is None
    await crawl_obscura.shutdown_crawl_obscura()
    assert sorted(engines.stopped) == [9000, 9001]


async def test_the_engine_is_held_for_the_whole_crawler_not_just_its_start(
    engines: _Engines, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crawler drives the engine until it closes; a replacement must never stop it under one."""
    monkeypatch.setattr(crawl4ai_utils, "_is_obscura", lambda: True)
    crawler = MagicMock(start=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(crawl4ai_utils, "AsyncWebCrawler", MagicMock(return_value=crawler))

    async with crawl4ai_utils.managed_crawler(context_name="t"):
        engines.rss[9000] = 5000.0
        async with crawl_obscura.crawl_obscura():
            pass
        assert engines.stopped == []

    assert engines.stopped == [9000]
