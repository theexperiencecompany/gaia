"""Items waiting for the user's next brief."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class PendingBriefItemDocument(UserScopedDocument):
    """A finished workflow run held for the user's next brief instead of being pushed.

    Written when a workflow whose delivery is brief completes with something
    worth reporting. The brief collects the items written since it last ran;
    text is the run's already-narrated result and conversation_id is
    where the full run lives.
    """

    workflow_id: str
    workflow_title: str
    conversation_id: str
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingBriefItemUpdate(BaseModel):
    """Pending brief items are written once and never patched."""

    model_config = ConfigDict(extra="forbid")
