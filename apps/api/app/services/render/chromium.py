"""The one headless Chromium launch every server-side render shares.

Each use owns a fresh browser that is always closed on exit; app.utils.browser_reaper is only
the process-level backstop.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, async_playwright

# Unhinted glyphs keep fractional advances on Linux, so text spaces as it does on macOS.
CHROMIUM_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"]


@asynccontextmanager
async def chromium_browser() -> AsyncIterator[Browser]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=CHROMIUM_LAUNCH_ARGS)
        try:
            yield browser
        finally:
            await browser.close()
