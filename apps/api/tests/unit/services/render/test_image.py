"""The HTML-to-image rasterizer: what it captures, how it trims, and where it reports the fold and paper.

Chromium is never launched: a fake page stands in for the one the process browser opens.
"""

import io
from typing import Any

from PIL import Image, ImageChops, ImageDraw
import pytest

from app.services.render import image as render_module
from app.services.render.image import (
    TRIM_ALPHA_THRESHOLD,
    TRIM_THRESHOLD,
    ImageRenderOptions,
    background_run,
    render_html_to_image,
    trim_to_content,
)
from tests.unit.services.render.conftest import FakeChromium

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
        self.fold_tops: dict[str, float | None] = {}
        self.paper_boxes: dict[str, list[float] | None] = {}

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

    async def evaluate(self, expression: str, selector: str | None = None) -> Any:
        if expression == render_module._FOLD_TOP_SCRIPT:
            assert selector is not None
            return self.fold_tops[selector]
        if expression == render_module._PAPER_BOX_SCRIPT:
            assert selector is not None
            return self.paper_boxes[selector]
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


@pytest.fixture
def page(chromium: FakeChromium) -> FakePage:
    chromium.page = FakePage(IMAGE_BYTES)
    return chromium.page


@pytest.mark.unit
class TestRenderHtmlToImage:
    async def test_an_untrimmed_capture_is_returned_unmodified(self, page: FakePage) -> None:
        result = (await render_html_to_image("<html>hi</html>")).image

        assert result == IMAGE_BYTES

    async def test_the_page_is_laid_out_at_the_options_width_and_scale(
        self, page: FakePage, chromium: FakeChromium
    ) -> None:
        await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(width=800, device_scale_factor=3)
        )

        [context] = chromium.browsers[0].contexts
        assert context.options == {
            "viewport": {"width": 800, "height": 1},
            "device_scale_factor": 3,
        }

    async def test_the_html_is_loaded_to_network_idle_and_fonts_settle_before_capture(
        self, page: FakePage
    ) -> None:
        await render_html_to_image("<html>body</html>")

        assert page.set_content_calls == [
            {"html": "<html>body</html>", "wait_until": "networkidle", "timeout": 15_000}
        ]
        assert page.wait_for_timeout_calls == [render_module._FONT_SETTLE_MS]

    async def test_a_failed_navigation_propagates_and_nothing_is_captured(
        self, page: FakePage
    ) -> None:
        page.set_content_error = TimeoutError("navigation timed out")

        with pytest.raises(TimeoutError, match="navigation timed out"):
            await render_html_to_image("<html>hi</html>")

        assert page.screenshot_calls == []

    async def test_a_page_script_error_fails_the_render_before_any_capture(
        self, page: FakePage
    ) -> None:
        page.script_errors = [ValueError("ed is undefined"), ValueError("second")]

        with pytest.raises(
            RuntimeError, match=r"^Page script failed while rendering: ed is undefined$"
        ):
            await render_html_to_image("<html>hi</html>")

        assert page.screenshot_calls == []


@pytest.mark.unit
class TestClipSelector:
    async def test_the_capture_is_exactly_the_element_box_in_page_coordinates(
        self, page: FakePage
    ) -> None:
        page.boxes[".paper"] = {"x": 100.0, "y": 50.0, "width": 400.0, "height": 300.0}
        page.scroll = [5.0, 700.0]

        await render_html_to_image("<html>hi</html>", ImageRenderOptions(clip_selector=".paper"))

        assert page.screenshot_calls == [
            {
                "full_page": True,
                "type": "png",
                "clip": {"x": 105.0, "y": 750.0, "width": 400.0, "height": 300.0},
                "omit_background": False,
            }
        ]

    async def test_the_bleed_grows_the_box_on_every_side(self, page: FakePage) -> None:
        page.boxes[".paper"] = {"x": 100.0, "y": 50.0, "width": 400.0, "height": 300.0}
        page.scroll = [5.0, 700.0]

        await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(clip_selector=".paper", clip_bleed_px=20)
        )

        [screenshot] = page.screenshot_calls
        assert screenshot["clip"] == {"x": 85.0, "y": 730.0, "width": 440.0, "height": 340.0}

    async def test_a_selector_matching_nothing_fails_loud_instead_of_shipping_uncropped(
        self, page: FakePage
    ) -> None:
        with pytest.raises(RuntimeError, match=r"^Clip element not rendered: '\.missing'$"):
            await render_html_to_image(
                "<html>hi</html>", ImageRenderOptions(clip_selector=".missing")
            )

        assert page.screenshot_calls == []


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

        trimmed = _opened(trim_to_content(png, 10)[0])

        assert trimmed.size == (150 + 20, 260 + 20)
        assert trimmed.getpixel((9, 9)) == _DESK
        assert trimmed.getpixel((10, 10)) == _PAPER
        assert trimmed.getpixel((159, 269)) == _PAPER
        assert trimmed.getpixel((160, 270)) == _DESK

    def test_a_visible_shadow_counts_as_paper(self) -> None:
        png = _desk_with_paper((300, 400), (50, 70, 200, 300), shadow_below=12)

        trimmed = _opened(trim_to_content(png, 10)[0])

        assert trimmed.size == (170, 230 + 12 + 20)
        assert trimmed.getpixel((80, 10 + 230 + 5)) == _SHADOW

    def test_a_side_already_inside_the_margin_is_left_as_captured(self) -> None:
        png = _desk_with_paper((300, 400), (4, 70, 200, 330))

        trimmed = _opened(trim_to_content(png, 10)[0])

        assert trimmed.size == (196 + 4 + 10, 280)
        assert trimmed.getpixel((0, 100)) == _DESK

    def test_a_grayscale_capture_is_trimmed_like_a_colour_one(self) -> None:
        gray = Image.new("L", (300, 400), 200)
        ImageDraw.Draw(gray).rectangle((50, 70, 199, 329), fill=40)
        out = io.BytesIO()
        gray.save(out, format="PNG")

        trimmed = Image.open(io.BytesIO(trim_to_content(out.getvalue(), 10)[0]))

        assert trimmed.size == (170, 280)

    def test_a_blank_capture_is_returned_untouched(self) -> None:
        png = _desk_with_paper((40, 40), (0, 0, 0, 0))

        assert trim_to_content(png, 10)[0] == png

    async def test_the_render_trims_at_device_scale(self, page: FakePage) -> None:
        page._image = _desk_with_paper((300, 400), (50, 70, 200, 330))

        image = await render_html_to_image(
            "<html>hi</html>", ImageRenderOptions(device_scale_factor=2, trim_margin_px=5)
        )

        assert _opened(image.image).size == (170, 280)

    def test_every_side_already_inside_the_margin_keeps_the_whole_capture(self) -> None:
        png = _desk_with_paper((300, 400), (4, 3, 297, 398))

        trimmed = _opened(trim_to_content(png, 10)[0])

        assert trimmed.size == (300, 400)
        assert trimmed.getpixel((0, 0)) == _DESK
        assert trimmed.getpixel((4, 3)) == _PAPER

    def test_content_in_the_first_row_is_seen_by_the_column_walk(self) -> None:
        png = _desk_with_paper((300, 400), (100, 0, 101, 1))

        trimmed = _opened(trim_to_content(png, 10)[0])

        assert trimmed.size == (21, 11)
        assert trimmed.getpixel((10, 0)) == _PAPER

    def test_content_in_the_first_column_is_seen_by_the_row_walk(self) -> None:
        png = _desk_with_paper((300, 400), (0, 100, 1, 101))

        trimmed = _opened(trim_to_content(png, 10)[0])

        assert trimmed.size == (11, 21)
        assert trimmed.getpixel((0, 10)) == _PAPER

    def test_a_difference_of_exactly_the_threshold_is_still_background(self) -> None:
        image = Image.new("RGB", (300, 400), _DESK)
        draw = ImageDraw.Draw(image)
        faint = (_DESK[0] + TRIM_THRESHOLD, _DESK[1], _DESK[2])
        visible = (_DESK[0] + TRIM_THRESHOLD + 1, _DESK[1], _DESK[2])
        draw.rectangle((20, 20, 279, 379), fill=faint)
        draw.rectangle((50, 70, 199, 329), fill=visible)

        trimmed = _opened(trim_to_content(_saved(image, format="PNG"), 10)[0])

        assert trimmed.size == (170, 280)

    def test_background_is_measured_against_the_edge_line_not_its_neighbour(self) -> None:
        image = Image.new("RGB", (300, 400), _DESK)
        draw = ImageDraw.Draw(image)
        drift = (_DESK[0] + 20, _DESK[1], _DESK[2])
        far_drift = (_DESK[0] + 40, _DESK[1], _DESK[2])
        draw.rectangle((1, 0, 1, 399), fill=drift)
        draw.rectangle((2, 0, 299, 399), fill=far_drift)
        draw.rectangle((150, 70, 199, 329), fill=_PAPER)

        trimmed = _opened(trim_to_content(_saved(image, format="PNG"), 0)[0])

        assert trimmed.size == (200 - 2, 260)
        assert trimmed.getpixel((0, 0)) == far_drift

    def test_a_transparent_capture_keeps_its_alpha(self) -> None:
        image = _clear_with_paper()

        trimmed = Image.open(io.BytesIO(trim_to_content(_saved(image, format="PNG"), 10)[0]))

        assert trimmed.mode == "RGBA"
        assert trimmed.size == (170, 280)
        assert trimmed.getpixel((0, 0)) == (0, 0, 0, 0)
        assert trimmed.getpixel((10, 10)) == (*_PAPER, 255)

    def test_the_faintest_shadow_on_a_transparent_capture_is_kept(self) -> None:
        image = _clear_with_paper()
        faintest = (0, 0, 0, TRIM_ALPHA_THRESHOLD + 1)
        ImageDraw.Draw(image).rectangle((50, 330, 199, 359), fill=faintest)

        trimmed = Image.open(io.BytesIO(trim_to_content(_saved(image, format="PNG"), 10)[0]))

        assert trimmed.size == (170, 280 + 30)
        assert trimmed.getpixel((80, 10 + 260 + 5)) == faintest

    def test_the_hidden_colour_of_a_transparent_background_is_not_content(self) -> None:
        image = _clear_with_paper()
        ImageDraw.Draw(image).rectangle((0, 0, 299, 30), fill=(255, 255, 255, 0))

        trimmed = Image.open(io.BytesIO(trim_to_content(_saved(image, format="PNG"), 10)[0]))

        assert trimmed.size == (170, 280)

    def test_a_paletted_capture_keeps_its_transparent_index_clear(self) -> None:
        paletted = Image.new("P", (300, 400), 0)
        paletted.putpalette([0, 0, 0, *_PAPER])
        ImageDraw.Draw(paletted).rectangle((50, 70, 199, 329), fill=1)
        paletted.info["transparency"] = 0

        trimmed = Image.open(io.BytesIO(trim_to_content(_saved(paletted, format="PNG"), 10)[0]))

        assert trimmed.size == (170, 280)

    def test_a_walk_over_an_image_that_is_not_premultiplied_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="zip"):
            background_run(Image.new("L", (4, 4)))

    def test_a_png_is_cut_losslessly_and_names_the_box_it_kept(self) -> None:
        png = _noisy_desk_with_paper()
        expected = _opened(png).crop((40, 60, 210, 340))

        trimmed, box = trim_to_content(png, 10)

        assert box == (40, 60, 210, 340)
        assert ImageChops.difference(_opened(trimmed), expected).getbbox() is None


def _noisy_desk_with_paper() -> bytes:
    """Draw a flat desk around a textured paper whose bytes depend on encoder settings."""
    image = Image.new("RGB", (300, 400), _DESK)
    texture = bytes((i * 37) % 256 for i in range(150 * 260 * 3))
    image.paste(Image.frombytes("RGB", (150, 260), texture), (50, 70))
    return _saved(image, format="PNG")


def _clear_with_paper() -> Image.Image:
    """Draw a paper on a fully transparent page, as a capture that leaves the desk out."""
    image = Image.new("RGBA", (300, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((50, 70, 199, 329), fill=(*_PAPER, 255))
    return image


def _saved(image: Image.Image, **save_options: Any) -> bytes:
    out = io.BytesIO()
    image.save(out, **save_options)
    return out.getvalue()


def _png(width: int, height: int, ink: tuple[int, int, int, int] | None = None) -> bytes:
    """Return a white capture, with a black block at ink=(left, top, right, bottom) when given."""
    image = Image.new("RGB", (width, height), "white")
    if ink is not None:
        ImageDraw.Draw(image).rectangle(ink, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


@pytest.mark.unit
class TestTheFold:
    async def test_the_fold_is_the_markers_top_less_the_clearance_as_a_share_of_the_image(
        self, page: FakePage
    ) -> None:
        page._image = _png(400, 800)
        page.fold_tops["#fold"] = 100.0

        rendered = await render_html_to_image("<p/>", ImageRenderOptions(fold_selector="#fold"))

        assert rendered.fold == (100 - render_module.FOLD_CLEARANCE_PX) * 2 / 800

    async def test_a_clipped_capture_measures_the_fold_from_the_clip_origin(
        self, page: FakePage
    ) -> None:
        page._image = _png(400, 800)
        page.boxes["#sheet"] = {"x": 0.0, "y": 50.0, "width": 200.0, "height": 400.0}
        page.fold_tops["#fold"] = 150.0

        rendered = await render_html_to_image(
            "<p/>", ImageRenderOptions(clip_selector="#sheet", fold_selector="#fold")
        )

        assert rendered.fold == (150 - 50 - render_module.FOLD_CLEARANCE_PX) * 2 / 800

    async def test_a_page_without_the_marker_has_no_fold(self, page: FakePage) -> None:
        page._image = _png(400, 800)
        page.fold_tops["#fold"] = None

        rendered = await render_html_to_image("<p/>", ImageRenderOptions(fold_selector="#fold"))

        assert rendered.fold is None

    async def test_no_fold_selector_asks_the_page_nothing_and_has_no_fold(
        self, page: FakePage
    ) -> None:
        page._image = _png(400, 800)

        rendered = await render_html_to_image("<p/>")

        assert rendered.fold is None

    @pytest.mark.parametrize("top", [1.0, 2.0, 402.0, 500.0])
    async def test_a_fold_outside_the_image_is_no_fold(self, page: FakePage, top: float) -> None:
        page._image = _png(400, 800)
        page.fold_tops["#fold"] = top

        rendered = await render_html_to_image("<p/>", ImageRenderOptions(fold_selector="#fold"))

        assert rendered.fold is None


@pytest.mark.unit
class TestThePaper:
    async def test_the_paper_is_its_box_in_shares_of_the_image(self, page: FakePage) -> None:
        page._image = _png(400, 800)
        page.paper_boxes["#paper"] = [10.0, 20.0, 110.0, 220.0]

        rendered = await render_html_to_image("<p/>", ImageRenderOptions(paper_selector="#paper"))

        assert rendered.paper == (20 / 400, 40 / 800, 220 / 400, 440 / 800)

    async def test_a_clipped_capture_measures_the_paper_from_the_clip_origin(
        self, page: FakePage
    ) -> None:
        page._image = _png(400, 800)
        page.boxes["#sheet"] = {"x": 5.0, "y": 10.0, "width": 200.0, "height": 400.0}
        page.paper_boxes["#paper"] = [15.0, 30.0, 115.0, 230.0]

        rendered = await render_html_to_image(
            "<p/>", ImageRenderOptions(clip_selector="#sheet", paper_selector="#paper")
        )

        assert rendered.paper == (20 / 400, 40 / 800, 220 / 400, 440 / 800)

    async def test_a_paper_past_the_image_edges_is_clamped_inside_it(self, page: FakePage) -> None:
        page._image = _png(400, 800)
        page.paper_boxes["#paper"] = [-50.0, -50.0, 900.0, 900.0]

        rendered = await render_html_to_image("<p/>", ImageRenderOptions(paper_selector="#paper"))

        assert rendered.paper == (0.0, 0.0, 1.0, 1.0)

    async def test_a_page_without_the_marker_has_no_paper(self, page: FakePage) -> None:
        page._image = _png(400, 800)
        page.paper_boxes["#paper"] = None

        rendered = await render_html_to_image("<p/>", ImageRenderOptions(paper_selector="#paper"))

        assert rendered.paper is None

    async def test_no_paper_selector_has_no_paper(self, page: FakePage) -> None:
        page._image = _png(400, 800)

        assert (await render_html_to_image("<p/>")).paper is None


@pytest.mark.unit
class TestTrimmingMovesTheMarkers:
    async def test_the_fold_and_the_paper_follow_the_content_the_trim_keeps(
        self, page: FakePage
    ) -> None:
        # Black block (100,200)-(300,600); a 10px margin at scale 2 keeps (80,180)-(320,620).
        page._image = _png(400, 800, ink=(100, 200, 299, 599))
        page.fold_tops["#fold"] = 150.0
        page.paper_boxes["#paper"] = [60.0, 110.0, 100.0, 210.0]

        rendered = await render_html_to_image(
            "<p/>",
            ImageRenderOptions(trim_margin_px=10, fold_selector="#fold", paper_selector="#paper"),
        )

        trimmed = Image.open(io.BytesIO(rendered.image))
        assert trimmed.size == (240, 440)
        assert rendered.fold == ((150 - render_module.FOLD_CLEARANCE_PX) * 2 - 180) / 440
        assert rendered.paper == (40 / 240, 40 / 440, 120 / 240, 240 / 440)


@pytest.mark.unit
class TestTrimReadsCoverage:
    async def test_an_opaque_block_the_same_colour_as_a_transparent_page_is_content(
        self, page: FakePage
    ) -> None:
        image = Image.new("RGBA", (400, 800), (255, 255, 255, 0))
        ImageDraw.Draw(image).rectangle((100, 200, 299, 599), fill=(255, 255, 255, 255))
        out = io.BytesIO()
        image.save(out, format="PNG")
        page._image = out.getvalue()
        page.fold_tops["#fold"] = 150.0

        rendered = await render_html_to_image(
            "<p/>", ImageRenderOptions(trim_margin_px=10, fold_selector="#fold")
        )

        assert Image.open(io.BytesIO(rendered.image)).size == (240, 440)
        assert rendered.fold == ((150 - render_module.FOLD_CLEARANCE_PX) * 2 - 180) / 440

    async def test_the_paper_share_counts_a_faint_shadow_the_trim_keeps(
        self, page: FakePage
    ) -> None:
        image = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 200, 299, 599), fill=(250, 250, 250, 255))
        draw.rectangle((100, 600, 299, 649), fill=(0, 0, 0, render_module.TRIM_ALPHA_THRESHOLD + 1))
        out = io.BytesIO()
        image.save(out, format="PNG")
        page._image = out.getvalue()
        page.paper_boxes["#paper"] = [50.0, 100.0, 150.0, 300.0]

        rendered = await render_html_to_image(
            "<p/>", ImageRenderOptions(trim_margin_px=10, paper_selector="#paper")
        )

        assert Image.open(io.BytesIO(rendered.image)).size == (240, 490)
        assert rendered.paper == (20 / 240, 20 / 490, 220 / 240, 420 / 490)
