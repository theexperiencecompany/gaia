"""
SystemWorkflowProvisioner

Auto-creates GAIA-managed workflows when users connect integrations.
Called from handle_oauth_connection() as a background task.

These workflows are standard Workflow documents in MongoDB — identical to
user-created workflows except for is_system_workflow=True. The entire existing
execution pipeline (trigger → webhook → queue → agent) handles them with no changes.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import CreateWorkflowRequest, TriggerType
from app.services.system_workflows.definitions.calendar import CALENDAR_SYSTEM_WORKFLOWS
from app.services.system_workflows.definitions.gmail import GMAIL_SYSTEM_WORKFLOWS
from app.services.workflow.service import WorkflowService
from app.services.workflow.trigger_service import TriggerService
from app.utils.workflow_utils import ensure_trigger_config_object

# Maps integration_id -> list of (system_workflow_key, factory)
SYSTEM_WORKFLOWS_BY_INTEGRATION: dict[
    str, list[tuple[str, Callable[[], CreateWorkflowRequest]]]
] = {
    "gmail": GMAIL_SYSTEM_WORKFLOWS,
    "googlecalendar": CALENDAR_SYSTEM_WORKFLOWS,
}

# Flat registry: system_workflow_key -> factory (for reset-to-default)
SYSTEM_WORKFLOW_REGISTRY: dict[str, Callable[[], CreateWorkflowRequest]] = {
    key: factory
    for entries in SYSTEM_WORKFLOWS_BY_INTEGRATION.values()
    for key, factory in entries
}


async def provision_system_workflows(user_id: str, integration_id: str) -> None:
    """Create system workflows for a newly connected integration.

    Called as a background task from handle_oauth_connection().
    Idempotent — checks system_workflow_key to avoid duplicates on reconnect.

    Args:
        user_id: The user who connected the integration.
        integration_id: The integration that was connected (e.g. 'gmail', 'googlecalendar').
    """
    entries = SYSTEM_WORKFLOWS_BY_INTEGRATION.get(integration_id)
    if not entries:
        logger.debug(f"No system workflows defined for integration '{integration_id}'")
        return

    logger.info(
        f"Provisioning {len(entries)} system workflow(s) for user {user_id}, "
        f"integration {integration_id}"
    )

    for key, factory in entries:
        # Idempotency: skip if this key already exists for this user
        existing = await workflows_collection.find_one(
            {"user_id": user_id, "system_workflow_key": key}
        )
        if existing:
            logger.info(
                f"System workflow '{key}' already exists for user {user_id}, skipping"
            )
            continue

        try:
            await WorkflowService.create_workflow(factory(), user_id)
            logger.info(f"Provisioned system workflow '{key}' for user {user_id}")
        except Exception as e:
            logger.error(
                f"Failed to provision system workflow '{key}' for user {user_id}: {e}",
                exc_info=True,
            )


async def reset_system_workflow_to_default(workflow_id: str, user_id: str) -> bool:
    """Re-apply the original definition to a system workflow document.

    Restores: title, description, steps, trigger_config.
    Preserves: _id, user_id, activated state, execution stats, created_at.

    Returns:
        True if reset succeeded, False if workflow not found or not resettable.
    """
    existing = await workflows_collection.find_one(
        {"_id": workflow_id, "user_id": user_id, "is_system_workflow": True}
    )
    if not existing:
        return False

    key: Optional[str] = existing.get("system_workflow_key")
    factory = SYSTEM_WORKFLOW_REGISTRY.get(key) if key else None
    if not factory:
        logger.warning(
            f"No definition found for system_workflow_key '{key}' on workflow {workflow_id}"
        )
        return False

    request = factory()
    trigger_config = ensure_trigger_config_object(request.trigger_config)

    # Unregister old Composio triggers before re-registering with fresh config
    old_trigger_ids: list[str] = (
        existing.get("trigger_config", {}).get("composio_trigger_ids") or []
    )
    trigger_name: Optional[str] = existing.get("trigger_config", {}).get("trigger_name")

    if old_trigger_ids and trigger_name:
        try:
            await TriggerService.unregister_triggers(
                user_id=user_id,
                trigger_name=trigger_name,
                trigger_ids=old_trigger_ids,
                workflow_id=workflow_id,
            )
        except Exception as e:
            logger.warning(
                f"Failed to unregister old triggers during reset of {workflow_id}: {e}"
            )

    # Register fresh triggers from the definition
    new_trigger_ids: list[str] = []
    if trigger_config.type == TriggerType.INTEGRATION and trigger_config.trigger_name:
        try:
            new_trigger_ids = await TriggerService.register_triggers(
                user_id=user_id,
                workflow_id=workflow_id,
                trigger_name=trigger_config.trigger_name,
                trigger_config=trigger_config,
                raise_on_failure=False,
            )
        except Exception as e:
            logger.error(
                f"Failed to re-register triggers during reset of {workflow_id}: {e}"
            )

    trigger_doc = trigger_config.model_dump(mode="json")
    trigger_doc["composio_trigger_ids"] = new_trigger_ids

    await workflows_collection.update_one(
        {"_id": workflow_id},
        {
            "$set": {
                "title": request.title,
                "description": request.description,
                "steps": [s.model_dump() for s in (request.steps or [])],
                "trigger_config": trigger_doc,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    logger.info(
        f"Reset system workflow '{key}' ({workflow_id}) to default for user {user_id}"
    )
    return True
