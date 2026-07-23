from datetime import datetime
from enum import Enum
import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.db.repositories.base import MongoDocument
from app.utils.timezone import is_valid_timezone

# Lowercased, bounded slug for request-supplied integration ids.
IntegrationSlug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
    ),
]


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
    def validate_profession(cls, v: str | None) -> str | None:
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
    def validate_response_style(cls, v: str | None) -> str | None:
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
    def validate_custom_instructions(cls, v: str | None) -> str | None:
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
    selected_integrations: list[IntegrationSlug] | None = Field(
        None,
        max_length=25,
        description="Integration slugs the user selected during onboarding.",
    )
    defer_workflows: bool = Field(
        default=False,
        description=(
            "Gmail-path split: run inbox intelligence immediately and defer "
            "workflow creation until the user submits selected integrations."
        ),
    )

    @field_validator("selected_integrations")
    @classmethod
    def dedupe_integrations(cls, v: list[str] | None) -> list[str] | None:
        return _dedupe_slugs(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
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
    def validate_profession(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Profession cannot be empty")
        if not re.match(r"^[a-zA-Z\s\-\.]+$", v):
            raise ValueError("Profession can only contain letters, spaces, hyphens, and periods")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            v = v.strip()
            # Canonical validation: accepts IANA names, ±HH:MM offsets, and UTC.
            if not is_valid_timezone(v):
                raise ValueError(
                    f"Invalid timezone '{v}'. Use IANA timezone identifiers like 'Asia/Kolkata', 'America/New_York', 'UTC'"
                )
            return v
        return v


class OnboardingResponse(BaseModel):
    success: bool = Field(..., description="Whether onboarding was successful")
    message: str = Field(..., description="Response message")
    user: dict[str, Any] | None = Field(None, description="Updated user data")


class OnboardingIntegrationsRequest(BaseModel):
    selected_integrations: list[IntegrationSlug] = Field(
        default_factory=list,
        max_length=25,
        description="Integration slugs the user selected during onboarding.",
    )

    @field_validator("selected_integrations")
    @classmethod
    def dedupe_integrations(cls, v: list[str]) -> list[str]:
        return _dedupe_slugs(v) or []


class OnboardingIntegrationsStatus(str, Enum):
    """Outcome of submitting onboarding integration selections."""

    QUEUED = "queued"  # Selections saved; workflows-phase job enqueued.
    ALREADY_COMPLETE = "already_complete"  # Onboarding already finished (replay).
    ALREADY_RUNNING = "already_running"  # Workflows job already in flight (replay).


class OnboardingIntegrationsResponse(BaseModel):
    success: bool = Field(..., description="Whether the submission was accepted")
    status: OnboardingIntegrationsStatus = Field(
        ..., description="Outcome of persisting the selected integrations"
    )


class OnboardingPhaseUpdateRequest(BaseModel):
    phase: OnboardingPhase = Field(..., description="The onboarding phase to transition to")

    @field_validator("phase")
    @classmethod
    def validate_phase_progression(cls, v: OnboardingPhase) -> OnboardingPhase:
        """Ensure phase values are valid"""
        # Phase validation is handled by the enum type
        # Additional business logic validation should be in the service layer
        return v


def _dedupe_slugs(v: list[str] | None) -> list[str] | None:
    # Order-preserving dedupe: a user can select the same integration twice
    # (e.g. via a chip and a mention). We keep the first occurrence so the
    # selection order — which downstream workflow generation treats as priority
    # — is stable, rather than using set() which would scramble it.
    if not v:
        return v
    seen: set[str] = set()
    out: list[str] = []
    for slug in v:
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


class UserDocument(MongoDocument):
    """A user as stored in MongoDB.

    ``extra="allow"`` (not the usual ``ignore``): the auth layer's
    ``build_user_context`` spreads the *entire* user document into
    ``request.state.user``, and ``GET /me`` and the onboarding endpoints spread it
    straight into their HTTP responses. Dropping undeclared fields here would
    silently strip them from those payloads with no error anywhere. Declared
    fields are all Optional so a legacy/partial row never fails an auth read.

    The write side is now a closed set — every writer routes through
    ``UserRepository`` and every field it can set is declared (the arbitrary
    ``set_active_job`` field is an ``onboarding.*`` path), so no *new* undeclared
    field can appear. Tightening to ``ignore`` is still blocked on the read side:
    it would drop whatever historical fields production rows carry, and that
    inventory cannot be established from a dev sample. Flip it only after scanning
    the production collection for undeclared top-level fields.
    """

    model_config = ConfigDict(extra="allow")

    email: str | None = None
    name: str | None = None
    picture: str | None = None
    timezone: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_active_at: datetime | None = None
    # These nested subdocuments are schemaless-ish and read via chained `.get`
    # across many callers; typed as Any (not a sub-model) per this wave's scope.
    onboarding: dict[str, Any] | None = None
    provider_metadata: dict[str, Any] | None = None
    hil_preferences: dict[str, Any] | None = None
    notification_channel_prefs: dict[str, Any] | None = None
    platform_links: dict[str, Any] | None = None
    platform_links_connected_at: dict[str, Any] | None = None
    starred_voice_ids: list[str] | None = None
    selected_voice_id: str | None = None
    # Profile / billing display name used by the payments emails.
    first_name: str | None = None
    # Email-to-memory processing markers (helpers/agents).
    email_memory_processed: bool | None = None
    email_memory_processed_at: datetime | None = None
    email_memory_count: int | None = None
    integration_scan_states: dict[str, Any] | None = None
    # Lifecycle / re-engagement markers (workers).
    is_active: bool | None = None
    memory_backfilled: datetime | None = None
    last_inactive_email_sent: datetime | None = None
    inactive_email_count: int | None = None


class UserUpdate(BaseModel):
    """Flat top-level user fields updatable through the generic ``update`` path.

    Nested ``onboarding.*`` / ``platform_links.*`` changes go through the
    repository's named methods, not this model.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    timezone: str | None = None
    picture: str | None = None


def user_to_legacy_dict(user: UserDocument) -> dict[str, Any]:
    """Raw-style user dict (string ``_id``) for consumers not yet migrated off
    the pre-repository dict shape — auth context building, bot resolution. A
    transitional bridge; removed once those consumers take ``UserDocument``."""
    return {**user.model_dump(exclude={"id"}, exclude_none=True), "_id": user.id}
