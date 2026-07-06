"""
Generic trigger management service for workflow automation.

Provides high-level trigger operations that delegate to provider-specific handlers.
Handles Composio trigger reference counting to prevent premature deletion.
"""

from typing import Any

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.triggers import get_handler_by_name
from app.utils.exceptions import TriggerRegistrationError
from app.utils.workflow_utils import ensure_trigger_config_object
from shared.py.wide_events import log


class TriggerService:
    """Generic service for managing workflow triggers.

    Delegates to provider-specific handlers for actual registration/unregistration.
    Handles reference counting for shared Composio triggers.
    """

    @staticmethod
    async def get_all_workflow_triggers() -> list[dict[str, Any]]:
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
                        {
                            "slug": schema.slug,
                            "composio_slug": schema.composio_slug,
                            "name": schema.name,
                            "description": schema.description,
                            "provider": integration.provider,
                            "integration_id": integration.id,
                            "config_schema": {
                                field_name: {
                                    "type": field_schema.type,
                                    "default": field_schema.default,
                                    "min": field_schema.min,
                                    "max": field_schema.max,
                                    "options_endpoint": field_schema.options_endpoint,
                                    "description": field_schema.description,
                                }
                                for field_name, field_schema in schema.config_schema.items()
                            },
                        }
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
                # Build query to count references
                query: dict[str, Any] = {"trigger_config.composio_trigger_ids": trigger_id}

                # Exclude the current workflow if provided
                if excluding_workflow_id:
                    query["_id"] = {"$ne": excluding_workflow_id}

                count = await workflows_collection.count_documents(query)

                if count == 0:
                    safe_to_delete.append(trigger_id)
                else:
                    log.debug(
                        f"{LogTag.WORKFLOW} Trigger {trigger_id} still referenced by {count} other workflow(s), skipping deletion"
                    )
            except Exception as e:
                log.error(
                    f"{LogTag.WORKFLOW} Error checking trigger references for {trigger_id}: {e}"
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
            log.error(f"{LogTag.WORKFLOW} {error_msg}")
            if raise_on_failure:
                raise TriggerRegistrationError(error_msg, trigger_name)
            return []

        try:
            # Pass TriggerConfig directly - handlers validate trigger_data type
            trigger_ids = await handler.register(user_id, workflow_id, trigger_name, trigger_config)
            return trigger_ids
        except TypeError as e:
            # Re-raise TypeError for type validation failures
            log.error(f"{LogTag.WORKFLOW} Type validation error registering triggers: {e!s}")
            raise
        except TriggerRegistrationError:
            # Re-raise our custom exception
            raise
        except Exception as e:
            error_msg = f"Error registering triggers: {type(e).__name__}: {e!s}"
            log.error(f"{LogTag.WORKFLOW} {error_msg}")
            log.exception(f"{LogTag.WORKFLOW} Full traceback:")
            if raise_on_failure:
                raise TriggerRegistrationError(error_msg, trigger_name)
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
            log.error(f"{LogTag.WORKFLOW} No handler found for trigger: {trigger_name}")
            return False

        try:
            # Filter to only triggers safe to delete
            safe_to_delete = await TriggerService.get_triggers_safe_to_delete(
                trigger_ids, excluding_workflow_id=workflow_id
            )

            if not safe_to_delete:
                log.info(
                    f"{LogTag.WORKFLOW} No triggers safe to delete - all {len(trigger_ids)} trigger(s) "
                    "are still referenced by other workflows"
                )
                return True

            if len(safe_to_delete) < len(trigger_ids):
                log.info(
                    f"{LogTag.WORKFLOW} Only {len(safe_to_delete)} of {len(trigger_ids)} triggers "
                    "are safe to delete (others still referenced)"
                )

            return await handler.unregister(user_id, safe_to_delete)
        except Exception as e:
            log.error(f"{LogTag.WORKFLOW} Error unregistering triggers: {e}")
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
        query = {
            "user_id": user_id,
            "activated": True,
            "trigger_config.type": TriggerType.INTEGRATION,
            "trigger_config.enabled": True,
            "trigger_config.trigger_name": {"$in": trigger_names},
        }
        async for doc in workflows_collection.find(query):
            workflow_id = doc["_id"]
            tc = ensure_trigger_config_object(doc.get("trigger_config") or {})
            if not tc.trigger_name:
                continue
            old_ids = tc.composio_trigger_ids or []
            try:
                new_ids = await TriggerService.register_triggers(
                    user_id, workflow_id, tc.trigger_name, tc
                )
            except Exception as e:
                log.error(
                    f"{LogTag.WORKFLOW} Trigger resync failed for workflow {workflow_id} "
                    f"({tc.trigger_name}): {e}"
                )
                continue
            # Account-level triggers (e.g. gmail_new_message) return no ids — nothing to repoint.
            if not new_ids or set(new_ids) == set(old_ids):
                continue
            await workflows_collection.update_one(
                {"_id": workflow_id},
                {"$set": {"trigger_config.composio_trigger_ids": new_ids}},
            )
            stale_ids = [i for i in old_ids if i not in new_ids]
            if stale_ids:
                await TriggerService.unregister_triggers(
                    user_id, tc.trigger_name, stale_ids, workflow_id
                )
            log.info(
                f"{LogTag.WORKFLOW} Resynced triggers for workflow {workflow_id} "
                f"({tc.trigger_name}): {old_ids} -> {new_ids}"
            )
