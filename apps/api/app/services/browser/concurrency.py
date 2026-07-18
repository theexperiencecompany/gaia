"""Global cap on concurrent browser sessions.

Each session is a real Chromium instance, so unbounded concurrency thrashes the
Steel container. This fails fast when the cap is reached rather than queueing
(a browser task is long — the user should be told to retry, not wait silently).
The API runs a single uvicorn worker, so an in-process counter is authoritative.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config.settings import settings
from app.services.browser.exceptions import BrowserConcurrencyLimit

_lock = asyncio.Lock()
_active = 0


@asynccontextmanager
async def session_slot() -> AsyncIterator[None]:
    """Reserve one of the ``BROWSER_USE_MAX_CONCURRENT_SESSIONS`` slots."""
    global _active
    async with _lock:
        if _active >= settings.BROWSER_USE_MAX_CONCURRENT_SESSIONS:
            raise BrowserConcurrencyLimit(
                "Too many browser tasks are running right now. Please try again in a bit."
            )
        _active += 1
    try:
        yield
    finally:
        async with _lock:
            _active -= 1
