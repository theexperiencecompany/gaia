"""Memory service layer for handling all memory operations with latest Mem0 API."""

from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from app.agents.memory.client import memory_client_manager
from app.config.loggers import llm_logger as logger
from app.models.memory_models import (
    MemoryEntry,
    MemoryRelation,
    MemorySearchResult,
)


class MemoryService:
    """Service class for managing memory operations."""

    def __init__(self):
        """Initialize the memory service."""
        self.logger = logger

    async def _get_client(self):
        """Get the configured async memory client."""
        return await memory_client_manager.get_client()

    def _validate_user_id(self, user_id: Optional[str]) -> Optional[str]:
        """
        Validate and return user_id.

        Args:
            user_id: User identifier

        Returns:
            Validated user_id or None
        """
        if not user_id:
            self.logger.warning("No user_id provided for memory operation")
            return None

        # Handle different user_id formats
        if isinstance(user_id, dict):
            # If user_id is accidentally a user object
            user_id = user_id.get("user_id") or user_id.get("id")

        return str(user_id) if user_id else None

    def _parse_memory_result(self, result: Dict[str, Any]) -> Optional[MemoryEntry]:
        """
        Parse a single memory result from Mem0 API v2 response.

        Args:
            result: Memory result dictionary from v2 API

        Returns:
            MemoryEntry or None if parsing fails
        """
        if not isinstance(result, dict):
            self.logger.warning(f"Expected dict, got {type(result)}: {result}")
            return None

        # Extract memory content - v2 API uses "memory" field
        content = result.get("memory", "")

        if not content:
            self.logger.warning(f"No memory content found in result: {result}")
            return None

        try:
            # Extract metadata - v2 API may have metadata nested or at root level
            metadata = result.get("metadata", {})
            if metadata is None:
                metadata = {}

            memory_entry = MemoryEntry(
                id=result.get("id"),
                content=content,
                user_id=result.get("user_id", ""),
                metadata=metadata,
                categories=result.get("categories") or [],
                created_at=result.get("created_at"),
                updated_at=result.get("updated_at"),
                expiration_date=result.get("expiration_date"),
                immutable=result.get("immutable", False),
                organization=result.get("organization"),
                owner=result.get("owner"),
                relevance_score=result.get("score"),  # v2 API includes relevance score
            )

            self.logger.debug(f"Successfully parsed memory: {memory_entry.id}")
            return memory_entry

        except Exception as e:
            self.logger.error(
                f"Error creating MemoryEntry from data: {e}, raw data: {result}"
            )
            return None

    def _parse_memory_list(
        self, memories: List[Dict[str, Any]], user_id: str
    ) -> List[MemoryEntry]:
        """
        Parse a list of memory results.

        Args:
            memories: List of memory dictionaries
            user_id: User ID to associate with memories

        Returns:
            List of MemoryEntry objects
        """
        parsed_memories = []
        for memory_data in memories:
            try:
                if memory_entry := self._parse_memory_result(memory_data):
                    memory_entry.user_id = user_id
                    parsed_memories.append(memory_entry)
            except Exception as e:
                self.logger.warning(f"Failed to parse memory: {e}")
                continue

        self.logger.debug(
            f"Successfully parsed {len(parsed_memories)}/{len(memories)} memories"
        )
        return parsed_memories

    def _parse_add_result(
        self, result: Dict[str, Any], is_async: bool = False
    ) -> Optional[MemoryEntry]:
        """
        Parse add operation result from Mem0 API v2.

        Args:
            result: Add result dictionary with format:
                    Sync: {"id": "...", "memory": "...", "event": "ADD"|"UPDATE"|"NOOP",
                           "structured_attributes": {...}}
                    Async: {"message": "...", "status": "PENDING", "event_id": "..."}
            is_async: Whether the result is from async mode

        Returns:
            MemoryEntry or None if parsing fails
        """
        if not isinstance(result, dict):
            self.logger.warning(f"Expected dict, got {type(result)}: {result}")
            return None

        # Handle async mode response (PENDING status)
        if result.get("status") == "PENDING" or is_async:
            event_id = result.get("event_id")
            message = result.get("message", "Memory processing queued")

            if not event_id:
                self.logger.warning(f"No event_id in async response: {result}")
                return None

            # Create a placeholder MemoryEntry for async processing
            memory_entry = MemoryEntry(
                id=event_id,  # Use event_id as temporary ID
                content=message,
                metadata={
                    "status": "PENDING",
                    "event_id": event_id,
                    "async_mode": True,
                },
                created_at=datetime.now(),
            )

            self.logger.debug(f"Memory queued for async processing: {event_id}")
            return memory_entry

        # Handle synchronous mode response
        # Extract memory content - v2 API uses "memory" field
        content = result.get("memory", "")

        if not content:
            self.logger.warning(f"No memory content found in add result: {result}")
            return None

        try:
            # v2 API returns structured_attributes as metadata
            structured_attrs = result.get("structured_attributes", {})
            if structured_attrs is None:
                structured_attrs = {}

            memory_entry = MemoryEntry(
                id=result.get("id"),
                content=content,
                metadata=structured_attrs,
                created_at=result.get("created_at"),
                updated_at=result.get("updated_at"),
            )

            self.logger.debug(
                f"Successfully parsed add result: {memory_entry.id} (event: {result.get('event')})"
            )
            return memory_entry

        except Exception as e:
            self.logger.error(
                f"Error creating MemoryEntry from add result: {e}, raw data: {result}"
            )
            return None

    def _extract_relationships_from_response(
        self, response: Any
    ) -> List[Dict[str, Any]]:
        """
        Extract relationships list from API response.

        Args:
            response: API response which might contain relationships

        Returns:
            List of relationship dictionaries
        """
        if isinstance(response, dict):
            return (
                response.get("relations", [])
                or response.get("entities", [])
                or response.get("relationships", [])
                or response.get("graph", {}).get("relationships", [])
            )
        return []

    def _parse_relationships(
        self, relations: List[Dict[str, Any]]
    ) -> List[MemoryRelation]:
        """
        Parse relationships from Mem0 API v2 graph memory response.

        Args:
            relations: List of relationship dictionaries in v2 graph format:
                      [{"source": "alice", "relation": "likes", "destination": "pizza"}]

        Returns:
            List of MemoryRelation objects
        """
        if not relations:
            return []

        parsed_relations = []
        for relation_data in relations:
            try:
                # v2 Graph API format: source, relation, destination
                if (
                    "source" in relation_data
                    and "relation" in relation_data
                    and "destination" in relation_data
                ):
                    relation = MemoryRelation(
                        source=relation_data.get("source", ""),
                        source_type=relation_data.get("source_type", "entity"),
                        relationship=relation_data.get("relation", ""),
                        target=relation_data.get("destination", ""),
                        target_type=relation_data.get("destination_type", "entity"),
                    )
                    parsed_relations.append(relation)
                # Legacy format fallback: source, relationship, target
                elif (
                    "source" in relation_data
                    and "relationship" in relation_data
                    and "target" in relation_data
                ):
                    relation = MemoryRelation(
                        source=relation_data.get("source", ""),
                        source_type=relation_data.get("source_type", "entity"),
                        relationship=relation_data.get("relationship", ""),
                        target=relation_data.get("target", ""),
                        target_type=relation_data.get("target_type", "entity"),
                    )
                    parsed_relations.append(relation)
                else:
                    self.logger.warning(f"Unknown relationship format: {relation_data}")

            except Exception as e:
                self.logger.warning(
                    f"Failed to parse relationship: {e}, data: {relation_data}"
                )
                continue

        self.logger.debug(
            f"Successfully parsed {len(parsed_relations)}/{len(relations)} graph relationships"
        )
        return parsed_relations

    async def store_memory(
        self,
        message: str,
        user_id: Optional[str],
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        async_mode: bool = True,
        custom_instructions: Optional[str] = None,
    ) -> Optional[MemoryEntry]:
        """
        Store a single memory using Mem0 v2 API.

        Args:
            message: The memory content to store
            user_id: User identifier
            conversation_id: Optional conversation/run identifier
            metadata: Additional metadata
            async_mode: If True, queue for background processing (default: True, faster but returns event_id).
                       If False, returns full memory content immediately.
            custom_instructions: Project-specific guidelines for handling memories

        Returns:
            For async_mode=True, returns MemoryEntry with event_id and PENDING status.
            For async_mode=False, returns MemoryEntry with full memory content.
        """
        user_id = self._validate_user_id(user_id)
        if not user_id:
            return None

        try:
            # Prepare metadata
            if metadata is None:
                metadata = {}
            metadata["timestamp"] = datetime.now().isoformat()

            # Get client
            client = await self._get_client()

            # Use v2 API to add memory
            # Messages format allows Mem0 to infer structured memories
            result = await client.add(
                messages=[{"role": "user", "content": message}],
                user_id=user_id,
                metadata=metadata,
                run_id=conversation_id,
                async_mode=async_mode,
            )

            mode_str = "async" if async_mode else "sync"
            self.logger.info(f"Memory stored for user {user_id} (mode: {mode_str})")

            # v2 API response format: {"results": [...]}
            results_list: List[Dict[str, Any]]
            if isinstance(result, dict) and "results" in result:
                raw_results = result["results"]
                results_list = cast(
                    List[Dict[str, Any]],
                    raw_results if isinstance(raw_results, list) else [],
                )
            elif isinstance(result, list):
                # Fallback for direct list response
                results_list = cast(List[Dict[str, Any]], result)
            else:
                self.logger.warning(
                    f"Unexpected response format from mem0 add: {type(result)}"
                )
                return None

            if not results_list:
                self.logger.debug("No memories created (NOOP event)")
                return None

            # Parse the first result (primary memory)
            first_result = results_list[0]
            memory_entry = self._parse_add_result(first_result, is_async=async_mode)

            if memory_entry:
                memory_entry.user_id = user_id
                # Merge any additional metadata
                if metadata:
                    memory_entry.metadata.update(metadata)

            return memory_entry

        except Exception as e:
            self.logger.error(f"Error storing memory for user {user_id}: {e}")
            return None

    async def store_memory_batch(
        self,
        messages: List[Dict[str, str]],
        user_id: Optional[str],
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        async_mode: bool = True,
        custom_instructions: Optional[str] = None,
    ) -> bool:
        """
        Store multiple memories in a single API call using Mem0 v2 API.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            user_id: User identifier
            conversation_id: Optional conversation/run identifier
            metadata: Additional metadata
            async_mode: If True, queue for background processing (default: True)
            custom_instructions: Project-specific guidelines for handling memories

        Returns:
            True if successful, False otherwise
        """
        user_id = self._validate_user_id(user_id)
        if not user_id:
            return False

        try:
            # Prepare metadata
            if metadata is None:
                metadata = {}
            metadata["timestamp"] = datetime.now().isoformat()

            # Get client
            client = await self._get_client()

            # Use v2 API to add multiple memories in one call
            result = await client.add(
                messages=messages,
                user_id=user_id,
                metadata=metadata,
                run_id=conversation_id,
                async_mode=async_mode,
                **(
                    {"custom_instructions": custom_instructions}
                    if custom_instructions
                    else {}
                ),
            )

            mode_str = "async" if async_mode else "sync"
            self.logger.info(
                f"Batch of {len(messages)} memories stored for user {user_id} (mode: {mode_str})"
            )

            # Log the raw response for debugging
            self.logger.debug(f"Mem0 API raw response: {result}")

            # v2 API response format: {"results": [...]}
            if isinstance(result, dict) and "results" in result:
                results_list = result["results"]
                success_count = (
                    len(results_list) if isinstance(results_list, list) else 0
                )

                # Log details about what was stored
                if success_count == 0:
                    self.logger.warning(
                        f"Mem0 returned 0 memories from {len(messages)} messages. "
                        f"Response: {result}"
                    )
                else:
                    self.logger.info(f"Successfully stored {success_count} memories")
                    # Log sample of events
                    events = [r.get("event", "UNKNOWN") for r in results_list[:5]]
                    self.logger.debug(f"Sample events: {events}")

                return success_count > 0
            elif isinstance(result, list):
                self.logger.info(f"Successfully stored {len(result)} memories")
                return len(result) > 0
            else:
                self.logger.warning(
                    f"Unexpected response format from mem0 batch add: {type(result)}, value: {result}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Error storing memory batch for user {user_id}: {e}")
            return False

    async def search_memories(
        self,
        query: str,
        user_id: Optional[str],
        limit: int = 5,
        threshold: Optional[float] = None,
    ) -> MemorySearchResult:
        """
        Search for relevant memories using Mem0 v2 API with semantic search.

        Args:
            query: Search query
            user_id: User identifier
            limit: Maximum number of results (default: 5)
            threshold: Minimum relevance score (default: None)

        Returns:
            MemorySearchResult with matching memories and relations
        """
        user_id = self._validate_user_id(user_id)
        if not user_id:
            return MemorySearchResult()

        try:
            client = await self._get_client()

            # v2 API search with reranking for better results
            # Use filters parameter to properly scope the search
            response = await client.search(
                query=query,
                filters={"user_id": user_id},
                limit=limit,
                rerank=True,
                threshold=threshold,
            )

            # v2 API response format: {"results": [...], "relations": [...]}
            memories_list: List[Dict[str, Any]] = []
            relations_list: List[Dict[str, Any]] = []

            if isinstance(response, dict):
                # Extract memories
                memories_list = response.get("results", [])
                # Extract graph relationships if enabled
                relations_list = self._extract_relationships_from_response(response)
            elif isinstance(response, list):
                # Fallback for direct list response
                memories_list = response
            else:
                self.logger.warning(
                    f"Unexpected response format from mem0 search: {type(response)}"
                )
                return MemorySearchResult()

            # Parse memories and relationships
            memories = self._parse_memory_list(memories_list, user_id)
            relations = self._parse_relationships(relations_list)

            self.logger.debug(
                f"Search found {len(memories)} memories and {len(relations)} relations for user {user_id}"
            )

            return MemorySearchResult(
                memories=memories,
                relations=relations,
                total_count=len(memories),
            )

        except Exception as e:
            self.logger.error(f"Error searching memories for user {user_id}: {e}")
            return MemorySearchResult()

    async def get_all_memories(
        self,
        user_id: Optional[str],
    ) -> MemorySearchResult:
        """
        Get all memories for a user using Mem0 v2 API.

        Args:
            user_id: User identifier
            limit: Maximum number of memories to retrieve (default: 100)

        Returns:
            MemorySearchResult with user's memories and graph relations
        """
        user_id = self._validate_user_id(user_id)
        if not user_id:
            return MemorySearchResult()

        try:
            client = await self._get_client()

            response = await client.get_all(
                filters={"AND": [{"user_id": user_id}]}, output_format="v1.1"
            )

            logger.debug(f"{response=}")

            # v2 API response format: {"results": [...], "relations": [...]}
            memories_list: List[Dict[str, Any]] = []
            relationships_list: List[Dict[str, Any]] = []

            if isinstance(response, dict):
                # Extract memories from results
                memories_list = response.get("results", [])
                # Extract graph relationships if enabled
                relationships_list = self._extract_relationships_from_response(response)
            elif isinstance(response, list):
                # Fallback for direct list response
                memories_list = response
            else:
                self.logger.error(
                    f"Unexpected response format from mem0 get_all: {type(response)}"
                )
                return MemorySearchResult()

            # Parse memories and relationships
            memory_entries = self._parse_memory_list(memories_list, user_id)
            relationships = self._parse_relationships(relationships_list)

            self.logger.info(
                f"Retrieved {len(memory_entries)} memories and {len(relationships)} graph relations for user {user_id}"
            )

            return MemorySearchResult(
                memories=memory_entries,
                relations=relationships,
                total_count=len(memory_entries),
            )

        except Exception as e:
            self.logger.error(f"Error retrieving all memories for user {user_id}: {e}")
            return MemorySearchResult()

    async def delete_memory(self, memory_id: str, user_id: Optional[str]) -> bool:
        """
        Delete a specific memory using Mem0 v2 API.

        Args:
            memory_id: Memory identifier
            user_id: User identifier (for logging/validation)

        Returns:
            True if successful, False otherwise
        """
        user_id = self._validate_user_id(user_id)
        if not user_id:
            return False

        try:
            client = await self._get_client()

            # v2 API delete by memory_id
            result = await client.delete(memory_id=memory_id)

            self.logger.info(f"Memory {memory_id} deleted for user {user_id}: {result}")
            return True

        except Exception as e:
            self.logger.error(
                f"Error deleting memory {memory_id} for user {user_id}: {e}"
            )
            return False

    async def delete_all_memories(self, user_id: Optional[str]) -> bool:
        """
        Delete all memories for a user using Mem0 v2 API.

        Args:
            user_id: User identifier

        Returns:
            True if successful, False otherwise
        """
        user_id = self._validate_user_id(user_id)
        if not user_id:
            return False

        try:
            client = await self._get_client()

            # v2 API delete_all with user filter
            result = await client.delete_all(user_id=user_id)

            self.logger.info(f"All memories deleted for user {user_id}: {result}")
            return True

        except Exception as e:
            self.logger.error(f"Error deleting all memories for user {user_id}: {e}")
            return False


# Create singleton instance
memory_service = MemoryService()
