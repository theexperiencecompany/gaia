"""Transcript -> structured memories: the write-path LLM calls.

Two operations, both built on the free LLM chain with per-model structured
output and graceful degradation — extraction failures must never break the
conversation flow that spawned them, so total failure returns an empty
batch / all-NEW decisions instead of raising.
"""

import asyncio
from datetime import datetime
from typing import TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents.llm.client import get_free_llm_chain
from app.constants.memory import (
    EXTRACTION_TRANSCRIPT_HEAD_CHARS,
    EXTRACTION_TRANSCRIPT_MAX_CHARS,
    EXTRACTION_TRANSCRIPT_TAIL_CHARS,
    ReconcileOutcome,
)
from app.memory.prompts import (
    CATEGORIZE_SYSTEM_PROMPT,
    EPISODE_SUMMARY_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    RECONCILE_SYSTEM_PROMPT,
)
from app.memory.schemas import (
    ConsolidatedDocument,
    EpisodeSummary,
    ExtractedFact,
    ExtractedMemoryBatch,
    FactCategorization,
    ReconcileBatchResult,
    ReconcileDecision,
)
from shared.py.wide_events import log

_StructuredT = TypeVar("_StructuredT", bound=BaseModel)

_TRANSCRIPT_TRUNCATION_MARKER = "\n[... transcript truncated ...]\n"

# Background ingestion retries transient LLM errors (rate limits, overload)
# instead of dropping the memory. Latency does not matter off the request path.
_MAX_STRUCTURED_RETRIES = 4
_RETRY_BASE_DELAY_SECONDS = 2.0
_TRANSIENT_ERROR_MARKERS = (
    "429",
    "rate limit",
    "ratelimit",
    "resource_exhausted",
    "resourceexhausted",
    "quota",
    "503",
    "overloaded",
    "unavailable",
    "timeout",
    "timed out",
)


def _is_transient_error(error: Exception) -> bool:
    """Whether an LLM error is a rate-limit/overload worth retrying."""
    text = str(error).lower()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


# These LLM calls run inside the LangGraph run that spawned them (the
# add_memory tool, or a background ingestion task that inherited the graph's
# callback context). Without this marker their structured-output tokens are
# captured by the chat token stream and rendered as assistant text. ``silent``
# is the same flag the chat stream consumers use to drop internal-LLM chunks.
_SILENT_CONFIG: RunnableConfig = {
    "silent": True,  # top-level flag, matching follow_up_actions_node
    "metadata": {"silent": True},  # canonical location the messages-stream consumers read
    "tags": ["memory_internal"],
}  # type: ignore[typeddict-unknown-key]


class SimilarMemory(BaseModel):
    """An existing memory candidate handed to the reconcile LLM."""

    id: str = Field(description="Memory ID in the canonical store")
    content: str = Field(description="The stored fact content")
    age_days: int = Field(description="How many days ago this memory was stored")


def format_transcript(messages: list[dict[str, str]]) -> str:
    """Render conversation messages as a plain-text transcript for the LLM.

    Capped at ``EXTRACTION_TRANSCRIPT_MAX_CHARS`` using a head+tail strategy:
    the opening context and the most recent exchanges matter most, the middle
    is dropped.
    """
    lines = [
        f"{message.get('role', 'user')}: {message.get('content', '')}"
        for message in messages
        if message.get("content")
    ]
    transcript = "\n".join(lines)
    if len(transcript) <= EXTRACTION_TRANSCRIPT_MAX_CHARS:
        return transcript
    head = transcript[:EXTRACTION_TRANSCRIPT_HEAD_CHARS]
    tail = transcript[-EXTRACTION_TRANSCRIPT_TAIL_CHARS:]
    return f"{head}{_TRANSCRIPT_TRUNCATION_MARKER}{tail}"


async def _invoke_structured(
    output_model: type[_StructuredT],
    messages: list[BaseMessage],
    *,
    operation: str,
) -> _StructuredT | None:
    """Invoke the free LLM chain with structured output, falling back per model.

    ``with_structured_output`` binds per model, so the fallback loop re-binds
    the schema for each LLM in the chain. Returns None if every model fails
    (including when no provider is configured) — callers degrade gracefully.
    """
    try:
        llm_chain = get_free_llm_chain()
    except RuntimeError as e:
        log.error(f"[memory] {operation}: no LLM provider configured: {e}")
        return None

    for index, llm in enumerate(llm_chain):
        provider_name = type(llm).__name__
        structured_llm = llm.with_structured_output(output_model)
        for attempt in range(_MAX_STRUCTURED_RETRIES):
            try:
                result = await structured_llm.ainvoke(messages, config=_SILENT_CONFIG)
                if isinstance(result, output_model):
                    return result
                return output_model.model_validate(result)
            except Exception as e:
                # Rate limits / transient errors must NOT silently drop a memory:
                # ingestion is a background task, so retry the same provider with
                # backoff before falling through to the next one.
                if _is_transient_error(e) and attempt < _MAX_STRUCTURED_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    log.warning(
                        f"[memory] {operation}: {provider_name} transient error, "
                        f"retrying in {delay:.0f}s ({attempt + 1}/{_MAX_STRUCTURED_RETRIES}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                if index < len(llm_chain) - 1:
                    log.warning(
                        f"[memory] {operation}: {provider_name} failed, trying next provider: {e}"
                    )
                else:
                    log.error(f"[memory] {operation}: all LLM providers failed. Last error: {e}")
                break
    return None


async def extract_memories(
    messages: list[dict[str, str]],
    *,
    user_id: str,
    user_name: str,
    folder_tree: str,
    recent_facts: list[str],
    journaled_today: list[str] | None = None,
    extraction_hints: str | None = None,
    current_date: datetime,
) -> ExtractedMemoryBatch:
    """Extract durable facts, episode entries and agenda updates from a conversation.

    Returns an empty batch on total LLM failure — never raises into callers.
    """
    transcript = format_transcript(messages)
    if not transcript:
        return ExtractedMemoryBatch()

    hints_section = f"\n{extraction_hints}\n" if extraction_hints else ""
    recent_facts_section = (
        "\n".join(f"- {fact}" for fact in recent_facts) if recent_facts else "(none yet)"
    )
    journal_section = (
        "\n".join(f"- {line}" for line in journaled_today) if journaled_today else "(empty)"
    )
    system_prompt = EXTRACTION_SYSTEM_PROMPT.format(
        current_date=f"{current_date:%A, %d %B %Y}",
        user_name=user_name,
        folder_tree=folder_tree or "(no folders yet)",
        recent_facts=recent_facts_section,
        journal_today=journal_section,
        extraction_hints=hints_section,
    )

    result = await _invoke_structured(
        ExtractedMemoryBatch,
        [SystemMessage(content=system_prompt), HumanMessage(content=transcript)],
        operation="extraction",
    )
    if result is None:
        log.error(f"[memory] extraction failed for user {user_id}; returning empty batch")
        return ExtractedMemoryBatch()

    log.set(
        memory={
            "operation": "extract",
            "user_id": user_id,
            "fact_count": len(result.facts),
            "episode_entry_count": len(result.episode_entries),
            "agenda_update_count": len(result.agenda_updates),
        }
    )
    return result


async def categorize_fact(
    content: str,
    *,
    folder_tree: str,
    current_date: datetime,
) -> FactCategorization | None:
    """File a single manually added fact: folder, kind, importance, entities.

    Used by the add_memory path, which skips transcript extraction. Returns
    None on total LLM failure — callers fall back to defaults.
    """
    system_prompt = CATEGORIZE_SYSTEM_PROMPT.format(
        current_date=f"{current_date:%A, %d %B %Y}",
        folder_tree=folder_tree or "(no folders yet)",
    )
    return await _invoke_structured(
        FactCategorization,
        [SystemMessage(content=system_prompt), HumanMessage(content=content)],
        operation="categorize",
    )


async def summarize_episode_entries(entries: list[str]) -> str | None:
    """Summarize one day's journal entries (day-rollover, one LLM call).

    Returns None on total LLM failure — the day simply stays unsummarized
    and is retried on the next rollover check.
    """
    if not entries:
        return None
    result = await _invoke_structured(
        EpisodeSummary,
        [
            SystemMessage(content=EPISODE_SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content="\n".join(entries)),
        ],
        operation="episode_summary",
    )
    return result.summary if result else None


async def rewrite_core_document(system_prompt: str, inputs: str) -> str | None:
    """Rewrite one core memory document from its inputs (consolidation pass).

    Returns None on total LLM failure — the document simply keeps its
    previous version until the next consolidation.
    """
    result = await _invoke_structured(
        ConsolidatedDocument,
        [SystemMessage(content=system_prompt), HumanMessage(content=inputs)],
        operation="consolidate",
    )
    return result.content if result else None


def _format_reconcile_input(pairs: list[tuple[ExtractedFact, list[SimilarMemory]]]) -> str:
    """Render (new fact, similar existing memories) pairs for the reconcile LLM."""
    blocks: list[str] = []
    for index, (fact, candidates) in enumerate(pairs):
        lines = [f"NEW FACT {index}: {fact.content}"]
        if candidates:
            lines.append("SIMILAR EXISTING MEMORIES:")
            lines.extend(
                f"- id={candidate.id} (age {candidate.age_days}d): {candidate.content}"
                for candidate in candidates
            )
        else:
            lines.append("SIMILAR EXISTING MEMORIES: (none)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _all_new_decisions(count: int) -> ReconcileBatchResult:
    """Fallback result: treat every fact as NEW (safe — nothing is lost or merged)."""
    return ReconcileBatchResult(
        decisions=[
            ReconcileDecision(new_fact_index=index, decision=ReconcileOutcome.NEW)
            for index in range(count)
        ]
    )


async def reconcile_facts(
    pairs: list[tuple[ExtractedFact, list[SimilarMemory]]],
) -> ReconcileBatchResult:
    """Decide how each new fact relates to its similar existing memories.

    One batched LLM call for all facts. On total failure every fact is
    treated as NEW — never raises into callers.
    """
    if not pairs:
        return ReconcileBatchResult()

    result = await _invoke_structured(
        ReconcileBatchResult,
        [
            SystemMessage(content=RECONCILE_SYSTEM_PROMPT),
            HumanMessage(content=_format_reconcile_input(pairs)),
        ],
        operation="reconcile",
    )
    if result is None:
        log.error("[memory] reconcile failed; treating all facts as NEW")
        return _all_new_decisions(len(pairs))

    # Normalize: one decision per fact, indexed 0..n-1; anything the LLM
    # missed or pointed out of range defaults to NEW.
    by_index = {
        decision.new_fact_index: decision
        for decision in result.decisions
        if 0 <= decision.new_fact_index < len(pairs)
    }
    decisions = [
        by_index.get(index, ReconcileDecision(new_fact_index=index, decision=ReconcileOutcome.NEW))
        for index in range(len(pairs))
    ]
    return ReconcileBatchResult(decisions=decisions)
