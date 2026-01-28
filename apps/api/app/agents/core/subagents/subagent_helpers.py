"""
Subagent Helper Functions

Reusable utilities for working with subagents, including system prompt creation
with provider metadata injection and skill retrieval.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from app.agents.memory.skill_learning.service import get_skill_learning_service
from app.agents.prompts.custom_mcp_prompts import CUSTOM_MCP_SUBAGENT_PROMPT
from app.config.loggers import common_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.services.memory_service import memory_service
from app.services.provider_metadata_service import get_provider_metadata
from langchain_core.messages import SystemMessage


async def build_subagent_system_prompt(
    integration_id: str,
    user_id: Optional[str] = None,
    base_system_prompt: Optional[str] = None,
) -> str:
    """
    Build a system prompt for a subagent with optional provider metadata injection.

    This function:
    1. Gets the base system prompt from the integration config (if not provided)
    2. Fetches provider metadata (username, etc.) for the user
    3. Injects metadata context into the system prompt

    Args:
        integration_id: The integration ID (e.g., "github", "twitter")
        user_id: The user ID to fetch metadata for (optional)
        base_system_prompt: Override the default system prompt from config (optional)

    Returns:
        The complete system prompt with metadata injected (if available)

    Example:
        >>> prompt = await build_subagent_system_prompt("github", user_id="123")
        >>> # Returns: "{base_prompt}\n\nUSER CONTEXT FOR GITHUB:\n- Username: Dhruv-Maradiya\n"
    """
    integration = get_integration_by_id(integration_id)

    if not integration:
        # Handle custom/public MCPs - use universal prompt
        # If not in OAUTH_INTEGRATIONS, it's a custom or public MCP integration
        if integration_id:
            return base_system_prompt or CUSTOM_MCP_SUBAGENT_PROMPT

        logger.warning(f"Integration {integration_id} not found")
        return base_system_prompt or ""

    # Use provided system prompt or get from integration config
    system_prompt = base_system_prompt
    if not system_prompt and integration.subagent_config:
        system_prompt = integration.subagent_config.system_prompt

    if not system_prompt:
        system_prompt = ""

    # Inject provider metadata if user_id is provided
    if user_id and integration.provider:
        try:
            metadata = await get_provider_metadata(user_id, integration.provider)
            if metadata and metadata.get("username"):
                provider_context = (
                    f"\n\nUSER CONTEXT FOR {integration.name.upper()}:\n"
                    f"- Username: {metadata['username']}\n"
                )
                system_prompt = system_prompt + provider_context
                logger.debug(
                    f"Injected {integration.provider} metadata into system prompt"
                )
        except Exception as e:
            logger.warning(f"Failed to inject provider metadata: {e}")

    return system_prompt


async def create_subagent_system_message(
    integration_id: str,
    agent_name: str,
    user_id: Optional[str] = None,
    base_system_prompt: Optional[str] = None,
) -> SystemMessage:
    """
    Create a SystemMessage for a subagent with provider metadata injected.

    This is a convenience wrapper around build_subagent_system_prompt that
    returns a LangChain SystemMessage object ready to use in message lists.

    Args:
        integration_id: The integration ID (e.g., "github", "twitter")
        agent_name: The agent name for visibility metadata
        user_id: The user ID to fetch metadata for (optional)
        base_system_prompt: Override the default system prompt from config (optional)

    Returns:
        SystemMessage with the complete prompt and visibility metadata

    Example:
        >>> msg = await create_subagent_system_message(
        ...     "github", "github_agent", user_id="123"
        ... )
        >>> # Returns SystemMessage with injected username context
    """
    system_prompt = await build_subagent_system_prompt(
        integration_id=integration_id,
        user_id=user_id,
        base_system_prompt=base_system_prompt,
    )

    return SystemMessage(content=system_prompt)


async def create_agent_context_message(
    agent_name: str,
    configurable: dict,
    user_id: Optional[str] = None,
    query: Optional[str] = None,
    thread_id: Optional[str] = None,
    subagent_id: Optional[str] = None,
) -> SystemMessage:
    """
    Create a context message with time, timezone, memories, and skills for executor/subagents.

    This ensures executor and subagents have the same temporal awareness as the main agent,
    including:
    - Current UTC time
    - User's timezone and local time (extracted from user_time)
    - Conversation memories
    - Relevant learned skills (for subagents)

    Args:
        agent_name: The agent name for visibility metadata
        configurable: The config["configurable"] dict from RunnableConfig
        user_id: Optional user ID (extracted from configurable if not provided)
        query: Optional search query for memory retrieval
        thread_id: Optional thread ID for memory session management (use conversation_id)
        subagent_id: Optional subagent ID for skill retrieval (e.g., "twitter", "github")

    Returns:
        SystemMessage with time/timezone/memories/skills context
    """
    context_parts = []

    # Extract user info from configurable
    user_id = user_id or configurable.get("user_id")
    user_name = configurable.get("user_name")
    user_time_str = configurable.get("user_time", "")

    # Add user name context
    if user_name:
        context_parts.append(f"User Name: {user_name}")

    # Add current UTC time
    utc_time = datetime.now(timezone.utc)
    formatted_utc_time = utc_time.strftime("%A, %B %d, %Y, %H:%M:%S UTC")
    context_parts.append(f"Current UTC Time: {formatted_utc_time}")

    # Extract timezone from user_time_str and add local time
    if user_time_str:
        try:
            user_time = datetime.fromisoformat(user_time_str)
            formatted_user_time = user_time.strftime("%A, %B %d, %Y, %H:%M:%S")

            # Extract timezone offset from user_time_str (e.g., +05:30 or -08:00 or Z)
            tz_match = re.search(r"([+-]\d{2}:\d{2}|Z)$", user_time_str)
            if tz_match:
                tz_offset = tz_match.group(1)
                if tz_offset == "Z":
                    tz_offset = "+00:00"
                context_parts.append(f"User Timezone Offset: {tz_offset}")
                context_parts.append(f"User Local Time: {formatted_user_time}")
            else:
                context_parts.append(f"User Local Time: {formatted_user_time}")
        except Exception as e:
            logger.warning(f"Error parsing user_time: {e}")

    # Search for conversation memories
    memories_section = ""
    if user_id and query:
        try:
            results = await memory_service.search_memories(
                query=query, user_id=user_id, limit=5
            )
            if results:
                memories = getattr(results, "memories", None)
                if memories:
                    memories_section = (
                        "\n\nBased on our previous conversations:\n"
                        + "\n".join(f"- {mem.content}" for mem in memories)
                    )
                    logger.info(f"Added {len(memories)} memories to subagent context")
        except Exception as e:
            logger.warning(f"Error retrieving memories for subagent: {e}")

    # Search for relevant skills (only for subagents)
    skills_section = ""
    if subagent_id and query:
        try:
            skill_service = get_skill_learning_service()
            result = await skill_service.search_skills(
                query=query,
                agent_id=subagent_id,
                limit=3,
            )
            if result.skills:
                skills_section = skill_service.format_skills_for_prompt(
                    result.skills, subagent_id
                )
                logger.info(
                    f"Added {len(result.skills)} skills to {subagent_id} context"
                )
        except Exception as e:
            logger.warning(f"Error retrieving skills for {subagent_id}: {e}")

    content = "\n".join(context_parts) + memories_section + skills_section

    return SystemMessage(content=content, memory_message=True)
