"""OpenUI artifacts: reports, dashboards, plans and the like, stored as artifact-OpenUI programs.

The program (openui-lang over the web app's artifact library) is the source of truth; the web
renders it and code fills every derived figure. Distinct from session-file artifacts, which
are files a coding run writes under artifacts/.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.document_models import UserScopedDocument
from app.schemas.common import ResponseModel


class ArtifactKind(StrEnum):
    """What the artifact is; each kind has its own generated prompt
    (apps/api/app/agents/prompts/artifacts/<kind>.txt, from libs/artifacts/src/kinds.ts)."""

    DASHBOARD = "dashboard"
    REPORT = "report"
    PLAN = "plan"
    COMPARISON = "comparison"
    MEMO = "memo"
    DOCUMENT = "document"


class ArtifactStatus(StrEnum):
    """Where a create_artifact run stands, as the chat card shows it."""

    STREAMING = "streaming"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


class ArtifactFailureReason(StrEnum):
    VALIDATION = "validation"
    REFUSED = "refused"
    TIMEOUT = "timeout"
    TRUNCATED = "truncated"


class ArtifactStreamHeader(BaseModel):
    """Which create_artifact run a card belongs to, keyed by stream_id."""

    stream_id: str
    kind: ArtifactKind
    title: str


class ArtifactDelta(ArtifactStreamHeader):
    """A chunk of the first draft's program; the run's card appends it while it streams."""

    delta: str


class ArtifactCard(ArtifactStreamHeader):
    """Where a create_artifact run stands: the artifact_done tool_data entry's data."""

    status: ArtifactStatus
    #: The first draft so far, while status is streaming; a ready card's program is fetched by artifact_id.
    program: str | None = None
    #: The stored artifact, once status is ready.
    artifact_id: str | None = None
    #: Why it gave up, on a failure the tool caught.
    reason: ArtifactFailureReason | None = None


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OpenUIArtifactUpdate(BaseModel):
    """An artifact is written once: no field can be ``$set``."""

    model_config = ConfigDict(extra="forbid")


class OpenUIArtifactResponse(ResponseModel):
    """An artifact as its owner's viewer loads it."""

    id: str
    kind: ArtifactKind
    title: str
    program: str
    conversation_id: str | None
    created_at: datetime
