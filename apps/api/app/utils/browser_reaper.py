"""Reap leaked headless-browser subprocesses.

crawl4ai launches one Playwright driver process (``playwright/driver/node``)
per ``AsyncWebCrawler``; the driver owns the Chromium tree. Teardown is
shielded against cancellation in ``crawl4ai_utils.managed_crawler``, but any
path that still orphans a driver (library bugs, crashes mid-launch) leaks
~50-130 MB per process with no in-heap trace — observed in prod as 31 browser
processes (2.5 GB) accumulating for days until the node swapped.

This reaper is the process-level guarantee: every interval it terminates
direct child driver processes older than the longest legitimate crawl. It is
scoped to *children of the current process* so the API and worker each reap
only their own spawn, and age-gated far above any real crawl duration so an
in-flight browser can never be killed.
"""

import asyncio
import contextlib
import time

import psutil

from app.constants.search import (
    BROWSER_REAPER_INTERVAL_SECONDS,
    BROWSER_REAPER_MAX_AGE_SECONDS,
)
from shared.py.wide_events import log

# patchright is the stealth fork of playwright pulled in by crawl4ai; both
# drivers present the same leak surface.
_DRIVER_CMDLINE_MARKERS = ("playwright/driver/node", "patchright/driver/node")

_KILL_ESCALATION_TIMEOUT_SECONDS = 5.0

_reaper_task: asyncio.Task[None] | None = None


def _is_leaked_driver(proc: psutil.Process, now: float) -> bool:
    """True when proc is a browser driver older than the reaper age gate."""
    try:
        if now - proc.create_time() < BROWSER_REAPER_MAX_AGE_SECONDS:
            return False
        cmdline = " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    return any(marker in cmdline for marker in _DRIVER_CMDLINE_MARKERS)


def reap_leaked_browsers() -> int:
    """Terminate leaked driver children; return how many were reaped.

    Blocking (uses ``psutil.wait_procs``) — call via ``asyncio.to_thread``.
    """
    now = time.time()
    leaked = [child for child in psutil.Process().children() if _is_leaked_driver(child, now)]
    if not leaked:
        return 0

    for child in leaked:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            child.terminate()

    _, alive = psutil.wait_procs(leaked, timeout=_KILL_ESCALATION_TIMEOUT_SECONDS)
    for child in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            child.kill()
    return len(leaked)


async def _reaper_loop() -> None:
    while True:
        await asyncio.sleep(BROWSER_REAPER_INTERVAL_SECONDS)
        try:
            reaped = await asyncio.to_thread(reap_leaked_browsers)
            if reaped:
                log.warning(f"Reaped {reaped} leaked browser driver process(es)")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Browser reaper sweep failed: {e}")


def start_browser_reaper() -> None:
    """Start the periodic reaper task (idempotent)."""
    global _reaper_task
    if _reaper_task is not None and not _reaper_task.done():
        return
    _reaper_task = asyncio.get_running_loop().create_task(_reaper_loop())
    log.info(
        f"Browser reaper started (interval={BROWSER_REAPER_INTERVAL_SECONDS:.0f}s, "
        f"max_age={BROWSER_REAPER_MAX_AGE_SECONDS:.0f}s)"
    )


async def stop_browser_reaper() -> None:
    """Cancel and await the reaper task."""
    global _reaper_task
    if _reaper_task is None:
        return
    _reaper_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _reaper_task
    _reaper_task = None
