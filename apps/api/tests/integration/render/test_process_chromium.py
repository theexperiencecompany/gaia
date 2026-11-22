"""The process browser against real Chromium: one launch, a context per render, a new launch once it dies."""

import asyncio
import os
import signal

from playwright.async_api import Browser, Playwright, ViewportSize
import pytest

from app.services.render import chromium as chromium_module
from app.services.render.chromium import chromium_page
from app.services.render.image import render_html_to_image

pytestmark = pytest.mark.asyncio(loop_scope="package")

_PAGE: ViewportSize = {"width": 320, "height": 200}


async def _render_browser() -> Browser:
    async with chromium_page(_PAGE) as rendering:
        browser = rendering.page.context.browser
    assert browser is not None
    return browser


@pytest.mark.integration
async def test_renders_share_one_browser_and_leave_no_context_behind() -> None:
    first = await _render_browser()
    second = await _render_browser()

    assert second is first
    assert first.contexts == []


@pytest.mark.integration
async def test_a_render_after_chromium_died_launches_a_new_browser() -> None:
    dead = await _render_browser()
    disconnected = asyncio.get_running_loop().create_future()
    dead.once("disconnected", lambda _: disconnected.set_result(None))
    cdp = await dead.new_browser_cdp_session()
    await cdp.send("Browser.close")
    await asyncio.wait_for(disconnected, timeout=30)

    rendered = await render_html_to_image("<p>after the crash</p>")

    assert rendered.image.startswith(b"\x89PNG")
    assert await _render_browser() is not dead


def _kill_driver(playwright: Playwright) -> None:
    """SIGKILL the Playwright driver behind playwright, as an OOM kill or a process reaper does."""
    os.kill(playwright._impl_obj._connection._transport._proc.pid, signal.SIGKILL)


@pytest.mark.integration
async def test_a_render_after_the_driver_died_launches_a_new_browser() -> None:
    """Replay: a killed driver left the browser connected, so every render on it failed."""
    dead = await _render_browser()
    launch = chromium_module._chromium._current
    assert launch is not None
    _kill_driver(launch.playwright)

    rendered = await render_html_to_image("<p>after the driver died</p>")

    assert rendered.image.startswith(b"\x89PNG")
    assert await _render_browser() is not dead


@pytest.mark.integration
async def test_a_browser_past_its_age_whose_driver_died_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay: replacing an aged browser closed its dead driver, which raised and failed the render."""
    dead = await _render_browser()
    launch = chromium_module._chromium._current
    assert launch is not None
    _kill_driver(launch.playwright)
    monkeypatch.setattr(chromium_module, "CHROMIUM_RECYCLE_AGE_SECONDS", 0)

    rendered = await render_html_to_image("<p>after the reaper</p>")

    assert rendered.image.startswith(b"\x89PNG")
    assert await _render_browser() is not dead
