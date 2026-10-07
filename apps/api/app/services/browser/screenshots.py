"""Publish a browser step screenshot and return the URL that serves it back.

Step frames are display-only progress artifacts that can show the user's
logged-in pages, so they must never be persisted as base64 in the conversation
document (Mongo bloat). With credentials they go to a Cloudflare R2 bucket and
are referenced by their public URL, which is the only thing persisted; R2 is on
Cloudflare's edge and free-tier, and the upload runs off the browser loop's
critical path (see runner _emit_step). Without credentials they go to Redis and
are served back through a short code (see shot_store), so a run with no object
store still produces real URLs for web and bots alike.

Best-effort throughout: a failed upload falls back to Redis, and only a frame
neither took returns None, which leaves the step without a photo rather than
failing the run. Every frame is served as a JPEG; one taken as a PNG (Browser-Use's
own photo of the step's page) is converted here, off the browser loop.
"""

import asyncio
from functools import lru_cache
from io import BytesIO
from time import perf_counter
from typing import Protocol, cast

import boto3
from botocore.config import Config
from PIL import Image

from app.config.settings import settings
from app.constants.browser import BROWSER_STEP_PHOTO_QUALITY
from app.constants.log_tags import LogTag
from app.services.browser.shot_store import SHOT_SUFFIX, store_step_screenshot
from shared.py.wide_events import log

_UPLOAD_TIMEOUT_SECONDS = 15
_CONTENT_TYPE = "image/jpeg"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class _S3Putter(Protocol):
    """The one boto3 S3 method we use (its clients are dynamically generated and have no static type, so we narrow to exactly what we call)."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object: ...


def _r2_public_base() -> str | None:
    """Return the bucket's public base URL, no trailing slash, when every R2 setting is present; else None."""
    base = settings.R2_PUBLIC_BASE_URL
    if not (
        settings.CLOUDFLARE_ACCOUNT_ID
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and base
    ):
        return None
    return base.rstrip("/")


@lru_cache(maxsize=1)
def _r2_client() -> _S3Putter:
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            connect_timeout=_UPLOAD_TIMEOUT_SECONDS,
            read_timeout=_UPLOAD_TIMEOUT_SECONDS,
            retries={"max_attempts": 1},
        ),
    )
    return cast(_S3Putter, client)


def _put(image: bytes, key: str) -> None:
    # A frame stored under the wrong type is also *served* under it.
    _r2_client().put_object(
        Bucket=settings.R2_BUCKET, Key=key, Body=image, ContentType=_CONTENT_TYPE
    )


def _png_to_jpeg(png: bytes) -> bytes:
    with Image.open(BytesIO(png)) as frame:
        jpeg = BytesIO()
        # Equivalent mutant: Pillow upper-cases the format name, so "jpeg" saves the same file.
        frame.convert("RGB").save(
            jpeg,
            format="JPEG",  # pragma: no mutate
            quality=BROWSER_STEP_PHOTO_QUALITY,
        )
    return jpeg.getvalue()


async def publish_step_screenshot(image: bytes, session_id: str, index: int) -> str | None:
    """Publish one step screenshot as a JPEG and return the URL that serves it, or None."""
    jpeg = (
        await asyncio.to_thread(_png_to_jpeg, image) if image.startswith(_PNG_SIGNATURE) else image
    )
    size_bytes = len(jpeg)
    started = perf_counter()
    base = _r2_public_base()
    if base is None:
        url = await store_step_screenshot(jpeg, session_id, index)
        _log_published(index, size_bytes, "redis", url is not None, started)
        return url
    key = f"browser_steps/{session_id}/step_{index}{SHOT_SUFFIX}"
    try:
        # boto3 is blocking — run it off the event loop.
        await asyncio.to_thread(_put, jpeg, key)
    except Exception as exc:  # a screenshot is non-essential progress
        log.warning(
            f"{LogTag.BROWSER} Browser screenshot upload failed; storing it in Redis instead",
            error_type=type(exc).__name__,
            size_bytes=size_bytes,
        )
        url = await store_step_screenshot(jpeg, session_id, index)
        _log_published(index, size_bytes, "redis_fallback", url is not None, started)
        return url
    _log_published(index, size_bytes, "r2", True, started)
    return f"{base}/{key}"


def _log_published(index: int, size_bytes: int, backend: str, ok: bool, started: float) -> None:
    """One real-time line per step frame, and its numbers on the wide event."""
    upload_ms = round((perf_counter() - started) * 1000)
    log.set_ns(
        "browser",
        screenshot_step_index=index,
        screenshot_backend=backend,
        screenshot_bytes=size_bytes,
        screenshot_upload_ms=upload_ms,
        screenshot_published=ok,
    )
    log.info(
        f"{LogTag.BROWSER} Browser screenshot published",
        step_index=index,
        backend=backend,
        size_bytes=size_bytes,
        upload_ms=upload_ms,
        success=ok,
    )
