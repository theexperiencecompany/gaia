"""Short-link models (heygaia.link/<slug>).

A short link is a capability URL: the slug is a high-entropy, globally unique
handle granting read-only access to exactly one artifact, so the owner can open
it from a chat app without a signed-in session (share-link semantics). Links
expire and can be revoked; resolution never requires auth.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Extend as new artifact kinds get short links (published sites, decks, …).
ShortLinkTarget = Literal["todo_canvas"]


class ShortLink(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    user_id: str
    target_type: ShortLinkTarget
    target_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    revoked: bool = False
