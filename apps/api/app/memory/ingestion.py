"""The memory write path: extract -> embed -> reconcile -> apply -> journal.

``retain`` is the single ingestion pipeline, designed to run fire-and-forget
after a turn ends — it never raises into callers for LLM failures
(extraction degrades to an empty batch upstream). Every ingestion schedules
the hash-gated ``/workspace/memory`` projection sync and a debounced
core-document consolidation for the docs its changes touch.
"""

from dataclasses import dataclass
from datetime import UTC, date as date_type, datetime, timedelta
import time
import uuid

from app.constants.memory import (
    AGENDA_CATEGORY_PATH,
    AGENDA_ITEM_TTL_DAYS,
    CATEGORY_PATH_MAX_DEPTH,
    DEFAULT_MEMORY_IMPORTANCE,
    EPISODE_ENTRY_TIME_FORMAT,
    FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN,
    FREE_MEMORY_FACT_LIMIT,
    RECENT_FACTS_LIMIT,
    RECONCILE_SIMILARITY_THRESHOLD,
    STATE_FACT_TTL_DAYS,
    TRANSCRIPT_CHUNK_MAX_CHARS,
    TRANSCRIPT_CHUNK_OVERLAP_CHARS,
    TRANSCRIPT_CHUNK_TURNS,
    TRANSCRIPT_CHUNKS_PER_SESSION_CAP,
    MemoryKind,
    MemoryRelationType,
    MemoryShelfLife,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory import cap_counter, chroma_store, pg_store
from app.memory.chroma_store import ConversationChunkItem, EpisodeVectorItem, MemoryVectorItem
from app.memory.consolidation import infer_doc_types, render_agenda_document, schedule_consolidation
from app.memory.context import invalidate_user_memory_caches
from app.memory.embeddings import embed_batch, embed_query
from app.memory.extraction import categorize_fact, extract_memories, summarize_episode_entries
from app.memory.management import forget_memory
from app.memory.mappers import row_to_entry
from app.memory.reconciliation import ReconciledFact, reconcile
from app.memory.schemas import ExtractedFact, ExtractedMemoryBatch
from app.models.memory_db_models import MemoryRecord
from app.models.memory_models import MemoryEntry
from app.models.payment_models import PlanType
from app.services.memory_fs import schedule_memory_vfs_sync
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import MemoryContext, UserContext, log

_DEFAULT_USER_NAME = "the user"
_FALLBACK_CATEGORY_PATH = "general"


class MemoryLimitReachedError(Exception):
    """An explicit memory add was blocked by the free plan's live-fact cap.

    Raised only by ``retain_single`` (add_memory tool / POST endpoint) so the
    caller can surface an upgrade prompt. Passive ingestion never raises — it
    silently drops NEW facts at the cap (see ``retain``).
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(
            f"Free plan memory limit reached ({limit} saved memories). "
            "Upgrade to Pro for unlimited memories."
        )


async def _free_cap_remaining(user_id: str, growth: int) -> int | None:
    """How many more live facts a FREE user may add, or ``None`` when uncapped.

    ``None`` means no cap applies — a paid plan, or an infra error during the
    plan lookup (fail open: memory must not stop working because the plan
    lookup hiccuped). For a free user it is ``max(0, limit - live count)``, so
    a batch that would cross the cap can be trimmed to land exactly at it.

    ``growth`` is how many facts this call would add (the NEW count for a
    batch, 1 for a single add). The live count comes from the Redis counter
    (``cap_counter``) on the hot path, avoiding a Postgres ``COUNT`` when a free
    user sits far below the cap. The cache is trusted only when the remaining
    budget clears ``growth`` plus a safety margin; when the batch might cross
    the cap, the counter is missing, or Redis is down, it falls back to the
    authoritative ``COUNT`` (and re-seeds the counter), so the hard cap is exact.

    Uses the cached plan lookup (Redis-backed) — retain() runs from many
    callers (chat turns, subagents, email ingestion, API endpoints), so
    resolving here keeps one canonical check instead of threading plan_type
    through every path.
    """
    try:
        plan = await payment_service.get_cached_plan_type(user_id)
    except Exception as e:
        log.warning(
            "Memory cap plan lookup failed (failing open)",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
    if plan != PlanType.FREE:
        return None

    cached = await cap_counter.get_cached_live_count(user_id)
    if cached is not None:
        remaining = max(0, FREE_MEMORY_FACT_LIMIT - cached)
        if remaining >= growth + FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN:
            return remaining

    # Near the cap, a cache miss, or Redis down: the COUNT is authoritative and
    # exact. Re-seed the counter so subsequent turns stay on the hot path.
    live = await pg_store.count_live_memories(user_id)
    await cap_counter.set_cached_live_count(user_id, live)
    return max(0, FREE_MEMORY_FACT_LIMIT - live)


def _enforce_free_cap(
    reconciled: list[ReconciledFact], remaining: int
) -> tuple[list[ReconciledFact], int]:
    """Trim growth facts to ``remaining`` free slots, preserving order.

    Admits at most ``remaining`` NEW facts (the only outcome that grows the
    live set) in reconciliation order and drops the surplus; UPDATES, EXTENDS
    and DUPLICATEs pass through untouched since each supersedes or collapses
    into an existing row. Returns the kept facts and how many were dropped.
    """
    kept: list[ReconciledFact] = []
    admitted = dropped = 0
    for item in reconciled:
        if item.outcome is ReconcileOutcome.NEW:
            if admitted >= remaining:
                dropped += 1
                continue
            admitted += 1
        kept.append(item)
    return kept, dropped


@dataclass
class RetainResult:
    """Counts of what one ingestion run did."""

    facts_extracted: int = 0
    new: int = 0
    updated: int = 0
    extended: int = 0
    duplicates: int = 0
    entities_linked: int = 0
    edges_added: int = 0
    episode_entries: int = 0


@dataclass
class RetainedMemory:
    """One explicitly stored fact plus how reconciliation resolved it."""

    entry: MemoryEntry
    outcome: ReconcileOutcome


@dataclass
class _ApplyResult:
    """Rows written by ``_apply_reconciled`` plus graph counts."""

    inserted: list[tuple[MemoryRecord, ExtractedFact]]
    duplicates: int
    new: int
    updated: int
    extended: int
    entities_linked: int = 0
    edges_added: int = 0


# A shelf life that expires maps to a flat window; durable and journal do not
# appear here because neither ever produces an expiring row.
# Reconcile outcomes that retire their target. Both write a new version onto
# the chain and flip the old row out of the live set; only the relation label
# differs, so history still says whether the world changed (UPDATES) or the
# same claim was merely restated more completely (EXTENDS).
_SUPERSESSION_RELATION: dict[ReconcileOutcome, MemoryRelationType] = {
    ReconcileOutcome.UPDATES: MemoryRelationType.UPDATES,
    ReconcileOutcome.EXTENDS: MemoryRelationType.EXTENDS,
}


_SHELF_LIFE_TTL_DAYS: dict[MemoryShelfLife, int] = {
    MemoryShelfLife.STATE: STATE_FACT_TTL_DAYS,
    MemoryShelfLife.TASK: AGENDA_ITEM_TTL_DAYS,
}


def _forget_after(shelf_life: MemoryShelfLife, since: datetime | None) -> datetime | None:
    """When a row stops being live — derived from shelf life, never from the LLM.

    The extractor used to pick expiry dates itself and almost never did (19 of
    1,028 production rows carried one), so every count, balance and connection
    status it stored stayed live forever.
    """
    ttl_days = _SHELF_LIFE_TTL_DAYS.get(shelf_life)
    if ttl_days is None:
        return None
    return (since or datetime.now(UTC)) + timedelta(days=ttl_days)


def _agenda_fact(item: str) -> ExtractedFact:
    """An agenda item as a memory row: a task-shelf-life fact in the agenda folder."""
    return ExtractedFact(
        content=item,
        kind=MemoryKind.FACT,
        shelf_life=MemoryShelfLife.TASK,
        category_path=AGENDA_CATEGORY_PATH,
        importance=DEFAULT_MEMORY_IMPORTANCE,
    )


def _route_by_shelf_life(batch: ExtractedMemoryBatch) -> tuple[ExtractedMemoryBatch, list[str]]:
    """Send every assertion to the store its shelf life says owns it.

    ``task`` and ``journal`` never become plain facts: a commitment becomes an
    agenda row and anything that merely happened — including everything GAIA
    itself recommended, drafted or advised — becomes a journal line. Agenda
    items go through the normal fact pipeline (so they are embedded, deduped
    and correctable) rather than the old Redis side-channel, which no tool
    could reach.

    Returns the rewritten batch plus the agenda items this conversation
    CLOSED; those retire an existing row instead of writing a new one.
    """
    facts: list[ExtractedFact] = []
    episode_entries = list(batch.episode_entries)
    agenda_items = [update.item for update in batch.agenda_updates if not update.resolved]
    resolved = [update.item for update in batch.agenda_updates if update.resolved]

    for fact in batch.facts:
        match fact.shelf_life:
            case MemoryShelfLife.TASK:
                agenda_items.append(fact.content)
            case MemoryShelfLife.JOURNAL:
                episode_entries.append(fact.content)
            case _:
                facts.append(fact)

    facts.extend(_agenda_fact(item) for item in agenda_items)
    return ExtractedMemoryBatch(facts=facts, episode_entries=episode_entries), resolved


async def _close_resolved_agenda_items(user_id: str, items: list[str]) -> int:
    """Retire the live agenda rows this conversation closed; returns how many.

    Matching is semantic, not textual: the extractor restates a commitment in
    its own words when it closes it, so the closure is embedded and matched the
    same way reconciliation matches a new fact against existing ones.
    """
    if not items:
        return 0
    embeddings = await embed_batch(items)
    closed = 0
    for item, embedding in zip(items, embeddings):
        similar = await chroma_store.query_similar(user_id, embedding, n=1, only_latest=True)
        if not similar or similar[0][1] < RECONCILE_SIMILARITY_THRESHOLD:
            continue
        memory_id = similar[0][0]
        rows = await pg_store.get_memories_by_ids(user_id, [memory_id])
        if not rows or rows[0].category_path != AGENDA_CATEGORY_PATH:
            continue
        if await forget_memory(user_id, memory_id, f"agenda item resolved: {item}"):
            closed += 1
    return closed


async def retain(
    user_id: str,
    messages: list[dict[str, str]],
    *,
    source_type: MemorySourceType,
    source_id: str | None = None,
    extraction_hints: str | None = None,
    user_name: str | None = None,
    now: datetime | None = None,
) -> RetainResult:
    """Ingest a conversation transcript into long-term memory.

    ``now`` overrides the ingestion timestamp used for relative-date
    resolution, ``mentioned_at`` (recency), and the journal day — letting
    callers replay historical sessions (backfills, benchmarks) at their real
    time. Defaults to the current UTC time.
    """
    timings: dict[str, int] = {}
    started = time.perf_counter()
    now = now or datetime.now(UTC)

    # Set operation context up front so a mid-ingest failure still attributes
    # the wide event to a retain (the completion set below replaces this).
    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(operation="retain", source_type=source_type.value),
    )

    folder_tree = await pg_store.get_folder_tree(user_id)
    recent_facts = await pg_store.get_recent_facts(user_id, limit=RECENT_FACTS_LIMIT)
    today_episode = await pg_store.get_episode(user_id, now.date())
    journaled_today = (
        [entry.get("text", "") for entry in today_episode.entries] if today_episode else []
    )
    timings["context_ms"] = _elapsed_ms(started)

    stage = time.perf_counter()
    batch = await extract_memories(
        messages,
        user_id=user_id,
        user_name=user_name or _DEFAULT_USER_NAME,
        folder_tree=_format_folder_tree(folder_tree),
        recent_facts=recent_facts,
        journaled_today=journaled_today,
        extraction_hints=extraction_hints,
        current_date=now,
    )
    timings["extract_ms"] = _elapsed_ms(stage)

    if source_type is MemorySourceType.EMAIL:
        # A mailbox (especially a founder's or support address) is not the
        # user's diary or to-do list — "respond to customer X", "resolve
        # ticket Y" are an inbound queue, not the user's agenda or journal.
        # Email ingestion contributes durable facts about the user only; the
        # extraction prompt is responsible for not storing inbound senders.
        batch.episode_entries = []
        batch.agenda_updates = []

    batch, resolved_agenda = _route_by_shelf_life(batch)

    result = RetainResult(facts_extracted=len(batch.facts))
    if not batch.facts and not batch.episode_entries and not resolved_agenda:
        log.set(
            memory=MemoryContext(
                operation="retain",
                source_type=source_type.value,
                facts_extracted=0,
                result_count=0,
                success=True,
            )
        )
        return result

    stage = time.perf_counter()
    embeddings = await embed_batch([fact.content for fact in batch.facts])
    timings["embed_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    reconciled = await reconcile(user_id, batch.facts, embeddings)
    timings["reconcile_ms"] = _elapsed_ms(stage)

    # Free-plan cap: passive ingestion admits only as many NEW facts as fit
    # under the cap and silently drops the rest, so a
    # batch that crosses the cap lands exactly at it rather than overshooting
    # (48 live + 10 new must not become 58). Concurrent same-user batches can
    # transiently exceed the cap by a few facts (the check is not a reservation
    # by design — enforcement stays fail-open), after which growth stops, so
    # the cap is exact per batch and convergent, not globally atomic. UPDATES
    # and EXTENDS supersede (net count unchanged) so what GAIA knows stays
    # current, and
    # reads are never gated — the cap blocks growth, it does not lobotomize.
    # Facts keep reconciliation order (input order), so earlier facts in the
    # transcript win the remaining slots deterministically.
    growth = sum(1 for item in reconciled if item.outcome is ReconcileOutcome.NEW)
    remaining = await _free_cap_remaining(user_id, growth)
    if remaining is not None:
        reconciled, dropped = _enforce_free_cap(reconciled, remaining)
        if dropped:
            log.info(
                "memory_cap_reached",
                event_name="memory_cap_reached",
                user_id=user_id,
                dropped=dropped,
                limit=FREE_MEMORY_FACT_LIMIT,
            )

    stage = time.perf_counter()
    applied = await _apply_reconciled(
        user_id, reconciled, source_type=source_type, source_id=source_id, mentioned_at=now
    )
    result.new = applied.new
    result.updated = applied.updated
    result.extended = applied.extended
    result.duplicates = applied.duplicates
    result.entities_linked = applied.entities_linked
    result.edges_added = applied.edges_added
    timings["apply_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    result.episode_entries = await _append_episode_entries(
        user_id, batch.episode_entries, source_type=source_type, now=now
    )
    await _summarize_rolled_over_days(user_id, today=now.date())
    timings["episodes_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    await _store_conversation_chunks(user_id, messages, source_id=source_id, now=now)
    timings["chunks_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    closed = await _close_resolved_agenda_items(user_id, resolved_agenda)
    agenda_touched = closed > 0 or any(
        fact.shelf_life is MemoryShelfLife.TASK for _, fact in applied.inserted
    )
    if agenda_touched:
        await render_agenda_document(user_id)
    timings["agenda_ms"] = _elapsed_ms(stage)

    await invalidate_user_memory_caches(user_id)
    await _schedule_post_ingest(user_id, inserted_facts=[fact for _, fact in applied.inserted])

    timings["total_ms"] = _elapsed_ms(started)
    log.set(
        memory=MemoryContext(
            operation="retain",
            source_type=source_type.value,
            facts_extracted=result.facts_extracted,
            result_count=result.new + result.updated + result.extended,
            new_count=result.new,
            updated_count=result.updated,
            extended_count=result.extended,
            duplicate_count=result.duplicates,
            entities_linked=result.entities_linked,
            edges_added=result.edges_added,
            episode_entries=result.episode_entries,
            success=True,
            timings={key: float(value) for key, value in timings.items()},
        ),
    )
    return result


async def retain_single(
    user_id: str,
    content: str,
    *,
    category_path: str | None = None,
    source_type: MemorySourceType,
) -> RetainedMemory:
    """Store one explicit fact (add_memory tool / POST endpoint).

    Skips transcript extraction. When no folder is given, one small
    categorize LLM call assigns folder/kind/importance/entities — the
    full extraction prompt is tuned to filter conversational noise and
    could drop an explicitly requested fact, so it is not reused here.

    Raises ``MemoryLimitReachedError`` when a free user at the live-fact cap
    tries to add a fact that would GROW the set — explicit adds fail LOUD so
    the tool/endpoint can upsell, unlike passive ingestion which drops
    silently. A DUPLICATE, UPDATES or EXTENDS resolves to zero growth and
    stays allowed at the cap, so the outcome is known only after
    reconciliation.
    """
    now = datetime.now(UTC)
    fact = await _build_single_fact(user_id, content, category_path, now)

    embeddings = await embed_batch([fact.content])
    reconciled = await reconcile(user_id, [fact], embeddings)
    if not reconciled:
        # reconcile() drops facts the batched LLM returned no verdict for.
        raise ValueError("Memory could not be reconciled against existing memories")

    is_growth = reconciled[0].outcome is ReconcileOutcome.NEW
    if is_growth:
        remaining = await _free_cap_remaining(user_id, growth=1)
        if remaining is not None and remaining <= 0:
            raise MemoryLimitReachedError(FREE_MEMORY_FACT_LIMIT)

    applied = await _apply_reconciled(user_id, reconciled, source_type=source_type, source_id=None)
    await invalidate_user_memory_caches(user_id)
    await _schedule_post_ingest(
        user_id, inserted_facts=[inserted_fact for _, inserted_fact in applied.inserted]
    )

    if applied.inserted:
        row = applied.inserted[0][0]
    else:
        # DUPLICATE: surface the existing memory it collapsed into.
        target_id = reconciled[0].target_memory_id
        existing = await pg_store.get_memory(target_id, user_id) if target_id else None
        if existing is None:
            raise ValueError("Memory was deduplicated but its target no longer exists")
        row = existing

    entities = await pg_store.get_entities_for_memories([row.id])
    return RetainedMemory(
        entry=row_to_entry(row, entities.get(row.id, [])),
        outcome=reconciled[0].outcome,
    )


async def summarize_episode(user_id: str, date: date_type) -> None:
    """Summarize one journal day and embed the summary (day rollover).

    Lives here (not consolidation.py) because rollover is part of the
    ingestion flow: it fires lazily on the first retain of a new day,
    while consolidation is a separate debounced pass over the core docs.
    """
    episode = await pg_store.get_episode(user_id, date)
    if episode is None or episode.summary or not episode.entries:
        return

    lines = [f"{entry.get('time', '')} {entry.get('text', '')}" for entry in episode.entries]
    summary = await summarize_episode_entries(lines, user_id=user_id)
    if summary is None:
        return

    await pg_store.set_episode_summary(user_id, date, summary)
    embedding = await embed_query(summary)
    item: EpisodeVectorItem = {
        "id": f"{user_id}:{date.isoformat()}",
        "embedding": embedding,
        "document": summary,
        "metadata": {"user_id": user_id, "date": date.isoformat()},
    }
    await chroma_store.upsert_episode(item)


async def _build_single_fact(
    user_id: str,
    content: str,
    category_path: str | None,
    now: datetime,
) -> ExtractedFact:
    """Build the ExtractedFact for a manual add, categorizing if needed.

    An explicit add is always durable: the user (or the agent on their behalf)
    asked for this to be remembered, so it must never expire on its own.
    """
    if category_path is not None:
        return ExtractedFact(
            content=content,
            kind=MemoryKind.FACT,
            shelf_life=MemoryShelfLife.DURABLE,
            category_path=category_path,
            importance=DEFAULT_MEMORY_IMPORTANCE,
        )

    folder_tree = await pg_store.get_folder_tree(user_id)
    categorization = await categorize_fact(
        content,
        user_id=user_id,
        folder_tree=_format_folder_tree(folder_tree),
        current_date=now,
    )
    if categorization is None:
        return ExtractedFact(
            content=content,
            kind=MemoryKind.FACT,
            shelf_life=MemoryShelfLife.DURABLE,
            category_path=_FALLBACK_CATEGORY_PATH,
            importance=DEFAULT_MEMORY_IMPORTANCE,
        )
    return ExtractedFact(
        content=content,
        kind=categorization.kind,
        shelf_life=MemoryShelfLife.DURABLE,
        category_path=categorization.category_path,
        importance=categorization.importance,
        entities=categorization.entities,
        edges=categorization.edges,
    )


async def _apply_reconciled(
    user_id: str,
    reconciled: list[ReconciledFact],
    *,
    source_type: MemorySourceType,
    source_id: str | None,
    mentioned_at: datetime | None = None,
) -> _ApplyResult:
    """Write reconciled facts to Postgres + Chroma and wire up the graph.

    EXTENDS supersedes its parent exactly like UPDATES. It used to coexist with
    it — "the new fact is distinct" — and the result in production was 329 live
    rows (36% of the store) that were EXTENDS children of a still-live parent,
    every pair injected into recall as two competing versions of one attribute.
    A more complete restatement of the same subject-attribute is a revision, so
    the parent moves into history and only the complete form stays live.
    """
    inserted: list[tuple[MemoryRecord, ExtractedFact]] = []
    new = updated = extended = duplicates = 0

    fresh: list[tuple[MemoryRecord, ExtractedFact]] = []
    for item in reconciled:
        if item.outcome is ReconcileOutcome.DUPLICATE:
            duplicates += 1
            continue
        record = _build_record(
            item.fact,
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            mentioned_at=mentioned_at,
        )
        relation = _SUPERSESSION_RELATION.get(item.outcome)
        if relation is not None and item.target_memory_id:
            row = await pg_store.supersede_memory(item.target_memory_id, user_id, record, relation)
            if row is not None:
                await chroma_store.set_memory_flags(item.target_memory_id, is_latest=False)
                if relation is MemoryRelationType.EXTENDS:
                    extended += 1
                else:
                    updated += 1
                inserted.append((record, item.fact))
                continue
            # Target vanished between reconcile and apply — store it as a plain
            # new row rather than losing the fact.
        fresh.append((record, item.fact))

    if fresh:
        await pg_store.insert_memories([record for record, _ in fresh])
        new = len(fresh)
        inserted.extend(fresh)

    embeddings_by_content = {item.fact.content: item.embedding for item in reconciled}
    vector_items: list[MemoryVectorItem] = [
        {
            "id": str(record.id),
            "embedding": embeddings_by_content[fact.content],
            "document": record.content,
            "metadata": {
                "user_id": user_id,
                "kind": record.kind,
                "category_path": record.category_path,
                "is_latest": True,
                "is_forgotten": False,
            },
        }
        for record, fact in inserted
    ]
    await chroma_store.upsert_memories(vector_items)

    entities_linked, edges_added = await _apply_graph(user_id, inserted)

    # Keep the free-cap counter in sync: only NEW grows the live set. UPDATES
    # and EXTENDS supersede (net zero) and DUPLICATEs add nothing. A no-op when
    # the counter is unseeded (paid users) or Redis is down.
    await cap_counter.adjust_live_count(user_id, new)

    return _ApplyResult(
        inserted=inserted,
        duplicates=duplicates,
        new=new,
        updated=updated,
        extended=extended,
        entities_linked=entities_linked,
        edges_added=edges_added,
    )


async def _apply_graph(
    user_id: str, inserted: list[tuple[MemoryRecord, ExtractedFact]]
) -> tuple[int, int]:
    """Upsert entities, link them to their memories, and insert edges."""
    names_types = [
        (entity.name, entity.entity_type.value) for _, fact in inserted for entity in fact.entities
    ]
    if not names_types:
        return 0, 0

    id_map = await pg_store.upsert_entities(user_id, names_types)
    entities_linked = edges_added = 0
    for record, fact in inserted:
        entity_ids = [
            id_map[entity.name.strip().lower()]
            for entity in fact.entities
            if entity.name.strip().lower() in id_map
        ]
        await pg_store.link_entities(record.id, entity_ids)
        entities_linked += len(entity_ids)

        edges = [
            (
                id_map[edge.source.strip().lower()],
                edge.relationship,
                id_map[edge.target.strip().lower()],
            )
            for edge in fact.edges
            if edge.source.strip().lower() in id_map and edge.target.strip().lower() in id_map
        ]
        edges_added += await pg_store.insert_edges(user_id, edges, record.id)
    return entities_linked, edges_added


async def _store_conversation_chunks(
    user_id: str,
    messages: list[dict[str, str]],
    *,
    source_id: str | None,
    now: datetime,
) -> None:
    """Embed the raw transcript in chunks (verbatim retention tier).

    Extracted facts compress a conversation, which loses verbatim
    micro-details ("the exact move GAIA suggested", "the 27th item in that
    list"). Chunking the transcript keeps those details searchable via
    ``recall_transcripts`` without polluting the fact store.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def _flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current))
            current, current_len = [], 0

    for message in messages:
        content = message.get("content", "")
        if not content.strip():
            continue
        line = f"{message.get('role', 'user')}: {content}"
        if len(line) > TRANSCRIPT_CHUNK_MAX_CHARS:
            # A single long turn — typically a list or detailed answer GAIA
            # generated ("here are 100 prompt parameters: ..."). Split it into
            # overlapping windows so every item stays searchable; truncating it
            # would silently drop the tail (and the exact detail asked for later).
            _flush()
            step = TRANSCRIPT_CHUNK_MAX_CHARS - TRANSCRIPT_CHUNK_OVERLAP_CHARS
            for start in range(0, len(line), step):
                chunks.append(line[start : start + TRANSCRIPT_CHUNK_MAX_CHARS])
            continue
        current.append(line)
        current_len += len(line)
        if len(current) >= TRANSCRIPT_CHUNK_TURNS or current_len >= TRANSCRIPT_CHUNK_MAX_CHARS:
            _flush()
    _flush()
    chunks = chunks[:TRANSCRIPT_CHUNKS_PER_SESSION_CAP]
    if not chunks:
        return

    embeddings = await embed_batch(chunks)
    session_key = source_id or uuid.uuid4().hex[:12]
    items: list[ConversationChunkItem] = [
        {
            "id": f"{user_id}:{session_key}:{index}",
            "embedding": embedding,
            "document": chunk,
            "metadata": {"user_id": user_id, "date": now.date().isoformat()},
        }
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    await chroma_store.upsert_conversation_chunks(items)


async def _append_episode_entries(
    user_id: str,
    entries: list[str],
    *,
    source_type: MemorySourceType,
    now: datetime,
) -> int:
    """Append today's journal lines, timestamped at ingestion time."""
    if not entries:
        return 0
    timestamp = now.strftime(EPISODE_ENTRY_TIME_FORMAT)
    episode_entries: list[pg_store.EpisodeEntry] = [
        {"time": timestamp, "text": text, "source": source_type.value} for text in entries
    ]
    await pg_store.append_episode_entries(user_id, now.date(), episode_entries)
    return len(episode_entries)


async def _summarize_rolled_over_days(user_id: str, today: date_type) -> None:
    """Lazily summarize any past day that has entries but no summary yet."""
    for date in await pg_store.get_unsummarized_episode_dates(user_id, today):
        await summarize_episode(user_id, date)


async def _schedule_post_ingest(
    user_id: str,
    *,
    inserted_facts: list[ExtractedFact],
) -> None:
    """Fire-and-forget follow-ups after every ingestion.

    The projection sync always runs (journal entries change even when no
    fact landed; the hash gate makes true no-ops ~free). Consolidation is
    debounced and only scheduled for the docs this ingestion touched.
    """
    schedule_memory_vfs_sync(user_id)
    doc_types = infer_doc_types(inserted_facts)
    if doc_types:
        await schedule_consolidation(user_id, doc_types)


def _elapsed_ms(since: float) -> int:
    """Milliseconds elapsed since a perf_counter() reading."""
    return int((time.perf_counter() - since) * 1000)


def _format_folder_tree(folders: list[tuple[str, int]]) -> str:
    """Render (category_path, count) rows for the extraction prompt."""
    return "\n".join(f"- {path} ({count})" for path, count in folders)


def _clamp_category_path(path: str | None) -> str:
    """Normalize an LLM-chosen folder path to the maximum tree depth."""
    if not path:
        return _FALLBACK_CATEGORY_PATH
    segments = [stripped for segment in path.split("/") if (stripped := segment.strip())]
    return "/".join(segments[:CATEGORY_PATH_MAX_DEPTH]) or _FALLBACK_CATEGORY_PATH


def _build_record(
    fact: ExtractedFact,
    *,
    user_id: str,
    source_type: MemorySourceType,
    source_id: str | None,
    mentioned_at: datetime | None = None,
) -> MemoryRecord:
    """Map an extracted fact onto an unsaved ORM row (no lineage fields).

    ``mentioned_at`` is set explicitly only when the caller replays a
    historical session; otherwise the column default (now) applies.
    """
    values: dict[str, object] = {
        "user_id": user_id,
        "kind": fact.kind.value,
        "shelf_life": fact.shelf_life.value,
        "content": fact.content,
        "category_path": _clamp_category_path(fact.category_path),
        "occurred_start": fact.occurred_start,
        "occurred_end": fact.occurred_end,
        "forget_after": _forget_after(fact.shelf_life, mentioned_at),
        "importance": fact.importance,
        "source_type": source_type.value,
        "source_id": source_id,
    }
    if mentioned_at is not None:
        values["mentioned_at"] = mentioned_at
    return MemoryRecord(**values)
