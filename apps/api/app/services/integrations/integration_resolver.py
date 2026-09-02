"""
Integration Resolver Service.

Single point of truth for integration lookups from any source.
Eliminates duplicate "check platform config, then MongoDB" pattern
across mcp_client.py, integrations.py, and integration_service.py.
"""

from dataclasses import dataclass

from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.models.cli_config import CliConfig
from app.models.integration_provider import ManagedBy
from app.models.mcp_config import MCPConfig
from app.models.oauth_models import OAuthIntegration
from shared.py.wide_events import log


@dataclass
class ResolvedIntegration:
    """Unified integration data from either platform config or MongoDB."""

    integration_id: str
    name: str
    description: str
    category: str
    managed_by: ManagedBy
    source: str  # "platform" or "custom"
    requires_auth: bool
    auth_type: str | None  # "none", "oauth", "bearer"
    mcp_config: MCPConfig | None
    cli_config: CliConfig | None
    # Original sources for backward compatibility
    platform_integration: OAuthIntegration | None
    custom_doc: dict | None


class IntegrationResolver:
    """
    Single point of truth for integration lookups.

    Checks platform integrations first (from OAUTH_INTEGRATIONS in code),
    then falls back to custom integrations in MongoDB.
    """

    @staticmethod
    async def resolve(integration_id: str) -> ResolvedIntegration | None:
        """Resolve an integration from either platform config or MongoDB."""
        log.set(integration={"provider": integration_id, "action": "resolve"})
        # Try platform integration first (from code)
        platform_integration = get_integration_by_id(integration_id)

        if platform_integration:
            # Determine auth requirements
            requires_auth = False
            auth_type = None

            if platform_integration.mcp_config:
                requires_auth = platform_integration.mcp_config.requires_auth
                auth_type = platform_integration.mcp_config.auth_type or (
                    "oauth" if requires_auth else "none"
                )
            elif platform_integration.composio_config or platform_integration.managed_by == "self":
                requires_auth = True
                auth_type = "oauth"

            return ResolvedIntegration(
                integration_id=integration_id,
                name=platform_integration.name,
                description=platform_integration.description,
                category=platform_integration.category,
                managed_by=platform_integration.managed_by,
                source="platform",
                requires_auth=requires_auth,
                auth_type=auth_type,
                mcp_config=platform_integration.mcp_config,
                cli_config=platform_integration.cli_config,
                platform_integration=platform_integration,
                custom_doc=None,
            )

        # Try custom integration from MongoDB
        integration = await integration_repository.get(integration_id)

        if integration:
            mcp_config = integration.mcp_config
            requires_auth = integration.requires_auth
            auth_type = integration.auth_type or "none"

            if integration.cli_config:
                # A CLI's auth shape is declared by its own spec, not by the
                # MCP-flavoured document fields.
                requires_auth = integration.cli_config.auth.kind != "none"

            if mcp_config:
                # mcp_config is authoritative, but log if document-level values conflict
                doc_requires_auth = integration.requires_auth
                mcp_requires_auth = mcp_config.requires_auth
                mcp_auth_type = mcp_config.auth_type or ("oauth" if mcp_requires_auth else "none")

                # Warn about inconsistencies and fix them
                if doc_requires_auth != mcp_requires_auth:
                    log.info(
                        f"{LogTag.INTEGRATION} Integration : syncing requires_auth from to (mcp_config is authoritative)",
                        integration_id=integration_id,
                        doc_requires_auth=doc_requires_auth,
                        mcp_requires_auth=mcp_requires_auth,
                    )
                    # Sync MongoDB document to match authoritative mcp_config
                    try:
                        await integration_repository.heal_top_level_auth(
                            integration_id, mcp_requires_auth, mcp_auth_type
                        )
                    except Exception as sync_err:
                        log.warning(
                            f"{LogTag.INTEGRATION} Failed to sync requires_auth for",
                            integration_id=integration_id,
                            error=str(sync_err),
                            error_type=type(sync_err).__name__,
                        )

                requires_auth = mcp_requires_auth
                auth_type = mcp_auth_type

            return ResolvedIntegration(
                integration_id=integration_id,
                name=integration.name or integration_id,
                description=integration.description,
                category=integration.category,
                managed_by=integration.managed_by,
                source="custom",
                requires_auth=requires_auth,
                auth_type=auth_type,
                mcp_config=mcp_config,
                cli_config=integration.cli_config,
                platform_integration=None,
                custom_doc=integration.model_dump(),
            )

        return None

    @staticmethod
    async def get_mcp_config(integration_id: str) -> MCPConfig | None:
        """Get the MCPConfig for an integration from either source, if MCP-based."""
        resolved = await IntegrationResolver.resolve(integration_id)
        return resolved.mcp_config if resolved else None

    @staticmethod
    async def get_server_url(integration_id: str) -> str | None:
        """Get the server URL for an MCP integration, if any."""
        mcp_config = await IntegrationResolver.get_mcp_config(integration_id)
        return mcp_config.server_url if mcp_config else None
