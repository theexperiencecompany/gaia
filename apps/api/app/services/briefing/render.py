"""Rasterize briefing HTML into PNG bytes with headless Chromium.

Each call owns a fresh browser that is always torn down in a finally block;
app.utils.browser_reaper is only the process-level backstop.
"""

from dataclasses import dataclass
import io
from typing import Literal

from PIL import Image, ImageChops, ImageStat
from playwright.async_api import FloatRect, Page, async_playwright

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_CHROMIUM_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

# Chromium reports fonts as ready before glyphs are fully painted; a short settle
# avoids capturing a frame mid-layout without polling for an arbitrary condition.
_FONT_SETTLE_MS = 150

# How far (0-255, any channel) a pixel must differ from the image edge's own pixel
# in the same row or column to count as content rather than background. Above a
# desk's gradient drift, below the faintest visible shadow.
TRIM_THRESHOLD = 24

# The fold sits this many CSS px above the marker, so an antialiased edge never shows.
FOLD_CLEARANCE_PX = 2

# The page-coordinate top of the fold marker and every visible box inside it.
_FOLD_TOP_SCRIPT = """(selector) => {
  const marker = document.querySelector(selector);
  if (!marker) return null;
  let top = Infinity;
  for (const el of [marker, ...marker.querySelectorAll("*")]) {
    const box = el.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) top = Math.min(top, box.top);
  }
  return Number.isFinite(top) ? top + window.scrollY : null;
}"""


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
        clip_selector: Capture exactly this element's box.
        trim_margin_px: Cut the background around the visible content (shadows and
            tilted pieces included) down to this even margin, in CSS pixels.
    """

    width: int = 1180
    device_scale_factor: int = 2
    full_page: bool = True
    image_format: Literal["png", "jpeg"] = "png"
    quality: int | None = None
    timeout_ms: int = 15000
    clip_selector: str | None = None
    trim_margin_px: int | None = None
    #: The element whose top is where the edition folds, reported as a share of the image height.
    fold_selector: str | None = None


@dataclass(frozen=True)
class RenderedImage:
    """The rasterized document, and where in it the edition folds."""

    image: bytes
    #: Share of the image height, 0..1, at the top of the fold marker; None without one.
    fold: float | None = None


async def render_html_to_image(
    html: str, options: ImageRenderOptions = ImageRenderOptions()
) -> RenderedImage:
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
            fold_px = await _fold_px(page, options, clip)
            if options.trim_margin_px is not None:
                margin = options.trim_margin_px * options.device_scale_factor
                box = content_box(Image.open(io.BytesIO(image)).convert("RGB"), margin)
                if fold_px is not None and box is not None:
                    fold_px -= box[1]
                image = trim_to_content(image, margin, options)
            log.debug(
                f"{LogTag.TOOL} Rendered HTML to image",
                image_format=options.image_format,
                image_bytes=len(image),
                width=options.width,
            )
            return RenderedImage(image=image, fold=_fold_share(image, fold_px))
        finally:
            await browser.close()


async def _fold_px(page: Page, options: ImageRenderOptions, clip: FloatRect | None) -> float | None:
    """Return the fold marker's top in image pixels before any trim, or None without one.

    The top is the highest point of the marker or anything inside it, so a dot or
    badge that pokes above the block never peeks over the fold.
    """
    if options.fold_selector is None:
        return None
    page_top: float | None = await page.evaluate(_FOLD_TOP_SCRIPT, options.fold_selector)
    if page_top is None:
        return None
    top = page_top - (clip["y"] if clip else 0) - FOLD_CLEARANCE_PX
    return top * options.device_scale_factor


def _fold_share(image_bytes: bytes, fold_px: float | None) -> float | None:
    """Express the fold as a share of the final image height, None when it falls outside it."""
    if fold_px is None:
        return None
    height = Image.open(io.BytesIO(image_bytes)).height
    share = fold_px / height
    return share if 0 < share < 1 else None


async def _clip_for(page: Page, selector: str) -> FloatRect:
    """Return the page-coordinate box of the selector's first element.

    A selector that matches nothing raises rather than ship an uncropped page.
    """
    box: FloatRect | None = await page.locator(selector).first.bounding_box()
    if box is None:
        raise RuntimeError(f"Clip element not rendered: {selector!r}")
    scroll = await page.evaluate("() => [window.scrollX, window.scrollY]")
    return {
        "x": box["x"] + scroll[0],
        "y": box["y"] + scroll[1],
        "width": box["width"],
        "height": box["height"],
    }


def background_run(image: Image.Image) -> int:
    """Count the pixel columns, walking left to right, that match the first one.

    A column matches when no pixel differs from the first column's pixel beside it by
    more than TRIM_THRESHOLD in any channel. Other sides are walked by transposing.
    """
    width, height = image.size

    def column(x: int) -> Image.Image:
        return image.crop((x, 0, x + 1, height))

    edge = column(0)
    for x in range(width):
        extrema = ImageStat.Stat(ImageChops.difference(column(x), edge)).extrema
        if max(high for _, high in extrema) > TRIM_THRESHOLD:
            return x
    return width


def content_box(image: Image.Image, margin_px: int) -> tuple[int, int, int, int] | None:
    """Return the box that cuts each side's background run down to margin_px, or None for a blank image.

    Background is whatever matches the image's own edge pixels; a side whose content
    already sits within the margin is left as captured.
    """
    width, height = image.size
    left = background_run(image)
    if left == width:
        return None
    right = background_run(image.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    top = background_run(image.transpose(Image.Transpose.TRANSPOSE))
    bottom = background_run(image.transpose(Image.Transpose.TRANSVERSE))
    return (
        max(0, left - margin_px),
        max(0, top - margin_px),
        min(width, width - right + margin_px),
        min(height, height - bottom + margin_px),
    )


def trim_to_content(image_bytes: bytes, margin_px: int, options: ImageRenderOptions) -> bytes:
    """Cut each side's background run down to margin_px device pixels; a blank image is returned unchanged."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    box = content_box(image, margin_px)
    if box is None:
        return image_bytes
    save_options: dict[str, int | bool] = (
        {"quality": options.quality or 75} if options.image_format == "jpeg" else {"optimize": True}
    )
    out = io.BytesIO()
    image.crop(box).save(out, format=options.image_format, **save_options)
    return out.getvalue()
