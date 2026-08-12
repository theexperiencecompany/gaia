"""Unit tests for MCP tool-result parsing and the SSE tool_result payload.

Two guards live here, both of which failed in review:

- `_tool_result_to_content` replaces mcp_use's `str(tool_result.content)`, which
  leaked pydantic reprs and destroyed images. A `str(item)` fallback for any
  content type it forgets to handle re-opens exactly that hole.
- `_json_safe_tool_result` feeds the MCP-UI iframe. Media blocks are plain dicts,
  so they sail through a naive `json.dumps` serializability probe and ship
  megabytes of base64 into the SSE event.
"""

import base64
import io
from typing import Any

from mcp.types import (
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
)
from PIL import Image

from app.constants.mcp import EMPTY_TOOL_RESULT
from app.constants.media import MAX_MEDIA_BLOCKS_PER_TOOL_RESULT
from app.helpers.agent_helpers import _json_safe_tool_result
from app.services.mcp.langchain_adapter import _tool_result_to_content


def _png_b64(color: str = "red") -> str:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _image(color: str = "red") -> ImageContent:
    return ImageContent(type="image", data=_png_b64(color), mimeType="image/png")


def _text(text: str) -> TextContent:
    return TextContent(type="text", text=text)


def _result(*items: Any) -> CallToolResult:
    return CallToolResult(content=list(items))


class TestToolResultToContent:
    async def test_text_only_result_collapses_to_a_plain_string(self) -> None:
        out = await _tool_result_to_content(_result(_text("line one"), _text("line two")))

        assert out == "line one\nline two"

    async def test_an_embedded_text_resource_yields_its_text_not_a_pydantic_repr(self) -> None:
        """Filesystem and database MCP servers routinely return EmbeddedResource.
        `str(item)` gives `type='resource' resource=TextResourceContents(...)`."""
        embedded = EmbeddedResource(
            type="resource",
            resource=TextResourceContents(uri="file:///a.sql", text="SELECT 1;"),
        )

        out = await _tool_result_to_content(_result(_text("rows: 2"), embedded))

        assert out == "rows: 2\nSELECT 1;"
        assert "TextResourceContents" not in out
        assert "resource=" not in out

    async def test_an_empty_result_says_so_rather_than_returning_nothing(self) -> None:
        """A void MCP action (a delete) legally returns no content. An empty
        ToolMessage tells the model nothing and some providers reject it."""
        assert await _tool_result_to_content(_result()) == EMPTY_TOOL_RESULT

    async def test_an_image_becomes_a_media_block_carrying_real_pixels(self) -> None:
        out = await _tool_result_to_content(_result(_text("here"), _image()))

        assert isinstance(out, list)
        images = [b for b in out if b["type"] == "image"]
        assert len(images) == 1
        assert Image.open(io.BytesIO(base64.b64decode(images[0]["base64"]))).format == "PNG"

    async def test_a_result_carrying_an_image_stays_a_block_list(self) -> None:
        """Collapsing to a string here would destroy the image entirely."""
        out = await _tool_result_to_content(_result(_image()))

        assert isinstance(out, list)

    async def test_images_beyond_the_budget_are_dropped(self) -> None:
        over = MAX_MEDIA_BLOCKS_PER_TOOL_RESULT + 2
        out = await _tool_result_to_content(_result(*[_image() for _ in range(over)]))

        assert len([b for b in out if b["type"] == "image"]) == MAX_MEDIA_BLOCKS_PER_TOOL_RESULT

    async def test_the_dropped_notice_is_emitted_once_with_a_count(self) -> None:
        """One notice per dropped image spams the context with identical lines."""
        over = MAX_MEDIA_BLOCKS_PER_TOOL_RESULT + 3
        out = await _tool_result_to_content(_result(*[_image() for _ in range(over)]))

        notices = [b for b in out if b["type"] == "text"]
        assert len(notices) == 1
        assert "3" in notices[0]["text"]

    async def test_exactly_at_the_budget_nothing_is_dropped(self) -> None:
        at = MAX_MEDIA_BLOCKS_PER_TOOL_RESULT
        out = await _tool_result_to_content(_result(*[_image() for _ in range(at)]))

        assert len([b for b in out if b["type"] == "image"]) == at
        assert not [b for b in out if b["type"] == "text"]

    async def test_an_undecodable_image_degrades_to_a_note_and_keeps_the_text(self) -> None:
        """A hostile or buggy server must not be able to fail the whole tool call
        — the text half of the result is usually what the model needed."""
        broken = ImageContent(type="image", data="!!!not base64!!!", mimeType="image/png")

        out = await _tool_result_to_content(_result(_text("still useful"), broken))

        # The image degrades to a text note, so every block is text and the
        # result collapses to a plain string — no image block survives.
        assert isinstance(out, str)
        assert "still useful" in out
        assert "could not be read" in out


class TestJsonSafeToolResult:
    def test_a_media_block_list_is_stripped_to_its_text(self) -> None:
        """The iframe payload is JSON-serialized into the SSE event. Media blocks
        are plain dicts, so json.dumps happily embeds a megabyte of base64."""
        big = "QUJD" * 50_000
        content = [
            {"type": "text", "text": "Image file shot.png"},
            {"type": "image", "base64": big, "mime_type": "image/png"},
        ]

        out = _json_safe_tool_result(content)

        assert out == "Image file shot.png"
        assert big not in str(out)

    def test_a_plain_string_is_returned_unchanged(self) -> None:
        assert _json_safe_tool_result("some tool output") == "some tool output"

    def test_a_serializable_dict_is_preserved_for_the_iframe(self) -> None:
        """The MCP-UI iframe renders structured data — it must not be flattened."""
        payload = {"rows": [{"id": 1}], "total": 1}

        assert _json_safe_tool_result(payload) == payload

    def test_a_text_only_block_list_is_preserved(self) -> None:
        """No media, so nothing to strip — the iframe still gets its structure."""
        content = [{"type": "text", "text": "hi"}]

        assert _json_safe_tool_result(content) == content

    def test_a_non_serializable_object_is_coerced_rather_than_raising(self) -> None:
        class Weird:
            def __init__(self) -> None:
                self.a = 1

        out = _json_safe_tool_result(Weird())

        assert out == {"a": 1}
