"""Memory service — thin delegation layer over the GAIA memory engine.

Kept as a class + singleton so the existing call sites (endpoints, tools,
email pipeline) keep importing ``memory_service``. Every method delegates
straight to ``memory_engine``; caching and cache invalidation live inside
the engine (``recall`` is Redis-cached, every mutation invalidates), so
this layer adds no decorators of its own.
"""

from app.constants.memory import MemorySourceType
from app.memory.engine import memory_engine
from app.models.memory_models import MemoryEntry, MemorySearchResult
from shared.py.wide_events import log

_GET_ALL_PAGE_SIZE = 200


class MemoryService:
    """Service facade for memory operations, backed by the memory engine."""

    async def store_memory(
        self,
        content: str,
        user_id: str | None,
        *,
        category_path: str | None = None,
        source_type: MemorySourceType = MemorySourceType.MANUAL,
    ) -> MemoryEntry | None:
        """Store one explicit fact. Returns the stored (or deduplicated) entry."""
        if not user_id:
            log.warning("No user_id provided for memory operation")
            return None
        try:
            return await memory_engine.retain_single(
                user_id, content, category_path=category_path, source_type=source_type
            )
        except Exception as e:
            log.error(f"Error storing memory for user {user_id}: {e}")
            return None

    async def store_memory_batch(
        self,
        messages: list[dict[str, str]],
        user_id: str | None,
        *,
        source_type: MemorySourceType,
        source_id: str | None = None,
        extraction_hints: str | None = None,
        user_name: str | None = None,
    ) -> bool:
        """Ingest a transcript (conversation, email batch, ...) into memory.

        Returns True when the extractor found anything worth remembering.
        """
        if not user_id:
            log.warning("No user_id provided for memory batch")
            return False
        try:
            result = await memory_engine.retain(
                user_id,
                messages,
                source_type=source_type,
                source_id=source_id,
                extraction_hints=extraction_hints,
                user_name=user_name,
            )
            return result.facts_extracted > 0 or result.episode_entries > 0
        except Exception as e:
            log.error(f"Error storing memory batch for user {user_id}: {e}")
            return False

    async def search_memories(
        self,
        query: str,
        user_id: str | None,
        limit: int = 5,
    ) -> MemorySearchResult:
        """Hybrid memory search (engine ``recall``; cached inside the engine)."""
        if not user_id:
            return MemorySearchResult()
        try:
            return await memory_engine.recall(user_id, query, limit=limit)
        except Exception as e:
            log.error(f"Error searching memories for user {user_id}: {e}")
            return MemorySearchResult()

    async def get_all_memories(self, user_id: str | None) -> MemorySearchResult:
        """All live memories for a user, newest first."""
        if not user_id:
            return MemorySearchResult()
        try:
            memories: list[MemoryEntry] = []
            page = 1
            while True:
                batch = await memory_engine.list_memories(
                    user_id, page=page, page_size=_GET_ALL_PAGE_SIZE
                )
                memories.extend(batch.memories)
                if len(memories) >= batch.total_count or not batch.memories:
                    return MemorySearchResult(memories=memories, total_count=batch.total_count)
                page += 1
        except Exception as e:
            log.error(f"Error retrieving all memories for user {user_id}: {e}")
            return MemorySearchResult()

    async def delete_memory(self, memory_id: str, user_id: str | None) -> bool:
        """Soft-delete one memory (kept for lineage history, hidden from recall)."""
        if not user_id:
            return False
        try:
            return await memory_engine.forget_memory(user_id, memory_id, reason="Deleted by user")
        except Exception as e:
            log.error(f"Error deleting memory {memory_id} for user {user_id}: {e}")
            return False

    async def delete_all_memories(self, user_id: str | None) -> bool:
        """Hard-wipe a user's entire memory."""
        if not user_id:
            return False
        try:
            await memory_engine.delete_all(user_id)
            return True
        except Exception as e:
            log.error(f"Error deleting all memories for user {user_id}: {e}")
            return False


memory_service = MemoryService()
