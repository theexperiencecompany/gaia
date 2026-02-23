"""
Trigger Utilities

Helper functions for trigger type detection and integration mapping.
Uses oauth_config.py as single source of truth.
"""

from typing import Optional

from app.config.oauth_config import OAUTH_INTEGRATIONS


def has_integration_triggers(trigger_type: str) -> bool:
    """
    Check if a trigger type has associated Composio triggers.

    Args:
        trigger_type: The trigger type/name to check (e.g., "calendar_event_created")

    Returns:
        bool: True if the trigger has Composio integration, False otherwise

    Example:
        >>> has_integration_triggers("calendar_event_created")
        True
        >>> has_integration_triggers("manual")
        False
    """
    for integration in OAUTH_INTEGRATIONS:
        if not integration.associated_triggers:
            continue

        for trigger in integration.associated_triggers:
            if not trigger.workflow_trigger_schema:
                continue

            # Match against the workflow trigger slug
            if trigger.workflow_trigger_schema.slug == trigger_type:
                return True

    return False


def get_integration_for_trigger(trigger_name: str) -> Optional[str]:
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


def get_all_trigger_types() -> set[str]:
    """
    Get all trigger types that have Composio integrations.

    Returns:
        set[str]: Set of all trigger type slugs with Composio integrations

    Example:
        >>> triggers = get_all_trigger_types()
        >>> "calendar_event_created" in triggers
        True
    """
    trigger_types = set()

    for integration in OAUTH_INTEGRATIONS:
        if not integration.associated_triggers:
            continue

        for trigger in integration.associated_triggers:
            if trigger.workflow_trigger_schema:
                trigger_types.add(trigger.workflow_trigger_schema.slug)

    return trigger_types
