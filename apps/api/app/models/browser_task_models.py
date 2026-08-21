"""Model for the persistent browser-task history (the ``browser_tasks`` collection)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.browser import BrowserSessionStatus
from app.db.repositories.base import UserScopedDocument


class BrowserTaskDocument(UserScopedDocument):
    """One finished browser task: what was asked, how it ended, and enough to
    rebuild its recap. ``session_id`` + ``steps`` locate the step screenshots in
    R2, so the history can replay a task long after the live session is gone.
    ``step_goals`` captions each frame ("what's going on"), aligned to steps 1..N.
    """

    conversation_id: str
    task: str
    status: BrowserSessionStatus
    success: bool
    session_id: str
    steps: int = 0
    step_goals: list[str] = Field(default_factory=list)
    # The screenshots that actually reached R2, in step order. Recorded rather
    # than derived: an upload can fail, and a guessed URL renders as a broken
    # image in history forever.
    step_screenshots: list[str] = Field(default_factory=list)
    # Where the task was started from ("web", "telegram", "whatsapp", …).
    source: str = ""
    replay_url: str | None = None
    created_at: datetime | None = None


class BrowserTaskUpdate(BaseModel):
    """Task records are write-once; no typed updates."""

    model_config = ConfigDict(extra="forbid")
