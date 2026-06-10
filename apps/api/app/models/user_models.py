from datetime import datetime
from enum import Enum
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class OnboardingPhase(str, Enum):
    """Tracks the current phase of user onboarding"""

    INITIAL = "initial"  # Name, profession, timezone entered
    PERSONALIZATION_PENDING = "personalization_pending"  # Waiting for bio, house, etc.
    PERSONALIZATION_COMPLETE = "personalization_complete"  # House, bio generated
    GETTING_STARTED = "getting_started"  # User clicked "Show me around"
    COMPLETED = "completed"  # All onboarding finished


class BioStatus(str, Enum):
    """Tracks the status of bio generation"""

    PENDING = "pending"  # Not yet started
    PROCESSING = "processing"  # Actively generating from memories
    COMPLETED = "completed"  # Successfully generated
    NO_GMAIL = "no_gmail"  # No Gmail connected, showing placeholder


class UserUpdateResponse(BaseModel):
    user_id: str = Field(..., description="Unique identifier for the user")
    name: str = Field(..., description="Name of the user")
    email: str = Field(..., description="Email address of the user")
    picture: str | None = Field(None, description="URL of the user's profile picture")
    updated_at: datetime | None = Field(None, description="Last update timestamp")


class OnboardingPreferences(BaseModel):
    profession: str | None = Field(
        None,
        description="User's profession or main area of focus",
    )
    response_style: str | None = Field(
        None,
        description="Preferred communication style: brief, detailed, casual, professional",
    )
    custom_instructions: str | None = Field(
        None, max_length=500, description="Custom instructions for the AI assistant"
    )
    # Removed timezone field - now only stored at user.timezone root level

    @field_validator("profession")
    @classmethod
    def validate_profession(cls, v):
        if v is not None and v != "":
            v = v.strip()
            if not v:
                raise ValueError("Profession cannot be empty")
            if len(v) > 50:
                raise ValueError("Profession must be 50 characters or less")
            return v
        # Return None for empty strings to normalize the data
        return None if v == "" else v

    @field_validator("response_style")
    @classmethod
    def validate_response_style(cls, v):
        if v is not None and v != "":
            valid_styles = {"brief", "detailed", "casual", "professional"}
            v = v.strip()
            # Allow custom response styles (anything that's not in the predefined list)
            if v not in valid_styles and len(v) == 0:
                raise ValueError("Response style cannot be empty")
            return v
        # Return None for empty strings to normalize the data
        return None if v == "" else v

    @field_validator("custom_instructions")
    @classmethod
    def validate_custom_instructions(cls, v):
        if v is not None and v != "":
            v = v.strip()
            if len(v) > 500:
                raise ValueError("Custom instructions must be 500 characters or less")
            return v
        # Return None for empty strings to normalize the data
        return None if v == "" else v


class ClarifyAnswer(BaseModel):
    """One answered no-Gmail clarify question, persisted on onboarding.clarify_answers."""

    id: str = Field(..., description="Question id — one of scope, blocker, constraint")
    kind: str = Field(..., description="scope / blocker / constraint")
    question: str = Field(..., description="Original question text")
    value: str | None = Field(
        None,
        max_length=500,
        description="User's answer; None means the question was skipped",
    )


class OnboardingRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="User's preferred name")
    profession: str = Field(..., min_length=1, max_length=50, description="User's profession")
    timezone: str | None = Field(
        None, description="User's detected timezone (e.g., 'America/New_York', 'UTC')"
    )
    focus: str | None = Field(
        None, max_length=500, description="User's current primary focus or goal"
    )
    clarify_answers: list[ClarifyAnswer] | None = Field(
        None,
        description="No-Gmail follow-up answers (scope/blocker/constraint)",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if not re.match(r"^[a-zA-Z\s\-\'\.]+$", v):
            raise ValueError(
                "Name can only contain letters, spaces, hyphens, apostrophes, and periods"
            )
        return v

    @field_validator("profession")
    @classmethod
    def validate_profession(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Profession cannot be empty")
        if not re.match(r"^[a-zA-Z\s\-\.]+$", v):
            raise ValueError("Profession can only contain letters, spaces, hyphens, and periods")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v):
        if v is not None and v.strip():
            import pytz

            v = v.strip()
            try:
                # Validate that it's a valid IANA timezone identifier
                pytz.timezone(v)
                return v
            except pytz.UnknownTimeZoneError:
                # Allow UTC as a special case
                if v.upper() == "UTC":
                    return "UTC"
                raise ValueError(
                    f"Invalid timezone '{v}'. Use IANA timezone identifiers like 'Asia/Kolkata', 'America/New_York', 'UTC'"
                )
        return v


class OnboardingResponse(BaseModel):
    success: bool = Field(..., description="Whether onboarding was successful")
    message: str = Field(..., description="Response message")
    user: dict[str, Any] | None = Field(None, description="Updated user data")


class OnboardingPhaseUpdateRequest(BaseModel):
    phase: OnboardingPhase = Field(..., description="The onboarding phase to transition to")

    @field_validator("phase")
    @classmethod
    def validate_phase_progression(cls, v):
        """Ensure phase values are valid"""
        # Phase validation is handled by the enum type
        # Additional business logic validation should be in the service layer
        return v
