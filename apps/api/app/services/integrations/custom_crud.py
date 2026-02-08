"""Custom integration CRUD operations."""

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional, Tuple

from mcp_use.client.exceptions import OAuthAuthenticationError

from app.config.loggers import app_logger as logger
from app.db.chroma.chroma_cleanup import cleanup_integration_chroma_data
from app.db.chroma.public_integrations_store import remove_public_integration
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache, delete_cache_by_pattern
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
from app.services.integrations.user_integrations import add_user_integration
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.utils.favicon_utils import fetch_favicon_from_url
from sqlalchemy import delete


async def create_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    icon_url: str | None = None,
) -> Integration:
    """Create a custom MCP integration."""
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
        logger.error(f"Failed to add user_integration, rolling back: {e}")
        await integrations_collection.delete_one({"integration_id": integration_id})
        raise

    return integration


async def update_custom_integration(
    user_id: str,
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
) -> Optional[Integration]:
    """Update a custom integration (creator only)."""
    doc = await integrations_collection.find_one(
        {
            "integration_id": integration_id,
            "source": "custom",
            "created_by": user_id,
        }
    )

    if not doc:
        return None

    update_data: Dict[str, Any] = {}
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
                    await cleanup_integration_chroma_data(
                        integration_id, old_server_url
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to clean old namespace for {integration_id}: {e}"
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

    updated_doc = await integrations_collection.find_one(
        {"integration_id": integration_id}
    )
    return Integration(**updated_doc) if updated_doc else None


async def delete_custom_integration(user_id: str, integration_id: str) -> bool:
    """Delete or remove a custom integration based on ownership."""
    doc = await integrations_collection.find_one(
        {"integration_id": integration_id, "source": "custom"}
    )

    if not doc:
        user_int = await user_integrations_collection.find_one(
            {"user_id": user_id, "integration_id": integration_id}
        )
        if user_int:
            await user_integrations_collection.delete_one(
                {"user_id": user_id, "integration_id": integration_id}
            )
            await delete_cache_by_pattern(f"tools:user:{user_id}:*")
            return True
        return False

    is_creator = doc.get("created_by") == user_id

    if is_creator:
        if doc.get("is_public"):
            try:
                await remove_public_integration(integration_id)
            except Exception as e:
                logger.warning(f"Failed to remove from public integrations: {e}")

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

            await user_integrations_collection.delete_many(
                {"integration_id": integration_id}
            )

            for affected_user_id in affected_user_ids:
                try:
                    await delete_cache_by_pattern(f"tools:user:{affected_user_id}:*")
                except Exception as e:
                    logger.debug(
                        f"Cache deletion failed for user {affected_user_id}: {e}"
                    )

            try:
                async with get_db_session() as session:
                    await session.execute(
                        delete(MCPCredential).where(
                            MCPCredential.integration_id == integration_id
                        )
                    )
                    await session.commit()
            except Exception as e:
                logger.warning(f"Failed to delete MCP credentials: {e}")

            try:
                await delete_cache("mcp:tools:all")
            except Exception as e:
                logger.debug(f"Cache deletion for mcp:tools:all failed: {e}")

            try:
                mcp_config = doc.get("mcp_config", {})
                server_url = mcp_config.get("server_url", "")
                await cleanup_integration_chroma_data(integration_id, server_url)
            except Exception as e:
                logger.debug(f"Chroma store deletion failed for {integration_id}: {e}")

            return True
        return False
    else:
        result = await user_integrations_collection.delete_one(
            {"user_id": user_id, "integration_id": integration_id}
        )

        if result.deleted_count > 0:
            await delete_cache_by_pattern(f"tools:user:{user_id}:*")

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
                logger.debug(
                    f"MCP credential deletion failed for {integration_id}: {e}"
                )

            return True
        return False


async def create_and_connect_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    mcp_client: Any,
) -> Tuple[Integration, dict]:
    """Create a custom integration and attempt connection."""
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


async def _fetch_icon_safely(server_url: str) -> Optional[str]:
    """Fetch favicon with error handling."""
    try:
        return await fetch_favicon_from_url(server_url)
    except Exception:
        return None


async def _probe_connection_safely(mcp_client: Any, server_url: str) -> Dict[str, Any]:
    """Probe connection with error handling."""
    try:
        return await mcp_client.probe_connection(server_url)
    except Exception as e:
        return {"error": str(e)}


async def _connect_with_bearer_token(
    user_id: str, integration_id: str, bearer_token: str, mcp_client: Any
) -> Tuple[Any, dict]:
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
) -> Tuple[Integration, dict]:
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
        return integration, await _build_oauth_result(
            mcp_client, integration.integration_id
        )
    except Exception as e:
        return integration, {"status": "failed", "error": str(e)}


async def _get_integration(integration_id: str) -> Optional[Integration]:
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
        logger.error(f"OAuth discovery failed: {e}")
        return {
            "status": "failed",
            "error": f"OAuth required but discovery failed: {e}",
        }
