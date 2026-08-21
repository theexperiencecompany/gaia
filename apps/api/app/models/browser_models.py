"""Models for persistent browser login state (the ``browser_profiles`` collection)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument


class BrowserProfileDocument(UserScopedDocument):
    """One saved login per (user, domain).

    ``storage_state_blob`` is the Fernet-encrypted JSON serialization of a
    Playwright-format storage_state ({cookies, origins}) captured when a browser
    session for this domain ends. Decrypting and loading it before the next
    session on the same domain restores cookies/localStorage without the agent
    logging in again.
    """

    domain: str
    storage_state_blob: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BrowserProfileUpdate(BaseModel):
    """Profile writes are raw upserts ($set/$setOnInsert), never typed updates."""

    model_config = ConfigDict(extra="forbid")
