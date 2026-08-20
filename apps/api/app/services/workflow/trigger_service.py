"""
Generic trigger management service for workflow automation.

Provides high-level trigger operations that delegate to provider-specific handlers.
Handles Composio trigger reference counting to prevent premature deletion.
"""

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.trigger_config import WorkflowTriggerResponse
from app.models.workflow_models import TriggerConfig
from app.services.triggers import get_handler_by_name
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import log


class TriggerService:
    """Generic service for managing workflow triggers.

    Delegates to provider-specific handlers for actual registration/unregistration.
    Handles reference counting for shared Composio triggers.
    """

    @staticmethod
    async def get_all_workflow_triggers() -> list[WorkflowTriggerResponse]:
        """
        Get all available workflow triggers from OAuth integrations.

        Returns a list of trigger schemas for frontend configuration UI.
        """
        triggers = []

        for integration in OAUTH_INTEGRATIONS:
            for trigger_config in integration.associated_triggers:
                if trigger_config.workflow_trigger_schema:
                    schema = trigger_config.workflow_trigger_schema
                    triggers.append(
                        WorkflowTriggerResponse(
                            slug=schema.slug,
                            composio_slug=schema.composio_slug,
                            name=schema.name,
                            description=schema.description,
                            provider=integration.provider,
                            integration_id=integration.id,
                            config_schema=schema.config_schema,
                        )
                    )

        return triggers

    @staticmethod
    async def get_triggers_safe_to_delete(
        trigger_ids: list[str], excluding_workflow_id: str | None = None
    ) -> list[str]:
        """Filter trigger IDs to those safe to delete from Composio.

        A trigger is safe to delete if no other workflows reference it.
        ``excluding_workflow_id`` is excluded from the reference count (used
        during workflow deletion/update).
        """
        safe_to_delete = []

        for trigger_id in trigger_ids:
            try:
                count = await workflow_repository.count_trigger_references(
                    trigger_id, excluding_workflow_id=excluding_workflow_id
                )

                if count == 0:
                    safe_to_delete.append(trigger_id)
                else:
                    log.debug(
                        f"{LogTag.WORKFLOW} Trigger still referenced by other workflow(s), skipping deletion",
                        trigger_id=trigger_id,
                        count=count,
                    )
            except Exception as e:
                log.error(
                    f"{LogTag.WORKFLOW} Error checking trigger references for",
                    trigger_id=trigger_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Don't delete if we can't verify - safer to leave orphaned triggers
                continue

        return safe_to_delete

    @staticmethod
    async def register_triggers(
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
        raise_on_failure: bool = False,
    ) -> list[str]:
        """Register triggers for a workflow using the appropriate handler.

        Returns the registered Composio trigger IDs (may be empty on success, e.g.
        account-level Gmail has no per-workflow IDs). With ``raise_on_failure``,
        raises TriggerRegistrationError when the handler is missing or raises.
        """
        handler = get_handler_by_name(trigger_name)
        if not handler:
            error_msg = f"No handler found for trigger: {trigger_name}"
            log.error(f"{LogTag.WORKFLOW} No handler found for trigger", trigger_name=trigger_name)
            if raise_on_failure:
                raise TriggerRegistrationError(error_msg, trigger_name)
            return []

        try:
            # Pass TriggerConfig directly - handlers validate trigger_data type
            trigger_ids = await handler.register(user_id, workflow_id, trigger_name, trigger_config)
            return trigger_ids
        except TypeError as e:
            # Re-raise TypeError for type validation failures
            log.error(
                f"{LogTag.WORKFLOW} Type validation error registering triggers",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                workflow_id=workflow_id,
            )
            raise
        except TriggerRegistrationError:
            # Re-raise our custom exception
            raise
        except Exception as e:
            error_msg = f"Error registering triggers: {type(e).__name__}: {e!s}"
            log.error(f"{LogTag.WORKFLOW} Error registering triggers", error_type=type(e).__name__)
            log.exception(f"{LogTag.WORKFLOW} Full traceback")
            if raise_on_failure:
                raise TriggerRegistrationError(error_msg, trigger_name) from e
            return []

    @staticmethod
    async def unregister_triggers(
        user_id: str,
        trigger_name: str,
        trigger_ids: list[str],
        workflow_id: str | None = None,
    ) -> bool:
        """Unregister triggers using the appropriate handler.

        Only deletes triggers from Composio when no other workflows reference
        them: Composio upserts, so workflows with identical configs share a
        trigger ID. Returns True once the operation completes, even if some
        triggers were kept due to remaining references.
        """
        if not trigger_ids:
            return True

        handler = get_handler_by_name(trigger_name)
        if not handler:
            log.error(
                f"{LogTag.WORKFLOW} No handler found for trigger",
                trigger_name=trigger_name,
                user_id=user_id,
                workflow_id=workflow_id,
            )
            return False

        try:
            # Filter to only triggers safe to delete
            safe_to_delete = await TriggerService.get_triggers_safe_to_delete(
                trigger_ids, excluding_workflow_id=workflow_id
            )

            if not safe_to_delete:
                log.info(
                    f"{LogTag.WORKFLOW} No triggers safe to delete - all trigger(s) are still referenced by other workflows",
                    trigger_ids_count=len(trigger_ids),
                )
                return True

            if len(safe_to_delete) < len(trigger_ids):
                log.info(
                    f"{LogTag.WORKFLOW} Only of triggers are safe to delete (others still referenced)",
                    safe_to_delete_count=len(safe_to_delete),
                    trigger_ids_count=len(trigger_ids),
                )

            return await handler.unregister(user_id, safe_to_delete)
        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error unregistering triggers",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                workflow_id=workflow_id,
            )
            return False

    @staticmethod
    async def resync_user_workflow_triggers(user_id: str, trigger_names: list[str]) -> None:
        """Re-register a user's activated integration workflows after a (re)connect.

        Reconnecting an integration creates a fresh Composio connected account,
        so per-workflow triggers registered against the old account stop firing
        and the stored ``composio_trigger_ids`` go permanently stale. Re-register
        each affected workflow against the current account and repoint its ids.
        Failures are logged per workflow — one broken workflow must not block
        the rest of the resync (or the OAuth flow it runs behind).
        """
        if not trigger_names:
            return
        for workflow in await workflow_repository.find_active_integration_workflows(
            user_id, trigger_names
        ):
            workflow_id = workflow.id
            tc = workflow.trigger_config
            if not tc.trigger_name:
                continue
            old_ids = tc.composio_trigger_ids or []
            try:
                new_ids = await TriggerService.register_triggers(
                    user_id, workflow_id, tc.trigger_name, tc
                )
            except Exception as e:
                log.error(
                    f"{LogTag.WORKFLOW} Trigger resync failed for workflow",
                    workflow_id=workflow_id,
                    trigger_name=tc.trigger_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
                continue
            # Account-level triggers (e.g. gmail_new_message) return no ids — nothing to repoint.
            if not new_ids or set(new_ids) == set(old_ids):
                continue
            await workflow_repository.set_composio_trigger_ids(workflow_id, new_ids)
            stale_ids = [i for i in old_ids if i not in new_ids]
            if stale_ids:
                await TriggerService.unregister_triggers(
                    user_id, tc.trigger_name, stale_ids, workflow_id
                )
            log.info(
                f"{LogTag.WORKFLOW} Resynced triggers for workflow",
                workflow_id=workflow_id,
                trigger_name=tc.trigger_name,
                old_ids=old_ids,
                new_ids=new_ids,
            )
