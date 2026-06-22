"""Custom integration CRUD operations."""

from datetime import UTC, datetime
from typing import Any
import uuid

from mcp_use.client.exceptions import OAuthAuthenticationError
from sqlalchemy import delete

from app.constants.log_tags import LogTag
from app.db.chroma.chroma_cleanup import cleanup_integration_chroma_data
from app.db.chroma.public_integrations_store import remove_public_integration
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.models.db_oauth import MCPCredential
from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
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
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.utils.favicon_utils import fetch_favicon_from_url
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

    await integrations_collection.insert_one(integration.model_dump())

    try:
        await add_user_integration(user_id, integration_id, initial_status="created")
    except Exception as e:
        log.error(f"{LogTag.INTEGRATION} Failed to add user_integration, rolling back: {e}")
        await integrations_collection.delete_one({"integration_id": integration_id})
        raise

    return integration


async def update_custom_integration(
    user_id: str,
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
) -> Integration | None:
    """Update a custom integration (creator only)."""
    log.set(integration={"provider": integration_id, "action": "update_custom_integration"})
    doc = await integrations_collection.find_one(
        {
            "integration_id": integration_id,
            "source": "custom",
            "created_by": user_id,
        }
    )

    if not doc:
        return None

    update_data: dict[str, Any] = {}
    if request.name is not None:
        update_data["name"] = request.name
    if request.description is not None:
        update_data["description"] = request.description
    if request.is_public is not None:
        update_data["is_public"] = request.is_public

    if any([request.server_url, request.requires_auth, request.auth_type]):
        current_config = doc.get("mcp_config", {})
        if request.server_url is not None:
            old_server_url = current_config.get("server_url", "")
            current_config["server_url"] = request.server_url

            # Clean up old ChromaDB namespace when server_url changes
            if old_server_url and old_server_url != request.server_url:
                try:
                    await cleanup_integration_chroma_data(integration_id, old_server_url)
                except Exception as e:
                    log.warning(
                        f"{LogTag.INTEGRATION} Failed to clean old namespace for {integration_id}: {e}"
                    )

        if request.requires_auth is not None:
            current_config["requires_auth"] = request.requires_auth
        if request.auth_type is not None:
            current_config["auth_type"] = request.auth_type
        update_data["mcp_config"] = current_config

    update_data["updated_at"] = datetime.now(UTC)

    await integrations_collection.update_one(
        {"integration_id": integration_id},
        {"$set": update_data},
    )

    # A name/description change makes every connected user's cached connected list
    # (which embeds the display name) stale. Bust them so the rename shows on the
    # next turn instead of lingering for the 24h cache TTL.
    if "name" in update_data or "description" in update_data:
        async for ui in user_integrations_collection.find(
            {"integration_id": integration_id}, {"user_id": 1}
        ):
            await invalidate_user_integration_caches(ui["user_id"])

    updated_doc = await integrations_collection.find_one({"integration_id": integration_id})
    return Integration(**updated_doc) if updated_doc else None


async def delete_custom_integration(user_id: str, integration_id: str) -> bool:
    """Delete or remove a custom integration based on ownership."""
    log.set(integration={"provider": integration_id, "action": "delete_custom_integration"})
    doc = await integrations_collection.find_one(
        {"integration_id": integration_id, "source": "custom"}
    )

    if not doc:
        # No catalog row — just drop this user's link. The mutator deletes the
        # row and invalidates atomically, returning False if there was nothing.
        return await remove_user_integration(user_id, integration_id)

    is_creator = doc.get("created_by") == user_id

    if is_creator:
        if doc.get("is_public"):
            try:
                await remove_public_integration(integration_id)
            except Exception as e:
                log.warning(f"{LogTag.INTEGRATION} Failed to remove from public integrations: {e}")

        result = await integrations_collection.delete_one(
            {
                "integration_id": integration_id,
                "source": "custom",
                "created_by": user_id,
            }
        )

        if result.deleted_count > 0:
            affected_users_cursor = user_integrations_collection.find(
                {"integration_id": integration_id}, {"user_id": 1}
            )
            affected_user_ids = [d["user_id"] async for d in affected_users_cursor]

            # Remove each user's link through the canonical mutator so the row
            # delete and its cache invalidation stay coupled per user.
            for affected_user_id in affected_user_ids:
                try:
                    await remove_user_integration(affected_user_id, integration_id)
                except Exception as e:
                    log.debug(
                        f"{LogTag.INTEGRATION} Failed to remove integration for user {affected_user_id}: {e}"
                    )

            try:
                async with get_db_session() as session:
                    await session.execute(
                        delete(MCPCredential).where(MCPCredential.integration_id == integration_id)
                    )
                    await session.commit()
            except Exception as e:
                log.warning(f"{LogTag.INTEGRATION} Failed to delete MCP credentials: {e}")

            try:
                await delete_cache("mcp:tools:all")
            except Exception as e:
                log.debug(f"{LogTag.INTEGRATION} Cache deletion for mcp:tools:all failed: {e}")

            try:
                mcp_config = doc.get("mcp_config", {})
                server_url = mcp_config.get("server_url", "")
                await cleanup_integration_chroma_data(integration_id, server_url)
            except Exception as e:
                log.debug(
                    f"{LogTag.INTEGRATION} Chroma store deletion failed for {integration_id}: {e}"
                )

            return True
        return False
    if await remove_user_integration(user_id, integration_id):
        try:
            async with get_db_session() as session:
                await session.execute(
                    delete(MCPCredential).where(
                        MCPCredential.integration_id == integration_id,
                        MCPCredential.user_id == user_id,
                    )
                )
                await session.commit()
        except Exception as e:
            log.debug(
                f"{LogTag.INTEGRATION} MCP credential deletion failed for {integration_id}: {e}"
            )

        return True
    return False


async def create_and_connect_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    mcp_client: Any,
) -> tuple[Integration, dict]:
    """Create a custom integration and attempt connection."""
    log.set(
        integration={
            "provider": request.name,
            "action": "create_and_connect_custom_integration",
        }
    )
    icon_url = await _fetch_icon_safely(request.server_url)
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


async def _fetch_icon_safely(server_url: str) -> str | None:
    """Fetch favicon with error handling."""
    try:
        return await fetch_favicon_from_url(server_url)
    except Exception:
        return None


async def _probe_connection_safely(mcp_client: Any, server_url: str) -> dict[str, Any]:
    """Probe connection with error handling."""
    try:
        return await mcp_client.probe_connection(server_url)
    except Exception as e:
        return {"error": str(e)}


async def _connect_with_bearer_token(
    user_id: str, integration_id: str, bearer_token: str, mcp_client: Any
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
    integration: Integration, mcp_client: Any
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
    doc = await integrations_collection.find_one({"integration_id": integration_id})
    return Integration(**doc) if doc else None


async def _build_oauth_result(mcp_client: Any, integration_id: str) -> dict:
    """Build OAuth redirect result."""
    try:
        auth_url = await mcp_client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path="/integrations",
        )
        return {"status": "requires_oauth", "oauth_url": auth_url}
    except Exception as e:
        log.error(f"{LogTag.INTEGRATION} OAuth discovery failed: {e}")
        return {
            "status": "failed",
            "error": f"OAuth required but discovery failed: {e}",
        }
