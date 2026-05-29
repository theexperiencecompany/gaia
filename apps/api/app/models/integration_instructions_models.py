"""Per-integration custom instructions — MongoDB document model.

A user-authored (and agent-updatable) markdown note attached to one
integration, e.g. "for Slack, focus on #eng, #design, #pm". Stored in
MongoDB as the source of truth; materialized read-only into the user's
workspace at ``integrations/<id>/agent/instructions.md`` and injected into
the matching subagent's dynamic context so it acts on the guidance
immediately. One document per (user_id, integration_id).
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# Guardrail: keep instructions short enough to live in every subagent turn's
# context without blowing the token budget. ~8k chars ≈ a couple of pages.
MAX_INSTRUCTIONS_CHARS = 8000


class InstructionsEditor(str, Enum):
    """Who last wrote the instructions — surfaced in the UI audit line."""

    USER = "user"
    AGENT = "agent"


class IntegrationInstructions(BaseModel):
    """Custom instructions for a single integration, owned by one user."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = Field(default=None, description="MongoDB document ID")
    user_id: str = Field(..., description="Owner user ID")
    integration_id: str = Field(..., description="Integration ID (slack, linear, github, …)")
    content: str = Field(
        default="",
        max_length=MAX_INSTRUCTIONS_CHARS,
        description="Markdown instructions the agent honors for this integration",
    )
    updated_by: InstructionsEditor = Field(
        default=InstructionsEditor.USER,
        description="Whether the user or the agent last wrote this",
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_serializer("updated_at")
    def _serialize_updated_at(self, value: datetime) -> str:
        return value.isoformat()
