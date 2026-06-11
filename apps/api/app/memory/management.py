"""Management accessors for the memory system: tree, graph, journal,
documents, CRUD over individual memories, and the full wipe.

These back the settings-UI endpoints (plan F6) and the explicit memory
tools (F4). Reads map ORM rows straight to the public API schemas; writes
keep Postgres, Chroma and the Redis caches consistent.
"""

from datetime import date as date_type

from app.constants.memory import (
    DOCUMENT_PREVIEW_CHARS,
    MemoryDocType,
    MemoryEntityType,
    MemoryRelationType,
    MemorySourceType,
)
from app.memory import chroma_store, pg_store
from app.memory.context import invalidate_core_context, invalidate_user_memory_caches
from app.memory.embeddings import embed_query
from app.memory.mappers import document_to_model, episode_to_model, row_to_entry
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
    MemoryTreeNode,
    MemoryTreeResponse,
)


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


async def update_memory(user_id: str, memory_id: str, content: str) -> MemoryEntry | None:
    """Correct a memory by chaining an UPDATES version onto it.

    The old row stays as history (``is_latest=False``); the new row inherits
    folder, kind, importance and entity links. Returns None when the memory
    does not exist or is not the live head of its chain.
    """
    old = await pg_store.get_memory(memory_id, user_id)
    if old is None or not old.is_latest or old.is_forgotten:
        return None

    record = MemoryRecord(
        user_id=user_id,
        kind=old.kind,
        content=content,
        category_path=old.category_path,
        importance=old.importance,
        source_type=MemorySourceType.MANUAL.value,
    )
    row = await pg_store.supersede_memory(memory_id, user_id, record, MemoryRelationType.UPDATES)
    if row is None:
        return None

    entities_by_memory = await pg_store.get_entities_for_memories([old.id])
    entities = entities_by_memory.get(old.id, [])
    await pg_store.link_entities(row.id, [entity.id for entity in entities])

    embedding = await embed_query(content)
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
    await invalidate_user_memory_caches(user_id)
    return row_to_entry(row, entities)


async def forget_memory(user_id: str, memory_id: str, reason: str) -> bool:
    """Soft-delete a memory: hidden from recall, kept for lineage history."""
    forgotten = await pg_store.mark_forgotten(memory_id, user_id, reason)
    if not forgotten:
        return False
    await chroma_store.set_memory_flags(memory_id, is_forgotten=True)
    await invalidate_user_memory_caches(user_id)
    return True


async def delete_all(user_id: str) -> int:
    """Hard-wipe a user's entire memory. Returns deleted memory count."""
    deleted = await pg_store.delete_all_memories(user_id)
    await chroma_store.delete_user(user_id)
    await invalidate_user_memory_caches(user_id)
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
