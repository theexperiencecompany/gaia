"""
Service for managing GAIA self-knowledge in ChromaDB.

This service provides methods to store and search GAIA's self-knowledge
(capabilities, integrations, architecture, etc.) using ChromaDB as the backend.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.db.chroma.chromadb import ChromaClient
from shared.py.wide_events import log


class KnowledgeItem(BaseModel):
    """Schema for a single knowledge item."""

    content: str = Field(..., min_length=1, description="Knowledge content to store")
    metadata: dict[str, Any] | None = Field(default_factory=dict, description="Optional metadata")

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Ensure content is not just whitespace."""
        if not v.strip():
            raise ValueError("Content cannot be empty or whitespace only")
        return v.strip()


@dataclass
class KnowledgeResult:
    """Result from a knowledge search"""

    content: str
    relevance_score: float
    metadata: dict[str, Any]


class GaiaKnowledgeService:
    """Service for managing GAIA self-knowledge in ChromaDB"""

    def __init__(self) -> None:
        self.collection_name = "gaia_knowledge"

    async def search_knowledge(self, query: str, limit: int = 5) -> list[KnowledgeResult]:
        """Search the GAIA knowledge base using semantic similarity."""
        log.set(
            component="gaia_knowledge_service",
            operation="search_knowledge",
            query_preview=query[:50],
            limit=limit,
        )
        try:
            # Get langchain client for similarity search
            client = await ChromaClient.get_langchain_client(
                collection_name=self.collection_name, create_if_not_exists=True
            )

            # Perform similarity search with scores
            results = await client.asimilarity_search_with_score(query=query, k=limit)

            # Convert to KnowledgeResult objects
            knowledge_results = [
                KnowledgeResult(
                    content=doc.page_content,
                    relevance_score=float(score),
                    metadata=doc.metadata or {},
                )
                for doc, score in results
            ]

            log.info("Found knowledge results for query", result_count=len(knowledge_results))
            return knowledge_results

        except Exception as e:
            log.error("Error searching GAIA knowledge", error=str(e), error_type=type(e).__name__)
            return []

    async def add_knowledge_batch(self, items: list[KnowledgeItem]) -> int:
        """Add multiple knowledge items in batch. Returns the number added."""
        log.set(
            component="gaia_knowledge_service",
            operation="add_knowledge_batch",
            item_count=len(items),
        )
        if not items:
            log.warning("add_knowledge_batch called with empty items list")
            return 0

        try:
            client = await ChromaClient.get_langchain_client(
                collection_name=self.collection_name, create_if_not_exists=True
            )

            # Extract texts and metadatas from validated Pydantic models
            texts = [item.content for item in items]
            metadatas = [item.metadata or {} for item in items]

            # Add documents in batch
            await client.aadd_texts(texts=texts, metadatas=metadatas)

            log.info("Added knowledge items to ChromaDB", items_count=len(items))
            return len(items)

        except Exception as e:
            log.error(
                "Error adding knowledge batch",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            return 0

    async def clear_knowledge(self) -> bool:
        """Clear all knowledge from the collection (use with caution)."""
        try:
            # Get the async client to delete collection
            async_client = await ChromaClient.get_client()

            # Delete and recreate collection
            await async_client.delete_collection(name=self.collection_name)
            log.info("Cleared knowledge collection", collection_name=self.collection_name)

            # Recreate empty collection
            await async_client.create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
            log.info("Recreated empty collection", collection_name=self.collection_name)

            return True

        except Exception as e:
            log.error("Error clearing knowledge", error=str(e), error_type=type(e).__name__)
            return False


# Singleton instance
gaia_knowledge_service = GaiaKnowledgeService()
