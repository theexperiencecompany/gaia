"""A user's standing instructions — one store for every scope the agent honours.

The global scope reaches every agent tier each turn; an integration scope (its id,
e.g. "slack") reaches the subagent for that integration. Both are user-level layers:
they shape tone, defaults and focus, and never outrank the platform rules in the
static system prompt.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument
from app.schemas.common import ResponseModel

GLOBAL_INSTRUCTIONS_SCOPE = "global"

# ~8k chars ≈ two pages: small enough to sit in every turn's context.
MAX_INSTRUCTIONS_CHARS = 8000


class InstructionsEditor(StrEnum):
    """Who last wrote a scope's instructions."""

    USER = "user"
    AGENT = "agent"


class UserInstructionsDocument(UserScopedDocument):
    """One (user_id, scope) record; revision increments on every write."""

    scope: str
    content: str = ""
    revision: int = 0
    updated_by: InstructionsEditor = InstructionsEditor.USER
    updated_at: datetime | None = None


class UserInstructionsUpdate(BaseModel):
    """Typed $set fields for an instructions record."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    updated_by: InstructionsEditor | None = None


class UpdateInstructionsRequest(BaseModel):
    """Replace one scope's instructions, guarded by the revision the editor loaded."""

    content: str = Field(
        max_length=MAX_INSTRUCTIONS_CHARS,
        description="Full replacement markdown; an empty string clears the scope",
    )
    base_revision: int = Field(
        ge=0,
        description="Revision the edit started from; a mismatch means someone else saved first",
    )


class InstructionsResponse(ResponseModel):
    """A scope's current instructions; revision 0 means never written."""

    scope: str
    content: str = ""
    revision: int = 0
    updated_by: InstructionsEditor | None = None
    updated_at: datetime | None = None
