"""Tool capabilities available to a user, for follow-up action generation.

Lives in the agents layer, not in app/services/integrations, because it reads
the agent tool registry: a service that imports the registry inverts the
dependency direction and closes an import cycle
(services -> agents -> services.composio -> services.integrations).
"""

from pydantic import ValidationError

from app.agents.tools.core.registry import get_tool_registry
from app.constants.cache import ONE_DAY_TTL
from app.constants.log_tags import LogTag
from app.decorators.caching import Cacheable
from app.models.integration_models import IntegrationCapability, UserIntegrationCapabilities
from app.services.integrations.marketplace import get_integration_details
from app.services.integrations.user_integrations import get_connected_integration_ids
from shared.py.wide_events import log


@Cacheable(
    key_pattern="tools:user:{user_id}:integration_capabilities",
    ttl=ONE_DAY_TTL,
    model=UserIntegrationCapabilities,
)
async def get_user_integration_capabilities(user_id: str) -> UserIntegrationCapabilities:
    """Get capabilities (tools) for user's connected integrations + core tools.

    Optimized for follow-up action generation to avoid passing all tools to
    the LLM. An integration whose stored document cannot be validated is
    skipped and the result flagged degraded, which keeps it out of the cache.
    """

    # Get core tools that are always available (categories that don't require integration)
    tool_registry = await get_tool_registry()
    core_categories = tool_registry.get_core_categories()

    tool_names_set = set()

    # Add core tool names
    for category in core_categories:
        for tool in category.tools:
            tool_names_set.add(tool.name)

    # Only *connected* integrations: these tool names feed user-clickable
    # follow-up suggestions, so a not-yet-connected one must not surface.
    connected_ids = await get_connected_integration_ids(user_id)

    integration_names: list[str] = []
    capabilities: dict[str, IntegrationCapability] = {}
    degraded = False

    for integration_id in connected_ids:
        try:
            integration = await get_integration_details(integration_id)
        except ValidationError as e:
            # Optional enrichment: one unreadable document (a retired integration's
            # tools-only stub) must not cost the rest. A DB outage still propagates.
            log.error(
                f"{LogTag.INTEGRATION} Skipping unresolvable integration in follow-up capabilities",
                integration_id=integration_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            degraded = True
            continue
        if not integration:
            continue

        integration_names.append(integration.name)
        tool_names_set.update(tool.name for tool in integration.tools)

        if integration.tools:
            capabilities[integration_id] = IntegrationCapability(
                name=integration.name, tools=integration.tools
            )

    return UserIntegrationCapabilities(
        integration_names=integration_names,
        tool_names=list(tool_names_set),
        capabilities=capabilities,
        degraded=degraded,
    )
