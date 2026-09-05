"""Short-link models (heygaia.link/<slug>).

A short link is a capability URL: the slug is a high-entropy, globally unique
handle granting read-only access to exactly one artifact, so the owner can open
it from a chat app without a signed-in session (share-link semantics). Links
expire and can be revoked; resolution never requires auth.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument

# Extend as new artifact kinds get short links (published sites, decks, …).
ShortLinkTarget = Literal["todo_canvas"]


class ShortLink(UserScopedDocument):
    """A capability URL as stored in the ``short_links`` collection. Doubles as
    the repository's document model (``ShortLinksRepository`` in
    ``app/db/repositories/short_links.py``). Identity is the globally-unique
    ``slug``, not Mongo's incidental ``_id``."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    slug: str
    target_type: ShortLinkTarget
    target_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    revoked: bool = False


class ShortLinkUpdate(BaseModel):
    """Typed ``$set`` fields for a short link."""

    model_config = ConfigDict(extra="forbid")

    expires_at: datetime | None = None
    revoked: bool | None = None
