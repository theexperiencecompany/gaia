"""The one headless Chromium a process renders with, and the page each render opens in it.

The browser launches on first use, is replaced once it dies or reaches CHROMIUM_RECYCLE_AGE_SECONDS,
closes after CHROMIUM_IDLE_CLOSE_SECONDS with no render, and is closed by close_chromium on API
and worker shutdown. A browser that cannot open a context is dead, even while it reports itself
connected (its driver was killed), so it is replaced and the render asks the new one once. Every render gets its own browser context, so nothing a page stores outlives
it, and at most CHROMIUM_MAX_CONCURRENT_RENDERS run at once.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import time

# A dead driver raises TargetClosedError, which playwright.async_api does not export.
from playwright._impl._errors import TargetClosedError
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    ViewportSize,
    async_playwright,
)

from app.constants.log_tags import LogTag
from app.constants.render import (
    CHROMIUM_DEAD_DRIVER_MESSAGE,
    CHROMIUM_IDLE_CLOSE_SECONDS,
    CHROMIUM_LAUNCH_ARGS,
    CHROMIUM_MAX_CONCURRENT_RENDERS,
    CHROMIUM_RECYCLE_AGE_SECONDS,
)
from shared.py.wide_events import log


@dataclass(eq=False)
class _Launch:
    """One launched browser and how many renders still use it."""

    playwright: Playwright
    browser: Browser
    launched_at: float = field(default_factory=time.monotonic)
    renders: int = 0

    def usable(self) -> bool:
        age = time.monotonic() - self.launched_at
        return self.browser.is_connected() and age < CHROMIUM_RECYCLE_AGE_SECONDS

    async def close(self) -> None:
        # Stopping the driver closes its browser; Browser.close raises once the driver is dead.
        await self.playwright.stop()


class _ProcessChromium:
    """The process's current browser; a replaced one closes when its last render ends."""

    def __init__(self) -> None:
        self._launching = asyncio.Lock()
        self._current: _Launch | None = None
        self._idle_timer: asyncio.TimerHandle | None = None
        # Holds each idle close so the loop cannot drop it mid-run; nothing reads it.
        self._idle_closes: set[asyncio.Task[None]] = set()  # pragma: no mutate — GC guard only

    async def acquire(self) -> _Launch:
        self._cancel_idle_timer()
        async with self._launching:
            current = self._current
            if current is None or not current.usable():
                self._current = None
                if current is not None and current.renders == 0:
                    await current.close()
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(headless=True, args=CHROMIUM_LAUNCH_ARGS)
                current = self._current = _Launch(playwright, browser)
            current.renders += 1
            return current

    def retire(self, launch: _Launch) -> None:
        """Stop handing out a launch that cannot render; it closes when its last render releases it."""
        if launch is self._current:
            self._current = None

    async def release(self, launch: _Launch) -> None:
        launch.renders -= 1
        if launch.renders:
            return
        if launch is self._current:
            self._idle_timer = asyncio.get_running_loop().call_later(
                CHROMIUM_IDLE_CLOSE_SECONDS, self._start_idle_close, launch
            )
        else:
            await launch.close()

    def _start_idle_close(self, launch: _Launch) -> None:
        self._idle_timer = None
        task = asyncio.create_task(self._close_if_idle(launch))
        self._idle_closes.add(task)  # pragma: no mutate — GC guard only
        task.add_done_callback(self._idle_closes.discard)  # pragma: no mutate — GC guard only

    async def _close_if_idle(self, launch: _Launch) -> None:
        async with self._launching:
            if launch is self._current and launch.renders == 0:
                self._current = None
                await launch.close()

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    async def close(self) -> None:
        self._cancel_idle_timer()
        async with self._launching:
            current, self._current = self._current, None
            if current is not None:
                await current.close()


class _RenderSlots:
    """CHROMIUM_MAX_CONCURRENT_RENDERS turns, and a count of the renders waiting for one."""

    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(CHROMIUM_MAX_CONCURRENT_RENDERS)
        self.waiting = 0

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[None]:
        if self._slots.locked():
            self.waiting += 1
            try:
                await self._slots.acquire()
            finally:
                self.waiting -= 1
        else:
            await self._slots.acquire()
        try:
            yield
        finally:
            self._slots.release()


_chromium = _ProcessChromium()
_slots = _RenderSlots()


@dataclass(frozen=True)
class RenderPage:
    """A page in its own browser context, and every script error it has thrown so far."""

    page: Page
    script_errors: list[str]

    def fail_on_script_errors(self, doing: str) -> None:
        """Raise RuntimeError naming the first script error, so a broken page never ships blank.

        Raises:
            RuntimeError: A script on the page threw.
        """
        if self.script_errors:
            raise RuntimeError(f"Page script failed while {doing}: {self.script_errors[0]}")


def renders_waiting() -> int:
    """Count the renders in this process waiting for a turn."""
    return _slots.waiting


@asynccontextmanager
async def chromium_page(
    viewport: ViewportSize, device_scale_factor: float | None = None
) -> AsyncIterator[RenderPage]:
    """Wait for a render turn, then open a page in a fresh context of the process's browser."""
    async with _slots.turn():
        launch, context = await _open_context(viewport, device_scale_factor)
        try:
            try:
                page = await context.new_page()
                script_errors: list[str] = []
                page.on("pageerror", lambda error: script_errors.append(str(error)))
                yield RenderPage(page, script_errors)
            finally:
                await context.close()
        finally:
            await _chromium.release(launch)


def _driver_died(error: BaseException) -> bool:
    """Whether an error says the browser's driver is gone, so the browser can never render again."""
    return isinstance(error, TargetClosedError) or CHROMIUM_DEAD_DRIVER_MESSAGE in str(error)


async def _open_context(
    viewport: ViewportSize, device_scale_factor: float | None
) -> tuple[_Launch, BrowserContext]:
    """Open a context in the process's browser, replacing it once if its driver died."""
    launch = await _chromium.acquire()
    try:
        return launch, await _context_on(launch, viewport, device_scale_factor)
    except Exception as exc:
        if not _driver_died(exc):
            raise
        log.warning(f"{LogTag.BROWSER} Render browser is dead; relaunching")
    launch = await _chromium.acquire()
    return launch, await _context_on(launch, viewport, device_scale_factor)


async def _context_on(
    launch: _Launch, viewport: ViewportSize, device_scale_factor: float | None
) -> BrowserContext:
    """Open a context on launch; a failure gives the launch back, retired first when its driver died."""
    try:
        return await launch.browser.new_context(
            viewport=viewport, device_scale_factor=device_scale_factor
        )
    except BaseException as exc:
        if _driver_died(exc):
            _chromium.retire(launch)
        await _chromium.release(launch)
        raise


async def close_chromium() -> None:
    """Close this process's browser; the next render launches a new one."""
    await _chromium.close()
