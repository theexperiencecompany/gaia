"""
SystemWorkflowProvisioner.

Auto-creates GAIA-managed workflows when users connect integrations.
Called from handle_oauth_connection() as a background task.

These workflows are standard Workflow documents in MongoDB — identical to
user-created workflows except for is_system_workflow=True. The entire existing
execution pipeline (trigger → webhook → queue → agent) handles them with no changes.
"""

from collections.abc import Callable

from pymongo.errors import DuplicateKeyError

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.decorators.entitlements import is_paid
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
from app.models.workflow_models import (
    CreateWorkflowRequest,
    SystemWorkflowDefinition,
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
)
from app.services.briefing.schedule import daily_briefing_cron
from app.services.notification_service import NotificationService
from app.services.system_workflows.definitions import SYSTEM_WORKFLOWS_BY_INTEGRATION
from app.services.system_workflows.definitions.briefing import BRIEFING_SYSTEM_WORKFLOWS
from app.services.user_service import get_profile_timezone
from app.services.workflow.scheduler import workflow_scheduler
from app.services.workflow.service import WorkflowService
from app.services.workflow.trigger_service import TriggerService
from app.utils.workflow_utils import ensure_trigger_config_object
from shared.py.wide_events import log

WorkflowEntries = list[tuple[str, Callable[[], CreateWorkflowRequest]]]

# Flat registry: system_workflow_key -> factory (for reset-to-default). Includes
# the integration-triggered workflows plus the always-provisioned briefings.
SYSTEM_WORKFLOW_REGISTRY: dict[str, Callable[[], CreateWorkflowRequest]] = {
    key: factory
    for entries in (*SYSTEM_WORKFLOWS_BY_INTEGRATION.values(), BRIEFING_SYSTEM_WORKFLOWS)
    for key, factory in entries
}


async def provision_system_workflows(
    user_id: str,
    integration_id: str,
    integration_display_name: str,
    notify: bool = True,
) -> None:
    """Create system workflows for a newly connected integration.

    Called as a background task from handle_oauth_connection().
    Idempotent: checks system_workflow_key to avoid duplicates on reconnect.
    notify is set False during onboarding so provisioning is silent (the
    onboarding UI surfaces the workflows itself).
    """
    log.set(
        component="system_workflow_provisioner",
        operation="provision_system_workflows",
        user_id=user_id,
        integration_id=integration_id,
        integration_display_name=integration_display_name,
    )
    entries = SYSTEM_WORKFLOWS_BY_INTEGRATION.get(integration_id)
    if not entries:
        log.debug(
            f"{LogTag.WORKFLOW} No system workflows defined for integration",
            integration_id=integration_id,
        )
        return

    log.info(
        f"{LogTag.WORKFLOW} Provisioning system workflow(s)",
        entries_count=len(entries),
        user_id=user_id,
        integration_id=integration_id,
    )

    created = await _provision_entries(user_id, entries, integration_display_name)

    if created and notify:
        await _notify_workflows_provisioned(user_id, integration_display_name, created)


async def _provision_entries(
    user_id: str, entries: WorkflowEntries, integration_display_name: str | None = None
) -> list[CreateWorkflowRequest]:
    """Create each (key, factory) workflow for the user, idempotent by key.

    Fits scheduled definitions to the user (factories can't know them), skips
    keys that already exist, and switches each new one on for a paying user.
    Returns the requests actually created.
    """
    created: list[CreateWorkflowRequest] = []

    for key, factory in entries:
        # Idempotency: skip if this key already exists for this user
        existing = await workflow_repository.find_system_workflow(user_id, key)
        if existing:
            log.info(
                f"{LogTag.WORKFLOW} System workflow already exists, skipping",
                key=key,
                user_id=user_id,
            )
            continue

        try:
            request = factory()
            trigger_config = ensure_trigger_config_object(request.trigger_config)
            await _stamp_user_schedule(key, trigger_config, user_id)
            request.trigger_config = trigger_config
            workflow = await WorkflowService.create_workflow(request, user_id)
            created.append(request)
            log.info(
                f"{LogTag.WORKFLOW} Provisioned system workflow for user", key=key, user_id=user_id
            )
            await _activate_for_paying_user(workflow.id, user_id, key)
        except DuplicateKeyError:
            log.info(
                f"{LogTag.WORKFLOW} System workflow already exists for user (concurrent creation), skipping",
                key=key,
                user_id=user_id,
            )
        except Exception as e:
            log.error(
                "system_workflow_provision_failed",
                system_workflow_key=key,
                user_id=user_id,
                integration_display_name=integration_display_name,
                error_type=type(e).__name__,
                error=str(e)[:500],
                outcome="failed",
                exc_info=True,
            )

    return created


async def _activate_for_paying_user(workflow_id: str, user_id: str, key: str) -> None:
    """Switch a freshly provisioned system workflow on for a Pro user.

    Free users keep it dormant instead (the paid-only gate would refuse to
    run it anyway); an activation failure is logged but never blocks the
    rest of provisioning.
    """
    if not await is_paid(user_id):
        log.info(
            f"{LogTag.WORKFLOW} System workflow left dormant for user without a plan",
            key=key,
            user_id=user_id,
        )
        return
    try:
        await WorkflowService.activate_workflow(workflow_id, user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} Could not activate provisioned system workflow",
            key=key,
            workflow_id=workflow_id,
            user_id=user_id,
            error=str(e)[:500],
            error_type=type(e).__name__,
        )
        return
    log.info(
        f"{LogTag.WORKFLOW} Activated provisioned system workflow for paying user",
        key=key,
        workflow_id=workflow_id,
        user_id=user_id,
    )


async def provision_briefing_workflows(user_id: str) -> list[CreateWorkflowRequest]:
    """Provision the daily-brief and weekly-recap system workflows for a user.

    Called at onboarding completion and by the existing-user backfill. Idempotent
    by system_workflow_key. The announcement is the caller's responsibility
    (app/services/briefing/rollout.py); this only wires the schedules.
    """
    log.set(
        component="system_workflow_provisioner",
        operation="provision_briefing_workflows",
        user_id=user_id,
    )
    return await _provision_entries(user_id, BRIEFING_SYSTEM_WORKFLOWS)


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

    workflow_lines = "\n".join(f"• {r.title}: {r.description}" for r in created)
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
                metadata={"integration_display_name": integration_display_name},
            )
        )
        log.info(
            f"{LogTag.WORKFLOW} Sent system workflow provisioning notification to user for integration",
            user_id=user_id,
            integration_display_name=integration_display_name,
        )
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Failed to send provisioning notification for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )


async def _stamp_user_schedule(key: str, trigger_config: TriggerConfig, user_id: str) -> None:
    """Fit a schedule definition to its user, then recompute next_run.

    Factories can't know the user, so scheduled definitions carry no timezone:
    the profile timezone is stamped so the cron fires on the user's clock. The
    daily brief also takes the hour the user's quiet hours leave it.
    """
    if trigger_config.type != TriggerType.SCHEDULE:
        return
    if not trigger_config.timezone:
        trigger_config.timezone = (await get_profile_timezone(user_id)).value
    if key == DAILY_BRIEFING_WORKFLOW_KEY:
        user = await user_repository.get(user_id)
        if user is None:
            raise LookupError(f"Cannot schedule the daily brief for unknown user {user_id}")
        trigger_config.cron_expression = daily_briefing_cron(user.quiet_hours)
    if trigger_config.cron_expression:
        trigger_config.update_next_run(user_timezone=trigger_config.timezone)


async def _reregister_triggers_for_reset(
    trigger_config: TriggerConfig, workflow_id: str, user_id: str
) -> list[str] | None:
    """Register fresh triggers for a reset. Registers old still active if this fails.

    Returns the new trigger ids, [] when no re-registration is needed, or None
    when registration failed and the caller must abort the reset.
    """
    if trigger_config.type != TriggerType.INTEGRATION or not trigger_config.trigger_name:
        return []
    try:
        new_trigger_ids = await TriggerService.register_triggers(
            user_id=user_id,
            owner_id=workflow_id,
            trigger_name=trigger_config.trigger_name,
            trigger_config=trigger_config,
            raise_on_failure=False,
        )
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Failed to re-register triggers, aborting reset of",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None

    if not new_trigger_ids:
        log.error(
            f"{LogTag.WORKFLOW} New trigger registration returned an empty result, aborting reset to avoid leaving the workflow without triggers",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        return None
    return new_trigger_ids


async def _unregister_old_triggers_for_reset(
    old_trigger_ids: list[str], trigger_name: str | None, workflow_id: str, user_id: str
) -> None:
    """Unregister the pre-reset triggers. Non-fatal: only called after new ones are confirmed."""
    if not (old_trigger_ids and trigger_name):
        return
    try:
        await TriggerService.unregister_triggers(
            user_id=user_id,
            trigger_name=trigger_name,
            trigger_ids=old_trigger_ids,
            workflow_id=workflow_id,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} Failed to unregister old triggers during reset of (non-fatal)",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


async def _rearm_reset_schedule(
    existing: WorkflowDocument, trigger_config: TriggerConfig, workflow_id: str, user_id: str
) -> bool:
    """Re-arm the schedule after a reset; return False only if arming was required and failed."""
    if not (
        existing.activated
        and trigger_config.type == TriggerType.SCHEDULE
        and trigger_config.next_run
    ):
        return True
    armed = await workflow_scheduler.schedule_workflow_execution(
        workflow_id,
        trigger_config.next_run,
        repeat=trigger_config.cron_expression,
    )
    if not armed:
        log.error(
            f"{LogTag.WORKFLOW} Reset applied but re-arming the schedule failed",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        return False
    return True


async def reset_system_workflow_to_default(workflow_id: str, user_id: str) -> bool:
    """Re-apply the original definition to a system workflow document.

    Restores title, description, prompt, steps, trigger_config; preserves
    _id, user_id, activated state, execution stats, created_at. Schedule
    triggers get the profile timezone stamped and next_run recomputed, and
    an activated workflow is re-armed with a queued fire.
    """
    log.set(
        component="system_workflow_provisioner",
        operation="reset_system_workflow_to_default",
        user_id=user_id,
        workflow_id=workflow_id,
    )
    existing = await workflow_repository.get_system_workflow_for_user(workflow_id, user_id)
    if not existing:
        return False

    key: str | None = existing.system_workflow_key
    factory = SYSTEM_WORKFLOW_REGISTRY.get(key) if key else None
    if not factory:
        log.warning(
            f"{LogTag.WORKFLOW} No definition found for system_workflow_key on workflow",
            key=key,
            workflow_id=workflow_id,
            user_id=user_id,
        )
        return False

    request = factory()
    trigger_config = ensure_trigger_config_object(request.trigger_config)

    await _stamp_user_schedule(key, trigger_config, user_id)

    old_trigger_ids: list[str] = existing.trigger_config.composio_trigger_ids or []
    trigger_name: str | None = existing.trigger_config.trigger_name

    # Register fresh triggers FIRST (old still active if this fails)
    new_trigger_ids = await _reregister_triggers_for_reset(trigger_config, workflow_id, user_id)
    if new_trigger_ids is None:
        return False

    # Only unregister old triggers AFTER new ones are confirmed registered
    await _unregister_old_triggers_for_reset(old_trigger_ids, trigger_name, workflow_id, user_id)

    await workflow_repository.reset_system_workflow(
        workflow_id,
        SystemWorkflowDefinition(
            title=request.title,
            description=request.description or "",
            prompt=request.prompt,
            steps=request.steps or [],
            trigger_config=trigger_config,
            composio_trigger_ids=new_trigger_ids,
        ),
    )

    # A failed re-arm must fail the reset: reporting success would leave a
    # workflow that looks reset but never fires (retrying re-arms it).
    if not await _rearm_reset_schedule(existing, trigger_config, workflow_id, user_id):
        return False

    log.info(
        f"{LogTag.WORKFLOW} Reset system workflow to default for user",
        key=key,
        workflow_id=workflow_id,
        user_id=user_id,
    )
    return True
