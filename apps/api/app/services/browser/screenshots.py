"""Upload browser step screenshots to Cloudflare R2 and return public URLs.

Step frames are display-only progress artifacts that can show the user's
logged-in pages, so they must never be persisted as base64 in the conversation
document (Mongo bloat). Each frame is uploaded to a Cloudflare R2 bucket and
referenced by its public r2.dev URL — the only thing persisted in ``tool_data``.
R2 is on Cloudflare's edge and free-tier (unlike Cloudflare Images, which needs a
paid plan); the per-step upload was the browser loop's biggest tax on the old
Cloudinary path, and it now runs off that critical path (see runner ``_emit_step``).
Reused by web and bots alike (both just render the URL).

Best-effort: if R2 is unconfigured or the upload fails, returns ``None`` so the
caller degrades to an inline data URL (dev) rather than failing the run.
"""

import asyncio
from functools import lru_cache
from typing import Protocol, cast

import boto3
from botocore.config import Config

from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_UPLOAD_TIMEOUT_SECONDS = 15


class _S3Putter(Protocol):
    """The one boto3 S3 method we use (its clients are dynamically generated and
    have no static type, so we narrow to exactly what we call)."""

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


def _put(png: bytes, key: str) -> None:
    _r2_client().put_object(Bucket=settings.R2_BUCKET, Key=key, Body=png, ContentType="image/png")


async def upload_step_screenshot(png: bytes, conversation_id: str, index: int) -> str | None:
    """Upload one step screenshot to R2; return its public URL or None."""
    if not _r2_configured():
        return None
    key = f"browser_steps/{conversation_id}/step_{index}.png"
    try:
        # boto3 is blocking — run it off the event loop.
        await asyncio.to_thread(_put, png, key)
    except Exception as exc:  # a screenshot is non-essential progress
        log.warning(
            f"{LogTag.BROWSER} Browser screenshot upload failed; using inline fallback",
            error_type=type(exc).__name__,
        )
        return None
    base = (settings.R2_PUBLIC_BASE_URL or "").rstrip("/")  # guaranteed set by _r2_configured
    return f"{base}/{key}"
