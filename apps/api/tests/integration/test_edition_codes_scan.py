"""Every QR and barcode on an edition scans to the brief's link.

The codes are decoded from the production render (render_edition_png, headless
Chromium), not from their geometry: they were once seeded pixels that drew a code
and encoded nothing, so only a decoder reading the final PNG can tell. The CDN's
downscale to the delivered width is stood in for by a Lanczos resize.
"""

from __future__ import annotations

import io

from PIL import Image
import pytest
import zxingcpp

from app.constants.briefing import EDITION_DELIVERY_MAX_WIDTH_PX
from app.models.briefing_models import BriefingPayload
from app.services.briefing.edition_email import render_edition_png
from tests.integration.test_edition_families_render import _DAILY

_SHORT_LINK = "https://heygaia.link/aB3dE5gH7jK"
# The fallback when minting fails: the brief's page URL, the longest link a code carries.
_PAGE_URL = "https://heygaia.io/brief/brief_0a1b2c3d4e5f"

# The Boarding Pass's code skin is drawn from the date: these two dates land on each.
_LINEAR_DATE = "2026-10-18"
_STACKED_DATE = "2026-10-14"

_CODES = pytest.mark.parametrize(
    ("family", "date", "symbology"),
    [
        ("invoice", _LINEAR_DATE, zxingcpp.BarcodeFormat.QRCode),
        ("receipt", _LINEAR_DATE, zxingcpp.BarcodeFormat.Code128),
        ("boardingpass", _LINEAR_DATE, zxingcpp.BarcodeFormat.Code128),
        ("boardingpass", _STACKED_DATE, zxingcpp.BarcodeFormat.PDF417),
    ],
    ids=["invoice_qr", "receipt_code128", "boardingpass_linear", "boardingpass_stacked"],
)


async def _render(family: str, link: str, date: str) -> Image.Image:
    payload = BriefingPayload.model_validate(
        {**_DAILY, "date": date, "template_family": family, "link": link}
    )
    rendered = await render_edition_png(payload)
    return Image.open(io.BytesIO(rendered.image))


def _delivered(image: Image.Image) -> Image.Image:
    width = EDITION_DELIVERY_MAX_WIDTH_PX
    return image.resize(
        (width, round(image.height * width / image.width)), Image.Resampling.LANCZOS
    )


def _scan(image: Image.Image) -> list[tuple[zxingcpp.BarcodeFormat, str]]:
    return [(code.format, code.text) for code in zxingcpp.read_barcodes(image)]


@pytest.mark.integration
@_CODES
async def test_edition_code_scans_to_the_short_link_as_delivered(
    family: str, date: str, symbology: zxingcpp.BarcodeFormat
) -> None:
    image = _delivered(await _render(family, _SHORT_LINK, date))
    assert _scan(image) == [(symbology, _SHORT_LINK)]


@pytest.mark.integration
@_CODES
async def test_edition_code_scans_to_the_page_url_when_minting_failed(
    family: str, date: str, symbology: zxingcpp.BarcodeFormat
) -> None:
    """Read at render size: Code 128 squeezes the page URL below a module per delivered pixel."""
    assert _scan(await _render(family, _PAGE_URL, date)) == [(symbology, _PAGE_URL)]
