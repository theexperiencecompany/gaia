"""Convert inline media in ToolMessage content for the OpenRouter lane.

langchain_openrouter formats HumanMessage content (image blocks -> image_url
data-URL parts) but passes ToolMessage content through untouched, so a tool
returning an image fails OpenRouter's own pydantic validation before any
request is sent ("Input tag 'image' does not match any of the expected
tags"). OpenRouter's OpenAPI spec types tool content the same as user content
and does accept media there — only the client-side conversion is missing, so
this reuses the library's own _format_message_content rather than
reimplementing it.

Unreported upstream as of 0.2.6; drop once the library formats tool content
itself. Import fails loudly if either private name goes away.
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
    """Rebind the module-level name _create_message_dicts resolves at call time."""
    chat_models._convert_message_to_dict = _convert_message_to_dict


apply()
