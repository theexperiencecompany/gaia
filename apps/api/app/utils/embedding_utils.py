from collections.abc import Mapping
from dataclasses import dataclass, replace

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict

from app.constants.chroma import CHROMA_NOTES_COLLECTION
from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.notes import note_repository
from shared.py.wide_events import log


class _IndexedItemMetadata(BaseModel):
    """The Chroma metadata the note/file indexers stamp on an embedded item."""

    model_config = ConfigDict(extra="ignore")

    note_id: str | None = None
    file_id: str | None = None
    user_id: str = ""


@dataclass(slots=True, frozen=True)
class SimilarityMatch:
    """One item search_by_similarity found, closest first (lower score is closer).

    created_at/updated_at are ISO strings set only on the enriched notes
    path, for a note that has them.
    """

    id: str
    similarity_score: float
    user_id: str
    content: str
    created_at: str | None = None
    updated_at: str | None = None


async def search_by_similarity(
    input_text: str,
    user_id: str,
    collection_name: str,
    top_k: int = 5,
    additional_filters: Mapping[str, str | int | float | bool] | None = None,
    fetch_mongo_details: bool | None = False,
) -> list[SimilarityMatch]:
    """Search a ChromaDB collection for items similar to input_text, scoped to user_id.

    Optionally enriches results with MongoDB details.
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
        where_filter: dict[str, object] = {"user_id": str(user_id)}
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
        result_items: list[SimilarityMatch] = []
        is_notes = collection_name == CHROMA_NOTES_COLLECTION

        # Build initial result data
        for item, score in chroma_results:
            meta = _IndexedItemMetadata.model_validate(item.metadata)
            item_id = meta.note_id if is_notes else meta.file_id
            if not item_id:
                continue

            result_items.append(
                SimilarityMatch(
                    id=item_id,
                    similarity_score=score,
                    user_id=meta.user_id,
                    content=item.page_content,
                )
            )

        # Enrich note results with their stored timestamps. Only the notes path
        # requests enrichment (see search_notes_by_similarity, the sole caller);
        # the files-detail branch was unreachable and is intentionally dropped.
        if fetch_mongo_details and is_notes:
            note_ids = [d.id for d in result_items]
            notes_by_id = {n.id: n for n in await note_repository.find_by_ids(user_id, note_ids)}
            result_items = [
                replace(
                    match,
                    created_at=note.created_at.isoformat() if note.created_at else None,
                    updated_at=note.updated_at.isoformat() if note.updated_at else None,
                )
                if (note := notes_by_id.get(match.id)) is not None
                else match
                for match in result_items
            ]

        # Sort by similarity score (lower is better)
        result_items.sort(key=lambda x: x.similarity_score)

        # Limit to top_k results
        result_items = result_items[:top_k]

        return result_items
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error searching in ChromaDB collection",
            collection_name=collection_name,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            exc_info=True,
        )
        return []


async def search_notes_by_similarity(input_text: str, user_id: str) -> list[SimilarityMatch]:
    return await search_by_similarity(
        input_text=input_text,
        user_id=user_id,
        collection_name=CHROMA_NOTES_COLLECTION,
        fetch_mongo_details=True,
    )
