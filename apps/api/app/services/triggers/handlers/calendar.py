"""
Google Calendar trigger handler.

Handles all calendar-specific trigger logic including:
- Multi-calendar registration
- "All calendars" expansion
- Event-to-workflow matching
"""

from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import (
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
)
from app.models.trigger_configs import (
    CalendarEventCreatedConfig,
    CalendarEventStartingSoonConfig,
)
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError


class CalendarTriggerHandler(TriggerHandler):
    """Handler for Google Calendar triggers."""

    # Trigger names this handler supports
    SUPPORTED_TRIGGERS = [
        "calendar_event_created",
        "calendar_event_starting_soon",
    ]

    # Composio event types this handler processes
    SUPPORTED_EVENTS = {
        "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
        "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
    }

    # Mapping from trigger_name to Composio slug
    TRIGGER_TO_COMPOSIO = {
        "calendar_event_created": "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
        "calendar_event_starting_soon": "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
    }

    @property
    def trigger_names(self) -> List[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> Set[str]:
        return self.SUPPORTED_EVENTS

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        """Register calendar triggers with parallel execution and rollback.

        Handles multi-calendar registration - creates one Composio trigger
        per calendar ID for proper event matching. If any fail, all are rolled back.

        Raises:
            TriggerRegistrationError: If any trigger registration fails
        """
        trigger_data = trigger_config.trigger_data

        # Validate trigger_data type based on trigger_name
        if trigger_name == "calendar_event_created":
            if not isinstance(trigger_data, CalendarEventCreatedConfig):
                raise TypeError(
                    f"Expected CalendarEventCreatedConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
                )
            calendar_ids = trigger_data.calendar_ids
        elif trigger_name == "calendar_event_starting_soon":
            if not isinstance(trigger_data, CalendarEventStartingSoonConfig):
                raise TypeError(
                    f"Expected CalendarEventStartingSoonConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
                )
            calendar_ids = trigger_data.calendar_ids
        else:
            raise TriggerRegistrationError(
                f"Unknown calendar trigger: {trigger_name}",
                trigger_name,
            )

        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            raise TriggerRegistrationError(
                f"Unknown calendar trigger: {trigger_name}",
                trigger_name,
            )

        if calendar_ids == ["all"]:
            calendar_ids = await self._fetch_user_calendars(user_id)

        if not calendar_ids:
            return []

        # Build configs for each calendar
        configs: List[Dict[str, Any]] = []
        for calendar_id in calendar_ids:
            config: Dict[str, Any] = {"calendarId": calendar_id}
            if trigger_name == "calendar_event_starting_soon":
                if not isinstance(trigger_data, CalendarEventStartingSoonConfig):
                    # Should be covered by validation above, but for MyPy safety:
                    raise TypeError("Expected CalendarEventStartingSoonConfig")

                starting_soon_data = trigger_data
                if starting_soon_data.minutes_before_start is not None:
                    config["countdown_window_minutes"] = (
                        starting_soon_data.minutes_before_start * 60
                    )
                if starting_soon_data.include_all_day is not None:
                    config["include_all_day"] = starting_soon_data.include_all_day
            configs.append(config)

        # Use the base class helper for parallel registration with rollback
        return await self._register_triggers_parallel(
            user_id=user_id,
            trigger_name=trigger_name,
            configs=configs,
            composio_slug=composio_slug,
        )

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a calendar trigger event."""
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }

            # optional: validate payload for calendar events
            # Validate payload based on event type
            if "event_created" in event_type.lower():
                try:
                    GoogleCalendarEventCreatedPayload.model_validate(data)
                except Exception as e:
                    logger.debug(
                        f"Calendar event created payload validation failed: {e}"
                    )
            elif "event_starting_soon" in event_type.lower():
                try:
                    GoogleCalendarEventStartingSoonPayload.model_validate(data)
                except Exception as e:
                    logger.debug(
                        f"Calendar event starting soon payload validation failed: {e}"
                    )

            cursor = workflows_collection.find(query)
            workflows: List[Workflow] = []

            async for workflow_doc in cursor:
                try:
                    workflow_doc["id"] = workflow_doc.get("_id")
                    if "_id" in workflow_doc:
                        del workflow_doc["_id"]

                    workflow = Workflow(**workflow_doc)
                    workflows.append(workflow)

                except Exception as e:
                    logger.error(f"Error processing workflow document: {e}")
                    continue

            return workflows

        except Exception as e:
            logger.error(f"Error finding workflows for trigger {trigger_id}: {e}")
            return []

    async def _fetch_user_calendars(self, user_id: str) -> List[str]:
        """Fetch list of user's calendar IDs.

        Used when calendar_ids is set to ["all"].
        """
        try:
            # Import here to avoid circular imports
            from app.services import calendar_service

            calendars = calendar_service.list_calendars(user_id)

            if calendars and "items" in calendars:
                return [
                    cal.get("id", "primary")
                    for cal in calendars["items"]
                    if cal.get("id")
                ]
            return ["primary"]

        except Exception as e:
            logger.error(f"Failed to fetch calendars for user {user_id}: {e}")
            return ["primary"]  # Fallback to primary calendar


calendar_trigger_handler = CalendarTriggerHandler()
