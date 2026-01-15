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
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler


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
        """Register calendar triggers.

        Handles multi-calendar registration - creates one Composio trigger
        per calendar ID for proper event matching.
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
            logger.error(f"Unknown calendar trigger: {trigger_name}")
            return []

        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown calendar trigger: {trigger_name}")
            return []

        if calendar_ids == ["all"]:
            calendar_ids = await self._fetch_user_calendars(user_id)

        composio_service = get_composio_service()

        trigger_ids: List[str] = []

        for calendar_id in calendar_ids:
            try:
                composio_trigger_config: Dict[str, Any] = {"calendarId": calendar_id}
                if trigger_name == "calendar_event_starting_soon":
                    # trigger_data is already validated as CalendarEventStartingSoonConfig
                    starting_soon_data = trigger_data  # type: CalendarEventStartingSoonConfig
                    if starting_soon_data.minutes_before_start is not None:
                        composio_trigger_config["countdown_window_minutes"] = (
                            starting_soon_data.minutes_before_start * 60
                        )
                    if starting_soon_data.include_all_day is not None:
                        composio_trigger_config["include_all_day"] = (
                            starting_soon_data.include_all_day
                        )

                result = composio_service.composio.triggers.create(
                    user_id=user_id,
                    slug=composio_slug,
                    trigger_config=composio_trigger_config,
                )

                if result and hasattr(result, "trigger_id"):
                    trigger_id = result.trigger_id
                    trigger_ids.append(trigger_id)
                else:
                    logger.warning(f"No trigger_id in result for {calendar_id}")

            except Exception as e:
                logger.error(
                    f"Failed to register trigger for {calendar_id}: {e}",
                    exc_info=True,
                )
        return trigger_ids

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
