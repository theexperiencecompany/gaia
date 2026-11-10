#!/usr/bin/env python3
"""Upload the briefing editions' hosted art to Cloudinary and record the URLs in its catalogue.

stamps: reads the founder's N_<slug>.png Air Mail stamps from --source, converts each
to a ~600px WebP (keeping the transparent perforated edge), uploads it under
briefing/stamps/<slug> and writes its URL into explorer/assets/stamps/cities.json.
Every catalogued city must have a source image; every one is re-uploaded.

artworks: downloads each catalogued Met Open Access work (explorer/assets/artworks/
artworks.json) that has no URL yet, fails unless the Met marks it public domain and
it fits every family it is catalogued for, shrinks it to the smallest size those
frames need at the export's 3x, uploads a WebP under briefing/artworks/<slug> and
records its URL and size.

Idempotent: each asset uploads to a fixed public id with overwrite, and the recorded
URL is versionless, so a re-run leaves the catalogue unchanged.

Needs CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET.

Run: mise infisical -- uv run python -m scripts.upload_briefing_art stamps --source <dir>
     mise infisical -- uv run python -m scripts.upload_briefing_art artworks
"""

import argparse
import asyncio
import io
import json
import math
from pathlib import Path
import re

import httpx
from PIL import Image

from app.config.cloudinary import init_cloudinary
from app.constants.briefing import ArtFamily
from app.constants.files import BlobKind
from app.constants.providers import CLOUDINARY_PROVIDER
from app.core.lazy_loader import providers
from app.services.blob_store import CloudinaryBlobStore
from app.services.briefing.editions.artworks import ART_FRAMES, ARTWORKS_JSON

_STAMPS_JSON = ARTWORKS_JSON.parents[1] / "stamps" / "cities.json"
_STAMP_WIDTH_PX = 600
_WEBP_QUALITY = 82
# Cloudinary stamps a fresh /v<timestamp>/ on every upload; the asset is the
# public id, so the recorded URL drops it to stay stable across re-runs.
_VERSION_SEGMENT = re.compile(r"/upload/v\d+/")
_STORE = CloudinaryBlobStore()
# CloudinaryBlobStore ignores the owner; the brief art belongs to no user.
_OWNER = "briefing"
_MET_OBJECT_API = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{}"
# The Met's CDN refuses httpx's default user agent.
_MET_HEADERS = {"User-Agent": "gaia-briefing-art/1.0"}
_MET_TIMEOUT_SECONDS = 120


def _webp(image: Image.Image, size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    image.resize(size, Image.Resampling.LANCZOS).save(out, "WEBP", quality=_WEBP_QUALITY, method=6)
    return out.getvalue()


async def _host(public_id: str, data: bytes) -> str:
    url = await _STORE.put(
        _OWNER,
        public_id,
        data,
        resource_type="image",
        kind=BlobKind.GENERATED_IMAGE,
        content_type="image/webp",
    )
    return _VERSION_SEGMENT.sub("/upload/", url)


def _write(catalogue: Path, rows: list[dict[str, object]]) -> None:
    catalogue.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(rows)} rows to {catalogue}")


async def _connect() -> None:
    init_cloudinary()
    await providers.aget(CLOUDINARY_PROVIDER)
    _STORE.ensure_ready()


async def upload_stamps(source: Path) -> None:
    await _connect()
    rows = json.loads(_STAMPS_JSON.read_text())
    sources = {png.stem.split("_", 1)[1]: png for png in source.glob("*_*.png")}
    missing = [row["slug"] for row in rows if row["slug"] not in sources]
    if missing:
        raise SystemExit(f"No source image for: {', '.join(missing)}")

    for done, row in enumerate(rows, start=1):
        image = Image.open(sources[row["slug"]]).convert("RGBA")
        height = round(image.height * _STAMP_WIDTH_PX / image.width)
        data = _webp(image, (_STAMP_WIDTH_PX, height))
        row["url"] = await _host(f"briefing/stamps/{row['slug']}", data)
        print(f"  {done}/{len(rows)} {row['slug']}: {len(data) // 1024} KB -> {row['url']}")
    _write(_STAMPS_JSON, rows)


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


async def upload_artworks() -> None:
    await _connect()
    rows = json.loads(ARTWORKS_JSON.read_text())
    pending = [row for row in rows if not row.get("url")]
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
            row["url"] = await _host(f"briefing/artworks/{row['slug']}", data)
            print(f"  {done}/{len(pending)} {row['slug']}: {len(data) // 1024} KB -> {row['url']}")
            _write(ARTWORKS_JSON, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    stamps = commands.add_parser("stamps", help="re-upload every Air Mail city stamp")
    stamps.add_argument("--source", type=Path, required=True, help="folder of N_<slug>.png")
    commands.add_parser("artworks", help="upload every catalogued artwork not hosted yet")
    args = parser.parse_args()
    if args.command == "stamps":
        asyncio.run(upload_stamps(args.source))
    else:
        asyncio.run(upload_artworks())


if __name__ == "__main__":
    main()
