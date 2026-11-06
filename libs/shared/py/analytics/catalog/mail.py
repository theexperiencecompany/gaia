"""Email events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "EmailComposeOpened",
    "EmailOpened",
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


class EmailOpened(WebEvent):
    """A user opened an email in the mail view."""

    event: ClassVar[str] = "email:opened"
    budget_per_user_day: ClassVar[int] = 50

    mail_id: Identifier


class EmailComposeOpened(WebEvent):
    """A user opened the compose modal; the server only sees the eventual send."""

    event: ClassVar[str] = "email:compose_opened"
    budget_per_user_day: ClassVar[int] = 50
