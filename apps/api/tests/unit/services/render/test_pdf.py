"""render_url_to_pdf: what it asks the page for, and that a page script failure is loud."""

import asyncio
import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pypdf import PdfWriter
import pytest

from app.services.render import chromium as chromium_module, pdf as pdf_module
from app.services.render.pdf import RenderBusyError, render_url_to_pdf
from tests.unit.services.render.conftest import FakeChromium


def _pdf_of(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=10, height=10)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _page(pdf: bytes, page_error: str | None = None) -> MagicMock:
    page = MagicMock()
    page.add_init_script = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.pdf = AsyncMock(return_value=pdf)

    def on(event: str, handler: Any) -> None:
        if event == "pageerror" and page_error is not None:
            handler(page_error)

    page.on = on
    return page


async def test_the_page_is_loaded_awaited_settled_and_printed_as_a_4(
    chromium: FakeChromium,
) -> None:
    page = chromium.page = _page(_pdf_of(3))
    pdf, pages = await render_url_to_pdf("https://x/print", "#ready", "window.p = 1;")

    assert pages == 3 and pdf.startswith(b"%PDF")
    [context] = chromium.browsers[0].contexts
    assert context.options["viewport"] == {"width": 794, "height": 1123}
    page.add_init_script.assert_awaited_once_with("window.p = 1;")
    page.goto.assert_awaited_once_with("https://x/print", wait_until="networkidle", timeout=45_000)
    page.wait_for_selector.assert_awaited_once_with("#ready", state="attached", timeout=45_000)
    page.wait_for_timeout.assert_awaited_once_with(600)
    page.pdf.assert_awaited_once_with(format="A4", print_background=True)


async def test_no_init_script_means_none_is_injected(chromium: FakeChromium) -> None:
    page = chromium.page = _page(_pdf_of(1))
    await render_url_to_pdf("https://x/print", "#ready")

    page.add_init_script.assert_not_awaited()


async def test_a_script_that_threw_on_the_page_fails_the_print(chromium: FakeChromium) -> None:
    page = chromium.page = _page(_pdf_of(1), page_error="boom")
    with pytest.raises(RuntimeError, match="Page script failed while printing: boom"):
        await render_url_to_pdf("https://x/print", "#ready")

    page.pdf.assert_not_awaited()


async def _burst(chromium: FakeChromium, waiting_allowed: int, extra: int) -> tuple[int, int]:
    """Start 1 running + waiting_allowed waiting + extra more renders; return (refused, finished)."""
    release = asyncio.Event()
    page = chromium.page = _page(_pdf_of(1))

    async def slow_goto(*_: Any, **__: Any) -> None:
        await release.wait()

    page.goto = slow_goto
    tasks = [
        asyncio.create_task(render_url_to_pdf("https://x/print", "#ready"))
        for _ in range(1 + waiting_allowed + extra)
    ]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    refused = [r for r in results if isinstance(r, RenderBusyError)]
    assert all(r.status_code == 429 for r in refused)
    assert all(
        (r.message, r.fix) == ("too many PDF exports are running", "try again in a minute")
        for r in refused
    )
    return len(refused), len(results) - len(refused)


@pytest.fixture
def one_turn_two_waiting(monkeypatch: pytest.MonkeyPatch, chromium: FakeChromium) -> FakeChromium:
    monkeypatch.setattr(chromium_module, "CHROMIUM_MAX_CONCURRENT_RENDERS", 1)
    monkeypatch.setattr(chromium_module, "_slots", chromium_module._RenderSlots())
    monkeypatch.setattr(pdf_module, "PDF_RENDER_MAX_WAITING", 2)
    return chromium


async def test_renders_past_the_turns_and_the_waiting_line_are_refused_with_429(
    one_turn_two_waiting: FakeChromium,
) -> None:
    assert await _burst(one_turn_two_waiting, waiting_allowed=2, extra=2) == (2, 3)


async def test_the_waiting_line_empties_as_renders_finish_so_the_next_burst_fits(
    one_turn_two_waiting: FakeChromium,
) -> None:
    assert await _burst(one_turn_two_waiting, waiting_allowed=2, extra=0) == (0, 3)
    assert await _burst(one_turn_two_waiting, waiting_allowed=2, extra=1) == (1, 3)
