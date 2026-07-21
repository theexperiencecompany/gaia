"""Upload browser step screenshots to the CDN and return access-controlled URLs.

Step frames are display-only progress artifacts that can show the user's
logged-in pages (email, bank, checkout), so they must never be persisted as
base64 in the conversation document (Mongo bloat) nor served from a public,
guessable URL. Each frame is uploaded to Cloudinary as an ``authenticated``
asset and referenced by a *signed* URL — the only thing persisted in
``tool_data``. Reused by web and bots alike (both just render the URL).

Best-effort: if Cloudinary is unconfigured or the upload fails, returns ``None``
so the caller degrades to an inline data URL (dev) rather than failing the run.
"""

import asyncio
import io

import cloudinary.uploader
from cloudinary.utils import cloudinary_url

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_SCREENSHOT_FOLDER = "browser_steps"


def _upload_and_sign(png: bytes, public_id: str) -> str:
    cloudinary.uploader.upload(
        io.BytesIO(png),
        resource_type="image",
        type="authenticated",
        public_id=public_id,
        folder=_SCREENSHOT_FOLDER,
        overwrite=True,
    )
    url, _ = cloudinary_url(
        f"{_SCREENSHOT_FOLDER}/{public_id}",
        resource_type="image",
        type="authenticated",
        sign_url=True,
        secure=True,
    )
    return url


async def upload_step_screenshot(png: bytes, conversation_id: str, index: int) -> str | None:
    """Upload one step screenshot; return a signed, access-controlled URL or None."""
    public_id = f"{conversation_id}/step_{index}"
    try:
        return await asyncio.to_thread(_upload_and_sign, png, public_id)
    except Exception as exc:  # noqa: BLE001 — a screenshot is non-essential progress
        log.warning(
            f"{LogTag.AGENT} Browser screenshot upload failed; using inline fallback: {exc}"
        )
        return None
