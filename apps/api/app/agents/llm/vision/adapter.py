"""Fit the inline media in a message list to what the active model lane accepts."""

from collections.abc import Sequence
from typing import TypeGuard, cast

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.llm.vision.capability import MediaDelivery, resolve_media_delivery
from app.constants.media import (
    MAX_INLINE_MEDIA_BLOCKS,
    MEDIA_DESCRIPTIONS_KEY,
    MEDIA_EVICTED_NOTICE,
    MEDIA_OMITTED_NOTICE,
)
from app.utils.multimodal import (
    ContentItem,
    extract_text_content,
    has_media_blocks,
    is_media_block,
    text_content_block,
)

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
    delivery = await resolve_media_delivery(config)
    return MediaAdapter(delivery).adapt(messages)


class MediaAdapter:
    """Rewrites tool-result media into the shape one lane can actually receive.

    Media enters history as image blocks inside ToolMessages — one canonical
    storage shape — but each lane takes delivery differently:

    - Vision lanes read image blocks inside tool results natively. Direct Gemini
      does so out of the box; OpenRouter needs
      ``app/patches/openrouter_tool_multimodal_patch.py``, because the client
      library converts blocks for user messages but not for tool messages.
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
        delivery: MediaDelivery,
        max_blocks: int = MAX_INLINE_MEDIA_BLOCKS,
    ) -> None:
        self._delivery = delivery
        self._max_blocks = max_blocks

    def adapt(self, messages: Sequence[AnyMessage]) -> list[AnyMessage]:
        """Rewrite the tool-result media in ``messages``, one branch per strategy."""
        if self._delivery is MediaDelivery.REPLACE_WITH_TEXT:
            return self._strip(messages)
        return self._keep_in_tool_results(messages, self._within_budget(messages))

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
            kept: list[ContentItem] = [
                block
                for b_idx, block in enumerate(blocks)
                if not is_media_block(block) or (m_idx, b_idx) in admitted
            ]
            if len(kept) < len(blocks):
                kept.append(text_content_block(MEDIA_EVICTED_NOTICE))
            adapted.append(msg.model_copy(update={"content": kept}))
        return adapted

    def _strip(self, messages: Sequence[AnyMessage]) -> list[AnyMessage]:
        """Text-only lane: every image becomes its description, or a notice."""
        return [_as_described_text(msg) if _carries_media(msg) else msg for msg in messages]


def _carries_media(msg: AnyMessage) -> TypeGuard[ToolMessage]:
    """True for a tool result that still holds inline image blocks."""
    return isinstance(msg, ToolMessage) and has_media_blocks(msg.content)


def _blocks(msg: ToolMessage) -> list[ContentItem]:
    """The block list of a message ``_carries_media`` has already vouched for."""
    return cast(list[ContentItem], msg.content)


def _as_text(msg: ToolMessage, notice: str) -> ToolMessage:
    """The tool result with its media dropped and ``notice`` appended, as plain text."""
    text = extract_text_content(msg.content)
    return msg.model_copy(update={"content": f"{text}\n{notice}" if text else notice})


def _as_described_text(msg: ToolMessage) -> ToolMessage:
    """The tool result with its media replaced by the descriptions cached on it.

    The descriptions are written at tool-execution time (``describe_tool_media``).
    A message that predates that — produced on a vision lane, now replayed on a
    text-only one — carries none, and falls back to the bare notice.
    """
    descriptions = msg.additional_kwargs.get(MEDIA_DESCRIPTIONS_KEY)
    if not descriptions:
        return _as_text(msg, MEDIA_OMITTED_NOTICE)
    total = len(descriptions)
    return _as_text(
        msg,
        "\n\n".join(
            f"[Image {i} of {total}, described because this model cannot view images:]\n{text}"
            for i, text in enumerate(descriptions, start=1)
        ),
    )
