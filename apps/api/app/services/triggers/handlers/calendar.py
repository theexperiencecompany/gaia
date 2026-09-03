"""
Google Calendar trigger handler.

Handles all calendar-specific trigger logic including:
- Multi-calendar registration
- "All calendars" expansion
- Event-to-workflow matching
"""

from typing import Any, ClassVar

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.composio_schemas import (
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
)
from app.models.trigger_configs import (
    CalendarEventCreatedConfig,
    CalendarEventStartingSoonConfig,
)
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import TriggerContext, log


class CalendarTriggerHandler(TriggerHandler):
    """Handler for Google Calendar triggers."""

    # Trigger names this handler supports
    SUPPORTED_TRIGGERS: ClassVar[list[str]] = [
        "calendar_event_created",
        "calendar_event_starting_soon",
    ]

    # Composio event types this handler processes
    SUPPORTED_EVENTS: ClassVar[set[str]] = {
        "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
        "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
    }

    # Mapping from trigger_name to Composio slug
    TRIGGER_TO_COMPOSIO: ClassVar[dict[str, str]] = {
        "calendar_event_created": "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
        "calendar_event_starting_soon": "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
    }

    @property
    def trigger_names(self) -> list[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> set[str]:
        return self.SUPPORTED_EVENTS

    async def register(
        self,
        user_id: str,
        _owner_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> list[str]:
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
        configs: list[dict[str, Any]] = []
        for calendar_id in calendar_ids:
            config: dict[str, Any] = {"calendarId": calendar_id}
            if trigger_name == "calendar_event_starting_soon":
                if not isinstance(trigger_data, CalendarEventStartingSoonConfig):
                    # Should be covered by validation above, but for MyPy safety:
                    raise TypeError("Expected CalendarEventStartingSoonConfig")

                starting_soon_data = trigger_data
                if starting_soon_data.minutes_before_start is not None:
                    config["countdown_window_minutes"] = starting_soon_data.minutes_before_start
                if starting_soon_data.include_all_day is not None:
                    config["include_all_day"] = starting_soon_data.include_all_day
            configs.append(config)

        log.set(
            trigger_name=trigger_name,
            composio_slug=composio_slug,
            calendar_count=len(calendar_ids),
            minutes_before_start=(
                trigger_data.minutes_before_start
                if isinstance(trigger_data, CalendarEventStartingSoonConfig)
                else None
            ),
            trigger=TriggerContext(
                operation="register",
                trigger_type=trigger_name,
                integration_id="google_calendar",
            ),
        )

        # Use the base class helper for parallel registration with rollback
        trigger_ids = await self._register_triggers_parallel(
            user_id=user_id,
            trigger_name=trigger_name,
            configs=configs,
            composio_slug=composio_slug,
        )
        log.set(composio_trigger_ids=trigger_ids, trigger_ids_count=len(trigger_ids))
        log.set_ns("trigger", result_count=len(trigger_ids))
        return trigger_ids

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, Any]
    ) -> list[Workflow]:
        """Find workflows matching a calendar trigger event."""
        log.set_ns("trigger", integration_id="google_calendar", trigger_type=event_type)
        try:
            # optional: validate payload for calendar events
            # Validate payload based on event type
            if "event_created" in event_type.lower():
                try:
                    GoogleCalendarEventCreatedPayload.model_validate(data)
                except Exception as e:
                    log.debug(
                        f"{LogTag.TRIGGER} Calendar event created payload validation failed",
                        error=str(e),
                        error_type=type(e).__name__,
                    )
            elif "event_starting_soon" in event_type.lower():
                try:
                    GoogleCalendarEventStartingSoonPayload.model_validate(data)
                except Exception as e:
                    log.debug(
                        f"{LogTag.TRIGGER} Calendar event starting soon payload validation failed",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            workflows: list[Workflow] = []
            workflows.extend(await workflow_repository.find_active_by_composio_trigger(trigger_id))
            return workflows

        except Exception as e:
            log.error(
                f"{LogTag.TRIGGER} Error finding workflows for trigger",
                trigger_id=trigger_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []

    async def _fetch_user_calendars(self, user_id: str) -> list[str]:
        """Fetch list of user's calendar IDs.

        Used when calendar_ids is set to ["all"].
        """
        try:
            # Import here to avoid circular imports
            # Deferred import: breaks circular import: calendar_service chain re-enters the trigger-handler modules
            from app.services import calendar_service  # noqa: PLC0415 -- calendar cycle

            calendar_list = await calendar_service.list_calendars(user_id)

            # An `items`-less payload means Google told us nothing about the user's
            # calendars, which is not the same as "the user has zero calendars" —
            # only the former falls back to primary.
            if "items" in calendar_list.model_fields_set:
                return [cal.id for cal in calendar_list.items]
            return ["primary"]

        except Exception as e:
            log.error(
                f"{LogTag.TRIGGER} Failed to fetch calendars for user",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ["primary"]  # Fallback to primary calendar


calendar_trigger_handler = CalendarTriggerHandler()
