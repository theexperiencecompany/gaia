"""Tool capabilities available to a user, for follow-up action generation.

Lives in the agents layer, not in ``app/services/integrations``, because it reads
the agent tool registry: a service that imports the registry inverts the
dependency direction and closes an import cycle
(services -> agents -> services.composio -> services.integrations).
"""

from typing import Any

from app.agents.tools.core.registry import get_tool_registry
from app.constants.cache import ONE_DAY_TTL
from app.decorators.caching import Cacheable
from app.models.integration_models import IntegrationTool
from app.services.integrations.marketplace import get_integration_details
from app.services.integrations.user_integrations import get_connected_integration_ids


@Cacheable(key_pattern="tools:user:{user_id}:integration_capabilities", ttl=ONE_DAY_TTL)
async def get_user_integration_capabilities(user_id: str) -> dict[str, Any]:
    """
    Get capabilities (tools) for user's connected integrations + core tools.

    This is optimized for follow-up action generation to avoid passing
    all tools to the LLM. Instead, only tools from user's connected
    integrations plus core built-in tools are included.

    Returns:
        Dict with:
        - integration_names: List of connected integration names
        - tool_names: List of available tool names (core + integrations)
        - capabilities: Dict mapping integration_id -> list of tool info
    """

    # Get core tools that are always available (categories that don't require integration)
    tool_registry = await get_tool_registry()
    core_categories = tool_registry.get_core_categories()

    tool_names_set = set()

    # Add core tool names
    for category in core_categories:
        for tool in category.tools:
            tool_names_set.add(tool.name)

    # Only the user's *connected* (authenticated) integrations. These tool names
    # feed user-clickable follow-up suggestions, so a merely-added but
    # not-yet-connected integration must not surface — its suggested action would
    # fail at execution time.
    connected_ids = await get_connected_integration_ids(user_id)

    integration_names = []
    capabilities = {}

    for integration_id in connected_ids:
        # Get integration details with tools
        integration = await get_integration_details(integration_id)
        if not integration:
            continue

        integration_names.append(integration.name)

        # Extract tool names and descriptions
        tools_info = []
        integration_tool: IntegrationTool
        for integration_tool in integration.tools:
            tool_names_set.add(integration_tool.name)
            tools_info.append(
                {
                    "name": integration_tool.name,
                    "description": integration_tool.description or "",
                }
            )

        if tools_info:
            capabilities[integration_id] = {
                "name": integration.name,
                "tools": tools_info,
            }

    return {
        "integration_names": integration_names,
        "tool_names": list(tool_names_set),
        "capabilities": capabilities,
    }
