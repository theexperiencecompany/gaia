"""The memory write path: extract -> embed -> reconcile -> apply -> journal.

``retain`` is the single ingestion pipeline, designed to run fire-and-forget
after a turn ends — it never raises into callers for LLM failures
(extraction degrades to an empty batch upstream). Every ingestion schedules
the hash-gated ``/workspace/memory`` projection sync and a debounced
core-document consolidation for the docs its changes touch.
"""

from dataclasses import dataclass
from datetime import UTC, date as date_type, datetime
import time
import uuid

from app.constants.memory import (
    DEFAULT_MEMORY_IMPORTANCE,
    EPISODE_ENTRY_TIME_FORMAT,
    RECENT_FACTS_LIMIT,
    TRANSCRIPT_CHUNK_MAX_CHARS,
    TRANSCRIPT_CHUNK_TURNS,
    TRANSCRIPT_CHUNKS_PER_SESSION_CAP,
    MemoryKind,
    MemoryRelationType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory import chroma_store, pg_store
from app.memory.chroma_store import ConversationChunkItem, EpisodeVectorItem, MemoryVectorItem
from app.memory.consolidation import infer_doc_types, schedule_consolidation
from app.memory.context import invalidate_user_memory_caches
from app.memory.embeddings import embed_batch, embed_query
from app.memory.extraction import categorize_fact, extract_memories, summarize_episode_entries
from app.memory.mappers import row_to_entry
from app.memory.reconciliation import ReconciledFact, reconcile
from app.memory.schemas import ExtractedFact
from app.models.memory_db_models import MemoryRecord
from app.models.memory_models import MemoryEntry
from app.services.memory_fs import schedule_memory_vfs_sync
from shared.py.wide_events import log

_DEFAULT_USER_NAME = "the user"
_FALLBACK_CATEGORY_PATH = "general"


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

    folder_tree = await pg_store.get_folder_tree(user_id)
    recent_facts = await pg_store.get_recent_facts(user_id, limit=RECENT_FACTS_LIMIT)
    timings["context_ms"] = _elapsed_ms(started)

    stage = time.perf_counter()
    batch = await extract_memories(
        messages,
        user_id=user_id,
        user_name=user_name or _DEFAULT_USER_NAME,
        folder_tree=_format_folder_tree(folder_tree),
        recent_facts=recent_facts,
        extraction_hints=extraction_hints,
        current_date=now,
    )
    timings["extract_ms"] = _elapsed_ms(stage)

    result = RetainResult(facts_extracted=len(batch.facts))
    if not batch.facts and not batch.episode_entries:
        return result

    stage = time.perf_counter()
    embeddings = await embed_batch([fact.content for fact in batch.facts])
    timings["embed_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    reconciled = await reconcile(user_id, batch.facts, embeddings)
    timings["reconcile_ms"] = _elapsed_ms(stage)

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

    await invalidate_user_memory_caches(user_id)
    await _schedule_post_ingest(
        user_id,
        inserted_facts=[fact for _, fact in applied.inserted],
        agenda_updates=batch.agenda_updates,
    )

    timings["total_ms"] = _elapsed_ms(started)
    log.info(
        "memory_retain_completed",
        memory={
            "operation": "retain",
            "user_id": user_id,
            "source_type": source_type.value,
            "facts_extracted": result.facts_extracted,
            "new": result.new,
            "updated": result.updated,
            "extended": result.extended,
            "duplicates": result.duplicates,
            "entities_linked": result.entities_linked,
            "edges_added": result.edges_added,
            "episode_entries": result.episode_entries,
            **timings,
        },
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
    """
    now = datetime.now(UTC)
    fact = await _build_single_fact(user_id, content, category_path, now)

    embeddings = await embed_batch([fact.content])
    reconciled = await reconcile(user_id, [fact], embeddings)
    applied = await _apply_reconciled(user_id, reconciled, source_type=source_type, source_id=None)
    await invalidate_user_memory_caches(user_id)
    await _schedule_post_ingest(
        user_id,
        inserted_facts=[inserted_fact for _, inserted_fact in applied.inserted],
        agenda_updates=[],
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
    summary = await summarize_episode_entries(lines)
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
    """Build the ExtractedFact for a manual add, categorizing if needed."""
    if category_path is not None:
        return ExtractedFact(
            content=content,
            kind=MemoryKind.FACT,
            category_path=category_path,
            importance=DEFAULT_MEMORY_IMPORTANCE,
        )

    folder_tree = await pg_store.get_folder_tree(user_id)
    categorization = await categorize_fact(
        content, folder_tree=_format_folder_tree(folder_tree), current_date=now
    )
    if categorization is None:
        return ExtractedFact(
            content=content,
            kind=MemoryKind.FACT,
            category_path=_FALLBACK_CATEGORY_PATH,
            importance=DEFAULT_MEMORY_IMPORTANCE,
        )
    return ExtractedFact(
        content=content,
        kind=categorization.kind,
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
    """Write reconciled facts to Postgres + Chroma and wire up the graph."""
    inserted: list[tuple[MemoryRecord, ExtractedFact]] = []
    new = updated = extended = duplicates = 0

    new_and_extends = [
        item
        for item in reconciled
        if item.outcome in (ReconcileOutcome.NEW, ReconcileOutcome.EXTENDS)
    ]
    extend_target_ids = [
        item.target_memory_id
        for item in new_and_extends
        if item.outcome is ReconcileOutcome.EXTENDS and item.target_memory_id
    ]
    extend_targets = {
        str(row.id): row for row in await pg_store.get_memories_by_ids(user_id, extend_target_ids)
    }

    records: list[MemoryRecord] = []
    for item in new_and_extends:
        record = _build_record(
            item.fact,
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            mentioned_at=mentioned_at,
        )
        target = extend_targets.get(item.target_memory_id or "")
        if item.outcome is ReconcileOutcome.EXTENDS and target is not None:
            # EXTENDS records a relatedness link to an existing fact, but the new
            # fact is distinct and coexists with its parent — it is NOT a revision.
            # So it keeps version 1 and its own chain (no version bump, no root
            # chaining); only UPDATES advances a supersession chain. This is why
            # a v2 always means "this fact was revised" and has real history.
            record.parent_id = target.id
            record.relation_type = MemoryRelationType.EXTENDS.value
            extended += 1
        else:
            new += 1
        records.append(record)

    await pg_store.insert_memories(records)
    inserted.extend(zip(records, [item.fact for item in new_and_extends]))

    for item in reconciled:
        if item.outcome is ReconcileOutcome.DUPLICATE:
            duplicates += 1
        elif item.outcome is ReconcileOutcome.UPDATES and item.target_memory_id:
            record = _build_record(
                item.fact,
                user_id=user_id,
                source_type=source_type,
                source_id=source_id,
                mentioned_at=mentioned_at,
            )
            row = await pg_store.supersede_memory(
                item.target_memory_id, user_id, record, MemoryRelationType.UPDATES
            )
            if row is None:
                # Target vanished between reconcile and apply — store as plain NEW.
                await pg_store.insert_memories([record])
                new += 1
            else:
                await chroma_store.set_memory_flags(item.target_memory_id, is_latest=False)
                updated += 1
            inserted.append((record, item.fact))

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
    for message in messages:
        content = message.get("content", "")
        if not content:
            continue
        line = f"{message.get('role', 'user')}: {content}"
        current.append(line)
        current_len += len(line)
        if len(current) >= TRANSCRIPT_CHUNK_TURNS or current_len >= TRANSCRIPT_CHUNK_MAX_CHARS:
            chunks.append("\n".join(current))
            current, current_len = [], 0
    if current:
        chunks.append("\n".join(current))
    chunks = [chunk[:TRANSCRIPT_CHUNK_MAX_CHARS] for chunk in chunks]
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
    agenda_updates: list[str],
) -> None:
    """Fire-and-forget follow-ups after every ingestion.

    The projection sync always runs (journal entries change even when no
    fact landed; the hash gate makes true no-ops ~free). Consolidation is
    debounced and only scheduled for the docs this ingestion touched.
    """
    schedule_memory_vfs_sync(user_id)
    doc_types = infer_doc_types(inserted_facts, agenda_updates)
    if doc_types:
        await schedule_consolidation(user_id, doc_types, agenda_updates=agenda_updates)


def _elapsed_ms(since: float) -> int:
    """Milliseconds elapsed since a perf_counter() reading."""
    return int((time.perf_counter() - since) * 1000)


def _format_folder_tree(folders: list[tuple[str, int]]) -> str:
    """Render (category_path, count) rows for the extraction prompt."""
    return "\n".join(f"- {path} ({count})" for path, count in folders)


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
        "content": fact.content,
        "category_path": fact.category_path or _FALLBACK_CATEGORY_PATH,
        "occurred_start": fact.occurred_start,
        "occurred_end": fact.occurred_end,
        "forget_after": fact.forget_after,
        "importance": fact.importance,
        "source_type": source_type.value,
        "source_id": source_id,
    }
    if mentioned_at is not None:
        values["mentioned_at"] = mentioned_at
    return MemoryRecord(**values)
