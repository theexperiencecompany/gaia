#!/usr/bin/env python3
"""One-off: upload the Air Mail city stamps to Cloudinary and record their URLs.

Reads the founder's ``N_<slug>.png`` stamp artworks from ``--source``, converts
each to a ~600px WebP (keeping the transparent perforated edge), uploads it to
Cloudinary under ``briefing/stamps/<slug>``, and writes the returned URL into
``app/services/briefing/editions/explorer/assets/stamps/cities.json`` — the only
stamp file the repo carries. Every city in the catalogue must have a source
image. Idempotent: each city uploads to a fixed public id with overwrite, and
the recorded URL is versionless, so a re-run replaces the same assets and
leaves cities.json unchanged.

Needs CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET.

Run: uv run python -m scripts.upload_city_stamps --source "<stamps folder>"
"""

import argparse
import asyncio
import io
import json
from pathlib import Path
import re

from PIL import Image

from app.config.cloudinary import init_cloudinary
from app.config.settings import settings
from app.core.lazy_loader import providers
from app.services.upload_service import upload_file_to_cloudinary

_CATALOGUE = (
    Path(__file__).resolve().parents[1]
    / "app/services/briefing/editions/explorer/assets/stamps/cities.json"
)
_PUBLIC_ID_PREFIX = "briefing/stamps"
_WIDTH_PX = 600
_WEBP_QUALITY = 80
# Cloudinary stamps a fresh /v<timestamp>/ on every upload; the asset is the
# public id, so the recorded URL drops it to stay stable across re-runs.
_VERSION_SEGMENT = re.compile(r"/upload/v\d+/")


def _webp(png: Path) -> bytes:
    image = Image.open(png).convert("RGBA")
    height = round(image.height * _WIDTH_PX / image.width)
    out = io.BytesIO()
    image.resize((_WIDTH_PX, height), Image.LANCZOS).save(
        out, "WEBP", quality=_WEBP_QUALITY, method=6
    )
    return out.getvalue()


def _sources(source: Path) -> dict[str, Path]:
    """``N_<slug>.png`` files keyed by slug."""
    return {png.stem.split("_", 1)[1]: png for png in source.glob("*_*.png")}


async def upload(source: Path) -> None:
    if not (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        raise SystemExit("Cloudinary credentials are not configured")
    init_cloudinary()
    await providers.aget("cloudinary")

    rows = json.loads(_CATALOGUE.read_text())
    sources = _sources(source)
    missing = [row["slug"] for row in rows if row["slug"] not in sources]
    if missing:
        raise SystemExit(f"No source image for: {', '.join(missing)}")

    for done, row in enumerate(rows, start=1):
        data = _webp(sources[row["slug"]])
        uploaded = await asyncio.to_thread(
            upload_file_to_cloudinary, f"{_PUBLIC_ID_PREFIX}/{row['slug']}", file_data=data
        )
        row["url"] = _VERSION_SEGMENT.sub("/upload/", uploaded)
        print(f"  {done}/{len(rows)} {row['slug']}: {len(data) // 1024} KB -> {row['url']}")

    _CATALOGUE.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(rows)} URLs to {_CATALOGUE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="folder of N_<slug>.png")
    asyncio.run(upload(parser.parse_args().source))


if __name__ == "__main__":
    main()
