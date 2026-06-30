"""Transcript -> structured memories: the write-path LLM calls.

Two operations, both built on the default model with structured output and
graceful degradation — extraction failures must never break the conversation
flow that spawned them, so total failure returns an empty batch / all-NEW
decisions instead of raising.
"""

from datetime import datetime
from typing import TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, ValidationError

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS
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

# Provider failures and malformed structured output both degrade to None so the
# memory helper never breaks the chat that spawned it.
_STRUCTURED_FAILURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    *LLM_FALLBACK_EXCEPTIONS,
    ValidationError,
)


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
    """Structured-output call on the default model. Returns None on any provider
    failure (or when no provider is configured) so extraction degrades gracefully
    and never breaks the chat that spawned it. ``_SILENT_CONFIG`` keeps the
    structured-output tokens out of the chat stream; transient-error retry is
    built into ``ainvoke_llm``."""
    try:
        model = get_default_llm()
    except RuntimeError as e:
        log.error(
            "memory_llm_no_provider", operation=operation, error_type=type(e).__name__, error=str(e)
        )
        return None

    structured_llm = model.with_structured_output(output_model)
    try:
        result = await ainvoke_llm(
            structured_llm, messages, config=_SILENT_CONFIG, label=f"memory:{operation}"
        )
        if isinstance(result, output_model):
            return result
        # Malformed structured output must stay on the graceful path, not raise.
        return output_model.model_validate(result)
    except _STRUCTURED_FAILURE_EXCEPTIONS as e:
        log.error(
            "memory_llm_failed", operation=operation, error_type=type(e).__name__, error=str(e)
        )
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
        # Memory context (operation/counts) is owned by retain, the orchestrator;
        # here we only flag that the extraction stage degraded to an empty batch.
        log.error("memory_extraction_failed", user_id=user_id, error_type="llm_returned_none")
        return ExtractedMemoryBatch()

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
        log.error(
            "memory_reconcile_failed",
            error_type="llm_returned_none",
            fact_count=len(pairs),
            fallback="all_new",
        )
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
