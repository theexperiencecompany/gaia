"""OpenUI artifacts: reports, dashboards, plans and the like, stored as artifact-OpenUI programs.

The program (openui-lang over the web app's artifact library) is the source of truth; the web
renders it and code fills every derived figure. Distinct from session-file artifacts, which
are files a coding run writes under artifacts/.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument
from app.schemas.common import ResponseModel


class ArtifactKind(StrEnum):
    """What the artifact is; each kind has its own generated prompt
    (apps/api/app/agents/prompts/artifacts/<kind>.txt, from the web library's kinds.ts)."""

    DASHBOARD = "dashboard"
    REPORT = "report"
    PLAN = "plan"
    COMPARISON = "comparison"
    MEMO = "memo"
    DOCUMENT = "document"


class ArtifactStatus(StrEnum):
    """Where a create_artifact run ended, as the chat card shows it."""

    READY = "ready"
    FAILED = "failed"


class ArtifactFailureReason(StrEnum):
    VALIDATION = "validation"
    REFUSED = "refused"
    TIMEOUT = "timeout"


class OpenUIArtifact(UserScopedDocument):
    """An artifact as stored in the ``artifacts`` collection."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    conversation_id: str | None = None
    kind: ArtifactKind
    title: str
    program: str
    brief_hash: str
    model: str
    repairs: int = 0
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None


class OpenUIArtifactUpdate(BaseModel):
    """Typed ``$set`` fields for an artifact."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    program: str | None = None
    version: int | None = None


class OpenUIArtifactResponse(ResponseModel):
    """An artifact as its owner's viewer loads it."""

    id: str
    kind: ArtifactKind
    title: str
    program: str
    version: int
    conversation_id: str | None
    created_at: datetime
