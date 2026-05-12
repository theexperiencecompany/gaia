from pydantic import BaseModel, Field


class WritingStyleExampleBlocks(BaseModel):
    """
    Example email broken into discrete blocks. The LLM fills each field
    independently; consumers (frontend, mail composer) decide how to render.
    """

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
    summary: str  # natural language description of their writing style
    example: WritingStyleExampleBlocks  # AI-composed example email, structured
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
    example: WritingStyleExampleBlocks = Field(
        description=(
            "Example email written in the user's voice, broken into structured blocks. "
            "Must reflect the observed style — do not invent traits not seen in the emails."
        ),
    )


class HoloCardLLMOutput(BaseModel):
    """Structured output for the holo card LLM call — phrase + bio in one shot."""

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
    """Structured output for regenerating a single example from an edited summary."""

    example: WritingStyleExampleBlocks = Field(
        description=(
            "Example email matching the provided style summary, broken into structured blocks."
        ),
    )


class SocialProfileFilterOutput(BaseModel):
    """Structured output for the social profile ownership LLM filter."""

    owned_profiles: list[dict] = Field(
        description="List of {platform, handle} dicts for profiles that belong to the user. Empty list if none."
    )
