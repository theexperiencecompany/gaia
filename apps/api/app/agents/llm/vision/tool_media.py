"""The text-description fallback, applied to any tool result carrying media.

Runs at tool-execution time, not at the request boundary: the lane is already
known there (compaction reads it the same way), and the ToolMessage that comes
out is persisted — so each image is described once, ever. A pre-model hook cannot
cache anything (its return value feeds one model call and is then discarded),
which is why this does not live in ``MediaAdapter``.

The canonical image block stays in the message; only the description is added, so
the thread still works if the lane later changes to one that can see pixels.
"""

import asyncio

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.llm.vision.capability import model_can_view_images
from app.agents.llm.vision.describe import describe_image
from app.constants.log_tags import LogTag
from app.constants.media import (
    MEDIA_DESCRIBE_FAILED,
    MEDIA_DESCRIPTIONS_KEY,
    TOOL_MEDIA_DESCRIBE_PROMPT,
)
from app.utils.json_helpers import text_bag
from app.utils.multimodal import ContentBlock, extract_text_content, media_blocks
from shared.py.wide_events import log


async def _describe_block(block: ContentBlock, prompt: str) -> str | None:
    """Describe one media block, or None when it carries no inline base64 image.

    ``media_blocks`` admits every shape LangChain calls a data block — url,
    file_id, the v0 ``source_type``/``data`` pair — while every GAIA producer
    emits the inline ``base64``/``mime_type`` block from ``image_content_block``.
    A foreign shape is skipped and logged rather than sent to the vision model
    as an empty image, which would spend a call to learn nothing.
    """
    image_b64 = block.get("base64")
    mime_type = block.get("mime_type")
    if not isinstance(image_b64, str) or not isinstance(mime_type, str):
        log.warning(
            f"{LogTag.TOOL} Media block carries no inline base64 image; not described",
            tool_media={"block_type": text_bag(block, "type")},
        )
        return None
    return await describe_image(image_b64, mime_type, prompt=prompt, label="tool_media_vision")


async def describe_tool_media(
    message: ToolMessage,
    config: RunnableConfig,
) -> ToolMessage | None:
    """Attach descriptions of ``message``'s media blocks when the lane can't see.

    Returns ``None`` when there is nothing to do — no media, a lane that takes
    pixels directly, or descriptions already attached — matching
    ``compact_tool_output``'s keep-as-is contract.
    """
    blocks = media_blocks(message.content)
    if not blocks:
        return None
    if message.additional_kwargs.get(MEDIA_DESCRIPTIONS_KEY):
        return None
    if await model_can_view_images(config):
        return None

    tool_name = message.name or "tool"
    prompt = TOOL_MEDIA_DESCRIBE_PROMPT.format(
        tool_name=tool_name,
        context=extract_text_content(message.content) or "(none)",
    )
    # Bounded by MAX_MEDIA_BLOCKS_PER_TOOL_RESULT at every producer.
    described = await asyncio.gather(*(_describe_block(block, prompt) for block in blocks))
    log.info(
        f"{LogTag.TOOL} Described tool media for a text-only lane",
        tool_media={
            "tool": tool_name,
            "images": len(blocks),
            "failed": sum(1 for text in described if text is None),
        },
    )
    updated: dict[str, object] = {
        **message.additional_kwargs,
        MEDIA_DESCRIPTIONS_KEY: [text or MEDIA_DESCRIBE_FAILED for text in described],
    }
    return message.model_copy(update={"additional_kwargs": updated})
