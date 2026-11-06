"""Email events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent

__all__ = [
    "EmailReplied",
    "EmailSent",
]


class EmailSent(ServerEvent):
    """A user sent a new email or a saved draft."""

    event: ClassVar[str] = "email:sent"
    budget_per_user_day: ClassVar[int] = 50

    has_attachments: bool | None = None
    attachment_count: int | None = None


class EmailReplied(ServerEvent):
    """A user sent an email into an existing thread."""

    event: ClassVar[str] = "email:replied"
    budget_per_user_day: ClassVar[int] = 50

    has_attachments: bool
    attachment_count: int
