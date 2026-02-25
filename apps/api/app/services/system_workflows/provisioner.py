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

from pymongo.errors import DuplicateKeyError

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.workflow_models import CreateWorkflowRequest, TriggerType
from app.services.notification_service import NotificationService
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


async def provision_system_workflows(
    user_id: str, integration_id: str, integration_display_name: str
) -> None:
    """Create system workflows for a newly connected integration.

    Called as a background task from handle_oauth_connection().
    Idempotent — checks system_workflow_key to avoid duplicates on reconnect.

    Args:
        user_id: The user who connected the integration.
        integration_id: The integration that was connected (e.g. 'gmail', 'googlecalendar').
        integration_display_name: Human-readable name for notifications (e.g. 'Gmail').
    """
    entries = SYSTEM_WORKFLOWS_BY_INTEGRATION.get(integration_id)
    if not entries:
        logger.debug(f"No system workflows defined for integration '{integration_id}'")
        return

    logger.info(
        f"Provisioning {len(entries)} system workflow(s) for user {user_id}, "
        f"integration {integration_id}"
    )

    created: list[CreateWorkflowRequest] = []

    for key, factory in entries:
        # Idempotency: skip if this key already exists for this user
        existing = await workflows_collection.find_one(
            {"user_id": user_id, "system_workflow_key": key, "is_system_workflow": True}
        )
        if existing:
            logger.info(
                f"System workflow '{key}' already exists for user {user_id}, skipping"
            )
            continue

        try:
            request = factory()
            await WorkflowService.create_workflow(request, user_id)
            created.append(request)
            logger.info(f"Provisioned system workflow '{key}' for user {user_id}")
        except DuplicateKeyError:
            logger.info(
                f"System workflow '{key}' already exists for user {user_id} "
                "(concurrent creation), skipping"
            )
        except Exception as e:
            logger.error(
                f"Failed to provision system workflow '{key}' for user {user_id}: {e}",
                exc_info=True,
            )

    if created:
        await _notify_workflows_provisioned(user_id, integration_display_name, created)


async def _notify_workflows_provisioned(
    user_id: str,
    integration_display_name: str,
    created: list[CreateWorkflowRequest],
) -> None:
    """Send a friendly notification summarising the newly provisioned workflows."""
    integration_name = integration_display_name

    if len(created) == 1:
        title = f"I set up a workflow for your {integration_name}"
    else:
        title = f"I set up {len(created)} workflows for your {integration_name}"

    workflow_lines = "\n".join(f"• {r.title} — {r.description}" for r in created)
    body = f"Here's what I've got running for you:\n\n{workflow_lines}\n\nYou can adjust or turn them off anytime."

    try:
        notification_service = NotificationService()
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.SYSTEM_WORKFLOWS_PROVISIONED,
                type=NotificationType.SUCCESS,
                priority=2,
                content=NotificationContent(
                    title=title,
                    body=body,
                    actions=[
                        NotificationAction(
                            type=ActionType.REDIRECT,
                            label="View Workflows",
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url="/workflows",
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    ],
                ),
                channels=[],
                metadata={"integration_display_name": integration_display_name},
            )
        )
        logger.info(
            f"Sent system workflow provisioning notification to user {user_id} "
            f"for integration '{integration_display_name}'"
        )
    except Exception as e:
        logger.error(
            f"Failed to send provisioning notification for user {user_id}: {e}",
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

    old_trigger_ids: list[str] = (
        existing.get("trigger_config", {}).get("composio_trigger_ids") or []
    )
    trigger_name: Optional[str] = existing.get("trigger_config", {}).get("trigger_name")

    # Register fresh triggers FIRST (old still active if this fails)
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
                f"Failed to re-register triggers, aborting reset of {workflow_id}: {e}"
            )
            return False

        if not new_trigger_ids:
            logger.error(
                f"New trigger registration returned empty result for {workflow_id}, "
                "aborting reset to avoid leaving workflow without triggers"
            )
            return False

    # Only unregister old triggers AFTER new ones are confirmed registered
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
                f"Failed to unregister old triggers during reset of {workflow_id} (non-fatal): {e}"
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
