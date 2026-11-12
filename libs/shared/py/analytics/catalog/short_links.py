"""heygaia.link short-link events, every one attributed to the link's owner."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent

__all__ = [
    "ShortLinkAccessChanged",
    "ShortLinkContentPublished",
    "ShortLinkCreated",
    "ShortLinkDenied",
    "ShortLinkOpened",
    "ShortLinkPublishRejected",
    "ShortLinkReported",
    "ShortLinkRevoked",
    "ShortLinkRotated",
    "ShortLinkTakenDown",
]


# The API's enums (apps/api/app/models/short_link_models.py) are the source of
# truth; this layer cannot import them, so the event schema restates each closed
# set and the API's test_registry asserts they stay equal, the same way the
# workflow events restate their delivery modes.
ShortLinkTarget = Literal[
    "todo_deliverable", "briefing", "session_artifact", "workflow_run", "openui_artifact"
]
ShortLinkAccess = Literal["public", "unlisted", "people", "owner"]
ShortLinkRevokeReason = Literal["owner", "rotated", "expired", "takedown", "target_deleted"]
ShortLinkDenialReason = Literal[
    "expired", "revoked", "removed", "target_deleted", "sign_in_required", "forbidden"
]
ShortLinkRenderMode = Literal[
    "frame_active", "image", "image_svg", "pdf", "text", "media", "download"
]
ShortLinkPublishRejection = Literal["too_large", "unsafe_url", "restricted_type", "quota"]
ShortLinkReportReason = Literal["phishing", "malware", "harassment", "illegal", "other"]


class ShortLinkCreated(ServerEvent):
    """A heygaia.link was minted for one of the user's artifacts."""

    event: ClassVar[str] = "short_link:created"
    budget_per_user_day: ClassVar[int] = 200

    target_type: ShortLinkTarget
    access: ShortLinkAccess
    #: The owner shared it, or GAIA attached it to something it handed over.
    origin: Literal["owner_share", "gaia_attached"]
    has_expiry: bool


class ShortLinkOpened(ServerEvent):
    """Someone other than the owner opened one of the user's heygaia.links, once a day per viewer.

    Unfurl bots building a chat preview never count.
    """

    event: ClassVar[str] = "short_link:opened"
    budget_per_user_day: ClassVar[int] = 500

    target_type: ShortLinkTarget
    access: ShortLinkAccess
    viewer_signed_in: bool


class ShortLinkAccessChanged(ServerEvent):
    """The user changed who one of their links opens for, or its expiry."""

    event: ClassVar[str] = "short_link:access_changed"
    budget_per_user_day: ClassVar[int] = 200

    target_type: ShortLinkTarget
    from_access: ShortLinkAccess
    to_access: ShortLinkAccess
    grantee_count: int


class ShortLinkRotated(ServerEvent):
    """The user replaced a link with a new URL; the old one stopped opening."""

    event: ClassVar[str] = "short_link:rotated"
    budget_per_user_day: ClassVar[int] = 100

    target_type: ShortLinkTarget
    access: ShortLinkAccess


class ShortLinkRevoked(ServerEvent):
    """The user stopped sharing one of their artifacts."""

    event: ClassVar[str] = "short_link:revoked"
    budget_per_user_day: ClassVar[int] = 50

    target_type: ShortLinkTarget
    reason: ShortLinkRevokeReason


class ShortLinkDenied(ServerEvent):
    """Someone opened one of the user's links and was turned away (dead, sign-in needed, not granted)."""

    event: ClassVar[str] = "short_link:denied"
    budget_per_user_day: ClassVar[int] = 500

    target_type: ShortLinkTarget
    reason: ShortLinkDenialReason


class ShortLinkContentPublished(ServerEvent):
    """A shared file's bytes were stored as a snapshot its link serves."""

    event: ClassVar[str] = "short_link:content_published"
    budget_per_user_day: ClassVar[int] = 500

    target_type: ShortLinkTarget
    render_mode: ShortLinkRenderMode
    size_bucket: Literal["lt_100kb", "lt_1mb", "lt_10mb", "gte_10mb"]


class ShortLinkPublishRejected(ServerEvent):
    """A shared file was not published, or was published only for narrower access."""

    event: ClassVar[str] = "short_link:publish_rejected"
    budget_per_user_day: ClassVar[int] = 500

    target_type: ShortLinkTarget
    reason: ShortLinkPublishRejection


class ShortLinkReported(ServerEvent):
    """Someone reported one of the user's links."""

    event: ClassVar[str] = "short_link:reported"
    budget_per_user_day: ClassVar[int] = 100

    target_type: ShortLinkTarget
    reason: ShortLinkReportReason
    reporter_signed_in: bool


class ShortLinkTakenDown(ServerEvent):
    """One of the user's links was removed for breaking GAIA's terms."""

    event: ClassVar[str] = "short_link:taken_down"
    budget_per_user_day: ClassVar[int] = 50

    target_type: ShortLinkTarget
    reason: Literal["reports_threshold", "admin"]
