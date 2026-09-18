"""Publish a browser step screenshot and return the URL that serves it back.

Step frames are display-only progress artifacts that can show the user's
logged-in pages, so they must never be persisted as base64 in the conversation
document (Mongo bloat). With credentials they go to a Cloudflare R2 bucket and
are referenced by their public URL, which is the only thing persisted; R2 is on
Cloudflare's edge and free-tier, and the upload runs off the browser loop's
critical path (see runner _emit_step). Without credentials they go to local disk
and are served back through a short code (see shot_store), so a run with no
object store still produces real URLs for web and bots alike.

Best-effort throughout: a failed upload falls back to disk, and only a failed
local write returns None, leaving the caller to degrade to an inline data URL
rather than failing the run.
"""

import asyncio
from functools import lru_cache
from typing import Protocol, cast

import boto3
from botocore.config import Config

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.services.browser.shot_store import store_step_screenshot
from shared.py.wide_events import log

_UPLOAD_TIMEOUT_SECONDS = 15


class _S3Putter(Protocol):
    """The one boto3 S3 method we use (its clients are dynamically generated and have no static type, so we narrow to exactly what we call)."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object: ...


def _r2_configured() -> bool:
    return bool(
        settings.CLOUDFLARE_ACCOUNT_ID
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_PUBLIC_BASE_URL
    )


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
    # Browser-Use captures PNG, and a frame stored under the wrong type is also
    # *served* under it, so the type is stated once here rather than passed in.
    _r2_client().put_object(Bucket=settings.R2_BUCKET, Key=key, Body=image, ContentType="image/png")


async def publish_step_screenshot(png: bytes, conversation_id: str, index: int) -> str | None:
    """Publish one step screenshot and return the URL that serves it, or None."""
    if not _r2_configured():
        return await _store_locally(png, conversation_id, index)
    key = f"browser_steps/{conversation_id}/step_{index}.png"
    try:
        # boto3 is blocking — run it off the event loop.
        await asyncio.to_thread(_put, png, key)
    except Exception as exc:  # a screenshot is non-essential progress
        log.warning(
            f"{LogTag.BROWSER} Browser screenshot upload failed; storing it locally instead",
            error_type=type(exc).__name__,
        )
        return await _store_locally(png, conversation_id, index)
    base = (settings.R2_PUBLIC_BASE_URL or "").rstrip("/")  # guaranteed set by _r2_configured
    return f"{base}/{key}"


async def _store_locally(png: bytes, conversation_id: str, index: int) -> str | None:
    """Keep the frame on this host, or None when even that fails."""
    try:
        return await store_step_screenshot(png, conversation_id, index)
    except OSError as exc:
        log.warning(
            f"{LogTag.BROWSER} Browser screenshot could not be stored; using inline fallback",
            error_type=type(exc).__name__,
        )
        return None
