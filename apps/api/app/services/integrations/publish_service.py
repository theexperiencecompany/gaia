"""Publish/unpublish service for community marketplace."""

from datetime import datetime, timezone

from app.config.loggers import app_logger as logger
from app.db.chroma.public_integrations_store import (
    index_public_integration,
    remove_public_integration,
)
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.db.redis import delete_cache_by_pattern
from app.services.integrations.category_inference_service import (
    infer_integration_category,
)
from app.services.integrations.publish_validator import PublishIntegrationValidator


class PublishError(Exception):
    """Raised when publish/unpublish fails with a user-facing message."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def publish_custom_integration(
    integration_id: str,
    user_id: str,
) -> dict:
    """Publish a custom integration to the community marketplace.

    Returns dict with integration_id and public_url on success.
    Raises PublishError on failure.
    """
    integration = await integrations_collection.find_one(
        {"integration_id": integration_id}
    )
    if not integration:
        raise PublishError("Integration not found", 404)

    if integration.get("created_by") != user_id:
        raise PublishError("You can only publish integrations you created", 403)

    if integration.get("source") != "custom":
        raise PublishError("Only custom integrations can be published")

    user_integration = await user_integrations_collection.find_one(
        {"user_id": user_id, "integration_id": integration_id}
    )
    if not user_integration or user_integration.get("status") != "connected":
        raise PublishError("Integration must be connected before publishing")

    tools = integration.get("tools", [])
    if not tools:
        raise PublishError("Integration must be connected with tools before publishing")

    validation_errors = PublishIntegrationValidator.validate_for_publish(
        name=integration.get("name", ""),
        description=integration.get("description"),
        tools=tools,
    )
    if validation_errors:
        raise PublishError("; ".join(validation_errors))

    category = await infer_integration_category(
        name=integration.get("name", ""),
        description=integration.get("description", ""),
        tools=tools,
        server_url=integration.get("mcp_config", {}).get("server_url", ""),
    )

    now = datetime.now(timezone.utc)
    update_result = await integrations_collection.update_one(
        {
            "integration_id": integration_id,
            "created_by": user_id,
            "source": "custom",
            "is_public": {"$ne": True},
        },
        {
            "$set": {
                "is_public": True,
                "published_at": now,
                "category": category,
                "clone_count": integration.get("clone_count", 0),
            }
        },
    )

    if update_result.modified_count == 0:
        existing = await integrations_collection.find_one(
            {"integration_id": integration_id, "created_by": user_id}
        )
        if existing and existing.get("is_public"):
            raise PublishError("Integration is already published")
        raise PublishError("Integration not found", 404)

    await index_public_integration(
        integration_id=integration_id,
        name=integration.get("name", ""),
        description=integration.get("description", ""),
        category=category,
        created_by=user_id,
        clone_count=integration.get("clone_count", 0),
        published_at=now.isoformat(),
        tool_count=len(tools),
        tools=tools,
    )

    await delete_cache_by_pattern("marketplace:community:*")
    logger.info(f"Published integration {integration_id}")

    return {
        "integration_id": integration_id,
        "public_url": f"/marketplace/{integration_id}",
    }


async def unpublish_custom_integration(
    integration_id: str,
    user_id: str,
) -> dict:
    """Unpublish a custom integration from the community marketplace.

    Returns dict with integration_id on success.
    Raises PublishError on failure.
    """
    integration = await integrations_collection.find_one(
        {"integration_id": integration_id}
    )
    if not integration:
        raise PublishError("Integration not found", 404)

    if integration.get("created_by") != user_id:
        raise PublishError("You can only unpublish integrations you created", 403)

    if not integration.get("is_public"):
        raise PublishError("Integration is not currently published")

    update_result = await integrations_collection.update_one(
        {"integration_id": integration_id},
        {
            "$set": {"is_public": False},
            "$unset": {"published_at": ""},
        },
    )

    if update_result.modified_count == 0:
        raise PublishError("Failed to update integration", 500)

    await remove_public_integration(integration_id)
    await delete_cache_by_pattern("marketplace:community:*")
    logger.info(f"Unpublished integration {integration_id}")

    return {"integration_id": integration_id}
