from datetime import datetime
from enum import Enum, StrEnum
import re
from typing import Annotated, Any, TypedDict

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

# Shared field doc for the `message` field on the success/message response models.
_RESPONSE_MESSAGE_DESC = "Response message"


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


class UpdateTimezoneResponse(BaseModel):
    success: bool = Field(..., description="Whether the timezone update succeeded")
    message: str = Field(..., description=_RESPONSE_MESSAGE_DESC)
    timezone: str = Field(..., description="The timezone that was set")


class OnboardingNeed(StrEnum):
    """What the user asked GAIA for during onboarding (Q2, multi-select)."""

    INBOX = "inbox"
    CALENDAR = "calendar"
    BRIEFINGS = "briefings"
    TODOS = "todos"
    MEMORY = "memory"
    RESEARCH = "research"
    AUTOMATION = "automation"
    REACH = "reach"


class OnboardingPreferences(BaseModel):
    profession: str | None = Field(
        None,
        description="User's profession or main area of focus",
    )
    needs: list[OnboardingNeed] | None = Field(
        None,
        description="What the user wants GAIA to help with (onboarding Q2)",
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
    message: str = Field(..., description=_RESPONSE_MESSAGE_DESC)
    user: dict[str, Any] | None = Field(None, description="Updated user data")


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


class AuthenticatedUser(TypedDict, total=False):
    """``request.state.user`` — what every ``Depends(get_current_user)`` yields.

    A ``TypedDict``, not a ``BaseModel``, on purpose (Type Safety item 6): this
    shape never crosses a validation boundary — ``build_user_context`` assembles
    it in-process from an already-validated ``UserDocument`` — and ~205 call
    sites read it with ``user["user_id"]``. A ``TypedDict`` is still a plain dict
    at runtime, so those keep working untouched while mypy starts checking every
    key; swapping to a model would have been a behaviour change (item 13) for no
    extra safety.

    ``total=False`` because the auth paths genuinely populate different subsets:
    a WorkOS session sets none of the flags, the agent-token path sets
    ``impersonated``, bots set ``bot_authenticated``, the dev bypass sets
    ``dev_bypass``, and the legacy bot dict carries ``_id`` where the rest carry
    ``user_id``. Fields mirror ``UserDocument`` because ``build_user_context``
    spreads the whole document.
    """

    # Auth context layered on by build_user_context()/user_to_legacy_dict().
    user_id: str
    auth_provider: str
    impersonated: bool
    bot_authenticated: bool
    dev_bypass: bool
    is_agent_token: bool
    # The bot/legacy path carries the raw Mongo id instead of `user_id`.
    _id: str

    # Spread from UserDocument — see that class for why these stay loose.
    email: str | None
    name: str | None
    picture: str | None
    timezone: str | None
    created_at: datetime | None
    updated_at: datetime | None
    last_active_at: datetime | None
    onboarding: dict[str, Any] | None
    provider_metadata: dict[str, Any] | None
    hil_preferences: dict[str, Any] | None
    notification_channel_prefs: dict[str, Any] | None
    platform_links: dict[str, Any] | None
    platform_links_connected_at: dict[str, Any] | None
    starred_voice_ids: list[str] | None
    selected_voice_id: str | None
    first_name: str | None
    email_memory_processed: bool | None
    email_memory_processed_at: datetime | None
    email_memory_count: int | None
    integration_scan_states: dict[str, Any] | None
    is_active: bool | None
    memory_backfilled: datetime | None
    last_inactive_email_sent: datetime | None
    inactive_email_count: int | None
    # Usage-limit upsell email dedupe + activity badge tier (usage system).
    last_limit_email_sent: datetime | None
    highest_activity_tier: str | None
    highest_activity_tier_at: datetime | None
    # Nurture email sequence state (workers) — completed_steps + send history.
    nurture: dict[str, Any] | None


class PlatformLinkRecord(TypedDict, total=False):
    """One ``users.platform_links.{platform}`` entry — the bot-account link.

    A ``TypedDict``, not a model (Type Safety item 6): it is written and read
    in-process against an already-persisted subdocument, and the read path has to
    keep tolerating legacy rows that stored a bare id instead of this mapping, so
    validating it would add a failure mode without adding safety. ``total=False``
    because only ``id`` is always written — ``username``/``display_name`` are
    stored only when the platform's profile supplied them.
    """

    id: str
    username: str
    display_name: str


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
    # Usage-limit upsell email dedupe (1/week — see send_limit_reached_email).
    last_limit_email_sent: datetime | None = None
    # Best activity-badge tier ever reached (monotonic; drives first-time
    # promotion emails — see usage_activity.sync_activity_tiers).
    highest_activity_tier: str | None = None
    highest_activity_tier_at: datetime | None = None
    # Nurture email sequence state (workers): completed_steps + send history.
    nurture: dict[str, Any] | None = None


class OnboardingStatusResponse(BaseModel):
    """``get_user_onboarding_status()``'s processed shape.

    Lives here rather than in ``onboarding_models`` because it embeds
    ``OnboardingPreferences`` (above) and is embedded by
    ``AuthenticatedUserResponse`` (below) — defining it there would make
    ``user_models`` import ``onboarding_models``, which already imports back.
    """

    completed: bool
    completed_at: datetime | None
    # `str`, not OnboardingPhase: this is whatever is persisted, and the only
    # consumer (mobile) treats an error response as "onboarding complete" — so a
    # validation failure on an unrecognised historical value would silently skip
    # a user past onboarding. A loose string is the safer honest type here.
    phase: str | None
    preferences: OnboardingPreferences
    first_message_conversation_id: str | None


class AuthenticatedUserResponse(BaseModel):
    """The full ``GET /me`` payload.

    ``build_user_context()`` (``app/utils/auth_utils.py``) spreads the entire
    ``UserDocument`` into ``request.state.user`` (see that class's docstring)
    plus a handful of auth-context fields layered on top: ``user_id``
    (replacing ``_id``), ``auth_provider``, and per-auth-path flags present on
    only *some* paths — a plain WorkOS session sets none of them, the agent
    token path sets ``impersonated``, bots set ``bot_authenticated``, and the
    dev bypass sets ``dev_bypass``. This model mirrors ``UserDocument``'s
    declared fields at the point where the endpoint returns them, rather than
    subclassing it, so the DB document's shape and this response's shape can
    evolve independently. ``extra="allow"`` for the same reason
    ``UserDocument`` has it: undeclared historical fields on the document
    still need to reach this response. ``onboarding`` holds
    ``get_user_onboarding_status()``'s processed shape, not the raw
    ``UserDocument.onboarding`` blob it overwrites.
    """

    model_config = ConfigDict(extra="allow")

    message: str
    user_id: str
    auth_provider: str
    impersonated: bool | None = None
    bot_authenticated: bool | None = None
    dev_bypass: bool | None = None
    onboarding: OnboardingStatusResponse

    email: str | None = None
    name: str | None = None
    picture: str | None = None
    timezone: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_active_at: datetime | None = None
    provider_metadata: dict[str, Any] | None = None
    hil_preferences: dict[str, Any] | None = None
    notification_channel_prefs: dict[str, Any] | None = None
    platform_links: dict[str, Any] | None = None
    platform_links_connected_at: dict[str, Any] | None = None
    starred_voice_ids: list[str] | None = None
    selected_voice_id: str | None = None
    first_name: str | None = None
    email_memory_processed: bool | None = None
    email_memory_processed_at: datetime | None = None
    email_memory_count: int | None = None
    integration_scan_states: dict[str, Any] | None = None
    is_active: bool | None = None
    memory_backfilled: datetime | None = None
    last_inactive_email_sent: datetime | None = None
    inactive_email_count: int | None = None


class HoloCardOnboardingFields(BaseModel):
    """The subset of ``UserDocument.onboarding`` the holo-card endpoint reads.

    ``UserDocument.onboarding`` stays ``dict[str, Any]`` (see its field comment
    in ``UserDocument``) because it's read via chained ``.get()`` across many
    other callers with different shape needs, several of which are under
    active, unrelated development right now -- widening that shared field is
    real scope, not this endpoint's. This model validates only the fields
    this one endpoint actually consumes, at the point of use, so the endpoint
    itself never guesses through ``.get()``.
    """

    house: str | None = None
    personality_phrase: str | None = None
    user_bio: str | None = None
    account_number: int | None = None
    member_since: str | None = None
    overlay_color: str = "rgba(0,0,0,0)"
    overlay_opacity: int = 40


class UpdateHoloCardColorsResponse(BaseModel):
    """Response for a holo-card overlay colour update, echoing the stored values."""

    success: bool = Field(..., description="Whether the update succeeded")
    message: str = Field(..., description=_RESPONSE_MESSAGE_DESC)
    overlay_color: str = Field(..., description="Overlay color that was stored")
    overlay_opacity: int = Field(..., description="Overlay opacity that was stored (0-100)")


class PublicHoloCardResponse(BaseModel):
    """Public-facing subset of a user's profile, keyed by user id (``card_id``).

    Deliberately excludes everything else on ``UserDocument`` (email, workflows,
    integration state, etc.) — this endpoint is unauthenticated.
    """

    house: str | None = Field(None, description="User's chosen onboarding house")
    personality_phrase: str | None = Field(
        None, description="Personality phrase generated during onboarding"
    )
    user_bio: str | None = Field(None, description="User's onboarding bio")
    account_number: int = Field(..., description="Sequential account number")
    member_since: str = Field(..., description="Formatted account creation date")
    name: str | None = Field(None, description="User's display name")
    overlay_color: str = Field("rgba(0,0,0,0)", description="Holo card overlay color")
    overlay_opacity: int = Field(40, description="Holo card overlay opacity (0-100)")


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
