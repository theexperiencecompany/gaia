"""Creating an MCP-backed integration."""

from __future__ import annotations

from typing import ClassVar

from app.models.integration_models import CreateCustomIntegrationRequest
from app.models.integration_provider import ManagedBy
from app.services.integrations.authoring.base import (
    AuthoredIntegration,
    IntegrationAuthor,
    IntegrationBlueprint,
    McpBlueprint,
    register_author,
)
from app.services.integrations.custom_crud import create_and_connect_custom_integration
from app.services.mcp.mcp_client import get_mcp_client
from app.utils.url_safety import assert_safe_url_shape


class McpIntegrationAuthor(IntegrationAuthor):
    """Wraps the existing custom-MCP creation path.

    Adds no logic of its own: MCP creation already probes the server, discovers
    its auth requirements and pulls the live tool list, and that behaviour is
    what the UI flow relies on. This exists so a caller can create an MCP
    integration and a CLI integration through the same call.
    """

    kind: ClassVar[str] = "mcp"
    managed_by: ClassVar[ManagedBy] = "mcp"

    async def create(self, user_id: str, blueprint: IntegrationBlueprint) -> AuthoredIntegration:
        if not isinstance(blueprint, McpBlueprint):  # pragma: no cover - dispatch guarantees this
            raise TypeError(f"{type(self).__name__} cannot author a {blueprint.kind!r} blueprint")

        # Same SSRF shape check the HTTP request model applies. Re-asserted here
        # because this path is reachable from a chat tool, which never went
        # through that model.
        assert_safe_url_shape(blueprint.server_url)

        request = CreateCustomIntegrationRequest(
            name=blueprint.name,
            description=blueprint.description or None,
            category=blueprint.category,
            server_url=blueprint.server_url,
            requires_auth=blueprint.requires_auth,
            auth_type=blueprint.auth_type,
            is_public=False,
            bearer_token=blueprint.bearer_token,
        )
        mcp_client = await get_mcp_client(user_id=user_id)
        integration, result = await create_and_connect_custom_integration(
            user_id, request, mcp_client
        )

        status = str(result.get("status", ""))
        connected = status == "connected"
        return AuthoredIntegration(
            integration=integration,
            needs_connection=not connected,
            note=(
                f"Connected. {result.get('tools_count', 0)} tools available."
                if connected
                else str(result.get("error") or "Connect it to finish authenticating.")
            ),
        )


register_author(McpIntegrationAuthor())
