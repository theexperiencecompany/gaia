"""heygaia.link short-link events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent

__all__ = ["ShortLinkCreated", "ShortLinkOpened", "ShortLinkRevoked"]


# The heygaia.link target kinds. The API's ShortLinkTargetType
# (apps/api/app/models/short_link_models.py) is the source of truth; this layer
# cannot import it, so the event schema restates the closed set, the same way the
# workflow events restate their delivery modes.
ShortLinkTarget = Literal["todo_deliverable", "briefing", "session_artifact", "workflow_run"]


class ShortLinkCreated(ServerEvent):
    """A heygaia.link was minted for one of the user's artifacts."""

    event: ClassVar[str] = "short_link:created"
    budget_per_user_day: ClassVar[int] = 200

    target_type: ShortLinkTarget


class ShortLinkOpened(ServerEvent):
    """Someone opened one of the user's heygaia.links (attributed to the owner)."""

    event: ClassVar[str] = "short_link:opened"
    budget_per_user_day: ClassVar[int] = 500

    target_type: ShortLinkTarget


class ShortLinkRevoked(ServerEvent):
    """The user revoked one of their heygaia.links."""

    event: ClassVar[str] = "short_link:revoked"
    budget_per_user_day: ClassVar[int] = 50
