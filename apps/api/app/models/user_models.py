from collections.abc import Mapping
from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.repositories.base import MongoDocument
from app.models.first_steps_models import FirstStepsState
from app.schemas.common import ResponseModel
from app.utils.timezone import is_valid_timezone

# Shared field doc for the `message` field on the success/message response models.
_RESPONSE_MESSAGE_DESC = "Response message"

#: Onboarding Q2 "Something else": one short line, sent verbatim in the first message.
OTHER_NEED_MAX_LENGTH = 120
#: Q2 is "pick up to three": every extra pick dilutes the first thread's opener and
#: the bot's first message down to a feature list. Mirrored in the web constants.
NEEDS_MAX_SELECTION = 3
#: Q1 is answered in sentences, not job titles, so this is a "one line" cap,
#: not a "job title" one. Mirrored by PROFESSION_MAX_LENGTH in the web
#: onboarding constants — the field's maxLength must match or typing goes dead.
PROFESSION_MAX_LENGTH = 80


def clean_profession(value: str) -> str:
    """One rule for every surface that stores a job title.

    Q1's "Other" field asks "What do you do?", and people answer in sentences
    ("I'm a founder, building a startup"), so punctuation and digits are fine.
    What is not fine is a second line: the text is spoken back inside GAIA's
    first message. The completion request and the preferences PATCH once had
    different rules here, and the wizard hung on the stricter one.
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Profession cannot be empty")
    if len(cleaned) > PROFESSION_MAX_LENGTH:
        raise ValueError(f"Profession must be {PROFESSION_MAX_LENGTH} characters or less")
    if any(ch.isspace() and ch != " " for ch in cleaned) or not any(ch.isalpha() for ch in cleaned):
        raise ValueError("Profession must be one line of words")
    return cleaned


def _known_enum_value_or_unset(value: object, enum: type[Enum]) -> object:
    """A stored value that is a member of ``enum`` today, else ``None``.

    A historical row with a value outside today's enum is an unset field, not a
    failed auth read; only our own code writes these, but the read must never
    depend on that. Enum members are ``str``, so they pass as themselves, and a
    dict or an int in the slot reads as unset rather than raising.

    Each field is checked against its OWN enum. One merged set of every known
    value looks equivalent and is not: ``OnboardingPhase`` and ``BioStatus``
    both carry ``"completed"``, so a value belonging to the other enum passes
    the guard and then fails Pydantic's coercion for the field's real type —
    producing exactly the failed read the guard exists to prevent.
    """
    return value if isinstance(value, str) and value in {m.value for m in enum} else None


def clean_other_need(value: str | None) -> str | None:
    """Whitespace-only is "nothing typed", not a need."""
    if value is None:
        return None
    return value.strip() or None


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
    """The pains the user handed GAIA during onboarding (Q2, up to three picks).

    Six are shown to everyone; the rest come in pairs, one pair per Q1 role, and
    only that role sees its pair (``ROLE_NEEDS``). Each value is a different job
    GAIA can start on, so the picks carry signal into the first thread, the
    bot opener and the comms playbooks.
    """

    # Shared
    INBOX = "inbox"
    CALENDAR = "calendar"
    MORNINGS = "mornings"
    REMINDERS = "reminders"
    GRUNT_WORK = "grunt_work"
    TOOLS = "tools"
    # Per role
    FOUNDER_TEAM_UPDATES = "founder_team_updates"
    FOUNDER_COMPETITORS = "founder_competitors"
    EXECUTIVE_REPORTS = "executive_reports"
    EXECUTIVE_DECISIONS = "executive_decisions"
    SALES_LEADS = "sales_leads"
    SALES_CALL_RESEARCH = "sales_call_research"
    PRODUCT_FEEDBACK = "product_feedback"
    PRODUCT_SPECS = "product_specs"
    MARKETING_CONTENT = "marketing_content"
    MARKETING_REPORTS = "marketing_reports"
    ENGINEERING_PRS = "engineering_prs"
    ENGINEERING_NOTIFICATIONS = "engineering_notifications"
    FINANCE_NUMBERS = "finance_numbers"
    FINANCE_REPORTS = "finance_reports"
    CREATIVE_REVISIONS = "creative_revisions"
    CREATIVE_DEADLINES = "creative_deadlines"
    STUDENT_ASSIGNMENTS = "student_assignments"
    STUDENT_EXAMS = "student_exams"


#: The two role-specific pains each Q1 slug unlocks. Keys are the
#: ``professionOptions`` values in apps/web onboarding constants; a typed
#: profession ("other") unlocks none. Mirrored one-for-one by
#: ``roleNeedOptions`` on the web.
ROLE_NEEDS: dict[str, tuple[OnboardingNeed, OnboardingNeed]] = {
    "founder": (OnboardingNeed.FOUNDER_TEAM_UPDATES, OnboardingNeed.FOUNDER_COMPETITORS),
    "executive": (OnboardingNeed.EXECUTIVE_REPORTS, OnboardingNeed.EXECUTIVE_DECISIONS),
    "sales": (OnboardingNeed.SALES_LEADS, OnboardingNeed.SALES_CALL_RESEARCH),
    "product": (OnboardingNeed.PRODUCT_FEEDBACK, OnboardingNeed.PRODUCT_SPECS),
    "marketing": (OnboardingNeed.MARKETING_CONTENT, OnboardingNeed.MARKETING_REPORTS),
    "engineering": (OnboardingNeed.ENGINEERING_PRS, OnboardingNeed.ENGINEERING_NOTIFICATIONS),
    "finance": (OnboardingNeed.FINANCE_NUMBERS, OnboardingNeed.FINANCE_REPORTS),
    "creative": (OnboardingNeed.CREATIVE_REVISIONS, OnboardingNeed.CREATIVE_DEADLINES),
    "student": (OnboardingNeed.STUDENT_ASSIGNMENTS, OnboardingNeed.STUDENT_EXAMS),
}

_NEED_ROLE: dict[OnboardingNeed, str] = {
    need: role for role, pair in ROLE_NEEDS.items() for need in pair
}


def role_of_need(need: OnboardingNeed) -> str | None:
    """The Q1 role a need belongs to, or ``None`` for the six everyone sees."""
    return _NEED_ROLE.get(need)


class OnboardingPreferences(BaseModel):
    profession: str | None = Field(
        # `default=` by keyword: mypy's dataclass-transform support does not read
        # a positional default, so `Field(None, ...)` typed as REQUIRED while the
        # runtime defaulted it — a caller omitting it was red for mypy and green
        # for pydantic. The keyword form is the one both agree on.
        default=None,
        description="User's profession or main area of focus",
    )
    needs: list[OnboardingNeed] | None = Field(
        default=None,
        max_length=NEEDS_MAX_SELECTION,
        description="The jobs the user handed GAIA (onboarding Q2, up to three)",
    )

    @field_validator("needs", mode="before")
    @classmethod
    def keep_the_needs_that_still_exist(cls, v: object) -> object:
        """A stored document must always load: users who onboarded before the
        pain-based Q2 hold values the enum no longer has and up to seven picks.
        Unknown values are dropped and the list is cut to the cap, first picks
        first. The strict check lives on ``OnboardingRequest``."""
        if not isinstance(v, list):
            return v
        known = {need.value for need in OnboardingNeed}
        kept = [need for need in dict.fromkeys(v) if need in known]
        return kept[:NEEDS_MAX_SELECTION]

    response_style: str | None = Field(
        default=None,
        description="Preferred communication style: brief, detailed, casual, professional",
    )
    other_need: str | None = Field(
        default=None,
        max_length=OTHER_NEED_MAX_LENGTH,
        description="What the user typed under 'Something else' in onboarding Q2, verbatim",
    )
    custom_instructions: str | None = Field(
        default=None, max_length=500, description="Custom instructions for the AI assistant"
    )
    # Removed timezone field - now only stored at user.timezone root level

    @field_validator("other_need")
    @classmethod
    def validate_other_need(cls, v: str | None) -> str | None:
        return clean_other_need(v)

    @field_validator("profession")
    @classmethod
    def validate_profession(cls, v: str | None) -> str | None:
        # Empty string normalises to None: "unset", not "set to nothing".
        if v is None or v == "":
            return None
        return clean_profession(v)

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


class OnboardingRequest(BaseModel):
    """The onboarding submission — Q1 (profession) and Q2 (needs).

    The name is derived from the email server-side, so it is not submitted;
    nothing else is generated at onboarding, so nothing else is collected.
    """

    profession: str = Field(
        ..., min_length=1, max_length=PROFESSION_MAX_LENGTH, description="User's profession"
    )
    needs: list[OnboardingNeed] = Field(
        default_factory=list,
        max_length=NEEDS_MAX_SELECTION,
        description="The jobs the user handed GAIA (onboarding Q2, up to three)",
    )
    other_need: str | None = Field(
        None,
        max_length=OTHER_NEED_MAX_LENGTH,
        description="What the user typed under 'Something else' in Q2, verbatim",
    )
    timezone: str | None = Field(
        None, description="User's detected timezone (e.g., 'America/New_York', 'UTC')"
    )

    @field_validator("needs", mode="before")
    @classmethod
    def dedupe_needs(cls, v: object) -> object:
        """First-occurrence order, no duplicates — the UI is a toggle grid, so
        a repeated value is a client bug, not a meaningful selection. Runs
        before the pick cap so a double tap counts as one pick, not three."""
        if isinstance(v, list):
            return list(dict.fromkeys(v))
        return v

    @field_validator("profession")
    @classmethod
    def validate_profession(cls, v: str) -> str:
        return clean_profession(v)

    @field_validator("other_need")
    @classmethod
    def validate_other_need(cls, v: str | None) -> str | None:
        return clean_other_need(v)

    @model_validator(mode="after")
    def require_an_answer_to_q2(self) -> "OnboardingRequest":
        # Q2 is answered by a pick or by typed words; an empty Q2 leaves the
        # first message with nothing to ask about.
        if not self.needs and not self.other_need:
            raise ValueError("Pick at least one need or say it in your own words")
        return self

    @model_validator(mode="after")
    def role_needs_match_the_profession(self) -> "OnboardingRequest":
        # A role pair is only ever shown to its role, so a mismatch is a client
        # bug or a replayed request, and the playbooks would coach the wrong job.
        for need in self.needs:
            role = role_of_need(need)
            if role is not None and role != self.profession.lower():
                raise ValueError(f"{need.value} is only offered to {role}")
        return self

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


class LogoutResponse(ResponseModel):
    """``POST /user/logout``: where the client sends the browser next."""

    logout_url: str | None = Field(None, description="Identity-provider logout URL to redirect to")


class OnboardingResponse(ResponseModel):
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
    chat_channel_priority: list[str] | None
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
    # Activation checklist collapse (first_steps_service).
    first_steps: FirstStepsState | None
    # Signup delivery stamps (signup_email_tasks) — absent while still owed.
    welcome_email_sent_at: datetime | None
    marketing_contact_added_at: datetime | None


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


class OnboardingSubdocument(BaseModel):
    """``users.onboarding`` — the wizard's answers plus everything the Gmail
    personalization pipeline stamps on the user.

    ``extra="allow"``: production rows carry keys written by onboarding flows
    that no longer exist, and dropping them here would silently strip them from
    ``GET /me`` (which spreads the document) and from any read-modify-write.
    Declared fields are what ``app/`` actually reads, so a reader is a typo-proof
    attribute access instead of a ``.get()`` that can never fail.

    The loosely-typed fields (``writing_style``, ``triage_summary``,
    ``social_profiles``, ``clarify_answers``) stay mappings on purpose: they are
    read back from rows written by older pipeline versions and are validated into
    their real models at the point of use (``PersistedTriageSummary`` and
    friends), so validating them here would turn a historical row into a failed
    auth read.
    """

    model_config = ConfigDict(extra="allow")

    # Wizard state.
    completed: bool = False
    completed_at: datetime | None = None
    phase: OnboardingPhase | None = None
    preferences: OnboardingPreferences | None = None
    focus: str = ""
    clarify_answers: list[dict[str, Any]] = Field(default_factory=list)

    # Seeded conversations, kept so a reset can tear them down again.
    first_message_conversation_id: str | None = None
    getting_started_conversation_id: str | None = None
    holo_conversation_id: str | None = None
    first_message: str | None = None

    # Gmail personalization pipeline.
    gmail_personalization_at: datetime | None = None
    bio_status: BioStatus | None = None
    writing_style: dict[str, Any] | None = None
    triage_summary: dict[str, Any] | None = None
    social_profiles: list[dict[str, Any]] = Field(default_factory=list)
    suggested_workflows: list[str] = Field(default_factory=list)

    # Holo card.
    house: str | None = None
    personality_phrase: str | None = None
    user_bio: str = ""
    account_number: int | None = None
    member_since: str | None = None
    overlay_color: str = "rgba(0,0,0,0)"
    overlay_opacity: int = 40

    @field_validator("phase", mode="before")
    @classmethod
    def an_unknown_phase_reads_as_unset(cls, value: object) -> object:
        """A stored ``phase`` outside today's enum is an unset field, not a failed read."""
        return _known_enum_value_or_unset(value, OnboardingPhase)

    @field_validator("bio_status", mode="before")
    @classmethod
    def an_unknown_bio_status_reads_as_unset(cls, value: object) -> object:
        """The same guard for ``bio_status``, against its own enum."""
        return _known_enum_value_or_unset(value, BioStatus)

    @field_validator("preferences", mode="before")
    @classmethod
    def a_non_mapping_preferences_blob_reads_as_unset(cls, value: object) -> object:
        """``onboarding.preferences`` is an untyped blob in stored rows: a string
        or a list there must read as "no preferences", not fail the whole user
        read. Typing the field moved that blast radius from one account
        projection to every authenticated request, so the leniency has to live
        here."""
        if value is None or isinstance(value, (OnboardingPreferences, Mapping)):
            return value
        return None

    @field_validator("preferences", mode="before")
    @classmethod
    def a_stored_profession_todays_rules_reject_reads_as_unset(cls, value: object) -> object:
        """A profession the input rules would refuse today is an unset field, not
        a failed auth read.

        ``OnboardingPreferences`` is both this stored subdocument's type and the
        request body of ``PATCH /preferences``, so every tightening of
        ``clean_profession`` applies retroactively: it re-judges rows the older,
        laxer validator already accepted. When it refuses one, ``_to_model``
        raises on the single-document read (``base.py``'s lenient guard covers
        only the list read), ``authenticate_workos_session`` catches it and
        returns an empty ``user_info``, and the caller is 401'd — WorkOS says they
        are signed in, we say they are not, and signing in again lands in the same
        loop with no self-service fix. Dropping the value keeps the account
        readable; the write path stays strict, so nobody can type one of these in.
        """
        if not isinstance(value, Mapping):
            return value
        stored = value.get("profession")
        if stored is None:
            return value
        if isinstance(stored, str):
            try:
                clean_profession(stored)
            except ValueError:
                # ValueError is clean_profession's only failure signal, and a
                # refused stored value is exactly the case handled here.
                pass
            else:
                return value
        # Anything that is not readable text drops out: a non-str never reaches
        # clean_profession at all, because ``profession: str | None`` rejects it
        # at the type level first and fails the same read this guard exists to
        # keep alive.
        return {**value, "profession": None}


class UserDocument(MongoDocument):
    """A user as stored in MongoDB.

    ``extra="allow"`` (not the usual ``ignore``): the auth layer's
    ``build_user_context`` spreads the *entire* user document into
    ``request.state.user``, and ``GET /me`` and the onboarding endpoints spread it
    straight into their HTTP responses. Dropping undeclared fields here would
    silently strip them from those payloads with no error anywhere. Declared
    fields are all Optional so a legacy/partial row never fails an auth read.

    The write side is now a closed set — every writer routes through
    ``UserRepository`` and every field it can set is declared, so no *new*
    undeclared field can appear. Tightening to ``ignore`` is still blocked on the read side:
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
    onboarding: OnboardingSubdocument | None = None
    # These nested subdocuments are schemaless-ish and read via chained `.get`
    # across many callers; typed as Any (not a sub-model) per this wave's scope.
    provider_metadata: dict[str, Any] | None = None
    hil_preferences: dict[str, Any] | None = None
    notification_channel_prefs: dict[str, Any] | None = None
    platform_links: dict[str, Any] | None = None
    platform_links_connected_at: dict[str, Any] | None = None
    # Order in which a proactive message picks its ONE chat platform; unset
    # means DEFAULT_CHAT_CHANNEL_PRIORITY.
    chat_channel_priority: list[str] | None = None
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
    # Activation checklist collapse (first_steps_service).
    first_steps: FirstStepsState | None = None
    # Signup's two outbound ESP deliveries, stamped when each one lands (see
    # app/workers/tasks/signup_email_tasks.py). These attribute names must keep
    # matching the values of ``constants.email.SignupDelivery``, which is what
    # the repository and the recovery sweep address them by. A missing stamp
    # means the delivery is still owed; a dev-minted user is owed neither and is
    # stamped at creation so the sweep never mails a seeded account.
    welcome_email_sent_at: datetime | None = None
    marketing_contact_added_at: datetime | None = None


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
    # The pre-relocation holo-card conversation. Still served because users who
    # ran that flow carry it; nothing writes it any more.
    first_message_conversation_id: str | None
    # The "Getting started" conversation seeded at completion — what the web
    # redirects into once the wizard closes.
    getting_started_conversation_id: str | None = None


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
    first_steps: FirstStepsState | None = None


class PersonalizationBundle(BaseModel):
    """The holo-card fields the Gmail pipeline generates and persists in one write."""

    house: str
    personality_phrase: str
    user_bio: str
    bio_status: BioStatus
    account_number: int
    member_since: str
    overlay_color: str
    overlay_opacity: int


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
