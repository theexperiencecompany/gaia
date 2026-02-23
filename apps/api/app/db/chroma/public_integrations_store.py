"""ChromaDB store for public integrations semantic search."""

from typing import Optional

from app.config.loggers import chroma_logger as logger
from app.core.lazy_loader import providers
from app.db.chroma.chromadb import ChromaClient

COLLECTION_NAME = "public_integrations"


async def index_public_integration(
    integration_id: str,
    name: str,
    description: str,
    tools: list[dict],
) -> None:
    """Index a public integration in ChromaDB for semantic search."""
    try:
        embedding_fn = await providers.aget("google_embeddings")
        chroma = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_fn,
            create_if_not_exists=True,
        )

        tools_text = " ".join(
            [f"{t.get('name', '')}: {t.get('description', '')}" for t in tools]
        )
        content = f"{name}\n{description}\n{tools_text}"

        await chroma.aadd_texts(
            texts=[content],
            ids=[integration_id],
            metadatas=[{"integration_id": integration_id}],
        )
        logger.info(f"Indexed public integration {integration_id} in ChromaDB")

    except Exception as e:
        logger.error(f"Failed to index public integration {integration_id}: {e}")
        raise


async def remove_public_integration(integration_id: str) -> None:
    """Remove a public integration from ChromaDB index."""
    try:
        embedding_fn = await providers.aget("google_embeddings")
        chroma = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_fn,
            create_if_not_exists=True,
        )
        await chroma.adelete(ids=[integration_id])
        logger.info(f"Removed public integration {integration_id} from ChromaDB")

    except Exception as e:
        logger.error(f"Failed to remove public integration {integration_id}: {e}")


async def search_public_integrations(
    query: str,
    limit: int = 20,
    category: Optional[str] = None,
) -> list[dict]:
    """Search public integrations. Returns list of {integration_id, relevance_score}."""
    try:
        embedding_fn = await providers.aget("google_embeddings")
        chroma = await ChromaClient.get_langchain_client(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_fn,
            create_if_not_exists=True,
        )

        results = await chroma.asimilarity_search_with_relevance_scores(
            query=query,
            k=limit,
        )

        return [
            {
                "integration_id": doc.metadata.get("integration_id")
                or getattr(doc, "id", None),
                "relevance_score": score,
            }
            for doc, score in results
            if doc.metadata.get("integration_id") or getattr(doc, "id", None)
        ]

    except Exception as e:
        logger.error(f"Failed to search public integrations: {e}")
        return []
