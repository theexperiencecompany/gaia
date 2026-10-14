"""Items waiting for the user's next brief."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class PendingBriefSource(StrEnum):
    """What held a result for the brief: a brief-delivery workflow or the inbox desk."""

    WORKFLOW = "workflow"
    INBOX_DESK = "inbox_desk"


class PendingBriefItemDocument(UserScopedDocument):
    """A finished run held for the user's next brief instead of being pushed.

    Written when a workflow whose delivery is brief completes with something
    worth reporting, or when the inbox desk finishes its scheduled sweep. The
    brief collects the items written since it last ran; source_id is the
    workflow or todo that produced the item, text is the run's already-narrated
    result and conversation_id is where the full run lives.
    """

    source: PendingBriefSource
    source_id: str
    source_title: str
    conversation_id: str
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingBriefItemUpdate(BaseModel):
    """Pending brief items are written once and never patched."""

    model_config = ConfigDict(extra="forbid")
