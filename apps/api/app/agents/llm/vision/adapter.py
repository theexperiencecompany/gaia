"""Fit the inline media in a message list to what the active model lane accepts."""

from collections.abc import Sequence
from typing import Any, TypeGuard, cast

from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.llm.vision.capability import VisionCapability, resolve_vision_capability
from app.constants.media import (
    MAX_INLINE_MEDIA_BLOCKS,
    MEDIA_EVICTED_NOTICE,
    MEDIA_OMITTED_NOTICE,
    MEDIA_REPACKED_NOTICE,
    REPACKED_MEDIA_HEADER,
)
from app.utils.multimodal import extract_text_content, has_media_blocks, is_media_block

# Where one media block sits in a message list: (message index, block index).
BlockRef = tuple[int, int]


async def adapt_media_for_model(
    messages: Sequence[AnyMessage],
    config: RunnableConfig,
) -> list[AnyMessage]:
    """Rewrite ``messages`` so their inline media fits the active lane.

    Applied at the request boundary only — persisted history keeps the canonical
    block shape, so a thread stays portable when the lane changes under it (plan
    upgrade, dev model override). A thread with no media is returned untouched
    and never pays for a lane lookup, which is the overwhelming majority of calls.
    """
    if not any(_carries_media(msg) for msg in messages):
        return list(messages)
    capability = await resolve_vision_capability(config)
    return MediaAdapter(capability).adapt(messages)


class MediaAdapter:
    """Rewrites tool-result media into the shape one lane can actually receive.

    Media enters history as image blocks inside ToolMessages — one canonical
    storage shape — but each lane takes delivery differently:

    - Direct Gemini reads image blocks inside tool results natively.
    - OpenRouter serializes ToolMessage content raw (langchain_openrouter
      forwards it without block conversion), so tool-result images can never
      work there. Multimodal OpenRouter models *do* accept images in user
      messages, so the blocks are repacked into an ephemeral HumanMessage placed
      after the tool results.
    - Text-only lanes get a notice instead; the `read` tool separately hands them
      a text description via `describe_image`.

    Every lane is also held to ``max_blocks``. History is append-only and media
    is never compacted away — a spilled image is useless, the block *is* the
    payload — so without a per-request budget a thread that read twenty
    screenshots would re-send all of them on every subsequent turn until the
    provider rejected the payload outright. The most recent blocks win.
    """

    def __init__(
        self,
        capability: VisionCapability,
        max_blocks: int = MAX_INLINE_MEDIA_BLOCKS,
    ) -> None:
        self._capability = capability
        self._max_blocks = max_blocks

    def adapt(self, messages: Sequence[AnyMessage]) -> list[AnyMessage]:
        if self._capability is VisionCapability.TEXT_ONLY:
            return self._strip(messages)

        admitted = self._within_budget(messages)
        if self._capability is VisionCapability.TOOL_MESSAGE_BLOCKS:
            return self._keep_in_tool_results(messages, admitted)
        return self._repack_into_user_messages(messages, admitted)

    def _within_budget(self, messages: Sequence[AnyMessage]) -> set[BlockRef]:
        """The most recent media blocks that fit the per-request budget."""
        admitted: set[BlockRef] = set()
        for m_idx, msg in reversed(list(enumerate(messages))):
            if not _carries_media(msg):
                continue
            for b_idx, block in reversed(list(enumerate(_blocks(msg)))):
                if not is_media_block(block):
                    continue
                if len(admitted) >= self._max_blocks:
                    return admitted
                admitted.add((m_idx, b_idx))
        return admitted

    def _keep_in_tool_results(
        self,
        messages: Sequence[AnyMessage],
        admitted: set[BlockRef],
    ) -> list[AnyMessage]:
        """Gemini: media stays where it is; only over-budget blocks drop out."""
        adapted: list[AnyMessage] = []
        for m_idx, msg in enumerate(messages):
            if not _carries_media(msg):
                adapted.append(msg)
                continue
            blocks = _blocks(msg)
            kept: list[Any] = [
                block
                for b_idx, block in enumerate(blocks)
                if not is_media_block(block) or (m_idx, b_idx) in admitted
            ]
            if len(kept) < len(blocks):
                kept.append(_text_block(MEDIA_EVICTED_NOTICE))
            adapted.append(msg.model_copy(update={"content": kept}))
        return adapted

    def _repack_into_user_messages(
        self,
        messages: Sequence[AnyMessage],
        admitted: set[BlockRef],
    ) -> list[AnyMessage]:
        """OpenRouter multimodal: media moves into a user message after the tool run.

        The HumanMessage is inserted after each contiguous run of ToolMessages,
        never between an AI tool-call message and its results — providers reject
        that ordering. Blocks keep their order and carry a per-source label so
        the model can attribute each image to the result it came from.
        """
        adapted: list[AnyMessage] = []
        pending: list[dict[str, Any]] = []

        def flush() -> None:
            if pending:
                adapted.append(HumanMessage(content=[_text_block(REPACKED_MEDIA_HEADER), *pending]))
                pending.clear()

        for m_idx, msg in enumerate(messages):
            if _carries_media(msg):
                carried = _admitted_blocks(msg, m_idx, admitted)
                adapted.append(
                    _as_text(msg, MEDIA_REPACKED_NOTICE if carried else MEDIA_EVICTED_NOTICE)
                )
                if carried:
                    label = f"[Media from the '{msg.name or 'tool'}' result:]"
                    pending.append(_text_block(label))
                    pending.extend(carried)
                continue
            if not isinstance(msg, ToolMessage):
                flush()
            adapted.append(msg)

        flush()
        return adapted

    def _strip(self, messages: Sequence[AnyMessage]) -> list[AnyMessage]:
        """Text-only lane: every image becomes a notice."""
        return [
            _as_text(msg, MEDIA_OMITTED_NOTICE) if _carries_media(msg) else msg for msg in messages
        ]


def _carries_media(msg: AnyMessage) -> TypeGuard[ToolMessage]:
    return isinstance(msg, ToolMessage) and has_media_blocks(msg.content)


def _blocks(msg: ToolMessage) -> list[Any]:
    """The block list of a message ``_carries_media`` has already vouched for."""
    return cast(list[Any], msg.content)


def _admitted_blocks(
    msg: ToolMessage,
    m_idx: int,
    admitted: set[BlockRef],
) -> list[dict[str, Any]]:
    return [
        block
        for b_idx, block in enumerate(_blocks(msg))
        if is_media_block(block) and (m_idx, b_idx) in admitted
    ]


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _as_text(msg: ToolMessage, notice: str) -> ToolMessage:
    """The tool result with its media dropped and ``notice`` appended, as plain text."""
    text = extract_text_content(msg.content)
    return msg.model_copy(update={"content": f"{text}\n{notice}" if text else notice})
