"""Vision support: the capability gate for inline media in tool results and the
canonical text-description fallback for models that can't view media."""

from collections.abc import Sequence

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    VISION_TOOL_RESULT_MODELS,
)
from app.constants.log_tags import LogTag
from app.utils.multimodal import (
    extract_text_content,
    has_data_content_blocks,
    image_content_block,
)
from shared.py.wide_events import log

MEDIA_OMITTED_NOTICE = (
    "[Inline media omitted: the current model cannot view media directly. "
    "Tell the user what you were unable to view if it matters for their request.]"
)


def model_supports_vision(config: RunnableConfig) -> bool:
    """Whether the run's active (provider, model) lane accepts inline image
    blocks in tool results. Unknown lanes are treated as non-vision (fail safe
    to the text-description fallback, never a broken provider request)."""
    configurable = config.get("configurable", {})
    provider = configurable.get("provider") or DEFAULT_LLM_PROVIDER
    model = configurable.get("model") or configurable.get("model_name") or DEFAULT_MODEL_NAME
    return (provider, model) in VISION_TOOL_RESULT_MODELS


async def describe_image(
    image_b64: str,
    mime_type: str,
    prompt: str,
    label: str = "vision_fallback",
) -> str | None:
    """Describe an image via a one-off call on the default (multimodal) model.

    The canonical fallback that lets non-vision lanes "see" media: image blocks
    inside tool results only work on VISION_TOOL_RESULT_MODELS, so other lanes
    return this text description instead. Returns ``None`` when the vision call
    fails so callers degrade gracefully rather than failing the whole tool.
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
    # ``.text`` flattens the message's content blocks to a string; ``.content``
    # may be a list (Gemini), whose repr would leak into the description.
    description = response.text.strip()
    return description or None


def strip_media_blocks_for_non_vision(
    messages: Sequence[AnyMessage],
    config: RunnableConfig,
) -> list[AnyMessage]:
    """Replace inline media blocks in ToolMessages with a text notice when the
    active model can't view media.

    Media blocks enter history on vision-capable lanes (read tool, MCP tools) —
    when the same thread later runs on a non-vision lane (plan change, dev
    override), forwarding them would make some providers reject the request.
    Unchanged messages keep their identity so ``add_messages`` reducers only
    replace the sanitized ones.
    """
    if model_supports_vision(config):
        return list(messages)

    sanitized: list[AnyMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and has_data_content_blocks(msg.content):
            text = extract_text_content(msg.content)
            notice = f"{text}\n{MEDIA_OMITTED_NOTICE}" if text else MEDIA_OMITTED_NOTICE
            msg = msg.model_copy(update={"content": notice})
        sanitized.append(msg)
    return sanitized
