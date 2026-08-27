"""Transcript -> structured memories: the write-path LLM calls.

Two operations, both built on the default model with structured output and
graceful degradation — extraction failures must never break the conversation
flow that spawned them, so total failure returns an empty batch / all-NEW
decisions instead of raising.
"""

from datetime import datetime
from typing import TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, ValidationError

from app.agents.llm.client import ainvoke_structured_gemini, silent_metered_config
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, LLMNotConfiguredError
from app.constants.memory import (
    EXTRACTION_TRANSCRIPT_HEAD_CHARS,
    EXTRACTION_TRANSCRIPT_MAX_CHARS,
    EXTRACTION_TRANSCRIPT_TAIL_CHARS,
    ReconcileOutcome,
)
from app.memory.prompts import (
    CATEGORIZE_SYSTEM_PROMPT,
    DOCUMENT_VERIFICATION_PROMPT,
    EPISODE_SUMMARY_SYSTEM_PROMPT,
    EXTRACTION_FOLDER_TREE_BLOCK,
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
    VerifiedDocument,
)
from shared.py.wide_events import log

_StructuredT = TypeVar("_StructuredT", bound=BaseModel)

_TRANSCRIPT_TRUNCATION_MARKER = "\n[... transcript truncated ...]\n"


# These LLM calls run inside the LangGraph run that spawned them (the
# add_memory tool, or a background ingestion task that inherited the graph's
# callback context). Without this marker their structured-output tokens are
# captured by the chat token stream and rendered as assistant text. ``silent``
# is the same flag the chat stream consumers use to drop internal-LLM chunks.
# ``configurable.user_id`` is who this background spend is metered against —
# see ``ainvoke_structured``; without it the pipeline's real COGS would land in
# nobody's budget.
def _silent_config(user_id: str) -> RunnableConfig:
    config: RunnableConfig = {
        **silent_metered_config(user_id),
        "tags": ["memory_internal"],
    }
    # The memory family's own sticky-routing chain, per user. On the aux lane
    # the sticky session is what keeps consecutive extractions landing on the
    # upstream that already holds this user's transcript prefixes — without it
    # every call routes independently and the append-only transcript re-sends
    # cold. Per USER, not per conversation: one upstream then holds all of a
    # user's memory-call prefixes, and the "-aux" suffix the runnable adds
    # keeps this chain from ever re-pinning a conversation's.
    # Indexing, not .get with a default: silent_metered_config always carries a
    # configurable (it is where the user_id metering lives), and a missing one
    # here would mean the spend attribution vanished — fail loud, not paper over.
    config["configurable"] = {
        **config["configurable"],
        "session_id": f"memory-{user_id}",
    }
    return config


# Provider failures and malformed structured output both degrade to None so the
# memory helper never breaks the chat that spawned it. ``OutputParserException``
# is what the structured-output parser raises on malformed/truncated model
# output (it wraps the underlying ``ValidationError``/JSON error).
_STRUCTURED_FAILURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    *LLM_FALLBACK_EXCEPTIONS,
    ValidationError,
    OutputParserException,
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
    user_id: str,
) -> _StructuredT | None:
    """Structured-output call on the memory lane via the canonical
    ``ainvoke_structured_gemini`` (which owns provider selection, retry +
    validation, and meters the spend against ``user_id``). Returns None only
    when NO provider is configured or every one of them failed, so extraction
    degrades gracefully and never breaks the chat that spawned it. The silent
    config keeps the structured-output tokens out of the chat stream.

    Prefers direct Gemini on purpose (see ``ainvoke_structured_gemini``): the
    extraction is a background task that overlaps the graph's next-turn
    requests, and concurrent requests on the same provider's cache store wipe
    each other's cached chains mid-read (measured). When Google is not
    configured, or Gemini is down, the call runs on the aux lane instead —
    losing the cache isolation, not the memory."""
    try:
        return await ainvoke_structured_gemini(
            output_model, messages, label=f"memory:{operation}", config=_silent_config(user_id)
        )
    except LLMNotConfiguredError as e:
        log.error(
            "memory_llm_no_provider", operation=operation, error_type=type(e).__name__, error=str(e)
        )
        return None
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
    # The system prompt is deliberately user-agnostic: the user's name used to
    # be formatted into it, so every user needed their own warm copy of the
    # system+schema prefix and no user's traffic could warm another's
    # (measured in production: 87% of extraction calls read zero cached
    # tokens). One universal prompt is the only version an upstream has to
    # hold; the name rides the volatile tail instead.
    system_prompt = EXTRACTION_SYSTEM_PROMPT
    # The volatile context (the user's name, today's date, the journal, the
    # folder tree, the recently stored facts) rides in a TRAILING message, NOT
    # inside the system prompt: the memory lane's cache is a byte-prefix
    # cache, and with these churning inside the system prompt the prefix broke
    # there and the whole (append-only) transcript re-sent uncached every turn
    # — measured ~41% hit on the lane.
    #
    # WITHIN the tail, order is by churn rate, slowest first, because the tail
    # is over half of a real extraction call (measured live: the cached prefix
    # stops at system+transcript, ~47%). The name never changes; the date is
    # stable all day; the journal only APPENDS during a day; the folder tree
    # gains a line rarely; the recent-facts window ROLLS on every ingestion
    # and the hints are per-run. With the rolling window ahead of the journal,
    # one new fact re-sent the whole journal on every extraction.
    volatile_context = (
        f"The user in this transcript (`user:`) is {user_name}. "
        "Write every fact using this real name.\n"
        f"Today is {current_date:%A, %d %B %Y}.\n"
        "## Today's journal so far (do NOT repeat these events, even reworded)\n"
        f"{journal_section}\n"
        + EXTRACTION_FOLDER_TREE_BLOCK.format(folder_tree=folder_tree or "(no folders yet)")
        + f"\n## Recently stored facts (do NOT re-extract these)\n{recent_facts_section}"
        + hints_section
    )

    result = await _invoke_structured(
        ExtractedMemoryBatch,
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=transcript),
            HumanMessage(content=volatile_context),
        ],
        operation="extraction",
        user_id=user_id,
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
    user_id: str,
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
        user_id=user_id,
    )


async def summarize_episode_entries(entries: list[str], *, user_id: str) -> str | None:
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
        user_id=user_id,
    )
    return result.summary if result else None


async def rewrite_core_document(system_prompt: str, inputs: str, *, user_id: str) -> str | None:
    """Rewrite one core memory document from its inputs (consolidation pass).

    Returns None on total LLM failure — the document simply keeps its
    previous version until the next consolidation.
    """
    result = await _invoke_structured(
        ConsolidatedDocument,
        [SystemMessage(content=system_prompt), HumanMessage(content=inputs)],
        operation="consolidate",
        user_id=user_id,
    )
    return result.content if result else None


async def verify_core_document(
    content: str, facts: list[str], *, user_id: str
) -> VerifiedDocument | None:
    """Strike document lines the source facts do not support (consolidation pass).

    Returns None on total LLM failure — the caller keeps the unverified
    document rather than losing the rewrite.
    """
    fact_lines = "\n".join(f"- {fact}" for fact in facts)
    return await _invoke_structured(
        VerifiedDocument,
        [
            SystemMessage(content=DOCUMENT_VERIFICATION_PROMPT),
            HumanMessage(content=f"## Document\n{content}\n\n## Source facts\n{fact_lines}"),
        ],
        operation="verify_document",
        user_id=user_id,
    )


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
    *,
    user_id: str,
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
        user_id=user_id,
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
