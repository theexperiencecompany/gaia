"""Own a dedicated, process-local Obscura that the crawl4ai engine drives over CDP.

crawl4ai cannot launch Obscura itself, only Chromium via Playwright, so it
connects to a running one via cdp_url. This owns that Obscura: one process
started on first crawl and reused after, relaunched if it died, torn down on
app shutdown. Deliberately separate from the interactive browser host's
Obscura so a crawl can never take down an agent's live session, or vice versa.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import subprocess

from app.browser_host.obscura_launch import obscura_serve_argv, poll_obscura_endpoint
from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# How many consecutive ports to try from OBSCURA_CRAWL_PORT before giving up: the
# base may be taken (a stray process, a dev's Chrome), and Obscura only serves at
# a port we name, so we probe upward rather than fail on the first collision.
_PORT_ATTEMPTS = 5
# A bind failure makes Obscura exit within a few ms; give it this long to have
# died before we decide the port took and start the (30s) readiness poll.
_BIND_SETTLE_SECONDS = 0.5


@dataclass(frozen=True)
class _CrawlEngine:
    """The running crawl Obscura and the CDP endpoint it publishes — one value, so the process and its URL can never disagree about whether an engine exists."""

    proc: asyncio.subprocess.Process
    cdp_url: str


_engine: _CrawlEngine | None = None
_lock = asyncio.Lock()


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=2)


async def ensure_crawl_obscura() -> str:
    """Return the CDP http endpoint of the crawl Obscura, launching (or relaunching) it if needed.

    Probes upward from OBSCURA_CRAWL_PORT so a taken base port (e.g. a dev's
    local Chrome) doesn't wedge crawling.
    """
    global _engine
    async with _lock:
        if _engine is not None and _engine.proc.returncode is None:
            return _engine.cdp_url
        base = settings.OBSCURA_CRAWL_PORT
        last_error: Exception | None = None
        for port in range(base, base + _PORT_ATTEMPTS):
            proc = await asyncio.create_subprocess_exec(
                *obscura_serve_argv(port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            await asyncio.sleep(_BIND_SETTLE_SECONDS)
            if proc.returncode is not None:  # exited immediately — port taken, try the next
                continue
            try:
                await poll_obscura_endpoint(port)
            except Exception as exc:
                last_error = exc
                await _terminate(proc)
                continue
            _engine = _CrawlEngine(proc=proc, cdp_url=f"http://127.0.0.1:{port}")
            log.info(f"{LogTag.TOOL} crawl4ai Obscura engine started", port=port)
            return _engine.cdp_url
        raise RuntimeError(
            f"crawl Obscura could not bind a port in {base}..{base + _PORT_ATTEMPTS - 1}"
        ) from last_error


async def shutdown_crawl_obscura() -> None:
    """Terminate the crawl Obscura on app shutdown (no-op if it never started)."""
    global _engine
    async with _lock:
        engine, _engine = _engine, None
        if engine is None or engine.proc.returncode is not None:
            return
        engine.proc.terminate()
        try:
            await asyncio.wait_for(engine.proc.wait(), timeout=5)
        except TimeoutError:
            engine.proc.kill()
