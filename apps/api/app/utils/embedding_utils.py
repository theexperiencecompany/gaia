from typing import Any

from langchain_core.documents import Document

from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.notes import note_repository
from shared.py.wide_events import log


async def search_by_similarity(
    input_text: str,
    user_id: str,
    collection_name: str,
    top_k: int = 5,
    additional_filters: dict | None = None,
    fetch_mongo_details: bool | None = False,
):
    """Search a ChromaDB collection for items similar to ``input_text``.

    Scoped to ``user_id``; optionally enriches results with MongoDB details.
    Returns a list of items with content and metadata.
    """
    log.set(
        collection_name=collection_name,
        user_id=user_id,
        top_k=top_k,
    )
    try:
        # Get the specified collection
        chroma_collection = await ChromaClient.get_langchain_client(collection_name=collection_name)

        # Build the filter
        where_filter: dict[str, Any] = {"user_id": str(user_id)}
        if additional_filters:
            where_filter = {
                "$and": [
                    where_filter,
                    *[{key: val} for key, val in additional_filters.items()],
                ]
            }

        # Query ChromaDB for similar items
        chroma_results: list[
            tuple[Document, float]
        ] = await chroma_collection.asimilarity_search_with_score(
            query=input_text,
            k=top_k,
            filter=where_filter,  # Filter by metadata
        )

        # Check if results are empty
        if not chroma_results:
            return []

        # Extract IDs for MongoDB lookup if needed
        result_items = []
        id_field = "note_id" if collection_name == "notes" else "file_id"

        # Build initial result data
        for item, score in chroma_results:
            item_id = item.metadata.get(id_field)
            if not item_id:
                continue

            result_items.append(
                {
                    "id": item_id,
                    "similarity_score": score,
                    "user_id": item.metadata.get("user_id", ""),
                    "content": item.page_content,
                }
            )

        # Enrich note results with their stored timestamps. Only the notes path
        # requests enrichment (see search_notes_by_similarity, the sole caller);
        # the files-detail branch was unreachable and is intentionally dropped.
        if fetch_mongo_details and collection_name == "notes":
            note_ids = [str(d["id"]) for d in result_items]
            notes_by_id = {n.id: n for n in await note_repository.find_by_ids(user_id, note_ids)}
            for item_data in result_items:
                note = notes_by_id.get(item_data["id"])
                if note is None:
                    continue
                for ts_field in ("created_at", "updated_at"):
                    value = getattr(note, ts_field, None)
                    if value is not None and hasattr(value, "isoformat"):
                        item_data[ts_field] = value.isoformat()

        # Sort by similarity score (lower is better)
        result_items.sort(key=lambda x: x.get("similarity_score", 1.0))

        # Limit to top_k results
        result_items = result_items[:top_k]

        return result_items
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error searching in ChromaDB collection '{collection_name}': {e!s}",
            exc_info=True,
        )
        return []


async def search_notes_by_similarity(input_text: str, user_id: str):
    return await search_by_similarity(
        input_text=input_text,
        user_id=user_id,
        collection_name="notes",
        fetch_mongo_details=True,
    )
