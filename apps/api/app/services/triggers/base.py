"""
Abstract base class for trigger handlers.

All provider-specific trigger handlers must extend this class.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set

from app.models.workflow_models import Workflow


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
        config: Dict[str, Any],
    ) -> List[str]:
        """Register triggers for a workflow.

        Args:
            user_id: The user ID
            workflow_id: The workflow ID
            trigger_name: The trigger name (e.g., 'calendar_event_created')
            config: Provider-specific config from trigger_data

        Returns:
            List of Composio trigger IDs that were registered
        """
        pass

    @abstractmethod
    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister triggers when workflow is deleted/deactivated.

        Args:
            user_id: The user ID
            trigger_ids: List of Composio trigger IDs to unregister

        Returns:
            True if all triggers were unregistered successfully
        """
        pass

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
