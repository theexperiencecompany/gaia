"""Unit tests for app.utils.image_codec (ImageCodec / InlineImage).

The codec is the single gate every inline image passes through, so its job is to
make a provider request safe: real image, honest MIME, bounded bytes and pixels.
These tests attack exactly that — the declared MIME is assumed hostile, and the
decode is assumed to fail late.
"""

import base64
import io
from typing import Any

from PIL import Image
import pytest

from app.constants.media import (
    DOWNSCALE_LONGEST_EDGE,
    JPEG_MIME,
    MAX_IMAGE_FILE_BYTES,
    PNG_MIME,
    TARGET_INLINE_IMAGE_BYTES,
    WEBP_MIME,
)
from app.utils.image_codec import ImageCodec, InlineImage, InvalidImageError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode(fmt: str, size: tuple[int, int] = (32, 32), color: str = "red", **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _sniff(inline: InlineImage) -> str | None:
    """The format Pillow reads back out of the block's actual payload."""
    return Image.open(io.BytesIO(base64.b64decode(inline.base64))).format


# ---------------------------------------------------------------------------
# The declared MIME is never trusted — the bytes are.
# ---------------------------------------------------------------------------


class TestMimeIsSniffedNotDeclared:
    async def test_png_bytes_are_labelled_png_regardless_of_file_extension(self) -> None:
        """A PNG saved as `photo.jpg` must not be labelled image/jpeg.

        This is the bug: the extension said JPEG, the payload was PNG, and the
        block went to Gemini as inline_data(mime_type=image/jpeg) with PNG bytes.
        Gemini 400s on that, which kills the whole turn — not just the tool.
        """
        assert ImageCodec.mime_for_path("/workspace/photo.jpg") == JPEG_MIME

        inline = await ImageCodec.from_bytes(_encode("PNG"))

        assert inline.mime_type == PNG_MIME
        assert _sniff(inline) == "PNG"

    async def test_declared_mime_cannot_smuggle_a_gif_past_the_provider_safe_set(self) -> None:
        """A lying MCP server declaring a GIF as image/png must still transcode.

        GIF is not in PROVIDER_SAFE_IMAGE_MIMES (Gemini 400s on it). If the
        declared MIME were trusted, `image/png` would wave the GIF straight
        through untouched.
        """
        inline = await ImageCodec.from_base64(base64.b64encode(_encode("GIF")).decode())

        assert inline.mime_type == JPEG_MIME
        assert _sniff(inline) == "JPEG"

    async def test_the_emitted_mime_always_matches_the_emitted_bytes(self) -> None:
        """The block's mime_type and its payload can never disagree."""
        by_mime = {PNG_MIME: "PNG", JPEG_MIME: "JPEG", WEBP_MIME: "WEBP"}
        for fmt in ("PNG", "JPEG", "WEBP", "GIF", "BMP"):
            inline = await ImageCodec.from_bytes(_encode(fmt))
            assert by_mime[inline.mime_type] == _sniff(inline), f"{fmt} produced a mismatched block"

    async def test_provider_safe_formats_pass_through_without_a_needless_transcode(self) -> None:
        """A small in-spec PNG must keep its own bytes — not be re-encoded to JPEG."""
        data = _encode("PNG")
        inline = await ImageCodec.from_bytes(data)

        assert inline.mime_type == PNG_MIME
        assert base64.b64decode(inline.base64) == data

    async def test_a_format_with_no_safe_mime_transcodes_rather_than_emitting_none(self) -> None:
        """BMP decodes but has no provider-safe MIME — it must not ship as-is."""
        inline = await ImageCodec.from_bytes(_encode("BMP"))

        assert inline.mime_type == JPEG_MIME
        assert _sniff(inline) == "JPEG"


# ---------------------------------------------------------------------------
# Late decode failures must arrive as InvalidImageError, not a raw OSError.
# ---------------------------------------------------------------------------


class TestDecodeFailuresAreTyped:
    async def test_truncated_image_on_the_transcode_path_raises_invalid_image(self) -> None:
        """verify() only reads the header; the full decode in _transcode is what fails.

        Callers guard with `except InvalidImageError`. A raw OSError escaping here
        propagates out of the `read` tool and fails the turn. The transcode path
        is the common one — every GIF, and every image over the size/edge budget.
        """
        full = _encode("JPEG", size=(3000, 3000), quality=95)  # oversized -> transcodes
        truncated = full[: len(full) // 2]

        with pytest.raises(InvalidImageError, match="could not be re-encoded"):
            await ImageCodec.from_bytes(truncated)

    async def test_non_image_bytes_raise_invalid_image(self) -> None:
        with pytest.raises(InvalidImageError, match="not a decodable image"):
            await ImageCodec.from_bytes(b"this is not an image, it is prose")

    async def test_empty_bytes_raise_invalid_image(self) -> None:
        with pytest.raises(InvalidImageError):
            await ImageCodec.from_bytes(b"")

    async def test_malformed_base64_raises_invalid_image(self) -> None:
        with pytest.raises(InvalidImageError, match="not valid base64"):
            await ImageCodec.from_base64("!!! not base64 !!!")

    def test_invalid_image_is_catchable_as_value_error(self) -> None:
        """Callers that catch ValueError (read_tool's size guard) must still work."""
        assert issubclass(InvalidImageError, ValueError)


# ---------------------------------------------------------------------------
# Budgets: bytes and pixels are independent, and either alone forces a transcode.
# ---------------------------------------------------------------------------


class TestBudgets:
    async def test_oversized_pixels_are_downscaled_even_when_bytes_are_tiny(self) -> None:
        """A flat 4000x4000 PNG compresses to almost nothing but bills as huge.

        Providers charge by pixel area, so bytes alone is not a sufficient gate.
        """
        data = _encode("PNG", size=(4000, 4000), color="white")
        assert len(data) <= TARGET_INLINE_IMAGE_BYTES, "fixture must be small in bytes"

        inline = await ImageCodec.from_bytes(data)

        width, height = Image.open(io.BytesIO(base64.b64decode(inline.base64))).size
        assert max(width, height) <= DOWNSCALE_LONGEST_EDGE

    async def test_an_image_exactly_at_the_edge_limit_is_not_downscaled(self) -> None:
        """Boundary: `<=` not `<`. Exactly-at-the-limit must pass through."""
        data = _encode("PNG", size=(DOWNSCALE_LONGEST_EDGE, 100), color="white")
        inline = await ImageCodec.from_bytes(data)

        width, _ = Image.open(io.BytesIO(base64.b64decode(inline.base64))).size
        assert width == DOWNSCALE_LONGEST_EDGE
        assert inline.mime_type == PNG_MIME, "in-spec image should not have been transcoded"

    async def test_one_pixel_over_the_edge_limit_is_downscaled(self) -> None:
        data = _encode("PNG", size=(DOWNSCALE_LONGEST_EDGE + 1, 100), color="white")
        inline = await ImageCodec.from_bytes(data)

        width, _ = Image.open(io.BytesIO(base64.b64decode(inline.base64))).size
        assert width <= DOWNSCALE_LONGEST_EDGE
        assert inline.mime_type == JPEG_MIME

    async def test_bytes_over_the_hard_limit_are_refused_before_decoding(self) -> None:
        with pytest.raises(InvalidImageError, match="exceeds"):
            await ImageCodec.from_bytes(b"\x89PNG" + b"\x00" * MAX_IMAGE_FILE_BYTES)

    async def test_oversized_base64_is_refused_without_materializing_the_payload(self) -> None:
        """The encoded length is checked first, so a hostile MCP server can't
        make us allocate the decoded copy of a 200 MB payload."""
        huge_b64 = "A" * (int(MAX_IMAGE_FILE_BYTES * 4 / 3) + 8)

        with pytest.raises(InvalidImageError, match="exceeds"):
            await ImageCodec.from_base64(huge_b64)

    async def test_oversized_bytes_transcode_even_when_the_dimensions_are_in_spec(self) -> None:
        """Bytes and pixels are independent budgets. A 1000x1000 noise PNG is well
        inside the edge limit but ~2.5 MB — it must still be re-encoded, or every
        Postgres checkpoint persists that payload."""
        buf = io.BytesIO()
        Image.effect_noise((1000, 1000), 64).convert("RGB").save(buf, format="PNG")
        data = buf.getvalue()
        assert len(data) > TARGET_INLINE_IMAGE_BYTES, "fixture must bust the byte budget"

        inline = await ImageCodec.from_bytes(data)

        assert inline.mime_type == JPEG_MIME
        assert len(inline.data) <= TARGET_INLINE_IMAGE_BYTES
        assert inline.data == base64.b64decode(inline.base64)


# ---------------------------------------------------------------------------
# Extension gate + block shape
# ---------------------------------------------------------------------------


class TestMimeForPathAndBlock:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/workspace/a.png", PNG_MIME),
            ("/workspace/a.PNG", PNG_MIME),
            ("/workspace/a.jpeg", JPEG_MIME),
            ("/workspace/dir.png/notes.txt", None),
            ("/workspace/archive.tar.gz", None),
            ("/workspace/noext", None),
            # A file literally named ".png" is a dotfile with no extension, so it
            # is not treated as an image — matches PurePosixPath(".png").suffix.
            ("/workspace/.png", None),
        ],
    )
    def test_mime_for_path(self, path: str, expected: str | None) -> None:
        assert ImageCodec.mime_for_path(path) == expected

    async def test_to_block_emits_the_canonical_v1_data_content_block(self) -> None:
        """The block shape is a provider contract — langchain_openrouter converts
        `{"type": "image", "base64": ...}` in a user message to an image_url data
        URL, and Gemini reads it as inline_data. A renamed key breaks both."""
        inline = await ImageCodec.from_bytes(_encode("PNG"))
        block = inline.to_block()

        assert block["type"] == "image"
        assert block["mime_type"] == PNG_MIME
        assert block["base64"] == inline.base64
        assert Image.open(io.BytesIO(base64.b64decode(block["base64"]))).format == "PNG"
