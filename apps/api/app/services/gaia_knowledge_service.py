"""
Service for managing GAIA self-knowledge in ChromaDB.

This service provides methods to store and search GAIA's self-knowledge
(capabilities, integrations, architecture, etc.) using ChromaDB as the backend.
"""

from dataclasses import dataclass
from typing import List

from app.config.loggers import general_logger as logger
from app.db.chroma.chromadb import ChromaClient


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


# Singleton instance
gaia_knowledge_service = GaiaKnowledgeService()
