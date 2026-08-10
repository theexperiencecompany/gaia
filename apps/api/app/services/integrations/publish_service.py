"""Publish/unpublish service for community marketplace."""

from app.constants.log_tags import LogTag
from app.db.chroma.public_integrations_store import (
    index_public_integration,
    remove_public_integration,
)
from app.db.redis import delete_cache_by_pattern
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.services.integrations.integration_inference_service import (
    infer_integration_category,
    infer_integration_content,
)
from app.services.integrations.publish_validator import PublishIntegrationValidator
from app.services.integrations.user_integrations import invalidate_user_integration_caches
from shared.py.wide_events import log


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
    log.set(integration={"provider": integration_id, "action": "publish"})
    integration = await integration_repository.get(integration_id)
    if not integration:
        raise PublishError("Integration not found", 404)

    if integration.created_by != user_id:
        raise PublishError("You can only publish integrations you created", 403)

    if integration.source != "custom":
        raise PublishError("Only custom integrations can be published")

    if not await user_integration_repository.is_connected(user_id, integration_id):
        raise PublishError("Integration must be connected before publishing")

    tools = [t.model_dump() for t in integration.tools]
    if not tools:
        raise PublishError("Integration must be connected with tools before publishing")

    server_url = integration.mcp_config.server_url if integration.mcp_config else ""

    validation_errors = await PublishIntegrationValidator.validate_for_publish(
        name=integration.name,
        description=integration.description,
        tools=tools,
    )
    if validation_errors:
        raise PublishError("; ".join(validation_errors))

    category = await infer_integration_category(
        name=integration.name,
        description=integration.description,
        tools=tools,
        server_url=server_url,
    )

    content = await infer_integration_content(
        user_id=user_id,
        name=integration.name,
        description=integration.description,
        tools=tools,
        server_url=server_url,
        category=category,
    )

    slug = await integration_repository.ensure_unique_slug(
        name=integration.name,
        category=category,
        integration_id=integration_id,
    )

    published = await integration_repository.publish(
        integration_id,
        created_by=user_id,
        category=category,
        slug=slug,
        content=content,
        clone_count=integration.clone_count,
    )

    if not published:
        existing = await integration_repository.get_by_creator(integration_id, user_id)
        if existing and existing.is_public:
            raise PublishError("Integration is already published")
        raise PublishError("Integration not found", 404)

    await index_public_integration(
        integration_id=integration_id,
        name=integration.name,
        description=integration.description,
        tools=tools,
    )

    await delete_cache_by_pattern("marketplace:community:*")
    # is_public / published_at feed the creator's MyIntegrationItem (tools:user:*:my).
    await invalidate_user_integration_caches(user_id)
    log.info(f"{LogTag.INTEGRATION} Published integration", integration_id=integration_id)

    return {
        "integration_id": integration_id,
        "public_url": f"/marketplace/{slug}",
    }


async def unpublish_custom_integration(
    integration_id: str,
    user_id: str,
) -> dict:
    """Unpublish a custom integration from the community marketplace.

    Returns dict with integration_id on success.
    Raises PublishError on failure.
    """
    log.set(integration={"provider": integration_id, "action": "unpublish"})
    integration = await integration_repository.get(integration_id)
    if not integration:
        raise PublishError("Integration not found", 404)

    if integration.created_by != user_id:
        raise PublishError("You can only unpublish integrations you created", 403)

    if not integration.is_public:
        raise PublishError("Integration is not currently published")

    if not await integration_repository.unpublish(integration_id):
        raise PublishError("Failed to update integration", 500)

    await remove_public_integration(integration_id)
    await delete_cache_by_pattern("marketplace:community:*")
    await invalidate_user_integration_caches(user_id)
    log.info(f"{LogTag.INTEGRATION} Unpublished integration", integration_id=integration_id)

    return {"integration_id": integration_id}
