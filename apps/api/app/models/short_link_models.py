"""Short-link models (heygaia.link/<slug>).

A short link is a per-user, 3-char handle pointing at an artifact. Slugs are
unique only within a user's namespace and resolution is viewer-scoped (the
signed-in viewer's own slug), so the same URL means different things per user
and a forwarded private link leaks nothing.
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
