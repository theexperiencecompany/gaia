"""
Canvas vector utilities — ChromaDB indexing for tracked todo canvases.

Indexes canvas.md content for semantic search across all of a user's
tracked todos. Follows the same pattern as todo_vector_utils.py.
"""

from datetime import UTC, datetime

from app.db.chroma.chromadb import ChromaClient
from shared.py.wide_events import log

COLLECTION_NAME = "gaia_canvas"


async def store_canvas_embedding(
    todo_id: str,
    canvas_content: str,
    user_id: str,
    title: str = "",
    labels: list[str] | None = None,
) -> bool:
    """Index canvas content in ChromaDB for semantic search."""
    try:
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME, create_if_not_exists=True
        )

        metadata = {
            "user_id": str(user_id),
            "todo_id": str(todo_id),
            "title": title,
            "updated_at": datetime.now(UTC).isoformat(),
            "completed": False,
        }
        if labels:
            metadata["labels"] = ", ".join(labels)

        await chroma_collection.aadd_texts(
            texts=[canvas_content],
            metadatas=[metadata],
            ids=[f"canvas_{todo_id}"],
        )
        return True
    except Exception as e:
        log.error(f"Failed to index canvas for todo {todo_id}: {e}")
        return False


async def update_canvas_embedding(
    todo_id: str,
    canvas_content: str,
    user_id: str,
    title: str = "",
    labels: list[str] | None = None,
) -> bool:
    """Re-index canvas content after update, preserving completed status."""
    # Preserve completed metadata before deleting the old embedding
    was_completed = False
    try:
        raw_client = await ChromaClient.get_client()
        collection = await raw_client.get_collection(COLLECTION_NAME)
        existing = await collection.get(
            ids=[f"canvas_{todo_id}"], include=["metadatas"]
        )
        metadatas = existing.get("metadatas") if existing else None
        if metadatas and metadatas[0]:
            was_completed = bool(metadatas[0].get("completed", False))
    except Exception as e:
        log.debug(
            "canvas.preserve_completed_metadata_failed", todo_id=todo_id, error=str(e)
        )

    await delete_canvas_embedding(todo_id)
    result = await store_canvas_embedding(
        todo_id, canvas_content, user_id, title, labels
    )

    # Restore completed status if the todo was previously completed
    if result and was_completed:
        try:
            await mark_canvas_completed(todo_id)
        except Exception as e:
            log.debug(
                "canvas.restore_completed_status_failed", todo_id=todo_id, error=str(e)
            )

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
        log.error(f"Failed to delete canvas index for todo {todo_id}: {e}")
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
        if not existing or not existing["metadatas"]:
            return False

        metadata: dict[str, str | int | float | bool | None] = dict(
            existing["metadatas"][0]
        )
        metadata["completed"] = True
        metadata["completed_at"] = datetime.now(UTC).isoformat()

        await collection.update(ids=[doc_id], metadatas=[metadata])
        return True
    except Exception as e:
        log.warning("canvas.mark_completed_failed", todo_id=todo_id, error=str(e))
        return False


async def search_canvas_context(
    query: str,
    user_id: str,
    top_k: int = 10,
    include_completed: bool = True,
) -> list[dict]:
    """Semantic search across all canvas content for a user.

    Returns list of {todo_id, title, score, snippet, completed} dicts.
    """
    try:
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME, create_if_not_exists=True
        )

        if include_completed:
            where_filter: dict = {"user_id": str(user_id)}
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

        matches = []
        for doc, score in results:
            meta = doc.metadata if hasattr(doc, "metadata") else {}
            matches.append(
                {
                    "todo_id": meta.get("todo_id", ""),
                    "title": meta.get("title", ""),
                    "score": round(score, 3),
                    "snippet": doc.page_content[:500]
                    if hasattr(doc, "page_content")
                    else "",
                    "completed": meta.get("completed", False),
                }
            )
        return matches
    except Exception as e:
        log.error(f"Canvas search failed for user {user_id}: {e}")
        return []
