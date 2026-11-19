"""Build the daily edition thumbnails the Briefing settings grid shows into apps/web/public.

Renders each daily family with the dev seed's first day through the delivery renderer,
keeps the top of the page at the card's 3:4 shape, and writes a small WebP per family.
Re-run when an edition's design or the family list changes.

Usage (from apps/api)::

    uv run python scripts/build_edition_thumbnails.py
"""

import asyncio
import io
import os
from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))
os.chdir(API_ROOT)

from PIL import Image
import tests.offline_env  # noqa: F401 -- must run before any app import

from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.dev_postmarks_seed import sample_edition_payload

OUT = API_ROOT.parent / "web/public/images/briefing/editions"
THUMB_WIDTH_PX = 360
# The settings card's shape: width / height.
THUMB_ASPECT = 3 / 4
WEBP_QUALITY = 80
RECIPIENT = "Alex"
# What the sample's QR and barcodes encode: a real brief encodes its own link.
SAMPLE_LINK = "https://heygaia.io"


def thumbnail(png: bytes) -> bytes:
    """Crop the page's top to the card's shape and shrink it to the thumbnail width."""
    page = Image.open(io.BytesIO(png))
    top = page.crop((0, 0, page.width, min(page.height, round(page.width / THUMB_ASPECT))))
    small = top.resize((THUMB_WIDTH_PX, round(THUMB_WIDTH_PX * top.height / top.width)))
    out = io.BytesIO()
    small.save(out, "WEBP", quality=WEBP_QUALITY, method=6)
    return out.getvalue()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    families = sorted(DAILY_FAMILY_WEIGHTS)
    for stale in set(OUT.glob("*.webp")) - {OUT / f"{family}.webp" for family in families}:
        stale.unlink()
    for family in families:
        payload = sample_edition_payload(family, RECIPIENT)
        payload.link = SAMPLE_LINK
        rendered = await render_edition_png(payload)
        (OUT / f"{family}.webp").write_bytes(thumbnail(rendered.image))
        print(f"{family}.webp")


if __name__ == "__main__":
    asyncio.run(main())
