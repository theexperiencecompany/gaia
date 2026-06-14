"""ORM row -> public API schema mapping for the memory engine.

Pure functions shared by the write path (ingestion), the read path
(retrieval), and the management accessors — the single place where database
rows become ``app.models.memory_models`` objects.
"""

from app.constants.memory import (
    MemoryDocType,
    MemoryEntityType,
    MemoryKind,
    MemoryRelationType,
    MemorySourceType,
)
from app.models.memory_db_models import (
    MemoryDocument as MemoryDocumentRecord,
    MemoryEntity,
    MemoryEpisode as MemoryEpisodeRecord,
    MemoryRecord,
)
from app.models.memory_models import (
    MemoryDocument,
    MemoryEntityRef,
    MemoryEntry,
    MemoryEpisode,
    MemoryEpisodeEntry,
)


def row_to_entry(
    row: MemoryRecord,
    entities: list[MemoryEntity],
    relevance_score: float | None = None,
) -> MemoryEntry:
    """Map an ORM row (+ its linked entities) to the public API schema."""
    return MemoryEntry(
        id=str(row.id),
        content=row.content,
        kind=MemoryKind(row.kind),
        category_path=row.category_path,
        importance=row.importance,
        occurred_start=row.occurred_start,
        occurred_end=row.occurred_end,
        mentioned_at=row.mentioned_at,
        version=row.version,
        is_latest=row.is_latest,
        parent_id=str(row.parent_id) if row.parent_id else None,
        root_id=str(row.root_id) if row.root_id else None,
        relation_type=MemoryRelationType(row.relation_type) if row.relation_type else None,
        is_forgotten=row.is_forgotten,
        forget_after=row.forget_after,
        forget_reason=row.forget_reason,
        source_type=MemorySourceType(row.source_type),
        source_id=row.source_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        relevance_score=relevance_score,
        entities=[
            MemoryEntityRef(
                id=str(entity.id),
                name=entity.name,
                entity_type=MemoryEntityType(entity.entity_type),
            )
            for entity in entities
        ],
    )


def episode_to_model(row: MemoryEpisodeRecord) -> MemoryEpisode:
    """Map a journal-day ORM row to the public API schema."""
    return MemoryEpisode(
        date=row.date.isoformat(),
        entries=[
            MemoryEpisodeEntry(
                time=entry.get("time", ""),
                text=entry.get("text", ""),
                source=entry.get("source", ""),
            )
            for entry in row.entries
        ],
        summary=row.summary,
    )


def document_to_model(row: MemoryDocumentRecord) -> MemoryDocument:
    """Map a core-document ORM row to the public API schema."""
    return MemoryDocument(
        doc_type=MemoryDocType(row.doc_type),
        content=row.content,
        version=row.version,
        updated_at=row.updated_at,
    )


def entry_to_note(entry: MemoryEntry) -> str:
    """Render a memory as a context note with its dates.

    The bracketed dates let the agent (or any answerer) do temporal
    reasoning — "when / how long ago / which came first" — directly from
    injected context. Used by prompt injection, tools, and benchmarks so
    every consumer formats memories identically.
    """
    parts = [entry.content]
    if entry.occurred_start:
        occurred = entry.occurred_start.date().isoformat()
        if entry.occurred_end and entry.occurred_end.date() != entry.occurred_start.date():
            occurred += f"..{entry.occurred_end.date().isoformat()}"
        parts.append(f"[occurred {occurred}]")
    mentioned = entry.mentioned_at or entry.created_at
    if mentioned:
        parts.append(f"[mentioned {mentioned.date().isoformat()}]")
    if entry.previous_content:
        parts.append(f"[previously: {entry.previous_content}]")
    return " ".join(parts)
