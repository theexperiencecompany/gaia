"""Convert inline media in ToolMessage content for the OpenRouter lane.

`langchain_openrouter._convert_message_to_dict` runs `_format_message_content`
on HumanMessage content — turning a canonical `{"type": "image", "base64": ...}`
block into the `image_url` data-URL part the wire expects — but passes
ToolMessage content through untouched. So a tool that returns an image dies in
the OpenRouter SDK's own pydantic validation, before any request is sent:

    Input tag 'image' does not match any of the expected tags:
    'file', 'image_url', 'input_audio', 'input_video', 'text', 'video_url'

OpenRouter itself accepts media in a tool message — its OpenAPI spec types
`ChatToolMessage.content` as `str | List[ChatContentItems]`, the same union the
user role gets, and models do perceive images delivered that way. Only the
client-side conversion is missing, so this reuses the library's own formatter
rather than reimplementing the block mapping.

Unreported upstream as of 0.2.6 (`_convert_message_to_dict` is identical on
master). Drop this patch once the library formats tool content itself; the
import will fail loudly if either private name goes away.
"""

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openrouter import chat_models

_original_convert_message_to_dict = chat_models._convert_message_to_dict


def _convert_message_to_dict(message: BaseMessage) -> dict[str, Any]:
    message_dict = _original_convert_message_to_dict(message)
    if message_dict.get("role") == "tool":
        # Plain-string content (the overwhelming majority of tool results) is
        # returned unchanged — `_format_message_content` only rewrites lists.
        message_dict["content"] = chat_models._format_message_content(message_dict["content"])
    return message_dict


def apply() -> None:
    """Rebind the module-level name `_create_message_dicts` resolves at call time."""
    chat_models._convert_message_to_dict = _convert_message_to_dict


apply()
