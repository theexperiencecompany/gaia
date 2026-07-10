"""Inline-media (image) content-block helpers shared by tools, middleware, and nodes.

The canonical block shape is the LangChain v1 data content block
(``{"type": "image", "base64": ..., "mime_type": ...}``) — the form
``langchain_core.messages.is_data_content_block`` recognizes and
``langchain_google_genai`` converts to real media Parts inside tool results.
"""

from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from langchain_core.messages import is_data_content_block
from PIL import Image

IMAGE_MIME_BY_EXTENSION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Refuse image files larger than this outright (pre-compression).
MAX_IMAGE_FILE_BYTES = 10 * 1024 * 1024
# Re-encode images above this size so the inline base64 payload stays small in
# the provider request and the Postgres checkpointer (which persists the full
# ToolMessage on every checkpoint).
TARGET_INLINE_IMAGE_BYTES = 1 * 1024 * 1024
_DOWNSCALE_LONGEST_EDGE = 1568
_DOWNSCALE_JPEG_QUALITY = 80


def image_mime_from_path(path: str) -> str | None:
    """MIME type for a supported image extension, or None for non-images."""
    return IMAGE_MIME_BY_EXTENSION.get(PurePosixPath(path).suffix.lower())


def fit_image_to_inline_budget(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """Validate ``data`` is a real image and shrink it under the inline budget.

    Small images pass through untouched; oversized ones are downscaled and
    re-encoded as JPEG (animated formats keep only their first frame). Raises
    ``PIL.UnidentifiedImageError``/``OSError`` for corrupt or mislabeled files —
    callers surface that instead of sending junk to the provider.
    """
    Image.open(BytesIO(data)).verify()
    if len(data) <= TARGET_INLINE_IMAGE_BYTES:
        return data, mime_type

    image = Image.open(BytesIO(data)).convert("RGB")
    image.thumbnail((_DOWNSCALE_LONGEST_EDGE, _DOWNSCALE_LONGEST_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="JPEG", optimize=True, quality=_DOWNSCALE_JPEG_QUALITY)
    return output.getvalue(), "image/jpeg"


def image_content_block(base64_data: str, mime_type: str) -> dict[str, Any]:
    """Standard v1 image content block from already-base64-encoded data."""
    return {"type": "image", "base64": base64_data, "mime_type": mime_type}


def has_data_content_blocks(content: Any) -> bool:
    """True when message content is a block list carrying inline media/data."""
    return isinstance(content, list) and any(
        isinstance(block, dict) and is_data_content_block(block) for block in content
    )


def extract_text_content(content: Any) -> str:
    """Extract the text from message content that may be a list of blocks.

    Non-text blocks (inline media, base64 payloads) are dropped so callers that
    log, stream, or ingest text never see megabytes of base64.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return " ".join(text_parts)

    return str(content)
