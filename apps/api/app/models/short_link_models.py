"""Short-link models (heygaia.link/<slug>).

A short link is a high-entropy, globally unique slug pointing at exactly one
artifact. Its access level says who may open it: anyone (public, unlisted),
signed-in grantees (people) or only its owner. It stays open until the owner
revokes or rotates it, it expires, or GAIA takes it down.

What a link serves is never the stored document. Each target type has a public
view model below — the only shape the resolver returns — carrying what a
recipient should see and nothing else: no ids, no thread ids, no addresses, no
raw canvas.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field

from app.db.repositories.base import MongoDocument, UserScopedDocument
from app.models.briefing_models import BriefingItemKind, BriefingKind, BriefingMood, BriefingStat
from app.models.openui_artifact_models import ArtifactKind
from app.models.workflow_execution_models import WorkflowExecutionStatus
from app.schemas.common import ResponseModel


class ShortLinkTargetType(StrEnum):
    """Every kind of artifact a heygaia.link can point at."""

    TODO_DELIVERABLE = "todo_deliverable"
    BRIEFING = "briefing"
    SESSION_ARTIFACT = "session_artifact"
    WORKFLOW_RUN = "workflow_run"
    OPENUI_ARTIFACT = "openui_artifact"


class LinkViewerKind(StrEnum):
    """Who opened a link, as far as counting opens is concerned."""

    OWNER = "owner"
    UNFURL_BOT = "unfurl_bot"
    RECIPIENT = "recipient"


class LinkAccess(StrEnum):
    """Who a link opens for."""

    # Anyone; previews show the content and search engines may index it.
    PUBLIC = "public"
    # Anyone holding the URL; never indexed.
    UNLISTED = "unlisted"
    # Signed-in GAIA users whose account email is one of the link's grantees.
    PEOPLE = "people"
    # Only the owner, signed in.
    OWNER = "owner"


class RevokeReason(StrEnum):
    """Why a link stopped opening."""

    OWNER = "owner"
    ROTATED = "rotated"
    EXPIRED = "expired"
    TAKEDOWN = "takedown"
    TARGET_DELETED = "target_deleted"


class LinkDenial(StrEnum):
    """Why a link did not open; each is one ErrorEnvelope code and one page the viewer sees."""

    NOT_FOUND = "link_not_found"
    REVOKED = "link_revoked"
    EXPIRED = "link_expired"
    REMOVED = "link_removed"
    TARGET_DELETED = "link_target_deleted"
    SIGN_IN_REQUIRED = "link_sign_in_required"
    FORBIDDEN = "link_forbidden"


class RenderMode(StrEnum):
    """How a snapshot's bytes are shown, which fixes the headers the content origin serves them with."""

    FRAME_ACTIVE = "frame_active"
    IMAGE = "image"
    IMAGE_SVG = "image_svg"
    PDF = "pdf"
    TEXT = "text"
    MEDIA = "media"
    DOWNLOAD = "download"


class PublishRejection(StrEnum):
    """Why a file's bytes were not published; the link then shows only the file's name and size."""

    TOO_LARGE = "too_large"
    UNSAFE_URL = "unsafe_url"
    RESTRICTED_TYPE = "restricted_type"
    QUOTA = "quota"


class ReportReason(StrEnum):
    PHISHING = "phishing"
    MALWARE = "malware"
    HARASSMENT = "harassment"
    ILLEGAL = "illegal"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LinkViewer:
    """Whoever opened a link: their session user and verified email (None when signed out), address and browser."""

    user_id: str | None
    email: str | None
    ip: str
    user_agent: str


class LinkSnapshot(BaseModel):
    """The file a link serves, pinned when it was published; resolution never reads the live file.

    content_id names the immutable bytes in the link-content store and is None
    when they were not published (rejected says why); the link then shows the
    name and size only. max_access is the widest level the bytes may be served
    at (restricted_by says what narrowed it). Several links may pin one
    content_id after a rotation.
    """

    model_config = ConfigDict(extra="ignore")

    filename: str
    mime: str
    size_bytes: int
    render: RenderMode
    content_id: str | None
    #: sha256 of the bytes, so republishing an unchanged file is skipped.
    digest: str | None = None
    has_thumbnail: bool = False
    rejected: PublishRejection | None = None
    max_access: LinkAccess = LinkAccess.PUBLIC
    restricted_by: PublishRejection | None = None
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    #: The live/dead switch the unique live-target index is partial on.
    revoked: bool = False
    revoked_at: datetime | None = None
    revoked_reason: RevokeReason | None = None
    #: Defaults carry a pre-access link as exactly what it was: unlisted, never expiring.
    access: LinkAccess = LinkAccess.UNLISTED
    grantees: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    snapshot: LinkSnapshot | None = None
    #: Reports crossed the threshold; the link shows "removed" until an admin restores it.
    suspended: bool = False


class ShortLinkUpdate(BaseModel):
    """Typed ``$set`` fields for a short link."""

    model_config = ConfigDict(extra="forbid")

    revoked: bool | None = None
    revoked_at: datetime | None = None
    revoked_reason: RevokeReason | None = None
    access: LinkAccess | None = None
    grantees: list[str] | None = None
    expires_at: datetime | None = None
    snapshot: LinkSnapshot | None = None
    suspended: bool | None = None


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
    """A file GAIA produced in a session's sandbox, as its link pinned it.

    text is the file's text when it is shown as text (code, markdown, and HTML
    source where the instance has no content origin); the page renders it
    itself. Every other file is framed from the content origin (LinkEnvelope.content)
    or offered as a download.
    """

    target_type: Literal[ShortLinkTargetType.SESSION_ARTIFACT]
    filename: str
    content_type: str
    size_bytes: int
    text: str | None


class PublicWorkflowRun(_PublicView):
    """One workflow execution's outcome."""

    target_type: Literal[ShortLinkTargetType.WORKFLOW_RUN]
    workflow_title: str
    status: WorkflowExecutionStatus
    started_at: datetime
    completed_at: datetime | None
    summary: str


class PublicOpenUIArtifact(_PublicView):
    """An artifact create_artifact made: its program, which the page renders as data."""

    target_type: Literal[ShortLinkTargetType.OPENUI_ARTIFACT]
    kind: ArtifactKind
    title: str
    program: str
    version: int
    created_at: datetime
    #: The owner's display name, never their email; None when they have none.
    shared_by: str | None


PublicShortLinkView = Annotated[
    PublicTodoDeliverable
    | PublicBriefing
    | PublicSessionArtifact
    | PublicWorkflowRun
    | PublicOpenUIArtifact,
    Field(discriminator="target_type"),
]


class LinkContent(BaseModel):
    """The bytes a link frames from the content origin; the page asks for a content token to load them."""

    content_id: str
    mime: str
    size_bytes: int
    render: RenderMode


class LinkEnvelope(ResponseModel):
    """What opening a link returns: its access level, the target's public view and any framed content."""

    access: LinkAccess
    target_type: ShortLinkTargetType
    view: PublicShortLinkView
    content: LinkContent | None
    #: The viewer is the link's owner, so the page offers its share settings.
    is_owner: bool


class LinkPreviewMeta(ResponseModel):
    """What a chat preview or a page's metadata may show for a link, by its access level and state.

    title and description are real content only for a live public or unlisted
    link; any other link carries the kind line or the dead-link line. image_url
    is None when the preview card is generated from these fields.
    """

    live: bool
    target_type: ShortLinkTargetType | None
    access: LinkAccess | None
    indexable: bool
    title: str
    description: str
    image_url: str | None


MAX_GRANTEES = 50


class LinkSettings(BaseModel):
    """Who a link opens for and until when."""

    model_config = ConfigDict(extra="forbid")

    access: LinkAccess = LinkAccess.UNLISTED
    grantees: list[EmailStr] = Field(default_factory=list, max_length=MAX_GRANTEES)
    expires_at: AwareDatetime | None = None


class LinkSettingsUpdate(BaseModel):
    """Owner changes to a live link; an omitted field keeps its value."""

    model_config = ConfigDict(extra="forbid")

    access: LinkAccess | None = None
    grantees: list[EmailStr] | None = Field(default=None, max_length=MAX_GRANTEES)
    expires_at: AwareDatetime | None = None


class ShortLinkTargetRequest(BaseModel):
    """One of the owner's artifacts, to read or stop sharing."""

    model_config = ConfigDict(extra="forbid")

    target_type: ShortLinkTargetType
    target_id: str = Field(min_length=1)


class ShareLinkRequest(ShortLinkTargetRequest):
    """Share one of the owner's artifacts: its live link, minted with settings when none is live."""

    settings: LinkSettings = Field(default_factory=LinkSettings)


class ShortLinkResponse(ResponseModel):
    """One live heygaia.link and its settings.

    content_max_access is the widest level its file may be served at when the
    file narrows it (a login form, an unsafe URL, an installer); None otherwise.
    """

    url: str
    slug: str
    access: LinkAccess
    grantees: list[str]
    expires_at: datetime | None
    content_max_access: LinkAccess | None


class ShortLinkShareState(ResponseModel):
    """Whether one of the owner's artifacts is shared: its live link, or None."""

    link: ShortLinkResponse | None


class ContentTokenResponse(ResponseModel):
    """A short-lived URL that loads a link's content from the content origin."""

    content_url: str
    expires_at: datetime


class LinkReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReportReason
    #: Cloudflare Turnstile's token, required where the deployment checks one.
    turnstile_token: str | None = None


class StopSharingResult(ResponseModel):
    """Whether stopping killed a live link; False when the artifact was not shared."""

    revoked: bool


class LinkReport(MongoDocument):
    """One viewer reporting one link, stored in link_reports; a viewer counts once per link."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    slug: str
    reason: ReportReason
    #: The signed-in reporter's user id, else a keyed hash of their address and browser.
    reporter_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LinkReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReportReason | None = None
