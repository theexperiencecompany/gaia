from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from app.models.user_models import OnboardingPhase
from app.models.workflow_models import IntegrationRef, TriggerType, WorkflowStep

# The four holo-card houses. The frontend types the same closed set.
House = Literal["frostpeak", "greenvale", "mistgrove", "bluehaven"]
HOUSES: list[House] = ["frostpeak", "greenvale", "mistgrove", "bluehaven"]


class WritingStyleExampleBlocks(BaseModel):  # type: ignore[explicit-any]
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


class WritingStyleProfile(BaseModel):  # type: ignore[explicit-any]
    summary: str
    example: WritingStyleExampleBlocks
    user_edited_summary: str | None = None


class SocialProfile(BaseModel):  # type: ignore[explicit-any]
    platform: str
    url: str


class EmailSummary(BaseModel):  # type: ignore[explicit-any]
    sender: str
    subject: str
    snippet: str = ""
    why_important: str


class TriageEmailSummary(BaseModel):  # type: ignore[explicit-any]
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


class InboxTriage(BaseModel):  # type: ignore[explicit-any]
    total_scanned: int
    total_unread: int
    summary: str = ""
    important_emails: list[EmailSummary]
    patterns: list[str]


class PersistedTriageSummary(BaseModel):  # type: ignore[explicit-any]
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


class InboxTriageOutput(BaseModel):  # type: ignore[explicit-any]
    summary: str = Field(
        min_length=1,
        description="2-3 sentence overview of the inbox written conversationally to the user",
    )
    important_emails: list[EmailSummary] = Field(
        description="5-10 most important emails that need attention"
    )
    patterns: list[str] = Field(description="2-5 interesting patterns across the inbox")


class WritingStyleOutput(BaseModel):  # type: ignore[explicit-any]
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


class HoloCardLLMOutput(BaseModel):  # type: ignore[explicit-any]
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


class WritingStyleExampleOutput(BaseModel):  # type: ignore[explicit-any]
    example: WritingStyleExampleBlocks = Field(
        description=(
            "Example email matching the provided style summary, broken into structured blocks."
        ),
    )


class OwnedSocialProfile(BaseModel):  # type: ignore[explicit-any]
    """One profile the ownership-filter LLM claims belongs to the user.

    Both fields default to empty so a key the model omits degrades to a lookup
    miss (the profile is dropped) exactly as it did when this was a bare dict,
    instead of failing the whole structured-output call.
    """

    platform: str = Field(default="", description="Platform name, echoed from the candidate list")
    handle: str = Field(default="", description="Handle, echoed from the candidate list")


class SocialProfileFilterOutput(BaseModel):  # type: ignore[explicit-any]
    owned_profiles: list[OwnedSocialProfile] = Field(
        description="Profiles that belong to the user. Empty list if none."
    )


# --------------------------------------------------------------------- clarify

ClarifyQuestionKind = Literal["scope", "blocker", "constraint"]


class ClarifyQuestion(BaseModel):  # type: ignore[explicit-any]
    """One no-Gmail follow-up question from ``POST /onboarding/clarify-questions``."""

    id: ClarifyQuestionKind
    kind: ClarifyQuestionKind
    question: str
    options: list[str]


class ClarifyQuestionsResponse(BaseModel):  # type: ignore[explicit-any]
    questions: list[ClarifyQuestion]


class OnboardingTodoSource(BaseModel):  # type: ignore[explicit-any]
    """The email a generated onboarding todo was drafted from."""

    sender: str
    subject: str


class OnboardingTodoSummary(BaseModel):  # type: ignore[explicit-any]
    """A todo the onboarding pipeline created, as sent on ``todos_ready`` and fed
    to the first-message prompt."""

    id: str
    title: str
    source_email: OnboardingTodoSource | None = None


class OnboardingTriggerPayload(BaseModel):  # type: ignore[explicit-any]
    """A created workflow's trigger, shaped like the workflow API's own ``trigger``
    field so the onboarding cards and the app render it identically."""

    type: TriggerType
    cron_expression: str | None = None
    timezone: str | None = None
    trigger_name: str | None = None


class OnboardingWorkflowSummary(BaseModel):  # type: ignore[explicit-any]
    """A workflow the onboarding pipeline created, as sent on ``workflows_ready``."""

    id: str
    title: str
    description: str
    categories: list[str]
    trigger: OnboardingTriggerPayload
    # Omitted from the wire (not null) on the fallback workflow, which is built
    # without the connected-integration check.
    missing_integrations: list[IntegrationRef] | None = None


class UserProfileMetadata(BaseModel):  # type: ignore[explicit-any]
    """Holo-card metadata derived from the user's account age."""

    account_number: int
    member_since: str


class ProfileCardDesign(BaseModel):  # type: ignore[explicit-any]
    """Randomized holo-card visuals."""

    house: House
    overlay_color: str
    overlay_opacity: int


# ------------------------------------------------------ websocket stage payloads


class StagePayload(BaseModel):  # type: ignore[explicit-any]
    """Base for the ``payload`` of an ``onboarding_stage`` WebSocket event."""

    # Whether a None field is dropped from the wire payload or sent as an explicit
    # null. Both are load-bearing: the frontend reads a missing `source_email` as
    # "this todo came from no email", but a null `style_summary` as "style learning
    # ran and came back empty".
    omit_none_on_wire: ClassVar[bool] = False

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=self.omit_none_on_wire)


class StatusTextPayload(StagePayload):  # type: ignore[explicit-any]
    """Progress ping for a stage that is still running."""

    status_text: str


class WritingStyleReadyPayload(StagePayload):  # type: ignore[explicit-any]
    style_summary: str | None
    example: WritingStyleExampleBlocks | None


class SocialProfilesReadyPayload(StagePayload):  # type: ignore[explicit-any]
    profiles: list[SocialProfile]


class TriageReadyPayload(StagePayload):  # type: ignore[explicit-any]
    total_scanned: int
    total_unread: int
    summary: str | None
    patterns: list[str]
    important_emails: list[TriageEmailSummary]


class TodosReadyPayload(StatusTextPayload):  # type: ignore[explicit-any]
    omit_none_on_wire: ClassVar[bool] = True

    todos: list[OnboardingTodoSummary]


class WorkflowsReadyPayload(StatusTextPayload):  # type: ignore[explicit-any]
    omit_none_on_wire: ClassVar[bool] = True

    workflows: list[OnboardingWorkflowSummary]


class CompletePayload(StagePayload):  # type: ignore[explicit-any]
    conversation_id: str | None


# ----------------------------------------------------------- endpoint responses


class OnboardingResetCounts(BaseModel):  # type: ignore[explicit-any]
    """What ``reset_onboarding`` tore down."""

    workflows_deleted: int
    todos_deleted: int
    conversation_deleted: int
    demo_conversations_deleted: int
    integrations_disconnected: int
    memories_cleared: int


class OnboardingResetResponse(OnboardingResetCounts):  # type: ignore[explicit-any]
    success: bool


class OnboardingPhaseUpdateResponse(BaseModel):  # type: ignore[explicit-any]
    success: bool
    phase: OnboardingPhase
    message: str


class SaveWritingStyleResponse(BaseModel):  # type: ignore[explicit-any]
    success: bool


class RegenerateWritingStyleExampleResponse(BaseModel):  # type: ignore[explicit-any]
    example: WritingStyleExampleBlocks | None


class SaveSocialProfilesResponse(BaseModel):  # type: ignore[explicit-any]
    success: bool
    saved: int


class PersonalizationWorkflow(BaseModel):  # type: ignore[explicit-any]
    """A suggested workflow as rendered by the onboarding cards."""

    id: str
    title: str
    description: str
    steps: list[WorkflowStep]


class PersonalizationWritingStyle(BaseModel):  # type: ignore[explicit-any]
    style_summary: str
    example: WritingStyleExampleBlocks | None


class PersonalizationTodo(BaseModel):  # type: ignore[explicit-any]
    id: str
    title: str
    description: str | None
    # `TodoDocument.source_email` is a `str | None` that nothing in the backend
    # writes, so this is always null — while the `todos_ready` WebSocket event
    # carries a {sender, subject} object the frontend renders. Typed as it really
    # is; reconciling the two is a product change, not a typing fix.
    source_email: str | None


class PersonalizationResponse(BaseModel):  # type: ignore[explicit-any]
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
