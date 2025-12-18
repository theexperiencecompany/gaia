"""Acontext space management with caching.

Provides cached space management for subagents.
Each subagent gets a dedicated space that is loaded once and cached.
"""

from typing import Any, Dict, List, Optional

from acontext import AcontextClient
from acontext.types.space import ListSpacesOutput
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.core.acontext_client import get_acontext_client


class AcontextSpaceManager:
    """Manages Acontext spaces and sessions with caching support.

    Caches space mappings to avoid creating duplicate spaces on reload.
    Caches sessions by (subagent_name, thread_id) to maintain one session per conversation.
    Uses get_or_create pattern for both spaces and sessions.
    """

    def __init__(self, client: AcontextClient):
        self._space_cache: Dict[str, str] = {}  # subagent_name -> space_id
        self._session_cache: Dict[
            str, str
        ] = {}  # "{subagent_name}:{thread_id}" -> session_id
        self._initialized: bool = False
        self._client = client

    async def _get_client(self):
        """Get the Acontext client instance."""

        return await get_acontext_client()

    async def load_existing_spaces(self) -> None:
        """Load all existing spaces from Acontext and populate cache.

        Should be called once when the provider is initialized.
        """
        if self._initialized:
            return

        if not settings.ACONTEXT_ENABLED:
            self._initialized = True
            return

        try:
            # List all existing spaces and cache them by name
            spaces: ListSpacesOutput = self._client.spaces.list(limit=100)

            if not isinstance(spaces, ListSpacesOutput):
                return

            for space in spaces.items:
                space_name = space.configs.get("name") if space.configs else None
                if not (space_name and space_name.endswith("_skills")):
                    continue

                subagent_name = space_name[:-7]
                self._space_cache[subagent_name] = space.id
                logger.debug(f"Loaded existing space for '{subagent_name}': {space.id}")

            logger.info(f"Loaded {len(self._space_cache)} existing Acontext spaces")
            self._initialized = True

        except Exception as e:
            logger.warning(f"Failed to load existing Acontext spaces: {e}")
            self._initialized = True

    async def get_or_create_space(self, subagent_name: str) -> Optional[str]:
        """Get existing space or create new one for a subagent.

        Args:
            subagent_name: Name of the subagent

        Returns:
            Space ID or None if creation fails
        """
        if not settings.ACONTEXT_ENABLED:
            return None

        # Ensure existing spaces are loaded
        await self.load_existing_spaces()

        # Check cache first
        if subagent_name in self._space_cache:
            return self._space_cache[subagent_name]

        # Create new space
        try:
            space = self._client.spaces.create(
                configs={"name": f"{subagent_name}_skills"}
            )
            self._space_cache[subagent_name] = space.id
            logger.info(f"Created Acontext space for '{subagent_name}': {space.id}")
            return space.id

        except Exception as e:
            logger.warning(
                f"Failed to create Acontext space for '{subagent_name}': {e}"
            )
            return None

    def get_or_create_session(
        self, subagent_name: str, thread_id: str, space_id: str
    ) -> Optional[str]:
        """Get existing session or create new one for a conversation.

        Sessions are cached by (subagent_name, thread_id) composite key.
        Same thread_id = same conversation = same Acontext session.

        Args:
            subagent_name: Name of the subagent
            thread_id: Conversation thread ID
            space_id: Space ID to create session in

        Returns:
            Session ID or None if creation fails
        """
        if not settings.ACONTEXT_ENABLED:
            return None

        cache_key = f"{subagent_name}:{thread_id}"

        # Check cache first
        if cache_key in self._session_cache:
            logger.debug(f"Reusing cached session for '{cache_key}'")
            return self._session_cache[cache_key]

        # Create new session
        try:
            session = self._client.sessions.create(
                space_id=space_id,
                configs={
                    "mode": "chat",
                    "subagent": subagent_name,
                    "thread_id": thread_id,
                },
            )
            self._session_cache[cache_key] = session.id
            logger.info(f"Created Acontext session for '{cache_key}': {session.id}")
            return session.id

        except Exception as e:
            logger.warning(f"Failed to create Acontext session for '{cache_key}': {e}")
            return None

    def get_cached_space(self, subagent_name: str) -> Optional[str]:
        """Get space from cache without creating.

        Args:
            subagent_name: Name of the subagent

        Returns:
            Space ID or None if not in cache
        """
        return self._space_cache.get(subagent_name)

    def get_cached_session(self, subagent_name: str, thread_id: str) -> Optional[str]:
        """Get session from cache without creating.

        Args:
            subagent_name: Name of the subagent
            thread_id: Conversation thread ID

        Returns:
            Session ID or None if not in cache
        """
        cache_key = f"{subagent_name}:{thread_id}"
        return self._session_cache.get(cache_key)

    def clear_cache(self) -> None:
        """Clear the space and session caches. Useful for testing."""
        self._space_cache.clear()
        self._session_cache.clear()
        self._initialized = False


_space_manager: Optional[AcontextSpaceManager] = None


async def get_space_manager() -> Optional[AcontextSpaceManager]:
    global _space_manager
    if _space_manager:
        return _space_manager

    client = await get_acontext_client()

    if not client:
        return None

    return AcontextSpaceManager(client)


async def get_subagent_space(subagent_name: str) -> Optional[str]:
    """Get or create the Acontext space for a subagent.

    Args:
        subagent_name: The subagent identifier

    Returns:
        Space ID or None if creation fails
    """
    space_manager = await get_space_manager()
    if not space_manager:
        return None

    return await space_manager.get_or_create_space(subagent_name)


async def get_subagent_session(
    subagent_name: str, thread_id: str, space_id: str
) -> Optional[str]:
    """Get or create the Acontext session for a conversation.

    Sessions are cached by (subagent_name, thread_id) - same conversation
    will reuse the same session.

    Args:
        subagent_name: The subagent identifier
        thread_id: The conversation thread ID
        space_id: The space ID to create session in

    Returns:
        Session ID or None if creation fails
    """
    space_manager = await get_space_manager()
    if not space_manager:
        return None

    return space_manager.get_or_create_session(subagent_name, thread_id, space_id)


async def search_skills(
    subagent_name: str,
    query: str,
    limit: int = 10,
    mode: str = "fast",
) -> List[Dict[str, Any]]:
    """Search learned skills for a subagent.

    Args:
        subagent_name: The subagent identifier
        query: Search query text
        limit: Maximum number of results
        mode: Search mode ("fast" or "agentic")

    Returns:
        List of skill blocks with title, content, and distance
    """
    try:
        space_id = await get_subagent_space(subagent_name)
        if not space_id:
            return []

        client = await get_acontext_client()
        if not client:
            return []

        result = client.spaces.experience_search(
            space_id=space_id,
            query=query,
            limit=limit,
            mode=mode,
        )

        return [
            {
                "title": block.title,
                "content": block.content,
                "distance": block.distance,
            }
            for block in result.cited_blocks
        ]

    except Exception as e:
        logger.warning(f"Skill search failed for '{subagent_name}': {e}")
        return []
