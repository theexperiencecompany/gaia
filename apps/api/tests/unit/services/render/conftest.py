"""Playwright faked at the boundary app.services.render.chromium launches through.

Every render test gets a fresh process browser and render line, so no launch or
waiting render carries over between tests (each runs on its own event loop).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.render import chromium as chromium_module


class FakeContext:
    def __init__(self, browser: FakeBrowser, options: dict[str, Any]) -> None:
        self.browser = browser
        self.options = options
        self.closed = False

    async def new_page(self) -> Any:
        return self.browser.chromium.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.connected = True
        self.closed = False
        self.contexts: list[FakeContext] = []
        #: Raised by new_context: a browser whose driver died still reports itself connected.
        self.context_error: Exception | None = chromium.context_error

    def is_connected(self) -> bool:
        return self.connected

    async def new_context(self, **options: Any) -> FakeContext:
        if self.context_error is not None:
            raise self.context_error
        context = FakeContext(self, options)
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True
        self.connected = False


class FakePlaywright:
    """One started driver; it is its own browser type, so playwright.chromium.launch() works.

    Stopping it closes every browser it launched, as the real driver does when it exits.
    """

    def __init__(self, fake: FakeChromium) -> None:
        self.fake = fake
        self.chromium = self
        self.stopped = False
        self.browsers: list[FakeBrowser] = []

    async def launch(self, **options: Any) -> FakeBrowser:
        self.fake.launches.append(options)
        if self.fake.launch_error is not None:
            raise self.fake.launch_error
        browser = FakeBrowser(self.fake)
        self.fake.browsers.append(browser)
        self.browsers.append(browser)
        return browser

    async def stop(self) -> None:
        self.stopped = True
        for browser in self.browsers:
            await browser.close()


class FakeChromium:
    """Every browser launched, the playwright each came from, and the page every context opens."""

    def __init__(self) -> None:
        self.page: Any = MagicMock()
        self.browsers: list[FakeBrowser] = []
        self.playwrights: list[FakePlaywright] = []
        self.launches: list[dict[str, Any]] = []
        self.launch_error: Exception | None = None
        #: What each browser launched from now on raises when asked for a context.
        self.context_error: Exception | None = None

    async def start(self) -> FakePlaywright:
        playwright = FakePlaywright(self)
        self.playwrights.append(playwright)
        return playwright


@pytest.fixture
def chromium(monkeypatch: pytest.MonkeyPatch) -> FakeChromium:
    fake = FakeChromium()
    monkeypatch.setattr(chromium_module, "async_playwright", lambda: fake)
    monkeypatch.setattr(chromium_module, "_chromium", chromium_module._ProcessChromium())
    monkeypatch.setattr(chromium_module, "_slots", chromium_module._RenderSlots())
    return fake
