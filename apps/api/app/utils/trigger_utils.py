"""
Trigger Utilities

Helper functions for trigger type detection and integration mapping.
Uses oauth_config.py as single source of truth.
"""

from app.config.oauth_config import OAUTH_INTEGRATIONS


def get_integration_for_trigger(trigger_name: str) -> str | None:
    """
    Get the integration ID for a given trigger name.

    Args:
        trigger_name: The trigger name to lookup (e.g., "calendar_event_created")

    Returns:
        Optional[str]: The integration ID if found, None otherwise

    Example:
        >>> get_integration_for_trigger("calendar_event_created")
        'googlecalendar'
        >>> get_integration_for_trigger("github_commit_event")
        'github'
    """
    for integration in OAUTH_INTEGRATIONS:
        if not integration.associated_triggers:
            continue

        for trigger in integration.associated_triggers:
            if not trigger.workflow_trigger_schema:
                continue

            if trigger.workflow_trigger_schema.slug == trigger_name:
                return integration.id

    return None
