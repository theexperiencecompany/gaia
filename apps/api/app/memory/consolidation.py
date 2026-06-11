"""Core-document consolidation: debounced LLM rewrites of the user's docs.

After every ingestion the affected doc types are merged into a per-user
Redis pending set and a single in-process waiter sleeps out the debounce
window before rewriting them (plan F2.5). Each rewrite is one structured
LLM call fed by the previous version plus fresh inputs from Postgres, and
lands through ``management.update_document`` (versioned, invalidates the
hot core context, reschedules the workspace projection).
"""

import asyncio
from datetime import UTC, datetime, timedelta
import time

from app.constants.memory import (
    CONSOLIDATION_DEBOUNCE_SECONDS,
    CONSOLIDATION_EPISODE_DAYS,
    CONSOLIDATION_FACTS_LIMIT,
    CONSOLIDATION_PENDING_KEY,
    CONSOLIDATION_PENDING_TTL,
    DOCUMENT_TARGET_MAX_CHARS,
    MemoryDocType,
    MemoryEntityType,
    MemoryKind,
)
from app.db.redis import get_and_delete_cache, get_cache, set_cache
from app.memory import pg_store
from app.memory.extraction import rewrite_core_document
from app.memory.management import update_document
from app.memory.prompts import (
    AGENDA_DOC_CONSOLIDATION_PROMPT,
    INSIGHTS_DOC_CONSOLIDATION_PROMPT,
    MEMORY_DOC_CONSOLIDATION_PROMPT,
    PEOPLE_DOC_CONSOLIDATION_PROMPT,
    USER_DOC_CONSOLIDATION_PROMPT,
)
from app.memory.schemas import ExtractedFact
from app.models.memory_db_models import MemoryRecord
from shared.py.wide_events import log

# Which core documents a fact feeds, keyed by its top-level category folder.
# Folders not listed here default to user.md (general life context); facts of
# kind 'experience' always feed insights.md regardless of folder.
CATEGORY_DOC_MAP: dict[str, tuple[MemoryDocType, ...]] = {
    "relationships": (MemoryDocType.PEOPLE_MD, MemoryDocType.USER_MD),
    "family": (MemoryDocType.PEOPLE_MD, MemoryDocType.USER_MD),
    "friends": (MemoryDocType.PEOPLE_MD, MemoryDocType.USER_MD),
    "people": (MemoryDocType.PEOPLE_MD, MemoryDocType.USER_MD),
    "contacts": (MemoryDocType.PEOPLE_MD,),
    "preferences": (MemoryDocType.MEMORY_MD,),
    "food-preferences": (MemoryDocType.MEMORY_MD,),
    "communication": (MemoryDocType.MEMORY_MD,),
    "conventions": (MemoryDocType.MEMORY_MD,),
    "work": (MemoryDocType.USER_MD,),
    "identity": (MemoryDocType.USER_MD,),
    "health": (MemoryDocType.USER_MD,),
    "education": (MemoryDocType.USER_MD,),
    "location": (MemoryDocType.USER_MD,),
    "routines": (MemoryDocType.USER_MD, MemoryDocType.INSIGHTS_MD),
    "projects": (MemoryDocType.USER_MD, MemoryDocType.AGENDA_MD),
    "goals": (MemoryDocType.AGENDA_MD, MemoryDocType.USER_MD),
    "commitments": (MemoryDocType.AGENDA_MD,),
    "deadlines": (MemoryDocType.AGENDA_MD,),
}
_DEFAULT_FACT_DOCS: tuple[MemoryDocType, ...] = (MemoryDocType.USER_MD,)

_DOC_PROMPTS: dict[MemoryDocType, str] = {
    MemoryDocType.USER_MD: USER_DOC_CONSOLIDATION_PROMPT,
    MemoryDocType.MEMORY_MD: MEMORY_DOC_CONSOLIDATION_PROMPT,
    MemoryDocType.AGENDA_MD: AGENDA_DOC_CONSOLIDATION_PROMPT,
    MemoryDocType.PEOPLE_MD: PEOPLE_DOC_CONSOLIDATION_PROMPT,
    MemoryDocType.INSIGHTS_MD: INSIGHTS_DOC_CONSOLIDATION_PROMPT,
}

# Pending-set payload keys (Redis JSON).
_PENDING_DOC_TYPES = "doc_types"
_PENDING_AGENDA_UPDATES = "agenda_updates"

# One live debounce waiter per user, in-process (same pattern as the
# memory_node background-task set). A process restart during the sleep loses
# the pending debounce — acceptable: the next ingestion reschedules it and
# the documents converge.
_waiters: dict[str, asyncio.Task] = {}


def infer_doc_types(facts: list[ExtractedFact], agenda_updates: list[str]) -> set[MemoryDocType]:
    """Which core documents this ingestion's changes touch."""
    doc_types: set[MemoryDocType] = set()
    for fact in facts:
        if fact.kind is MemoryKind.EXPERIENCE:
            doc_types.add(MemoryDocType.INSIGHTS_MD)
            continue
        top_folder = fact.category_path.split("/", 1)[0]
        doc_types.update(CATEGORY_DOC_MAP.get(top_folder, _DEFAULT_FACT_DOCS))
    if agenda_updates:
        doc_types.add(MemoryDocType.AGENDA_MD)
    return doc_types


async def schedule_consolidation(
    user_id: str,
    doc_types: set[MemoryDocType],
    *,
    agenda_updates: list[str] | None = None,
) -> None:
    """Debounce a consolidation: merge into the Redis pending set, ensure a waiter.

    If a waiter is already live for this user the merged pending set is
    picked up when it fires — repeated ingestions inside the window cost
    one consolidation, not one each.
    """
    if not doc_types:
        return
    key = CONSOLIDATION_PENDING_KEY.format(user_id=user_id)
    pending = await get_cache(key) or {}
    merged: dict[str, list[str]] = {
        _PENDING_DOC_TYPES: sorted(
            {*pending.get(_PENDING_DOC_TYPES, []), *(doc.value for doc in doc_types)}
        ),
        _PENDING_AGENDA_UPDATES: [
            *pending.get(_PENDING_AGENDA_UPDATES, []),
            *(agenda_updates or []),
        ],
    }
    await set_cache(key, merged, ttl=CONSOLIDATION_PENDING_TTL)

    if user_id not in _waiters:
        task = asyncio.create_task(_debounce_waiter(user_id))
        _waiters[user_id] = task


async def _debounce_waiter(user_id: str) -> None:
    """Sleep out the debounce window, then consume the pending set and consolidate."""
    try:
        await asyncio.sleep(CONSOLIDATION_DEBOUNCE_SECONDS)
        pending = await get_and_delete_cache(CONSOLIDATION_PENDING_KEY.format(user_id=user_id))
        if not pending:
            return
        doc_types = [MemoryDocType(value) for value in pending.get(_PENDING_DOC_TYPES, [])]
        agenda_updates = pending.get(_PENDING_AGENDA_UPDATES) or None
        if doc_types:
            await consolidate(user_id, doc_types, agenda_updates=agenda_updates)
    except Exception as e:  # noqa: BLE001 — fire-and-forget body must not crash
        log.warning(
            "memory_consolidation_failed",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
    finally:
        _waiters.pop(user_id, None)


async def consolidate(
    user_id: str,
    doc_types: list[MemoryDocType] | None = None,
    *,
    agenda_updates: list[str] | None = None,
) -> list[MemoryDocType]:
    """Rewrite the given core documents (default: all five) from fresh inputs.

    Returns the doc types actually rewritten. Skips a document when there is
    nothing to write it from (no inputs and no previous version) or when the
    LLM fails (the previous version stays).
    """
    started = time.perf_counter()
    targets = doc_types or list(MemoryDocType)
    outcomes: dict[str, str] = {}
    rewritten: list[MemoryDocType] = []

    for doc_type in targets:
        previous = await pg_store.get_document(user_id, doc_type)
        previous_content = previous.content if previous else ""
        inputs = await _gather_inputs(user_id, doc_type, agenda_updates or [])
        if not inputs and not previous_content.strip():
            outcomes[doc_type.value] = "skipped"
            continue

        content = await rewrite_core_document(
            _system_prompt(doc_type),
            _format_inputs(previous_content, inputs),
        )
        if content is None or not content.strip():
            outcomes[doc_type.value] = "failed"
            continue

        await update_document(user_id, doc_type, content.strip())
        outcomes[doc_type.value] = "rewritten"
        rewritten.append(doc_type)

    log.info(
        "memory_consolidation_completed",
        memory={
            "operation": "consolidate",
            "user_id": user_id,
            "outcomes": outcomes,
            "total_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return rewritten


def _system_prompt(doc_type: MemoryDocType) -> str:
    """The consolidation system prompt for one doc, with shared fields filled."""
    return _DOC_PROMPTS[doc_type].format(
        max_chars=DOCUMENT_TARGET_MAX_CHARS,
        current_date=f"{datetime.now(UTC):%A, %d %B %Y}",
    )


def _prefixes_for(doc_type: MemoryDocType) -> list[str]:
    """Category folders that feed this document, per ``CATEGORY_DOC_MAP``."""
    return [prefix for prefix, docs in CATEGORY_DOC_MAP.items() if doc_type in docs]


async def _gather_inputs(
    user_id: str, doc_type: MemoryDocType, agenda_updates: list[str]
) -> list[str]:
    """Assemble the fresh-input sections for one document rewrite."""
    sections: list[str] = []

    if doc_type is MemoryDocType.USER_MD:
        # user.md is the general life-context doc: feed it every fact-kind
        # memory so unmapped folders still reach a document.
        facts = await pg_store.get_facts_for_consolidation(
            user_id, kind=MemoryKind.FACT.value, limit=CONSOLIDATION_FACTS_LIMIT
        )
        sections.extend(_facts_section(facts))
    elif doc_type is MemoryDocType.INSIGHTS_MD:
        facts = await pg_store.get_facts_for_consolidation(
            user_id, kind=MemoryKind.EXPERIENCE.value, limit=CONSOLIDATION_FACTS_LIMIT
        )
        sections.extend(_facts_section(facts, heading="## Recent experiences"))
        sections.extend(await _episode_summaries_section(user_id))
    else:
        facts = await pg_store.get_facts_for_consolidation(
            user_id,
            category_prefixes=_prefixes_for(doc_type),
            limit=CONSOLIDATION_FACTS_LIMIT,
        )
        sections.extend(_facts_section(facts))

    if doc_type is MemoryDocType.PEOPLE_MD:
        people = await pg_store.get_entities_by_type(user_id, MemoryEntityType.PERSON.value)
        if people:
            names = "\n".join(f"- {entity.name}" for entity in people)
            sections.append(f"## Known people (entity register)\n{names}")

    if doc_type is MemoryDocType.AGENDA_MD and agenda_updates:
        updates = "\n".join(f"- {update}" for update in agenda_updates)
        sections.append(f"## Agenda updates from recent conversations\n{updates}")

    return sections


def _facts_section(facts: list[MemoryRecord], *, heading: str = "## Latest facts") -> list[str]:
    """Render fact rows as one input section (empty list when there are none)."""
    if not facts:
        return []
    lines = "\n".join(f"- {fact.content} (stored {fact.created_at:%Y-%m-%d})" for fact in facts)
    return [f"{heading}\n{lines}"]


async def _episode_summaries_section(user_id: str) -> list[str]:
    """Day summaries from the last ``CONSOLIDATION_EPISODE_DAYS`` days."""
    today = datetime.now(UTC).date()
    episodes = await pg_store.get_episodes_range(
        user_id, today - timedelta(days=CONSOLIDATION_EPISODE_DAYS), today
    )
    summaries = [
        f"- {episode.date.isoformat()}: {episode.summary}"
        for episode in episodes
        if episode.summary
    ]
    if not summaries:
        return []
    return ["## Recent day summaries\n" + "\n".join(summaries)]


def _format_inputs(previous_content: str, sections: list[str]) -> str:
    """The human message for one rewrite: previous version + fresh inputs."""
    previous_block = previous_content.strip() or "(no previous version)"
    inputs_block = "\n\n".join(sections) if sections else "(no new inputs)"
    return f"## Previous version of the document\n{previous_block}\n\n{inputs_block}"
