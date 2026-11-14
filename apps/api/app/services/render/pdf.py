"""Print a web page to an A4 PDF with headless Chromium."""

import asyncio
import io

from pypdf import PdfReader

from app.constants.openui_artifacts import PDF_RENDER_MAX_CONCURRENT, PDF_RENDER_MAX_WAITING
from app.services.render.chromium import chromium_browser
from app.utils.errors import AppError

# A4 at 96 dpi, so charts lay out at the width they print at.
_A4_WIDTH_PX = 794
_A4_HEIGHT_PX = 1123
_PAGE_TIMEOUT_MS = 45_000
# Charts measure and draw a frame after the program renders; let them settle.
_CHART_SETTLE_MS = 600


class RenderBusyError(AppError):
    """Every render slot is taken and the waiting line is full."""


class _RenderGate:
    """At most PDF_RENDER_MAX_CONCURRENT renders run and PDF_RENDER_MAX_WAITING wait; the rest are refused."""

    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(PDF_RENDER_MAX_CONCURRENT)
        self._waiting = 0

    async def __aenter__(self) -> None:
        if self._slots.locked():
            if self._waiting >= PDF_RENDER_MAX_WAITING:
                raise RenderBusyError(
                    message="too many PDF exports are running",
                    fix="try again in a minute",
                    status_code=429,
                )
            self._waiting += 1
            try:
                await self._slots.acquire()
            finally:
                self._waiting -= 1
        else:
            await self._slots.acquire()

    async def __aexit__(self, *_: object) -> None:
        self._slots.release()


_gate = _RenderGate()


async def render_url_to_pdf(
    url: str, ready_selector: str, init_script: str | None = None
) -> tuple[bytes, int]:
    """Load url (running init_script first), wait for ready_selector, print it.

    Returns the PDF bytes and page count.

    Raises:
        RuntimeError: A script on the page threw.
    """
    async with _gate, chromium_browser() as browser:
        page = await browser.new_page(viewport={"width": _A4_WIDTH_PX, "height": _A4_HEIGHT_PX})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        if init_script is not None:
            await page.add_init_script(init_script)
        await page.goto(url, wait_until="networkidle", timeout=_PAGE_TIMEOUT_MS)
        await page.wait_for_selector(ready_selector, state="attached", timeout=_PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(_CHART_SETTLE_MS)
        if page_errors:
            raise RuntimeError(f"Page script failed while printing: {page_errors[0]}")
        pdf = await page.pdf(format="A4", print_background=True)
    return pdf, len(PdfReader(io.BytesIO(pdf)).pages)
