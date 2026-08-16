"""Model for the persistent browser-task history (the ``browser_tasks`` collection)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.constants.browser import BrowserSessionStatus
from app.db.repositories.base import UserScopedDocument


class BrowserTaskDocument(UserScopedDocument):
    """One finished browser task: what was asked, how it ended, and enough to
    rebuild its recap. ``session_id`` + ``steps`` locate the step screenshots in
    R2, so the history can replay a task long after the live session is gone.
    """

    conversation_id: str
    task: str
    status: BrowserSessionStatus
    success: bool
    session_id: str
    steps: int = 0
    replay_url: str | None = None
    created_at: datetime | None = None


class BrowserTaskUpdate(BaseModel):
    """Task records are write-once; no typed updates."""

    model_config = ConfigDict(extra="forbid")
