"""Management accessors for the memory system: tree, graph, journal,
documents, CRUD over individual memories, and the full wipe.

These back the settings-UI endpoints (plan F6) and the explicit memory
tools (F4). Reads map ORM rows straight to the public API schemas; writes
keep Postgres, Chroma and the Redis caches consistent.
"""

from datetime import UTC, date as date_type, datetime

from app.constants.memory import (
    DOCUMENT_PREVIEW_CHARS,
    MemoryDocType,
    MemoryEntityType,
    MemoryKind,
    MemoryRelationType,
    MemoryShelfLife,
    MemorySourceType,
)
from app.memory import cap_counter, chroma_store, pg_store
from app.memory.context import invalidate_core_context, invalidate_user_memory_caches
from app.memory.embeddings import embed_batch
from app.memory.mappers import document_to_model, episode_to_model, row_to_entry
from app.memory.schemas import ExtractedFact
from app.models.memory_db_models import MemoryRecord
from app.models.memory_models import (
    MemoryDocument,
    MemoryDocumentPreview,
    MemoryDocumentsResponse,
    MemoryEntry,
    MemoryEpisodesResponse,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryGraphResponse,
    MemoryListResponse,
    MemoryOverviewResponse,
    MemorySearchResult,
    MemoryTreeNode,
    MemoryTreeResponse,
)
from app.services.memory_fs import schedule_memory_vfs_sync
from app.utils.errors import AppError


async def get_tree(user_id: str) -> MemoryTreeResponse:
    """The user's memory folder tree with per-folder (and subtree) counts."""
    folders = await pg_store.get_folder_tree(user_id)
    roots: list[MemoryTreeNode] = []
    nodes_by_path: dict[str, MemoryTreeNode] = {}

    for path, count in folders:
        parent_path = ""
        for segment in path.split("/"):
            node_path = f"{parent_path}/{segment}".lstrip("/")
            node = nodes_by_path.get(node_path)
            if node is None:
                node = MemoryTreeNode(name=segment, path=node_path, count=0)
                nodes_by_path[node_path] = node
                if parent_path:
                    nodes_by_path[parent_path].children.append(node)
                else:
                    roots.append(node)
            node.count += count
            parent_path = node_path

    return MemoryTreeResponse(tree=roots, total_count=sum(count for _, count in folders))


async def get_graph(user_id: str) -> MemoryGraphResponse:
    """The entity graph: nodes, labeled edges, and their provenance memories."""
    entity_counts, edge_rows = await pg_store.get_graph(user_id)

    nodes = [
        MemoryGraphNode(
            id=str(entity.id),
            name=entity.name,
            entity_type=MemoryEntityType(entity.entity_type),
            memory_count=count,
        )
        for entity, count in entity_counts
    ]
    edges = [
        MemoryGraphEdge(
            id=str(edge.id),
            source_entity_id=str(edge.source_entity_id),
            target_entity_id=str(edge.target_entity_id),
            relationship=edge.relationship,
            memory_id=str(edge.memory_id) if edge.memory_id else None,
        )
        for edge in edge_rows
    ]

    provenance_ids = list({str(edge.memory_id) for edge in edge_rows if edge.memory_id})
    rows = await pg_store.get_memories_by_ids(user_id, provenance_ids)
    memories = await _rows_to_entries(rows)
    return MemoryGraphResponse(nodes=nodes, edges=edges, memories=memories)


async def get_episodes(user_id: str, start: date_type, end: date_type) -> MemoryEpisodesResponse:
    """Journal pages for a date range (inclusive), oldest first."""
    rows = await pg_store.get_episodes_range(user_id, start, end)
    return MemoryEpisodesResponse(episodes=[episode_to_model(row) for row in rows])


async def get_documents(user_id: str) -> MemoryDocumentsResponse:
    """All of a user's core documents."""
    rows = await pg_store.get_documents(user_id)
    return MemoryDocumentsResponse(documents=[document_to_model(row) for row in rows])


async def get_document(user_id: str, doc_type: MemoryDocType) -> MemoryDocument | None:
    """One core document by type."""
    row = await pg_store.get_document(user_id, doc_type)
    return document_to_model(row) if row else None


async def update_document(user_id: str, doc_type: MemoryDocType, content: str) -> MemoryDocument:
    """Rewrite a core document (versioned) and refresh the hot context."""
    row = await pg_store.upsert_document(user_id, doc_type, content)
    await invalidate_core_context(user_id)
    schedule_memory_vfs_sync(user_id)
    return document_to_model(row)


async def list_memories(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    include_subfolders: bool = False,
) -> MemoryListResponse:
    """One page of memories, newest first. ``category`` is an EXACT folder
    match by default so tree expansion shows only a folder's own memories;
    pass ``include_subfolders=True`` for whole-subtree listings."""
    rows, total = await pg_store.list_memories(
        user_id,
        page=page,
        page_size=page_size,
        category=category,
        include_subfolders=include_subfolders,
    )
    memories = await _rows_to_entries(rows)
    return MemoryListResponse(memories=memories, page=page, page_size=page_size, total_count=total)


async def get_history(user_id: str, memory_id: str) -> MemorySearchResult:
    """Full supersession chain for a memory, newest version first.

    Includes superseded versions so the UI can expand a v2+ row to show what
    it replaced and why (relation_type).
    """
    rows = await pg_store.get_chain(memory_id, user_id)
    memories = await _rows_to_entries(rows)
    return MemorySearchResult(memories=memories, total_count=len(memories))


class MemoryNotFoundError(AppError):
    """No live memory could be resolved from the id a caller supplied."""

    def __init__(self, memory_id: str) -> None:
        super().__init__(
            message=f"Memory {memory_id} does not exist for this user.",
            why="The id does not name any memory in this user's store.",
            fix=(
                "Call search_memory to get the current id of the fact you mean, "
                "then retry the correction with that id. Do NOT tell the user "
                "the memory was corrected — it was not."
            ),
            status_code=404,
            meta={"memory_id": memory_id},
        )


async def _resolve_live_head(memory_id: str, user_id: str) -> MemoryRecord:
    """The live head of the chain ``memory_id`` belongs to.

    A model correcting a memory routinely hands back an id it saw in an older
    recall, which by then has been superseded. That id still names a real
    chain, so resolve it to the chain's live head rather than refusing — the
    correction the user asked for is unambiguous either way.

    Raises ``MemoryNotFoundError`` when the id names nothing at all (a typo, a
    hallucination, another user's memory) or when the chain has no live head.
    That has to be an exception, not a string: the tool returned
    "Error: ... not found or already superseded" as its result and the model
    read it as a result, told the user the memory was fixed, and moved on.
    """
    try:
        row = await pg_store.get_memory(memory_id, user_id)
    except ValueError as e:
        # Not even a UUID — a fabricated id, which is exactly the case that
        # must not read back as an ordinary tool result.
        raise MemoryNotFoundError(memory_id) from e
    if row is None or row.is_forgotten:
        raise MemoryNotFoundError(memory_id)
    if row.is_latest:
        return row

    head = next(
        (version for version in await pg_store.get_chain(memory_id, user_id) if version.is_latest),
        None,
    )
    if head is None or head.is_forgotten:
        raise MemoryNotFoundError(memory_id)
    return head


async def update_memory(user_id: str, memory_id: str, content: str) -> MemoryEntry:
    """Correct a memory by chaining an UPDATES version onto its live head.

    A superseded id resolves to the head of its chain, so a correction never
    fails just because the model quoted an older version. The old row stays as
    history (``is_latest=False``); the new row inherits folder, kind, shelf
    life, expiry, importance and entity links.

    Raises ``MemoryNotFoundError`` when no live memory can be resolved.
    """
    old = await _resolve_live_head(memory_id, user_id)
    memory_id = str(old.id)

    # embed_batch, not embed_query: this vector is stored as the row's passage
    # embedding, and mixing query-space vectors into the passage index
    # measurably degrades ANN recall (see embeddings._embed_query_sync).
    # Computed BEFORE the Postgres supersession (same shape as ingestion's
    # _apply_reconciled) so an embedding failure aborts the whole correction
    # instead of leaving the new live row permanently invisible to dense recall.
    embedding = (await embed_batch([content]))[0]

    record = MemoryRecord(
        user_id=user_id,
        kind=old.kind,
        shelf_life=old.shelf_life,
        content=content,
        category_path=old.category_path,
        importance=old.importance,
        forget_after=old.forget_after,
        source_type=MemorySourceType.MANUAL.value,
    )
    row = await pg_store.supersede_memory(memory_id, user_id, record, MemoryRelationType.UPDATES)
    if row is None:
        raise MemoryNotFoundError(memory_id)

    entities_by_memory = await pg_store.get_entities_for_memories([old.id])
    entities = entities_by_memory.get(old.id, [])
    await pg_store.link_entities(row.id, [entity.id for entity in entities])

    await chroma_store.set_memory_flags(memory_id, is_latest=False)
    await chroma_store.upsert_memories(
        [
            {
                "id": str(row.id),
                "embedding": embedding,
                "document": row.content,
                "metadata": {
                    "user_id": user_id,
                    "kind": row.kind,
                    "category_path": row.category_path,
                    "is_latest": True,
                    "is_forgotten": False,
                },
            }
        ]
    )
    await _reconsolidate_documents(user_id, row)
    await invalidate_user_memory_caches(user_id)
    schedule_memory_vfs_sync(user_id)
    return row_to_entry(row, entities)


async def _reconsolidate_documents(user_id: str, row: MemoryRecord) -> None:
    """Schedule a rewrite of the core documents that quote this fact.

    Without this, user.md (injected into every prompt) keeps asserting a
    corrected or forgotten fact until an unrelated ingestion happens to touch
    the same doc type.
    """
    from app.memory.consolidation import (  # noqa: PLC0415 -- breaks the consolidation <-> management import cycle
        infer_doc_types,
        schedule_consolidation,
    )

    fact = ExtractedFact(
        content=row.content,
        kind=MemoryKind(row.kind),
        shelf_life=MemoryShelfLife(row.shelf_life),
        category_path=row.category_path,
        importance=row.importance,
    )
    doc_types = infer_doc_types([fact])
    if doc_types:
        await schedule_consolidation(user_id, doc_types)


async def forget_memory(user_id: str, memory_id: str, reason: str) -> bool:
    """Soft-delete a memory: hidden from recall, kept for lineage history."""
    # Snapshot liveness before forgetting so the free-cap counter is only
    # decremented when a fact that actually counted toward the live set is
    # removed. Mirrors pg_store's active-memory predicate (latest, not
    # forgotten, not expired); a superseded or expired row never counted.
    before = await pg_store.get_memory(memory_id, user_id)
    was_live = (
        before is not None
        and before.is_latest
        and not before.is_forgotten
        and (before.forget_after is None or before.forget_after > datetime.now(UTC))
    )

    forgotten = await pg_store.mark_forgotten(memory_id, user_id, reason)
    if not forgotten:
        return False
    if was_live:
        await cap_counter.adjust_live_count(user_id, -1)
    await chroma_store.set_memory_flags(memory_id, is_forgotten=True)
    if before is not None:
        if before.source_id:
            # Forgetting a fact forfeits verbatim recall of the conversation
            # that produced it: leaving the raw chunks searchable would keep
            # the forgotten sentence quotable via search_conversations forever.
            await chroma_store.delete_conversation_chunks(user_id, before.source_id)
        await _reconsolidate_documents(user_id, before)
    await invalidate_user_memory_caches(user_id)
    schedule_memory_vfs_sync(user_id)
    return True


async def delete_all(user_id: str) -> int:
    """Hard-wipe a user's entire memory. Returns deleted memory count."""
    from app.memory.consolidation import (  # noqa: PLC0415 -- breaks the consolidation <-> management import cycle
        cancel_consolidation,
    )

    await cancel_consolidation(user_id)
    deleted = await pg_store.delete_all_memories(user_id)
    await chroma_store.delete_user(user_id)
    await cap_counter.set_cached_live_count(user_id, 0)
    await invalidate_user_memory_caches(user_id)
    schedule_memory_vfs_sync(user_id)
    return deleted


async def get_overview(user_id: str) -> MemoryOverviewResponse:
    """Headline counts and core-document previews for the settings UI."""
    counts = await pg_store.get_overview_counts(user_id)
    documents = await pg_store.get_documents(user_id)
    previews = [
        MemoryDocumentPreview(
            doc_type=MemoryDocType(document.doc_type),
            preview=document.content[:DOCUMENT_PREVIEW_CHARS],
            updated_at=document.updated_at,
        )
        for document in documents
    ]
    return MemoryOverviewResponse(
        total_memories=counts.total_memories,
        total_entities=counts.total_entities,
        folder_count=counts.folder_count,
        episode_count=counts.episode_count,
        documents=previews,
    )


async def _rows_to_entries(rows: list[MemoryRecord]) -> list[MemoryEntry]:
    """Hydrate entities for a batch of rows and map them to API entries."""
    entities_by_memory = await pg_store.get_entities_for_memories([row.id for row in rows])
    return [row_to_entry(row, entities_by_memory.get(row.id, [])) for row in rows]
