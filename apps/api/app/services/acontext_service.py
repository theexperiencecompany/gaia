"""
Acontext Service - Fetches contextual skills for subagents.

This service integrates with the hosted Acontext API to provide
relevant skills/context to subagents based on the current query.

Uses conversation_id as thread_id to maintain session consistency
across the same conversation thread.
"""

import httpx
from typing import Optional

from app.config.loggers import common_logger as logger
from app.config.settings import settings


ACONTEXT_BASE_URL = "https://api.acontext.ai"
ACONTEXT_TIMEOUT = 10.0  # seconds


class AcontextService:
    """Service for fetching contextual skills from Acontext API."""

    def __init__(self):
        self._api_key: Optional[str] = None

    @property
    def api_key(self) -> Optional[str]:
        """Lazy load API key from settings."""
        if self._api_key is None:
            self._api_key = getattr(settings, "ACONTEXT_API_KEY", None)
        return self._api_key

    @property
    def is_configured(self) -> bool:
        """Check if Acontext is properly configured."""
        return bool(self.api_key)

    async def fetch_skills(
        self,
        query: str,
        thread_id: str,
        agent_name: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 5,
    ) -> Optional[str]:
        """
        Fetch relevant skills/context from Acontext API.

        Args:
            query: The user's query/task
            thread_id: Thread ID for session management (use conversation_id)
            agent_name: Optional agent name for context
            user_id: Optional user ID for personalization
            limit: Maximum number of skills to fetch

        Returns:
            Formatted skills string to inject into system prompt, or None if unavailable
        """
        if not self.is_configured:
            logger.debug("Acontext not configured, skipping skill fetch")
            return None

        try:
            async with httpx.AsyncClient(timeout=ACONTEXT_TIMEOUT) as client:
                response = await client.post(
                    f"{ACONTEXT_BASE_URL}/v1/skills/search",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "thread_id": thread_id,
                        "agent_name": agent_name,
                        "user_id": user_id,
                        "limit": limit,
                    },
                )

                if response.status_code != 200:
                    logger.warning(
                        f"Acontext API returned {response.status_code}: {response.text}"
                    )
                    return None

                data = response.json()
                skills = data.get("skills", [])

                if not skills:
                    logger.debug("No skills returned from Acontext")
                    return None

                return self._format_skills(skills)

        except httpx.TimeoutException:
            logger.warning("Acontext API request timed out")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Acontext API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching Acontext skills: {e}")
            return None

    def _format_skills(self, skills: list) -> str:
        """Format skills list into a prompt-friendly string."""
        if not skills:
            return ""

        formatted_parts = ["\n\nRELEVANT SKILLS AND CONTEXT:"]

        for i, skill in enumerate(skills, 1):
            name = skill.get("name", f"Skill {i}")
            content = skill.get("content", "")
            description = skill.get("description", "")

            if content:
                formatted_parts.append(f"\n[{name}]")
                if description:
                    formatted_parts.append(f"Description: {description}")
                formatted_parts.append(f"{content}")

        return "\n".join(formatted_parts)

    async def record_skill_usage(
        self,
        thread_id: str,
        skill_id: str,
        was_helpful: bool = True,
    ) -> bool:
        """
        Record skill usage feedback for learning.

        Args:
            thread_id: Thread ID for session
            skill_id: The skill that was used
            was_helpful: Whether the skill was helpful

        Returns:
            True if feedback was recorded successfully
        """
        if not self.is_configured:
            return False

        try:
            async with httpx.AsyncClient(timeout=ACONTEXT_TIMEOUT) as client:
                response = await client.post(
                    f"{ACONTEXT_BASE_URL}/v1/skills/feedback",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "thread_id": thread_id,
                        "skill_id": skill_id,
                        "was_helpful": was_helpful,
                    },
                )
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"Failed to record skill feedback: {e}")
            return False


# Singleton instance
acontext_service = AcontextService()


async def get_acontext_skills(
    query: str,
    thread_id: str,
    agent_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """
    Convenience function to fetch Acontext skills.

    Args:
        query: The user's query/task
        thread_id: Thread ID for session management (use conversation_id)
        agent_name: Optional agent name for context
        user_id: Optional user ID for personalization

    Returns:
        Formatted skills string or None
    """
    return await acontext_service.fetch_skills(
        query=query,
        thread_id=thread_id,
        agent_name=agent_name,
        user_id=user_id,
    )
