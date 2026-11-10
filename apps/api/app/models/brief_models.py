"""Items waiting for the user's next brief."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefItemSource
from app.db.repositories.base import UserScopedDocument


class PendingBriefItemDocument(UserScopedDocument):
    """A result that can wait, held for the user's next brief instead of being pushed.

    Written by a workflow whose delivery is brief, or by a tracked todo's run. The
    brief collects the items written since it last ran; source_id and source_title
    name the workflow or todo, text is the already-written result and
    conversation_id is where the full run lives.
    """

    source: BriefItemSource
    source_id: str
    source_title: str
    conversation_id: str
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingBriefItemUpdate(BaseModel):
    """Pending brief items are written once and never patched."""

    model_config = ConfigDict(extra="forbid")
