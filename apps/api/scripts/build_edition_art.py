#!/usr/bin/env python3
"""Write the briefing editions' art into the repo, beside its catalogue, so it ships in the image.

stamps: reads the founder's N_<slug>.png Air Mail stamps from --source and writes each as
a ~600px WebP (keeping the transparent perforated edge) to explorer/assets/stamps/<slug>.webp
and a web-sized copy to stamps/display/<slug>.webp (what GET /briefings/stamps serves).
Every catalogued city in cities.json must have a source image; every one is rewritten.

artworks: downloads each catalogued Met Open Access work (explorer/assets/artworks/
artworks.json) that has no image file yet, fails unless the Met marks it public domain and
it fits every family it is catalogued for, shrinks it to the smallest size those frames need
at the export's 3x, writes it as explorer/assets/artworks/<slug>.webp and records its size.

Run: uv run python -m scripts.build_edition_art stamps --source <dir>
     uv run python -m scripts.build_edition_art stamp-display   (display copies from the full files)
     uv run python -m scripts.build_edition_art artworks
"""

import argparse
import asyncio
import io
import json
import math
from pathlib import Path

import httpx
from PIL import Image

from app.constants.briefing import STAMP_DISPLAY_WIDTH_PX, ArtFamily
from app.services.briefing.editions.artworks import ART_FRAMES, ARTWORKS_JSON
from app.services.briefing.editions.stamps import stamp_catalogue

_STAMPS_DIR = ARTWORKS_JSON.parents[1] / "stamps"
_DISPLAY_DIR = _STAMPS_DIR / "display"
_STAMP_WIDTH_PX = 600
_WEBP_QUALITY = 82
# The display copy is small on screen, so it trades colour and perforation-edge fidelity for bytes.
_DISPLAY_WEBP_QUALITY = 70
_DISPLAY_ALPHA_QUALITY = 30
_MET_OBJECT_API = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{}"
# The Met's CDN refuses httpx's default user agent.
_MET_HEADERS = {"User-Agent": "gaia-briefing-art/1.0"}
_MET_TIMEOUT_SECONDS = 120


def _webp(image: Image.Image, size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    image.resize(size, Image.Resampling.LANCZOS).save(out, "WEBP", quality=_WEBP_QUALITY, method=6)
    return out.getvalue()


def build_stamps(source: Path) -> None:
    sources = {png.stem.split("_", 1)[1]: png for png in source.glob("*_*.png")}
    slugs = list(stamp_catalogue())
    missing = [slug for slug in slugs if slug not in sources]
    if missing:
        raise SystemExit(f"No source image for: {', '.join(missing)}")

    for done, slug in enumerate(slugs, start=1):
        image = Image.open(sources[slug]).convert("RGBA")
        height = round(image.height * _STAMP_WIDTH_PX / image.width)
        data = _webp(image, (_STAMP_WIDTH_PX, height))
        (_STAMPS_DIR / f"{slug}.webp").write_bytes(data)
        display = write_stamp_display(image, slug)
        print(f"  {done}/{len(slugs)} {slug}: {len(data) // 1024} KB, display {display} B")


def write_stamp_display(image: Image.Image, slug: str) -> int:
    """Write the web-sized variant of a stamp and return its size in bytes."""
    height = round(image.height * STAMP_DISPLAY_WIDTH_PX / image.width)
    out = io.BytesIO()
    image.convert("RGBA").resize((STAMP_DISPLAY_WIDTH_PX, height), Image.Resampling.LANCZOS).save(
        out, "WEBP", quality=_DISPLAY_WEBP_QUALITY, alpha_quality=_DISPLAY_ALPHA_QUALITY
    )
    data = out.getvalue()
    _DISPLAY_DIR.mkdir(exist_ok=True)
    (_DISPLAY_DIR / f"{slug}.webp").write_bytes(data)
    return len(data)


def build_stamp_display() -> None:
    for slug in stamp_catalogue():
        write_stamp_display(Image.open(_STAMPS_DIR / f"{slug}.webp"), slug)


def _framed_size(width: int, height: int, families: list[ArtFamily]) -> tuple[int, int]:
    """Return the smallest size that still covers every family's frame at the export scale."""
    scale = max(
        max(frame_w / width, frame_h / height)
        for frame_w, frame_h in (ART_FRAMES[family].min_size_px for family in families)
    )
    if scale > 1:
        raise SystemExit(f"{width}x{height} is too small for {families}; it would upscale")
    return math.ceil(width * scale), math.ceil(height * scale)


async def _met_image(client: httpx.AsyncClient, object_id: int) -> Image.Image:
    record = (await client.get(_MET_OBJECT_API.format(object_id))).raise_for_status().json()
    if not (record["isPublicDomain"] and record["primaryImage"]):
        raise SystemExit(f"Met object {object_id} is not a public-domain image")
    original = (await client.get(record["primaryImage"])).raise_for_status().content
    return Image.open(io.BytesIO(original)).convert("RGB")


async def build_artworks() -> None:
    rows = json.loads(ARTWORKS_JSON.read_text())
    folder = ARTWORKS_JSON.parent
    pending = [row for row in rows if not (folder / f"{row['slug']}.webp").exists()]
    async with httpx.AsyncClient(headers=_MET_HEADERS, timeout=_MET_TIMEOUT_SECONDS) as client:
        for done, row in enumerate(pending, start=1):
            image = await _met_image(client, row["met_object_id"])
            families = [ArtFamily(family) for family in row["families"]]
            unfit = [f for f in families if not ART_FRAMES[f].fits(image.width, image.height)]
            if unfit:
                raise SystemExit(
                    f"{row['slug']} ({image.width}x{image.height}) does not fit {unfit}"
                )
            row["width"], row["height"] = _framed_size(image.width, image.height, families)
            data = _webp(image, (row["width"], row["height"]))
            (folder / f"{row['slug']}.webp").write_bytes(data)
            ARTWORKS_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
            print(f"  {done}/{len(pending)} {row['slug']}: {len(data) // 1024} KB")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    stamps = commands.add_parser("stamps", help="rewrite every Air Mail city stamp")
    stamps.add_argument("--source", type=Path, required=True, help="folder of N_<slug>.png")
    commands.add_parser("stamp-display", help="rewrite every stamp's web-sized copy")
    commands.add_parser("artworks", help="fetch every catalogued artwork with no image yet")
    args = parser.parse_args()
    if args.command == "stamps":
        build_stamps(args.source)
    elif args.command == "stamp-display":
        build_stamp_display()
    else:
        asyncio.run(build_artworks())


if __name__ == "__main__":
    main()
