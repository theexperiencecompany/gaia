"""render_url_to_pdf: what it asks the page for, and that a page script failure is loud."""

from contextlib import asynccontextmanager
import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pypdf import PdfWriter
import pytest

from app.services.render.pdf import render_url_to_pdf

_PDF = "app.services.render.pdf"


def _pdf_of(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=10, height=10)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _browser(pdf: bytes, page_error: str | None = None) -> tuple[MagicMock, MagicMock]:
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
    browser = MagicMock()
    browser.new_page = AsyncMock(return_value=page)
    return browser, page


def _launch(browser: MagicMock) -> Any:
    @asynccontextmanager
    async def launched() -> Any:
        yield browser

    return launched


async def test_the_page_is_loaded_awaited_settled_and_printed_as_a_4() -> None:
    browser, page = _browser(_pdf_of(3))
    with patch(f"{_PDF}.chromium_browser", _launch(browser)):
        pdf, pages = await render_url_to_pdf("https://x/print", "#ready", "window.p = 1;")

    assert pages == 3 and pdf.startswith(b"%PDF")
    browser.new_page.assert_awaited_once_with(viewport={"width": 794, "height": 1123})
    page.add_init_script.assert_awaited_once_with("window.p = 1;")
    page.goto.assert_awaited_once_with("https://x/print", wait_until="networkidle", timeout=45_000)
    page.wait_for_selector.assert_awaited_once_with("#ready", state="attached", timeout=45_000)
    page.wait_for_timeout.assert_awaited_once_with(600)
    page.pdf.assert_awaited_once_with(format="A4", print_background=True)


async def test_no_init_script_means_none_is_injected() -> None:
    browser, page = _browser(_pdf_of(1))
    with patch(f"{_PDF}.chromium_browser", _launch(browser)):
        await render_url_to_pdf("https://x/print", "#ready")

    page.add_init_script.assert_not_awaited()


async def test_a_script_that_threw_on_the_page_fails_the_print() -> None:
    browser, page = _browser(_pdf_of(1), page_error="boom")
    with patch(f"{_PDF}.chromium_browser", _launch(browser)):
        with pytest.raises(RuntimeError, match="Page script failed while printing: boom"):
            await render_url_to_pdf("https://x/print", "#ready")

    page.pdf.assert_not_awaited()
