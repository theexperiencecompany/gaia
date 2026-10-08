"""Email events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class EmailSent(ServerEvent):
    """A user sent a new email or a saved draft."""

    event: ClassVar[str] = "email:sent"
    budget_per_user_day: ClassVar[int] = 50

    has_attachments: bool | None = None
    attachment_count: int | None = None
    recipient_count: int | None = None


class EmailReplied(ServerEvent):
    """A user sent an email into an existing thread."""

    event: ClassVar[str] = "email:replied"
    budget_per_user_day: ClassVar[int] = 50

    has_attachments: bool
    attachment_count: int


class EmailDraftComposed(ServerEvent):
    """The assistant finished composing a draft; not the web's email:compose_opened modal open."""

    event: ClassVar[str] = "email:draft_composed"
    budget_per_user_day: ClassVar[int] = 50


class EmailMarkedRead(ServerEvent):
    """A user marked messages as read."""

    event: ClassVar[str] = "email:marked_read"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailMarkedUnread(ServerEvent):
    """A user marked messages as unread."""

    event: ClassVar[str] = "email:marked_unread"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailStarred(ServerEvent):
    """A user starred messages."""

    event: ClassVar[str] = "email:starred"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailUnstarred(ServerEvent):
    """A user unstarred messages."""

    event: ClassVar[str] = "email:unstarred"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailTrashed(ServerEvent):
    """A user moved messages to the trash."""

    event: ClassVar[str] = "email:trashed"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailUntrashed(ServerEvent):
    """A user restored messages from the trash."""

    event: ClassVar[str] = "email:untrashed"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailArchived(ServerEvent):
    """A user archived messages."""

    event: ClassVar[str] = "email:archived"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailMovedToInbox(ServerEvent):
    """A user moved messages back to the inbox."""

    event: ClassVar[str] = "email:moved_to_inbox"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailLabelCreated(ServerEvent):
    """A user created a mail label."""

    event: ClassVar[str] = "email:label_created"
    budget_per_user_day: ClassVar[int] = 50


class EmailLabelUpdated(ServerEvent):
    """A user updated a mail label."""

    event: ClassVar[str] = "email:label_updated"
    budget_per_user_day: ClassVar[int] = 50


class EmailLabelDeleted(ServerEvent):
    """A user deleted a mail label."""

    event: ClassVar[str] = "email:label_deleted"
    budget_per_user_day: ClassVar[int] = 50


class EmailLabelApplied(ServerEvent):
    """A user applied a label to messages."""

    event: ClassVar[str] = "email:label_applied"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailLabelRemoved(ServerEvent):
    """A user removed a label from messages."""

    event: ClassVar[str] = "email:label_removed"
    budget_per_user_day: ClassVar[int] = 50

    message_count: int


class EmailDraftCreated(ServerEvent):
    """A user saved a new draft."""

    event: ClassVar[str] = "email:draft_created"
    budget_per_user_day: ClassVar[int] = 50


class EmailDraftUpdated(ServerEvent):
    """A user updated a draft."""

    event: ClassVar[str] = "email:draft_updated"
    budget_per_user_day: ClassVar[int] = 50


class EmailDraftDeleted(ServerEvent):
    """A user deleted a draft."""

    event: ClassVar[str] = "email:draft_deleted"
    budget_per_user_day: ClassVar[int] = 50


class EmailOpened(WebEvent):
    """A user opened an email in the mail view."""

    event: ClassVar[str] = "email:opened"
    budget_per_user_day: ClassVar[int] = 50

    mail_id: Identifier


class EmailComposeOpened(WebEvent):
    """A user opened the compose modal; the server only sees the eventual send."""

    event: ClassVar[str] = "email:compose_opened"
    budget_per_user_day: ClassVar[int] = 50


__all__ = [
    "EmailArchived",
    "EmailComposeOpened",
    "EmailDraftComposed",
    "EmailDraftCreated",
    "EmailDraftDeleted",
    "EmailDraftUpdated",
    "EmailLabelApplied",
    "EmailLabelCreated",
    "EmailLabelDeleted",
    "EmailLabelRemoved",
    "EmailLabelUpdated",
    "EmailMarkedRead",
    "EmailMarkedUnread",
    "EmailMovedToInbox",
    "EmailOpened",
    "EmailReplied",
    "EmailSent",
    "EmailStarred",
    "EmailTrashed",
    "EmailUnstarred",
    "EmailUntrashed",
]
