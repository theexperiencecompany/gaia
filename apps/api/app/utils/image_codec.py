"""Decode, validate, and budget-fit images for inline model context.

Every producer of inline media — the workspace `read` tool, MCP tool results,
the device bridge — routes through ``ImageCodec`` before its bytes become a
content block. That makes one place responsible for the guarantees a provider
request depends on: the data is a real image, its MIME is one the provider
accepts, its pixels and bytes are bounded.

Pillow is CPU-bound and holds the GIL, so the public entry points are async and
hop to a thread. Decoding a 10 MB screenshot inline would otherwise freeze every
other request on the worker for the duration.
"""

import asyncio
import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.constants.media import (
    DOWNSCALE_LONGEST_EDGE,
    IMAGE_MIME_BY_EXTENSION,
    MAX_IMAGE_FILE_BYTES,
    PROVIDER_SAFE_IMAGE_MIMES,
    TARGET_INLINE_IMAGE_BYTES,
    TRANSCODE_FORMAT,
    TRANSCODE_MIME,
    TRANSCODE_QUALITY,
)
from app.utils.multimodal import image_content_block

# base64 encodes 3 bytes as 4 chars; used to reject an oversized payload before
# allocating the decoded copy of it.
_BASE64_EXPANSION = 4 / 3


class InvalidImage(ValueError):
    """Data that is not a decodable image, or that busts the inline size budget."""


@dataclass(frozen=True, slots=True)
class InlineImage:
    """An image that has been validated and fitted to the inline budget."""

    base64: str
    mime_type: str
    byte_size: int

    def to_block(self) -> dict[str, Any]:
        return image_content_block(self.base64, self.mime_type)


class ImageCodec:
    """Turns raw image bytes into an ``InlineImage`` a provider will accept."""

    @staticmethod
    def mime_for_path(path: str) -> str | None:
        """MIME for a supported image extension, or None if this isn't an image."""
        return IMAGE_MIME_BY_EXTENSION.get(PurePosixPath(path).suffix.lower())

    @classmethod
    async def from_bytes(cls, data: bytes, mime_type: str) -> InlineImage:
        """Fit raw image bytes to the inline budget. Raises ``InvalidImage``."""
        return await asyncio.to_thread(cls._fit, data, mime_type)

    @classmethod
    async def from_base64(cls, data_b64: str, mime_type: str) -> InlineImage:
        """Fit already-base64-encoded image data (MCP tool results, the bridge).

        The encoded length is checked before decoding, so a hostile or buggy MCP
        server cannot make us materialize a 200 MB payload in memory.
        """
        if len(data_b64) > MAX_IMAGE_FILE_BYTES * _BASE64_EXPANSION:
            raise InvalidImage(f"image exceeds the {MAX_IMAGE_FILE_BYTES}-byte inline limit")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise InvalidImage(f"image data is not valid base64: {exc}") from exc
        return await cls.from_bytes(data, mime_type)

    @classmethod
    def _fit(cls, data: bytes, mime_type: str) -> InlineImage:
        """Validate and, when needed, re-encode. CPU-bound — runs in a thread."""
        if len(data) > MAX_IMAGE_FILE_BYTES:
            raise InvalidImage(
                f"image is {len(data)} bytes; exceeds the {MAX_IMAGE_FILE_BYTES}-byte inline limit"
            )
        width, height = cls._probe(data)

        # Bytes and pixels are separate budgets, and either one alone can blow up
        # a request: providers bill images by pixel area, so a flat 8000x8000 PNG
        # that zips down to 200 KB is still enormous once tiled.
        fits = (
            mime_type in PROVIDER_SAFE_IMAGE_MIMES
            and len(data) <= TARGET_INLINE_IMAGE_BYTES
            and max(width, height) <= DOWNSCALE_LONGEST_EDGE
        )
        if fits:
            return cls._encode(data, mime_type)
        return cls._encode(cls._transcode(data), TRANSCODE_MIME)

    @staticmethod
    def _probe(data: bytes) -> tuple[int, int]:
        """Dimensions of a real image, from its header. Raises ``InvalidImage``."""
        try:
            with Image.open(BytesIO(data)) as image:
                size = image.size
                image.verify()  # invalidates `image` — read anything else first
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise InvalidImage(f"not a decodable image: {exc}") from exc
        return size

    @staticmethod
    def _transcode(data: bytes) -> bytes:
        """Downscale and re-encode as JPEG (animated formats keep frame one)."""
        image = Image.open(BytesIO(data)).convert("RGB")
        image.thumbnail((DOWNSCALE_LONGEST_EDGE, DOWNSCALE_LONGEST_EDGE), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format=TRANSCODE_FORMAT, optimize=True, quality=TRANSCODE_QUALITY)
        return output.getvalue()

    @staticmethod
    def _encode(data: bytes, mime_type: str) -> InlineImage:
        return InlineImage(
            base64=base64.b64encode(data).decode("ascii"),
            mime_type=mime_type,
            byte_size=len(data),
        )
