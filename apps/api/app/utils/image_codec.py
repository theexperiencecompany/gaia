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

from PIL import Image

from app.constants.media import (
    DOWNSCALE_LONGEST_EDGE,
    IMAGE_EXTENSION_BY_MIME,
    IMAGE_MIME_BY_EXTENSION,
    MAX_IMAGE_FILE_BYTES,
    MAX_IMAGE_PIXELS,
    MIME_BY_PILLOW_FORMAT,
    PROVIDER_SAFE_IMAGE_MIMES,
    TARGET_INLINE_IMAGE_BYTES,
    TRANSCODE_FORMAT,
    TRANSCODE_MIME,
    TRANSCODE_QUALITY_STEPS,
)
from app.utils.multimodal import ContentBlock, image_content_block

# base64 encodes 3 bytes as 4 chars; used to reject an oversized payload before
# allocating the decoded copy of it.
_BASE64_EXPANSION = 4 / 3


class InvalidImageError(ValueError):
    """Data that is not a decodable image, or that busts the inline size budget."""


@dataclass(frozen=True, slots=True)
class InlineImage:
    """An image that has been validated and fitted to the inline budget."""

    data: bytes
    base64: str
    mime_type: str

    @property
    def extension(self) -> str:
        return IMAGE_EXTENSION_BY_MIME[self.mime_type]

    def to_block(self) -> ContentBlock:
        return image_content_block(self.base64, self.mime_type)


class ImageCodec:
    """Turns raw image bytes into an ``InlineImage`` a provider will accept."""

    @staticmethod
    def mime_for_path(path: str) -> str | None:
        """MIME for a supported image extension, or None if this isn't an image."""
        return IMAGE_MIME_BY_EXTENSION.get(PurePosixPath(path).suffix.lower())

    @classmethod
    async def from_bytes(cls, data: bytes) -> InlineImage:
        """Fit raw image bytes to the inline budget. Raises ``InvalidImageError``."""
        return await asyncio.to_thread(cls._fit, data)

    @classmethod
    async def from_base64(cls, data_b64: str) -> InlineImage:
        """Fit already-base64-encoded image data (MCP tool results, the bridge).

        The encoded length is checked before decoding, so a hostile or buggy server
        cannot make us materialize a 200 MB payload in memory.
        """
        if len(data_b64) > MAX_IMAGE_FILE_BYTES * _BASE64_EXPANSION:
            raise InvalidImageError(f"image exceeds the {MAX_IMAGE_FILE_BYTES}-byte inline limit")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise InvalidImageError(f"image data is not valid base64: {exc}") from exc
        return await cls.from_bytes(data)

    @classmethod
    def _fit(cls, data: bytes) -> InlineImage:
        """Validate and, when needed, re-encode. CPU-bound — runs in a thread."""
        if len(data) > MAX_IMAGE_FILE_BYTES:
            raise InvalidImageError(
                f"image is {len(data)} bytes; exceeds the {MAX_IMAGE_FILE_BYTES}-byte inline limit"
            )
        mime_type, (width, height) = cls._probe(data)
        if width * height > MAX_IMAGE_PIXELS:
            raise InvalidImageError(
                f"image is {width}x{height} ({width * height} pixels); "
                f"exceeds the {MAX_IMAGE_PIXELS}-pixel inline limit"
            )

        # Bytes and pixels are separate budgets, and either one alone can blow up
        # a request: providers bill images by pixel area, so a flat 8000x8000 PNG
        # that zips down to 200 KB is still enormous once tiled.
        safe_mime = mime_type if mime_type in PROVIDER_SAFE_IMAGE_MIMES else None
        if (
            safe_mime is not None
            and len(data) <= TARGET_INLINE_IMAGE_BYTES
            and max(width, height) <= DOWNSCALE_LONGEST_EDGE
        ):
            return cls._encode(data, safe_mime)
        return cls._encode(cls._transcode(data), TRANSCODE_MIME)

    @staticmethod
    def _probe(data: bytes) -> tuple[str | None, tuple[int, int]]:
        """The sniffed MIME and dimensions of a real image. Raises ``InvalidImageError``.

        The MIME comes off the decoded header, never from the caller — a file
        extension and an MCP server's declared ``mimeType`` can both lie, and a block
        whose mime_type contradicts its payload is rejected outright by the provider
        (Gemini 400s on `inline_data`). ``None`` means a format with no safe MIME.
        """
        try:
            with Image.open(BytesIO(data)) as image:
                sniffed = MIME_BY_PILLOW_FORMAT.get(image.format or "")
                size = image.size
                image.verify()  # invalidates `image` — read anything else first
        except (OSError, Image.DecompressionBombError) as exc:
            raise InvalidImageError(f"not a decodable image: {exc}") from exc
        return sniffed, size

    @staticmethod
    def _transcode(data: bytes) -> bytes:
        """Downscale and re-encode as JPEG under the inline byte budget.

        Animated formats keep frame one. Quality steps down until the payload fits
        ``TARGET_INLINE_IMAGE_BYTES`` — a dense 1568px image can still exceed it at
        full quality, and that payload is persisted in every checkpoint. The last
        step is the floor: it ships even if still over budget, rather than failing
        the turn over an unusually dense image.
        """
        try:
            image = Image.open(BytesIO(data)).convert("RGB")
            image.thumbnail(
                (DOWNSCALE_LONGEST_EDGE, DOWNSCALE_LONGEST_EDGE), Image.Resampling.LANCZOS
            )
        except (OSError, Image.DecompressionBombError) as exc:
            # `verify()` in `_probe` only reads the header — a truncated or
            # corrupt file gets past it and blows up here, on the full decode.
            raise InvalidImageError(f"image could not be re-encoded: {exc}") from exc

        encoded = b""
        for quality in TRANSCODE_QUALITY_STEPS:
            output = BytesIO()
            image.save(output, format=TRANSCODE_FORMAT, optimize=True, quality=quality)
            encoded = output.getvalue()
            if len(encoded) <= TARGET_INLINE_IMAGE_BYTES:
                break
        return encoded

    @staticmethod
    def _encode(data: bytes, mime_type: str) -> InlineImage:
        return InlineImage(
            data=data,
            base64=base64.b64encode(data).decode("ascii"),
            mime_type=mime_type,
        )
