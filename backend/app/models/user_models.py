import re
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="New name for the user")


class UserUpdateResponse(BaseModel):
    user_id: str = Field(..., description="Unique identifier for the user")
    name: str = Field(..., description="Name of the user")
    email: str = Field(..., description="Email address of the user")
    picture: Optional[str] = Field(
        None, description="URL of the user's profile picture"
    )
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    selected_model: Optional[str] = Field(
        None, description="ID of the user's selected AI model"
    )


class OnboardingPreferences(BaseModel):
    profession: Optional[str] = Field(
        None,
        description="User's profession or main area of focus",
    )
    response_style: Optional[str] = Field(
        None,
        description="Preferred communication style: brief, detailed, casual, professional",
    )
    custom_instructions: Optional[str] = Field(
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


class OnboardingData(BaseModel):
    completed: bool = Field(
        default=False, description="Whether onboarding is completed"
    )
    completed_at: Optional[datetime] = Field(
        None, description="Timestamp when onboarding was completed"
    )
    preferences: Optional[OnboardingPreferences] = Field(
        None, description="User's onboarding preferences"
    )
    house: Optional[str] = Field(None, description="Assigned house name")
    personality_phrase: Optional[str] = Field(
        None, description="LLM-generated personality phrase"
    )
    user_bio: Optional[str] = Field(None, description="LLM-generated bio paragraph")
    suggested_workflows: Optional[list[str]] = Field(
        default_factory=list, description="Workflow IDs suggested via RAG"
    )


class OnboardingRequest(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=100, description="User's preferred name"
    )
    profession: str = Field(
        ..., min_length=1, max_length=50, description="User's profession"
    )
    timezone: Optional[str] = Field(
        None, description="User's detected timezone (e.g., 'America/New_York', 'UTC')"
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
            raise ValueError(
                "Profession can only contain letters, spaces, hyphens, and periods"
            )
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
    user: Optional[Dict[str, Any]] = Field(None, description="Updated user data")
