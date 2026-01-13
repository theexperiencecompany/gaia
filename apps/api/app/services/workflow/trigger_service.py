"""
Generic trigger management service for workflow automation.

Provides high-level trigger operations that delegate to provider-specific handlers.
"""

from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.decorators.caching import Cacheable
from app.models.oauth_models import WorkflowTriggerSchema
from app.services.triggers import get_handler_by_name


class TriggerService:
    """Generic service for managing workflow triggers.

    Delegates to provider-specific handlers for actual registration/unregistration.
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
    async def register_triggers(
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        config: Dict[str, Any],
    ) -> List[str]:
        """
        Register triggers for a workflow using the appropriate handler.

        Args:
            user_id: The user ID
            workflow_id: The workflow ID
            trigger_name: The trigger name (e.g., 'calendar_event_created')
            config: Provider-specific configuration

        Returns:
            List of registered Composio trigger IDs
        """
        handler = get_handler_by_name(trigger_name)
        if not handler:
            logger.error(f"No handler found for trigger: {trigger_name}")
            return []

        try:
            return await handler.register(user_id, workflow_id, trigger_name, config)
        except Exception as e:
            logger.error(f"Error registering triggers: {e}", exc_info=True)
            return []

    @staticmethod
    async def unregister_triggers(
        user_id: str,
        trigger_name: str,
        trigger_ids: List[str],
    ) -> bool:
        """
        Unregister triggers using the appropriate handler.

        Args:
            user_id: The user ID
            trigger_name: The trigger name to find the right handler
            trigger_ids: List of Composio trigger IDs to unregister

        Returns:
            True if all triggers were unregistered successfully
        """
        if not trigger_ids:
            return True

        handler = get_handler_by_name(trigger_name)
        if not handler:
            logger.error(f"No handler found for trigger: {trigger_name}")
            return False

        try:
            return await handler.unregister(user_id, trigger_ids)
        except Exception as e:
            logger.error(f"Error unregistering triggers: {e}")
            return False
