"""Custom integration CRUD operations."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional, Tuple

from mcp_use.client.exceptions import OAuthAuthenticationError

from app.config.loggers import app_logger as logger
from app.core.lazy_loader import providers
from app.db.chroma.public_integrations_store import remove_public_integration
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache, delete_cache_by_pattern
from app.helpers.mcp_helpers import get_api_base_url
from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
    UpdateCustomIntegrationRequest,
)
from app.models.db_oauth import MCPCredential
from app.models.mcp_config import MCPConfig
from app.services.integrations.user_integrations import add_user_integration
from app.utils.favicon_utils import fetch_favicon_from_url
from sqlalchemy import delete


async def create_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    icon_url: str | None = None,
) -> Integration:
    """Create a custom MCP integration."""
    integration_id = str(uuid.uuid4())

    orphaned = await user_integrations_collection.find_one(
        {"integration_id": integration_id, "user_id": user_id}
    )
    if orphaned:
        await user_integrations_collection.delete_one(
            {"integration_id": integration_id, "user_id": user_id}
        )
        await delete_cache_by_pattern(f"tools:user:{user_id}:*")

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
            current_config["server_url"] = request.server_url
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
                store = await providers.aget("chroma_tools_store")
                if store:
                    await store.adelete(namespace=("subagents",), key=integration_id)
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
    """Create a custom integration and attempt connection.

    Returns tuple of (integration, connection_result) where connection_result is:
    {"status": "connected", "tools_count": N} or
    {"status": "requires_oauth", "oauth_url": "..."} or
    {"status": "failed", "error": "..."}
    """
    # Parallel: Favicon fetch + MCP probe
    results = await asyncio.gather(
        fetch_favicon_from_url(request.server_url),
        mcp_client.probe_connection(request.server_url),
        return_exceptions=True,
    )
    favicon_result: str | BaseException | None = results[0]
    probe_result: Dict[str, Any] | BaseException = results[1]

    icon_url: str | None = None
    if favicon_result and not isinstance(favicon_result, BaseException):
        icon_url = favicon_result

    integration = await create_custom_integration(user_id, request, icon_url)

    # Determine connection result based on probe
    if isinstance(probe_result, BaseException):
        return integration, {"status": "failed", "error": str(probe_result)}

    if probe_result.get("error"):
        return integration, {"status": "failed", "error": probe_result["error"]}

    if probe_result.get("requires_auth"):
        await mcp_client.update_integration_auth_status(
            integration.integration_id,
            requires_auth=True,
            auth_type=probe_result.get("auth_type", "oauth"),
        )
        return integration, await _build_oauth_result(
            mcp_client, integration.integration_id
        )

    # No auth required - try to connect
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
