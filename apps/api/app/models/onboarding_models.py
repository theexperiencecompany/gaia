from typing import Optional

from pydantic import BaseModel


class CompanyProfile(BaseModel):
    name: str
    description: str
    industry: Optional[str] = None


class WritingStyleProfile(BaseModel):
    summary: str  # natural language description of their writing style
    sample_snippets: list[str]  # 3-5 real excerpts from sent emails (style only)


class EmailSummary(BaseModel):
    sender: str
    subject: str
    snippet: str
    why_important: str


class InboxTriage(BaseModel):
    total_scanned: int
    total_unread: int
    important_emails: list[EmailSummary]
    patterns: list[str]
