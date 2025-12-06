"""Memory service layer using Zep for knowledge graph and memory operations."""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.agents.memory.client import zep_client_manager
from app.config.loggers import llm_logger as logger
from app.models.memory_models import (
    MemoryEntry,
    MemoryRelation,
    MemorySearchResult,
)
from zep_cloud import EpisodeData
from zep_cloud.client import Zep
from zep_cloud.types import Message


class MemoryService:
    """Service class for managing memory operations with Zep."""

    def __init__(self):
        """Initialize the memory service."""
        self.logger = logger

    def _get_client(self) -> Zep:
        """Get the configured Zep client."""
        return zep_client_manager.get_client()

    def _extract_node_data(
        self, node: Any, default_name: str = "Unknown"
    ) -> Dict[str, Any]:
        """Extract common node attributes into a dict."""
        return {
            "id": node.uuid_,
            "name": getattr(node, "name", default_name),
            "labels": getattr(node, "labels", []),
            "summary": getattr(node, "summary", None),
        }

    def _build_relation_from_edge(
        self, edge: Any, node_map: Dict[str, Dict[str, Any]]
    ) -> Optional[MemoryRelation]:
        """Build a MemoryRelation from an edge and node map."""
        if not (
            hasattr(edge, "source_node_uuid") and hasattr(edge, "target_node_uuid")
        ):
            return None

        source_node = node_map.get(edge.source_node_uuid, {})
        target_node = node_map.get(edge.target_node_uuid, {})

        return MemoryRelation(
            source=source_node.get("name", str(edge.source_node_uuid)),
            source_type=", ".join(source_node.get("labels", ["entity"])),
            relationship=getattr(edge, "name", "related_to"),
            target=target_node.get("name", str(edge.target_node_uuid)),
            target_type=", ".join(target_node.get("labels", ["entity"])),
        )

    def _ensure_user_exists(self, user_id: str, name: Optional[str] = None) -> None:
        """
        Ensure Zep user exists, create if not.

        Args:
            user_id: User identifier
            name: Optional user name
        """
        try:
            client = self._get_client()

            try:
                client.user.get(user_id)
                return
            except Exception as e:
                self.logger.debug(f"User {user_id} not found, will create: {e}")

            # Create user with name parsing
            parts = name.split(" ", 1) if name and " " in name else [name or "User"]
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            client.user.add(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
            )
            self.logger.info(f"Created Zep user: {user_id}")
        except Exception as e:
            self.logger.warning(f"Could not ensure user exists: {e}")

    def _get_or_create_thread(
        self, user_id: str, conversation_id: Optional[str] = None
    ) -> str:
        """
        Get existing thread or create a new one for the user.

        Args:
            user_id: User identifier
            conversation_id: Optional conversation identifier

        Returns:
            Thread ID
        """
        client = self._get_client()

        thread_id = conversation_id or f"thread_{user_id}_{uuid4().hex[:8]}"

        try:
            client.thread.get(thread_id)
            return thread_id
        except Exception:
            try:
                client.thread.create(
                    thread_id=thread_id,
                    user_id=user_id,
                )
                self.logger.info(f"Created thread {thread_id} for user {user_id}")
            except Exception as e:
                self.logger.warning(f"Could not create thread: {e}")

            return thread_id

    async def store_memory(
        self,
        message: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[MemoryEntry]:
        """
        Store a single memory using Zep.

        Args:
            message: The memory content to store
            user_id: User identifier
            conversation_id: Optional conversation/thread identifier
            metadata: Message metadata (sentiment, source, priority, etc.)

        Returns:
            MemoryEntry with the stored memory
        """
        try:
            client = self._get_client()

            self._ensure_user_exists(user_id)

            thread_id = self._get_or_create_thread(user_id, conversation_id)

            messages = [
                Message(
                    role="user",
                    content=message,
                    metadata=metadata,
                )
            ]

            client.thread.add_messages(thread_id, messages=messages)

            self.logger.info(f"Memory stored for user {user_id} in thread {thread_id}")

            return MemoryEntry(
                id=thread_id,
                content=message,
                user_id=user_id,
                metadata=metadata or {},
                created_at=datetime.now(),
            )

        except Exception as e:
            self.logger.error(f"Error storing memory for user {user_id}: {e}")
            return None

    async def store_memory_batch(
        self,
        messages: List[Dict[str, str]],
        user_id: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Store multiple memories in batch using Zep.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            user_id: User identifier
            conversation_id: Optional conversation/thread identifier
            metadata: Shared metadata applied to all messages in batch

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self._get_client()

            self._ensure_user_exists(user_id)

            thread_id = self._get_or_create_thread(user_id, conversation_id)

            zep_messages = [
                Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    metadata=metadata,
                )
                for msg in messages
            ]

            client.thread.add_messages(thread_id, messages=zep_messages)

            self.logger.info(
                f"Batch of {len(messages)} memories stored for user {user_id}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error storing batch memories for user {user_id}: {e}")
            return False

    async def add_business_data(
        self,
        user_id: str,
        data: Any,
    ) -> bool:
        """
        Add business data (emails, JSON objects, etc.) directly to user's knowledge graph.

        Args:
            user_id: User identifier
            data: Business data to add (dict, JSON, or text)

        Returns:
            True if successful
        """
        try:
            client = self._get_client()

            self._ensure_user_exists(user_id)

            client.graph.add(
                user_id=user_id,
                data=data,
                type="json",
            )

            self.logger.info(f"Business data added to graph for user {user_id}")
            return True

        except Exception as e:
            self.logger.error(f"Error adding business data for user {user_id}: {e}")
            return False

    async def add_business_data_batch(
        self,
        user_id: str,
        data_items: List[Any],
    ) -> bool:
        """
        Add multiple business data items in batch using Zep's concurrent processing.
        Up to 20 items can be processed simultaneously.

        Args:
            user_id: User identifier
            data_items: List of business data items (dicts, JSON, or text)

        Returns:
            True if successful
        """
        if not data_items:
            return True

        try:
            client = self._get_client()

            self._ensure_user_exists(user_id)

            episodes = [
                EpisodeData(
                    data=json.dumps(item) if isinstance(item, dict) else item,
                    type="json" if isinstance(item, dict) else "text",
                )
                for item in data_items
                if isinstance(item, (dict, str))
            ]

            batch_size = 20
            for i in range(0, len(episodes), batch_size):
                batch = episodes[i : i + batch_size]
                client.graph.add_batch(user_id=user_id, episodes=batch)
                self.logger.info(
                    f"Batch processed: {len(batch)} items for user {user_id}"
                )
            return True

        except Exception as e:
            self.logger.error(f"Error adding batch data for user {user_id}: {e}")
            return False

    async def search_memory(
        self,
        query: str,
        user_id: str,
        limit: int = 10,
    ) -> MemorySearchResult:
        """
        Search memories using Zep's hybrid search.

        Args:
            query: Search query
            user_id: User identifier
            limit: Maximum results to return

        Returns:
            MemorySearchResult with found memories
        """
        try:
            client = self._get_client()

            results = client.graph.search(
                user_id=user_id,
                query=query,
                limit=limit,
                reranker="rrf",
            )

            memories = (
                [
                    MemoryEntry(
                        id=result.uuid_,
                        content=result.fact or "",
                        user_id=user_id,
                        metadata={},
                        relevance_score=getattr(result, "score", None),
                        created_at=getattr(result, "created_at", None),
                    )
                    for result in results.edges[:limit]
                ]
                if results and results.edges
                else []
            )

            self.logger.info(f"Found {len(memories)} memories for query: {query}")
            return MemorySearchResult(memories=memories)

        except Exception as e:
            self.logger.error(f"Error searching memories for user {user_id}: {e}")
            return MemorySearchResult(memories=[])

    async def get_all_memories(
        self,
        user_id: str,
        user_data: Optional[Dict[str, Any]] = None,
    ) -> MemorySearchResult:
        """
        Get all memories for a user using Zep.

        Args:
            user_id: User identifier
            user_data: Optional user data dict with profile info

        Returns:
            MemorySearchResult with all memories, relations, and user node
        """
        try:
            client = self._get_client()

            user_node_response, edges, nodes = await asyncio.gather(
                asyncio.to_thread(client.user.get_node, user_id=user_id),
                asyncio.to_thread(client.graph.edge.get_by_user_id, user_id=user_id),
                asyncio.to_thread(client.graph.node.get_by_user_id, user_id=user_id),
            )

            user_graph_node = user_node_response.node if user_node_response else None

            node_map = {}
            if user_graph_node and hasattr(user_graph_node, "uuid_"):
                node_map[user_graph_node.uuid_] = self._extract_node_data(
                    user_graph_node, "User"
                )

            if nodes:
                node_map.update(
                    {
                        node.uuid_: self._extract_node_data(node)
                        for node in nodes
                        if hasattr(node, "uuid_") and node.uuid_ not in node_map
                    }
                )

            memories = [
                MemoryEntry(
                    id=edge.uuid_,
                    content=edge.fact or "",
                    user_id=user_id,
                    metadata={},
                    created_at=getattr(edge, "created_at", None),
                )
                for edge in (edges or [])
            ]

            relations = [
                relation
                for edge in (edges or [])
                if (relation := self._build_relation_from_edge(edge, node_map))
            ]

            user_node_data = None
            if user_graph_node and hasattr(user_graph_node, "uuid_"):
                base_data = self._extract_node_data(user_graph_node, "User")
                user_node_data = {
                    "id": base_data["name"],
                    "uuid": base_data["id"],
                    "name": user_data.get("full_name", base_data["name"])
                    if user_data
                    else base_data["name"],
                    "email": user_data.get("email") if user_data else None,
                    "profile_photo_url": user_data.get("profile_photo_url")
                    if user_data
                    else None,
                    "type": "user",
                    "labels": base_data["labels"],
                    "summary": base_data["summary"],
                }

            return MemorySearchResult(
                memories=memories, relations=relations, user_node=user_node_data
            )

        except Exception as e:
            self.logger.error(f"Error getting all memories for user {user_id}: {e}")
            return MemorySearchResult(memories=[])

    async def get_user_context(
        self,
        user_id: str,
        conversation_id: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> str:
        """
        Get the auto-assembled context block for a user.
        This is Zep's superpower - returns prompt-ready context.

        Args:
            user_id: User identifier
            conversation_id: Optional thread/conversation ID
            template_id: Optional custom context template ID

        Returns:
            Context string ready for LLM prompt
        """
        try:
            client = self._get_client()

            thread_id = self._get_or_create_thread(user_id, conversation_id)

            memory = client.thread.get_user_context(
                thread_id=thread_id,
                template_id=template_id,
            )
            return memory.context or ""

        except Exception as e:
            self.logger.error(f"Error getting user context: {e}")
            return ""

    async def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """
        Delete a specific memory/edge from the graph.

        Args:
            memory_id: UUID of the edge/episode to delete
            user_id: User identifier

        Returns:
            True if successful
        """
        try:
            client = self._get_client()

            try:
                client.graph.edge.delete(uuid_=memory_id)
                return True
            except Exception:
                client.graph.episode.delete(uuid_=memory_id)
                return True

        except Exception as e:
            self.logger.error(f"Error deleting memory {memory_id}: {e}")
            return False


memory_service = MemoryService()
