"""Resolve an integration id to its target and gate it on the user's connection."""

from app.agents.core.subagents.integration_target import CustomMcpSubagent, get_integration_target
from app.agents.core.subagents.registry import get_subagent_by_id
from app.models.subagent_models import Subagent
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import check_integration_status
from app.utils.integration_checker import request_integration_connection


def _requires_auth(target: Subagent | CustomMcpSubagent) -> bool:
    if isinstance(target, CustomMcpSubagent):
        return target.mcp_config is not None and target.mcp_config.requires_auth
    return target.managed_by == "mcp" and bool(
        target.mcp_config and target.mcp_config.requires_auth
    )


def is_per_user_mcp(target: Subagent | CustomMcpSubagent) -> bool:
    """Whether the target's tools are issued per user by an MCP server (never registry-bound)."""
    return isinstance(target, CustomMcpSubagent) or _requires_auth(target)


async def check_integration_connection(
    integration_id: str,
    user_id: str,
) -> str | None:
    """Return the connect prompt when a registry integration isn't connected, else None.

    Lives here rather than in integration_checker: it needs check_integration_status
    from oauth_service, which reaches integration_checker through composio.
    """
    subagent = get_subagent_by_id(integration_id)
    if not subagent:
        return None

    if await check_integration_status(integration_id, user_id):
        return None

    return await request_integration_connection(subagent.id, subagent.name, user_id)


async def check_mcp_connection(integration_id: str, user_id: str) -> str | None:
    """Return the connect prompt when an auth-requiring MCP has no usable credential, else None."""
    target = await get_integration_target(integration_id)
    if target is None or not _requires_auth(target):
        return None

    if await MCPTokenStore(user_id=user_id).is_connected(target.id):
        return None

    name = target.name if isinstance(target, Subagent) else (target.name or target.id)
    return await request_integration_connection(target.id, name, user_id)
