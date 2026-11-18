"""The process browser against real Chromium: one launch, a context per render, a new launch once it dies."""

import asyncio

from playwright.async_api import Browser, ViewportSize
import pytest

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
