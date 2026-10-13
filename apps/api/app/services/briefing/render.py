"""Rasterize briefing HTML into PNG bytes with headless Chromium.

The briefing engine composes each summary as an HTML document; delivery
channels (notifications, image attachments) need a pixel-perfect PNG. Playwright
+ Chromium are already vendored via crawl4ai, so we drive a throwaway headless
browser here rather than pulling in a separate rasterizer.

Each call owns a fresh browser that is always torn down in a ``finally`` block —
``app.utils.browser_reaper`` is the process-level backstop for anything this
path still manages to orphan, but the happy path must never leak.
"""

from dataclasses import dataclass
from typing import Literal

from playwright.async_api import async_playwright

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_CHROMIUM_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

# Chromium reports fonts as ready before glyphs are fully painted; a short settle
# avoids capturing a frame mid-layout without polling for an arbitrary condition.
_FONT_SETTLE_MS = 150


@dataclass(frozen=True)
class ImageRenderOptions:
    """How a briefing HTML document is rasterized.

    Attributes:
        width: Viewport width in CSS pixels.
        device_scale_factor: Pixel density multiplier (2 = retina-sharp output).
        full_page: Capture the entire scrollable page, not just the viewport.
        image_format: ``"png"`` (lossless) or ``"jpeg"`` (smaller — used when the
            output is inlined into an email that must dodge Gmail's ~102KB clip).
        quality: JPEG quality 0-100 (ignored for PNG).
        timeout_ms: Per-navigation timeout for ``set_content``.
    """

    width: int = 1180
    device_scale_factor: int = 2
    full_page: bool = True
    image_format: Literal["png", "jpeg"] = "png"
    quality: int | None = None
    timeout_ms: int = 15000


async def render_html_to_image(
    html: str, options: ImageRenderOptions = ImageRenderOptions()
) -> bytes:
    """Render an HTML string to image bytes via headless Chromium.

    Args:
        html: Full HTML document to rasterize.
        options: Viewport, output format and timeout settings.

    Returns:
        Encoded image bytes in the requested format.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=_CHROMIUM_LAUNCH_ARGS)
        try:
            context = await browser.new_context(
                viewport={"width": options.width, "height": 1},
                device_scale_factor=options.device_scale_factor,
            )
            page = await context.new_page()
            await page.set_content(html, wait_until="networkidle", timeout=options.timeout_ms)
            await page.wait_for_timeout(_FONT_SETTLE_MS)
            if options.image_format == "jpeg":
                image = await page.screenshot(
                    full_page=options.full_page, type="jpeg", quality=options.quality
                )
            else:
                image = await page.screenshot(full_page=options.full_page, type="png")
            log.debug(
                f"{LogTag.TOOL} Rendered HTML to image",
                image_format=options.image_format,
                image_bytes=len(image),
                width=options.width,
            )
            return image
        finally:
            await browser.close()
