"""
Trigger handler registry.

Maps trigger names and event types to their handlers.
Provides plug-and-play registration for new trigger handlers.
"""

from typing import Dict, Optional, Set

from app.config.loggers import general_logger as logger
from app.services.triggers.base import TriggerHandler


class TriggerRegistry:
    """Registry for trigger handlers.

    Handlers are registered by trigger names and event types,
    allowing efficient lookup for both workflow creation and webhook processing.
    """

    def __init__(self) -> None:
        # Maps trigger_name -> handler
        self._name_handlers: Dict[str, TriggerHandler] = {}
        # Maps event_type -> handler
        self._event_handlers: Dict[str, TriggerHandler] = {}

    def register(self, handler: TriggerHandler) -> None:
        """Register a trigger handler.

        Args:
            handler: The handler instance to register
        """
        # Register by trigger names
        for name in handler.trigger_names:
            if name in self._name_handlers:
                logger.warning(f"Overwriting handler for trigger: {name}")
            self._name_handlers[name] = handler
            logger.info(f"Registered handler for trigger: {name}")

        # Register by event types
        for event_type in handler.event_types:
            if event_type in self._event_handlers:
                logger.warning(f"Overwriting handler for event: {event_type}")
            self._event_handlers[event_type] = handler
            logger.info(f"Registered handler for event: {event_type}")

    def get_by_trigger_name(self, trigger_name: str) -> Optional[TriggerHandler]:
        """Get handler by trigger name (for registration)."""
        return self._name_handlers.get(trigger_name)

    def get_by_event_type(self, event_type: str) -> Optional[TriggerHandler]:
        """Get handler by event type (for webhook processing)."""
        return self._event_handlers.get(event_type)

    def get_all_trigger_names(self) -> Set[str]:
        """Get all registered trigger names."""
        return set(self._name_handlers.keys())

    def get_all_event_types(self) -> Set[str]:
        """Get all registered event types."""
        return set(self._event_handlers.keys())


# Global registry instance
trigger_registry = TriggerRegistry()


def get_handler_by_name(trigger_name: str) -> Optional[TriggerHandler]:
    """Get handler by trigger name."""
    return trigger_registry.get_by_trigger_name(trigger_name)


def get_handler_by_event(event_type: str) -> Optional[TriggerHandler]:
    """Get handler by event type."""
    return trigger_registry.get_by_event_type(event_type)
