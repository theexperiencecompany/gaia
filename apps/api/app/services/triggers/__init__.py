"""
Triggers package initialization.

Registers all trigger handlers with the global registry.
"""

from app.services.triggers.handlers.asana import asana_trigger_handler
from app.services.triggers.handlers.calendar import calendar_trigger_handler
from app.services.triggers.handlers.github import github_trigger_handler
from app.services.triggers.handlers.gmail import gmail_trigger_handler
from app.services.triggers.handlers.google_docs import google_docs_trigger_handler
from app.services.triggers.handlers.google_sheets import google_sheets_trigger_handler
from app.services.triggers.handlers.linear import linear_trigger_handler
from app.services.triggers.handlers.notion import notion_trigger_handler
from app.services.triggers.handlers.slack import slack_trigger_handler
from app.services.triggers.handlers.todoist import todoist_trigger_handler
from app.services.triggers.registry import (
    get_handler_by_event,
    get_handler_by_name,
    trigger_registry,
)

# Register all handlers
trigger_registry.register(calendar_trigger_handler)
trigger_registry.register(github_trigger_handler)
trigger_registry.register(gmail_trigger_handler)
trigger_registry.register(google_docs_trigger_handler)
trigger_registry.register(google_sheets_trigger_handler)
trigger_registry.register(linear_trigger_handler)
trigger_registry.register(notion_trigger_handler)
trigger_registry.register(slack_trigger_handler)
trigger_registry.register(todoist_trigger_handler)
trigger_registry.register(asana_trigger_handler)

__all__ = [
    "trigger_registry",
    "get_handler_by_name",
    "get_handler_by_event",
]
