"""Print a web page to an A4 PDF with headless Chromium."""

import io

from pypdf import PdfReader

from app.constants.openui_artifacts import PDF_RENDER_MAX_WAITING
from app.services.render.chromium import chromium_page, renders_waiting
from app.utils.errors import AppError

# A4 at 96 dpi, so charts lay out at the width they print at.
_A4_WIDTH_PX = 794
_A4_HEIGHT_PX = 1123
_PAGE_TIMEOUT_MS = 45_000
# Charts measure and draw a frame after the program renders; let them settle.
_CHART_SETTLE_MS = 600


class RenderBusyError(AppError):
    """Every render turn is taken and PDF_RENDER_MAX_WAITING renders already wait for one."""


async def render_url_to_pdf(
    url: str, ready_selector: str, init_script: str | None = None
) -> tuple[bytes, int]:
    """Load url (running init_script first), wait for ready_selector, print it.

    Returns the PDF and its page count; a script that threw on the page fails the print.

    Raises:
        RenderBusyError: The line of renders waiting for a turn is full.
    """
    if renders_waiting() >= PDF_RENDER_MAX_WAITING:
        raise RenderBusyError(
            message="too many PDF exports are running",
            fix="try again in a minute",
            status_code=429,
        )
    async with chromium_page({"width": _A4_WIDTH_PX, "height": _A4_HEIGHT_PX}) as rendering:
        page = rendering.page
        if init_script is not None:
            await page.add_init_script(init_script)
        await page.goto(url, wait_until="networkidle", timeout=_PAGE_TIMEOUT_MS)
        await page.wait_for_selector(ready_selector, state="attached", timeout=_PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(_CHART_SETTLE_MS)
        rendering.fail_on_script_errors("printing")
        pdf = await page.pdf(format="A4", print_background=True)
    return pdf, len(PdfReader(io.BytesIO(pdf)).pages)
