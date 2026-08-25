"""Core documents: the debounced LLM rewrites plus the rendered agenda.

Three of the four documents (``user.md``, ``memory.md``, ``people.md``) are
written by an LLM. After every ingestion the affected doc types are merged into
a per-user Redis pending set and a single in-process waiter sleeps out the
debounce window before rewriting them (plan F2.5). Each rewrite is fed the
document's WHOLE live fact corpus — not a recency window — because a rewrite
that cannot see the fact it corrupted can never be corrected by it. The result
is size-checked, then fact-checked against those same facts, before it lands
through ``management.update_document``.

``agenda.md`` is not written by an LLM at all: it is rendered from the agenda
memory rows, so every item on it can be searched, corrected, superseded and
expired like any other memory.
"""

import asyncio
import contextlib
from datetime import UTC, datetime
import time

from app.constants.memory import (
    AGENDA_CATEGORY_PATH,
    AGENDA_INJECTED_ITEM_CAP,
    CONSOLIDATION_DEBOUNCE_SECONDS,
    CONSOLIDATION_FACTS_LIMIT,
    CONSOLIDATION_PENDING_KEY,
    CONSOLIDATION_PENDING_TTL,
    DOCUMENT_TARGET_MAX_CHARS,
    MemoryDocType,
    MemoryEntityType,
    MemoryShelfLife,
)
from app.db.redis import delete_cache, get_and_delete_cache, get_cache, set_cache
from app.db.repositories.users import user_repository
from app.memory import pg_store
from app.memory.extraction import rewrite_core_document, verify_core_document
from app.memory.management import update_document
from app.memory.prompts import (
    MEMORY_DOC_CONSOLIDATION_PROMPT,
    PEOPLE_DOC_CONSOLIDATION_PROMPT,
    USER_DOC_CONSOLIDATION_PROMPT,
)
from app.memory.schemas import ExtractedFact
from app.models.memory_db_models import MemoryRecord
from shared.py.wide_events import MemoryContext, UserContext, log, wide_task

# Which core documents a fact feeds, keyed by its top-level category folder.
# Folders not listed here default to user.md (general life context). The agenda
# folder maps to nothing on purpose: agenda.md is rendered from its rows, never
# consolidated, so an agenda item must not also leak into user.md.
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
    "routines": (MemoryDocType.USER_MD,),
    "projects": (MemoryDocType.USER_MD,),
    "goals": (MemoryDocType.USER_MD,),
    AGENDA_CATEGORY_PATH: (),
    "commitments": (),
    "deadlines": (),
}
_DEFAULT_FACT_DOCS: tuple[MemoryDocType, ...] = (MemoryDocType.USER_MD,)

_DOC_PROMPTS: dict[MemoryDocType, str] = {
    MemoryDocType.USER_MD: USER_DOC_CONSOLIDATION_PROMPT,
    MemoryDocType.MEMORY_MD: MEMORY_DOC_CONSOLIDATION_PROMPT,
    MemoryDocType.PEOPLE_MD: PEOPLE_DOC_CONSOLIDATION_PROMPT,
}

# Pending-set payload key (Redis JSON).
_PENDING_DOC_TYPES = "doc_types"

_AGENDA_DOC_HEADING = "# Current agenda"
_AGENDA_EMPTY_BODY = "- (nothing open)"

# One live debounce waiter per user, in-process (same pattern as the
# memory_node background-task set). A process restart during the sleep loses
# the pending debounce — acceptable: the next ingestion reschedules it and
# the documents converge.
_waiters: dict[str, asyncio.Task] = {}


def infer_doc_types(facts: list[ExtractedFact]) -> set[MemoryDocType]:
    """Which LLM-written core documents this ingestion's facts touch.

    Only durable facts qualify. A ``state`` value ("18 workflows active") must
    never be consolidated into a document that is injected into every prompt,
    and ``task``/``journal`` assertions are not facts at all by the time they
    get here — they were routed to the agenda and the journal upstream.
    """
    doc_types: set[MemoryDocType] = set()
    for fact in facts:
        if fact.shelf_life is not MemoryShelfLife.DURABLE:
            continue
        top_folder = fact.category_path.split("/", 1)[0]
        doc_types.update(CATEGORY_DOC_MAP.get(top_folder, _DEFAULT_FACT_DOCS))
    return doc_types


async def schedule_consolidation(user_id: str, doc_types: set[MemoryDocType]) -> None:
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
        )
    }
    await set_cache(key, merged, ttl=CONSOLIDATION_PENDING_TTL)

    if user_id not in _waiters:
        try:
            _waiters[user_id] = asyncio.create_task(_debounce_waiter(user_id))
        except RuntimeError as e:
            # No running loop (e.g. shutdown in progress): the pending set
            # survives in Redis and the next ingestion reschedules.
            log.warning("memory_consolidation_waiter_unscheduled", user_id=user_id, error=str(e))


async def cancel_consolidation(user_id: str) -> None:
    """Cancel a pending consolidation and drop its Redis state.

    Called when a user's memories are wiped: without this, a sleeping waiter
    would wake to an empty store and overwrite the (already cleared) core
    documents with skeletons.
    """
    waiter = _waiters.pop(user_id, None)
    if waiter is not None:
        waiter.cancel()
    await delete_cache(CONSOLIDATION_PENDING_KEY.format(user_id=user_id))


async def _debounce_waiter(user_id: str) -> None:
    """Sleep out the debounce window, then consume the pending set and consolidate.

    Runs in its own ``wide_task`` scope: this is a fire-and-forget background
    task with no request middleware, so the scope is what makes consolidation
    outcomes and failures emit a queryable wide event.
    """
    try:
        # wide_task emits any failure (error_type + outcome=failed) as a wide
        # event + error line; suppress the re-raise so this fire-and-forget task
        # stays quiet (it must not crash the event loop).
        with contextlib.suppress(Exception):
            async with wide_task("memory_consolidation", user=UserContext(id=user_id)):
                await asyncio.sleep(CONSOLIDATION_DEBOUNCE_SECONDS)
                pending = await get_and_delete_cache(
                    CONSOLIDATION_PENDING_KEY.format(user_id=user_id)
                )
                if not pending:
                    return
                doc_types = [MemoryDocType(value) for value in pending.get(_PENDING_DOC_TYPES, [])]
                if doc_types:
                    await consolidate(user_id, doc_types)
    finally:
        _waiters.pop(user_id, None)


async def consolidate(
    user_id: str, doc_types: list[MemoryDocType] | None = None
) -> list[MemoryDocType]:
    """Rewrite the given core documents (default: every LLM-written one).

    Returns the doc types actually rewritten. Skips a document when there is
    nothing to write it from (no inputs and no previous version), when the LLM
    fails, or when the result will not fit the size cap — in every case the
    previous version stays, because a stale document beats a truncated one.
    """
    started = time.perf_counter()
    targets = doc_types if doc_types is not None else list(_DOC_PROMPTS)
    outcomes: dict[str, str] = {}
    rewritten: list[MemoryDocType] = []

    user_name = await _get_user_name(user_id)
    for doc_type in targets:
        if doc_type not in _DOC_PROMPTS:
            # agenda.md is rendered from its rows, never consolidated.
            continue
        previous = await pg_store.get_document(user_id, doc_type)
        previous_content = previous.content if previous else ""
        facts = await _gather_facts(user_id, doc_type)
        inputs = await _gather_inputs(user_id, doc_type, facts)
        if not inputs and not previous_content.strip():
            outcomes[doc_type.value] = "skipped"
            continue

        content = await _rewrite_within_cap(
            user_id, doc_type, previous_content, inputs, user_name=user_name
        )
        if content is None:
            outcomes[doc_type.value] = "failed"
            continue

        content = await _strike_unsupported(user_id, doc_type, content, facts)
        await update_document(user_id, doc_type, content)
        outcomes[doc_type.value] = "rewritten"
        rewritten.append(doc_type)

    log.set(
        memory=MemoryContext(
            operation="consolidate",
            result_count=len(rewritten),
            doc_types=[doc_type.value for doc_type in targets],
            outcomes=outcomes,
            success="failed" not in outcomes.values(),
            timings={"total_ms": (time.perf_counter() - started) * 1000},
        ),
    )
    return rewritten


async def render_agenda_document(user_id: str) -> None:
    """Rewrite agenda.md from the user's live agenda rows — no LLM involved.

    The agenda used to be an LLM-maintained document fed by a Redis
    side-channel, which meant no tool could correct an item and nothing could
    expire one. Rendering from rows makes every line a real memory: searchable,
    correctable with update_memory, retired by ``forget_memory`` when the
    conversation closes it, and swept when it ages out.
    """
    rows = await pg_store.get_agenda_memories(user_id, limit=AGENDA_INJECTED_ITEM_CAP)
    lines = [f"- {row.content}" for row in rows] or [_AGENDA_EMPTY_BODY]
    await update_document(
        user_id, MemoryDocType.AGENDA_MD, "\n".join([_AGENDA_DOC_HEADING, *lines])
    )


async def _rewrite_within_cap(
    user_id: str,
    doc_type: MemoryDocType,
    previous_content: str,
    inputs: list[str],
    *,
    user_name: str,
) -> str | None:
    """One rewrite, retried once when it blows the size cap. None when unusable.

    The cap was previously only interpolated into the prompt and never checked,
    so a document that ignored it was written anyway (production agenda.md:
    4,886 characters against a 2,500 cap, injected into every single turn).
    """
    system_prompt = _system_prompt(doc_type, user_name)
    human = _format_inputs(previous_content, inputs)

    for attempt in range(2):
        content = await rewrite_core_document(system_prompt, human, user_id=user_id)
        if content is None or not content.strip():
            log.warning(
                "memory_consolidation_doc_failed",
                user_id=user_id,
                doc_type=doc_type.value,
                error_type="llm_returned_empty",
            )
            return None
        content = content.strip()
        if len(content) <= DOCUMENT_TARGET_MAX_CHARS:
            return content
        log.warning(
            "memory_consolidation_doc_over_cap",
            user_id=user_id,
            doc_type=doc_type.value,
            error_type="document_over_cap",
            chars=len(content),
            cap=DOCUMENT_TARGET_MAX_CHARS,
            attempt=attempt + 1,
        )
        human = (
            f"{human}\n\n## Your previous attempt was too long\n"
            f"It was {len(content)} characters against a hard cap of "
            f"{DOCUMENT_TARGET_MAX_CHARS}. Rewrite it under the cap by dropping "
            "the least important bullets — do not truncate mid-sentence, and do "
            "not drop a section heading."
        )
    return None


async def _strike_unsupported(
    user_id: str, doc_type: MemoryDocType, content: str, facts: list[MemoryRecord]
) -> str:
    """Remove lines the source facts do not support. Returns the kept document.

    One extra structured call per rewrite. Consolidation is the only place a
    fact can silently mutate — the always-injected user.md said "Partner: Khyal
    Shetal (anniversary Oct 19, 2026)" while five live memories said "Khyati
    Sheth ... October 19, 2022" — and nothing downstream can tell a corrupted
    document from a correct one. On LLM failure the unverified document stands:
    a document that skipped its check beats no document.
    """
    if not facts:
        return content
    verified = await verify_core_document(
        content, [fact.content for fact in facts], user_id=user_id
    )
    if verified is None or not verified.content.strip():
        log.warning(
            "memory_consolidation_verification_failed",
            user_id=user_id,
            doc_type=doc_type.value,
            error_type="llm_returned_empty",
        )
        return content
    if verified.struck:
        log.warning(
            "memory_consolidation_struck_unsupported",
            user_id=user_id,
            doc_type=doc_type.value,
            error_type="unsupported_document_lines",
            struck_count=len(verified.struck),
        )
    return verified.content.strip()


def _system_prompt(doc_type: MemoryDocType, user_name: str) -> str:
    """The consolidation system prompt for one doc, with shared fields filled."""
    return _DOC_PROMPTS[doc_type].format(
        max_chars=DOCUMENT_TARGET_MAX_CHARS,
        current_date=f"{datetime.now(UTC):%A, %d %B %Y}",
        user_name=user_name,
    )


async def _get_user_name(user_id: str) -> str:
    """The user's display name, so prompts can tell the user apart from others."""
    try:
        user = await user_repository.get(user_id)
    except Exception:
        user = None
    return (user.name if user else None) or "the user"


def _prefixes_for(doc_type: MemoryDocType) -> list[str]:
    """Category folders that feed this document, per ``CATEGORY_DOC_MAP``."""
    return [prefix for prefix, docs in CATEGORY_DOC_MAP.items() if doc_type in docs]


async def _gather_facts(user_id: str, doc_type: MemoryDocType) -> list[MemoryRecord]:
    """Every live DURABLE fact this document is written from.

    Not a recency window: a rewrite fed only the 50 freshest facts can never be
    contradicted by the fact it corrupted, so a bad name or date survives every
    subsequent pass. ``CONSOLIDATION_FACTS_LIMIT`` is a safety valve, not a
    window.
    """
    prefixes = None if doc_type is MemoryDocType.USER_MD else _prefixes_for(doc_type)
    return await pg_store.get_facts_for_consolidation(
        user_id,
        category_prefixes=prefixes,
        shelf_life=MemoryShelfLife.DURABLE.value,
        limit=CONSOLIDATION_FACTS_LIMIT,
    )


async def _gather_inputs(
    user_id: str, doc_type: MemoryDocType, facts: list[MemoryRecord]
) -> list[str]:
    """Assemble the fresh-input sections for one document rewrite."""
    sections = _facts_section(facts)

    if doc_type is MemoryDocType.PEOPLE_MD:
        people = await pg_store.get_entities_by_type(user_id, MemoryEntityType.PERSON.value)
        if people:
            names = "\n".join(f"- {entity.name}" for entity in people)
            sections.append(f"## Known people (entity register)\n{names}")

    return sections


def _facts_section(facts: list[MemoryRecord]) -> list[str]:
    """Render fact rows as one input section (empty list when there are none)."""
    if not facts:
        return []
    lines = "\n".join(f"- {fact.content} (stored {fact.created_at:%Y-%m-%d})" for fact in facts)
    return [f"## Every fact this document is written from\n{lines}"]


def _format_inputs(previous_content: str, sections: list[str]) -> str:
    """The human message for one rewrite: previous version + the fact corpus."""
    previous_block = previous_content.strip() or "(no previous version)"
    inputs_block = "\n\n".join(sections) if sections else "(no facts)"
    return (
        "## Previous version of the document (a draft — the facts below outrank it)\n"
        f"{previous_block}\n\n{inputs_block}"
    )
