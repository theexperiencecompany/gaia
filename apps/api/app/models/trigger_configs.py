"""
Type-safe trigger configuration models.

This module defines Pydantic models for provider-specific trigger configurations
using a discriminated union pattern for type safety.

To add a new trigger:
1. Create a new config class extending BaseTriggerConfigData
2. Add a literal trigger_name field as the discriminator
3. Add the class to the TriggerConfigData union
"""

from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, Discriminator, Field


class BaseTriggerConfigData(BaseModel):
    """Base class for trigger-specific configuration."""

    pass


# =============================================================================
# CALENDAR TRIGGERS
# =============================================================================


class CalendarEventCreatedConfig(BaseTriggerConfigData):
    """Config for calendar_event_created trigger."""

    trigger_name: Literal["calendar_event_created"] = "calendar_event_created"
    calendar_ids: List[str] = Field(
        default=["primary"],
        description="Calendar IDs to monitor. Use ['all'] for all calendars.",
    )


class CalendarEventStartingSoonConfig(BaseTriggerConfigData):
    """Config for calendar_event_starting_soon trigger."""

    trigger_name: Literal["calendar_event_starting_soon"] = (
        "calendar_event_starting_soon"
    )
    calendar_ids: List[str] = Field(
        default=["primary"],
        description="Calendar IDs to monitor. Use ['all'] for all calendars.",
    )
    minutes_before_start: int = Field(
        default=10,
        ge=1,
        le=1440,
        description="Minutes before event start to trigger",
    )
    include_all_day: bool = Field(
        default=False, description="Whether to include all-day events"
    )


# =============================================================================
# GMAIL TRIGGERS
# =============================================================================


class GmailNewMessageConfig(BaseTriggerConfigData):
    """Config for gmail new message trigger."""

    trigger_name: Literal["gmail_new_message"] = "gmail_new_message"
    # Gmail triggers currently have no additional config


# =============================================================================
# DISCRIMINATED UNION - Add new configs here
# =============================================================================

TriggerConfigData = Annotated[
    Union[
        CalendarEventCreatedConfig,
        CalendarEventStartingSoonConfig,
        GmailNewMessageConfig,
    ],
    Discriminator("trigger_name"),
]

# Type alias for trigger names
TriggerName = Literal[
    "calendar_event_created",
    "calendar_event_starting_soon",
    "gmail_new_message",
]
