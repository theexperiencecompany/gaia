"""
Google Calendar trigger handler.

Handles all calendar-specific trigger logic including:
- Multi-calendar registration
- "All calendars" expansion
- Event-to-workflow matching
"""

import asyncio
from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import (
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
)
from app.models.workflow_models import TriggerType, Workflow
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
        config: Dict[str, Any],
    ) -> List[str]:
        """Register calendar triggers.

        Handles multi-calendar registration - creates one Composio trigger
        per calendar ID for proper event matching.
        """
        trigger_data = config.get("trigger_data", {})
        calendar_ids = trigger_data.get("calendar_ids", ["primary"])

        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown calendar trigger: {trigger_name}")
            return []

        if calendar_ids == ["all"]:
            calendar_ids = await self._fetch_user_calendars(user_id)

        composio = get_composio_service()

        async def register_one(calendar_id: str) -> str | None:
            try:
                trigger_config: Dict[str, Any] = {"calendar_id": calendar_id}
                if trigger_name == "calendar_event_starting_soon":
                    minutes_before = trigger_data.get("minutes_before_start")
                    if minutes_before is not None:
                        trigger_config["countdown_window_minutes"] = minutes_before * 60
                    include_all_day = trigger_data.get("include_all_day")
                    if include_all_day is not None:
                        trigger_config["include_all_day"] = include_all_day

                result = await asyncio.to_thread(
                    composio.composio.triggers.create,
                    user_id=user_id,
                    slug=composio_slug,
                    trigger_config=trigger_config,
                )
                if result and hasattr(result, "trigger_id"):
                    logger.info(
                        f"Registered {composio_slug} for calendar {calendar_id}: {result.trigger_id}"
                    )
                    return result.trigger_id
                else:
                    logger.warning(
                        f"No trigger_id in result for calendar {calendar_id}"
                    )
                    return None
            except Exception as e:
                logger.error(
                    f"Failed to register trigger for {calendar_id}: {e}",
                    exc_info=True,
                )
                return None

        results = await asyncio.gather(*(register_one(cid) for cid in calendar_ids))
        return [rid for rid in results if rid]

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a calendar trigger event."""
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.CALENDAR,
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
