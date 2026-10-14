"""Unit tests for the briefing HTML-to-image rasterizer.

Chromium is never launched: async_playwright is faked at the boundary render.py uses,
so every browser argument the module sends is captured and asserted exactly.
"""

from dataclasses import FrozenInstanceError
import io
from typing import Any

from PIL import Image, ImageDraw
import pytest

from app.services.briefing import render as render_module
from app.services.briefing.render import (
    ImageRenderOptions,
    render_html_to_image,
    trim_to_content,
)

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-payload"


class FakePage:
    def __init__(self, image: bytes) -> None:
        self._image = image
        self.set_content_calls: list[dict[str, Any]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.screenshot_calls: list[dict[str, Any]] = []
        self.set_content_error: Exception | None = None
        self.handlers: dict[str, list[Any]] = {}
        self.script_errors: list[Exception] = []
        self.boxes: dict[str, dict[str, float] | None] = {}
        self.scroll: list[float] = [0.0, 0.0]

    def on(self, event: str, handler: Any) -> None:
        self.handlers.setdefault(event, []).append(handler)

    async def set_content(self, html: str, **kwargs: Any) -> None:
        self.set_content_calls.append({"html": html, **kwargs})
        for error in self.script_errors:
            for handler in self.handlers.get("pageerror", []):
                handler(error)
        if self.set_content_error is not None:
            raise self.set_content_error

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator(self.boxes.get(selector))

    async def evaluate(self, expression: str) -> list[float]:
        assert expression == "() => [window.scrollX, window.scrollY]"
        return self.scroll

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_for_timeout_calls.append(milliseconds)

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_calls.append(kwargs)
        return self._image


class FakeLocator:
    def __init__(self, box: dict[str, float] | None) -> None:
        self._box = box

    @property
    def first(self) -> "FakeLocator":
        return self

    async def bounding_box(self) -> dict[str, float] | None:
        return self._box


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    async def new_page(self) -> FakePage:
        return self._page


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.new_context_calls: list[dict[str, Any]] = []
        self.close_count = 0

    async def new_context(self, **kwargs: Any) -> FakeContext:
        self.new_context_calls.append(kwargs)
        return FakeContext(self._page)

    async def close(self) -> None:
        self.close_count += 1


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self._browser = browser
        self.launch_calls: list[dict[str, Any]] = []

    async def launch(self, **kwargs: Any) -> FakeBrowser:
        self.launch_calls.append(kwargs)
        return self._browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.exited = False

    async def __aenter__(self) -> "FakePlaywright":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self.exited = True
        return False


class Harness:
    def __init__(self) -> None:
        self.page = FakePage(IMAGE_BYTES)
        self.browser = FakeBrowser(self.page)
        self.chromium = FakeChromium(self.browser)
        self.playwright = FakePlaywright(self.chromium)


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Harness:
    harness = Harness()
    monkeypatch.setattr(render_module, "async_playwright", lambda: harness.playwright)
    return harness


@pytest.mark.unit
class TestImageRenderOptions:
    def test_defaults_are_the_shipped_render_settings(self) -> None:
        options = ImageRenderOptions()

        assert options.width == 1180
        assert options.device_scale_factor == 2
        assert options.full_page is True
        assert options.image_format == "png"
        assert options.quality is None
        assert options.timeout_ms == 15000
        assert options.clip_selector is None
        assert options.trim_margin_px is None

    def test_options_are_immutable(self) -> None:
        options = ImageRenderOptions()

        with pytest.raises(FrozenInstanceError):
            options.width = 500  # type: ignore[misc]  # assigning to a frozen field is exactly what this test asserts raises

    def test_overrides_are_kept_verbatim(self) -> None:
        options = ImageRenderOptions(
            width=640,
            device_scale_factor=1,
            full_page=False,
            image_format="jpeg",
            quality=70,
            timeout_ms=1000,
        )

        assert (options.width, options.device_scale_factor, options.full_page) == (640, 1, False)
        assert (options.image_format, options.quality, options.timeout_ms) == ("jpeg", 70, 1000)


@pytest.mark.unit
class TestRenderHtmlToImage:
    async def test_returns_the_screenshot_bytes_unmodified(self, browser: Harness) -> None:
        result = await render_html_to_image("<html>hi</html>")

        assert result == IMAGE_BYTES

    async def test_chromium_launches_headless_with_the_container_safe_flags(
        self, browser: Harness
    ) -> None:
        await render_html_to_image("<html>hi</html>")

        assert browser.chromium.launch_calls == [
            {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        ]

    async def test_viewport_and_scale_come_from_the_options(self, browser: Harness) -> None:
        await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(width=800, device_scale_factor=3)
        )

        assert browser.browser.new_context_calls == [
            {"viewport": {"width": 800, "height": 1}, "device_scale_factor": 3}
        ]

    async def test_content_is_set_with_the_html_and_navigation_timeout(
        self, browser: Harness
    ) -> None:
        await render_html_to_image("<html>body</html>", ImageRenderOptions(timeout_ms=4321))

        assert browser.page.set_content_calls == [
            {"html": "<html>body</html>", "wait_until": "networkidle", "timeout": 4321}
        ]

    async def test_waits_for_fonts_to_settle_before_capturing(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>")

        assert browser.page.wait_for_timeout_calls == [150]

    async def test_png_capture_sends_no_quality(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>", ImageRenderOptions(quality=55))

        assert browser.page.screenshot_calls == [{"full_page": True, "type": "png", "clip": None}]

    async def test_jpeg_capture_forwards_the_quality(self, browser: Harness) -> None:
        await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(image_format="jpeg", quality=62)
        )

        assert browser.page.screenshot_calls == [
            {"full_page": True, "type": "jpeg", "quality": 62, "clip": None}
        ]

    async def test_jpeg_capture_without_quality_passes_none(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>", ImageRenderOptions(image_format="jpeg"))

        assert browser.page.screenshot_calls == [
            {"full_page": True, "type": "jpeg", "quality": None, "clip": None}
        ]

    async def test_viewport_only_capture_is_honoured(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>", ImageRenderOptions(full_page=False))

        assert browser.page.screenshot_calls == [{"full_page": False, "type": "png", "clip": None}]

    async def test_empty_html_still_renders(self, browser: Harness) -> None:
        result = await render_html_to_image("")

        assert result == IMAGE_BYTES
        assert browser.page.set_content_calls[0]["html"] == ""

    async def test_browser_is_closed_on_the_happy_path(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>")

        assert browser.browser.close_count == 1
        assert browser.playwright.exited is True

    async def test_browser_is_closed_and_the_error_propagates_when_navigation_fails(
        self, browser: Harness
    ) -> None:
        browser.page.set_content_error = TimeoutError("navigation timed out")

        with pytest.raises(TimeoutError, match="navigation timed out"):
            await render_html_to_image("<html>hi</html>")

        assert browser.browser.close_count == 1
        assert browser.page.screenshot_calls == []

    async def test_a_page_script_error_fails_the_render_before_any_capture(
        self, browser: Harness
    ) -> None:
        browser.page.script_errors = [ValueError("ed is undefined"), ValueError("second")]

        with pytest.raises(
            RuntimeError, match=r"^Page script failed while rendering: ed is undefined$"
        ):
            await render_html_to_image("<html>hi</html>")

        assert browser.page.screenshot_calls == []
        assert browser.browser.close_count == 1


@pytest.mark.unit
class TestClipSelector:
    async def test_the_capture_is_exactly_the_element_box_in_page_coordinates(
        self, browser: Harness
    ) -> None:
        browser.page.boxes[".paper"] = {"x": 100.0, "y": 50.0, "width": 400.0, "height": 300.0}
        browser.page.scroll = [5.0, 700.0]

        await render_html_to_image("<html>hi</html>", ImageRenderOptions(clip_selector=".paper"))

        assert browser.page.screenshot_calls == [
            {
                "full_page": True,
                "type": "png",
                "clip": {"x": 105.0, "y": 750.0, "width": 400.0, "height": 300.0},
            }
        ]

    async def test_a_selector_matching_nothing_fails_loud_instead_of_shipping_uncropped(
        self, browser: Harness
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^Clip element not rendered: '\.missing'$"):
            await render_html_to_image(
                "<html>hi</html>", ImageRenderOptions(clip_selector=".missing")
            )

        assert browser.page.screenshot_calls == []


_DESK = (90, 60, 40)
_PAPER = (250, 250, 250)
_SHADOW = (40, 25, 15)


def _desk_with_paper(
    size: tuple[int, int], paper: tuple[int, int, int, int], *, shadow_below: int = 0
) -> bytes:
    """Draw a flat desk with a paper box and an optional shadow strip under it."""
    image = Image.new("RGB", size, _DESK)
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = paper
    if shadow_below:
        draw.rectangle((left, bottom, right - 1, bottom + shadow_below - 1), fill=_SHADOW)
    if right > left and bottom > top:
        draw.rectangle((left, top, right - 1, bottom - 1), fill=_PAPER)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _opened(image: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image)).convert("RGB")


@pytest.mark.unit
class TestTrimToContent:
    def test_every_side_is_cut_to_the_same_margin_of_desk(self) -> None:
        png = _desk_with_paper((300, 400), (50, 70, 200, 330))

        trimmed = _opened(trim_to_content(png, 10, ImageRenderOptions()))

        assert trimmed.size == (150 + 20, 260 + 20)
        assert trimmed.getpixel((9, 9)) == _DESK
        assert trimmed.getpixel((10, 10)) == _PAPER
        assert trimmed.getpixel((159, 269)) == _PAPER
        assert trimmed.getpixel((160, 270)) == _DESK

    def test_a_visible_shadow_counts_as_paper(self) -> None:
        png = _desk_with_paper((300, 400), (50, 70, 200, 300), shadow_below=12)

        trimmed = _opened(trim_to_content(png, 10, ImageRenderOptions()))

        assert trimmed.size == (170, 230 + 12 + 20)
        assert trimmed.getpixel((80, 10 + 230 + 5)) == _SHADOW

    def test_a_side_already_inside_the_margin_is_left_as_captured(self) -> None:
        png = _desk_with_paper((300, 400), (4, 70, 200, 330))

        trimmed = _opened(trim_to_content(png, 10, ImageRenderOptions()))

        assert trimmed.size == (196 + 4 + 10, 280)
        assert trimmed.getpixel((0, 100)) == _DESK

    def test_a_blank_capture_is_returned_untouched(self) -> None:
        png = _desk_with_paper((40, 40), (0, 0, 0, 0))

        assert trim_to_content(png, 10, ImageRenderOptions()) == png

    def test_a_jpeg_capture_stays_a_jpeg(self) -> None:
        png = _desk_with_paper((300, 400), (50, 70, 200, 330))

        trimmed = trim_to_content(png, 10, ImageRenderOptions(image_format="jpeg", quality=80))

        assert trimmed[:3] == b"\xff\xd8\xff"

    async def test_the_render_trims_at_device_scale(self, browser: Harness) -> None:
        browser.page._image = _desk_with_paper((300, 400), (50, 70, 200, 330))

        image = await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(device_scale_factor=2, trim_margin_px=5)
        )

        assert _opened(image).size == (170, 280)
