from typing import ClassVar, Literal, TypedDict

from pydantic import BaseModel, Field

from app.models.user_models import OnboardingPhase
from app.models.workflow_models import WorkflowStep

# The four holo-card houses. The frontend types the same closed set.
House = Literal["frostpeak", "greenvale", "mistgrove", "bluehaven"]
HOUSES: list[House] = ["frostpeak", "greenvale", "mistgrove", "bluehaven"]


class WritingStyleExampleBlocks(BaseModel):
    """An example email split into the parts the onboarding card renders separately."""

    greeting: str = Field(
        default="",
        description=(
            "Greeting line on its own, e.g. 'Hey Sarah,' or 'Hi!'. "
            "Empty string if the observed style has no greeting habit."
        ),
    )
    body: list[str] = Field(
        min_length=1,
        description=(
            "One string per body paragraph (1-3 typical). Do NOT include greeting "
            "or sign-off. Do NOT put `\\n` inside a paragraph."
        ),
    )
    signoff: str = Field(
        default="",
        description=("Sign-off line, e.g. 'Best,' or 'Thanks,'. Empty string if none."),
    )
    name: str = Field(
        default="",
        description="Sender name on its own line. Empty string if none.",
    )


class WritingStyleProfile(BaseModel):
    """The learned writing style, plus the user's own edit of the summary if any."""

    summary: str
    example: WritingStyleExampleBlocks
    user_edited_summary: str | None = None


class SocialProfile(BaseModel):
    """One social account belonging to the user, as stored and sent to the client."""

    platform: str
    url: str


class EmailSummary(BaseModel):
    """An important email as the triage LLM returns it."""

    sender: str
    subject: str
    snippet: str = ""
    why_important: str


class TriageEmailSummary(BaseModel):
    """The fields of an important email that actually reach the client.

    Deliberately not :class:`EmailSummary`: both the persisted triage subdoc and
    the ``triage_ready`` WebSocket payload drop ``snippet``, and the frontend
    types exactly these three.

    Defaulted for the same reason as :class:`PersistedTriageSummary` — these
    entries are read back out of a persisted subdoc, and the write path always
    supplies all three, so the defaults only ever apply on read.
    """

    sender: str = ""
    subject: str = ""
    why_important: str = ""


class InboxTriage(BaseModel):
    """The whole inbox-scan result, as held in memory for the rest of onboarding."""

    total_scanned: int
    total_unread: int
    summary: str = ""
    important_emails: list[EmailSummary]
    patterns: list[str]


class PersistedTriageSummary(BaseModel):
    """``users.onboarding.triage_summary``.

    Written only by the onboarding pipeline's ``_persist_profiles`` and surfaced
    by ``GET /onboarding/personalization``.

    Every field defaults so that *any* subset of keys validates. This subdoc is
    read back from rows written by older versions of the pipeline, and what those
    versions wrote cannot be established from here — a missing key must degrade to
    an empty value, never turn the whole personalization fetch into a 500. The
    current writer always populates all five, so the defaults only apply on read.
    """

    total_scanned: int = 0
    total_unread: int = 0
    summary: str = ""
    patterns: list[str] = Field(default_factory=list)
    important_emails: list[TriageEmailSummary] = Field(default_factory=list)


class InboxTriageOutput(BaseModel):
    """Structured-output contract for the inbox-triage LLM call."""

    summary: str = Field(
        min_length=1,
        description="2-3 sentence overview of the inbox written conversationally to the user",
    )
    important_emails: list[EmailSummary] = Field(
        description="5-10 most important emails that need attention"
    )
    patterns: list[str] = Field(description="2-5 interesting patterns across the inbox")


class WritingStyleOutput(BaseModel):
    """Structured-output contract for the writing-style LLM call."""

    summary: str = Field(
        description=(
            "2-3 sentence writing style description capturing concrete observable patterns: "
            "how they greet, sign off, sentence length, formality, and any distinctive habits."
        )
    )
    example: WritingStyleExampleBlocks = Field(
        description=(
            "Example email written in the user's voice, broken into structured blocks. "
            "Must reflect the observed style — do not invent traits not seen in the emails."
        ),
    )


class HoloCardLLMOutput(BaseModel):
    """Structured-output contract for the holo-card LLM call."""

    personality_phrase: str = Field(
        description=(
            "Unique 2-3 word personality phrase capturing the user's essence. "
            "Poetic, metaphorical, and unexpected — never corporate buzzwords, "
            "generic descriptors, or obvious profession references. Examples of "
            "the right register: 'Midnight Architect', 'Velvet Rebel', 'Pattern "
            "Seeker', 'Quiet Thunder'."
        ),
    )
    user_bio: str = Field(
        description=(
            "Sassy, insightful 2-3 sentence bio in third person that makes the "
            "user think 'wow, how does GAIA know me so well?'. Calls out patterns "
            "and quirks, not job titles. NEVER use em dashes or en dashes — use "
            "commas, periods, colons, or parentheses instead."
        ),
    )


class WritingStyleExampleOutput(BaseModel):
    """Structured-output contract for regenerating the style example on its own."""

    example: WritingStyleExampleBlocks = Field(
        description=(
            "Example email matching the provided style summary, broken into structured blocks."
        ),
    )


class OwnedSocialProfile(BaseModel):
    """One profile the ownership-filter LLM claims belongs to the user.

    Both fields default to empty so a key the model omits degrades to a lookup
    miss (the profile is dropped) exactly as it did when this was a bare dict,
    instead of failing the whole structured-output call.
    """

    platform: str = Field(default="", description="Platform name, echoed from the candidate list")
    handle: str = Field(default="", description="Handle, echoed from the candidate list")


class SocialProfileFilterOutput(BaseModel):
    """Structured-output contract for the profile-ownership LLM call."""

    owned_profiles: list[OwnedSocialProfile] = Field(
        description="Profiles that belong to the user. Empty list if none."
    )


# --------------------------------------------------------------------- clarify


class ClarifyAnswerRecord(TypedDict, total=False):
    """``users.onboarding.clarify_answers`` as persisted by the pre-paid-flow
    onboarding submission. Read-only legacy data — nothing writes it now.

    A ``TypedDict``, not a model (Type Safety item 6): it is read straight off an
    already-persisted subdocument and only ever consumed in-process, so validating
    it would add a new failure mode on historical rows without adding safety, while
    a ``TypedDict`` stays a plain dict at runtime and mypy checks every key.
    """

    id: str
    kind: str
    question: str
    value: str | None


# ------------------------------------------------------- pipeline output shapes


class UserProfileMetadata(BaseModel):
    """Holo-card metadata derived from the user's account age."""

    account_number: int
    member_since: str


class ProfileCardDesign(BaseModel):
    """Randomized holo-card visuals."""

    house: House
    overlay_color: str
    overlay_opacity: int


# ------------------------------------------------------ websocket stage payloads


class StagePayload(BaseModel):
    """Base for the ``payload`` of an ``onboarding_stage`` WebSocket event."""

    # Whether a None field is dropped from the wire payload or sent as explicit
    # null. Both are load-bearing: a missing source_email means "no email", but
    # a null style_summary means "style learning ran and came back empty".
    omit_none_on_wire: ClassVar[bool] = False

    def to_wire(self) -> dict[str, object]:
        """The payload as it goes onto the WebSocket frame."""
        return self.model_dump(mode="json", exclude_none=self.omit_none_on_wire)


class StatusTextPayload(StagePayload):
    """Progress ping for a stage that is still running."""

    status_text: str


class WritingStyleReadyPayload(StagePayload):
    """Payload of the ``writing_style_ready`` stage event."""

    style_summary: str | None
    example: WritingStyleExampleBlocks | None


class SocialProfilesReadyPayload(StagePayload):
    """Payload of the ``social_profiles_ready`` stage event."""

    profiles: list[SocialProfile]


class TriageReadyPayload(StagePayload):
    """Payload of the ``triage_ready`` stage event."""

    total_scanned: int
    total_unread: int
    summary: str | None
    patterns: list[str]
    important_emails: list[TriageEmailSummary]


# ----------------------------------------------------------- endpoint responses


class OnboardingResetCounts(BaseModel):
    """What ``reset_onboarding`` tore down."""

    workflows_deleted: int
    todos_deleted: int
    conversation_deleted: int
    demo_conversations_deleted: int
    integrations_disconnected: int
    memories_cleared: int


class OnboardingResetResponse(OnboardingResetCounts):
    """Response body for the onboarding reset endpoint."""

    success: bool


class OnboardingPhaseUpdateResponse(BaseModel):
    """Response body for an onboarding phase update."""

    success: bool
    phase: OnboardingPhase
    message: str


class SaveWritingStyleResponse(BaseModel):
    """Response body for saving a user-edited writing style."""

    success: bool


class RegenerateWritingStyleExampleResponse(BaseModel):
    """Response body for regenerating the writing-style example."""

    example: WritingStyleExampleBlocks | None


class SaveSocialProfilesResponse(BaseModel):
    """Response body for confirming social profiles, carrying how many were kept."""

    success: bool
    saved: int


class PersonalizationWorkflow(BaseModel):
    """A suggested workflow as rendered by the onboarding cards."""

    id: str
    title: str
    description: str
    steps: list[WorkflowStep]


class PersonalizationWritingStyle(BaseModel):
    """The learned writing style as rendered by the onboarding cards."""

    style_summary: str
    example: WritingStyleExampleBlocks | None


class PersonalizationTodo(BaseModel):
    """A suggested todo as rendered by the onboarding cards."""

    id: str
    title: str
    description: str | None
    # TodoDocument.source_email is str | None but nothing in the backend writes
    # it, so this is always null — the todos_ready WebSocket event carries a
    # {sender, subject} object instead. Reconciling is a product change, not a fix.
    source_email: str | None


class PersonalizationResponse(BaseModel):
    """``GET /onboarding/personalization`` — the holo card plus every reveal the
    onboarding UI replays when the WebSocket stage events are missed."""

    # `str`, not OnboardingPhase, for the same reason as OnboardingStatusResponse,
    # and because the "no onboarding yet" default below is not an enum member.
    phase: str
    has_personalization: bool
    house: str
    personality_phrase: str
    user_bio: str
    account_number: int
    member_since: str
    overlay_color: str
    overlay_opacity: int
    suggested_workflows: list[PersonalizationWorkflow]
    name: str
    holo_card_id: str
    first_message_conversation_id: str | None
    first_message: str | None
    writing_style: PersonalizationWritingStyle | None
    social_profiles: list[SocialProfile] | None
    triage_summary: PersistedTriageSummary | None
    onboarding_todos: list[PersonalizationTodo] | None
