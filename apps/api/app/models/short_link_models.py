"""Short-link models (heygaia.link/<slug>).

A short link is a capability URL: the slug is a high-entropy, globally unique
handle granting read-only access to exactly one artifact, so it opens from a
chat app or an email with no signed-in session. Anyone holding the link can
open it until the owner revokes it.

What a link serves is never the stored document. Each target type has a public
view model below — the only shape the resolver returns — carrying what a
recipient should see and nothing else: no ids, no thread ids, no addresses, no
raw canvas.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument
from app.models.briefing_models import BriefingItemKind, BriefingKind, BriefingMood, BriefingStat
from app.models.workflow_execution_models import WorkflowExecutionStatus


class ShortLinkTargetType(StrEnum):
    """Every kind of artifact a heygaia.link can point at."""

    TODO_DELIVERABLE = "todo_deliverable"
    BRIEFING = "briefing"
    SESSION_ARTIFACT = "session_artifact"
    WORKFLOW_RUN = "workflow_run"


class ShortLink(UserScopedDocument):
    """A capability URL as stored in the ``short_links`` collection. Doubles as
    the repository's document model (``ShortLinksRepository`` in
    ``app/db/repositories/short_links.py``). Identity is the globally-unique
    ``slug``; ``user_id`` is the artifact's owner, the only scope its target is
    ever read under."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    slug: str
    target_type: ShortLinkTargetType
    target_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    revoked: bool = False


class ShortLinkUpdate(BaseModel):
    """Typed ``$set`` fields for a short link."""

    model_config = ConfigDict(extra="forbid")

    revoked: bool | None = None


class _PublicView(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicTodoDeliverable(_PublicView):
    """A tracked todo's result: its title and the deliverable facet of its
    canvas (``canvas_markdown.deliverable_markdown``), never the working sections."""

    target_type: Literal[ShortLinkTargetType.TODO_DELIVERABLE]
    title: str
    completed: bool
    content: str


class PublicBriefingItem(_PublicView):
    """An item as the brief page lists it. ``link`` is the item's own public
    heygaia.link; the todo id it is bound to stays private."""

    text: str
    kind: BriefingItemKind
    link: str | None


class PublicBriefingSection(_PublicView):
    numeral: str
    title: str
    items: list[PublicBriefingItem]


class PublicBriefingEvent(_PublicView):
    """A calendar entry on the brief: when and what, never where."""

    date: str
    start: str | None
    title: str


class PublicBriefingPayload(_PublicView):
    """The brief fields the standalone brief page reads (``BriefingEdition``)."""

    kicker: str
    date: str
    headline: str
    lede: str
    stats: list[BriefingStat]
    sections: list[PublicBriefingSection]
    mood: BriefingMood
    caption: str
    hue: int
    calendar: list[PublicBriefingEvent]


class PublicBriefing(_PublicView):
    """A persisted daily/weekly brief: its rendered edition image and payload,
    shaped like the ``BriefingModel`` fields ``StandaloneBriefing`` renders."""

    target_type: Literal[ShortLinkTargetType.BRIEFING]
    kind: BriefingKind
    edition_image_url: str | None
    payload: PublicBriefingPayload


class PublicSessionArtifact(_PublicView):
    """A file GAIA produced in a session's sandbox. ``content`` is the text of a
    text file; binary files carry ``None`` and render as a metadata card."""

    target_type: Literal[ShortLinkTargetType.SESSION_ARTIFACT]
    filename: str
    content_type: str
    size_bytes: int
    content: str | None


class PublicWorkflowRun(_PublicView):
    """One workflow execution's outcome."""

    target_type: Literal[ShortLinkTargetType.WORKFLOW_RUN]
    workflow_title: str
    status: WorkflowExecutionStatus
    started_at: datetime
    completed_at: datetime | None
    summary: str


PublicShortLinkView = Annotated[
    PublicTodoDeliverable | PublicBriefing | PublicSessionArtifact | PublicWorkflowRun,
    Field(discriminator="target_type"),
]


class ShortLinkTargetRequest(BaseModel):
    """One of the owner's artifacts, to share (mint or fetch its link) or stop sharing."""

    model_config = ConfigDict(extra="forbid")

    target_type: ShortLinkTargetType
    target_id: str = Field(min_length=1)


class ShortLinkResponse(BaseModel):
    """A minted heygaia.link URL."""

    url: str
