"""The text-description fallback — how a model that cannot see gets to "see"."""

from typing import cast

from langchain_core.messages import BaseMessage

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.constants.log_tags import LogTag
from app.utils.multimodal import image_content_block
from shared.py.wide_events import log


async def describe_image(
    image_b64: str,
    mime_type: str,
    prompt: str,
    label: str = "vision_fallback",
) -> str | None:
    """Describe an image with a one-off call on the default (multimodal) model.

    The canonical fallback for lanes that can't take pixels — the `read` tool and
    the desktop screenshot tool both route through here. Returns ``None`` when
    the vision call fails, so a caller degrades to telling the user it couldn't
    look rather than failing the whole tool.
    """
    try:
        response = await ainvoke_llm(
            get_default_llm(),
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
        )
    except Exception as exc:  # any provider failure degrades gracefully
        log.warning(f"{LogTag.TOOL} Vision fallback call failed: {exc}")
        return None
    # `.text` flattens the message's content blocks to a string; `.content` may
    # be a list (Gemini), whose repr would leak into the description.
    # ainvoke_llm is typed -> Any (its return shape varies by call site); this
    # call always resolves to a chat-model response message.
    description = cast(BaseMessage, response).text.strip()
    return description or None
