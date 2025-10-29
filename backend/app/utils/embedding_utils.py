import hashlib
import inspect
import time
from typing import Any, List, Optional, Tuple

from bson import ObjectId
from langchain_core.documents import Document

from app.config.loggers import chat_logger as logger
from app.db.chromadb import ChromaClient
from app.db.mongodb.collections import files_collection, notes_collection
from app.db.redis import redis_cache


async def get_or_compute_embeddings(all_tools, embeddings):
    """Get cached embeddings or compute them via Google API."""
    # Collect all descriptions and code hashes
    tool_descriptions = []
    tool_hashes = []

    for tool in all_tools:
        description = f"{tool.name}: {tool.description}"
        tool_descriptions.append(description)

        # Get code hash for the tool function
        try:
            # Get the actual function source code
            if hasattr(tool, "func") and callable(tool.func):
                code_source = inspect.getsource(tool.func)
            elif callable(tool):
                code_source = inspect.getsource(tool)
            else:
                # Fallback: use string representation
                code_source = str(tool)

            code_hash = hashlib.sha256(code_source.encode()).hexdigest()

            # Get tool name safely
            tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
            tool_hashes.append(f"{tool_name}:{code_hash}")
        except (OSError, TypeError):
            # Fallback if we can't get source (built-in functions, etc.)
            tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
            tool_hashes.append(f"{tool_name}:no_source")

    # Generate combined hash for descriptions + code
    combined_description = "||".join(tool_descriptions)
    combined_code_hash = "||".join(tool_hashes)
    tools_hash = hashlib.sha256(
        f"{combined_description}::{combined_code_hash}".encode()
    ).hexdigest()
    cache_key = f"embed:batch:{tools_hash}"

    # Check cache first
    cached_embeddings = await redis_cache.get(cache_key)

    if cached_embeddings:
        logger.info("Using cached embeddings (description + code hash)")
        return cached_embeddings, tool_descriptions
    else:
        # Compute embeddings in one batch call
        logger.info("Sending batch request to Google Embeddings API...")
        embed_start = time.time()
        embeddings_list = embeddings.embed_documents(tool_descriptions)
        embed_time = time.time() - embed_start
        logger.info(
            f"Batch computed {len(embeddings_list)} embeddings in {embed_time:.3f}s"
        )

        # Cache the results
        await redis_cache.set(cache_key, embeddings_list, ttl=604800)  # 7 days
        return embeddings_list, tool_descriptions


async def search_by_similarity(
    input_text: str,
    user_id: str,
    collection_name: str,
    top_k: int = 5,
    additional_filters: Optional[dict] = None,
    fetch_mongo_details: Optional[bool] = False,
):
    """
    Generalized function to search for similar items in a ChromaDB collection.

    Args:
        input_text: The text to compare items against
        user_id: The user ID whose items to search
        collection_name: The name of the ChromaDB collection to query
        top_k: Maximum number of results to return
        additional_filters: Additional filters to apply to the query
        fetch_mongo_details: Whether to fetch additional details from MongoDB

    Returns:
        List of items with their content and metadata
    """
    try:
        # Get the specified collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name=collection_name
        )

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
        chroma_results: List[
            Tuple[Document, float]
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
        mongo_ids = []
        id_field = "note_id" if collection_name == "notes" else "file_id"

        # Build initial result data and collect IDs for MongoDB lookup
        for item, score in chroma_results:
            item_id = item.metadata.get(id_field)
            if not item_id:
                continue

            item_data = {
                "id": item_id,
                "similarity_score": score,
                "user_id": item.metadata.get("user_id", ""),
                "content": item.page_content,
            }
            result_items.append(item_data)

            if fetch_mongo_details:
                mongo_ids.append(ObjectId(item_id))

        # Extract IDs, similarity scores, content, and metadata
        if fetch_mongo_details:
            # Fetch additional details from MongoDB if required
            mongo_collection = (
                notes_collection if collection_name == "notes" else files_collection
            )

            mongo_items = await mongo_collection.find(
                {
                    "_id": {"$in": mongo_ids},
                    "user_id": user_id,
                }
            ).to_list(length=None)

            mongo_items_map = {str(item["_id"]): item for item in mongo_items}

            # Enhance result items with MongoDB details
            for item_data in result_items:
                mongo_item = mongo_items_map.get(item_data["id"])
                if mongo_item:
                    # Format timestamps
                    for ts_field in ["created_at", "updated_at"]:
                        if ts_field in mongo_item and hasattr(
                            mongo_item[ts_field], "isoformat"
                        ):
                            item_data[ts_field] = mongo_item[ts_field].isoformat()

                    # Add collection-specific fields
                    if collection_name == "files":
                        item_data["folder"] = mongo_item.get("folder", "")
                        item_data["tags"] = mongo_item.get("tags", [])

        # Sort by similarity score (lower is better)
        result_items.sort(key=lambda x: x.get("similarity_score", 1.0))

        # Limit to top_k results
        result_items = result_items[:top_k]

        return result_items
    except Exception as e:
        logger.error(
            f"Error searching in ChromaDB collection '{collection_name}': {str(e)}",
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


async def search_documents_by_similarity(
    input_text: str,
    user_id: str,
    conversation_id: Optional[str] = None,
    top_k: int = 5,
):
    additional_filters = (
        {"conversation_id": conversation_id} if conversation_id else None
    )
    return await search_by_similarity(
        input_text=input_text,
        user_id=user_id,
        collection_name="documents",
        top_k=top_k,
        additional_filters=additional_filters,
        fetch_mongo_details=True,
    )
