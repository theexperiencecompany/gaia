"""Read a model's "thinking" off a streamed chunk.

Shared by the comms stream and the subagent runner. It lives under
agents/llm rather than utils (app.utils may not import the model stack) or
agent_utils (which would close an agent_utils -> subagent_runner cycle).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict


class _ContentBlock(BaseModel):
    """A streamed content block (dict or block object), read for its reasoning text."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    type: str | None = None
    reasoning: str = ""


class _ProviderExtras(BaseModel):
    """The DeepSeek-style additional_kwargs, read for the thinking they may carry."""

    model_config = ConfigDict(extra="ignore")

    reasoning_content: object = None


def extract_reasoning_delta(chunk: AIMessage) -> str:
    """Pull this chunk's reasoning ("thinking") text, model-agnostic.

    ChatOpenRouter surfaces reasoning as standard reasoning content blocks;
    other providers (DeepSeek-style) put it in additional_kwargs.reasoning_content.
    Returns "" when the chunk carries no thinking (e.g. non-reasoning models), so
    the caller emits nothing for them.
    """
    # a v1 content list may hold bare strings beside its block dicts; they carry no thinking
    blocks = [
        _ContentBlock.model_validate(block)
        for block in chunk.content_blocks
        if not isinstance(block, str)
    ]
    parts = [block.reasoning for block in blocks if block.type == "reasoning" and block.reasoning]
    if not parts:
        fallback = _ProviderExtras.model_validate(chunk.additional_kwargs).reasoning_content
        if fallback:
            parts.append(fallback if isinstance(fallback, str) else str(fallback))
    return "".join(parts)
