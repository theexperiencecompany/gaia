"""Vision support: per-lane capability resolution, the per-call media adapter,
and the canonical text-description fallback for models that can't view media.

Inline media enters history as image blocks inside ToolMessages (the `read`
tool, MCP tools) — the one canonical storage shape. How a given model call can
actually receive that media differs per lane, so `adapt_media_blocks_for_model`
rewrites the request messages (never the persisted history) to fit:

- Direct Gemini accepts image blocks inside tool results natively.
- OpenRouter multimodal models can't take images in tool-role messages
  (langchain_openrouter serializes ToolMessage content raw), but do accept
  them in user messages — so the blocks are repacked into an ephemeral
  HumanMessage after the tool results.
- Text-only models get a notice instead; the `read` tool additionally gives
  them a text description via `describe_image`.
"""

from collections.abc import Sequence
from enum import Enum

from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage, is_data_content_block
from langchain_core.runnables import RunnableConfig

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.agents.llm.model_catalog import openrouter_model_accepts_images
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    GEMINI_PROVIDER,
    OPENROUTER_PROVIDER,
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
MEDIA_REPACKED_NOTICE = (
    "[Inline media from this result is attached in the user message following these tool results.]"
)
_REPACKED_MEDIA_HEADER = "[Media attached from the preceding tool results:]"


class VisionCapability(Enum):
    """How the active lane can receive inline media, from most to least direct."""

    TOOL_MESSAGE_BLOCKS = "tool_message_blocks"
    USER_MESSAGE_BLOCKS = "user_message_blocks"
    TEXT_ONLY = "text_only"


def _active_lane(config: RunnableConfig) -> tuple[str, str]:
    configurable = config.get("configurable", {})
    provider = configurable.get("provider") or DEFAULT_LLM_PROVIDER
    model = configurable.get("model") or configurable.get("model_name") or DEFAULT_MODEL_NAME
    return provider, model


async def get_vision_capability(config: RunnableConfig) -> VisionCapability:
    """Resolve the active (provider, model) lane's media capability.

    Direct Gemini is natively multimodal down to tool results. OpenRouter
    models are looked up in the live catalog (image input modality → user
    message delivery). Unknown providers and catalog misses are treated as
    text-only — fail safe to the description fallback, never a rejected
    provider request.
    """
    provider, model = _active_lane(config)
    if provider == GEMINI_PROVIDER:
        return VisionCapability.TOOL_MESSAGE_BLOCKS
    if provider == OPENROUTER_PROVIDER and await openrouter_model_accepts_images(model):
        return VisionCapability.USER_MESSAGE_BLOCKS
    return VisionCapability.TEXT_ONLY


async def model_can_view_images(config: RunnableConfig) -> bool:
    """Whether the run's active model can see inline images at all (in tool
    results directly or repacked into a user message)."""
    return await get_vision_capability(config) is not VisionCapability.TEXT_ONLY


async def describe_image(
    image_b64: str,
    mime_type: str,
    prompt: str,
    label: str = "vision_fallback",
) -> str | None:
    """Describe an image via a one-off call on the default (multimodal) model.

    The canonical fallback that lets text-only lanes "see" media. Returns
    ``None`` when the vision call fails so callers degrade gracefully rather
    than failing the whole tool.
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


async def adapt_media_blocks_for_model(
    messages: Sequence[AnyMessage],
    config: RunnableConfig,
) -> list[AnyMessage]:
    """Fit inline media in ToolMessages to the active lane, per model call.

    Callers apply this to the request messages only — persisted history keeps
    the canonical block shape, so a thread stays portable across lane changes
    (plan change, dev override). Unchanged messages keep their identity.
    """
    capability = await get_vision_capability(config)
    if capability is VisionCapability.TOOL_MESSAGE_BLOCKS:
        return list(messages)
    if capability is VisionCapability.USER_MESSAGE_BLOCKS:
        return _repack_media_into_user_message(messages)
    return _strip_media_blocks(messages)


def _media_blocks(content: object) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and is_data_content_block(block)]


def _repack_media_into_user_message(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Move ToolMessage media into an ephemeral HumanMessage.

    The HumanMessage is inserted after each contiguous run of ToolMessages
    (never between an AI tool-call message and its results, which providers
    reject). Blocks keep their order and get a per-source label so the model
    can attribute each image to the tool result it came from.
    """
    adapted: list[AnyMessage] = []
    pending: list[dict] = []

    def flush() -> None:
        if pending:
            adapted.append(
                HumanMessage(content=[{"type": "text", "text": _REPACKED_MEDIA_HEADER}, *pending])
            )
            pending.clear()

    for msg in messages:
        if isinstance(msg, ToolMessage) and has_data_content_blocks(msg.content):
            text = extract_text_content(msg.content)
            notice = f"{text}\n{MEDIA_REPACKED_NOTICE}" if text else MEDIA_REPACKED_NOTICE
            adapted.append(msg.model_copy(update={"content": notice}))
            label = f"[Media from the '{msg.name or 'tool'}' result:]"
            pending.append({"type": "text", "text": label})
            pending.extend(_media_blocks(msg.content))
            continue
        if not isinstance(msg, ToolMessage):
            flush()
        adapted.append(msg)

    flush()
    return adapted


def _strip_media_blocks(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Replace inline media in ToolMessages with a text notice (text-only lanes)."""
    sanitized: list[AnyMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and has_data_content_blocks(msg.content):
            text = extract_text_content(msg.content)
            notice = f"{text}\n{MEDIA_OMITTED_NOTICE}" if text else MEDIA_OMITTED_NOTICE
            msg = msg.model_copy(update={"content": notice})
        sanitized.append(msg)
    return sanitized
