"""
Canvas vector utilities — ChromaDB indexing for tracked todo canvases.

Indexes canvas.md content for semantic search across all of a user's
tracked todos. Follows the same pattern as todo_vector_utils.py.
"""

from datetime import UTC, datetime
from typing import TypedDict

from pydantic import BaseModel, ConfigDict

from app.constants.chroma import CHROMA_CANVAS_COLLECTION
from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from shared.py.wide_events import log

COLLECTION_NAME = CHROMA_CANVAS_COLLECTION


class CanvasIndexMetadata(BaseModel):
    """The Chroma metadata stored with a canvas embedding.

    ``extra="allow"`` because :func:`mark_canvas_completed` reads a stored row
    and writes it back whole — a key this model does not declare must survive
    the round trip rather than be stripped.
    """

    model_config = ConfigDict(extra="allow")

    user_id: str = ""
    todo_id: str = ""
    title: str = ""
    updated_at: str = ""
    completed: bool = False
    labels: str | None = None
    completed_at: str | None = None
    revision: str | None = None


class _StoredCanvasRows(BaseModel):
    """The ``metadatas`` column of a chromadb ``GetResult`` — the only part read here."""

    model_config = ConfigDict(extra="ignore")

    metadatas: list[CanvasIndexMetadata | None] | None = None


class CanvasSearchMatch(TypedDict):
    """One canvas hit from search_canvas_context, rendered as a line by the tool."""

    todo_id: str
    title: str
    score: float
    snippet: str
    completed: bool


async def store_canvas_embedding(
    todo_id: str,
    canvas_content: str,
    user_id: str,
    title: str = "",
    labels: list[str] | None = None,
    revision: str | None = None,
) -> bool:
    """Index canvas content in ChromaDB for semantic search."""
    try:
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME, create_if_not_exists=True
        )

        metadata = CanvasIndexMetadata(
            user_id=str(user_id),
            todo_id=str(todo_id),
            title=title,
            updated_at=datetime.now(UTC).isoformat(),
            labels=", ".join(labels) if labels else None,
            revision=revision,
        )

        await chroma_collection.aadd_texts(
            texts=[canvas_content],
            metadatas=[metadata.model_dump(exclude_none=True)],
            ids=[f"canvas_{todo_id}"],
        )
        return True
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Failed to index canvas for todo",
            todo_id=todo_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return False


async def update_canvas_embedding(
    todo_id: str,
    canvas_content: str,
    user_id: str,
    title: str = "",
    labels: list[str] | None = None,
    revision: str | None = None,
) -> bool:
    """Re-index canvas content after update, preserving completed status."""
    # Preserve completed metadata before deleting the old embedding
    was_completed = False
    # Only read via `is not None` then a string `>=`; a failed read yields "" and
    # "" >= any real revision is False, so the same branch is taken as with None.
    stored_revision: str | None = None  # pragma: no mutate — None and "" are equivalent here
    try:
        raw_client = await ChromaClient.get_client()
        collection = await raw_client.get_collection(COLLECTION_NAME)
        existing = await collection.get(ids=[f"canvas_{todo_id}"], include=["metadatas"])
        metadatas = _StoredCanvasRows.model_validate(existing).metadatas if existing else None
        if metadatas and metadatas[0]:
            was_completed = metadatas[0].completed
            stored_revision = metadatas[0].revision
    except Exception as e:
        log.debug("canvas.preserve_completed_metadata_failed", todo_id=todo_id, error=str(e))

    if revision is not None and stored_revision is not None and stored_revision >= revision:
        return True

    await delete_canvas_embedding(todo_id)
    result = await store_canvas_embedding(
        todo_id, canvas_content, user_id, title, labels, revision=revision
    )

    # Restore completed status if the todo was previously completed
    if result and was_completed:
        try:
            await mark_canvas_completed(todo_id)
        except Exception as e:
            log.debug("canvas.restore_completed_status_failed", todo_id=todo_id, error=str(e))

    return result


async def delete_canvas_embedding(todo_id: str) -> bool:
    """Remove canvas from ChromaDB index."""
    try:
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME, create_if_not_exists=True
        )
        await chroma_collection.adelete(ids=[f"canvas_{todo_id}"])
        return True
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Failed to delete canvas index for todo",
            todo_id=todo_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def mark_canvas_completed(todo_id: str) -> bool:
    """Mark a canvas embedding as completed without deleting it.

    The embedding remains searchable but is tagged as completed
    so active-only searches can filter it out.
    """
    try:
        doc_id = f"canvas_{todo_id}"
        raw_client = await ChromaClient.get_client()
        collection = await raw_client.get_collection(COLLECTION_NAME)

        existing = await collection.get(ids=[doc_id], include=["metadatas"])
        metadatas = _StoredCanvasRows.model_validate(existing).metadatas if existing else None
        if not metadatas:
            return False

        stored = metadatas[0]
        if stored is None:
            return False
        metadata = stored.model_copy(
            update={"completed": True, "completed_at": datetime.now(UTC).isoformat()}
        )

        # exclude_unset: the row goes back exactly as stored plus the two stamps
        # — a key the stored row never had must not be invented as a default.
        await collection.update(ids=[doc_id], metadatas=[metadata.model_dump(exclude_unset=True)])
        return True
    except Exception as e:
        log.warning("canvas.mark_completed_failed", todo_id=todo_id, error=str(e))
        return False


async def search_canvas_context(
    query: str,
    user_id: str,
    top_k: int = 10,
    include_completed: bool = True,
) -> list[CanvasSearchMatch]:
    """Semantic search across all canvas content for a user."""
    try:
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME, create_if_not_exists=True
        )

        if include_completed:
            where_filter: dict[str, object] = {"user_id": str(user_id)}
        else:
            where_filter = {
                "$and": [
                    {"user_id": str(user_id)},
                    {"completed": False},
                ]
            }

        results = await chroma_collection.asimilarity_search_with_score(
            query=query,
            k=top_k,
            filter=where_filter,
        )

        matches: list[CanvasSearchMatch] = []
        for doc, score in results:
            meta = CanvasIndexMetadata.model_validate(
                doc.metadata if hasattr(doc, "metadata") else {}
            )
            matches.append(
                {
                    "todo_id": meta.todo_id,
                    "title": meta.title,
                    "score": round(score, 3),
                    "snippet": doc.page_content[:500] if hasattr(doc, "page_content") else "",
                    "completed": meta.completed,
                }
            )
        return matches
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Canvas search failed for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return []
