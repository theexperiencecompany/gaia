"""Unit tests for the briefing HTML→image rasterizer.

The real Chromium is never launched: ``async_playwright`` is faked at the
boundary ``render.py`` actually uses, so every browser argument the module
sends is captured and asserted exactly.
"""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from app.services.briefing import render as render_module
from app.services.briefing.render import ImageRenderOptions, render_html_to_image

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-payload"


class FakePage:
    def __init__(self, image: bytes) -> None:
        self._image = image
        self.set_content_calls: list[dict[str, Any]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.screenshot_calls: list[dict[str, Any]] = []
        self.set_content_error: Exception | None = None

    async def set_content(self, html: str, **kwargs: Any) -> None:
        self.set_content_calls.append({"html": html, **kwargs})
        if self.set_content_error is not None:
            raise self.set_content_error

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_for_timeout_calls.append(milliseconds)

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_calls.append(kwargs)
        return self._image


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

        assert browser.page.screenshot_calls == [{"full_page": True, "type": "png"}]

    async def test_jpeg_capture_forwards_the_quality(self, browser: Harness) -> None:
        await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(image_format="jpeg", quality=62)
        )

        assert browser.page.screenshot_calls == [{"full_page": True, "type": "jpeg", "quality": 62}]

    async def test_jpeg_capture_without_quality_passes_none(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>", ImageRenderOptions(image_format="jpeg"))

        assert browser.page.screenshot_calls == [
            {"full_page": True, "type": "jpeg", "quality": None}
        ]

    async def test_viewport_only_capture_is_honoured(self, browser: Harness) -> None:
        await render_html_to_image("<html>hi</html>", ImageRenderOptions(full_page=False))

        assert browser.page.screenshot_calls == [{"full_page": False, "type": "png"}]

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
