"""Message-content block helpers — pure, synchronous, no I/O.

Message content is either a plain string or a list of blocks, and once inline
media is in play the list form carries base64 payloads that must never reach a
logger, a stream, a memory ingest, or a char-based token estimate. These helpers
are the single place that knows how to look inside that list.

Image encoding and transcoding live in ``app/utils/image_codec.py``; per-lane
delivery lives in ``app/agents/llm/vision/``.
"""

from typing import Any, TypeAlias, TypeGuard

from langchain_core.messages import is_data_content_block

from app.constants.media import MEDIA_BLOCK_TOKEN_ESTIMATE

# Chars a media block stands in for when estimating context from string length.
_MEDIA_BLOCK_CHARS = MEDIA_BLOCK_TOKEN_ESTIMATE * 4

# A single content block: an arbitrary string-keyed JSON object. Values stay
# ``Any`` because provider and LangChain data blocks are genuinely heterogeneous
# third-party shapes — this is the one place that ``Any`` is unavoidable. The
# blocks this codebase itself produces (text / image) follow a fixed schema.
ContentBlock: TypeAlias = dict[str, Any]
# One entry in a structured content list: a bare string or a block.
ContentItem: TypeAlias = str | ContentBlock
# A message's ``content``: plain text, or a list of items. Mirrors the shape of
# ``BaseMessage.content`` (``str | list[str | dict]``).
MessageContent: TypeAlias = str | list[ContentItem]


def text_content_block(text: str) -> ContentBlock:
    return {"type": "text", "text": text}


def image_content_block(base64_data: str, mime_type: str) -> ContentBlock:
    """The canonical inline-image block, from already-base64-encoded data."""
    return {"type": "image", "base64": base64_data, "mime_type": mime_type}


def is_media_block(block: object) -> TypeGuard[ContentBlock]:
    return isinstance(block, dict) and is_data_content_block(block)


def media_blocks(content: MessageContent) -> list[ContentBlock]:
    """The inline-media blocks in ``content``, in order; empty for text content."""
    if not isinstance(content, list):
        return []
    return [block for block in content if is_media_block(block)]


def has_media_blocks(content: MessageContent) -> bool:
    return bool(media_blocks(content))


def extract_text_content(content: object) -> str:
    """The text of message content that may be a list of blocks.

    Non-text blocks (inline media, base64 payloads) are dropped, so callers that
    log, stream, or ingest text never see megabytes of base64. Text blocks are
    rejoined with newlines, the separator their producers split on (an MCP result
    is one block per line), so extracting a block list round-trips its layout.

    Typed ``object`` rather than ``MessageContent``: real callers (``msg.content``
    on non-``BaseMessage`` objects, malformed upstream data) sometimes hand this a
    bool/int/None, so the trailing ``str(content)`` fallback below is real,
    reachable code, not dead code the type alias would otherwise imply.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
        return "\n".join(text_parts)

    return str(content)


def approx_content_chars(content: object) -> int:
    """Char length of message content for context estimation.

    Media blocks are charged a flat cost rather than their base64 length (~350k
    chars for a 1 MB image), which would otherwise read as a near-full context
    window and trigger compaction on the first screenshot.
    """
    if isinstance(content, str):
        return len(content)
    if not isinstance(content, list):
        return len(str(content))
    return sum(
        _MEDIA_BLOCK_CHARS if is_media_block(block) else len(str(block)) for block in content
    )
