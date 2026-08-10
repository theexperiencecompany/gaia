"""Tests for the OpenRouter ToolMessage media patch.

``langchain_openrouter`` formats media blocks (``{"type": "image", ...}`` →
``image_url``) for user messages but passes ToolMessage content through
untouched, so a tool that returns an image dies in the SDK's pydantic
validation. The patch reuses the library's own formatter for ``role ==
"tool"`` content; plain-string tool content must pass through unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage
from langchain_openrouter import chat_models

# Importing the patch module rebinds _convert_message_to_dict at import time.
import app.patches.openrouter_tool_multimodal_patch as patch_module

_IMAGE_BLOCK = {"type": "image", "base64": "QUJD", "mime_type": "image/png"}
_EXPECTED_IMAGE_URL_BLOCK = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,QUJD"},
}


def _call_wrapper(message_dict: dict) -> dict:
    """Invoke the patched converter with a stubbed original.

    Re-point the captured original at a stub so we exercise the wrapper in
    isolation, then restore it so we don't pollute other tests.
    """
    saved = patch_module._original_convert_message_to_dict
    patch_module._original_convert_message_to_dict = MagicMock(return_value=message_dict)
    try:
        return patch_module._convert_message_to_dict(MagicMock())
    finally:
        patch_module._original_convert_message_to_dict = saved


class TestWrapper:
    def test_string_tool_content_passes_through_unchanged(self) -> None:
        result = _call_wrapper({"role": "tool", "content": "just text"})
        assert result["content"] == "just text"

    def test_image_block_in_tool_message_is_converted_to_image_url(self) -> None:
        result = _call_wrapper({"role": "tool", "content": [_IMAGE_BLOCK]})
        assert result["content"] == [_EXPECTED_IMAGE_URL_BLOCK]

    def test_text_blocks_in_tool_message_are_kept(self) -> None:
        result = _call_wrapper(
            {"role": "tool", "content": [{"type": "text", "text": "see this"}, _IMAGE_BLOCK]}
        )
        assert result["content"] == [
            {"type": "text", "text": "see this"},
            _EXPECTED_IMAGE_URL_BLOCK,
        ]

    def test_non_tool_roles_are_returned_untouched(self) -> None:
        # The user role already gets formatted by the library itself.
        message_dict = {"role": "user", "content": [_IMAGE_BLOCK]}
        assert _call_wrapper(message_dict) == message_dict


class TestRealConversion:
    def test_tool_message_image_reaches_the_wire_format(self) -> None:
        # The end-to-end shape the patch exists to produce: a tool message
        # whose media block survives as the image_url part the SDK accepts.
        tool_msg = ToolMessage(
            content=[{"type": "text", "text": "Image file /workspace/shot.png"}, _IMAGE_BLOCK],
            tool_call_id="call_1",
            name="read",
        )
        converted = chat_models._convert_message_to_dict(tool_msg)
        assert converted["role"] == "tool"
        assert converted["content"][1] == _EXPECTED_IMAGE_URL_BLOCK

    def test_plain_string_tool_message_is_not_touched(self) -> None:
        tool_msg = ToolMessage(content="just text", tool_call_id="call_1")
        converted = chat_models._convert_message_to_dict(tool_msg)
        assert converted["content"] == "just text"


class TestApply:
    def test_library_function_is_rebound_to_the_wrapper(self) -> None:
        assert chat_models._convert_message_to_dict is patch_module._convert_message_to_dict

    def test_apply_keeps_the_rebinding(self) -> None:
        patch_module.apply()
        assert chat_models._convert_message_to_dict is patch_module._convert_message_to_dict
