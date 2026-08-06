"""Models for per-user E2B sandbox lifecycle (the ``e2b_sandboxes`` collection)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import MongoDocument


class E2bSandboxDocument(MongoDocument):
    """A user's E2B sandbox record — one per user, keyed by ``user_id``.

    ``last_canary_ts`` is an ISO-format string; the other timestamps are datetimes.
    There is no ``updated_at`` field, so the repository's raw writes carry their
    own values with no base auto-stamp.
    """

    user_id: str
    shard_id: int
    state: str
    sandbox_id: str | None = None
    template_id: str | None = None
    workspace_version: int = 0
    total_invocations: int = 0
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    paused_at: datetime | None = None
    last_canary_ts: str | None = None


class E2bSandboxUpdate(BaseModel):
    """Sandbox writes are raw ($set/$setOnInsert/$inc), never typed updates."""

    model_config = ConfigDict(extra="forbid")
