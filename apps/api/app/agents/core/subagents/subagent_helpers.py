"""
Subagent Helper Functions

Reusable utilities for working with subagents, including system prompt creation
with provider metadata injection.
"""

from typing import Optional

from app.config.loggers import common_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.models.oauth_models import OAuthIntegration
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
        # Handle custom MCPs - use universal prompt
        if integration_id.startswith("custom_"):
            from app.agents.prompts.custom_mcp_prompts import CUSTOM_MCP_SUBAGENT_PROMPT

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

    return SystemMessage(
        content=system_prompt,
        additional_kwargs={"visible_to": {agent_name}},
    )


def get_integration_info(integration_id: str) -> Optional[OAuthIntegration]:
    """
    Get integration configuration by ID.

    This is a simple wrapper around get_integration_by_id for convenience.

    Args:
        integration_id: The integration ID

    Returns:
        The OAuthIntegration object or None if not found
    """
    return get_integration_by_id(integration_id)
