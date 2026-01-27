"""
Integration Resolver Service.

Single point of truth for integration lookups from any source.
Eliminates duplicate "check platform config, then MongoDB" pattern
across mcp_client.py, integrations.py, and integration_service.py.
"""

from dataclasses import dataclass
from typing import Optional

from app.config.loggers import common_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.db.mongodb.collections import integrations_collection
from app.models.mcp_config import MCPConfig
from app.models.oauth_models import OAuthIntegration


@dataclass
class ResolvedIntegration:
    """Unified integration data from either platform config or MongoDB."""

    integration_id: str
    name: str
    description: str
    category: str
    managed_by: str
    source: str  # "platform" or "custom"
    requires_auth: bool
    auth_type: Optional[str]  # "none", "oauth", "bearer"
    mcp_config: Optional[MCPConfig]
    # Original sources for backward compatibility
    platform_integration: Optional[OAuthIntegration]
    custom_doc: Optional[dict]


class IntegrationResolver:
    """
    Single point of truth for integration lookups.

    Checks platform integrations first (from OAUTH_INTEGRATIONS in code),
    then falls back to custom integrations in MongoDB.
    """

    @staticmethod
    async def resolve(integration_id: str) -> Optional[ResolvedIntegration]:
        """
        Resolve an integration from either platform config or MongoDB.

        Args:
            integration_id: The integration ID to look up

        Returns:
            ResolvedIntegration if found, None otherwise
        """
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
            elif platform_integration.composio_config:
                requires_auth = True
                auth_type = "oauth"
            elif platform_integration.managed_by == "self":
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
                platform_integration=platform_integration,
                custom_doc=None,
            )

        # Try custom integration from MongoDB
        custom_doc = await integrations_collection.find_one(
            {"integration_id": integration_id}
        )

        if custom_doc:
            mcp_config = None
            requires_auth = custom_doc.get("requires_auth", False)
            auth_type = custom_doc.get("auth_type", "none")

            if custom_doc.get("mcp_config"):
                mcp_config = MCPConfig(**custom_doc["mcp_config"])
                # mcp_config is authoritative, but log if document-level values conflict
                doc_requires_auth = custom_doc.get("requires_auth", False)
                mcp_requires_auth = mcp_config.requires_auth
                mcp_auth_type = mcp_config.auth_type or (
                    "oauth" if mcp_requires_auth else "none"
                )

                # Warn about inconsistencies - helps identify data integrity issues
                if doc_requires_auth != mcp_requires_auth:
                    logger.warning(
                        f"Integration {integration_id}: mcp_config.requires_auth "
                        f"({mcp_requires_auth}) differs from document requires_auth "
                        f"({doc_requires_auth}). Using mcp_config value."
                    )

                requires_auth = mcp_requires_auth
                auth_type = mcp_auth_type

            return ResolvedIntegration(
                integration_id=integration_id,
                name=custom_doc.get("name", integration_id),
                description=custom_doc.get("description", ""),
                category=custom_doc.get("category", "custom"),
                managed_by=custom_doc.get("managed_by", "mcp"),
                source="custom",
                requires_auth=requires_auth,
                auth_type=auth_type,
                mcp_config=mcp_config,
                platform_integration=None,
                custom_doc=custom_doc,
            )

        return None

    @staticmethod
    async def get_mcp_config(integration_id: str) -> Optional[MCPConfig]:
        """
        Get MCPConfig for an integration from either source.

        Args:
            integration_id: The integration ID to look up

        Returns:
            MCPConfig if found and integration is MCP-based, None otherwise
        """
        resolved = await IntegrationResolver.resolve(integration_id)
        return resolved.mcp_config if resolved else None

    @staticmethod
    async def get_server_url(integration_id: str) -> Optional[str]:
        """
        Get server URL for an MCP integration.

        Args:
            integration_id: The integration ID

        Returns:
            Server URL string if found, None otherwise
        """
        mcp_config = await IntegrationResolver.get_mcp_config(integration_id)
        return mcp_config.server_url if mcp_config else None

    @staticmethod
    async def is_mcp_integration(integration_id: str) -> bool:
        """Check if an integration is MCP-based."""
        resolved = await IntegrationResolver.resolve(integration_id)
        return resolved is not None and resolved.managed_by == "mcp"

    @staticmethod
    async def requires_authentication(integration_id: str) -> bool:
        """Check if an integration requires authentication."""
        resolved = await IntegrationResolver.resolve(integration_id)
        return resolved.requires_auth if resolved else False
