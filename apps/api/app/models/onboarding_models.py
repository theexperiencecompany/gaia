from pydantic import BaseModel, Field


class WritingStyleProfile(BaseModel):
    summary: str  # natural language description of their writing style
    example: str  # one AI-composed example email in their voice, relevant to their profession
    user_edited_summary: str | None = (
        None  # user-edited summary saved during onboarding
    )


class SocialProfile(BaseModel):
    platform: str  # e.g. "twitter", "linkedin", "github"
    url: str


class EmailSummary(BaseModel):
    sender: str
    subject: str
    snippet: str = ""
    why_important: str


class InboxTriage(BaseModel):
    total_scanned: int
    total_unread: int
    summary: str = ""
    important_emails: list[EmailSummary]
    patterns: list[str]


# ── Structured LLM output models ─────────────────────────────────────────────


class InboxTriageOutput(BaseModel):
    """Structured output for inbox triage LLM call."""

    summary: str = Field(
        min_length=1,
        description="2-3 sentence overview of the inbox written conversationally to the user",
    )
    important_emails: list[EmailSummary] = Field(
        description="5-10 most important emails that need attention"
    )
    patterns: list[str] = Field(description="2-5 interesting patterns across the inbox")


class WritingStyleOutput(BaseModel):
    """Structured output for writing style analysis LLM call."""

    summary: str = Field(
        description=(
            "2-3 sentence writing style description capturing concrete observable patterns: "
            "how they greet, sign off, sentence length, formality, and any distinctive habits."
        )
    )
    example: str = Field(
        min_length=1,
        description="One short example email (3-6 lines) written in the user's voice, "
        "relevant to their profession. Must reflect the observed style — "
        "do not invent traits not seen in the emails. Must not be empty.",
    )


class WritingStyleExampleOutput(BaseModel):
    """Structured output for regenerating a single example from an edited summary."""

    example: str = Field(
        description=(
            "One short example email (3-6 lines) written to match the provided style summary, "
            "relevant to the user's profession."
        )
    )


class SocialProfileFilterOutput(BaseModel):
    """Structured output for the social profile ownership LLM filter."""

    owned_profiles: list[dict] = Field(
        description="List of {platform, handle} dicts for profiles that belong to the user. Empty list if none."
    )
