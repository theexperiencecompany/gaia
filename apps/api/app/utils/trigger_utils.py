"""
Trigger Utilities

Helper functions for trigger type detection and integration mapping.
Uses oauth_config.py as single source of truth.
"""

from app.config.oauth_config import OAUTH_INTEGRATIONS


def get_integration_for_trigger(trigger_name: str) -> str | None:
    """Return the integration ID owning ``trigger_name``, or None.

    E.g. "calendar_event_created" -> "googlecalendar".
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
