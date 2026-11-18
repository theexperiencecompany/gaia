"""Build the Briefing settings grid's edition images into apps/web/public.

Renders each daily family through the delivery renderer twice: the dev seed's first day,
cropped to the card's 3:4 top as a small thumbnail, and the busy composition (lead,
needs-you, done, calendar, chart, quote, note) whole, as the full-size demo the card opens.
Re-run when an edition's design or the family list changes.

Usage (from apps/api)::

    LOG_LEVEL=ERROR PYTHONPATH=. uv run --group backend --group dev python scripts/build_edition_thumbnails.py
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
from tests import offline_env  # noqa: F401 -- must run before any app import
from tests.integration.brief_compositions import composed_payload

from app.models.brief_payload_models import BriefingPayload
from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.dev_postmarks_seed import sample_edition_payload

OUT = API_ROOT.parent / "web/public/images/briefing/editions"
DEMO_OUT = OUT / "demo"
DEMO_COMPOSITION = "busy"
THUMB_WIDTH_PX = 360
# Twice the 572px column the demo opens into, so it stays sharp on a retina screen.
DEMO_WIDTH_PX = 1144
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


def demo(png: bytes) -> bytes:
    """Shrink the whole page to the demo width, keeping its transparent desk."""
    page = Image.open(io.BytesIO(png))
    width = min(DEMO_WIDTH_PX, page.width)
    whole = page.resize((width, round(width * page.height / page.width)))
    out = io.BytesIO()
    whole.save(out, "WEBP", quality=WEBP_QUALITY, method=6)
    return out.getvalue()


def demo_payload(family: str) -> BriefingPayload:
    """Return the busy composition in family, wearing the sample's stamp or painting and day hue."""
    sample = sample_edition_payload(family, RECIPIENT)
    return composed_payload(DEMO_COMPOSITION, family, sample.artwork_id).model_copy(
        update={
            "stamp_city": sample.stamp_city,
            "hue": sample.hue,
            "recipient_name": RECIPIENT,
            "link": SAMPLE_LINK,
        }
    )


def drop_stale(directory: Path, families: list[str]) -> None:
    """Delete images for families that no longer exist."""
    for stale in set(directory.glob("*.webp")) - {directory / f"{f}.webp" for f in families}:
        stale.unlink()


async def main() -> None:
    DEMO_OUT.mkdir(parents=True, exist_ok=True)
    families = sorted(DAILY_FAMILY_WEIGHTS)
    drop_stale(OUT, families)
    drop_stale(DEMO_OUT, families)
    for family in families:
        payload = sample_edition_payload(family, RECIPIENT).model_copy(update={"link": SAMPLE_LINK})
        rendered = await render_edition_png(payload)
        (OUT / f"{family}.webp").write_bytes(thumbnail(rendered.image))
        shown = await render_edition_png(demo_payload(family))
        (DEMO_OUT / f"{family}.webp").write_bytes(demo(shown.image))
        print(f"{family}.webp")


if __name__ == "__main__":
    asyncio.run(main())
