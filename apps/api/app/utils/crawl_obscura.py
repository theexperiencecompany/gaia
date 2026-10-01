"""Own a dedicated, process-local Obscura that the crawl4ai engine drives over CDP.

crawl4ai cannot launch Obscura itself, only Chromium via Playwright, so it
connects to a running one via cdp_url. This owns that Obscura: started on first
crawl and shared after, relaunched if it died, torn down on app shutdown, and
replaced once it outgrows BROWSER_ENGINE_RECYCLE_MB: a fresh one takes new
crawls while the old one finishes its own and is stopped. Deliberately separate
from the interactive browser host's Obscura, so a crawl can never take down an
agent's live session, or the reverse.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.browser_host.obscura_launch import (
    LaunchedEngine,
    launch_obscura,
    process_tree_rss_mb,
    stop_process,
)
from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


@dataclass(eq=False, slots=True)
class _CrawlEngine:
    """One crawl Obscura and the crawls currently driving it."""

    launched: LaunchedEngine
    crawls: int = 0


_current: _CrawlEngine | None = None
_draining: set[_CrawlEngine] = set()
_lock = asyncio.Lock()


@asynccontextmanager
async def crawl_obscura() -> AsyncIterator[str]:
    """Yield the CDP http endpoint of the crawl Obscura, held for the crawl's whole life."""
    engine = await _acquire()
    try:
        yield engine.launched.http_url
    finally:
        await _release(engine)


async def _acquire() -> _CrawlEngine:
    global _current
    async with _lock:
        if _current is None or _current.launched.proc.returncode is not None:
            _current = _CrawlEngine(launched=await launch_obscura())
            log.info(f"{LogTag.TOOL} crawl4ai Obscura engine started", port=_current.launched.port)
        _current.crawls += 1
        return _current


async def _release(engine: _CrawlEngine) -> None:
    global _current
    async with _lock:
        engine.crawls -= 1
        limit = settings.BROWSER_ENGINE_RECYCLE_MB
        if engine is _current and limit is not None:
            rss = process_tree_rss_mb(engine.launched.proc.pid)
            if rss is not None and rss > limit:
                log.warning(
                    f"{LogTag.TOOL} crawl4ai Obscura engine replaced over its memory limit",
                    rss_mb=round(rss),
                    limit_mb=limit,
                )
                _current = None
                _draining.add(engine)
        if engine in _draining and engine.crawls == 0:
            _draining.discard(engine)
            await stop_process(engine.launched.proc)


async def shutdown_crawl_obscura() -> None:
    """Stop every crawl Obscura on app shutdown (a no-op when none ever started)."""
    global _current
    async with _lock:
        engines = [*_draining, *([_current] if _current is not None else [])]
        _current = None
        _draining.clear()
        for engine in engines:
            await stop_process(engine.launched.proc)
