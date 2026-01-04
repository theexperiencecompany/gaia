"""
Triggers package initialization.

Registers all trigger handlers with the global registry.
"""

from app.services.triggers.handlers.calendar import calendar_trigger_handler
from app.services.triggers.handlers.gmail import gmail_trigger_handler
from app.services.triggers.registry import (
    get_handler_by_event,
    get_handler_by_name,
    trigger_registry,
)

# Register all handlers
trigger_registry.register(calendar_trigger_handler)
trigger_registry.register(gmail_trigger_handler)

__all__ = [
    "trigger_registry",
    "get_handler_by_name",
    "get_handler_by_event",
]
