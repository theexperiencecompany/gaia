"""The text-description fallback — how a model that cannot see gets to "see"."""

from typing import cast

from langchain_core.messages import BaseMessage

from app.agents.llm.client import ainvoke_llm, metered_config, resolve_model
from app.constants.llm import ModelUse
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

    The fallback for lanes that can't take pixels; runs on ModelUse.VISION, never
    the default model. Returns None when the call fails; raises
    LLMNotConfiguredError when no configured provider can see at all.
    """
    vision_model = resolve_model(ModelUse.VISION)
    try:
        response = await ainvoke_llm(
            vision_model,
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
