"""ChromaDB store for public integrations semantic search."""

from typing import List, Optional

from app.config.loggers import chroma_logger as logger
from app.core.lazy_loader import providers
from app.db.chroma.chromadb import ChromaClient


COLLECTION_NAME = "public_integrations"


async def index_public_integration(
    integration_id: str,
    name: str,
    description: str,
    category: str,
    created_by: str,
    clone_count: int,
    published_at: str,
    tool_count: int,
    tools: list[dict],
) -> None:
    """
    Index a public integration in ChromaDB for semantic search.

    Args:
        integration_id: Unique integration ID
        name: Integration name
        description: Integration description
        category: Integration category
        created_by: Creator's user ID
        clone_count: Number of clones
        published_at: ISO timestamp of publish date
        tool_count: Number of tools
        tools: List of tool dicts with name/description
    """
    try:
        embedding_fn = await providers.aget("google_embeddings")
        chroma = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_fn,
            create_if_not_exists=True,
        )

        # Build searchable text
        tools_text = " ".join(
            [
                f"{t.get('name', '')}: {t.get('description', '')}"
                for t in tools[:20]  # Limit to first 20 tools
            ]
        )
        content = f"{name}\n{description}\n{tools_text}"

        # Add to ChromaDB with metadata
        await chroma.aadd_texts(
            texts=[content],
            ids=[integration_id],
            metadatas=[
                {
                    "integration_id": integration_id,  # Store ID in metadata for easy retrieval
                    "name": name,
                    "description": description[:500] if description else "",
                    "category": category,
                    "created_by": created_by,
                    "clone_count": clone_count,
                    "published_at": published_at,
                    "tool_count": tool_count,
                }
            ],
        )

        logger.info(f"Indexed public integration {integration_id} in ChromaDB")

    except Exception as e:
        logger.error(f"Failed to index public integration {integration_id}: {e}")
        raise


async def remove_public_integration(integration_id: str) -> None:
    """
    Remove a public integration from ChromaDB index.

    Args:
        integration_id: Integration ID to remove
    """
    try:
        embedding_fn = await providers.aget("google_embeddings")
        chroma = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_fn,
            create_if_not_exists=False,
        )

        await chroma.adelete(ids=[integration_id])
        logger.info(f"Removed public integration {integration_id} from ChromaDB")

    except Exception as e:
        logger.error(f"Failed to remove public integration {integration_id}: {e}")
        # Don't raise - removal failures are not critical


async def search_public_integrations(
    query: str,
    limit: int = 20,
    category: Optional[str] = None,
) -> List[dict]:
    """
    Search public integrations using semantic similarity.

    Args:
        query: Search query text
        limit: Maximum results to return
        category: Optional category filter

    Returns:
        List of integration metadata dicts with relevance score
    """
    try:
        embedding_fn = await providers.aget("google_embeddings")
        chroma = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_fn,
            create_if_not_exists=True,
        )

        # Build filter if category provided
        filter_dict = None
        if category and category != "all":
            filter_dict = {"category": category}

        # Search with similarity
        results = await chroma.asimilarity_search_with_relevance_scores(
            query=query,
            k=limit,
            filter=filter_dict,
        )

        # Format results
        formatted = []
        for doc, score in results:
            metadata = doc.metadata.copy()
            # The integration_id is stored in metadata and as document ID
            integration_id = metadata.get("integration_id")
            if not integration_id:
                # Fallback to document ID for older indexed documents
                if hasattr(doc, "id") and doc.id:
                    integration_id = doc.id
            metadata["integration_id"] = integration_id
            metadata["relevance_score"] = score
            formatted.append(metadata)

        return formatted

    except Exception as e:
        logger.error(f"Failed to search public integrations: {e}")
        return []


async def update_clone_count(integration_id: str, clone_count: int) -> None:
    """
    Update the clone count metadata for an integration.

    Note: This requires re-indexing the document since ChromaDB
    doesn't support partial metadata updates.

    Args:
        integration_id: Integration ID
        clone_count: New clone count
    """
    # This is a no-op for now - we'll update on next full re-index
    # A more sophisticated implementation would fetch and re-index
    logger.debug(f"Clone count update for {integration_id}: {clone_count}")
