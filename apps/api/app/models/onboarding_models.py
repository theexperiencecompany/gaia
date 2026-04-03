from pydantic import BaseModel, Field


class WritingStyleProfile(BaseModel):
    summary: str  # natural language description of their writing style
    sample_snippets: list[str]  # 3-5 real excerpts from sent emails (style only)
    user_edited_sample: str | None = None  # user-edited snippet saved during onboarding


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
    important_emails: list[EmailSummary]
    patterns: list[str]


# ── Structured LLM output models ─────────────────────────────────────────────


class InboxTriageOutput(BaseModel):
    """Structured output for inbox triage LLM call."""

    important_emails: list[EmailSummary] = Field(
        description="5-10 most important emails that need attention"
    )
    patterns: list[str] = Field(description="2-5 interesting patterns across the inbox")


class WritingStyleOutput(BaseModel):
    """Structured output for writing style analysis LLM call."""

    summary: str = Field(
        description="2-4 sentence description of writing style for AI to mimic"
    )
    sample_snippets: list[str] = Field(
        description="3-5 short direct quotes exemplifying the style"
    )
