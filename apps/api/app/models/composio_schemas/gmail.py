"""
Gmail trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/gmail.ts
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.constants.email import DEFAULT_SUMMARY_FIELDS, MessageFieldLiteral

# =============================================================================
# Trigger Payloads
# =============================================================================


class GmailNewMessagePayload(BaseModel):
    """Payload for GMAIL_NEW_GMAIL_MESSAGE trigger."""

    attachment_list: list[Any] | None = Field(
        None, description="List of attachments in the message"
    )
    message_id: str | None = Field(None, description="Message ID")
    message_text: str | None = Field(None, description="Text content of the message")
    message_timestamp: str | None = Field(None, description="Timestamp of the message")
    payload: dict[str, Any] | None = Field(None, description="Full message payload")
    sender: str | None = Field(None, description="Sender email address")
    subject: str | None = Field(None, description="Email subject")
    thread_id: str | None = Field(None, description="Thread ID")


# =============================================================================
# Custom Tool Inputs
# =============================================================================


# Convenience timeframes the agent can pass instead of computing Gmail's
# after:/before: operators. Resolved server-side using the user's home timezone.
TimeframeLiteral = Literal[
    "today",
    "yesterday",
    "tomorrow",
    "this_week",
    "last_week",
    "next_week",
    "1d",
    "3d",
    "5d",
    "7d",
    "1w",
    "2w",
    "1m",
    "3m",
    "6m",
    "1y",
]

BodyProcessingLiteral = Literal["normalize", "raw", "none"]


class FetchInboxSummaryInput(BaseModel):
    """Input for the GMAIL_FETCH_INBOX_SUMMARY custom tool."""

    timeframe: TimeframeLiteral | None = Field(
        default=None,
        description=(
            "Convenience range, resolved to Gmail's after:/before: operators "
            "in the user's home timezone. Ignored if `query` already "
            "contains after:/before:."
        ),
    )
    query: str | None = Field(
        default=None,
        description="Raw Gmail search query (ANDed with the timeframe clause).",
    )
    fields: list[MessageFieldLiteral] = Field(
        default_factory=lambda: list(DEFAULT_SUMMARY_FIELDS),
        description=(
            "Which fields per message. Defaults to metadata + snippet. "
            "Add 'body' for the processed body. Empty list = all fields."
        ),
    )

    @field_validator("fields", mode="before")
    @classmethod
    def _coerce_none_fields(
        cls, value: list[MessageFieldLiteral] | None
    ) -> list[MessageFieldLiteral]:
        # Tool wrappers pass omitted args as explicit None; treat that the same
        # as omission and fall back to the curated default field set. An empty
        # list is preserved (it carries the "all fields" meaning downstream).
        if value is None:
            return list(DEFAULT_SUMMARY_FIELDS)
        return value

    body_processing: BodyProcessingLiteral = Field(
        default="normalize",
        description=(
            "'normalize' (default): strip signatures, disclaimers, "
            "unsubscribe footers, and utm tracking chains. Lossless on "
            "meaningful content (quoted replies are KEPT — they give context "
            "into the older conversation). 'raw': untouched Gmail body. "
            "'none': omit body regardless of fields[]."
        ),
    )
    max_messages: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Cap on total messages aggregated. Default scales with timeframe "
            "(100 for today/yesterday, 200 for a week, 500 for a month+)."
        ),
    )
    per_page: int = Field(default=100, ge=1, le=500, description="Gmail page size (max 500).")
    user_id: str | None = Field(default=None, description="Internal. Set from auth.")
