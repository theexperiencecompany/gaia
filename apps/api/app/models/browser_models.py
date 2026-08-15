"""Models for persistent Steel browser profiles (the ``browser_profiles`` collection)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument


class BrowserProfileDocument(UserScopedDocument):
    """One Steel profile per (user, domain).

    The Steel profile holds the cookies / localStorage the user established in a
    live-view handoff; we keep only its id so a repeat task on that domain reuses
    the authenticated context instead of logging in again.
    """

    domain: str
    steel_profile_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BrowserProfileUpdate(BaseModel):
    """Profile writes are raw upserts ($set/$setOnInsert), never typed updates."""

    model_config = ConfigDict(extra="forbid")
