"""Unit tests for app.utils.multimodal.

These helpers are the only thing standing between a base64 image block and a
logger, an SSE stream, a Mongo document, or a char-based token estimate. Every
test here is really asking one question: can megabytes of base64 get through?
"""

from app.constants.media import MEDIA_BLOCK_TOKEN_ESTIMATE
from app.utils.multimodal import (
    approx_content_chars,
    extract_text_content,
    has_media_blocks,
    image_content_block,
    is_media_block,
    media_blocks,
    text_content_block,
)

BIG_B64 = "QUJDRA" * 20_000
IMAGE = {"type": "image", "base64": BIG_B64, "mime_type": "image/png"}
TEXT = {"type": "text", "text": "Image file shot.png"}


class TestExtractTextContent:
    def test_media_base64_never_survives_extraction(self):
        """The core guarantee. If this leaks, it leaks to the browser and Mongo."""
        result = extract_text_content([TEXT, IMAGE])

        assert result == "Image file shot.png"
        assert BIG_B64 not in result
        assert "base64" not in result

    def test_media_only_content_yields_empty_string_not_a_repr(self):
        """A bridge read_file returns an image with no text sibling. The old
        `str(content)` produced the whole dict repr, base64 and all."""
        assert extract_text_content([IMAGE]) == ""

    def test_plain_string_passes_through(self):
        assert extract_text_content("hello") == "hello"

    def test_empty_list_is_empty_string(self):
        assert extract_text_content([]) == ""

    def test_non_string_non_list_stringifies(self):
        assert extract_text_content(42) == "42"

    def test_bare_strings_inside_the_block_list_are_kept(self):
        assert "loose" in extract_text_content(["loose", TEXT])

    def test_text_block_missing_its_text_key_does_not_raise(self):
        assert extract_text_content([{"type": "text"}]) == ""

    def test_unknown_block_types_are_dropped_rather_than_repr_ed(self):
        """A future block type must not start leaking its dict into logs."""
        result = extract_text_content([TEXT, {"type": "audio", "base64": BIG_B64}])

        assert result == "Image file shot.png"
        assert BIG_B64 not in result


class TestMediaBlockDetection:
    def test_image_block_is_media(self):
        assert is_media_block(IMAGE) is True

    def test_text_block_is_not_media(self):
        assert is_media_block(TEXT) is False

    def test_non_dict_is_not_media(self):
        assert is_media_block("just a string") is False

    def test_has_media_blocks_on_a_plain_string_is_false(self):
        """Compaction calls this on every tool result; most are plain strings."""
        assert has_media_blocks("a normal tool output") is False

    def test_has_media_blocks_on_a_text_only_block_list_is_false(self):
        """A text-only block list must still be compactable — it is not media."""
        assert has_media_blocks([TEXT, TEXT]) is False

    def test_has_media_blocks_finds_an_image_buried_after_text(self):
        assert has_media_blocks([TEXT, TEXT, IMAGE]) is True

    def test_media_blocks_preserves_order_and_returns_the_real_blocks(self):
        second = {"type": "image", "base64": "WYZ", "mime_type": "image/jpeg"}

        assert media_blocks([TEXT, IMAGE, TEXT, second]) == [IMAGE, second]

    def test_media_blocks_on_non_list_content_is_empty(self):
        assert media_blocks("string content") == []


class TestApproxContentChars:
    def test_media_block_is_charged_a_flat_cost_not_its_base64_length(self):
        """A 1 MB image is ~1.4M base64 chars. Charged literally, one screenshot
        reads as a near-full context window and triggers compaction immediately."""
        charged = approx_content_chars([IMAGE])

        assert charged == MEDIA_BLOCK_TOKEN_ESTIMATE * 4
        assert charged < len(BIG_B64)

    def test_plain_string_is_charged_its_real_length(self):
        assert approx_content_chars("hello") == 5

    def test_text_blocks_still_contribute_their_size(self):
        """The flat media charge must not make the estimator blind to real text."""
        small = approx_content_chars([{"type": "text", "text": "hi"}])
        large = approx_content_chars([{"type": "text", "text": "x" * 5000}])

        assert large > small

    def test_mixed_content_charges_text_and_media_separately(self):
        text_only = approx_content_chars([TEXT])
        with_image = approx_content_chars([TEXT, IMAGE])

        assert with_image == text_only + MEDIA_BLOCK_TOKEN_ESTIMATE * 4


class TestBlockConstructors:
    def test_image_content_block_shape(self):
        assert image_content_block("QUJD", "image/png") == {
            "type": "image",
            "base64": "QUJD",
            "mime_type": "image/png",
        }

    def test_image_content_block_is_recognized_as_media_by_langchain(self):
        """The constructor and the detector must agree, or the adapter goes blind."""
        assert is_media_block(image_content_block("QUJD", "image/png")) is True

    def test_text_content_block_shape(self):
        assert text_content_block("hi") == {"type": "text", "text": "hi"}

    def test_text_content_block_is_not_media(self):
        assert is_media_block(text_content_block("hi")) is False
