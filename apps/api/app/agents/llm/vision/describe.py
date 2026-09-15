"""The text-description fallback — how a model that cannot see gets to "see"."""

from typing import cast

from langchain_core.messages import BaseMessage

from app.agents.llm.client import ainvoke_llm, get_vision_llm, metered_config
from app.constants.log_tags import LogTag
from app.utils.multimodal import image_content_block
from shared.py.wide_events import log


async def describe_image(
    image_b64: str,
    mime_type: str,
    prompt: str,
    label: str = "vision_fallback",
    user_id: str | None = None,
) -> str | None:
    """Describe an image with a one-off call on the dedicated vision model.

    The canonical fallback for lanes that can't take pixels (read tool,
    desktop screenshot tool). Returns None on failure. Uses
    :func:get_vision_llm, never the default model, since callers reach here
    precisely because the active lane cannot see.
    """
    try:
        response = await ainvoke_llm(
            get_vision_llm(),
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        image_content_block(image_b64, mime_type),
                    ],
                }
            ],
            label=label,
            config=metered_config(user_id) if user_id else None,
        )
    except Exception as exc:  # any provider failure degrades gracefully
        log.warning(f"{LogTag.TOOL} Vision fallback call failed", error_type=type(exc).__name__)
        return None
    # `.text` flattens content blocks to a string; `.content` may be a list
    # (Gemini), whose repr would leak into the description.
    description = cast(BaseMessage, response).text.strip()
    return description or None
