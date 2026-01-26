"""
Generic trigger management service for workflow automation.

Provides high-level trigger operations that delegate to provider-specific handlers.
Handles Composio trigger reference counting to prevent premature deletion.
"""

from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.mongodb.collections import workflows_collection
from app.decorators.caching import Cacheable
from app.models.trigger_config import WorkflowTriggerSchema
from app.models.workflow_models import TriggerConfig
from app.services.triggers import get_handler_by_name
from app.utils.exceptions import TriggerRegistrationError


class TriggerService:
    """Generic service for managing workflow triggers.

    Delegates to provider-specific handlers for actual registration/unregistration.
    Handles reference counting for shared Composio triggers.
    """

    @staticmethod
    @Cacheable(smart_hash=True, ttl=3600)
    async def get_all_workflow_triggers() -> List[Dict[str, Any]]:
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
    def get_trigger_by_slug(slug: str) -> Optional[WorkflowTriggerSchema]:
        """Get a workflow trigger schema by its slug."""
        for integration in OAUTH_INTEGRATIONS:
            for trigger_config in integration.associated_triggers:
                if (
                    trigger_config.workflow_trigger_schema
                    and trigger_config.workflow_trigger_schema.slug == slug
                ):
                    return trigger_config.workflow_trigger_schema
        return None

    @staticmethod
    async def get_trigger_reference_count(trigger_id: str) -> int:
        """
        Count how many workflows reference a specific Composio trigger ID.

        Composio uses upsert for triggers, so multiple workflows may share
        the same trigger ID if they have identical configurations.

        Args:
            trigger_id: The Composio trigger ID to check

        Returns:
            Number of workflows referencing this trigger
        """
        try:
            count = await workflows_collection.count_documents(
                {"trigger_config.composio_trigger_ids": trigger_id}
            )
            return count
        except Exception as e:
            logger.error(f"Error counting trigger references for {trigger_id}: {e}")
            return 0

    @staticmethod
    async def get_triggers_safe_to_delete(
        trigger_ids: List[str], excluding_workflow_id: Optional[str] = None
    ) -> List[str]:
        """
        Filter trigger IDs to only those safe to delete from Composio.

        A trigger is safe to delete if no other workflows reference it.
        When excluding_workflow_id is provided, we check if any OTHER workflows
        reference the trigger (used during workflow deletion/update).

        Args:
            trigger_ids: List of Composio trigger IDs to check
            excluding_workflow_id: Workflow ID to exclude from reference count

        Returns:
            List of trigger IDs that are safe to delete
        """
        safe_to_delete = []

        for trigger_id in trigger_ids:
            try:
                # Build query to count references
                query: Dict[str, Any] = {
                    "trigger_config.composio_trigger_ids": trigger_id
                }

                # Exclude the current workflow if provided
                if excluding_workflow_id:
                    query["_id"] = {"$ne": excluding_workflow_id}

                count = await workflows_collection.count_documents(query)

                if count == 0:
                    safe_to_delete.append(trigger_id)
                else:
                    logger.debug(
                        f"Trigger {trigger_id} still referenced by {count} other workflow(s), skipping deletion"
                    )
            except Exception as e:
                logger.error(f"Error checking trigger references for {trigger_id}: {e}")
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
    ) -> List[str]:
        """
        Register triggers for a workflow using the appropriate handler.

        Args:
            user_id: The user ID
            workflow_id: The workflow ID
            trigger_name: The trigger name (e.g., 'calendar_event_created')
            trigger_config: The TriggerConfig object with properly typed trigger_data
            raise_on_failure: If True, raise TriggerRegistrationError when no triggers created

        Returns:
            List of registered Composio trigger IDs

        Raises:
            TypeError: If trigger_data type doesn't match expected type
            TriggerRegistrationError: If raise_on_failure=True and no triggers were created
        """
        handler = get_handler_by_name(trigger_name)
        if not handler:
            error_msg = f"No handler found for trigger: {trigger_name}"
            logger.error(error_msg)
            if raise_on_failure:
                raise TriggerRegistrationError(error_msg, trigger_name)
            return []

        try:
            # Pass TriggerConfig directly - handlers validate trigger_data type
            trigger_ids = await handler.register(
                user_id, workflow_id, trigger_name, trigger_config
            )

            if not trigger_ids and raise_on_failure:
                raise TriggerRegistrationError(
                    f"Failed to register any triggers for '{trigger_name}'. "
                    "This may be due to permission issues or invalid configuration.",
                    trigger_name,
                )

            return trigger_ids
        except TypeError as e:
            # Re-raise TypeError for type validation failures
            logger.error(f"Type validation error registering triggers: {str(e)}")
            raise
        except TriggerRegistrationError:
            # Re-raise our custom exception
            raise
        except Exception as e:
            error_msg = f"Error registering triggers: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            logger.exception("Full traceback:")
            if raise_on_failure:
                raise TriggerRegistrationError(error_msg, trigger_name)
            return []

    @staticmethod
    async def unregister_triggers(
        user_id: str,
        trigger_name: str,
        trigger_ids: List[str],
        workflow_id: Optional[str] = None,
    ) -> bool:
        """
        Unregister triggers using the appropriate handler.

        Only deletes triggers from Composio if no other workflows reference them.
        This is important because Composio uses upsert - multiple workflows may
        share the same trigger ID if they have identical configurations.

        Args:
            user_id: The user ID
            trigger_name: The trigger name to find the right handler
            trigger_ids: List of Composio trigger IDs to unregister
            workflow_id: The workflow being deleted/updated (to exclude from ref count)

        Returns:
            True if operation completed (even if some triggers weren't deleted due to refs)
        """
        if not trigger_ids:
            return True

        handler = get_handler_by_name(trigger_name)
        if not handler:
            logger.error(f"No handler found for trigger: {trigger_name}")
            return False

        try:
            # Filter to only triggers safe to delete
            safe_to_delete = await TriggerService.get_triggers_safe_to_delete(
                trigger_ids, excluding_workflow_id=workflow_id
            )

            if not safe_to_delete:
                logger.info(
                    f"No triggers safe to delete - all {len(trigger_ids)} trigger(s) "
                    "are still referenced by other workflows"
                )
                return True

            if len(safe_to_delete) < len(trigger_ids):
                logger.info(
                    f"Only {len(safe_to_delete)} of {len(trigger_ids)} triggers "
                    "are safe to delete (others still referenced)"
                )

            return await handler.unregister(user_id, safe_to_delete)
        except Exception as e:
            logger.error(f"Error unregistering triggers: {e}")
            return False
