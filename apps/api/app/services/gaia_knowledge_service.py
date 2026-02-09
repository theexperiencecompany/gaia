"""
Service for managing GAIA self-knowledge in ChromaDB.

This service provides methods to store and search GAIA's self-knowledge
(capabilities, integrations, architecture, etc.) using ChromaDB as the backend.
"""

from dataclasses import dataclass
from typing import List, Optional

from app.config.loggers import general_logger as logger
from app.db.chroma.chromadb import ChromaClient
from pydantic import BaseModel, Field, field_validator


class KnowledgeItem(BaseModel):
    """Schema for a single knowledge item."""

    content: str = Field(..., min_length=1, description="Knowledge content to store")
    metadata: Optional[dict] = Field(
        default_factory=dict, description="Optional metadata"
    )

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
    metadata: dict


class GaiaKnowledgeService:
    """Service for managing GAIA self-knowledge in ChromaDB"""

    def __init__(self):
        self.collection_name = "gaia_knowledge"

    async def search_knowledge(
        self, query: str, limit: int = 5
    ) -> List[KnowledgeResult]:
        """
        Search GAIA knowledge base using semantic similarity.

        Args:
            query: The search query
            limit: Maximum number of results to return

        Returns:
            List of KnowledgeResult objects with content and relevance scores
        """
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

            logger.info(
                f"Found {len(knowledge_results)} knowledge results for query: {query[:50]}..."
            )
            return knowledge_results

        except Exception as e:
            logger.error(f"Error searching GAIA knowledge: {e}")
            return []

    async def add_knowledge(
        self, content: str, metadata: Optional[dict] = None
    ) -> bool:
        """
        Add a single knowledge item to the knowledge base.

        Args:
            content: The knowledge content to store
            metadata: Optional metadata (source, section, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            client = await ChromaClient.get_langchain_client(
                collection_name=self.collection_name, create_if_not_exists=True
            )

            # Add document
            await client.aadd_texts(texts=[content], metadatas=[metadata or {}])

            logger.debug(f"Added knowledge: {content[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Error adding knowledge: {e}")
            return False

    async def add_knowledge_batch(self, items: List[KnowledgeItem]) -> int:
        """
        Add multiple knowledge items in batch.

        Args:
            items: List of KnowledgeItem objects (validated via Pydantic)

        Returns:
            Number of items successfully added
        """
        if not items:
            logger.warning("add_knowledge_batch called with empty items list")
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

            logger.info(f"Added {len(items)} knowledge items to ChromaDB")
            return len(items)

        except Exception as e:
            logger.error(f"Error adding knowledge batch: {e}", exc_info=True)
            return 0

    async def clear_knowledge(self) -> bool:
        """
        Clear all knowledge from the collection (use with caution).

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the async client to delete collection
            async_client = await ChromaClient.get_client()

            # Delete and recreate collection
            await async_client.delete_collection(name=self.collection_name)
            logger.info(f"Cleared knowledge collection: {self.collection_name}")

            # Recreate empty collection
            await async_client.create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Recreated empty collection: {self.collection_name}")

            return True

        except Exception as e:
            logger.error(f"Error clearing knowledge: {e}")
            return False


# Singleton instance
gaia_knowledge_service = GaiaKnowledgeService()
