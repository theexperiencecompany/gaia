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
    # Provenance — only set on the CLI import path; None for logins GAIA acquired
    # by browsing. ``source`` is a ``BrowserLoginSource`` value ("import").
    source: str | None = None
    source_browser: str | None = None
    source_ip: str | None = None


class BrowserLoginProvenance(BaseModel):
    """Where a saved login came from — recorded only on the CLI import path.

    Passed to the store as an optional slice so the generic task-end save path
    (which never sets it) can't clobber a previously-imported doc's provenance.
    """

    source: str
    source_browser: str | None = None
    source_ip: str | None = None


class BrowserProfileUpdate(BaseModel):
    """Profile writes are raw upserts ($set/$setOnInsert), never typed updates."""

    model_config = ConfigDict(extra="forbid")
