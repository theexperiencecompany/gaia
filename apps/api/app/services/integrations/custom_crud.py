"""Custom integration CRUD operations."""

from datetime import UTC, datetime
from typing import Any, cast
import uuid

from mcp_use.client.exceptions import OAuthAuthenticationError
from sqlalchemy import delete

from app.constants.log_tags import LogTag
from app.db.chroma.chroma_cleanup import cleanup_integration_chroma_data
from app.db.chroma.public_integrations_store import remove_public_integration
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache, delete_cache_by_pattern
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.helpers.mcp_helpers import get_api_base_url
from app.models.db_oauth import MCPCredential
from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
    IntegrationUpdate,
    UpdateCustomIntegrationRequest,
)
from app.models.mcp_config import MCPConfig
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.integrations.user_integrations import (
    add_user_integration,
    invalidate_user_integration_caches,
    remove_user_integration,
)
from app.services.mcp.mcp_client import MCPClient
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.utils.favicon_utils import fetch_favicon_safely
from shared.py.wide_events import log


async def create_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    icon_url: str | None = None,
) -> Integration:
    """Create a custom MCP integration."""
    log.set(integration={"provider": request.name, "action": "create_custom_integration"})
    # uuid4 collision probability is negligible (~10^-36); no orphan check needed.
    integration_id = str(uuid.uuid4())

    integration = Integration(
        integration_id=integration_id,
        name=request.name,
        description=request.description or "",
        category=request.category,
        managed_by="mcp",
        source="custom",
        is_public=request.is_public,
        created_by=user_id,
        icon_url=icon_url,
        display_priority=0,
        is_featured=False,
        mcp_config=MCPConfig(
            server_url=request.server_url,
            requires_auth=request.requires_auth,
            auth_type=request.auth_type,
        ),
        created_at=datetime.now(UTC),
        published_at=None,
        clone_count=0,
    )

    await integration_repository.create(integration)

    try:
        await add_user_integration(user_id, integration_id, initial_status="created")
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Failed to add user_integration, rolling back",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        await integration_repository.delete(integration_id)
        raise

    return integration


async def _updated_mcp_config(
    user_id: str,
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
    doc: Integration,
) -> MCPConfig:
    """The integration's MCP config with this request's changes applied.

    Pointing an integration at a different server orphans the vector data
    indexed under the old one, so that is cleaned up here rather than left to
    accumulate. Best effort: a stale namespace is not worth failing the edit.
    """
    config_changes: dict[str, object] = {}

    if request.server_url is not None:
        old_server_url = doc.mcp_config.server_url if doc.mcp_config else ""
        config_changes["server_url"] = request.server_url
        if old_server_url and old_server_url != request.server_url:
            try:
                await cleanup_integration_chroma_data(integration_id, old_server_url)
            except Exception as e:
                log.warning(
                    f"{LogTag.INTEGRATION} Failed to clean old namespace for",
                    integration_id=integration_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )

    if request.requires_auth is not None:
        config_changes["requires_auth"] = request.requires_auth
    if request.auth_type is not None:
        config_changes["auth_type"] = request.auth_type

    if doc.mcp_config:
        return doc.mcp_config.model_copy(update=config_changes)
    return MCPConfig.model_validate(config_changes)


async def update_custom_integration(
    user_id: str,
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
) -> Integration | None:
    """Update a custom integration (creator only)."""
    log.set(integration={"provider": integration_id, "action": "update_custom_integration"})
    doc = await integration_repository.get_custom_for_user(integration_id, user_id)

    if not doc:
        return None

    changes: dict[str, object] = {"updated_at": datetime.now(UTC)}
    for field in ("name", "description", "is_public"):
        value = getattr(request, field)
        if value is not None:
            changes[field] = value

    if any([request.server_url, request.requires_auth, request.auth_type]):
        changes["mcp_config"] = await _updated_mcp_config(user_id, integration_id, request, doc)

    update = IntegrationUpdate.model_validate(changes)
    updated = await integration_repository.update(integration_id, update)

    # name / description / is_public all embed into every connected user's cached
    # catalog item (MyIntegrationItem + connected-list). Bust those users so the
    # change shows next turn instead of lingering for the 24h cache TTL.
    catalog_fields = {"name", "description", "is_public"}
    if catalog_fields & update.model_dump(exclude_unset=True).keys():
        for affected_user_id in await user_integration_repository.user_ids_with_integration(
            integration_id
        ):
            await invalidate_user_integration_caches(affected_user_id)

    return updated


async def _unpublish(integration_id: str) -> None:
    """Drop a published integration from the public store and the cached list.

    Best effort: a failure here leaves a stale marketplace entry, which is worth
    a warning but not worth failing the delete the user asked for.
    """
    try:
        await remove_public_integration(integration_id)
    except Exception as e:
        log.warning(
            f"{LogTag.INTEGRATION} Failed to remove from public integrations",
            error=str(e),
            error_type=type(e).__name__,
            integration_id=integration_id,
        )
    await delete_cache_by_pattern("marketplace:community:*")


async def _unlink_every_user(integration_id: str) -> None:
    """Remove every user's link to an integration whose catalog row is gone.

    Goes through the canonical mutator per user so each row delete and its cache
    invalidation stay coupled.
    """
    for affected_user_id in await user_integration_repository.user_ids_with_integration(
        integration_id
    ):
        try:
            await remove_user_integration(affected_user_id, integration_id)
        except Exception as e:
            log.debug(
                f"{LogTag.INTEGRATION} Failed to remove integration for user",
                affected_user_id=affected_user_id,
                error=str(e),
                error_type=type(e).__name__,
            )


async def _delete_credentials(integration_id: str, user_id: str | None = None) -> None:
    """Delete stored MCP credentials for an integration, or for one user of it."""
    conditions = [MCPCredential.integration_id == integration_id]
    if user_id is not None:
        conditions.append(MCPCredential.user_id == user_id)
    try:
        async with get_db_session() as session:
            await session.execute(delete(MCPCredential).where(*conditions))
            await session.commit()
    except Exception as e:
        log.warning(
            f"{LogTag.INTEGRATION} Failed to delete MCP credentials",
            error=str(e),
            error_type=type(e).__name__,
            integration_id=integration_id,
            user_id=user_id,
        )


async def _clear_derived_state(integration_id: str, doc: Integration) -> None:
    """Drop the caches and vector data derived from an integration."""
    try:
        await delete_cache("mcp:tools:all")
    except Exception as e:
        log.debug(
            f"{LogTag.INTEGRATION} Cache deletion for mcp:tools:all failed",
            error=str(e),
            error_type=type(e).__name__,
        )
    try:
        server_url = doc.mcp_config.server_url if doc.mcp_config else ""
        await cleanup_integration_chroma_data(integration_id, server_url)
    except Exception as e:
        log.debug(
            f"{LogTag.INTEGRATION} Chroma store deletion failed for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def _delete_as_creator(user_id: str, integration_id: str, doc: Integration) -> bool:
    """Remove the integration itself, and everything derived from it."""
    if doc.is_public:
        await _unpublish(integration_id)

    if not await integration_repository.delete_custom(integration_id, user_id):
        return False

    await _unlink_every_user(integration_id)
    await _delete_credentials(integration_id)
    await _clear_derived_state(integration_id, doc)
    return True


async def delete_custom_integration(user_id: str, integration_id: str) -> bool:
    """Delete or remove a custom integration based on ownership.

    Three cases, and the ownership check is what separates them: no catalog row
    at all, the creator (who removes the integration for everyone), and everyone
    else (who only drops their own link and credential).
    """
    log.set(integration={"provider": integration_id, "action": "delete_custom_integration"})
    doc = await integration_repository.get_custom(integration_id)

    if not doc:
        # No catalog row — just drop this user's link. The mutator deletes the
        # row and invalidates atomically, returning False if there was nothing.
        # @CacheInvalidator erases the wrapped function's return type to Any
        # (see app/decorators/caching.py); cast back to the real contract.
        return cast(bool, await remove_user_integration(user_id, integration_id))

    if doc.created_by == user_id:
        return await _delete_as_creator(user_id, integration_id, doc)

    if not await remove_user_integration(user_id, integration_id):
        return False
    await _delete_credentials(integration_id, user_id)
    return True


async def create_and_connect_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    mcp_client: MCPClient,
) -> tuple[Integration, dict]:
    """Create a custom integration and attempt connection."""
    log.set(
        integration={
            "provider": request.name,
            "action": "create_and_connect_custom_integration",
        }
    )
    icon_url = await fetch_favicon_safely(request.server_url)
    integration = await create_custom_integration(user_id, request, icon_url)
    integration_id = integration.integration_id

    # Bearer token flow - store and connect
    if request.bearer_token:
        return await _connect_with_bearer_token(
            user_id, integration_id, request.bearer_token, mcp_client
        )

    # Probe for auth requirements
    probe_result = await _probe_connection_safely(mcp_client, request.server_url)
    if probe_result.get("error"):
        return integration, {"status": "failed", "error": probe_result["error"]}

    if probe_result.get("requires_auth"):
        await mcp_client.update_integration_auth_status(
            integration_id,
            requires_auth=True,
            auth_type=probe_result.get("auth_type", "oauth"),
        )
        return integration, await _build_oauth_result(mcp_client, integration_id)

    # No auth required - try direct connection
    return await _connect_without_auth(integration, mcp_client)


async def _probe_connection_safely(mcp_client: MCPClient, server_url: str) -> dict[str, Any]:
    """Probe connection with error handling."""
    try:
        return cast(dict[str, Any], await mcp_client.probe_connection(server_url))
    except Exception as e:
        return {"error": str(e)}


async def _connect_with_bearer_token(
    user_id: str, integration_id: str, bearer_token: str, mcp_client: MCPClient
) -> tuple[Any, dict]:
    """Store bearer token and attempt connection."""
    token_store = MCPTokenStore(user_id)
    await token_store.store_bearer_token(integration_id, bearer_token)

    try:
        tools = await mcp_client.connect(integration_id)
        await update_user_integration_status(user_id, integration_id, "connected")
        return await _get_integration(integration_id), {
            "status": "connected",
            "tools_count": len(tools) if tools else 0,
        }
    except Exception as e:
        return await _get_integration(integration_id), {
            "status": "failed",
            "error": str(e),
        }


async def _connect_without_auth(
    integration: Integration, mcp_client: MCPClient
) -> tuple[Integration, dict]:
    """Attempt connection without authentication."""
    try:
        tools = await mcp_client.connect(integration.integration_id)
        return integration, {
            "status": "connected",
            "tools_count": len(tools) if tools else 0,
        }
    except OAuthAuthenticationError:
        await mcp_client.update_integration_auth_status(
            integration.integration_id, requires_auth=True, auth_type="oauth"
        )
        return integration, await _build_oauth_result(mcp_client, integration.integration_id)
    except Exception as e:
        return integration, {"status": "failed", "error": str(e)}


async def _get_integration(integration_id: str) -> Integration | None:
    """Fetch integration from database."""
    return await integration_repository.get(integration_id)


async def _build_oauth_result(mcp_client: MCPClient, integration_id: str) -> dict:
    """Build OAuth redirect result."""
    try:
        auth_url = await mcp_client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path="/integrations",
        )
        return {"status": "requires_oauth", "oauth_url": auth_url}
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} OAuth discovery failed",
            error=str(e),
            error_type=type(e).__name__,
            integration_id=integration_id,
        )
        return {
            "status": "failed",
            "error": f"OAuth required but discovery failed: {e}",
        }
