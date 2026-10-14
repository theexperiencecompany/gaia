"""Rasterize briefing HTML into PNG bytes with headless Chromium.

Each call owns a fresh browser that is always torn down in a finally block;
app.utils.browser_reaper is only the process-level backstop.
"""

from dataclasses import dataclass
from typing import Literal

from playwright.async_api import FloatRect, Page, async_playwright

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_CHROMIUM_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

# Chromium reports fonts as ready before glyphs are fully painted; a short settle
# avoids capturing a frame mid-layout without polling for an arbitrary condition.
_FONT_SETTLE_MS = 150

# Breathing room kept around a clipped element so its edge shadow survives.
CLIP_PADDING_PX = 12


@dataclass(frozen=True)
class ImageRenderOptions:
    """How a briefing HTML document is rasterized.

    Attributes:
        width: Viewport width in CSS pixels.
        device_scale_factor: Pixel density multiplier (2 = retina-sharp output).
        full_page: Capture the entire scrollable page, not just the viewport.
        image_format: "png" or "jpeg" (smaller, to dodge Gmail's ~102KB clip).
        quality: JPEG quality 0-100 (ignored for PNG).
        timeout_ms: Per-navigation timeout for set_content.
        clip_selector: Crop to this element's box plus CLIP_PADDING_PX.
    """

    width: int = 1180
    device_scale_factor: int = 2
    full_page: bool = True
    image_format: Literal["png", "jpeg"] = "png"
    quality: int | None = None
    timeout_ms: int = 15000
    clip_selector: str | None = None


async def render_html_to_image(
    html: str, options: ImageRenderOptions = ImageRenderOptions()
) -> bytes:
    """Render an HTML string to image bytes via headless Chromium.

    Raises:
        RuntimeError: A script on the page threw, leaving the document unrendered.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=_CHROMIUM_LAUNCH_ARGS)
        try:
            context = await browser.new_context(
                viewport={"width": options.width, "height": 1},
                device_scale_factor=options.device_scale_factor,
            )
            page = await context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            await page.set_content(html, wait_until="networkidle", timeout=options.timeout_ms)
            if page_errors:
                raise RuntimeError(f"Page script failed while rendering: {page_errors[0]}")
            await page.wait_for_timeout(_FONT_SETTLE_MS)
            clip = await _clip_for(page, options.clip_selector) if options.clip_selector else None
            if options.image_format == "jpeg":
                image = await page.screenshot(
                    full_page=options.full_page, type="jpeg", quality=options.quality, clip=clip
                )
            else:
                image = await page.screenshot(full_page=options.full_page, type="png", clip=clip)
            log.debug(
                f"{LogTag.TOOL} Rendered HTML to image",
                image_format=options.image_format,
                image_bytes=len(image),
                width=options.width,
            )
            return image
        finally:
            await browser.close()


async def _clip_for(page: Page, selector: str) -> FloatRect:
    """Return the padded page-coordinate box of the selector's element.

    A selector that matches nothing raises rather than ship uncropped margins.
    """
    box: FloatRect | None = await page.locator(selector).first.bounding_box()
    if box is None:
        raise RuntimeError(f"Clip element not rendered: {selector!r}")
    scroll = await page.evaluate("() => [window.scrollX, window.scrollY]")
    x = max(0.0, box["x"] + scroll[0] - CLIP_PADDING_PX)
    y = max(0.0, box["y"] + scroll[1] - CLIP_PADDING_PX)
    return {
        "x": x,
        "y": y,
        "width": box["width"] + 2 * CLIP_PADDING_PX,
        "height": box["height"] + 2 * CLIP_PADDING_PX,
    }
