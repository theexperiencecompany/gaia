"""
Canvas vector utilities — ChromaDB indexing for tracked todo canvases.

Indexes canvas.md content for semantic search across all of a user's
tracked todos. Follows the same pattern as todo_vector_utils.py.
"""

from datetime import datetime, timezone

from shared.py.wide_events import log

from app.db.chroma.chromadb import ChromaClient

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
            "updated_at": datetime.now(timezone.utc).isoformat(),
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
    """Re-index canvas content after update."""
    await delete_canvas_embedding(todo_id)
    return await store_canvas_embedding(
        todo_id, canvas_content, user_id, title, labels
    )


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


async def search_canvas_context(
    query: str,
    user_id: str,
    top_k: int = 10,
) -> list[dict]:
    """Semantic search across all canvas content for a user.

    Returns list of {todo_id, title, score, snippet} dicts.
    """
    try:
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME, create_if_not_exists=True
        )

        results = await chroma_collection.asimilarity_search_with_score(
            query=query,
            k=top_k,
            filter={"user_id": str(user_id)},
        )

        matches = []
        for doc, score in results:
            meta = doc.metadata if hasattr(doc, "metadata") else {}
            matches.append(
                {
                    "todo_id": meta.get("todo_id", ""),
                    "title": meta.get("title", ""),
                    "score": round(score, 3),
                    "snippet": doc.page_content[:500] if hasattr(doc, "page_content") else "",
                }
            )
        return matches
    except Exception as e:
        log.error(f"Canvas search failed for user {user_id}: {e}")
        return []
