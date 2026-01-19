"""
Abstract base class for trigger handlers.

All provider-specific trigger handlers must extend this class.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.composio.composio_service import get_composio_service
from app.utils.exceptions import TriggerRegistrationError


class TriggerHandler(ABC):
    """Abstract base for all trigger handlers.

    Each provider (calendar, gmail, github, etc.) implements this interface
    to handle registration, unregistration, and webhook processing.
    """

    @property
    @abstractmethod
    def trigger_names(self) -> List[str]:
        """Return supported trigger names (e.g., ['calendar_event_created']).

        These are the values stored in trigger_data.trigger_name.
        """
        pass

    @property
    @abstractmethod
    def event_types(self) -> Set[str]:
        """Return Composio event types this handler processes.

        These are the webhook event types from Composio (e.g., 'GOOGLECALENDAR_...')
        """
        pass

    @abstractmethod
    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        """Register triggers for a workflow.

        Args:
            user_id: The user ID
            workflow_id: The workflow ID
            trigger_name: The trigger name (e.g., 'calendar_event_created')
            trigger_config: The complete TriggerConfig with typed trigger_data

        Returns:
            List of Composio trigger IDs that were registered
        """
        pass

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister triggers when workflow is deleted/deactivated.

        Default implementation uses Composio triggers.delete API.
        Override if provider needs custom logic.

        Args:
            user_id: The user ID
            trigger_ids: List of Composio trigger IDs to unregister

        Returns:
            True if all triggers were unregistered successfully
        """
        if not trigger_ids:
            return True

        success = True
        composio = get_composio_service()

        for trigger_id in trigger_ids:
            try:
                await asyncio.to_thread(
                    composio.composio.triggers.delete,
                    trigger_id=trigger_id,
                )
                logger.debug(f"Deleted trigger: {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to delete trigger {trigger_id}: {e}")
                success = False

        return success

    async def _register_triggers_parallel(
        self,
        user_id: str,
        trigger_name: str,
        configs: List[Dict[str, Any]],
        composio_slug: str,
        config_description_fn: Optional[Callable[[Dict[str, Any]], str]] = None,
    ) -> List[str]:
        """Register multiple triggers in parallel with automatic rollback on failure.

        This is a reusable helper for handlers that create multiple triggers.
        If any registration fails, all successful ones are rolled back.

        Args:
            user_id: The user ID
            trigger_name: The trigger name (for error messages)
            configs: List of Composio trigger configs to register
            composio_slug: The Composio trigger slug
            config_description_fn: Optional function to describe a config for logging

        Returns:
            List of registered trigger IDs (only if ALL succeed)

        Raises:
            TriggerRegistrationError: If any registration fails
        """

        if not configs:
            return []

        composio = get_composio_service()

        async def register_single(config: Dict[str, Any]) -> Optional[str]:
            """Register a single trigger and return trigger_id."""
            result = await asyncio.to_thread(
                composio.composio.triggers.create,
                user_id=user_id,
                slug=composio_slug,
                trigger_config=config,
            )
            if result and hasattr(result, "trigger_id"):
                return result.trigger_id
            return None

        # Execute all registrations in parallel
        results = await asyncio.gather(
            *[register_single(cfg) for cfg in configs],
            return_exceptions=True,
        )

        # Collect results and check for failures
        successful_ids: List[str] = []
        has_failure = False
        failure_message = ""

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                has_failure = True
                failure_message = str(result)
                config_desc = (
                    config_description_fn(configs[i])
                    if config_description_fn
                    else str(configs[i])
                )
                logger.error(f"Trigger registration failed for {config_desc}: {result}")
            elif result is not None:
                successful_ids.append(result)

        # If any failed, rollback all successful ones
        if has_failure:
            if successful_ids:
                logger.warning(
                    f"Rolling back {len(successful_ids)} triggers due to partial failure"
                )
                await self.unregister(user_id, successful_ids)

            raise TriggerRegistrationError(
                f"Failed to register all {trigger_name} triggers: {failure_message}",
                trigger_name,
                partial_ids=successful_ids,
            )

        return successful_ids

    @abstractmethod
    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows that match an incoming webhook event.

        Args:
            event_type: The Composio event type
            trigger_id: The Composio trigger ID from the webhook
            data: The webhook payload data

        Returns:
            List of workflows to execute
        """
        pass

    async def get_config_options(
        self,
        trigger_name: str,
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, str]]:
        """Get dynamic options for a trigger configuration field.

        Optional method for handlers to provide dropdown options for
        configuration fields (e.g., list of channels, boards, repos).

        Supports cascading dropdowns by accepting parent_ids to filter children.

        Args:
            trigger_name: The trigger slug (e.g., 'slack_new_message')
            field_name: The config field name (e.g., 'channel_id')
            user_id: The user ID
            integration_id: The integration ID (e.g., 'slack')
            parent_ids: Parent IDs for cascading options (e.g., workspace IDs)

        Returns:
            List of options as [{"value": "...", "label": "..."}]
            For grouped options: [{"group": "...", "options": [...]}]
            Empty list if no dynamic options available
        """
        return []
